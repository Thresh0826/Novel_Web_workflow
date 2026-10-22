import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, create_autospec

from fastapi.testclient import TestClient
from src.agents import workflow
from src.agents.local_cli import run_agent
from src.api import local_workbench as wb
from src.local_preview import app
from src.storage import workbench_store as store


def report(verdict='PASS', text='已核对本章因果、人物连续性与本书规则，未发现实质问题。'):
    return json.dumps({'verdict':verdict,'report':text,'revision_brief':'保持停点，修正人物已知信息。'}, ensure_ascii=False)


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)/'book';self.root.mkdir()
        (self.root/'大纲').mkdir();(self.root/'正文').mkdir()
        self.outline=self.root/'大纲/细纲_第001章.md'
        self.outline.write_text('# 本章细纲\n主角发现钥匙。',encoding='utf-8')
        self.book={'root':self.root,'title':'测试书','manuscript':'正文','outlines':['大纲']}
        self.environment=patch.dict(os.environ,NOVEL_WORKBENCH_DATA=str(Path(temp.name)/'data'))
        self.environment.start();self.addCleanup(self.environment.stop)
        p=patch.dict(wb.BOOKS,{'test':self.book},clear=True);p.start();self.addCleanup(p.stop)
        p=patch.object(wb,'build_packet',side_effect=lambda *a,**kw:{'text':'本书规则和当前候选稿，禁止新增人物。'})
        p.start();self.addCleanup(p.stop)
        p=patch.object(workflow.legacy,'_long_write_context',return_value='写作门禁')
        p.start();self.addCleanup(p.stop)

    def execute(self,outputs,mode='outline',max_revisions=3,**kwargs):
        agent=create_autospec(run_agent,side_effect=outputs)
        run=store.create_run('test',1,{'mode':mode})
        with patch.object(workflow,'cli_agent',agent):
            workflow.run_automatic(run,'test',self.book,1,mode=mode,max_revisions=max_revisions,**kwargs)
        return store.get_run(run),agent

    def test_outline_only_repairs_and_never_writes_body(self):
        original=self.outline.read_bytes()
        run,agent=self.execute([report('REVISE','细纲第三段让主角知道尚未揭示的秘密。'),'# 修改细纲\n主角只知道眼前的钥匙。',report(),report()])
        self.assertEqual(run['status'],'completed',run['message'])
        self.assertEqual([c.args[0] for c in agent.call_args_list],['codex','gemini','codex','codex'])
        self.assertFalse(run['result'].get('draft_file'))
        self.assertEqual(run['result']['progress'],100)
        self.assertEqual(original,self.outline.read_bytes())
        self.assertEqual(list((self.root/'正文').glob('*')),[])

    def test_full_writing_has_body_and_model_overrides(self):
        run,agent=self.execute([report(),'# 第一章\n他发现钥匙。',report(),report()],mode='full',codex_model='author-codex',gemini_model='author-gemini')
        self.assertEqual(run['status'],'completed',run['message'])
        self.assertEqual(len(run['result']['phases']),6)
        self.assertTrue(Path(run['result']['draft_file']).exists())
        self.assertEqual(agent.call_args_list[0].kwargs['model'],'author-codex')
        self.assertEqual(agent.call_args_list[1].kwargs['model'],'author-gemini')
        self.assertIn('不能查阅之前的审查报告',agent.call_args_list[-1].args[1])

    def test_revision_limit_preserves_actual_reason_and_every_report(self):
        run,agent=self.execute([report('REVISE','第一处：人物不应提前知道钥匙位置。'),'# 修订细纲',report('REVISE','仍未解决：第三段直接说出未揭示的密室位置。')],max_revisions=1)
        self.assertEqual(run['status'],'blocked')
        self.assertIn('未揭示的密室位置',run['message'])
        self.assertIn('已修改 1 次',run['message'])
        self.assertEqual(len(run['result']['reviews']),2)
        self.assertTrue(Path(run['result']['outline_file']).exists())

    def test_author_conflict_stops_before_gemini(self):
        run,agent=self.execute([report('BLOCKED','人物身份有两个互相冲突的作者设定，需要裁定。')])
        self.assertEqual(run['status'],'blocked')
        self.assertEqual(agent.call_count,1)
        self.assertIn('两个互相冲突',run['message'])

    def test_markdown_is_rendered_and_active_content_escaped(self):
        with TestClient(app) as client:
            response=client.post('/api/local/markdown',json={'text':'# 标题\n\n**正文**\n\n<script>alert(1)</script>\n\n[跳转](javascript:alert(1))'})
        self.assertEqual(response.status_code,200)
        html=response.json()['html']
        self.assertIn('<h1>标题</h1>',html)
        self.assertIn('<strong>正文</strong>',html)
        self.assertNotIn('<script>',html)
        self.assertNotIn('href="javascript:',html)

    def test_request_rejects_unbounded_revisions_and_bad_mode(self):
        with TestClient(app) as client:
            self.assertEqual(client.post('/api/local/books/test/run',json={'chapter':1,'mode':'anything'}).status_code,422)
            self.assertEqual(client.post('/api/local/books/test/run',json={'chapter':1,'max_revisions':100}).status_code,422)
