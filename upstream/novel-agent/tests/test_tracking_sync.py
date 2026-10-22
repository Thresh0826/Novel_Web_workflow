import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, create_autospec

from src.agents import tracking_sync as sync
from src.storage import workbench_store as store


class TrackingSyncTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'book'
        (self.root / '正文').mkdir(parents=True)
        (self.root / '正文/第001章.md').write_text('他把钥匙放在桌面上。', encoding='utf-8')
        self.book = {'root': self.root, 'manuscript': '正文', 'title': '测试书'}
        env = patch.dict(os.environ, NOVEL_WORKBENCH_DATA=str(Path(self.temp.name) / 'data'))
        env.start()
        self.addCleanup(env.stop)
        self.tool = sync.tracker()
        self.context = {'position': {'volume': '第一卷', 'volume_start_chapter': 1,
                                    'story_time': '当日', 'scene': '屋内'},
                        'long_term_constraints': [], 'active_character_names': [], 'continuity_risks': []}
        self.tool.initialize(self.root, {'schema_version': 1, 'book_title': '测试书',
                                        'last_chapter': 1, 'context': self.context})

    def run_sync(self, agent):
        run = store.create_run('test', 0, {'kind': 'tracking_sync'})
        sync.sync_book(run, self.book, agent)
        return store.get_run(run)

    def test_noop_never_calls_model(self):
        before = sync.fingerprint(self.root)
        result = self.run_sync(lambda *args, **kwargs: self.fail('不应调用模型'))
        self.assertEqual(result['status'], 'completed', result['message'])
        self.assertEqual(before, sync.fingerprint(self.root))

    def test_unlisted_body_is_excluded(self):
        (self.root / '正文/阅读入口.md').write_text('[正文](第001章.md)', encoding='utf-8')
        (self.root / '正文/第002章.md').write_text('未确认稿', encoding='utf-8')
        chapters, excluded = sync.sources(self.book)
        self.assertEqual(list(chapters), [1])
        self.assertEqual(excluded, ['第002章.md'])

    def test_append_uses_official_transaction(self):
        path = self.root / '正文/第002章.md'
        path.write_text('他把钥匙放在桌面上。', encoding='utf-8')
        tx = {'schema_version': 1, 'mode': 'append', 'chapter': 2, 'chapter_title': '钥匙',
              'expected_state_revision': 0, 'delta': {'result': '钥匙放在桌上'},
              'context': self.context, 'character_snapshots': {}}
        agent = create_autospec(sync.run_agent, return_value=json.dumps({'transaction': tx, 'evidence': ['他把钥匙放在桌面上']}))
        result = self.run_sync(agent)
        self.assertEqual(result['status'], 'completed', result['message'])
        self.assertEqual(agent.call_args.kwargs['cwd'], self.root)
        self.assertEqual(self.tool.check_project(self.root)['last_committed_chapter'], 2)
        self.assertEqual(path.read_text(encoding='utf-8'), '他把钥匙放在桌面上。')

    def test_concurrent_edit_stops_writeback(self):
        (self.root / '追踪/上下文.md').write_text('损坏的派生视图', encoding='utf-8')
        original = (self.root / '追踪/_tracking-state.json').read_bytes()
        def agent(*args, **kwargs):
            (self.root / '正文/第001章.md').write_text('作者正在改稿', encoding='utf-8')
            return json.dumps({'transaction': {'schema_version': 1, 'mode': 'revision', 'chapter': 1,
                'chapter_title': '钥匙', 'expected_state_revision': 0,
                'delta': {'result': '钥匙放在桌上'}, 'context': self.context},
                'evidence': ['他把钥匙放在桌面上']})
        result = self.run_sync(agent)
        self.assertEqual(result['status'], 'blocked')
        self.assertIn('发生变化', result['message'])
        self.assertEqual(original, (self.root / '追踪/_tracking-state.json').read_bytes())

    def test_migration_preserves_original(self):
        state = {'wordcount_records': {'1': {'actual': 20, 'author_range': {'min': 10, 'max': 30}}}}
        old = sync.migrate(state)
        self.assertEqual(old['1']['author_range'], {'min': 10, 'max': 30})
        self.assertNotIn('author_range', state['wordcount_records']['1'])

    def test_write_failure_restores_tracking(self):
        (self.root / '正文/第002章.md').write_text('他把钥匙放在桌面上。', encoding='utf-8')
        before = sync.fingerprint(self.root)
        tx = {'schema_version': 1, 'mode': 'append', 'chapter': 2, 'chapter_title': '钥匙',
              'expected_state_revision': 0, 'delta': {'result': '钥匙放在桌上'}, 'context': self.context}
        replace = os.replace
        def fail_state(source, target):
            if Path(target) == self.root / '追踪/_tracking-state.json':
                raise OSError('模拟磁盘写入失败')
            return replace(source, target)
        with patch.object(sync.os, 'replace', side_effect=fail_state):
            result = self.run_sync(lambda *args, **kwargs: json.dumps({'transaction': tx, 'evidence': ['他把钥匙放在桌面上']}))
        self.assertEqual(result['status'], 'blocked')
        self.assertEqual(before, sync.fingerprint(self.root))

