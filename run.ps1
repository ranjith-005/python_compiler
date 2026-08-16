# Start PyCompiler on http://127.0.0.1:8000
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $root ".venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    Write-Host "Creating virtual environment..." -ForegroundColor Cyan
    python -m venv (Join-Path $root ".venv")
    & $python -m pip install --upgrade pip
    & $python -m pip install -r (Join-Path $root "requirements.txt")
}

Set-Location $root
& $python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 @args
