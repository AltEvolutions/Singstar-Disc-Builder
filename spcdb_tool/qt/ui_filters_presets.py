# ruff: noqa
from __future__ import annotations

"""Songs filter + presets helpers (Qt UI).

Extracted from `spcdb_tool/qt/main_window.py` as part of the incremental refactor.
Behavior is intended to be unchanged.
"""

from pathlib import Path
from typing import Dict, List, Optional, Set

from PySide6.QtCore import Qt

from ..controller import SongAgg
from .constants import SONG_SOURCE_SELECTED_KEY, SONG_SOURCE_SELECTED_DISP


def base_disc_folder_name(self) -> str:
    try:
        bp = str(self.base_edit.text() or "").strip()
    except Exception:
        bp = ""
    if not bp:
        return ""
    try:
        return Path(bp).name
    except Exception:
        return bp


def display_label_for_source(self, label: str) -> str:
    lab = str(label or "").strip()
    if lab == SONG_SOURCE_SELECTED_KEY:
        return SONG_SOURCE_SELECTED_DISP
    if lab == "Base":
        nm = self._base_disc_folder_name()
        if nm:
            return f"Base [{nm}]"
    return lab if lab else "Base"


def normalize_source_key(self, val: str) -> str:
    t = str(val or "").strip()
    if t == SONG_SOURCE_SELECTED_KEY:
        return SONG_SOURCE_SELECTED_KEY
    if t.lower().startswith("selected discs"):
        return SONG_SOURCE_SELECTED_KEY
    if t.startswith("Base ["):
        return "Base"
    return t if t else "All"


def song_source_filter_key(self) -> str:
    try:
        d = self.song_source_combo.currentData()
        if d is not None:
            return self._normalize_source_key(str(d))
    except Exception:
        pass
    try:
        return self._normalize_source_key(str(self.song_source_combo.currentText() or "All"))
    except Exception:
        return "All"


def selected_source_labels_for_filter(self) -> Set[str]:
    """Return Source labels currently selected in the Sources panel (for the 'Selected discs' filter)."""
    labels: Set[str] = set()
    try:
        selected_rows = sorted({i.row() for i in self.sources_table.selectedIndexes()})
    except Exception:
        selected_rows = []

    # No selection -> empty set (so 'Selected discs' shows nothing until the user selects discs).
    if not selected_rows:
        return labels

    # Include Base only if the Base row is selected.
    try:
        if any(self._is_base_row(r) for r in selected_rows):
            labels.add("Base")
    except Exception:
        pass

    for r in (selected_rows or []):
        if self._is_base_row(r):
            continue
        try:
            if bool(self.sources_table.isRowHidden(int(r))):
                continue
        except Exception:
            pass
        try:
            label = (self.sources_table.item(r, 0).text() if self.sources_table.item(r, 0) else "").strip()
        except Exception:
            label = ""
        if label:
            labels.add(str(label))
    return labels


def update_song_source_combo_tooltip(self) -> None:
    try:
        self.song_source_combo.setToolTip(str(self.song_source_combo.currentText() or ""))
    except Exception:
        pass


def commit_song_source_combo_edit(self) -> None:
    """Editable Source combo: resolve typed text to a real item (best-effort)."""
    try:
        raw = str(self.song_source_combo.currentText() or "").strip()
    except Exception:
        raw = ""
    if not raw:
        # Reset to All
        try:
            ix = int(self.song_source_combo.findData("All"))
        except Exception:
            ix = -1
        if ix < 0:
            try:
                ix = int(self.song_source_combo.findText("All"))
            except Exception:
                ix = -1
        if ix >= 0:
            try:
                self.song_source_combo.setCurrentIndex(ix)
            except Exception:
                pass
        self._update_song_source_combo_tooltip()
        return

    want = raw.strip().lower()
    best_ix = -1

    # Exact match (case-insensitive)
    try:
        for i in range(int(self.song_source_combo.count() or 0)):
            t = str(self.song_source_combo.itemText(i) or "").strip()
            if t.lower() == want:
                best_ix = int(i)
                break
    except Exception:
        best_ix = -1

    # Substring match (display text)
    if best_ix < 0:
        try:
            for i in range(int(self.song_source_combo.count() or 0)):
                t = str(self.song_source_combo.itemText(i) or "").strip()
                if want and want in t.lower():
                    best_ix = int(i)
                    break
        except Exception:
            best_ix = -1

    # Substring match (data)
    if best_ix < 0:
        try:
            for i in range(int(self.song_source_combo.count() or 0)):
                d = self.song_source_combo.itemData(i)
                if d is None:
                    continue
                if want and want in str(d).lower():
                    best_ix = int(i)
                    break
        except Exception:
            best_ix = -1

    if best_ix >= 0:
        try:
            self.song_source_combo.setCurrentIndex(int(best_ix))
        except Exception:
            pass

    self._update_song_source_combo_tooltip()


def maybe_apply_song_filter_from_sources_selection(self) -> None:
    """If the Source filter is 'Selected discs', re-apply when Sources selection changes."""
    try:
        if str(self._song_source_filter_key() or "All") == SONG_SOURCE_SELECTED_KEY:
            self._apply_song_filter()
    except Exception:
        pass


def refresh_song_source_combo(self) -> None:
    current_key = str(self._song_source_filter_key() or "All")
    wanted_key = self._normalize_source_key(str(getattr(self, "_qt_state_wanted_source", "") or ""))

    try:
        keys = [str(k) for k in (self._disc_song_ids_by_label or {}).keys()]
    except Exception:
        keys = []

    ordered: List[str] = []
    try:
        for k in (self._song_group_order_labels or []):
            ks = str(k)
            if ks in keys and ks not in ordered:
                ordered.append(ks)
    except Exception:
        pass
    # Any remaining (unexpected) labels at the end (stable-ish)
    try:
        for k in (keys or []):
            ks = str(k)
            if ks not in ordered:
                ordered.append(ks)
    except Exception:
        pass

    all_keys: List[str] = ["All", SONG_SOURCE_SELECTED_KEY]
    all_keys.extend(ordered)

    try:
        self.song_source_combo.blockSignals(True)
    except Exception:
        pass
    try:
        self.song_source_combo.clear()
        for k in (all_keys or ["All"]):
            if k == "All":
                disp = "All"
            else:
                disp = self._display_label_for_source(k)
            try:
                self.song_source_combo.addItem(disp, k)
            except Exception:
                # Extremely defensive: fall back to addItem(text) only
                try:
                    self.song_source_combo.addItem(str(disp))
                except Exception:
                    pass


        # Make the popup wide enough to show full disc names (no ellipsis).
        try:
            v = self.song_source_combo.view()
            try:
                v.setTextElideMode(Qt.ElideNone)
            except Exception:
                pass
            from PySide6.QtGui import QFontMetrics
            fm = QFontMetrics(v.font())
            maxw = 0
            for i in range(int(self.song_source_combo.count() or 0)):
                t = str(self.song_source_combo.itemText(i) or '')
                try:
                    w = int(fm.horizontalAdvance(t))
                except Exception:
                    w = int(fm.size(0, t).width())
                if w > maxw:
                    maxw = int(w)
            # Padding for margins + scrollbar.
            maxw = int(min(900, maxw + 70))
            try:
                v.setMinimumWidth(max(int(self.song_source_combo.width() or 0), int(maxw)))
            except Exception:
                v.setMinimumWidth(int(maxw))
        except Exception:
            pass

        target = "All"
        if wanted_key and wanted_key in all_keys:
            target = wanted_key
        elif current_key and current_key in all_keys:
            target = current_key

        ix = -1
        try:
            ix = int(self.song_source_combo.findData(target))
        except Exception:
            ix = -1
        if ix < 0:
            try:
                ix = int(self.song_source_combo.findText(str(target)))
            except Exception:
                ix = -1
        if ix >= 0:
            self.song_source_combo.setCurrentIndex(ix)
            try:
                self._update_song_source_combo_tooltip()
            except Exception:
                pass
    finally:
        try:
            self.song_source_combo.blockSignals(False)
        except Exception:
            pass



# ---- Presets (0.8c) ----


def builtin_presets(self) -> Dict[str, dict]:
    return {
        "All songs": {
            "search": "",
            "source_filter": "All",
            "selected_only": False,
            "flags": {"conflicts_only": False, "duplicates_only": False, "overrides_only": False, "disabled_only": False},
        },
        "Conflicts": {
            "search": "",
            "source_filter": "All",
            "selected_only": False,
            "flags": {"conflicts_only": True, "duplicates_only": False, "overrides_only": False, "disabled_only": False},
        },
        "Duplicates": {
            "search": "",
            "source_filter": "All",
            "selected_only": False,
            "flags": {"conflicts_only": False, "duplicates_only": True, "overrides_only": False, "disabled_only": False},
        },
        "Overrides": {
            "search": "",
            "source_filter": "All",
            "selected_only": False,
            "flags": {"conflicts_only": False, "duplicates_only": False, "overrides_only": True, "disabled_only": False},
        },
        "Disabled": {
            "search": "",
            "source_filter": "All",
            "selected_only": False,
            "flags": {"conflicts_only": False, "duplicates_only": False, "overrides_only": False, "disabled_only": True},
        },
    }


def rebuild_preset_combo(self) -> None:
    # Keep current text if possible
    try:
        cur = str(self.song_preset_combo.currentText() or "")
    except Exception:
        cur = ""
    try:
        self.song_preset_combo.blockSignals(True)
    except Exception:
        pass
    try:
        self.song_preset_combo.clear()
        # Built-in views
        for name, payload in self._builtin_presets().items():
            self.song_preset_combo.addItem(name, {"kind": "builtin", "name": name, "payload": payload})
    finally:
        try:
            self.song_preset_combo.blockSignals(False)
        except Exception:
            pass

    # Restore selection best-effort
    try:
        if cur:
            self._set_preset_combo_to_name(cur)
    except Exception:
        pass


def set_preset_combo_to_name(self, name: str) -> None:
    nm = str(name or "").strip()
    if not nm:
        nm = "All songs"
    try:
        for i in range(int(self.song_preset_combo.count() or 0)):
            if str(self.song_preset_combo.itemText(i) or "") == nm:
                self.song_preset_combo.setCurrentIndex(i)
                return
    except Exception:
        pass
    try:
        self.song_preset_combo.setCurrentIndex(0)
    except Exception:
        pass


def current_filter_payload(self) -> dict:
    try:
        search = str(self.song_search_edit.text() or "")
    except Exception:
        search = ""
    try:
        src = str(self._song_source_filter_key() or "All")
    except Exception:
        src = "All"
    try:
        sel_only = bool(self.song_selected_only_chk.isChecked())
    except Exception:
        sel_only = False

    flags = {
        "conflicts_only": bool(getattr(self, "_filter_conflicts_only", False)),
        "duplicates_only": bool(getattr(self, "_filter_duplicates_only", False)),
        "overrides_only": bool(getattr(self, "_filter_overrides_only", False)),
        "disabled_only": bool(getattr(self, "_filter_disabled_only", False)),
    }
    return {"search": search, "source_filter": src, "selected_only": sel_only, "flags": flags}


def apply_filter_payload(self, payload: dict) -> None:
    # IMPORTANT: keep _applying_preset True through the resulting _apply_song_filter()
    # so the view dropdown doesn't immediately revert to "Custom".
    self._applying_preset = True
    try:
        payload = payload or {}
        search = str(payload.get("search") or "")
        src = self._normalize_source_key(str(payload.get("source_filter") or "All"))
        sel_only = bool(payload.get("selected_only", False))
        flags = payload.get("flags") or {}
        if isinstance(flags, dict):
            self._filter_conflicts_only = bool(flags.get("conflicts_only", False))
            self._filter_duplicates_only = bool(flags.get("duplicates_only", False))
            self._filter_overrides_only = bool(flags.get("overrides_only", False))
            self._filter_disabled_only = bool(flags.get("disabled_only", False))

        try:
            self.song_search_edit.setText(search)
        except Exception:
            pass
        try:
            # Source combo may not have been populated yet; store wanted and try apply now.
            self._qt_state_wanted_source = src
            ix = self.song_source_combo.findData(src)
            if ix < 0:
                ix = self.song_source_combo.findText(src)
            if ix >= 0:
                self.song_source_combo.setCurrentIndex(ix)
        except Exception:
            pass
        try:
            self.song_selected_only_chk.setChecked(sel_only)
        except Exception:
            pass

        # Apply now while _applying_preset is True.
        try:
            self._apply_song_filter()
        except Exception:
            pass
        try:
            self._save_qt_state()
        except Exception:
            pass
        try:
            self._update_inspector_context()
        except Exception:
            pass
    finally:
        self._applying_preset = False


def apply_preset_from_combo(self) -> None:
    """Apply the selected built-in View.

    v0.8g3:
    - No 'Custom' entry in the View dropdown.
    - Manual filter edits do not force the dropdown to change.
    """
    try:
        data = self.song_preset_combo.currentData() or {}
    except Exception:
        data = {}
    kind = str((data or {}).get("kind") or "")
    if kind == "builtin":
        payload = (data or {}).get("payload") or {}
        try:
            self._active_preset_name = str((data or {}).get("name") or self.song_preset_combo.currentText() or "All songs")
        except Exception:
            self._active_preset_name = str(self.song_preset_combo.currentText() or "All songs")
        self._apply_filter_payload(payload)
        try:
            self._save_qt_state()
        except Exception:
            pass
    else:
        # No-op; keep whatever is selected in the combo.
        try:
            self._active_preset_name = str(self.song_preset_combo.currentText() or "All songs")
            self._save_qt_state()
            self._update_inspector_context()
        except Exception:
            pass


def apply_song_filter(self) -> None:
    q = str(self.song_search_edit.text() or "").strip().lower()
    src = str(self._song_source_filter_key() or "All").strip()
    sel_only = bool(self.song_selected_only_chk.isChecked())

    # View extra flags
    conf_only = bool(getattr(self, '_filter_conflicts_only', False))
    dup_only = bool(getattr(self, '_filter_duplicates_only', False))
    ov_only = bool(getattr(self, '_filter_overrides_only', False))
    dis_only = bool(getattr(self, '_filter_disabled_only', False))

    selected_labels: Optional[Set[str]] = None
    if src == SONG_SOURCE_SELECTED_KEY:
        try:
            selected_labels = self._selected_source_labels_for_filter()
        except Exception:
            selected_labels = set()

    if not self._songs_all:
        self._songs_visible_ids = []
        self._render_songs_table([])
        self._update_song_status(total=0, visible=0)
        return

    filtered: List[SongAgg] = []
    for s in self._songs_all:
        sid = int(getattr(s, 'song_id', 0) or 0)

        if conf_only:
            try:
                if sid not in (self._song_conflicts or {}):
                    continue
            except Exception:
                continue

        if dup_only:
            try:
                srcs = list(getattr(s, 'sources', ()) or ())
            except Exception:
                srcs = []
            if int(len(srcs)) <= 1:
                continue

        if ov_only:
            try:
                if sid not in (self._song_source_overrides or {}):
                    continue
            except Exception:
                continue

        if dis_only:
            try:
                if sid not in (self._disabled_song_ids or set()):
                    continue
            except Exception:
                continue

        if src and src != "All":
            found = False
            try:
                srcs = list(getattr(s, 'sources', ()) or ())  # type: ignore
            except Exception:
                srcs = []

            if src == SONG_SOURCE_SELECTED_KEY:
                # Filter by currently-selected discs in Sources panel.
                if not selected_labels:
                    continue
                try:
                    for oc in (srcs or []):
                        lab = str(getattr(oc, 'label', oc) or '')
                        if lab and lab in selected_labels:
                            found = True
                            break
                except Exception:
                    found = False
            else:
                try:
                    for oc in (srcs or []):
                        if str(getattr(oc, 'label', oc) or '') == src:
                            found = True
                            break
                except Exception:
                    found = False

            if not found:
                continue

        if q:
            try:
                t = str(getattr(s, 'title', '') or '').lower()
                a = str(getattr(s, 'artist', '') or '').lower()
                if q not in t and q not in a:
                    continue
            except Exception:
                continue

        if sel_only:
            try:
                if sid in (self._disabled_song_ids or set()):
                    continue
            except Exception:
                continue

        filtered.append(s)

    # Sort stable (by artist then title) for UX consistency
    try:
        filtered.sort(key=lambda ss: ((ss.artist or '').lower(), (ss.title or '').lower(), int(getattr(ss, 'song_id', 0) or 0)))
    except Exception:
        pass

    try:
        self._songs_visible_ids = [int(getattr(x, 'song_id', 0) or 0) for x in filtered]
    except Exception:
        self._songs_visible_ids = []

    self._render_songs_table(filtered)
    self._update_song_status(total=len(self._songs_all), visible=len(filtered))
