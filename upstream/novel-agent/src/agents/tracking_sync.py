"""Synchronize confirmed manuscripts through the project's tracking transaction tool."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from urllib.parse import unquote

from .local_cli import run_agent
from ..storage import workbench_store as store

SKILL = Path.home() / '.agents/skills/story-long-write'


def tracker():
    spec = importlib.util.spec_from_file_location('workbench_tracking_tool', SKILL / 'scripts/tracking_commit.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fingerprint(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*') if p.is_file() and p.suffix in {'.md', '.json'}
            and not any(part.startswith('.') for part in p.relative_to(root).parts)}


def sources(book):
    from ..api.local_workbench import chapter_number
    root = book['root'].resolve()
    directory = root / book['manuscript']
    entry = directory / '阅读入口.md'
    candidates = [p.resolve() for p in directory.glob('*.md') if chapter_number(p)]
    selected = candidates
    if entry.exists():
        selected = []
        for link in re.findall(r'\]\(([^)]+\.md)\)', entry.read_text(encoding='utf-8-sig')):
            path = (entry.parent / unquote(link)).resolve()
            if not path.is_relative_to(root):
                raise ValueError('阅读入口含越界路径，停止同步')
            if not path.is_relative_to(directory.resolve()):
                continue
            if chapter_number(path):
                if not path.is_file():
                    raise ValueError(f'阅读入口正文不存在：{path.name}')
                selected.append(path)
    chapters = {}
    for path in set(selected):
        number = chapter_number(path)
        if number in chapters:
            raise ValueError(f'第{number}章存在多个有效版本')
        chapters[number] = path
    if not chapters or set(chapters) != set(range(1, max(chapters) + 1)):
        raise ValueError('有效正文缺章，不能连续同步')
    return chapters, [p.name for p in candidates if p not in selected]


def plan(book):
    chapters, excluded = sources(book)
    state = json.loads((book['root'] / '追踪/_tracking-state.json').read_text(encoding='utf-8-sig'))
    last = state['last_committed_chapter']
    if last > max(chapters):
        raise ValueError('追踪进度超过有效正文，需先核对阅读入口')
    try:
        tracker().check_project(book['root'])
        error = ''
    except Exception as exc:
        error = str(exc)
    return {'title': book['title'], 'tracked': last, 'confirmed': max(chapters),
            'pending': list(range(last + 1, max(chapters) + 1)), 'excluded': excluded,
            'validation_error': error}


def migrate(state):
    """Only migrate the known old author_range field; retain it in the audit log."""
    changes = {}
    for number, record in state.get('wordcount_records', {}).items():
        if 'author_range' in record:
            changes[number] = dict(record)
            del record['author_range']
    return changes


def parse_json(output):
    output = output.strip()
    if output.startswith('```'):
        output = re.sub(r'^```(?:json)?\s*|\s*```$', '', output)
    return json.loads(output)


def sync_book(run_id, book, agent=run_agent):
    root = book['root'].resolve()
    audit = store.data_directory() / 'runs' / run_id
    audit.mkdir(parents=True, exist_ok=True)
    try:
        tool = tracker()
        before = fingerprint(root)
        chapters, excluded = sources(book)
        summary = plan(book)
        tool_text = (SKILL / 'references/tracking-transaction.md').read_text(encoding='utf-8-sig')
        rules = '\n'.join(p.read_text(encoding='utf-8-sig') for p in
                          [root.parent / 'AGENTS.md', root / 'AGENTS.md'] if p.is_file())
        manifest_path = store.data_directory() / ('tracking-sync-' + hashlib.sha256(str(root).encode()).hexdigest()[:16] + '.json')
        source_hashes = {str(n): hashlib.sha256(p.read_bytes()).hexdigest() for n, p in chapters.items()}
        if manifest_path.exists():
            previous = json.loads(manifest_path.read_text(encoding='utf-8'))
            changed = [n for n, digest in previous.get('chapter_hashes', {}).items() if source_hashes.get(n) != digest]
            if changed:
                raise ValueError('已同步正文有修订，需先核对历史追踪，停止自动覆盖：第' + '、'.join(changed) + '章')
        with tempfile.TemporaryDirectory(prefix='novel-tracking-') as tmp:
            stage = Path(tmp)
            shutil.copytree(root / '追踪', stage / '追踪')
            state_path = stage / '追踪/_tracking-state.json'
            state = json.loads(state_path.read_text(encoding='utf-8-sig'))
            migration = migrate(state)
            (audit / 'migration-original.json').write_text(json.dumps(migration, ensure_ascii=False, indent=2), encoding='utf-8')
            tool.normalize_state(state)
            if migration:
                state_path.write_text(json.dumps(state, ensure_ascii=False), encoding='utf-8')
            work = summary['pending'][:]
            # Rebuild inconsistent derived views by revising the latest committed chapter.
            try:
                tool.check_project(stage)
                needs_revision = False
            except Exception:
                needs_revision = True
            if needs_revision and state['last_committed_chapter']:
                work.insert(0, state['last_committed_chapter'])
            for number in work:
                state = tool.load_state(stage)
                mode = 'append' if number > state['last_committed_chapter'] else 'revision'
                store.update_run(run_id, status='running', step=f'同步第{number}章',
                                 message=f"{book['title']}：逐章核对正文事实，暂未写入原目录")
                body = chapters[number].read_text(encoding='utf-8-sig')
                prompt = (f'你是小说追踪同步员，只读输入，禁止操作文件。只输出JSON对象，包含transaction和evidence。'
                          f'evidence为本章逐字原文引用的非空字符串数组。不得用大纲或推测补事实。'
                          f'按下述协议生成第{number}章完整事务，mode={mode}，expected_state_revision={state["state_revision"]}。'
                          '只同步上下文、人物、伏笔、时间线，不写正文，不附wordcount。保留既有ID和仍有效约束。'
                          'revision时保留截至最新已提交章的当前人物状态，不能退回旧章。'
                          f'\n协议：\n{tool_text}\n项目规则：\n{rules}\n当前权威状态：\n'
                          f'{json.dumps(state, ensure_ascii=False)}\n本章文件：{chapters[number].name}\n正文：\n{body}')
                if mode == 'revision':
                    prompt += '\n后续已提交正文：\n' + '\n'.join(chapters[n].read_text(encoding='utf-8-sig')
                        for n in range(number + 1, state['last_committed_chapter'] + 1))
                error = ''
                for attempt in range(2):
                    try:
                        answer = parse_json(agent('codex', prompt + '\n上次校验错误：' + error, cwd=root))
                        evidence = answer['evidence']
                        if not isinstance(evidence, list) or not evidence or not all(isinstance(q, str) and len(q) >= 6 and q in body for q in evidence):
                            raise ValueError('证据引用必须逐字出现在本章正文')
                        tx = answer['transaction']
                        if tx.get('chapter') != number or tx.get('mode') != mode or 'wordcount' in tx:
                            raise ValueError('事务章节或模式不符，或包含未授权字数记录')
                        tool.normalize_transaction(stage, state, tx)
                        break
                    except (ValueError, KeyError, TypeError) as exc:
                        error = str(exc)
                else:
                    raise ValueError(f'第{number}章事务校验失败：{error}')
                (audit / f'sync-{number:03d}.json').write_text(json.dumps(answer, ensure_ascii=False, indent=2), encoding='utf-8')
                tool.apply_transaction(stage, tx)
            tool.check_project(stage)
            with tool.project_write_lock(root):
                if fingerprint(root) != before:
                    raise ValueError('同步期间书稿或追踪发生变化，已停止，未覆盖原文件')
                backup = audit / 'backup/追踪'
                shutil.copytree(root / '追踪', backup, ignore=shutil.ignore_patterns('.tracking-commit.lock'))
                outputs = {p.relative_to(stage / '追踪'): p.read_bytes() for p in (stage / '追踪').rglob('*')
                           if p.is_file() and p.name != '.tracking-commit.lock'}
                written = []
                try:
                    for relative in sorted(outputs, key=lambda p: (p.name == '_tracking-state.json', str(p))):
                        target = root / '追踪' / relative
                        if target.exists() and target.read_bytes() == outputs[relative]:
                            continue
                        target.parent.mkdir(parents=True, exist_ok=True)
                        temp = target.with_name(target.name + f'.{run_id}.tmp')
                        temp.write_bytes(outputs[relative])
                        os.replace(temp, target)
                        written.append(relative)
                    for target in (root / '追踪/角色状态').glob('*.md'):
                        relative = target.relative_to(root / '追踪')
                        if relative not in outputs:
                            target.unlink()
                            written.append(relative)
                    tool.check_project(root)
                except Exception:
                    for relative in reversed(written):
                        target = root / '追踪' / relative
                        old = backup / relative
                        if old.exists():
                            target.write_bytes(old.read_bytes())
                        else:
                            target.unlink(missing_ok=True)
                    raise
            report = {'before': summary, 'migration_original_records': migration,
                      'confirmed_chapter': max(chapters), 'excluded': excluded,
                      'backup': str(backup), 'changed_files': [str(p) for p in written]}
            (audit / 'sync-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
            manifest_path.write_text(json.dumps({'chapter_hashes': source_hashes, 'report': report}, ensure_ascii=False), encoding='utf-8')
            store.update_run(run_id, status='completed', step='同步完成',
                             message=f"已同步至第{max(chapters)}章；原始追踪已备份，正文和细纲未修改。", result=report)
    except Exception as exc:
        detail = str(exc)
        (audit / 'sync-error.json').write_text(json.dumps({'error': detail}, ensure_ascii=False, indent=2), encoding='utf-8')
        if 'workspace routing discovery failed' in detail:
            detail = '本机 Codex CLI 无法连接模型服务（工作区路由发现失败），未完成本书同步；错误详情已保存，原追踪未被本次写回覆盖。'
        store.update_run(run_id, status='blocked', step='同步停止', message=detail)
