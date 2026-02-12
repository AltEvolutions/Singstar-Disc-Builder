# ruff: noqa
from __future__ import annotations

"""Qt Sources table helpers (internal).

Extracted from `spcdb_tool/qt/main_window.py` as part of the incremental Qt refactor.
Behavior is intended to be unchanged.

Imported lazily via `MainWindow`.
"""

from pathlib import Path
from typing import TYPE_CHECKING, Dict, List

from PySide6.QtCore import Qt, QThread
from PySide6.QtWidgets import QFileDialog, QMessageBox, QTableWidgetItem

from ..controller import CancelToken, _index_cache_path_for_input

from .workers import ScanWorker

if TYPE_CHECKING:
    from .main_window import MainWindow


def update_sources_title(win: "MainWindow") -> None:
    # Keep the original variable name used in main_window to minimize risk.
    self = win

    try:
        n = int(self.sources_table.rowCount())
    except Exception:
        n = 0
    total = max(0, n - 1)  # row 0 is Base Disc
    shown = 0
    tallies = {"Extracted": 0, "Packed": 0, "Partial": 0, "Needs extract": 0, "Errors": 0, "Other": 0}
    try:
        for r in range(self.sources_table.rowCount()):
            if self._is_base_row(r):
                continue
            if bool(self.sources_table.isRowHidden(r)):
                continue
            shown += 1
            try:
                st_txt = (self.sources_table.item(r, 1).text() if self.sources_table.item(r, 1) else "")
            except Exception:
                st_txt = ""
            try:
                cat = str(self._source_state_category(st_txt) or "Other")
            except Exception:
                cat = "Other"
            try:
                tallies[cat] = int(tallies.get(cat, 0)) + 1
            except Exception:
                pass
    except Exception:
        shown = total

    sel = 0
    try:
        selected_rows = sorted({i.row() for i in self.sources_table.selectedIndexes()})
    except Exception:
        selected_rows = []
    try:
        for r in set(int(x) for x in selected_rows):
            try:
                if self._is_base_row(r):
                    continue
            except Exception:
                if int(r) == 0:
                    continue
            try:
                if bool(self.sources_table.isRowHidden(int(r))):
                    continue
            except Exception:
                pass
            sel += 1
    except Exception:
        sel = 0

    try:
        if shown != total:
            txt = f"Sources: {shown}/{total} (+ Base)"
        else:
            txt = f"Sources: {total} (+ Base)"
        if sel > 0:
            txt = f"{txt} | Selected: {sel}"
        self.sources_title_lbl.setText(txt)
        try:
            if getattr(self, "sources_tallies_lbl", None) is not None:
                self.sources_tallies_lbl.setText(
                    f"Status (shown): Extracted {int(tallies.get('Extracted',0))} | Packed {int(tallies.get('Packed',0))} | Partial {int(tallies.get('Partial',0))} | Needs {int(tallies.get('Needs extract',0))} | Errors {int(tallies.get('Errors',0))}"
                )
        except Exception:
            pass
    except Exception:
        pass


def sources_filter_active(win: "MainWindow") -> bool:
    self = win

    try:
        q = str(self.sources_filter_edit.text() or "").strip()
    except Exception:
        q = ""
    if q:
        return True
    try:
        acts = getattr(self, "_src_state_actions", {}) or {}
        if acts and any((not a.isChecked()) for a in acts.values()):
            return True
    except Exception:
        pass
    return False


def source_state_category(state: str) -> str:
    s = str(state or "")
    if "Errors" in s:
        return "Errors"
    if "Extracted" in s:
        return "Extracted"
    if "Partial" in s:
        return "Partial"
    if "Packed" in s:
        return "Packed"
    if "Needs extract" in s:
        return "Needs extract"
    return "Other"


def apply_sources_filter(win: "MainWindow") -> None:
    self = win

    tbl = getattr(self, "sources_table", None)
    if tbl is None:
        return

    try:
        q = str(self.sources_filter_edit.text() or "").strip().lower()
    except Exception:
        q = ""

    allowed: Dict[str, bool] = {}
    try:
        acts = getattr(self, "_src_state_actions", {}) or {}
        for k, act in acts.items():
            try:
                allowed[str(k)] = bool(act.isChecked())
            except Exception:
                allowed[str(k)] = True
    except Exception:
        allowed = {}

    try:
        for r in range(tbl.rowCount()):
            try:
                if self._is_base_row(r):
                    tbl.setRowHidden(r, False)
                    continue
            except Exception:
                if int(r) == 0:
                    try:
                        tbl.setRowHidden(r, False)
                    except Exception:
                        pass
                    continue

            label = (tbl.item(r, 0).text() if tbl.item(r, 0) else "").strip()
            path = (tbl.item(r, 2).text() if tbl.item(r, 2) else "").strip()
            state = (tbl.item(r, 1).text() if tbl.item(r, 1) else "").strip()

            if q:
                hay = f"{label} {path}".lower()
                if q not in hay:
                    tbl.setRowHidden(r, True)
                    continue

            cat = self._source_state_category(state)
            if allowed and (not bool(allowed.get(cat, True))):
                tbl.setRowHidden(r, True)
                continue

            tbl.setRowHidden(r, False)
    except Exception:
        pass

    try:
        self._update_sources_title()
    except Exception:
        pass


def select_sources_shown(win: "MainWindow") -> None:
    self = win

    tbl = getattr(self, "sources_table", None)
    if tbl is None:
        return
    try:
        tbl.blockSignals(True)
    except Exception:
        pass
    try:
        tbl.clearSelection()
        for r in range(tbl.rowCount()):
            try:
                if self._is_base_row(r):
                    continue
            except Exception:
                if int(r) == 0:
                    continue
            try:
                if bool(tbl.isRowHidden(int(r))):
                    continue
            except Exception:
                pass
            tbl.selectRow(int(r))
    except Exception:
        pass
    try:
        tbl.blockSignals(False)
    except Exception:
        pass
    try:
        self._update_sources_title()
    except Exception:
        pass


def norm_key(p: str) -> str:
    try:
        return str(Path(str(p or "").strip()).expanduser().resolve())
    except Exception:
        return str(p or "").strip()


def compute_disc_state(win: "MainWindow", disc_root: str) -> str:
    self = win

    root = Path(str(disc_root or "").strip())
    usr = root / "PS3_GAME" / "USRDIR"
    parts: list[str] = []

    try:
        extracted = (usr / "FileSystem" / "Export").is_dir() or (usr / "filesystem" / "export").is_dir()
    except Exception:
        extracted = False
    if extracted:
        parts.append("Extracted")
        try:
            if bool(self._disc_extraction_verified.get(self._norm_key(str(root)))):
                parts.append("Verified")
        except Exception:
            pass
    else:
        try:
            if usr.is_dir():
                has_pkd_out = False
                try:
                    for cand in usr.iterdir():
                        try:
                            if cand.is_dir():
                                nl = cand.name.lower()
                                if nl.startswith("pack") and nl.endswith(".pkd_out"):
                                    has_pkd_out = True
                                    break
                        except Exception:
                            continue
                except Exception:
                    has_pkd_out = False

                has_pack = bool(any(usr.glob("pack*.pkd")) or any(usr.glob("pack*.PKD")))
                if has_pkd_out:
                    parts.append("Partial")
                elif has_pack:
                    parts.append("Packed")
                else:
                    # USRDIR exists but isn't extracted; treat as needing extraction.
                    parts.append("Needs extract")
        except Exception:
            pass

    try:
        cache_p = _index_cache_path_for_input(str(root))
        if cache_p.exists():
            parts.append("Indexed")
    except Exception:
        pass

    badge = self._disc_validation_badge.get(self._norm_key(str(root)))
    if badge:
        if badge == "V":
            parts.append("Valid")
        elif badge == "W":
            parts.append("Warnings")
        elif badge == "X":
            parts.append("Errors")

    return " • ".join(parts) if parts else "—"


def apply_source_row_decor(win: "MainWindow", row: int, state: str) -> None:
    self = win

    """Apply full-row tinting for Sources.

    Rules:
    - Base disc row: green
    - Needs attention: red (packed/unextracted OR validation errors)
    """

    try:
        r = int(row)
    except Exception:
        return

    s = str(state or "")
    try:
        is_base = bool(self._is_base_row(r))
    except Exception:
        is_base = (r == 0)

    needs_attention = ((("Packed" in s) or ("Partial" in s) or ("Needs extract" in s)) and ("Extracted" not in s)) or ("Errors" in s)

    try:
        from PySide6.QtGui import QBrush, QColor
    except Exception:
        return

    bg = None
    fg = None
    tip = ""

    if is_base:
        bg = QBrush(QColor(40, 100, 40, 180))
        fg = QBrush(QColor(235, 255, 235))
        tip = "Base disc"
    elif needs_attention:
        bg = QBrush(QColor(155, 45, 45, 180))
        fg = QBrush(QColor(255, 235, 235))
        if ((("Packed" in s) or ("Partial" in s) or ("Needs extract" in s)) and ("Extracted" not in s)):
            tip = (
                "Unextracted disc. Use Extract Selected to unpack/verify.\n"
                "If you have leftover artifacts, use Tools -> Cleanup PKD artifacts..."
            )
        elif "Errors" in s:
            tip = "Validation errors detected for this source."
    else:
        # Clear any prior tinting if state changed back to normal.
        bg = None
        fg = None
        tip = ""

    try:
        for c in range(3):
            it = self.sources_table.item(r, c)
            if it is None:
                continue
            if bg is None:
                try:
                    it.setData(Qt.BackgroundRole, None)
                except Exception:
                    pass
                try:
                    it.setData(Qt.ForegroundRole, None)
                except Exception:
                    pass
                try:
                    it.setToolTip("")
                except Exception:
                    pass
            else:
                try:
                    it.setBackground(bg)
                except Exception:
                    pass
                try:
                    it.setForeground(fg)
                except Exception:
                    pass
                try:
                    it.setToolTip(tip)
                except Exception:
                    pass
    except Exception:
        pass


def refresh_source_states(win: "MainWindow") -> None:
    self = win

    try:
        self._ensure_base_row()
    except Exception:
        pass
    try:
        for r in range(self.sources_table.rowCount()):
            path = (self.sources_table.item(r, 2).text() if self.sources_table.item(r, 2) else "").strip()
            state = self._compute_disc_state(path)

            it = self.sources_table.item(r, 1)
            if it is None:
                it = QTableWidgetItem(str(state))
                self.sources_table.setItem(r, 1, it)
            else:
                it.setText(str(state))
            try:
                it.setTextAlignment(Qt.AlignCenter)
            except Exception:
                pass

            try:
                self._apply_source_row_decor(r, str(state))
            except Exception:
                pass
    except Exception:
        pass

    # Re-apply any Sources filters after states change.
    try:
        self._apply_sources_filter()
    except Exception:
        pass


def add_source_path(win: "MainWindow", path: str) -> bool:
    self = win

    d = str(path or "").strip()
    if not d:
        return False

    try:
        d_norm = str(Path(d).expanduser().resolve())
    except Exception:
        d_norm = d

    try:
        self._ensure_base_row()
    except Exception:
        pass

    try:
        base_norm = str(Path(self.base_edit.text().strip()).expanduser().resolve()) if self.base_edit.text().strip() else ""
    except Exception:
        base_norm = self.base_edit.text().strip()
    if base_norm and base_norm == d_norm:
        self._log("[sources] Not adding Base disc as a Source (already Base).")
        return False

    for r in range(self.sources_table.rowCount()):
        if self._is_base_row(r):
            continue
        existing = (self.sources_table.item(r, 2).text() if self.sources_table.item(r, 2) else "").strip()
        if not existing:
            continue
        try:
            if str(Path(existing).expanduser().resolve()) == d_norm:
                return False
        except Exception:
            if existing == d:
                return False

    row = self.sources_table.rowCount()
    self.sources_table.insertRow(row)
    self.sources_table.setItem(row, 0, QTableWidgetItem(Path(d).name))
    # State (col 1) + Path (col 2)
    st = QTableWidgetItem(self._compute_disc_state(str(d)))
    try:
        st.setTextAlignment(Qt.AlignCenter)
    except Exception:
        pass
    self.sources_table.setItem(row, 1, st)
    self.sources_table.setItem(row, 2, QTableWidgetItem(str(d)))
    try:
        self._apply_source_row_decor(row, str(st.text() if st is not None else ""))
    except Exception:
        pass
    self._update_sources_title()
    try:
        self._apply_sources_filter()
    except Exception:
        pass
    return True


def clear_sources(win: "MainWindow") -> None:
    self = win

    try:
        if self.sources_table.rowCount() <= 0:
            return
    except Exception:
        pass

    resp = QMessageBox.question(self, "Clear Sources", "Remove all Sources?", QMessageBox.Yes | QMessageBox.No)
    if resp != QMessageBox.Yes:
        return

    self.sources_table.setRowCount(0)
    self._ensure_base_row()
    self._update_sources_title()
    try:
        self._apply_sources_filter()
    except Exception:
        pass
    self._log("Cleared all Sources.")


def cleanup_scan(win: "MainWindow") -> None:
    self = win

    try:
        if self._scan_thread is not None:
            self._scan_thread.quit()
            if QThread.currentThread() is not self._scan_thread:
                self._scan_thread.wait(1500)
    except Exception:
        pass
    self._scan_thread = None
    self._scan_worker = None
    self._cancel_token = None
    self._set_op_running(False)
    self._active_op = None


def on_scan_done(win: "MainWindow", found_paths) -> None:
    self = win

    added = 0
    found_list = list(found_paths or [])

    extracted_paths: List[str] = []
    extracted_n = 0
    packed_n = 0
    other_n = 0

    for fp in found_list:
        st = self._compute_disc_state(str(fp))
        if "Extracted" in st:
            extracted_n += 1
            try:
                extracted_paths.append(str(fp))
            except Exception:
                pass
        elif "Packed" in st:
            packed_n += 1
        else:
            other_n += 1

        if self._add_source_path(str(fp)):
            added += 1

    try:
        self._refresh_source_states()
    except Exception:
        pass

    self._log(f"[scan] Done. Found={len(found_list)} Added={added}")
    self._cleanup_scan()

    # Safety (v0.8d): do NOT auto-index after a scan.
    # Instead, offer explicit buttons to index extracted discs and/or extract packed discs.
    msg_lines = [
        f"Found {len(found_list)} disc(s). Added {added} new Source(s).",
        "",
        f"Extracted: {extracted_n}   Packed: {packed_n}   Other: {other_n}",
    ]
    if packed_n:
        msg_lines += [
            "",
            "Packed (unextracted) discs are highlighted in red.",
            "Set the extractor executable and use Extract, then Refresh Songs (or rescan).",
        ]
    msg = "\n".join(msg_lines)

    try:
        base_ok = bool(self.base_edit.text().strip())
    except Exception:
        base_ok = False
    try:
        extractor_ok = bool(self.extractor_edit.text().strip())
    except Exception:
        extractor_ok = False

    dlg = QMessageBox(self)
    dlg.setIcon(QMessageBox.Information)
    dlg.setWindowTitle("Scan complete")
    dlg.setText(msg)

    btn_close = dlg.addButton("Close", QMessageBox.AcceptRole)
    btn_index = None
    btn_extract = None

    if base_ok and extracted_n:
        btn_index = dlg.addButton("Index Extracted Now", QMessageBox.ActionRole)

    if packed_n:
        btn_extract = dlg.addButton("Extract Packed Now", QMessageBox.ActionRole)
        try:
            if not extractor_ok:
                btn_extract.setEnabled(False)
        except Exception:
            pass

    # Helpful hint in the "informative" area
    hints = []
    if not base_ok:
        hints.append("Set Base first to index songs.")
    if packed_n and not extractor_ok:
        hints.append("To extract packed discs, set the extractor executable first.")
    if base_ok and extracted_n:
        hints.append("Tip: You can select a few Sources and click Refresh Songs to index in batches.")
    if hints:
        try:
            dlg.setInformativeText("\n".join(hints))
        except Exception:
            pass

    dlg.exec()

    clicked = dlg.clickedButton()
    if clicked is btn_index:
        try:
            self._start_refresh_songs(auto=False, only_extracted=True)
        except Exception:
            pass
    elif clicked is btn_extract:
        try:
            self._start_extract_packed_only()
        except Exception:
            pass
    else:
        _ = btn_close


def on_scan_cancelled(win: "MainWindow") -> None:
    self = win

    self._log("[scan] Cancelled.")
    self._cleanup_scan()


def on_scan_error(win: "MainWindow", msg: str) -> None:
    self = win

    self._log(f"[scan] ERROR: {msg}")
    self._cleanup_scan()
    self._show_critical_with_logs("Scan failed", str(msg or "Unknown error"), tip="Tip: Check the logs for details.")


def scan_sources_root(win: "MainWindow") -> None:
    self = win

    if self._any_op_running():
        self._log("[scan] Another operation is already running.")
        return

    root_dir = QFileDialog.getExistingDirectory(self, "Scan folder for discs")
    if not root_dir:
        return

    self._active_op = "scan"
    self._cancel_token = CancelToken()
    self._set_op_running(True)

    self._log(f"[scan] Scanning: {root_dir}")

    # Run scan in background to keep UI responsive.
    self._scan_thread = QThread()
    self._scan_worker = ScanWorker(str(root_dir), max_depth=4, cancel_token=self._cancel_token)
    self._scan_worker.moveToThread(self._scan_thread)

    self._scan_thread.started.connect(self._scan_worker.run, Qt.QueuedConnection)
    self._scan_worker.log.connect(self._log)

    # Ensure UI updates happen on the GUI thread (avoid Qt crashes from cross-thread widget updates).
    self._scan_worker.done.connect(self._on_scan_done, Qt.QueuedConnection)
    self._scan_worker.cancelled.connect(self._on_scan_cancelled, Qt.QueuedConnection)
    self._scan_worker.error.connect(self._on_scan_error, Qt.QueuedConnection)

    try:
        self._scan_thread.finished.connect(self._scan_thread.deleteLater)
        self._scan_worker.finished.connect(self._scan_worker.deleteLater)
    except Exception:
        pass

    self._scan_thread.start()


def add_source(win: "MainWindow") -> None:
    self = win

    d = QFileDialog.getExistingDirectory(self, "Add Source disc folder")
    if not d:
        return
    added = self._add_source_path(str(d))
    if added:
        self._log(f"Added source: {d}")
        try:
            self._refresh_source_states()
        except Exception:
            pass
        # Auto-refresh songs after adding a Source (only runs if Base is set)
        try:
            self._start_refresh_songs(auto=True)
        except Exception:
            pass
    else:
        self._log(f"Source already present: {d}")


def remove_selected_sources(win: "MainWindow") -> None:
    self = win

    sel_rows = sorted({i.row() for i in self.sources_table.selectedIndexes()}, reverse=True)
    if not sel_rows:
        return

    to_remove = []
    hidden_ignored = 0
    for row in sel_rows:
        if self._is_base_row(row):
            continue
        try:
            if bool(self.sources_table.isRowHidden(int(row))):
                hidden_ignored += 1
                continue
        except Exception:
            pass
        try:
            to_remove.append(int(row))
        except Exception:
            pass

    if hidden_ignored:
        try:
            self._log(f"[sources] Remove Selected: ignored {hidden_ignored} hidden row(s) (filtered).")
        except Exception:
            pass

    for row in to_remove:
        p = (self.sources_table.item(row, 2).text() if self.sources_table.item(row, 2) else "").strip()
        self.sources_table.removeRow(row)
        if p:
            self._log(f"Removed source: {p}")

    self._update_sources_title()
    self._refresh_source_states()
