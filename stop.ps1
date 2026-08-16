# Stop whatever is serving PyCompiler on port 8000.
$listeners = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
if (-not $listeners) {
    Write-Host "Nothing is listening on port 8000." -ForegroundColor Yellow
    return
}
$listeners.OwningProcess | Sort-Object -Unique | ForEach-Object {
    $name = (Get-Process -Id $_ -ErrorAction SilentlyContinue).ProcessName
    Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue
    Write-Host "Stopped $name (pid $_)" -ForegroundColor Green
}
