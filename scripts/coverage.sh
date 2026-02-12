#!/usr/bin/env bash
set -euo pipefail

# Generate a coverage report (report-only; no fail-under gate).
# Produces:
#   - terminal missing-lines report
#   - coverage.xml
#   - ./htmlcov/ (HTML report)
#
# Usage:
#   ./scripts/coverage.sh

if python -c "import pytest_cov" >/dev/null 2>&1; then
  python -m pytest -q --cov=spcdb_tool --cov-report=term-missing --cov-report=xml --cov-report=html
  echo "Coverage reports written: coverage.xml and ./htmlcov/"
else
  echo "pytest-cov is not installed in this Python environment." >&2
  echo "Install dev deps: python -m pip install -r requirements-dev.txt" >&2
  exit 2
fi
