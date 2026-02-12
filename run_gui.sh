#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

export SPCDB_LOG_TO_CONSOLE=1
export SPCDB_LOG_LEVEL="${SPCDB_LOG_LEVEL:-INFO}"
export PYTHONUNBUFFERED=1

# Prefer a local venv if present (mirrors run_gui.bat behavior).
PYEXE=""
if [[ -x ".venv/bin/python" ]]; then
  PYEXE="./.venv/bin/python"
elif [[ -x "venv/bin/python" ]]; then
  PYEXE="./venv/bin/python"
elif [[ -x "env/bin/python" ]]; then
  PYEXE="./env/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PYEXE="$(command -v python3)"
elif command -v python >/dev/null 2>&1; then
  PYEXE="$(command -v python)"
else
  echo "ERROR: No Python interpreter found." >&2
  exit 1
fi

exec "$PYEXE" -u run_gui.py "$@"
