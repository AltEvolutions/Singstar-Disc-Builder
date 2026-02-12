"""Qt main window geometry/state persistence (robust, portable).

This replaces the older saveGeometry()/restoreGeometry() base64 approach which
proved flaky on some Windows setups (especially when restoring windowed mode).

Principles:
- Store window state separately from song selection state to avoid frequent writes.
- Persist a simple "normal rect" (x, y, w, h) + a maximized flag.
- Apply a soft clamp only when the window would otherwise be mostly off-screen.
- Be best-effort and never crash the GUI.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from .ui_helpers import qt_window_state_path


@dataclass(frozen=True)
class WindowRect:
    x: int
    y: int
    w: int
    h: int

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> Optional["WindowRect"]:
        try:
            x = int(d.get("x"))
            y = int(d.get("y"))
            w = int(d.get("w"))
            h = int(d.get("h"))
        except Exception:
            return None
        if w <= 100 or h <= 100:
            return None
        # Extremely huge sizes are almost certainly bad state.
        if w > 20000 or h > 20000:
            return None
        return cls(x=x, y=y, w=w, h=h)

    def to_dict(self) -> Dict[str, int]:
        return {"x": int(self.x), "y": int(self.y), "w": int(self.w), "h": int(self.h)}


def _read_json(p: Path) -> Dict[str, Any]:
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            return raw
    except Exception:
        pass
    return {}


def _write_json(p: Path, data: Dict[str, Any]) -> None:
    try:
        p.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    except Exception:
        pass


def _available_geometry_for_window(mw):
    try:
        screen = mw.screen()
    except Exception:
        screen = None
    try:
        if screen is None:
            screen = QApplication.primaryScreen()
    except Exception:
        screen = None
    if screen is None:
        return None
    try:
        return screen.availableGeometry()
    except Exception:
        return None


def _soft_clamp_rect(mw, rect: WindowRect) -> WindowRect:
    """Soft clamp: only intervene if the window would be mostly off-screen."""
    try:
        avail = _available_geometry_for_window(mw)
        if avail is None:
            return rect
        left = int(avail.left())
        top = int(avail.top())
        aw = int(avail.width())
        ah = int(avail.height())
        if aw <= 0 or ah <= 0:
            return rect
        right = left + aw
        bottom = top + ah
    except Exception:
        return rect

    gx, gy, gw, gh = int(rect.x), int(rect.y), int(rect.w), int(rect.h)

    # Tolerate small negative offsets (Windows invisible borders/shadows).
    tol = 32

    # If absurdly large, shrink and center.
    try:
        oversize = 140  # tolerate modest oversize vs available
        if (gw > aw + oversize) or (gh > ah + oversize):
            margin = 10
            gw = max(260, min(gw, aw - margin))
            gh = max(240, min(gh, ah - margin))
            gx = left + max(0, (aw - gw) // 2)
            gy = top + max(0, (ah - gh) // 2)
    except Exception:
        pass

    # Compute visible area ratio for a simple rect intersection.
    ix1 = max(gx, left)
    iy1 = max(gy, top)
    ix2 = min(gx + gw, right)
    iy2 = min(gy + gh, bottom)
    iw = max(0, ix2 - ix1)
    ih = max(0, iy2 - iy1)
    inter_area = int(iw) * int(ih)
    win_area = int(max(1, gw)) * int(max(1, gh))
    visible_ratio = float(inter_area) / float(win_area)

    if visible_ratio >= 0.35:
        return WindowRect(gx, gy, gw, gh)

    # Mostly off-screen: clamp into view.
    if gx < (left - tol):
        gx = left
    if gy < (top - tol):
        gy = top

    max_x = int(right - gw)
    max_y = int(bottom - gh)
    if gx > (max_x + tol):
        gx = max_x
    if gy > (max_y + tol):
        gy = max_y

    return WindowRect(gx, gy, gw, gh)


def load_window_state() -> Tuple[Optional[bool], Optional[WindowRect]]:
    """Return (is_maximized, normal_rect) from the window state file."""
    try:
        p = qt_window_state_path()
    except Exception:
        return (None, None)
    if not p.exists():
        return (None, None)

    raw = _read_json(p)
    if not raw:
        return (None, None)

    is_max = None
    try:
        if "window_is_maximized" in raw:
            is_max = bool(raw.get("window_is_maximized", False))
    except Exception:
        is_max = None

    rect = None
    try:
        nr = raw.get("normal_rect")
        if isinstance(nr, dict):
            rect = WindowRect.from_dict(nr)
    except Exception:
        rect = None

    return (is_max, rect)


def apply_window_state_on_first_show(mw) -> bool:
    """Apply saved state to an already-constructed window.

    Returns True if any saved state was applied.
    """
    is_max, rect = load_window_state()
    applied = False

    # Apply the normal rect first (so restore-down has a sane target).
    if rect is not None:
        try:
            rect2 = _soft_clamp_rect(mw, rect)
            mw.setGeometry(int(rect2.x), int(rect2.y), int(rect2.w), int(rect2.h))
            applied = True
        except Exception:
            pass

    # Apply maximized last (defer one tick for Windows reliability).
    if is_max is True:
        try:
            QTimer.singleShot(0, mw.showMaximized)
            applied = True
        except Exception:
            try:
                mw.showMaximized()
                applied = True
            except Exception:
                pass

    return bool(applied)


def _capture_normal_rect_best_effort(mw) -> Optional[WindowRect]:
    """Capture the best available 'normal' window rect."""
    # Prefer the tracked stable rect if present.
    try:
        tr = getattr(mw, "_qt_last_normal_rect", None)
        if isinstance(tr, (tuple, list)) and len(tr) == 4:
            x, y, w, h = (int(tr[0]), int(tr[1]), int(tr[2]), int(tr[3]))
            r = WindowRect(x=x, y=y, w=w, h=h)
            return r
    except Exception:
        pass

    # QWidget.normalGeometry() is usually the right answer, including for maximized windows.
    try:
        ng = mw.normalGeometry()
        x = int(ng.x())
        y = int(ng.y())
        w = int(ng.width())
        h = int(ng.height())
        r = WindowRect(x=x, y=y, w=w, h=h)
        return r
    except Exception:
        pass

    # Fallback to current geometry.
    try:
        g = mw.geometry()
        x = int(g.x())
        y = int(g.y())
        w = int(g.width())
        h = int(g.height())
        r = WindowRect(x=x, y=y, w=w, h=h)
        return r
    except Exception:
        return None


def save_window_state(mw) -> None:
    """Persist window state at shutdown (best-effort)."""
    try:
        p = qt_window_state_path()
    except Exception:
        return

    # Maximized flag: prefer the last stable value tracked while running.
    is_max = None
    try:
        is_max = getattr(mw, "_qt_last_window_is_maximized", None)
    except Exception:
        is_max = None
    if is_max is None:
        try:
            is_max = bool(mw.isMaximized())
        except Exception:
            is_max = None

    rect = _capture_normal_rect_best_effort(mw)
    if rect is not None:
        try:
            rect = _soft_clamp_rect(mw, rect)
        except Exception:
            pass

    payload: Dict[str, Any] = {"window_state_version": 1}
    if rect is not None:
        payload["normal_rect"] = rect.to_dict()
    if is_max is not None:
        payload["window_is_maximized"] = bool(is_max)

    _write_json(p, payload)
