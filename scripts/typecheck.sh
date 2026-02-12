#!/usr/bin/env bash
set -euo pipefail

if ! python -c "import mypy" >/dev/null 2>&1; then
  echo "mypy is not installed. Install dev deps: python -m pip install -r requirements-dev.txt" >&2
  exit 2
fi

python -m mypy
