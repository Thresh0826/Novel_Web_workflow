"""Read account limits through the CLI protocol, without reading credentials."""
import json
import queue
import subprocess
import threading
import time
from .local_cli import agent_environment, executables

_cache = None
_lock = threading.Lock()


def read_usage():
    global _cache
    with _lock:
        if _cache and time.time() - _cache['fetched_at'] < 60:
            return _cache
        result = {'fetched_at': time.time(), 'codex': {'available': False}, 'gemini': {
            'available': False, 'message': 'Antigravity CLI 未提供可用的额度查询命令，请在 Antigravity 账号界面查看；无法推算剩余额度。'}}
        process = None
        try:
            executable = executables()['codex']
            if not executable: raise ValueError('未找到 Codex CLI')
            process = subprocess.Popen([executable, 'app-server', '--listen', 'stdio://'], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, text=True, encoding='utf-8', env=agent_environment(), creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            inbox = queue.Queue()
            def reader():
                for line in process.stdout:
                    try: inbox.put(json.loads(line))
                    except ValueError: pass
            threading.Thread(target=reader, daemon=True).start()
            def send(value):
                process.stdin.write(json.dumps(value)+'\n'); process.stdin.flush()
            def receive(identifier):
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline:
                    value = inbox.get(timeout=max(.1, deadline-time.monotonic()))
                    if value.get('id') == identifier:
                        if value.get('error'): raise ValueError('额度查询被 CLI 拒绝')
                        return value['result']
                raise ValueError('额度查询超时')
            send({'id':1,'method':'initialize','params':{'clientInfo':{'name':'novel_workbench','version':'0.4.0'}}})
            receive(1)
            send({'method':'initialized','params':{}})
            send({'id':2,'method':'account/rateLimits/read','params':{}})
            data = receive(2)
            buckets = data.get('rateLimitsByLimitId') or {'codex':data.get('rateLimits')}
            cleaned = []
            for name, bucket in buckets.items():
                if not bucket: continue
                windows = []
                for key in ['primary','secondary']:
                    w = bucket.get(key)
                    if w and isinstance(w.get('usedPercent'), (int,float)):
                        windows.append({'remaining':max(0,min(100,100-w['usedPercent'])), 'minutes':w.get('windowDurationMins'), 'resets_at':w.get('resetsAt')})
                cleaned.append({'name':bucket.get('limitName') or name, 'windows':windows})
            result['codex'] = {'available':bool(cleaned), 'buckets':cleaned, 'message':'与同账号 Codex 使用共享额度；查询不会发起模型生成。'}
        except Exception:
            result['codex'] = {'available':False, 'message':'暂时无法读取 Codex 额度，请在 Codex 的 /status 或账号用量页查看。'}
        finally:
            if process:
                process.terminate()
                try: process.wait(timeout=5)
                except subprocess.TimeoutExpired: process.kill(); process.wait()
        _cache = result
        return result
