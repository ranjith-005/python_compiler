# Start PyCompiler on http://127.0.0.1:8000
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $root ".venv\Scripts\python.exe"

# 1. Ensure virtual environment exists
if (-not (Test-Path $python)) {
    Write-Host "Creating virtual environment..." -ForegroundColor Cyan
    python -m venv (Join-Path $root ".venv")
}

# 2. Ensure pip is present
$hasPip = $null
try {
    $hasPip = & $python -m pip --version 2>$null
} catch {}
if (-not $hasPip) {
    Write-Host "Setting up pip in virtual environment..." -ForegroundColor Cyan
    & $python -m ensurepip --upgrade
}

# 3. Ensure required packages are installed
$hasModules = $null
try {
    $hasModules = & $python -c "import uvicorn, fastapi; print('OK')" 2>$null
} catch {}
if ($LASTEXITCODE -ne 0 -or $hasModules -ne "OK") {
    Write-Host "Installing dependencies from requirements.txt..." -ForegroundColor Cyan
    & $python -m pip install -r (Join-Path $root "requirements.txt")
}

# 4. Open browser once the server is listening
$url = "http://127.0.0.1:8000"
Start-Job -ScriptBlock {
    param($targetUrl)
    for ($i = 0; $i -lt 30; $i++) {
        Start-Sleep -Milliseconds 800
        try {
            $req = [System.Net.WebRequest]::Create($targetUrl)
            $req.Timeout = 1500
            $res = $req.GetResponse()
            $res.Close()
            Start-Process $targetUrl
            break
        } catch {}
    }
} -ArgumentList $url | Out-Null

Set-Location $root
Write-Host "Starting PyCompiler on $url..." -ForegroundColor Green
& $python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 @args

