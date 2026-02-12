@echo off
setlocal EnableDelayedExpansion

set WITH_SUPPORT_BUNDLE=0

if "%1"=="--with-support-bundle" (
  set WITH_SUPPORT_BUNDLE=1
  shift
)

if not "%1"=="" (
  echo Usage: scripts\smoke.cmd [--with-support-bundle]
  exit /b 2
)

echo [smoke] python:
python --version

python -m compileall spcdb_tool >nul
if errorlevel 1 exit /b 1
echo [smoke] compileall: ok

python -m pytest -q
if errorlevel 1 exit /b 1
echo [smoke] pytest: ok

python -m ruff check .
if errorlevel 1 exit /b 1
echo [smoke] ruff: ok

python -m mypy
if errorlevel 1 exit /b 1
echo [smoke] mypy: ok

if "%WITH_SUPPORT_BUNDLE%"=="1" (
  set OUT=spcdb_support_smoke.zip
  if exist "!OUT!" del /q "!OUT!"
  python -m spcdb_tool support-bundle --out "!OUT!"
  if errorlevel 1 exit /b 1
  if not exist "!OUT!" (
    echo [smoke] support bundle: expected !OUT! but it was not created
    exit /b 1
  )
  echo [smoke] support bundle: !OUT!
)

echo [smoke] all good
exit /b 0
