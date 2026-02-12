from __future__ import annotations

import logging
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Optional, TextIO, cast

from .constants import LOGS_DIRNAME


_LOG = logging.getLogger("spcdb_tool")


def _find_app_root(start: Path) -> Path:
    """Best-effort "app root" finder.

    Prefers a folder that contains run_gui.bat (portable zip use-case), otherwise
    falls back to the current working directory.
    """
    try:
        cur = start
        for _ in range(8):
            if (cur / "run_gui.bat").is_file() or (cur / "README.md").is_file():
                return cur
            if cur.parent == cur:
                break
            cur = cur.parent
    except Exception:
        pass
    try:
        return Path.cwd()
    except Exception:
        return start


class _Tee:
    """Write to two streams (used to mirror stdout/stderr to a file)."""

    def __init__(self, primary, secondary) -> None:
        self._primary = primary
        self._secondary = secondary

    def write(self, s: str) -> int:
        n = 0
        try:
            n = self._primary.write(s)
        except Exception:
            pass
        try:
            self._secondary.write(s)
        except Exception:
            pass
        return n

    def flush(self) -> None:
        try:
            self._primary.flush()
        except Exception:
            pass
        try:
            self._secondary.flush()
        except Exception:
            pass


def init_app_logging(component: str = "app") -> Optional[Path]:
    """Initialise per-run log file under ./logs.

    Creates a timestamped log file and:
      * attaches a FileHandler to the `logging` root
      * tees stdout/stderr into the same file
      * installs an excepthook to capture uncaught exceptions

    Returns the log file path on success, otherwise None.
    """
    # Avoid double-initialisation
    if getattr(init_app_logging, "_initialised", False):
        return getattr(init_app_logging, "_log_path", None)

    try:
        pkg_dir = Path(__file__).resolve().parent
        root = _find_app_root(pkg_dir)
        logs_dir = root / LOGS_DIRNAME
        logs_dir.mkdir(parents=True, exist_ok=True)

        ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        log_path = logs_dir / f"{component}_{ts}.log"

        # Determine log level
        lvl_name = str(os.environ.get("SPCDB_LOG_LEVEL", "INFO") or "INFO").upper().strip()
        level = getattr(logging, lvl_name, logging.INFO)

        # Configure logging to file only (we tee stdout/stderr separately)
        root_logger = logging.getLogger()
        root_logger.setLevel(level)
        fh = logging.FileHandler(log_path, encoding="utf-8")
        fh.setLevel(level)
        fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
        root_logger.addHandler(fh)

        # Optional console handler (so run_gui.bat isn't a blank window).
        try:
            to_console = str(os.environ.get("SPCDB_LOG_TO_CONSOLE", "") or "").strip().lower()
            if to_console in ("1", "true", "yes", "on"):
                sh = logging.StreamHandler(sys.stdout)
                sh.setLevel(level)
                sh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
                root_logger.addHandler(sh)
        except Exception:
            pass


        # Tee stdout/stderr to file
        try:
            f = open(log_path, "a", encoding="utf-8", buffering=1)
            # _Tee intentionally implements only the stream methods we use;
            # cast keeps mypy happy while preserving runtime behavior.
            sys.stdout = cast(TextIO, _Tee(sys.stdout, f))
            sys.stderr = cast(TextIO, _Tee(sys.stderr, f))
        except Exception:
            # If tee fails, the file handler still captures logging.
            pass

        def _excepthook(exc_type, exc, tb):
            try:
                _LOG.error("Uncaught exception:\n%s", "".join(traceback.format_exception(exc_type, exc, tb)))
            except Exception:
                pass
            try:
                # Preserve default behaviour too.
                sys.__excepthook__(exc_type, exc, tb)
            except Exception:
                pass

        try:
            sys.excepthook = _excepthook
        except Exception:
            pass

        # Header
        try:
            from . import __version__
            _LOG.info("=== SingStar Disc Builder %s (%s) ===", __version__, component)
            _LOG.info("cwd=%s", str(Path.cwd()))
            _LOG.info("python=%s", sys.version.replace("\n", " "))
        except Exception:
            pass

        setattr(init_app_logging, "_initialised", True)
        setattr(init_app_logging, "_log_path", log_path)
        return log_path
    except Exception:
        return None


def current_log_path() -> Optional[Path]:
    """Return the current per-run log path, if logging was initialised."""
    try:
        return getattr(init_app_logging, "_log_path", None)
    except Exception:
        return None


def current_logs_dir() -> Optional[Path]:
    """Return the logs directory path (best-effort).

    If logging is initialised, this is the parent folder of the current log file.
    Otherwise we compute the portable app root and return <root>/logs.
    """
    try:
        lp = current_log_path()
        if lp is not None:
            try:
                return Path(lp).parent
            except Exception:
                pass
    except Exception:
        pass

    try:
        pkg_dir = Path(__file__).resolve().parent
        root = _find_app_root(pkg_dir)
        return (root / LOGS_DIRNAME)
    except Exception:
        return None


def logs_dir() -> Optional[Path]:
    """Return the logs directory used by the app (best-effort)."""
    try:
        pkg_dir = Path(__file__).resolve().parent
        root = _find_app_root(pkg_dir)
        logs = root / LOGS_DIRNAME
        try:
            logs.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        return logs
    except Exception:
        return None

