@echo off
setlocal

REM Generate a coverage report (report-only; no fail-under gate).
REM Produces:
REM   - terminal missing-lines report
REM   - coverage.xml
REM   - .\\htmlcov\\ (HTML report)

python -m pytest -q --cov=spcdb_tool --cov-report=term-missing --cov-report=xml --cov-report=html

endlocal
