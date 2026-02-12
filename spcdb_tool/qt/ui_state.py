"""Qt UI state persistence + window geometry helpers (extracted from MainWindow).

This module is intentionally defensive: most helpers are best-effort and should never crash the GUI.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Dict

from PySide6.QtCore import QByteArray, QTimer, QObject, QEvent, Qt
from PySide6.QtWidgets import QApplication


def _capture_normal_window_geometry_b64(mw) -> str:
    """Capture a stable *normal* (non-maximized) window geometry snapshot.

    We intentionally avoid capturing geometry while maximized/minimized, because
    some platforms temporarily switch state during shutdown which can produce a
    bogus (0,0) / tiny geometry when closing.
    """
    try:
        # Only after first show, otherwise geometry is often meaningless.
        if not bool(getattr(mw, "_did_first_show", False)):
            return ""
    except Exception:
        return ""

    try:
        st = int(mw.windowState())
        if st & int(Qt.WindowMaximized) or st & int(Qt.WindowMinimized):
            return ""
    except Exception:
        pass

    try:
        g = mw.saveGeometry()
        b64 = bytes(g.toBase64()).decode("ascii")
        return str(b64 or "")
    except Exception:
        return ""




def _capture_normal_window_rect_tuple(mw):
    """Capture a stable normal-geometry tuple (x, y, w, h) or None."""
    try:
        if not bool(getattr(mw, "_did_first_show", False)):
            return None
    except Exception:
        return None

    try:
        st = int(mw.windowState())
        if st & int(Qt.WindowMinimized):
            return None
    except Exception:
        pass

    try:
        ng = mw.normalGeometry()
        x = int(ng.x())
        y = int(ng.y())
        w = int(ng.width())
        h = int(ng.height())
        if w <= 100 or h <= 100:
            return None
        if w > 20000 or h > 20000:
            return None
        return (x, y, w, h)
    except Exception:
        return None
class _WindowStateTracker(QObject):
    """Tracks last-stable window state/geometry to survive shutdown quirks."""

    def __init__(self, mw) -> None:
        super().__init__(mw)
        self._mw = mw

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if obj is not self._mw:
            return False

        try:
            et = int(event.type())
        except Exception:
            return False

        # Mark shutdown as early as possible so later WindowStateChange events
        # during close can't overwrite the last-stable "maximized" flag.
        if et == int(QEvent.Close):
            try:
                setattr(self._mw, "_qt_shutting_down", True)
            except Exception:
                pass
            return False

        # Once shutdown is requested, ignore further window state/geometry updates.
        try:
            if bool(getattr(self._mw, "_qt_shutting_down", False)):
                return False
        except Exception:
            pass

        if et == int(QEvent.WindowStateChange):
            try:
                now = float(time.monotonic())
            except Exception:
                now = 0.0

            try:
                old = int(getattr(event, "oldState")())
            except Exception:
                old = None
            try:
                new = int(self._mw.windowState())
            except Exception:
                new = None

            try:
                setattr(self._mw, "_qt_last_state_change_ts", now)
                setattr(self._mw, "_qt_last_state_old", old)
                setattr(self._mw, "_qt_last_state_new", new)
            except Exception:
                pass

            try:
                is_max = False
                try:
                    is_max = bool(int(self._mw.windowState()) & int(Qt.WindowMaximized))
                except Exception:
                    is_max = bool(self._mw.isMaximized())
                setattr(self._mw, "_qt_last_window_is_maximized", bool(is_max))
            except Exception:
                pass

            # If we went from maximized -> normal, do NOT immediately capture geometry;
            # it may be the shutdown transition. Instead, delay capture slightly.
            try:
                if (old is not None) and (new is not None) and (int(old) & int(Qt.WindowMaximized)) and not (int(new) & int(Qt.WindowMaximized)):
                    try:
                        setattr(self._mw, "_qt_ignore_normal_geom_until_ts", float(now) + 0.9)
                    except Exception:
                        pass

                    def _late_capture():
                        try:
                            b64 = _capture_normal_window_geometry_b64(self._mw)
                            if b64:
                                setattr(self._mw, "_qt_last_normal_geometry_b64", b64)

                        except Exception:
                            pass

                    try:
                        QTimer.singleShot(350, _late_capture)
                    except Exception:
                        pass
            except Exception:
                pass

            return False

        # Regular geometry capture while running (move/resize/show).
        if et in (int(QEvent.Move), int(QEvent.Resize), int(QEvent.Show)):
            try:
                if not bool(getattr(self._mw, "_did_first_show", False)):
                    return False
            except Exception:
                return False

            try:
                now = float(time.monotonic())
            except Exception:
                now = 0.0
            try:
                ignore_until = float(getattr(self._mw, "_qt_ignore_normal_geom_until_ts", 0.0) or 0.0)
            except Exception:
                ignore_until = 0.0
            if (ignore_until > 0.0) and (now > 0.0) and (now < ignore_until):
                return False

            try:
                b64 = _capture_normal_window_geometry_b64(self._mw)
                if b64:
                    setattr(self._mw, "_qt_last_normal_geometry_b64", b64)
                try:
                    rt = _capture_normal_window_rect_tuple(self._mw)
                    if rt:
                        setattr(self._mw, "_qt_last_normal_rect", rt)
                except Exception:
                    pass

            except Exception:
                pass

            try:
                is_max = bool(int(self._mw.windowState()) & int(Qt.WindowMaximized))
                setattr(self._mw, "_qt_last_window_is_maximized", bool(is_max))
            except Exception:
                pass

        return False


def install_window_state_tracker(mw) -> None:
    """Install a window state/geometry tracker onto the MainWindow (best-effort)."""
    try:
        if getattr(mw, "_qt_window_state_tracker", None) is not None:
            return
    except Exception:
        pass

    try:
        setattr(mw, "_qt_shutting_down", False)
    except Exception:
        pass

    try:
        tr = _WindowStateTracker(mw)
        mw.installEventFilter(tr)
        setattr(mw, "_qt_window_state_tracker", tr)
    except Exception:
        return

    try:
        is_max = bool(int(mw.windowState()) & int(Qt.WindowMaximized))
        setattr(mw, "_qt_last_window_is_maximized", bool(is_max))
    except Exception:
        pass
    try:
        b64 = _capture_normal_window_geometry_b64(mw)
        if b64:
            setattr(mw, "_qt_last_normal_geometry_b64", b64)
            try:
                rt = _capture_normal_window_rect_tuple(mw)
                if rt:
                    setattr(mw, "_qt_last_normal_rect", rt)
            except Exception:
                pass
    except Exception:
        pass
def restore_window_geometry(mw) -> None:
    """Restore window geometry/maximized flag from the Qt state file (best-effort).

    Sets:
      - mw._qt_window_geometry_loaded (bool)
      - mw._qt_window_was_maximized (bool)
    """
    # Default
    try:
        mw._qt_window_geometry_loaded = False
        mw._qt_window_was_maximized = False
    except Exception:
        pass

    try:
        p: Path = mw._qt_state_path()
    except Exception:
        return
    if not p.exists():
        return

    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return

    try:
        wgeo = raw.get("window_geometry_b64")
        ws = str(wgeo or "").strip() if isinstance(wgeo, str) else ""
        if ws:
            try:
                ba = QByteArray.fromBase64(ws.encode("ascii"))
            except Exception:
                try:
                    ba = QByteArray.fromBase64(QByteArray(ws.encode("ascii")))
                except Exception:
                    ba = QByteArray()
            try:
                ok = bool(mw.restoreGeometry(ba))
            except Exception:
                ok = False
            if ok:
                try:
                    mw._qt_window_geometry_loaded = True
                except Exception:
                    pass
    except Exception:
        pass

    try:
        mw._qt_window_was_maximized = bool(raw.get("window_is_maximized", False))
    except Exception:
        try:
            mw._qt_window_was_maximized = False
        except Exception:
            pass


def apply_default_window_geometry(mw) -> None:
    """Apply a sane default size/position when no saved geometry exists."""
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
        return
    try:
        avail = screen.availableGeometry()
    except Exception:
        return
    try:
        aw = int(avail.width())
        ah = int(avail.height())
    except Exception:
        return
    if aw <= 0 or ah <= 0:
        return

    # Aim for ~86% of the available screen, bounded for sanity.
    try:
        w = int(max(1100, min(int(aw * 0.86), 1800)))
        h = int(max(720, min(int(ah * 0.86), 1050)))
        # Never exceed screen.
        w = int(min(w, aw))
        h = int(min(h, ah))
        mw.resize(w, h)
        x = int(avail.left() + max(0, (aw - w) // 2))
        y = int(avail.top() + max(0, (ah - h) // 2))
        mw.move(x, y)
    except Exception:
        pass


def clamp_to_screen(mw) -> None:
    """Keep the window reasonably visible without snapping it to the top-left.

    This is intentionally a *soft* clamp:
      - We only intervene if the window is largely off-screen, or wildly larger than the
        available desktop area (monitor/DPI changes).
      - Small negative frame offsets (common on Windows due to invisible borders/shadows)
        are tolerated and will NOT be clamped.

    The goal is to preserve the user's intended window position/size whenever possible,
    while still preventing the app from opening completely off-screen.
    """
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
        return

    try:
        avail = screen.availableGeometry()
    except Exception:
        return
    try:
        geo = mw.frameGeometry()
    except Exception:
        return

    try:
        aw = int(avail.width())
        ah = int(avail.height())
        left = int(avail.left())
        top = int(avail.top())
        right = int(avail.right())
        bottom = int(avail.bottom())
    except Exception:
        return

    try:
        gw = int(geo.width())
        gh = int(geo.height())
        gx = int(geo.x())
        gy = int(geo.y())
    except Exception:
        return

    if aw <= 0 or ah <= 0 or gw <= 0 or gh <= 0:
        return

    # 1) If the restored window is *massively* larger than the available area,
    # shrink it and center it. (Don't "almost shrink" – that causes the annoying
    # top-left snapping the user noticed.)
    try:
        size_tol_px = 120  # tolerate small oversize due to frame/borders
        if (gw > aw + size_tol_px) or (gh > ah + size_tol_px):
            margin = 8
            w = int(max(260, min(gw, aw - margin)))
            h = int(max(240, min(gh, ah - margin)))
            mw.resize(w, h)
            # Center within the available screen area
            x = int(left + max(0, (aw - w) // 2))
            y = int(top + max(0, (ah - h) // 2))
            mw.move(x, y)
            try:
                geo = mw.frameGeometry()
                gw = int(geo.width())
                gh = int(geo.height())
                gx = int(geo.x())
                gy = int(geo.y())
            except Exception:
                pass
    except Exception:
        pass

    # 2) Only clamp position if the window is *mostly* off-screen.
    try:
        try:
            inter = geo.intersected(avail)
            inter_area = int(inter.width()) * int(inter.height())
        except Exception:
            # Manual intersection fallback
            ix1 = max(int(gx), int(left))
            iy1 = max(int(gy), int(top))
            ix2 = min(int(gx + gw), int(left + aw))
            iy2 = min(int(gy + gh), int(top + ah))
            iw = max(0, int(ix2 - ix1))
            ih = max(0, int(iy2 - iy1))
            inter_area = int(iw) * int(ih)

        win_area = int(gw) * int(gh)
        visible_ratio = float(inter_area) / float(max(1, win_area))
    except Exception:
        visible_ratio = 1.0

    # If at least ~35% is visible, do nothing (prevents "snap to top-left" on Windows).
    if visible_ratio >= 0.35:
        return

    # Otherwise, clamp the window into view (best-effort).
    try:
        tol = 24  # allow small negative border offsets
        x = gx
        y = gy

        if x < (left - tol):
            x = left
        if y < (top - tol):
            y = top

        # Qt right/bottom are inclusive.
        max_x = int(right - gw + 1)
        max_y = int(bottom - gh + 1)

        if x > (max_x + tol):
            x = max_x
        if y > (max_y + tol):
            y = max_y

        mw.move(int(x), int(y))
    except Exception:
        pass


def current_song_refresh_key(mw) -> str:
    try:
        t = mw._collect_song_targets()
        parts = [f"{str(lbl)}::{str(pth)}::{int(bool(is_base))}" for (lbl, pth, is_base) in (t or [])]
        return "|".join(parts)
    except Exception:
        return ""


def load_qt_state_into_ui(mw) -> None:
    p = mw._qt_state_path()
    if not p.exists():
        return
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return

    # ETA heuristics: per-phase EMA durations
    try:
        em = raw.get("eta_phase_ema_sec")
        d: Dict[str, float] = {}
        if isinstance(em, dict):
            for k, v in em.items():
                ks = str(k or "").strip()
                if not ks:
                    continue
                try:
                    fv = float(v)
                except Exception:
                    continue
                if fv <= 0.0:
                    continue
                d[ks] = float(fv)
        mw._eta_phase_ema_sec = d
    except Exception:
        try:
            mw._eta_phase_ema_sec = {}
        except Exception:
            pass

    # UI layout (splitters + column widths) is stored in Qt state.
    # Only apply it when present; otherwise rely on built-in defaults.
    try:
        layout = raw.get("ui_layout", None)
        if isinstance(layout, dict) and layout:
            mw._apply_ui_layout(layout)
            # Apply again after the event loop starts (helps when restoring before first show).
            try:
                QTimer.singleShot(0, lambda layout_=layout: mw._apply_ui_layout(layout_))
                # One more delayed pass helps on slow first-layout situations / different DPI screens.
                QTimer.singleShot(200, lambda layout_=layout: mw._apply_ui_layout(layout_))
            except Exception:
                pass
    except Exception:
        pass

    try:
        mw._qt_state_loaded = True
    except Exception:
        pass
    try:
        mw._qt_state_had_disabled_key = bool("disabled_song_ids" in raw)
    except Exception:
        mw._qt_state_had_disabled_key = False
    try:
        mw._qt_state_had_selected_key = bool("selected_song_ids" in raw)
    except Exception:
        mw._qt_state_had_selected_key = False
    try:
        mw._qt_state_applied_disabled_ids = False
        mw._qt_state_applied_selected_ids = False
    except Exception:
        pass
    try:
        all_ids = raw.get("all_song_ids")
        if isinstance(all_ids, list):
            mw._qt_state_last_all_song_ids = set(int(x) for x in all_ids if str(x).strip().isdigit())
    except Exception:
        mw._qt_state_last_all_song_ids = set()

    # Filters
    try:
        mw.song_search_edit.setText(str(raw.get("search") or ""))
    except Exception:
        pass
    try:
        mw.song_selected_only_chk.setChecked(bool(raw.get("selected_only", False)))
    except Exception:
        pass
    try:
        mw._qt_state_wanted_source = mw._normalize_source_key(str(raw.get("source_filter") or "All"))
    except Exception:
        mw._qt_state_wanted_source = "All"

    # Extra filter flags (0.8c)
    try:
        flags = raw.get("filter_flags") or {}
        if isinstance(flags, dict):
            mw._filter_conflicts_only = bool(flags.get("conflicts_only", False))
            mw._filter_duplicates_only = bool(flags.get("duplicates_only", False))
            mw._filter_overrides_only = bool(flags.get("overrides_only", False))
            mw._filter_disabled_only = bool(flags.get("disabled_only", False))
    except Exception:
        pass

    try:
        mw._active_preset_name = str(raw.get("active_preset") or "All songs")
        if str(mw._active_preset_name or "") == "Custom":
            mw._active_preset_name = "All songs"
    except Exception:
        mw._active_preset_name = "All songs"
    try:
        mw._qt_state_version = int(raw.get("qt_state_version", 0) or 0)
    except Exception:
        mw._qt_state_version = 0
    try:
        mw._qt_state_default_all_disabled = bool(raw.get("default_all_disabled", True))
    except Exception:
        mw._qt_state_default_all_disabled = True
    try:
        mw._qt_state_selection_initialized = bool(raw.get("selection_initialized", False))
    except Exception:
        mw._qt_state_selection_initialized = False

    # Selection state
    try:
        # Load disabled_song_ids regardless of whether the disc set changed.
        dis = raw.get("disabled_song_ids")
        if isinstance(dis, list):
            mw._disabled_song_ids = set(int(x) for x in dis if str(x).strip().isdigit())
            try:
                mw._qt_state_applied_disabled_ids = True
            except Exception:
                pass
    except Exception:
        try:
            mw._disabled_song_ids = set()
        except Exception:
            pass

    # 0.7c: conflict overrides (song_id -> winner source label)
    try:
        raw_ov = raw.get("song_source_overrides")
        ov: Dict[int, str] = {}
        if isinstance(raw_ov, dict):
            for k, v in raw_ov.items():
                try:
                    sid = int(k)
                except Exception:
                    continue
                lab = str(v or "").strip()
                if lab:
                    ov[int(sid)] = lab
        mw._song_source_overrides = ov
    except Exception:
        mw._song_source_overrides = {}


    # 0.9.199: display-duplicate keep overrides (Title+Artist -> kept song_id)
    # These are only applied when the current disc inputs match the saved refresh_key.
    try:
        saved_key = str(raw.get("refresh_key") or "")
        cur_key = current_song_refresh_key(mw)
        raw_dup = raw.get("display_dup_keep_overrides")
        if saved_key and cur_key and (saved_key != cur_key):
            raw_dup = None

        dup: Dict[str, int] = {}
        if isinstance(raw_dup, dict):
            for k, v in raw_dup.items():
                kk = str(k or "").strip()
                if not kk:
                    continue
                try:
                    sid = int(v)
                except Exception:
                    continue
                if sid > 0:
                    dup[kk] = int(sid)
        mw._display_dup_keep_overrides = dup
    except Exception:
        mw._display_dup_keep_overrides = {}

    # Back-compat: only carry explicit selected_song_ids across if the exact disc inputs match.
    try:
        saved_key = str(raw.get("refresh_key") or "")
        cur_key = current_song_refresh_key(mw)
        sel = raw.get("selected_song_ids")
        if saved_key and cur_key and (saved_key != cur_key):
            sel = None
        if isinstance(sel, list):
            mw._selected_song_ids = set(int(x) for x in sel if str(x).strip().isdigit())
            try:
                mw._qt_state_applied_selected_ids = True
            except Exception:
                pass
    except Exception:
        pass

    # Collapsed disc groups (best-effort)
    try:
        cg = raw.get("collapsed_groups")
        if isinstance(cg, list):
            mw._qt_state_collapsed_groups = [str(x) for x in cg if str(x).strip()]
    except Exception:
        mw._qt_state_collapsed_groups = []

    # Rebuild presets dropdown and set selection (best-effort)
    try:
        mw._rebuild_preset_combo()
        mw._set_preset_combo_to_name(mw._active_preset_name)
    except Exception:
        pass


def save_qt_state(mw, force: bool = False) -> None:
    try:
        now_ts = float(time.time())
    except Exception:
        now_ts = 0.0
    if (not force) and (now_ts > 0.0):
        try:
            last = float(getattr(mw, "_qt_state_last_write_ts", 0.0) or 0.0)
            if (now_ts - last) < 0.5:
                return
        except Exception:
            pass
    try:
        mw._qt_state_last_write_ts = now_ts
    except Exception:
        pass

    payload = {
        "refresh_key": current_song_refresh_key(mw),
        "search": str(mw.song_search_edit.text() or ""),
        "source_filter": str(mw._song_source_filter_key() or "All"),
        "selected_only": bool(mw.song_selected_only_chk.isChecked()),
        "filter_flags": {
            "conflicts_only": bool(getattr(mw, "_filter_conflicts_only", False)),
            "duplicates_only": bool(getattr(mw, "_filter_duplicates_only", False)),
            "overrides_only": bool(getattr(mw, "_filter_overrides_only", False)),
            "disabled_only": bool(getattr(mw, "_filter_disabled_only", False)),
        },
        "active_preset": str(getattr(mw, "_active_preset_name", "All songs") or "All songs"),
        "qt_state_version": 2,
        "default_all_disabled": bool(getattr(mw, "_qt_state_default_all_disabled", True)),
        "selection_initialized": bool(getattr(mw, "_qt_state_selection_initialized", False)),
        "disabled_song_ids": sorted(int(x) for x in (mw._disabled_song_ids or set())),
        "all_song_ids": sorted(int(x) for x in (getattr(mw, "_qt_state_last_all_song_ids", set()) or set())),
        # 0.7c: conflict overrides (song_id -> winner label)
        "song_source_overrides": {
            str(int(k)): str(v)
            for (k, v) in sorted((mw._song_source_overrides or {}).items())
            if str(v).strip()
        },

        # 0.9.199: display-duplicate keep overrides (display_key -> kept song_id)
        "display_dup_keep_overrides": {
            str(k): int(v)
            for (k, v) in sorted((getattr(mw, "_display_dup_keep_overrides", {}) or {}).items())
            if str(k).strip() and int(v) > 0
        },

        # 0.6b: persist collapsed disc groups (best-effort)
        "collapsed_groups": sorted([str(k) for (k, v) in (mw._song_group_expanded or {}).items() if not bool(v)]),
    }


    try:
        ema = getattr(mw, "_eta_phase_ema_sec", None)
        clean: Dict[str, float] = {}
        if isinstance(ema, dict):
            for k, v in ema.items():
                ks = str(k or "").strip()
                if not ks:
                    continue
                try:
                    fv = float(v)
                except Exception:
                    continue
                if fv <= 0.0:
                    continue
                clean[ks] = float(fv)
        if clean:
            payload["eta_phase_ema_sec"] = {k: float(v) for (k, v) in sorted(clean.items())}
    except Exception:
        pass

    try:
        ui_layout = mw._capture_ui_layout()
        if ui_layout:
            payload["ui_layout"] = ui_layout
    except Exception:
        pass

    try:
        p = mw._qt_state_path()
        p.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    except Exception:
        pass
