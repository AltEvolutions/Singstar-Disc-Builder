# ruff: noqa
from __future__ import annotations

"""Qt Sources panel (internal).

Extracted from `spcdb_tool/qt/main_window.py` as part of the incremental Qt refactor.
Behavior is intended to be unchanged.

This module is imported lazily from `spcdb_tool.qt.main_window`.
"""

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from .main_window import MainWindow


def build_sources_panel(win: "MainWindow") -> QWidget:
    # Keep the original variable name used in main_window to minimize risk.
    self = win

    left = QWidget()
    left_v = QVBoxLayout(left)
    try:
        left_v.setContentsMargins(0, 0, 0, 0)
    except Exception:
        pass
    gb_sources = QGroupBox("Sources")
    gb_sources_v = QVBoxLayout(gb_sources)

    # Base disc (treated as a source)
    row_base = QHBoxLayout()
    row_base.addWidget(QLabel("Base disc:"))
    row_base.addWidget(self.base_edit, 1)
    self.btn_browse_base = QPushButton("Browse")
    self.btn_browse_base.clicked.connect(self._browse_base)
    try:
        self.btn_browse_base.setToolTip("Browse for Base disc folder.")
        self.btn_browse_base.setStatusTip("Browse for Base disc folder.")
    except Exception:
        pass
    try:
        self.base_edit.textChanged.connect(lambda _t: self._on_base_changed())
    except Exception:
        pass
    row_base.addWidget(self.btn_browse_base)
    gb_sources_v.addLayout(row_base)

    gb_sources_v.addWidget(self.sources_title_lbl)
    gb_sources_v.addWidget(self.sources_tallies_lbl)

    row_sources_filter = QHBoxLayout()

    try:

        row_sources_filter.setContentsMargins(0, 0, 0, 0)

    except Exception:

        pass

    row_sources_filter.addWidget(self.sources_filter_edit, 1)
    try:
        self.sources_filter_edit.setToolTip("Filter Sources by Label/Path.")
        self.sources_filter_edit.setStatusTip("Filter Sources by Label/Path.")
    except Exception:
        pass

    row_sources_filter.addWidget(self.btn_sources_states)

    row_sources_filter.addWidget(self.btn_sources_select_shown)

    row_sources_filter.addWidget(self.btn_sources_clear_sel)

    gb_sources_v.addLayout(row_sources_filter)
    gb_sources_v.addWidget(self.sources_table, 1)
    left_v.addWidget(gb_sources, 3)

    gb_src_actions = QGroupBox("Source actions")
    row_src_btns = QHBoxLayout()
    gb_src_actions.setLayout(row_src_btns)
    # Add discs (dropdown): Scan folder… / Add disc…
    self.btn_add_discs = QToolButton()
    self.btn_add_discs.setText("Add discs…")
    try:
        self.btn_add_discs.setToolTip("Add disc folders as Sources (scan a folder or add a single disc).")
        self.btn_add_discs.setStatusTip("Add disc folders as Sources.")
    except Exception:
        pass
    try:
        m = QMenu(self)
        try:
            m.setToolTipsVisible(True)
        except Exception:
            pass
        act_scan = QAction("Scan folder…", self)
        try:
            act_scan.setToolTip("Scan a folder and add all detected discs as Sources.")
        except Exception:
            pass
        try:
            act_scan.setStatusTip("Scan a folder and add detected discs.")
        except Exception:
            pass
        act_scan.triggered.connect(self._scan_sources_root)
        m.addAction(act_scan)

        act_add = QAction("Add disc…", self)
        try:
            act_add.setToolTip("Add a single disc folder as a Source.")
        except Exception:
            pass
        try:
            act_add.setStatusTip("Add a single disc folder as a Source.")
        except Exception:
            pass
        act_add.triggered.connect(self._add_source)
        m.addAction(act_add)
        self.btn_add_discs.setMenu(m)
        self.btn_add_discs.setPopupMode(QToolButton.InstantPopup)
    except Exception:
        # Fallback: behave like scan if menu can't be built
        try:
            self.btn_add_discs.clicked.connect(self._scan_sources_root)
        except Exception:
            pass
    self.btn_remove_sources = QPushButton("Remove Selected (visible)")
    try:
        self.btn_remove_sources.setToolTip("Remove selected visible Source rows (ignores filtered-out rows).")
        self.btn_remove_sources.setStatusTip("Remove selected visible Source rows.")
    except Exception:
        pass
    self.btn_remove_sources.clicked.connect(self._remove_selected_sources)
    self.btn_clear_sources = QPushButton("Clear Sources")
    try:
        self.btn_clear_sources.setToolTip("Remove all Sources (keeps Base path).")
        self.btn_clear_sources.setStatusTip("Clear all Sources.")
    except Exception:
        pass
    self.btn_clear_sources.clicked.connect(self._clear_sources)

    row_src_btns.addWidget(self.btn_add_discs)
    row_src_btns.addWidget(self.btn_remove_sources)
    row_src_btns.addWidget(self.btn_clear_sources)
    left_v.addWidget(gb_src_actions)
    gb_extractor = QGroupBox("Extractor tool")
    exe_v = QVBoxLayout(gb_extractor)

    row_exe = QHBoxLayout()
    row_exe.addWidget(QLabel("Extractor tool:"))
    row_exe.addWidget(self.extractor_edit, 1)
    try:
        self.extractor_edit.setStatusTip("SCEE extractor executable (needed for packed sources).")
    except Exception:
        pass
    self.btn_browse_extractor = QPushButton("Browse")
    self.btn_browse_extractor.clicked.connect(self._browse_extractor)
    try:
        self.btn_browse_extractor.setToolTip("Browse for extractor executable (scee_london / scee_london.exe).")
        self.btn_browse_extractor.setStatusTip("Browse for extractor executable (scee_london / scee_london.exe).")
    except Exception:
        pass
    row_exe.addWidget(self.btn_browse_extractor)
    exe_v.addLayout(row_exe)

    left_v.addWidget(gb_extractor)


    return left
