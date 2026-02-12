@echo off
setlocal

if not "%1"=="" (
  echo Usage: scripts\lint.cmd
  exit /b 2
)

echo [lint] python:
python --version

python -m ruff check .
if errorlevel 1 exit /b 1
echo [lint] ruff: ok
exit /b 0
