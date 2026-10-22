"""Read-only book adapters and persistent, explicitly manual review handoffs."""

import hashlib
import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from difflib import unified_diff
from pathlib import Path
from typing import Literal
from urllib.parse import unquote

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from ..storage import workbench_store as store

router = APIRouter()
RUN_POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix="novel-run")
RUN_LOCK = threading.Lock()
SKILLS = Path.home() / ".codex" / "skills"
STORY_SKILLS = Path.home() / ".agents" / "skills"
def load_books():
    import os
    path = Path(os.environ.get('NOVEL_WORKBENCH_BOOKS', Path(__file__).parents[4] / 'books.local.json'))
    if not path.is_file():
        return {}
    configured = json.loads(path.read_text(encoding='utf-8-sig'))
    for book in configured.values():
        book['root'] = Path(book['root'])
    return configured


BOOKS = load_books()

STAGES = {"outline": "细纲审查", "draft": "正文创作", "review": "正文审查", "final": "独立终审"}


@router.get('/api/local/tracking-sync')
def tracking_sync_status():
    from ..agents.tracking_sync import plan
    result = []
    for book_id, book in BOOKS.items():
        try:
            item = plan(book)
        except Exception as exc:
            item = {'title': book['title'], 'error': str(exc)}
        runs = [r for r in store.runs_for(book_id) if r['result'].get('options', {}).get('kind') == 'tracking_sync']
        result.append({'book_id': book_id, **item, 'latest_run': runs[0] if runs else None})
    return result


@router.post('/api/local/tracking-sync')
def start_tracking_sync(request: Request, background: BackgroundTasks):
    same_origin(request)
    from ..agents.tracking_sync import sync_book
    with RUN_LOCK:
        existing = [r for book_id in BOOKS for r in store.runs_for(book_id)
                    if r['result'].get('options', {}).get('kind') == 'tracking_sync'
                    and r['status'] in {'queued', 'running'}]
        if existing:
            return {'runs': existing}
        runs = []
        for book_id, book in BOOKS.items():
            run_id = store.create_run(book_id, 0, {'kind': 'tracking_sync'})
            runs.append(store.get_run(run_id))
            background.add_task(RUN_POOL.submit, sync_book, run_id, book)
    return {'runs': runs}

INSTRUCTIONS = {
    "outline": "只读审查本章细纲。核验必要因果、金手指、人物连续性和内容容量，保留非关键对白与动作的创作空间。输出有原文证据、最小修改方向和验收条件的报告，不擅自改纲。",
    "draft": "依据本章细纲创作正文。先核对承接与资料，保持行动主体、必要因果、关键选择、结果和停笔点；执行本书文风与验收规则。正文在原有写作环境中保存，本工作台不写入书稿。",
    "review": "只读审查本章正文。对照细纲、有效前文、机制和本书专属审查规则，输出有证据的确定问题、待作者裁定项及最小修改方向。不擅自改正文或设定，不强加题材不需要的现实限制。",
    "final": "先独立完整通读，不参考前轮评价。判断阅读流畅度、人物可信度、内容空转、爽点兑现和修改造成的损伤。遵守本书金手指与审查尺度。先完成独立报告；报告保存后，再回看前轮报告进行问题核对。不要为了挑错而凑数，不把个人偏好当硬伤。",
}


def book_by_id(book_id):
    if book_id not in BOOKS:
        raise HTTPException(404, "书籍不存在")
    return BOOKS[book_id]


def read(path):
    return path.read_text(encoding="utf-8-sig")


def safe_file(root, relative):
    root = root.resolve()
    target = (root / relative).resolve()
    if not target.is_relative_to(root) or target.suffix.lower() != ".md" or not target.is_file():
        raise HTTPException(404, "文件不在本书有效范围内")
    return target


def chapter_number(path):
    match = re.search(r"第([0-9]+|[一二三四五六七八九十百零〇两]+)章", path.stem)
    if not match:
        return None
    value = match.group(1)
    if value.isdigit():
        return int(value)
    digits = dict(zip("零一二三四五六七八九", range(10))) | {"〇": 0, "两": 2}
    total = current = 0
    for char in value:
        if char in "十百":
            total += (current or 1) * {"十": 10, "百": 100}[char]
            current = 0
        else:
            current = digits[char]
    return total + current


def index(book):
    rows = {}
    root = book["root"]
    entry = root / book["manuscript"] / "阅读入口.md"
    listed = set()
    if entry.is_file():
        for link in re.findall(r"\]\(([^)]+\.md)\)", read(entry)):
            linked = (entry.parent / unquote(link)).resolve()
            if linked.is_relative_to(root.resolve()):
                listed.add(linked)
    for kind, directories in [("draft", [book["manuscript"]]), ("outline", book["outlines"])]:
        for directory in directories:
            for path in sorted((root / directory).glob("*.md")):
                number = chapter_number(path)
                if number is None or (kind == "outline" and "细纲" not in path.name and directory != "章节细纲"):
                    continue
                row = rows.setdefault(number, {"number": number})
                row.setdefault(kind, []).append(path.relative_to(root).as_posix())
    for row in rows.values():
        row["source_warning"] = bool(entry.is_file() and any((root / p).resolve() not in listed for p in row.get("draft", [])))
        row["status"] = "版本待核对" if any(len(row.get(k, [])) > 1 for k in ["draft", "outline"]) else "入口未收录 · 待核对" if row["source_warning"] else "待正文审查" if row.get("draft") else "已有细纲"
    return sorted(rows.values(), key=lambda row: row["number"], reverse=True)


def changed_sources(payload):
    changes = []
    for item in payload["files"]:
        try:
            current = hashlib.sha256(Path(item["absolute_path"]).read_bytes()).hexdigest()
        except OSError:
            current = None
        if current != item["sha256"]:
            changes.append({"path": item["path"], "reason": "文件已变化" if current else "文件已移走或无法读取"})
    return changes


def task_view(record, include_payload=False):
    payload = json.loads(record["payload"])
    reports = store.reports_for(record["id"])
    approval = store.latest_approval(record["id"])
    latest = reports[0] if reports else None
    changes = changed_sources(payload)
    sources = payload.get("chapter_sources")
    if sources:
        current = next((row for row in index(book_by_id(record["book_id"])) if row["number"] == sources["chapter"]), {})
        if any(current.get(key, []) != sources[key] for key in ["draft", "outline"]):
            changes.append({"path": "当前章文件集合", "reason": "正文或细纲新增、移走或出现多个版本"})
    stale = bool(changes)
    approved = bool(approval and latest and approval["report_id"] == latest["id"] and latest["verdict"] == "pass" and not stale)
    status = "材料已变化 · 待复审" if stale else "作者已定稿" if approved else {
        "pass": "终审通过 · 待定稿" if record["stage"] == "final" else "本轮审查通过",
        "revise": "待修改", "blocked": "待作者裁定", "submitted": "创作结果已记录",
    }.get(latest["verdict"] if latest else "", "待执行 · 已生成材料")
    result = {k: v for k, v in record.items() if k != "payload"}
    result.update({"stage_label": STAGES[record["stage"]], "status": status, "stale": stale,
                   "changed_files": changes, "report_count": len(reports), "latest_report": latest,
                   "approved": approved, "approval": approval,
                   "can_approve": bool(record["stage"] == "final" and latest and latest["verdict"] == "pass" and not stale and not approved),
                   "file_count": len(payload["files"]), "chars": len(payload["text"])})
    if include_payload:
        result.update({"packet": payload, "reports": reports})
    return result


def require_task(task_id):
    record = store.get_task(task_id)
    if record is None:
        raise HTTPException(404, "任务不存在")
    book_by_id(record["book_id"])
    return record


def same_origin(request):
    origin = request.headers.get("origin")
    if origin and origin.rstrip("/") != str(request.base_url).rstrip("/"):
        raise HTTPException(403, "请从本地工作台提交操作")


@router.get("/workbench")
def page():
    return FileResponse(Path(__file__).parents[1] / "frontend" / "workbench.html", headers={"Cache-Control": "no-store"})


@router.get("/workbench.js")
def javascript():
    return FileResponse(Path(__file__).parents[1] / "frontend" / "workbench.js", headers={"Cache-Control": "no-store"})


@router.get("/api/local/books")
def books():
    result = []
    for key, book in BOOKS.items():
        tasks = [task_view(r) for r in store.task_records(key)]
        chapters = index(book)
        for row in chapters:
            chapter_tasks = [t for t in tasks if t["chapter"] == row["number"]]
            row["task_count"] = len(chapter_tasks)
            if chapter_tasks:
                row["status"] = chapter_tasks[0]["status"]
                row["stage"] = chapter_tasks[0]["stage_label"]
        result.append({"id": key, "title": book["title"], "genre": book["genre"], "root": str(book["root"]),
                       "focus": book["focus"], "chapters": chapters, "task_count": len(tasks),
                       "approved_count": sum(1 for row in chapters if row["status"] == "作者已定稿"),
                       "stale_count": sum(t["stale"] for t in tasks)})
    return result


@router.get("/api/local/books/{book_id}/document")
def document(book_id: str, path: str):
    book = book_by_id(book_id)
    target = safe_file(book["root"], path)
    from markdown_it import MarkdownIt
    content = read(target)
    return {"path": target.relative_to(book["root"].resolve()).as_posix(), "content": content,
            'html': MarkdownIt('commonmark', {'html':False, 'breaks':False}).enable('table').render(content)}


@router.get('/api/local/usage')
def usage_limits():
    from ..agents.usage import read_usage
    return read_usage()


@router.get('/api/local/models')
def model_settings():
    import tomllib
    import subprocess
    from ..agents.local_cli import executables, agent_environment
    codex = {'model':None, 'effort':None, 'source':'本机 Codex 配置；任务未指定时跟随 CLI'}
    try:
        config = tomllib.loads((Path.home()/'.codex/config.toml').read_text(encoding='utf-8-sig'))
        codex.update(model=config.get('model'), effort=config.get('model_reasoning_effort'))
    except (OSError, ValueError): pass
    models = []
    executable = executables()['gemini']
    if executable:
        try:
            response = subprocess.run([executable,'models'],capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=20,env=agent_environment(),creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            if response.returncode == 0:
                models = [{'id':parts[0], 'name':parts[1]} for line in response.stdout.splitlines() if len(parts:=line.split('\t',1)) == 2 and re.fullmatch(r'[A-Za-z0-9._:/-]+',parts[0])]
        except Exception: pass
    return {'codex':codex, 'gemini':{'model':None,'source':'Antigravity CLI 默认模型未被接口披露；可在本次任务显式指定', 'available_models':models}}


class MarkdownRequest(BaseModel):
    text: str = Field(max_length=1000000)


@router.post('/api/local/markdown')
def render_markdown(request: MarkdownRequest, http_request: Request):
    same_origin(http_request)
    from markdown_it import MarkdownIt
    return {'html': MarkdownIt('commonmark', {'html':False}).enable('table').render(request.text)}


@router.get("/api/local/books/{book_id}/materials")
def materials(book_id: str):
    book = book_by_id(book_id)
    root = book["root"]
    paths = []
    for folder in ["设定", "写作规范", "大纲"]:
        for path in sorted((root / folder).rglob("*.md")):
            if path.is_file() and path.resolve().is_relative_to(root.resolve()):
                relative = path.relative_to(root).as_posix()
                paths.append({"path": relative, "default": relative in book.get("core", [])})
    return {"files": paths, "skills": book.get("skills", {})}


@router.get("/api/local/agents")
def agents():
    import subprocess
    from ..agents.local_cli import executables
    available = executables()
    codex_ready = False
    codex_error = None
    if available["codex"]:
        try:
            result = subprocess.run([available["codex"], "login", "status"], capture_output=True, text=True, timeout=12,
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            codex_ready = result.returncode == 0 and "logged in" in ((result.stdout or "") + (result.stderr or "")).lower()
            if not codex_ready:
                codex_error = "Codex CLI 尚未登录 ChatGPT。"
        except Exception:
            codex_error = "无法读取 Codex CLI 登录状态。"
    agy_version = None
    if available["gemini"]:
        try:
            result = subprocess.run([available["gemini"], "--version"], capture_output=True, text=True, timeout=10,
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if result.returncode == 0:
                agy_version = (result.stdout or result.stderr).strip()
        except Exception:
            pass
    return {"gemini": {"ready": bool(available["gemini"] and agy_version), "name": "Antigravity CLI / Gemini", "executable": available["gemini"], "version": agy_version},
            "codex": {"ready": codex_ready, "name": "Codex CLI", "executable": available["codex"], "error": codex_error}}


@router.get("/api/local/books/{book_id}/readiness")
def readiness(book_id: str, chapter: int | None = Query(default=None, ge=1, le=99999)):
    import subprocess
    from ..agents.local_cli import executables
    book = book_by_id(book_id)
    available = executables()
    agent_state = {"gemini": bool(available["gemini"]), "codex": False}
    if available["codex"]:
        try:
            auth = subprocess.run([available["codex"], "login", "status"], capture_output=True, text=True, timeout=12,
                                  creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            agent_state["codex"] = auth.returncode == 0 and "logged in" in ((auth.stdout or "") + (auth.stderr or "")).lower()
        except Exception:
            pass
    root = book["root"]
    rows = index(book)
    written = [row["number"] for row in rows if row.get("draft")]
    next_chapter = max(written, default=0) + 1
    chapter = chapter or next_chapter
    next_row = next((row for row in rows if row["number"] == chapter), {})
    tracking_script = STORY_SKILLS / "story-long-write" / "scripts" / "tracking_commit.py"
    tracking = {"available": tracking_script.is_file(), "ok": False, "message": "未找到长篇追踪校验工具。"}
    if tracking["available"]:
        try:
            result = subprocess.run([str(Path(__import__("sys").executable)), str(tracking_script), "check", "--project", str(root)],
                                    capture_output=True, text=True, timeout=30, encoding="utf-8", errors="replace",
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            tracking["ok"] = result.returncode == 0
            tracking["message"] = "追踪状态通过校验。" if tracking["ok"] else (result.stderr or result.stdout).strip()[-1200:]
        except subprocess.TimeoutExpired:
            tracking["message"] = "追踪校验超过 30 秒，已停止。"
        except Exception as exc:
            tracking["message"] = str(exc)[:1000]
    blockers = []
    if not agent_state["gemini"]: blockers.append("缺少 Antigravity CLI (agy)。")
    if not agent_state["codex"]: blockers.append("Codex CLI 未登录 ChatGPT。")
    if not tracking["ok"]: blockers.append("追踪状态需要先修复，不能安全地把新章写回正文与角色状态。")
    if next_row.get("source_warning"): blockers.append(f"第{chapter}章尚未在阅读入口确认有效版本。")
    return {"book_id": book_id, "agents": agent_state, "tracking": tracking, "next_chapter": next_chapter, "chapter": chapter,
            "has_outline": bool(next_row.get("outline")), "has_draft": bool(next_row.get("draft")),
            "source_warning": bool(next_row.get("source_warning")), "can_start": bool(agent_state["gemini"] and agent_state["codex"] and next_row),
            "tracking_ok": bool(tracking["ok"]), "can_write_back": False,
            "writeback_message": "本机自动流程尚未接通本书的章节验收与追踪提交脚本；候选稿暂存在运行目录。", "blockers": blockers}



class AutomaticRunRequest(BaseModel):
    chapter: int = Field(ge=1, le=99999)
    confirm_versions: bool = False
    mode: Literal['full', 'outline'] = 'full'
    max_revisions: int = Field(default=3, ge=1, le=6)
    codex_model: str | None = Field(default=None, max_length=100, pattern=r'^[A-Za-z0-9._:/-]+$')
    gemini_model: str | None = Field(default=None, max_length=100, pattern=r'^[A-Za-z0-9._:/-]+$')


@router.post("/api/local/books/{book_id}/run")
def start_automatic_run(book_id: str, request: AutomaticRunRequest, http_request: Request, background: BackgroundTasks):
    same_origin(http_request)
    book = book_by_id(book_id)
    row = next((item for item in index(book) if item["number"] == request.chapter), None)
    if not row:
        raise HTTPException(404, "请从章节目录选中本章后再启动。")
    if len(row.get('outline', [])) != 1:
        raise HTTPException(409, '请先准备本章唯一有效细纲，再选择全面写作或仅审细纲。')
    agent_state = agents()
    if not agent_state["gemini"]["ready"] or not agent_state["codex"]["ready"]:
        raise HTTPException(409, "本机 Antigravity CLI 与 Codex CLI 必须都已安装，并登录现有账号。")
    if row["source_warning"] and not request.confirm_versions:
        raise HTTPException(409, f"第{request.chapter}章正文未在本书当前入口确认，请核对版本后重试。")
    if any(len(row.get(kind, [])) > 1 for kind in ("draft", "outline")):
        raise HTTPException(409, f"第{request.chapter}章存在多个正文或细纲版本，请先核对。")
    with RUN_LOCK:
        active = [r for r in store.runs_for(book_id, request.chapter) if r['status'] in {'queued','running'}]
        if active:
            raise HTTPException(409, '本章已有运行中的任务，请先查看进度。')
        run_id = store.create_run(book_id, request.chapter, request.model_dump())
    from ..agents.workflow import run_automatic
    background.add_task(RUN_POOL.submit, run_automatic, run_id, book_id, book, request.chapter, confirm_versions=request.confirm_versions, mode=request.mode, max_revisions=request.max_revisions, codex_model=request.codex_model, gemini_model=request.gemini_model)
    return store.get_run(run_id)


@router.get("/api/local/books/{book_id}/runs")
def list_runs(book_id: str, chapter: int | None = Query(default=None, ge=1, le=99999)):
    book_by_id(book_id)
    return store.runs_for(book_id, chapter)


@router.get("/api/local/runs/{run_id}")
def run_detail(run_id: str):
    run = store.get_run(run_id)
    if not run:
        raise HTTPException(404, "自动流程记录不存在")
    directory = store.data_directory() / 'runs' / run_id
    run['artifacts'] = [{'name': p.name, 'url': f'/api/local/runs/{run_id}/artifacts/{__import__("urllib.parse", fromlist=["quote"]).quote(p.name)}'} for p in sorted(directory.glob('*')) if p.is_file() and p.suffix in {'.md', '.json'} and 'schema' not in p.name]
    return run


@router.get("/api/local/runs/{run_id}/artifacts/{name}")
def run_artifact(run_id: str, name: str):
    from fastapi.responses import FileResponse as Download
    run = store.get_run(run_id)
    if not run:
        raise HTTPException(404, "自动流程记录不存在")
    if Path(name).name != name or not name.endswith((".md", ".json")):
        raise HTTPException(404, "候选文件不存在")
    run_root = (store.data_directory() / "runs" / run_id).resolve()
    target = (run_root / name).resolve()
    if not target.is_relative_to(run_root) or not target.is_file():
        raise HTTPException(404, "候选文件不存在")
    return Download(target, filename=name, media_type="text/markdown" if name.endswith(".md") else "application/json")


class PacketRequest(BaseModel):
    chapter: int = Field(ge=1, le=99999)
    stage: Literal["outline", "draft", "review", "final"]
    extra_paths: list[str] = Field(default_factory=list, max_length=40)
    confirm_versions: bool = False


def build_packet(book_id, request, draft_override=None, outline_override=None):
    book = book_by_id(book_id)
    root = book["root"]
    rows = index(book)
    row = next((r for r in rows if r["number"] == request.chapter), None)
    if row is None and (request.stage == "outline" or outline_override is not None):
        row = {"number": request.chapter, "draft": [], "outline": [], "source_warning": False}
    if not row:
        raise HTTPException(404, "章节不存在")
    selected = []
    warnings = []
    for key in ["draft", "outline"]:
        matches = row.get(key, [])
        if len(matches) > 1:
            raise HTTPException(409, "同章存在多个候选版本，请先核对，工作台不会自动选择。")
        if not (key == "draft" and draft_override is not None) and not (key == "outline" and outline_override is not None):
            selected += matches
    if request.stage in ["review", "final"] and not row.get("draft") and draft_override is None:
        raise HTTPException(409, "本章还没有正文，不能生成正文审查或终审材料。")
    if request.stage in ["outline", "draft"] and not row.get("outline") and outline_override is None:
        raise HTTPException(409, "本章缺少细纲，请先准备有效细纲。")
    if request.stage == "draft" and row.get("draft"):
        raise HTTPException(409, "本章已有正文；请使用审查阶段，工作台不生成覆盖原稿的任务。")
    previous = sorted([r for r in rows if r["number"] < request.chapter and r.get("draft")], key=lambda r: r["number"])[-3:]
    unresolved = [r for r in [row] + previous if r["source_warning"]]
    if unresolved and not request.confirm_versions:
        nums = "、".join(str(r["number"]) for r in unresolved)
        raise HTTPException(409, f"第 {nums} 章正文未被阅读入口收录。核对文件后，请勾选版本确认再创建任务。")
    if unresolved:
        warnings.append("作者已在工作台确认使用以下入口未收录版本：" + "、".join(str(r["number"]) for r in unresolved) + "章。阅读入口未被修改。")
    rules = ["写作规范/文风规则.md", "写作规范/正文验收清单.md", "写作规范/西幻词汇规范.md", "大纲/细纲写作规则.md", "追踪/上下文.md", f"{book['manuscript']}/阅读入口.md"]
    for relative in ["写作规范/文风规则.md", "写作规范/正文验收清单.md", "追踪/上下文.md"]:
        if not (root / relative).is_file():
            raise HTTPException(409, f"缺少必要文件：{relative}。请先恢复文件，再创建任务。")
    sources = []
    agents = root / "AGENTS.md"
    if not agents.exists():
        agents = root.parent / "AGENTS.md"
    if agents.is_file():
        sources.append((agents, "项目约定", "project"))
    else:
        warnings.append("未找到项目 AGENTS.md，执行者应核对项目约定。")
    for earlier in previous:
        if len(earlier["draft"]) != 1:
            raise HTTPException(409, f"第{earlier['number']}章前文存在多个版本，请先核对。")
        rules += earlier["draft"]
    if request.stage != "outline" and request.chapter > 1 and not any(r["number"] == request.chapter - 1 for r in previous):
        raise HTTPException(409, f"缺少直接承接的第{request.chapter-1}章正文，不能自动整理连续章节材料。")
    rules += book.get("core", [])
    for relative in request.extra_paths:
        safe_file(root, relative)
    for relative in dict.fromkeys(rules + request.extra_paths + selected):
        if (root / relative).is_file():
            sources.append((safe_file(root, relative), relative, "book"))
    if outline_override is not None:
        virtual_path, _ = outline_override
        sources.append((Path(virtual_path), "当前待审细纲.md", "outline"))
    if draft_override is not None:
        virtual_path, _ = draft_override
        sources.append((Path(virtual_path), "当前待审稿.md", "draft"))
    skill_stage = "review" if request.stage == "final" else request.stage
    skill_name = book.get("skills", {}).get(skill_stage)
    if skill_name:
        skill_dir = SKILLS / skill_name
        if not (skill_dir / "SKILL.md").is_file():
            raise HTTPException(409, f"缺少本书专属审查规则：{skill_name}，请先恢复技能文件。")
        sources.append((skill_dir / "SKILL.md", f"审查技能/{skill_name}/SKILL.md", "skill"))
        for path in sorted((skill_dir / "references").glob("*.md")):
            if path.resolve().is_relative_to(skill_dir.resolve()):
                sources.append((path, f"审查技能/{skill_name}/references/{path.name}", "skill"))
    files, sections, seen = [], [], set()
    for target, label, kind in sources:
        target = target.resolve()
        if target in seen:
            continue
        seen.add(target)
        raw = target.read_bytes()
        content = raw.decode("utf-8-sig")
        file_hash = hashlib.sha256(raw).hexdigest()
        files.append({"path": label, "absolute_path": str(target), "kind": kind, "sha256": file_hash, "chars": len(content), "content": content})
        sections.append(f"\n## 文件：{label}\n\n{content}\n")
    warnings.append("已附本书核心设定及手动勾选材料；人物、能力与旧事仍需按本章内容回查早期有效正文。材料包不代表已经完成审查。")
    if request.stage == "final":
        warnings.append("独立首读材料不包含历史审查报告。独立报告回填后，可在工作台查看前轮报告，再另存核对结论。")
    header = f"# {book['title']} · 第{request.chapter:03d}章 · {STAGES[request.stage]}\n\n{INSTRUCTIONS[request.stage]}\n\n审查尺度：{book['focus']}\n\n作者指示优先；有效正文是已发生事实的依据；细纲是计划；追踪只作索引。附入技能仅用于本阶段审查标准，不能将只读审查变成正文改写。正文创作仅按当前授权执行。\n\n## 材料限制与版本说明\n" + "\n".join(f"- {w}" for w in warnings)
    manifest = "\n\n## 送审文件指纹\n" + "\n".join(f"- {f['path']}：{f['sha256']}" for f in files)
    return {"text": header + manifest + "\n".join(sections), "files": files, "warnings": warnings, "confirmed_versions": request.confirm_versions,
            "chapter_sources": {"chapter": request.chapter, "draft": row.get("draft", []), "outline": row.get("outline", [])}}


@router.post("/api/local/books/{book_id}/packet")
def packet(book_id: str, request: PacketRequest, http_request: Request):
    same_origin(http_request)
    return build_packet(book_id, request)


@router.post("/api/local/books/{book_id}/tasks")
def create_task(book_id: str, request: PacketRequest, http_request: Request):
    same_origin(http_request)
    payload = build_packet(book_id, request)
    task_id = store.create_task(book_id, request.chapter, request.stage, payload)
    return task_view(require_task(task_id), include_payload=True)


@router.get("/api/local/books/{book_id}/tasks")
def tasks(book_id: str, chapter: int = Query(default=1, ge=1, le=99999)):
    book_by_id(book_id)
    return [task_view(r) for r in store.task_records(book_id, chapter)]


@router.get("/api/local/tasks/{task_id}")
def task_detail(task_id: str):
    return task_view(require_task(task_id), include_payload=True)


@router.get("/api/local/tasks/{task_id}/changes")
def task_changes(task_id: str):
    record = require_task(task_id)
    view = task_view(record)
    payload = json.loads(record["payload"])
    changed = {item["path"] for item in view["changed_files"]}
    result = []
    for item in payload["files"]:
        if item["path"] not in changed:
            continue
        try:
            current = read(Path(item["absolute_path"]))
        except OSError:
            current = "（文件已移走或无法读取）"
        diff = "\n".join(unified_diff(item["content"].splitlines(), current.splitlines(), fromfile="送审版本/" + item["path"], tofile="当前文件/" + item["path"], lineterm=""))
        result.append({"path": item["path"], "diff": diff or "文件字节或编码变化，文本内容未变化。"})
    return {"changes": view["changed_files"], "diffs": result}


class ReportRequest(BaseModel):
    reviewer: str = Field(min_length=1, max_length=100)
    verdict: Literal["pass", "revise", "blocked", "submitted"]
    content: str = Field(min_length=10, max_length=300000)


@router.post("/api/local/tasks/{task_id}/reports")
def add_report(task_id: str, request: ReportRequest, http_request: Request):
    same_origin(http_request)
    record = require_task(task_id)
    if len(request.content.strip()) < 10 or not request.reviewer.strip():
        raise HTTPException(422, "请填写审阅人和至少十字的完整报告")
    if record["stage"] == "draft" and request.verdict != "submitted":
        raise HTTPException(409, "创作任务只能记录创作结果，不能标记审查通过。")
    if record["stage"] != "draft" and request.verdict == "submitted":
        raise HTTPException(409, "审查任务请选择通过、需修改或待裁定。")
    store.save_report(task_id, request.reviewer.strip(), request.verdict, request.content.strip())
    return task_view(record, include_payload=True)


class ApprovalRequest(BaseModel):
    report_id: int = Field(gt=0)
    note: str = Field(default="作者确认本次终审结论与送审版本", max_length=2000)


@router.post("/api/local/tasks/{task_id}/approve")
def approve(task_id: str, request: ApprovalRequest, http_request: Request):
    same_origin(http_request)
    record = require_task(task_id)
    view = task_view(record)
    if not view["can_approve"]:
        raise HTTPException(409, "只有材料未变化、最新终审报告通过的任务才能由作者定稿。")
    if view["latest_report"]["id"] != request.report_id:
        raise HTTPException(409, "报告版本已变化，请刷新后核对最新结论。")
    if not store.save_approval(task_id, request.report_id, request.note.strip()):
        raise HTTPException(409, "报告版本已变化，请刷新后重试。")
    return task_view(record, include_payload=True)


@router.get("/api/local/tasks/{task_id}/previous-reports")
def previous_reports(task_id: str):
    record = require_task(task_id)
    if record["stage"] == "final" and not store.reports_for(task_id):
        raise HTTPException(409, "请先完成并回填独立首读报告，再查看前轮意见。")
    result = []
    for earlier in store.task_records(record["book_id"], record["chapter"]):
        if earlier["id"] == task_id or earlier["created_at"] >= record["created_at"]:
            continue
        reports = store.reports_for(earlier["id"])
        if reports:
            view = task_view(earlier)
            result.append({"id": earlier["id"], "stage_label": view["stage_label"], "stale": view["stale"], "reports": reports})
    return result
