"""Thin adapters for the user's already-authenticated local Gemini and Codex CLIs."""

import os
import json
import shutil
import subprocess
from pathlib import Path
from urllib.request import getproxies


def agent_environment():
    """Reuse explicit proxies, otherwise inherit the Windows Internet proxy."""
    env = os.environ.copy()
    for key in ('OPENAI_API_KEY', 'CODEX_API_KEY', 'GEMINI_API_KEY', 'GOOGLE_API_KEY'):
        env.pop(key, None)
    proxies = getproxies()
    if os.name == 'nt':
        from urllib.request import getproxies_registry
        proxies = {**getproxies_registry(), **proxies}
    override = env.get('NOVEL_WORKBENCH_PROXY')
    for scheme in ('http', 'https'):
        key = scheme.upper() + '_PROXY'
        if override:
            env[key] = override
            env[key.lower()] = override
        elif not any(env.get(k) for k in (key, key.lower(), 'ALL_PROXY', 'all_proxy')):
            proxy = proxies.get(scheme)
            if proxy:
                env[key] = proxy
    env['NO_COLOR'] = '1'
    return env


def executables():
    codex = os.environ.get("CODEX_CLI") or shutil.which("codex")
    agy = os.environ.get("ANTIGRAVITY_CLI") or shutil.which("agy")
    if not agy:
        local = os.environ.get("LOCALAPPDATA")
        if local:
            candidate = Path(local) / "agy" / "bin" / "agy.exe"
            if candidate.is_file():
                agy = str(candidate)
    return {"gemini": agy, "codex": codex}


def run_agent(provider, prompt, *, cwd, timeout=900, schema_path=None, model=None):
    available = executables()
    executable = available.get(provider)
    if not executable:
        name = "Antigravity CLI (agy)" if provider == "gemini" else "Codex CLI"
        raise RuntimeError(f"找不到{name}。请先完成安装，然后在工作台刷新检查。")

    if provider == "gemini":
        args = [executable, "--input-format", "stream-json", "--output-format", "stream-json"]
        if schema_path:
            args.extend(["--json-schema", str(schema_path)])
        input_text = json.dumps({"event": "user", "message": {"content": prompt}}, ensure_ascii=False) + "\n"
    elif provider == "codex":
        args = [executable, "exec", "--ephemeral", "--skip-git-repo-check", "--sandbox", "read-only", "--cd", str(cwd)]
        if schema_path:
            args.extend(["--output-schema", str(schema_path)])
        args.append("-")
    else:
        raise ValueError("未配置此模型适配器")

    if model:
        args.extend(['--model', model])

    child_env = agent_environment()
    try:
        completed = subprocess.run(
            args, cwd=str(cwd), input=input_text if provider == "gemini" else prompt,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
            env=child_env, timeout=timeout, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"{provider} CLI 超过 {timeout//60} 分钟没有完成，本次停止并保留进度。") from exc
    output = (completed.stdout or "").strip()
    diagnostics = (completed.stderr or "").strip()
    if len(output) > 2_000_000:
        raise RuntimeError("模型输出超过 2 MB，已中止本次步骤。")
    if completed.returncode != 0:
        raise RuntimeError(f"{provider} CLI 退出码 {completed.returncode}：{diagnostics[-3000:] or output[-3000:]}")
    if provider == "gemini":
        events = []
        for line in output.splitlines():
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        terminal = next((event.get("result", {}) for event in reversed(events) if event.get("event") == "result"), None)
        if terminal is None:
            raise RuntimeError(f"Antigravity CLI 没有返回终止事件：{diagnostics[-2000:] or output[-2000:]}")
        if terminal.get("status") not in {None, "SUCCESS"}:
            raise RuntimeError(f"Antigravity CLI 状态 {terminal.get('status')}：{terminal.get('error') or diagnostics[-2000:]}")
        structured = terminal.get("structured_output")
        output = json.dumps(structured, ensure_ascii=False) if structured is not None else str(terminal.get("response", "")).strip()
    if not output:
        raise RuntimeError(f"{provider} CLI 返回空结果。")
    return output
