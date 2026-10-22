"""Explicit outline-only and full-writing workflows, with durable review evidence."""
import json
from pathlib import Path
from . import automation as legacy
from .local_cli import run_agent as cli_agent
from ..storage import workbench_store as store

FULL = ['审阅细纲', '修改细纲', '写正文', '审阅正文', '修改正文', '最终正文审阅']
OUTLINE = ['审阅细纲', '修改细纲', '最终细纲审阅']
FINAL_RULES = '''你是最后一轮复核人。使用全新 Codex CLI 会话，不能查阅之前的审查报告。
这不是专用 skill 或子 agent。按本次输入中的本书审查 skill 和项目规则，独立完整审阅当前候选稿。
细纲复核只检查因果、正文承接、人物知识边界、金手指和内容容量，不写正文，不锁死表达。
正文复核检查既定事件落实、人物连续性、文风、信息空转和改稿损伤。
只报告有材料证据、影响本书阅读或连续性的问题；不要以偏好挑错，不推翻作者明确的题材尺度。
每个问题写清原文位置、证据、影响、最小修改方向和验收条件。信息不足则说明缺什么。
PASS 必须有检查范围及结论；REVISE 必须有明确修改项；BLOCKED 必须指出需要作者决定的冲突。'''


class ReviewStopped(Exception):
    pass


def run_automatic(run_id, book_id, book, chapter, *, confirm_versions=False, mode='full', max_revisions=3, codex_model=None, gemini_model=None):
    from ..api import local_workbench as wb
    directory = store.data_directory() / 'runs' / run_id
    directory.mkdir(parents=True, exist_ok=True)
    schema = directory / 'review-schema.json'
    legacy._write_text(schema, json.dumps(legacy.REVIEW_SCHEMA))
    phases = OUTLINE if mode == 'outline' else FULL
    reviews, events, done = [], [], set()
    current = 0
    def run_agent(provider, prompt, **kwargs):
        model = codex_model if provider == 'codex' else gemini_model
        if model: kwargs['model'] = model
        return cli_agent(provider, prompt, **kwargs)
    outline_file = directory / f'第{chapter:03d}章_细纲.md'
    draft_file = directory / f'第{chapter:03d}章_正文.md'

    def progress(index, message, status='running', **extra):
        nonlocal current
        current = index
        events.append({'at': store.now(), 'stage': phases[index], 'message': message})
        result = {'mode': mode, 'phases': [{'name': p, 'state': 'done' if i in done else 'active' if i == index else 'pending'} for i,p in enumerate(phases)],
                  'progress': round(len(done) / len(phases) * 100), 'progress_note': '按已完成步骤计算，非模型生成速度',
                  'reviews': reviews, 'steps': reviews, 'events': events, 'stage_started_at': store.now(),
                  'review_method': 'Codex 全新 CLI 会话 + 本书审查 skill + 工作台内置复核规则；未部署专用终审 skill 或子 agent', **extra}
        for key, path in [('outline_file', outline_file), ('draft_file', draft_file)]:
            if path.exists(): result[key] = str(path)
        store.update_run(run_id, status=status, step=phases[index], message=message, result=result)

    def review(label, packet, final=False):
        prompt = legacy._report_prompt(label, packet['text'], independent=final)
        if final: prompt = FINAL_RULES + '\n\n' + prompt
        raw = run_agent('codex', prompt, cwd=directory, schema_path=schema)
        legacy._write_text(directory / f'审查原始输出_{len(reviews)+1}.txt', raw)
        data = json.loads(raw.strip().removeprefix('```json').removesuffix('```').strip())
        if data.get('verdict') not in {'PASS','REVISE','BLOCKED'} or not isinstance(data.get('report'), str) or not data['report'].strip():
            raise RuntimeError('模型返回的审查结论或报告无效，原始输出已保留。')
        row = {'stage': label, 'reviewer': 'Codex（新会话）' if final else 'Codex', **data}
        reviews.append(row)
        legacy._write_text(directory / f'审查报告_{len(reviews)}.json', json.dumps(row, ensure_ascii=False, indent=2))
        progress(current, f'{label}：' + {'PASS':'通过','REVISE':'发现待修改问题','BLOCKED':'需要作者裁定'}[data['verdict']])
        return data

    def stop(label, result, why):
        raise ReviewStopped(f"{label}：{why}\n\n尚未解决的问题：\n{result['report']}\n\n修改建议：\n{result.get('revision_brief') or '请按上方逐项问题核对。'}")

    try:
        row = next((r for r in wb.index(book) if r['number'] == chapter), None)
        if not row or not row.get('outline'):
            raise RuntimeError('此流程需要本章已有唯一有效细纲，请先准备细纲。')
        source = wb.safe_file(book['root'], row['outline'][0])
        outline = wb.read(source)
        legacy._write_text(outline_file, outline)
        req = wb.PacketRequest(chapter=chapter, stage='outline', confirm_versions=confirm_versions)

        def outline_packet():
            return wb.build_packet(book_id, req, outline_override=(outline_file, outline))

        def revise_outline(result, count):
            nonlocal outline
            progress(1, f'Gemini 正在修改细纲，第 {count}/{max_revisions} 次。依据：{result.get("revision_brief") or result["report"]}')
            outline = run_agent('gemini', '只输出修改后的完整细纲 Markdown。保留作者锁定的事件、胜负、章序与停点，不新增设定或写正文。\n'
                                + outline_packet()['text'] + '\n审查报告：\n' + result['report'] + '\n修改要点：\n' + result.get('revision_brief',''), cwd=directory).strip()
            if not outline: raise RuntimeError('Gemini 返回空细纲，保留之前的文件，停止执行。')
            legacy._write_text(outline_file, outline)

        progress(0, 'Codex 正在按本书审纲规则检查细纲。')
        result = review('细纲初审', outline_packet())
        count = 0
        while result['verdict'] != 'PASS':
            if result['verdict'] == 'BLOCKED': stop('细纲审查', result, '存在需要作者裁定的冲突')
            if count >= max_revisions: stop('细纲审查', result, f'已修改 {count} 次，仍有下列问题，停止继续消耗额度')
            count += 1
            done.add(0)
            revise_outline(result, count)
            result = review(f'细纲修改后复核 {count}', outline_packet())
        done.update([0,1])
        if mode == 'outline':
            while True:
                progress(2, 'Codex 新会话正在最终审阅细纲，仅处理细纲，不进入正文。')
                result = review('最终细纲审阅', outline_packet(), final=True)
                if result['verdict'] == 'PASS': break
                if result['verdict'] == 'BLOCKED' or count >= max_revisions:
                    stop('最终细纲审阅', result, f'需要处理以下问题；本次已修改 {count}/{max_revisions} 次')
                count += 1
                done.discard(1)
                revise_outline(result, count)
                done.add(1)
            done.add(2)
            progress(2, '细纲审阅与修改已完成，最终审阅通过。候选细纲已另存，未生成正文。', status='completed', final_verdict='PASS', final_report=result['report'])
            return

        if row.get('draft'):
            progress(2, '检测到已有正文，读取原稿作为候选稿，不重新生成覆盖原稿。')
            draft = wb.read(wb.safe_file(book['root'], row['draft'][0]))
        else:
            progress(2, 'Gemini 正在按通过审查的细纲创作正文。')
            packet = wb.build_packet(book_id, wb.PacketRequest(chapter=chapter, stage='draft', confirm_versions=confirm_versions), outline_override=(outline_file, outline))
            draft = run_agent('gemini', '只输出本章完整正文 Markdown。严格依据细纲和本书文风，不改其它文件。\n' + packet['text'] + legacy._long_write_context('draft'), cwd=directory).strip()
        if not draft: raise RuntimeError('正文为空，停止后续步骤。')
        legacy._write_text(draft_file, draft)
        done.add(2)
        count = 0
        final = False
        while True:
            index = 5 if final else 3
            progress(index, 'Codex 新会话正在最终审阅正文。' if final else 'Codex 正在审阅正文，核对细纲、设定与前文。')
            packet = wb.build_packet(book_id, wb.PacketRequest(chapter=chapter, stage='final' if final else 'review', confirm_versions=confirm_versions),
                                     draft_override=(draft_file, draft), outline_override=(outline_file, outline))
            result = review('最终正文审阅' if final else f'正文审查 {count+1}', packet, final=final)
            if result['verdict'] == 'PASS':
                if final: break
                done.update([3,4]); final = True; continue
            if result['verdict'] == 'BLOCKED' or count >= max_revisions:
                stop('最终正文审阅' if final else '正文审查', result, f'需要处理以下问题；本次已修改 {count}/{max_revisions} 次')
            count += 1
            done.discard(4)
            progress(4, f'Gemini 正在修改正文，第 {count}/{max_revisions} 次。依据：{result.get("revision_brief") or result["report"]}')
            draft = run_agent('gemini', '按报告最小修改，只输出完整正文 Markdown。保留已成立的剧情、文风和作者约束。\n' + packet['text'] + '\n审查报告：\n' + result['report'] + '\n修改要点：\n' + result.get('revision_brief',''), cwd=directory).strip()
            if not draft: raise RuntimeError('返修正文为空，原候选文件未覆盖。')
            legacy._write_text(draft_file, draft)
            final = False
        done.update(range(6))
        progress(5, '全面写作流程完成，最终审阅通过。候选稿另存，请查看报告后采用；原正文和细纲未覆盖。',
                 status='completed', final_verdict='PASS', final_report=result['report'])
    except Exception as exc:
        progress(current, str(exc), status='blocked', pause_reason=str(exc), stopped_at=phases[current])
