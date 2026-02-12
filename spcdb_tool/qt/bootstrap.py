"""Qt GUI bootstrap helpers (internal).

Extracted from `spcdb_tool/qt_app.py` during the incremental Qt refactor.

Important: this module must NOT import PySide6 at import time. All Qt objects
are passed in by the caller after PySide6 is successfully imported.
"""

from __future__ import annotations

import json

from datetime import datetime
from pathlib import Path
from typing import Callable, Optional


def start_qt_boot_trace(logs_dir: Optional[Path] = None) -> Callable[[str], None]:
    """Create a per-run boot trace writer.

    Behavior matches the historical inline boot trace:
    - Writes to <cwd>/logs/qt_boot_trace_<timestamp>.log
    - Never throws (best-effort only)
    - Adds an atexit marker
    """
    try:
        _logs_dir = logs_dir or (Path.cwd() / 'logs')
        _logs_dir.mkdir(parents=True, exist_ok=True)
        _ts = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        _boot_path = _logs_dir / f'qt_boot_trace_{_ts}.log'
    except Exception:
        # Fall back to a dummy writer.
        def _noop(_m: str) -> None:
            return

        return _noop

    def _qt_boot(_m: str) -> None:
        try:
            with _boot_path.open('a', encoding='utf-8', errors='replace') as _fp:
                _fp.write(str(_m) + '\n')
        except Exception:
            pass

    _qt_boot('[boot] created')

    try:
        import atexit

        atexit.register(lambda: _qt_boot('atexit reached'))
    except Exception:
        pass

    return _qt_boot


def install_killtimer_message_suppression(q_install_message_handler, qt_boot: Callable[[str], None]) -> None:
    """Suppress a benign Qt warning printed on some startup paths.

    Specifically:
      QObject::killTimer: Timers cannot be stopped from another thread
    """
    try:
        import sys

        qt_boot('qt_message_handler: installing')
        prev = {'handler': None}

        def _qt_msg_handler(msg_type, context, message):
            try:
                if isinstance(message, str) and message.startswith(
                    'QObject::killTimer: Timers cannot be stopped from another thread'
                ):
                    return
            except Exception:
                pass

            try:
                ph = prev.get('handler')
                if ph is not None:
                    ph(msg_type, context, message)
                else:
                    sys.stderr.write(str(message) + '\n')
            except Exception:
                pass

        prev['handler'] = q_install_message_handler(_qt_msg_handler)
    except Exception:
        # Never let boot be blocked by the handler.
        return


def show_splash(*, app, Qt, QSplashScreen, QPixmap, icon_path: Path):
    """Show a short splash screen if an icon is available.

    Returns the QSplashScreen instance or None.
    """
    splash = None
    try:
        if icon_path.exists():
            pm = QPixmap(str(icon_path))
            if not pm.isNull():
                pm = pm.scaled(420, 420, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                splash = QSplashScreen(pm)
                try:
                    splash.setWindowFlag(Qt.WindowStaysOnTopHint, True)
                except Exception:
                    pass
                splash.show()
                try:
                    app.processEvents()
                except Exception:
                    pass
    except Exception:
        splash = None
    return splash


def show_main_window_smart(*, app, win, QCursor) -> None:
    """Show the main window sized appropriately for the current screen.

    If a saved window state exists, respect it.
    Otherwise (first run), open windowed centered at a fit-to-content size (clamped to the screen).
    """
    try:
        # If we have a saved window state, respect it. This prevents
        # the startup heuristic (maximized on large screens) from fighting
        # the user's saved *windowed* geometry.
        try:
            from .ui_helpers import qt_window_state_path as _qt_window_state_path
        except Exception:
            _qt_window_state_path = None
        try:
            from .ui_helpers import qt_state_path as _qt_state_path
        except Exception:
            _qt_state_path = None

        _saved_mode = None

        # Prefer the dedicated window state file (v0.9.128+).
        try:
            if callable(_qt_window_state_path):
                _p = _qt_window_state_path()
                if _p.exists():
                    _raw = json.loads(_p.read_text(encoding="utf-8"))
                    if isinstance(_raw, dict):
                        if "window_is_maximized" in _raw:
                            _saved_mode = "max" if bool(_raw.get("window_is_maximized", False)) else "win"
                        elif isinstance(_raw.get("normal_rect"), dict):
                            _saved_mode = "win"
        except Exception:
            _saved_mode = None

        # Legacy fallback: older song selection file may still include window bits.
        if _saved_mode is None:
            try:
                if callable(_qt_state_path):
                    _p = _qt_state_path()
                    if _p.exists():
                        _raw = json.loads(_p.read_text(encoding="utf-8"))
                        if isinstance(_raw, dict):
                            if "window_is_maximized" in _raw:
                                _saved_mode = "max" if bool(_raw.get("window_is_maximized", False)) else "win"
                            elif str(_raw.get("window_geometry_b64", "") or "").strip():
                                _saved_mode = "win"
            except Exception:
                _saved_mode = None

        if _saved_mode == 'max':
            win.showMaximized()
            return
        if _saved_mode == 'win':
            win.show()
            return

        # Pick the screen under the cursor if possible (multi-monitor friendly).
        _screen = None
        try:
            _pos = QCursor.pos()
        except Exception:
            _pos = None

        try:
            _screens = list(app.screens() or [])
        except Exception:
            _screens = []

        if _pos is not None and _screens:
            for _s in _screens:
                try:
                    if _s.geometry().contains(_pos):
                        _screen = _s
                        break
                except Exception:
                    continue

        if _screen is None:
            try:
                _screen = app.primaryScreen()
            except Exception:
                _screen = _screens[0] if _screens else None

        if _screen is None:
            win.showMaximized()
            return

        _avail = _screen.availableGeometry()
        _aw = int(_avail.width())
        _ah = int(_avail.height())

        # First-run default (no saved window state):
        # Try to size to the UI's preferred size (fit-to-content) so the user sees the
        # full layout without unnecessary scrolling on first launch. Clamp to the
        # available screen geometry and keep it centered.
        _pref_w = 0
        _pref_h = 0

        try:
            win.ensurePolished()
        except Exception:
            pass

        try:
            _sh = win.sizeHint()
            _pref_w = max(_pref_w, int(_sh.width()))
            _pref_h = max(_pref_h, int(_sh.height()))
        except Exception:
            pass

        try:
            _msh = win.minimumSizeHint()
            _pref_w = max(_pref_w, int(_msh.width()))
            _pref_h = max(_pref_h, int(_msh.height()))
        except Exception:
            pass

        try:
            _cw = win.centralWidget()
            if _cw is not None:
                _cw_msh = _cw.minimumSizeHint()
                _pref_w = max(_pref_w, int(_cw_msh.width()))
                _pref_h = max(_pref_h, int(_cw_msh.height()))
        except Exception:
            pass

        # Safety floors so the UI never starts tiny.
        _pref_w = max(960, _pref_w)
        _pref_h = max(720, _pref_h)

        # Expand to at least ~90% of the available screen, but if the content needs
        # more (and the screen allows it), grow further up to the full available size.
        _w = min(_aw, max(_pref_w, int(_aw * 0.90)))
        _h = min(_ah, max(_pref_h, int(_ah * 0.90)))

        try:
            win.resize(_w, _h)
        except Exception:
            pass

        try:
            _left = int(_avail.left())
            _top = int(_avail.top())
            _x = _left + max(0, (_aw - _w) // 2)
            _y = _top + max(0, (_ah - _h) // 2)
            win.move(_x, _y)
        except Exception:
            pass

        win.show()
    except Exception:
        try:
            win.showMaximized()
        except Exception:
            try:
                win.show()
            except Exception:
                pass
