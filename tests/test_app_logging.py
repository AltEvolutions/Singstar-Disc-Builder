from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest

import spcdb_tool.app_logging as al


def _reset_app_logging_state() -> None:
    for attr in ("_initialised", "_log_path"):
        if hasattr(al.init_app_logging, attr):
            delattr(al.init_app_logging, attr)


def test_find_app_root_prefers_readme(tmp_path: Path) -> None:
    # Create a fake tree where the README is two levels up.
    root = tmp_path / "APPROOT"
    pkg = root / "spcdb_tool" / "subpkg"
    pkg.mkdir(parents=True, exist_ok=True)
    (root / "README.md").write_text("hi", encoding="utf-8")

    found = al._find_app_root(pkg)
    assert found.resolve() == root.resolve()


def test_init_app_logging_creates_log_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Force app root to our temp path so we don't pollute the repo.
    monkeypatch.setattr(al, "_find_app_root", lambda _start: tmp_path)
    monkeypatch.setattr(al, "LOGS_DIRNAME", "logs_test")

    _reset_app_logging_state()

    orig_out, orig_err, orig_hook = sys.stdout, sys.stderr, sys.excepthook
    try:
        lp = al.init_app_logging(component="unit")
        assert lp is not None
        assert lp.exists()
        assert lp.parent.name == "logs_test"

        assert al.current_log_path() == lp
        assert al.current_logs_dir() == lp.parent

        # Exercise _Tee: write something through stdout, flush.
        sys.stdout.write("hello\n")
        sys.stdout.flush()

        # Ensure we can log and the root logger has a file handler.
        logging.getLogger("spcdb_tool").info("test log line")
    finally:
        # Restore global state to avoid impacting other tests.
        sys.stdout, sys.stderr, sys.excepthook = orig_out, orig_err, orig_hook

        # Remove any file handlers we added, so Windows can delete the file too.
        root_logger = logging.getLogger()
        for h in list(root_logger.handlers):
            if isinstance(h, logging.FileHandler):
                try:
                    h.close()
                except Exception:
                    pass
                root_logger.removeHandler(h)

        # Clean up our logs dir.
        logs_dir = tmp_path / "logs_test"
        if logs_dir.exists():
            import shutil
            shutil.rmtree(logs_dir, ignore_errors=True)

        _reset_app_logging_state()


def test_logs_dir_creates_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(al, "_find_app_root", lambda _start: tmp_path)
    monkeypatch.setattr(al, "LOGS_DIRNAME", "logs_test2")

    p = al.logs_dir()
    assert p is not None
    assert Path(p).exists()
