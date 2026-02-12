@echo off

REM SingStar Disc Builder - launcher

REM

REM Cross-platform launch:

REM   python -m spcdb_tool gui

REM

REM Windows launch:

REM   run_gui.bat [--qt|--tk] [--debug]



setlocal EnableExtensions EnableDelayedExpansion

cd /d "%~dp0"



REM Per-run logs under .\logs, plus a root 'last run' file.

set "LOGDIR=%~dp0logs"

if not exist "%LOGDIR%" mkdir "%LOGDIR%" >nul 2>&1



REM Locale-safe timestamp (prefer WMIC). WMIC returns: yyyymmddHHMMSS.mmmmmms+tz

set "TS="

for /f "tokens=2 delims==" %%I in ('wmic os get LocalDateTime /value 2^>nul') do (

  if not defined TS set "TS=%%I"

)

if defined TS (

  set "TS=!TS:~0,4!-!TS:~4,2!-!TS:~6,2!_!TS:~8,2!-!TS:~10,2!-!TS:~12,2!"

) else (

  REM Fallback: sanitize %DATE% and %TIME% for filenames

  set "TS=%DATE%_%TIME%"

  set "TS=!TS:/=-!"

  set "TS=!TS::=-!"

  set "TS=!TS:.=-!"

  set "TS=!TS:,=-!"

  set "TS=!TS: =0!"

)



set "LOG=%LOGDIR%\run_gui_launch_%TS%.log"
set "LOG_ERR=%LOGDIR%\run_gui_launch_%TS%_stderr.log"

set "LOG_LAST=%~dp0run_gui_launch.log"



> "%LOG%" echo [%date% %time%] run_gui.bat started in: "%cd%"

> "%LOG_LAST%" echo [%date% %time%] run_gui.bat started in: "%cd%"



set "MODE=AUTO"

set "SPCDB_LOG_LEVEL=INFO"

set "SPCDB_LOG_TO_CONSOLE=1"

set "PYTHONUNBUFFERED=1"

set "QT_DIAG=0"



for %%A in (%*) do (

  if /I "%%~A"=="--qt" set "MODE=QT"

  if /I "%%~A"=="--tk" set "MODE=TK"

  if /I "%%~A"=="--qt-diag" set "QT_DIAG=1"

  if /I "%%~A"=="--debug" set "SPCDB_LOG_LEVEL=DEBUG"

)



REM If --debug was requested, enable Qt plugin diagnostics too.

if /I "%SPCDB_LOG_LEVEL%"=="DEBUG" (

  set "QT_DEBUG_PLUGINS=1"

)



REM Choose an interpreter.

set "PYEXE="

set "PYEXE_ARGS="



if exist ".venv\Scripts\python.exe" (

  set "PYEXE=%~dp0.venv\Scripts\python.exe"

) else if exist "venv\Scripts\python.exe" (

  set "PYEXE=%~dp0venv\Scripts\python.exe"

) else if exist "env\Scripts\python.exe" (

  set "PYEXE=%~dp0env\Scripts\python.exe"

) else (

  where py >nul 2>&1

  if "%errorlevel%"=="0" (

    set "PYEXE=py"

    set "PYEXE_ARGS=-3"

  ) else (

    set "PYEXE=python"

    set "PYEXE_ARGS="

  )

)



set "GUIARG=gui"

if /I "%MODE%"=="QT" set "GUIARG=gui-qt"

if /I "%MODE%"=="TK" set "GUIARG=gui-tk"

if "%QT_DIAG%"=="1" set "GUIARG=qt-diag"



echo Using Python: "%PYEXE%" %PYEXE_ARGS%

echo Mode: %GUIARG%

echo Logs folder: "%LOGDIR%"

echo(



>>"%LOG%" echo Using Python: "%PYEXE%" %PYEXE_ARGS%

>>"%LOG%" echo Mode: %GUIARG%

>>"%LOG_LAST%" echo Using Python: "%PYEXE%" %PYEXE_ARGS%

>>"%LOG_LAST%" echo Mode: %GUIARG%



REM Launch in the same console so you can see logs live.
REM In --debug, suppress scary PowerShell "NativeCommandError" spam by capturing native stderr
REM (including Qt plugin diagnostics) to a sidecar log file, while leaving stdout live.

if /I "%SPCDB_LOG_LEVEL%"=="DEBUG" (
  "%PYEXE%" %PYEXE_ARGS% -u -X faulthandler -m spcdb_tool %GUIARG% 2>>"%LOG_ERR%"
  set "EXITCODE=%errorlevel%"

  REM Merge any captured stderr into the per-run launch log for easy sharing.
  set "ERRSIZE=0"
  if exist "%LOG_ERR%" (
    for %%F in ("%LOG_ERR%") do set "ERRSIZE=%%~zF"
  )
  if not "!ERRSIZE!"=="0" (
    >>"%LOG%" echo(
    >>"%LOG%" echo ===== STDERR ^(captured^) =====
    type "%LOG_ERR%" >>"%LOG%"
  )

  REM Delete empty stderr sidecar to reduce noise.
  if exist "%LOG_ERR%" (
    if "!ERRSIZE!"=="0" del /q "%LOG_ERR%" >nul 2>&1
  )

  REM Keep a copy of the latest full launch log at repo root for easy sharing.
  copy /y "%LOG%" "%LOG_LAST%" >nul 2>&1
) else (
  "%PYEXE%" %PYEXE_ARGS% -u -m spcdb_tool %GUIARG%
  set "EXITCODE=%errorlevel%"
)



>>"%LOG%" echo Exit code: %EXITCODE%

>>"%LOG_LAST%" echo Exit code: %EXITCODE%



if not "%EXITCODE%"=="0" goto :LAUNCH_FAILED



goto :LAUNCH_DONE



:LAUNCH_FAILED

REM Use echo( instead of echo. to avoid edge-case parsing issues in cmd blocks.

echo(

echo Launcher failed (exit code %EXITCODE%).

echo See: "%LOG%" ^(and "%LOG_LAST%"^)

echo(

pause



:LAUNCH_DONE

exit /b %EXITCODE%

