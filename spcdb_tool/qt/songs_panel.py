# ruff: noqa
from __future__ import annotations

"""Qt Songs/Log/Output center panel (internal).

Extracted from `spcdb_tool/qt/main_window.py` as part of the incremental Qt refactor.
Behavior is intended to be unchanged.

This module is imported lazily from `spcdb_tool.qt.main_window`.
"""

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from .main_window import MainWindow


def build_songs_panel(win: "MainWindow") -> QWidget:
    # Keep the original variable name used in main_window to minimize risk.
    self = win

    center = QWidget()
    center_v = QVBoxLayout(center)
    try:
        center_v.setContentsMargins(0, 0, 0, 0)
    except Exception:
        pass

    # Filters / bulk actions row
    row_song_filters = QHBoxLayout()
    row_song_filters.addWidget(QLabel("Search:"))
    row_song_filters.addWidget(self.song_search_edit, 1)
    row_song_filters.addWidget(QLabel("Source:"))
    row_song_filters.addWidget(self.song_source_combo)
    row_song_filters.addWidget(self.song_selected_only_chk)

    # Bulk actions (visible)
    row_song_filters.addSpacing(10)
    row_song_filters.addWidget(self.btn_select_all_visible)
    row_song_filters.addWidget(self.btn_clear_visible)
    row_song_filters.addWidget(self.btn_invert_visible)

    # Views (0.8e)
    row_song_filters.addSpacing(10)
    row_song_filters.addWidget(QLabel("View:"))
    row_song_filters.addWidget(self.song_preset_combo)


    try:
        self.song_preset_combo.setToolTip(
            'Quick views (filters only):\n'
            '• All songs: no special filters\n'
            '• Conflicts: show only songs with conflicting files between sources\n'
            '• Duplicates: show only Song IDs present in 2+ sources\n'
            '• Overrides: show only songs with a forced source override\n'
            '• Disabled: show only songs currently turned off\n'
            '\n'
            'Presets do not modify disc files.'
        )
    except Exception:
        pass
    row_song_filters.addStretch(1)
    row_song_filters.addWidget(self.btn_refresh_songs)
    center_v.addLayout(row_song_filters)

    center_split = QSplitter(Qt.Vertical)
    self._center_split = center_split
    center_v.addWidget(center_split, 1)

    gb_songs = QGroupBox("Songs")
    songs_wrap_v = QVBoxLayout(gb_songs)
    try:
        songs_wrap_v.setContentsMargins(6, 6, 6, 6)
    except Exception:
        pass
    songs_wrap_v.addWidget(self.songs_table, 1)

    # Summary strip (songs/selected/cache)
    summary_row = QHBoxLayout()
    summary_row.addWidget(self.songs_status_lbl)
    summary_row.addSpacing(12)
    summary_row.addWidget(self.cache_status_lbl)
    summary_row.addStretch(1)
    songs_wrap_v.addLayout(summary_row)

    center_split.addWidget(gb_songs)

    gb_log = QGroupBox("Log")
    log_v = QVBoxLayout(gb_log)
    try:
        log_v.setContentsMargins(6, 6, 6, 6)
    except Exception:
        pass
    log_v.addWidget(self.log_edit, 1)
    center_split.addWidget(gb_log)

    try:
        center_split.setStretchFactor(0, 8)
        center_split.setStretchFactor(1, 2)
        center_split.setSizes([520, 160])
    except Exception:
        pass

    # Output (build) controls (kept near songs/log)
    gb_output = QGroupBox("Output")
    out_v = QVBoxLayout(gb_output)
    try:
        out_v.setContentsMargins(6, 6, 6, 6)
    except Exception:
        pass

    row_out = QHBoxLayout()
    row_out.addWidget(QLabel("Output location:"))
    row_out.addWidget(self.output_edit, 1)
    self.btn_browse_output = QPushButton("Browse")
    self.btn_browse_output.clicked.connect(self._browse_output)
    try:
        self.btn_browse_output.setToolTip("Choose the parent folder for build output.")
        self.btn_browse_output.setStatusTip("Browse for output folder.")
    except Exception:
        pass

    row_out.addWidget(self.btn_browse_output)
    out_v.addLayout(row_out)

    row_build = QGridLayout()
    try:
        row_build.setColumnStretch(0, 1)
        row_build.setColumnStretch(1, 1)
    except Exception:
        pass
    try:
        self.btn_build.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.btn_cancel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    except Exception:
        pass
    try:
        self.btn_update_existing.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    except Exception:
        pass
    row_build.addWidget(self.btn_build, 0, 0)
    row_build.addWidget(self.btn_cancel, 0, 1)
    row_build.addWidget(self.btn_update_existing, 1, 0, 1, 2)
    out_v.addLayout(row_build)

    center_v.addWidget(gb_output)

    return center
