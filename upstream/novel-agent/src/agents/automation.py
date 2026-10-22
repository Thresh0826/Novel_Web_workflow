"""One-click, resumable handoff across Antigravity/Gemini and Codex CLIs."""

from __future__ import annotations

import json
import hashlib
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from .local_cli import run_agent
from ..storage import workbench_store as store

SKILL_ROOT = Path.home() / ".agents" / "skills" / "story-long-write"
REVIEW_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "verdict": {"type": "string", "enum": ["PASS", "REVISE", "BLOCKED"]},
        "report": {"type": "string"},
        "revision_brief": {"type": "string"},
    },
    "required": ["verdict", "report", "revision_brief"],
}


def _update(run_id, step, message, *, status="running", extra=None):
    record = store.get_run(run_id) or {}
    result = dict(record.get("result", {}))
    if extra:
        result.update(extra)
    store.update_run(run_id, status=status, step=step, message=message, result=result)


def _write_text(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")


def _agent_json(provider, prompt, workdir: Path, schema_path: Path):
    raw = run_agent(provider, prompt, cwd=workdir, schema_path=schema_path)
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    for match in reversed(list(re.finditer(r"\{[\s\S]*\}", raw))):
        try:
            data = json.loads(match.group())
            if isinstance(data, dict) and "verdict" in data:
                return data
        except json.JSONDecodeError:
            continue
    raise RuntimeError(f"{provider} 没返回约定的审查格式。输出已保存在运行记录目录。")


def _read_skill(name: str) -> str:
    path = SKILL_ROOT / "references" / name
    if not path.is_file():
        raise RuntimeError(f"长篇写作 skill 缺少必读参考文件：{path}")
    return f"\n\n### 本阶段写作方法：{name}\n\n{path.read_text(encoding='utf-8-sig')}"


def _long_write_context(stage: str) -> str:
    if not (SKILL_ROOT / "SKILL.md").is_file():
        raise RuntimeError(f"未安装 story-long-write：{SKILL_ROOT}")
    text = "\n\n# 本地 story-long-write 流程门禁\n\n" + (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8-sig")
    references = ["style-resolution.md", "project-files.md", "state-tracking.md"]
    if stage == "outline":
        references += ["workflow-setup.md", "outline-structure-theory.md", "outline-methods.md", "outline-rhythm.md", "outline-conflict.md"]
    elif stage == "draft":
        references += ["workflow-chapter.md", "long-format.md", "writing-craft.md", "long-chapter-quality.md", "long-chapter-hooks.md", "reader-contract-and-progression.md", "writer-prompt-fallback.md"]
    for reference in references:
        text += _read_skill(reference)
    return text


def _report_prompt(label: str, materials: str, *, independent: bool) -> str:
    blind = "This is an independent first read. Do not request or infer prior review reports. Assess the chapter on its own using only the supplied manuscript, outline, canon, and book-specific audit rules." if independent else "Audit the outline and chapter against the supplied project rules and source material."
    return f"""You are the {label} in a Chinese serialized novel workflow. Write only in Chinese.
{blind}
Return the required JSON. PASS means you found no material issue that needs revision. REVISE means you can give a concrete, minimal repair supported by the source. BLOCKED means a missing or conflicting author decision prevents a reliable judgment. Never invent problems to fill the report.

{materials}
"""


def run_automatic(*args, **kwargs):
    """Compatibility entry point; both modes use the same explicit state machine."""
    from .workflow import run_automatic as execute
    return execute(*args, **kwargs)
