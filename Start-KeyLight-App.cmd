@echo off
setlocal

set "ROOT=%~dp0"
powershell -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "%ROOT%scripts\launch-app.ps1"

endlocal
