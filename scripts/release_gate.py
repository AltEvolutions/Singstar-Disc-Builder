#!/usr/bin/env python3
"""Release gate convenience runner.

Runs the same checks as the smoke scripts (compile + tests + lint + typecheck),
and can optionally package a code-only FULL_CODE zip under ./dist/.

This is intentionally lightweight and has no external dependencies.
"""

from __future__ import annotations

import argparse
import fnmatch
import re
import subprocess
import sys
import zipfile
from pathlib import Path


def _repo_root() -> Path:
    # scripts/release_gate.py -> repo root
    return Path(__file__).resolve().parents[1]


def _read_version(repo_root: Path) -> str:
    p = repo_root / "spcdb_tool" / "__init__.py"
    s = p.read_text(encoding="utf-8")
    m = re.search(r"__version__\s*=\s*['\"]([^'\"]+)['\"]", s)
    if not m:
        raise RuntimeError(f"Could not parse __version__ from {p}")
    return m.group(1)


def _run(cmd: list[str], *, cwd: Path) -> None:
    print("[release_gate] " + " ".join(cmd))
    subprocess.run(cmd, cwd=str(cwd), check=True)


def _is_excluded(rel_posix: str) -> bool:
    # Normalize for matching
    rp = rel_posix

    # Always skip version control and common caches/build outputs
    top = rp.split("/", 1)[0]
    if top in {
        ".git",
        ".venv",
        "venv",
        "ENV",
        "build",
        "dist",
        "htmlcov",
        ".mypy_cache",
        ".ruff_cache",
        ".pytest_cache",
    }:
        return True

    parts = rp.split("/")
    if any(p in {"__pycache__", "logs", "_index_cache", "*.egg-info"} for p in parts):
        # Note: "*.egg-info" here is literal; also handled below via fnmatch.
        pass

    # Directory-name based excludes
    for part in parts:
        if part == "__pycache__":
            return True
        if part == "logs":
            return True
        if part == "_index_cache":
            return True
        if part.endswith(".egg-info"):
            return True

    # File-name based excludes
    base = parts[-1]
    if base in {".DS_Store", "Thumbs.db", "coverage.xml", ".coverage"}:
        return True
    if base.startswith(".coverage."):
        return True
    if base.endswith((".pyc", ".pyo", ".log")):
        return True

    # Support bundle artifacts
    if fnmatch.fnmatch(base, "spcdb_support_*.zip"):
        return True

    return False


def _make_zip(repo_root: Path, out_zip: Path) -> None:
    out_zip.parent.mkdir(parents=True, exist_ok=True)
    if out_zip.exists():
        out_zip.unlink()

    # Create a deterministic-ish zip (timestamps are still filesystem-based).
    with zipfile.ZipFile(out_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for abs_path in repo_root.rglob("*"):
            if abs_path.is_dir():
                continue
            rel = abs_path.relative_to(repo_root)
            rel_posix = rel.as_posix()
            if _is_excluded(rel_posix):
                continue

            # Prevent accidentally zipping the output zip itself if run from repo root
            if rel_posix == out_zip.relative_to(repo_root).as_posix():
                continue

            zf.write(abs_path, rel_posix)


def main(argv: list[str] | None = None) -> int:
    repo_root = _repo_root()

    ap = argparse.ArgumentParser(description="Release gate: smoke checks + optional FULL_CODE zip")
    ap.add_argument("--with-support-bundle", action="store_true", help="Also generate a privacy-safe support bundle under dist/.")
    ap.add_argument("--no-zip", action="store_true", help="Skip creating the FULL_CODE zip.")
    ap.add_argument("--outdir", default="dist", help="Output directory for artifacts (default: dist)")

    args = ap.parse_args(argv)

    version = _read_version(repo_root)
    outdir = (repo_root / args.outdir).resolve()

    print(f"[release_gate] repo: {repo_root}")
    print(f"[release_gate] python: {sys.executable}")
    print(f"[release_gate] version: {version}")

    print('[release_gate] tip: if ruff/mypy are missing, install: python -m pip install -r requirements-dev.txt')

    # --- checks (same intent as scripts/smoke.*) ---
    _run([sys.executable, "-B", "-m", "compileall", "spcdb_tool"], cwd=repo_root)
    print("[release_gate] compileall: ok")

    _run([sys.executable, "-m", "pytest", "-q"], cwd=repo_root)
    print("[release_gate] pytest: ok")

    _run([sys.executable, "-m", "ruff", "check", ".", "--force-exclude"], cwd=repo_root)
    print("[release_gate] ruff: ok")

    # Use repo config from pyproject.toml (tool.mypy).
    # Running without explicit targets allows the config `files=` list to control scope.
    _run([sys.executable, "-m", "mypy"], cwd=repo_root)
    print("[release_gate] mypy: ok")

    if args.with_support_bundle:
        outdir.mkdir(parents=True, exist_ok=True)
        out = outdir / "spcdb_support_smoke.zip"
        if out.exists():
            out.unlink()
        _run([sys.executable, "-m", "spcdb_tool", "support-bundle", "--out", str(out)], cwd=repo_root)
        if not out.exists():
            raise RuntimeError(f"Expected support bundle at {out}, but it was not created")
        print(f"[release_gate] support bundle: {out}")

    if not args.no_zip:
        zip_name = f"SSPCDB_v{version}_FULL_CODE.zip"
        out_zip = outdir / zip_name
        _make_zip(repo_root, out_zip)
        if not out_zip.exists():
            raise RuntimeError(f"Expected zip at {out_zip}, but it was not created")
        size_mb = out_zip.stat().st_size / (1024 * 1024)
        print(f"[release_gate] full-code zip: {out_zip} ({size_mb:.2f} MB)")

    print("[release_gate] all good")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
