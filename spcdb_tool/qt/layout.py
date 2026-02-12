
"""Qt UI layout persistence helpers (internal).

This module contains the splitter + table-column layout capture/restore logic.
It was extracted from `spcdb_tool.qt.main_window.MainWindow` to keep that file
smaller. Behaviour is intended to be unchanged.

Imported lazily via `MainWindow`.
"""

from __future__ import annotations

from PySide6.QtCore import Qt


def capture_ui_layout(win) -> dict:
    layout: dict = {}

    # Splitters
    try:
        ms = getattr(win, "_main_split", None)
        if ms is not None:
            sz = ms.sizes() or []
            if sz:
                layout["main_split_sizes"] = [int(x) for x in sz]
    except Exception:
        pass

    try:
        cs = getattr(win, "_center_split", None)
        if cs is not None:
            sz = cs.sizes() or []
            if sz:
                layout["center_split_sizes"] = [int(x) for x in sz]
    except Exception:
        pass

    # Tables (column widths)
    try:
        tbl = getattr(win, "sources_table", None)
        if tbl is not None:
            n = int(tbl.columnCount() or 0)
            if n > 0:
                layout["sources_col_widths"] = [int(tbl.columnWidth(i)) for i in range(n)]
    except Exception:
        pass

    try:
        tbl = getattr(win, "songs_table", None)
        if tbl is not None:
            n = int(tbl.columnCount() or 0)
            if n > 0:
                layout["songs_col_widths"] = [int(tbl.columnWidth(i)) for i in range(n)]
    except Exception:
        pass

    return layout


def apply_ui_layout(win, layout: dict) -> None:
    """Apply saved UI layout, scaled/clamped to the current window size.

    We store raw pixel sizes (splitters + column widths). When restoring on a
    different resolution/aspect ratio, those raw pixels can look stretched.
    This applies the saved layout proportionally to the current available size
    and clamps to reasonable mins/maxes, falling back to built-in defaults if
    the saved layout is clearly unusable.
    """

    if not isinstance(layout, dict):
        return

    def _sum_pos(vals: list[int]) -> int:
        s = 0
        for v in vals:
            try:
                iv = int(v)
            except Exception:
                continue
            if iv > 0:
                s += iv
        return int(s)

    def _normalize_to_total(vals: list[int], total: int, *, lo: int, hi: int) -> list[int] | None:
        """Clamp vals to [lo, hi] and adjust so they sum to total."""
        if total <= 0 or not vals:
            return None
        out: list[int] = []
        for v in vals:
            try:
                iv = int(v)
            except Exception:
                iv = lo
            if iv < lo:
                iv = lo
            if iv > hi:
                iv = hi
            out.append(int(iv))

        # Adjust to sum exactly to total by borrowing/giving from right-to-left.
        cur = int(sum(out))
        if cur == total:
            return out

        if cur < total:
            out[-1] = int(out[-1] + (total - cur))
            return out

        # cur > total: reduce without breaking mins.
        extra = cur - total
        for i in range(len(out) - 1, -1, -1):
            can = max(0, int(out[i] - lo))
            if can <= 0:
                continue
            take = min(extra, can)
            out[i] = int(out[i] - take)
            extra -= take
            if extra <= 0:
                break
        if extra > 0:
            return None
        return out

    def _scaled_list(saved: list[int], total: int, *, count: int, lo: int, hi: int) -> list[int] | None:
        if not isinstance(saved, list) or not saved or total <= 0:
            return None
        if count <= 0:
            return None
        if len(saved) != count:
            return None
        saved_total = _sum_pos([int(x) for x in saved])
        if saved_total <= 0:
            return None
        # Scale proportionally to current total.
        scaled = [int(round(int(x) * float(total) / float(saved_total))) for x in saved]
        return _normalize_to_total(scaled, int(total), lo=lo, hi=hi)

    def _apply_splitter(splitter, key: str) -> bool:
        try:
            saved = layout.get(key)
            if not isinstance(saved, list) or not saved:
                return True
            cur_sizes = splitter.sizes() or []
            count = len(cur_sizes)
            if count <= 0:
                return False

            # Available size in the split direction.
            try:
                if splitter.orientation() == Qt.Horizontal:
                    total = int(splitter.size().width() or 0)
                else:
                    total = int(splitter.size().height() or 0)
            except Exception:
                total = 0
            if total <= 0:
                total = int(sum(int(x) for x in cur_sizes if int(x) > 0) or 0)
            if total <= 0:
                # Too early (before first show); caller schedules another pass.
                return False

            # Reasonable bounds: keep panes usable on small screens.
            lo = max(80, int(total * 0.10))
            hi = max(lo, int(total * 0.85))

            scaled = _scaled_list([int(x) for x in saved], total, count=count, lo=lo, hi=hi)
            if scaled is None:
                return False
            splitter.setSizes([int(x) for x in scaled])
            return True
        except Exception:
            return False

    def _apply_table(tbl, key: str, *, mins: list[int] | None = None, fixed: dict[int, int] | None = None) -> bool:
        try:
            saved = layout.get(key)
            if not isinstance(saved, list) or not saved:
                return True
            n = int(tbl.columnCount() or 0)
            if n <= 0 or len(saved) != n:
                return False

            avail = int((tbl.viewport().width() if tbl.viewport() is not None else 0) or tbl.width() or 0)
            if avail <= 0:
                return False

            widths = [int(x) for x in saved[:n]]

            fixed_total = 0
            if fixed:
                for idx, w in fixed.items():
                    if 0 <= int(idx) < n:
                        widths[int(idx)] = int(w)
                        fixed_total += int(w)

            var_idxs = [i for i in range(n) if not (fixed and i in fixed)]
            var_total = _sum_pos([widths[i] for i in var_idxs])

            # Scale variable widths to fit viewport.
            target_var = max(1, int(avail - fixed_total))
            if var_total > 0:
                scale = float(target_var) / float(var_total)
            else:
                scale = 1.0

            scaled = widths[:]
            for i in var_idxs:
                scaled[i] = int(round(int(widths[i]) * scale))

            # Clamp each column.
            if mins is None or len(mins) != n:
                mins = [24 for _ in range(n)]
            lo_list = [int(x) for x in mins]
            hi_each = max(80, int(avail * 0.90))

            for i in range(n):
                lo = int(lo_list[i])
                hi = int(max(lo, hi_each))
                if fixed and i in fixed:
                    scaled[i] = int(fixed[i])
                    continue
                if scaled[i] < lo:
                    scaled[i] = lo
                if scaled[i] > hi:
                    scaled[i] = hi

            # Normalize to available width (best-effort, doesn't need to be perfect).
            # If we can't normalize cleanly, still apply clamped sizes.
            want = int(avail)
            got = int(sum(int(x) for x in scaled))
            if got > 0:
                # Only normalize if wildly off (avoids fighting user-intended scrollbars).
                if got > int(want * 1.20) or got < int(want * 0.70):
                    norm = _normalize_to_total(scaled, want, lo=24, hi=hi_each)
                    if norm is not None:
                        scaled = norm

            for i in range(n):
                try:
                    tbl.setColumnWidth(i, int(scaled[i]))
                except Exception:
                    pass
            return True
        except Exception:
            return False

    ok = True

    # Splitters
    try:
        ms = getattr(win, "_main_split", None)
        if ms is not None:
            ok = _apply_splitter(ms, "main_split_sizes") and ok
    except Exception:
        ok = False

    try:
        cs = getattr(win, "_center_split", None)
        if cs is not None:
            ok = _apply_splitter(cs, "center_split_sizes") and ok
    except Exception:
        ok = False

    # Tables (column widths)
    try:
        tbl = getattr(win, "sources_table", None)
        if tbl is not None:
            ok = _apply_table(tbl, "sources_col_widths", mins=[140, 100, 220]) and ok
    except Exception:
        ok = False

    try:
        tbl = getattr(win, "songs_table", None)
        if tbl is not None:
            ok = _apply_table(
                tbl,
                "songs_col_widths",
                mins=[44, 220, 150, 120, 220, 80],
                fixed={0: 44},
            ) and ok
    except Exception:
        ok = False

    # If the saved layout can't be applied sanely (e.g., very different screen),
    # fall back to built-in defaults so the UI remains usable.
    if not ok:
        try:
            win._apply_default_ui_splitters()
        except Exception:
            pass
        try:
            win._apply_default_ui_columns()
        except Exception:
            pass
