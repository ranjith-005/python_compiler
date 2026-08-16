@echo off
REM Double-click this to start PyCompiler and open it in your browser.
cd /d "%~dp0"
start "" http://127.0.0.1:8000
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1"
pause
