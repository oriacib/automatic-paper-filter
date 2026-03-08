@echo off
setlocal
cd /d %~dp0\..
python -m app.main run-once
endlocal
