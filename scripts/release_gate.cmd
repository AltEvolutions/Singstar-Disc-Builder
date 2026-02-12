@echo off
setlocal

python scripts\release_gate.py %*
exit /b %errorlevel%
