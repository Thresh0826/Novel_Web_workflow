$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath "$PSScriptRoot/upstream/novel-agent"
& "$PSScriptRoot/.venv/Scripts/python.exe" -m uvicorn src.local_preview:app --host 127.0.0.1 --port 8765
