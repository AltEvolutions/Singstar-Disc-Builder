# ruff: noqa
from __future__ import annotations

"""Qt Songs table helpers (internal).

Extracted from `spcdb_tool/qt/main_window.py` as part of the incremental Qt refactor.
Behavior is intended to be unchanged.

Imported lazily via `MainWindow`.
"""

from typing import TYPE_CHECKING, Dict, List, Optional

from PySide6.QtCore import Qt, QEvent
from PySide6.QtWidgets import QTableWidgetItem

from ..controller import SongAgg

from .delegates import _SONGS_ROW_KIND_ROLE

if TYPE_CHECKING:
    from .main_window import MainWindow


def render_songs_table(win: "MainWindow", songs: List[SongAgg]) -> List[int]:
    """Render songs into the table.

    0.6b: Group by preferred source label, keep Base first, follow Sources order,
    and insert collapsible disc header rows.

    Returns the list of song_ids that are actually shown (used by bulk select).
    """

    # Keep the original variable name used in main_window to minimize risk.
    self = win

    shown_ids: List[int] = []
    self._songs_table_loading = True
    try:
        self._songs_header_rows = {}
        self._songs_group_song_ids = {}
        self.songs_table.setRowCount(0)

        # Group by provider (preferred_source). (May be empty if filters hide everything.)
        groups: Dict[str, List[SongAgg]] = {}
        for s in (songs or []):
            try:
                k = str(getattr(s, 'preferred_source', '') or 'Base')
            except Exception:
                k = 'Base'
            groups.setdefault(k, []).append(s)

        # Determine group order:
        # - Prefer the known disc order from the current Sources list (Base first)
        # - Append any unexpected providers at the end (stable-ish)
        order: List[str] = []
        try:
            order = [str(x) for x in (self._song_group_order_labels or [])]
        except Exception:
            order = []

        if 'Base' in order:
            order = ['Base'] + [x for x in order if x != 'Base']
        elif 'Base' in groups:
            order = ['Base'] + order

        try:
            for k in groups.keys():
                if str(k) not in order:
                    order.append(str(k))
        except Exception:
            pass

        # If we have nothing to show (no order, no groups), we're done.
        if not order:
            return []

        col_count = int(self.songs_table.columnCount() or 6)
        r = 0

        for label in order:
            disc_songs = groups.get(label) or []

            expanded = bool(self._song_group_expanded.get(label, True))
            arrow = "▼" if expanded else "▶"
            disp_label = self._display_label_for_source(label)
            header_txt = f"{arrow}  {disp_label} ({len(disc_songs)})"
            # Header row: [0]=disc toggle checkbox, [1..]=disc label + count, spanning the rest.
            self.songs_table.insertRow(r)
            try:
                self.songs_table.setRowHeight(r, 28)
            except Exception:
                pass

            # Track which song_ids are in this group for the current render (used by header toggles/tri-state).
            try:
                self._songs_group_song_ids[str(label)] = [int(getattr(x, 'song_id', 0) or 0) for x in (disc_songs or [])]
            except Exception:
                self._songs_group_song_ids[str(label)] = []

            # Column 0: tri-state toggle for this disc group (all on/off)
            itSel = QTableWidgetItem("")
            try:
                itSel.setToolTip(
                    "Disc group toggle:\n"
                    "Checked = all songs in this disc enabled, Unchecked = none enabled, Partial = some enabled.\n"
                    "Click to toggle the whole disc."
                )
            except Exception:
                pass

            try:
                itSel.setFlags((itSel.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable) & ~Qt.ItemIsEditable)
            except Exception:
                pass
            try:
                itSel.setData(_SONGS_ROW_KIND_ROLE, "group_header")
            except Exception:
                pass

            ids_for_state = list(self._songs_group_song_ids.get(str(label), []) or [])
            try:
                sel_count = sum(1 for sid in ids_for_state if int(sid) in (self._selected_song_ids or set()))
                total_in_group = int(len(ids_for_state))
            except Exception:
                sel_count = 0
                total_in_group = 0

            if total_in_group <= 0:
                try:
                    itSel.setFlags(itSel.flags() & ~Qt.ItemIsUserCheckable)
                except Exception:
                    pass
                try:
                    itSel.setCheckState(Qt.Unchecked)
                except Exception:
                    pass
            else:
                if sel_count <= 0:
                    itSel.setCheckState(Qt.Unchecked)
                elif sel_count >= total_in_group:
                    itSel.setCheckState(Qt.Checked)
                else:
                    itSel.setCheckState(Qt.PartiallyChecked)

            self.songs_table.setItem(r, 0, itSel)

            # Column 1: label/collapse text spans columns 1..end
            itH = QTableWidgetItem(header_txt)
            try:
                itH.setToolTip("Click this header row to collapse/expand songs for this disc.")
            except Exception:
                pass

            try:
                f = itH.font()
                f.setBold(True)
                try:
                    f.setPointSize(max(1, int(f.pointSize()) + 1))
                except Exception:
                    pass
                itH.setFont(f)
            except Exception:
                pass
            try:
                itH.setTextAlignment(Qt.AlignVCenter | Qt.AlignLeft)
            except Exception:
                pass
            try:
                itH.setData(_SONGS_ROW_KIND_ROLE, "group_header")
            except Exception:
                pass
            try:
                itH.setFlags((itH.flags() | Qt.ItemIsEnabled | Qt.ItemIsSelectable) & ~Qt.ItemIsEditable)
            except Exception:
                pass
            self.songs_table.setItem(r, 1, itH)
            try:
                self.songs_table.setSpan(r, 1, 1, max(1, col_count - 1))
            except Exception:
                pass

            # 0.9.62: Disc-group header styling (ensure tint is visible).
            try:
                from PySide6.QtGui import QBrush, QColor, QPalette

                pal = self.songs_table.palette()
                base = pal.color(QPalette.Base)
                alt = pal.color(QPalette.AlternateBase)

                def _dist(c1: QColor, c2: QColor) -> int:
                    return (
                        abs(int(c1.red()) - int(c2.red()))
                        + abs(int(c1.green()) - int(c2.green()))
                        + abs(int(c1.blue()) - int(c2.blue()))
                    )

                tint = QColor(alt)
                if _dist(base, alt) < 18:
                    hi = pal.color(QPalette.Highlight)
                    tint = QColor(hi)
                    tint.setAlpha(55)
                else:
                    tint.setAlpha(130)

                bg = QBrush(tint)
                for _it in (itSel, itH):
                    try:
                        _it.setBackground(bg)
                    except Exception:
                        pass
            except Exception:
                pass

            self._songs_header_rows[int(r)] = str(label)
            r += 1

            if (not expanded) or (not disc_songs):
                continue

            try:
                disc_songs.sort(
                    key=lambda x: (
                        (getattr(x, 'artist', '') or '').lower(),
                        (getattr(x, 'title', '') or '').lower(),
                        int(getattr(x, 'song_id', 0) or 0),
                    )
                )
            except Exception:
                pass

            for s in disc_songs:
                sid = int(getattr(s, 'song_id', 0) or 0)
                title = str(getattr(s, 'title', '') or '')
                artist = str(getattr(s, 'artist', '') or '')
                pref = str(getattr(s, 'preferred_source', '') or '')
                pref_disp = self._display_label_for_source(pref)
                try:
                    srcs = list(getattr(s, 'sources', ()) or ())
                except Exception:
                    srcs = []
                src_disp: List[str] = []
                for oc in (srcs or []):
                    try:
                        lab = str(getattr(oc, "label", oc) or "")
                    except Exception:
                        lab = str(oc)
                    lab = lab.strip()
                    if lab == "Base":
                        lab = self._display_label_for_source("Base")
                    src_disp.append(lab)
                src_txt = ", ".join(src_disp)

                self.songs_table.insertRow(r)
                it0 = QTableWidgetItem("")
                it0.setData(Qt.UserRole, sid)
                try:
                    it0.setFlags((it0.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable) & ~Qt.ItemIsEditable)
                except Exception:
                    pass
                it0.setCheckState(Qt.Checked if sid in (self._selected_song_ids or set()) else Qt.Unchecked)
                self.songs_table.setItem(r, 0, it0)

                # 0.8e column order: Title, Artist, Preferred, Sources, ID
                it1 = QTableWidgetItem(title)
                it2 = QTableWidgetItem(artist)
                it3 = QTableWidgetItem(pref_disp)
                it4 = QTableWidgetItem(src_txt)
                it5 = QTableWidgetItem(str(sid))
                try:
                    it1.setFlags(it1.flags() & ~Qt.ItemIsEditable)
                    it2.setFlags(it2.flags() & ~Qt.ItemIsEditable)
                    it3.setFlags(it3.flags() & ~Qt.ItemIsEditable)
                    it4.setFlags(it4.flags() & ~Qt.ItemIsEditable)
                    it5.setFlags(it5.flags() & ~Qt.ItemIsEditable)
                except Exception:
                    pass
                self.songs_table.setItem(r, 1, it1)
                self.songs_table.setItem(r, 2, it2)
                self.songs_table.setItem(r, 3, it3)
                self.songs_table.setItem(r, 4, it4)
                self.songs_table.setItem(r, 5, it5)

                shown_ids.append(sid)
                r += 1

        # 0.8e: Don't auto-resize columns on every render; it fights user sizing.
        try:
            self.songs_table.setColumnWidth(0, 44)
        except Exception:
            pass

    finally:
        self._songs_table_loading = False

    return shown_ids


def update_group_header_states(win: "MainWindow") -> None:
    """Update disc header tri-state checkboxes based on current selection."""

    self = win

    try:
        if self._songs_table_loading:
            return
    except Exception:
        pass

    try:
        self.songs_table.blockSignals(True)
    except Exception:
        pass
    try:
        for row, label in (self._songs_header_rows or {}).items():
            try:
                ids = list((self._songs_group_song_ids or {}).get(str(label), []) or [])
            except Exception:
                ids = []
            total_in_group = int(len(ids))
            try:
                it = self.songs_table.item(int(row), 0)
            except Exception:
                it = None
            if it is None:
                continue
            if total_in_group <= 0:
                try:
                    it.setCheckState(Qt.Unchecked)
                except Exception:
                    pass
                continue
            try:
                sel_count = sum(1 for sid in ids if int(sid) in (self._selected_song_ids or set()))
            except Exception:
                sel_count = 0

            if sel_count <= 0:
                st = Qt.Unchecked
            elif sel_count >= total_in_group:
                st = Qt.Checked
            else:
                st = Qt.PartiallyChecked
            try:
                it.setCheckState(st)
            except Exception:
                pass
    finally:
        try:
            self.songs_table.blockSignals(False)
        except Exception:
            pass


def toggle_disc_group_all(win: "MainWindow", label: str) -> None:
    """Toggle all songs in a disc group ON/OFF (based on current rendered group)."""

    self = win

    try:
        ids = set(int(x) for x in ((self._songs_group_song_ids or {}).get(str(label), []) or []))
    except Exception:
        ids = set()
    if not ids:
        return

    # If all selected -> clear; otherwise select all.
    if ids.issubset(set(self._selected_song_ids or set())):
        self._selected_song_ids -= ids
        try:
            self._disabled_song_ids |= ids
        except Exception:
            pass
    else:
        self._selected_song_ids |= ids
        try:
            self._disabled_song_ids -= ids
        except Exception:
            pass

    try:
        self._qt_state_selection_initialized = True
    except Exception:
        pass

    self._apply_song_filter()
    self._save_qt_state(force=True)


def toggle_song_group(win: "MainWindow", label: str) -> None:
    self = win

    try:
        if not label:
            return
        cur = bool(self._song_group_expanded.get(str(label), True))
        self._song_group_expanded[str(label)] = (not cur)
    except Exception:
        return
    self._apply_song_filter()
    self._save_qt_state(force=True)


def songs_event_filter(win: "MainWindow", obj, event, fallback):
    """Songs table UX.

    - Mouse: only the checkbox *indicator* toggles On/Off.
    - Keyboard: Space toggles the checkbox for the current row.

    `fallback` should behave like `super().eventFilter`.
    """

    self = win

    try:
        # --- Keyboard handling (spacebar toggles current row) ---
        if obj is self.songs_table and event.type() == QEvent.KeyPress:
            try:
                key = int(getattr(event, "key", lambda: -1)())
            except Exception:
                key = -1
            if key == int(Qt.Key_Space):
                row = int(self.songs_table.currentRow())
                if row >= 0:
                    # Disc header rows: space toggles all in group
                    try:
                        if int(row) in (self._songs_header_rows or {}):
                            lbl = str((self._songs_header_rows or {}).get(int(row)) or '')
                            if lbl:
                                self._toggle_disc_group_all(lbl)
                            try:
                                event.accept()
                            except Exception:
                                pass
                            return True
                    except Exception:
                        pass

                    try:
                        it0 = self.songs_table.item(row, 0)
                    except Exception:
                        it0 = None
                    if it0 is not None:
                        try:
                            self.songs_table.selectRow(row)
                            self.songs_table.setCurrentCell(row, 1)
                        except Exception:
                            pass
                        try:
                            cur = it0.checkState()
                        except Exception:
                            cur = Qt.Unchecked
                        new_state = Qt.Unchecked if cur == Qt.Checked else Qt.Checked
                        try:
                            it0.setCheckState(new_state)
                        except Exception:
                            pass
                        try:
                            event.accept()
                        except Exception:
                            pass
                        return True

        # --- Mouse handling (checkbox indicator only) ---
        if obj is self.songs_table.viewport():
            # We swallow *all* interactions in column 0 so native styles can't
            # auto-toggle checkboxes when clicking anywhere in the cell.
            et = event.type()
            try:
                is_left = (getattr(event, "button", lambda: None)() == Qt.LeftButton)
            except Exception:
                is_left = False

            if et in (QEvent.MouseButtonPress, QEvent.MouseButtonRelease, QEvent.MouseButtonDblClick) and is_left:
                idx = self.songs_table.indexAt(event.pos())
                if not idx.isValid():
                    try:
                        self._songs_pending_cb_row = -1
                        self._songs_cancel_cb_row = -1
                    except Exception:
                        pass
                    return fallback(obj, event)

                row = int(idx.row())
                col = int(idx.column())
                try:
                    # Ensure table takes focus so keyboard navigation works.
                    self.songs_table.setFocus()
                except Exception:
                    pass

                def _hit_checkbox(_idx, _pos) -> bool:
                    """Return True only if the click is on the checkbox indicator area.

                    We intentionally avoid QStyle.subElementRect here because it can
                    trigger rare access violations on Windows when called from inside
                    an eventFilter (seen with PySide6).
                    """

                    try:
                        vr = self.songs_table.visualRect(_idx)
                        try:
                            if not vr.isValid():
                                return False
                        except Exception:
                            pass

                        # Conservative hit-box: small square near the left edge,
                        # vertically centered. This prevents accidental toggles when
                        # clicking the cell text/whitespace.
                        pad_x = 6
                        h = int(getattr(vr, "height", lambda: 18)())
                        ind = max(12, min(18, int(h - 6)))

                        cx = int(getattr(vr, "x", lambda: 0)()) + int(pad_x)
                        cy = int(getattr(vr, "y", lambda: 0)()) + int((h - ind) / 2)

                        px = int(getattr(_pos, "x", lambda: 0)())
                        py = int(getattr(_pos, "y", lambda: 0)())

                        return bool((cx <= px <= (cx + ind)) and (cy <= py <= (cy + ind)))
                    except Exception:
                        return False

                # Lazily init our click state.
                try:
                    if not hasattr(self, "_songs_pending_cb_row"):
                        self._songs_pending_cb_row = -1
                    if not hasattr(self, "_songs_cancel_cb_row"):
                        self._songs_cancel_cb_row = -1
                except Exception:
                    pass

                # Double-click on column 0 should NOT toggle a second time.
                if et == QEvent.MouseButtonDblClick and col == 0:
                    try:
                        self._songs_cancel_cb_row = int(row)
                        self._songs_pending_cb_row = -1
                    except Exception:
                        pass
                    try:
                        event.accept()
                    except Exception:
                        pass
                    return True

                # Column 0: handle selection and (optionally) arm a checkbox toggle on press.
                if et == QEvent.MouseButtonPress and col == 0:
                    try:
                        self.songs_table.selectRow(row)
                        self.songs_table.setCurrentCell(row, 1)
                    except Exception:
                        pass
                    try:
                        self._songs_pending_cb_row = int(row) if _hit_checkbox(idx, event.pos()) else -1
                    except Exception:
                        pass
                    try:
                        event.accept()
                    except Exception:
                        pass
                    return True

                # Column 0: on release, toggle if we armed it on press.
                if et == QEvent.MouseButtonRelease and col == 0:
                    try:
                        # Cancel the second toggle in a double-click sequence.
                        if int(getattr(self, "_songs_cancel_cb_row", -1)) == int(row):
                            self._songs_cancel_cb_row = -1
                            self._songs_pending_cb_row = -1
                            try:
                                event.accept()
                            except Exception:
                                pass
                            return True
                    except Exception:
                        pass

                    try:
                        self.songs_table.selectRow(row)
                        self.songs_table.setCurrentCell(row, 1)
                    except Exception:
                        pass

                    armed = False
                    try:
                        armed = (int(getattr(self, "_songs_pending_cb_row", -1)) == int(row))
                    except Exception:
                        armed = False

                    try:
                        self._songs_pending_cb_row = -1
                    except Exception:
                        pass

                    if armed:
                        # Disc header rows: toggle all in group.
                        try:
                            if int(row) in (self._songs_header_rows or {}):
                                lbl = str((self._songs_header_rows or {}).get(int(row)) or "")
                                if lbl:
                                    self._toggle_disc_group_all(lbl)
                                try:
                                    event.accept()
                                except Exception:
                                    pass
                                return True
                        except Exception:
                            pass

                        # Regular song rows: toggle single song.
                        try:
                            it0 = self.songs_table.item(row, 0)
                        except Exception:
                            it0 = None
                        if it0 is not None:
                            try:
                                cur = it0.checkState()
                            except Exception:
                                cur = Qt.Unchecked
                            new_state = Qt.Unchecked if cur == Qt.Checked else Qt.Checked
                            try:
                                it0.setCheckState(new_state)
                            except Exception:
                                pass

                    try:
                        event.accept()
                    except Exception:
                        pass
                    return True

                # Disc header rows (col 1+): collapse/expand on click (on release).
                if et == QEvent.MouseButtonRelease:
                    try:
                        if int(row) in (self._songs_header_rows or {}):
                            lbl = str((self._songs_header_rows or {}).get(int(row)) or "")
                            self._toggle_song_group(lbl)
                            try:
                                event.accept()
                            except Exception:
                                pass
                            return True
                    except Exception:
                        pass

                # Other columns: do not toggle, allow normal selection behavior.
                return False

    except Exception:
        pass

    return fallback(obj, event)


def on_song_item_changed(win: "MainWindow", item: QTableWidgetItem) -> None:
    self = win

    if self._songs_table_loading:
        return

    try:
        if item.column() != 0:
            return
    except Exception:
        pass

    # Ignore disc header checkbox changes (handled by click handler)
    try:
        if int(item.row()) in (self._songs_header_rows or {}):
            return
    except Exception:
        pass

    sid = item.data(Qt.UserRole)
    try:
        sid_i = int(sid)
    except Exception:
        return

    try:
        self._qt_state_selection_initialized = True
    except Exception:
        pass

    if item.checkState() == Qt.Checked:
        self._selected_song_ids.add(sid_i)
        try:
            self._disabled_song_ids.discard(sid_i)
        except Exception:
            pass
    else:
        try:
            self._selected_song_ids.discard(sid_i)
        except Exception:
            pass
        try:
            self._disabled_song_ids.add(sid_i)
        except Exception:
            pass

    self._update_group_header_states()
    self._update_song_status()
    self._save_qt_state(force=True)


def bulk_select_visible(win: "MainWindow", mode: str = "select") -> None:
    self = win

    vis = set(int(x) for x in (self._songs_visible_ids or []))
    if not vis:
        return

    if mode == "select":
        self._selected_song_ids |= vis
        try:
            self._disabled_song_ids -= vis
        except Exception:
            pass
    elif mode == "clear":
        self._selected_song_ids -= vis
        try:
            self._disabled_song_ids |= vis
        except Exception:
            pass
    elif mode == "invert":
        for sid in list(vis):
            if sid in (self._selected_song_ids or set()):
                try:
                    self._selected_song_ids.discard(sid)
                except Exception:
                    pass
                try:
                    self._disabled_song_ids.add(sid)
                except Exception:
                    pass
            else:
                try:
                    self._selected_song_ids.add(sid)
                except Exception:
                    pass
                try:
                    self._disabled_song_ids.discard(sid)
                except Exception:
                    pass

    try:
        self._qt_state_selection_initialized = True
    except Exception:
        pass

    self._apply_song_filter()
    self._save_qt_state(force=True)


def update_song_status(win: "MainWindow", total: Optional[int] = None, visible: Optional[int] = None) -> None:
    self = win

    tot = int(total) if total is not None else int(len(self._songs_all or []))
    vis = int(visible) if visible is not None else int(len(self._songs_visible_ids or []))
    picked = int(len(self._selected_song_ids or set()))

    # Title+Artist duplicate stats (in-game may suppress these)
    included = picked
    title_dupe_extra = 0
    try:
        import re as _re

        def _norm(s: str) -> str:
            return _re.sub(r"\s+", " ", (s or "").strip()).upper()

        counts: Dict[str, int] = {}
        for sid in (self._selected_song_ids or set()):
            try:
                sid_i = int(sid)
            except Exception:
                continue
            s = getattr(self, "_songs_by_id", {}).get(sid_i)
            title = str(getattr(s, "title", "") or "") if s is not None else ""
            artist = str(getattr(s, "artist", "") or "") if s is not None else ""
            k = f"{_norm(title)}||{_norm(artist)}"
            if not _norm(title) and not _norm(artist):
                k = f"ID:{sid_i}"
            counts[k] = int(counts.get(k, 0)) + 1

        for k, n in (counts or {}).items():
            if k.startswith("ID:"):
                continue
            if int(n) >= 2:
                title_dupe_extra += max(0, int(n) - 1)

        included = max(0, picked - int(title_dupe_extra))
    except Exception:
        included = picked
        title_dupe_extra = 0

    # Conflicts = song IDs that appear in 2+ sources with different files (needs resolution)
    conflicts_n = 0
    try:
        conflicts_n = int(len(getattr(self, "_song_conflicts", {}) or {}))
    except Exception:
        conflicts_n = 0

    # ID dupes = song IDs that appear in 2+ sources (table shows one row per song ID)
    id_dupes = int(getattr(self, "_dedupe_songs_with_dups", 0) or 0)

    # Build readable status line
    songs_part = f"Songs: {tot}" + (f" ({vis} shown)" if vis != tot else "")
    included_part = f"Included: {included}"
    if title_dupe_extra > 0:
        included_part += f" ({picked} picked; {title_dupe_extra} duplicate title" + ("s" if title_dupe_extra != 1 else "") + ")"
    conflicts_part = f"Conflicts: {conflicts_n}"

    extra_parts: List[str] = []
    if id_dupes > 0:
        extra_parts.append(f"ID dupes: {id_dupes}")

    line = " | ".join([songs_part, included_part, conflicts_part] + extra_parts)

    try:
        self.songs_status_lbl.setText(line)
    except Exception:
        pass
    try:
        self._update_inspector_context()
    except Exception:
        pass

