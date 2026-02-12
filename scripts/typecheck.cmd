@echo off
setlocal

if not "%1"=="" (
  echo Usage: scripts\typecheck.cmd
  exit /b 2
)

echo [typecheck] python:
python --version

python -m mypy
if errorlevel 1 exit /b 1
echo [typecheck] mypy: ok
exit /b 0
