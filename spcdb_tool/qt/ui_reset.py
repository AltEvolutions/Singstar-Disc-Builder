# ruff: noqa
from __future__ import annotations

"""Qt UI reset helpers (internal).

Extracted from `spcdb_tool/qt/main_window.py` as part of the incremental Qt refactor.
Behavior is intended to be unchanged.

This module is imported lazily from `spcdb_tool.qt.main_window`.
"""

from typing import TYPE_CHECKING

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QMessageBox

if TYPE_CHECKING:
    from .main_window import MainWindow


def reset_ui_state_action(win: "MainWindow") -> None:
    msg = (
        "This will reset Qt UI state (filters, disabled songs, collapsed groups, and conflict overrides).\n\n"
        "It will NOT delete discs, caches, or output folders."
    )
    try:
        r = QMessageBox.question(win, "Reset UI state", msg, QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if r != QMessageBox.Yes:
            return
    except Exception:
        pass

    p = None
    try:
        p = win._qt_state_path()
    except Exception:
        p = None

    try:
        if p and p.exists():
            p.unlink()
            win._log(f"[ui] Reset UI state: deleted {p}")
    except Exception as e:
        win._log(f"[ui] Reset UI state failed: {e}")

    # Reset widgets + in-memory (best-effort)
    try:
        win.song_search_edit.setText("")
    except Exception:
        pass
    try:
        ix = win.song_source_combo.findData("All")
        if ix < 0:
            ix = win.song_source_combo.findText("All")
        if ix < 0:
            ix = 0
        win.song_source_combo.setCurrentIndex(int(ix))
    except Exception:
        pass
    try:
        win.song_selected_only_chk.setChecked(False)
    except Exception:
        pass
    try:
        win._disabled_song_ids = set()
    except Exception:
        pass
    try:
        win._song_source_overrides = {}
    except Exception:
        pass
    try:
        win._song_group_expanded = {}
    except Exception:
        pass

    try:
        if win.base_edit.text().strip():
            win._start_refresh_songs(auto=True)
    except Exception:
        pass


def apply_default_ui_splitters(win: "MainWindow") -> None:
    try:
        ms = getattr(win, "_main_split", None)
        if ms is not None:
            try:
                ms.setStretchFactor(0, 0)
                ms.setStretchFactor(1, 1)
                ms.setStretchFactor(2, 0)
            except Exception:
                pass
            try:
                ms.setSizes([320, 760, 320])
            except Exception:
                pass
    except Exception:
        pass
    try:
        cs = getattr(win, "_center_split", None)
        if cs is not None:
            try:
                cs.setStretchFactor(0, 8)
                cs.setStretchFactor(1, 2)
            except Exception:
                pass
            try:
                cs.setSizes([520, 160])
            except Exception:
                pass
    except Exception:
        pass


def apply_default_ui_columns(win: "MainWindow") -> None:
    # Sources table
    try:
        if getattr(win, "sources_table", None) is not None:
            win.sources_table.setColumnWidth(0, 180)
            win.sources_table.setColumnWidth(1, 140)
            win.sources_table.setColumnWidth(2, 520)
    except Exception:
        pass
    # Songs table
    try:
        if getattr(win, "songs_table", None) is not None:
            win.songs_table.setColumnWidth(0, 44)
            win.songs_table.setColumnWidth(1, 420)
            win.songs_table.setColumnWidth(2, 260)
            win.songs_table.setColumnWidth(3, 150)
            win.songs_table.setColumnWidth(4, 460)
            win.songs_table.setColumnWidth(5, 90)
    except Exception:
        pass


def reset_layout_action(win: "MainWindow") -> None:
    # Reset splitters to built-in defaults and persist to Qt state.
    try:
        apply_default_ui_splitters(win)
        try:
            QTimer.singleShot(0, lambda: apply_default_ui_splitters(win))
        except Exception:
            pass
        win._save_qt_state(force=True)
        win._log("[ui] Reset layout to defaults.")
    except Exception as e:
        win._log(f"[ui] Reset layout failed: {e}")


def reset_columns_action(win: "MainWindow") -> None:
    # Reset table column widths to built-in defaults and persist to Qt state.
    try:
        apply_default_ui_columns(win)
        try:
            QTimer.singleShot(0, lambda: apply_default_ui_columns(win))
        except Exception:
            pass
        win._save_qt_state(force=True)
        win._log("[ui] Reset columns to defaults.")
    except Exception as e:
        win._log(f"[ui] Reset columns failed: {e}")
