#!/usr/bin/env bash
set -euo pipefail

WITH_SUPPORT_BUNDLE=0

if [[ "${1:-}" == "--with-support-bundle" ]]; then
  WITH_SUPPORT_BUNDLE=1
  shift
fi

if [[ "${1:-}" != "" ]]; then
  echo "Usage: ./scripts/smoke.sh [--with-support-bundle]" >&2
  exit 2
fi

echo "[smoke] python: $(python --version 2>&1)"
python -m compileall spcdb_tool >/dev/null

echo "[smoke] compileall: ok"
pytest -q

echo "[smoke] pytest: ok"
./scripts/lint.sh

echo "[smoke] ruff: ok"
./scripts/typecheck.sh

echo "[smoke] mypy: ok"

if [[ "$WITH_SUPPORT_BUNDLE" == "1" ]]; then
  OUT="spcdb_support_smoke.zip"
  rm -f "$OUT"
  python -m spcdb_tool support-bundle --out "$OUT"
  if [[ ! -f "$OUT" ]]; then
    echo "[smoke] support bundle: expected $OUT but it was not created" >&2
    exit 1
  fi
  echo "[smoke] support bundle: $OUT"
fi

echo "[smoke] all good"
