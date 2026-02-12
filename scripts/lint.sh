#!/usr/bin/env bash
set -euo pipefail

# Run Ruff via the active Python environment so PATH issues don't matter.
# Usage:
#   ./scripts/lint.sh
#   ./scripts/lint.sh --fix

if python -m ruff --version >/dev/null 2>&1; then
  python -m ruff check . "$@"
else
  echo "Ruff is not installed in this Python environment." >&2
  echo "Install dev deps: python -m pip install -r requirements-dev.txt" >&2
  exit 2
fi
