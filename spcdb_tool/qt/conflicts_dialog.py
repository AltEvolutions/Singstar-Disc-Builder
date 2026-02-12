"""Conflict resolver dialog (internal).

Extracted from `spcdb_tool/qt_app.py` as part of the incremental Qt refactor.
Behavior is intended to be unchanged.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET

from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..controller import SongOccur


class ConflictResolverDialog(QDialog):
    """Resolve true conflicts (same Song ID, different content) by selecting a winning source."""

    def __init__(self, parent, *, conflicts: Dict[int, Tuple[SongOccur, ...]], overrides: Dict[int, str], export_roots_by_label: Optional[Dict[str, str]] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Resolve Conflicts")
        # Sensible default size so the 3-pane layout is readable on first open.
        try:
            self.resize(1200, 720)
            self.setMinimumSize(980, 560)
        except Exception:
            pass
        self._conflicts = dict(conflicts or {})
        self._overrides: Dict[int, str] = dict(overrides or {})
        self._export_roots_by_label: Dict[str, str] = dict(export_roots_by_label or {})
        # C5: caches are keyed by export root (labels can repeat across sessions).
        self._cmp_meta_cache: Dict[Tuple[str, str, int], Dict[str, object]] = {}
        self._cmp_assets_cache: Dict[Tuple[str, str, int], Dict[str, object]] = {}
        self._cmp_melody_cache: Dict[Tuple[str, str, int], Dict[str, object]] = {}
        self._cmp_media_cache: Dict[Tuple[str, str, int, str], Dict[str, object]] = {}
        self._cmp_acts_cache: Dict[str, Dict[str, object]] = {}
        self._cmp_diff_cache: Dict[Tuple[int, str, str], Dict[str, object]] = {}

        self._identical_by_sid: Dict[int, bool] = {}
        self._identical_summary_by_sid: Dict[int, str] = {}
        self._identical_detection_ran: bool = False

        # N3/N4: classification (identical vs effectively identical vs different)
        self._dupe_class_by_sid: Dict[int, str] = {}
        self._dupe_summary_by_sid: Dict[int, str] = {}

        # Speedrun P2: cache safe recommendations so filtering doesn't repeatedly scan.
        self._rec_cache_by_sid: Dict[int, Tuple[str, str]] = {}


        self._ids: List[int] = sorted(int(k) for k in (self._conflicts or {}).keys())

        root = QVBoxLayout(self)
        try:
            root.setContentsMargins(10, 10, 10, 10)
        except Exception:
            pass

        top_lbl = QLabel("Candidates are detected when the same Song ID exists in multiple sources with different melody_1.xml SHA1. Use 'Detect identical duplicates' to classify by melody fingerprint.")
        try:
            top_lbl.setWordWrap(True)
        except Exception:
            pass
        root.addWidget(top_lbl)

        # Variant A layout: dialog-wide header controls (actions + filters + current song).
        # This avoids the header being crushed by the left splitter pane.
        top_controls = QWidget()
        top_v = QVBoxLayout(top_controls)
        try:
            top_v.setContentsMargins(0, 0, 0, 0)
        except Exception:
            pass
        
        row_actions = QHBoxLayout()
        self.btn_detect_identical = QPushButton("Detect identical duplicates")
        row_actions.addWidget(self.btn_detect_identical)
        self.btn_auto_resolve_identical = QPushButton("Auto-resolve identical")
        try:
            self.btn_auto_resolve_identical.setEnabled(False)
        except Exception:
            pass
        row_actions.addWidget(self.btn_auto_resolve_identical)
        self.btn_auto_pick_quality = QPushButton("Auto-pick best quality")
        try:
            self.btn_auto_pick_quality.setEnabled(False)
        except Exception:
            pass
        row_actions.addWidget(self.btn_auto_pick_quality)
        
        # Speedrun P2: jump to next unresolved
        self.btn_next_unresolved = QPushButton("Next unresolved")
        try:
            self.btn_next_unresolved.setToolTip("Jump to the next unresolved conflict (no override).")
        except Exception:
            pass
        row_actions.addWidget(self.btn_next_unresolved)

        # Speedrun P3: apply safe recommendations in bulk.
        self.btn_apply_recommended = QPushButton("Apply recommended")
        try:
            self.btn_apply_recommended.setEnabled(False)  # enabled after 'Detect identical duplicates'
            self.btn_apply_recommended.setToolTip("Apply recommended choices to all visible unresolved conflicts (only when candidates are verified identical).")
        except Exception:
            pass
        row_actions.addWidget(self.btn_apply_recommended)

        row_actions.addStretch(1)
        top_v.addLayout(row_actions)
        
        row_filters = QHBoxLayout()
        self.chk_show_identical = QCheckBox("Show identical duplicates")
        try:
            self.chk_show_identical.setChecked(False)
        except Exception:
            pass
        row_filters.addWidget(self.chk_show_identical)
        
        self.chk_unresolved_only = QCheckBox("Unresolved only")
        try:
            self.chk_unresolved_only.setChecked(False)
            self.chk_unresolved_only.setToolTip("Show only conflicts that do not have an override set.")
        except Exception:
            pass
        row_filters.addWidget(self.chk_unresolved_only)
        
        self.chk_recommended_only = QCheckBox("Recommended")
        try:
            self.chk_recommended_only.setChecked(False)
            self.chk_recommended_only.setEnabled(False)  # enabled after 'Detect identical duplicates'
            self.chk_recommended_only.setToolTip("Show only conflicts with a recommendation (generated for identical duplicates; run 'Detect identical duplicates' first).")
        except Exception:
            pass
        row_filters.addWidget(self.chk_recommended_only)
        
        # Speedrun P1: optional auto-advance after Apply/Clear.
        self.chk_auto_advance = QCheckBox("Auto-advance")
        try:
            self.chk_auto_advance.setChecked(True)
            self.chk_auto_advance.setToolTip("After Apply/Clear, jump to the next conflict. Hotkeys: A/B (pick compare A/B), N/P (next/prev), Del (clear).")
        except Exception:
            pass
        row_filters.addWidget(self.chk_auto_advance)
        
        row_filters.addStretch(1)
        top_v.addLayout(row_filters)
        
        self.current_song_lbl = QLabel("")
        self._current_song_full = ""
        try:
            self.current_song_lbl.setWordWrap(False)
            self.current_song_lbl.setStyleSheet("font-weight: 600;")
        except Exception:
            pass
        top_v.addWidget(self.current_song_lbl)
        
        root.addWidget(top_controls)
        body = QSplitter()
        # Keep references so we can apply nicer default splitter sizes.
        self._conflict_body_split = body
        try:
            body.setChildrenCollapsible(False)
        except Exception:
            pass
        root.addWidget(body, 1)

        # Left: conflict list
        left = QWidget()
        left_v = QVBoxLayout(left)
        try:
            left_v.setContentsMargins(0, 0, 0, 0)
        except Exception:
            pass



        self.listw = QListWidget()
        left_v.addWidget(self.listw, 1)
        body.addWidget(left)

        # Right: details + compare (C1 skeleton)
        right_split = QSplitter()
        self._conflict_right_split = right_split
        try:
            right_split.setChildrenCollapsible(False)
        except Exception:
            pass
        try:
            right_split.setOrientation(Qt.Horizontal)
        except Exception:
            pass

        # Details pane
        right = QWidget()
        right_v = QVBoxLayout(right)
        try:
            right_v.setContentsMargins(0, 0, 0, 0)
        except Exception:
            pass

        self.title_lbl = QLabel("")
        try:
            self.title_lbl.setWordWrap(True)
        except Exception:
            pass
        try:
            self.title_lbl.setVisible(False)
        except Exception:
            pass
        right_v.addWidget(self.title_lbl)

        self.status_lbl = QLabel("")
        try:
            self.status_lbl.setWordWrap(True)
        except Exception:
            pass
        right_v.addWidget(self.status_lbl)

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Source", "Melody FP"])
        try:
            self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
            self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
            self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        except Exception:
            pass
        right_v.addWidget(self.table, 1)
        # Default column sizing (Source readable; SHA uses remaining space).
        try:
            from PySide6.QtWidgets import QHeaderView
            hdr = self.table.horizontalHeader()
            hdr.setSectionResizeMode(0, QHeaderView.ResizeToContents)
            hdr.setSectionResizeMode(1, QHeaderView.Stretch)
            try:
                hdr.setMinimumSectionSize(140)
            except Exception:
                pass
        except Exception:
            pass
        row_win = QHBoxLayout()
        row_win.addWidget(QLabel("Winner:"))
        self.winner_combo = QComboBox()
        row_win.addWidget(self.winner_combo, 1)
        self.btn_apply = QPushButton("Apply")
        self.btn_clear = QPushButton("Clear Override")
        row_win.addWidget(self.btn_apply)
        row_win.addWidget(self.btn_clear)
        right_v.addLayout(row_win)

        right_split.addWidget(right)

        # Compare pane (placeholder; real diffs come in later patches)
        compare = QWidget()
        cmp_v = QVBoxLayout(compare)
        try:
            cmp_v.setContentsMargins(0, 0, 0, 0)
        except Exception:
            pass

        cmp_hdr = QLabel("Compare")
        try:
            f = cmp_hdr.font()
            f.setPointSize(max(10, int(f.pointSize()) + 1))
            f.setBold(True)
            cmp_hdr.setFont(f)
        except Exception:
            pass
        cmp_v.addWidget(cmp_hdr)

        self.cmp_info_lbl = QLabel("Select a conflict on the left to compare two sources.")
        try:
            self.cmp_info_lbl.setWordWrap(True)
        except Exception:
            pass
        cmp_v.addWidget(self.cmp_info_lbl)

        form = QFormLayout()
        self.cmp_a_combo = QComboBox()
        self.cmp_b_combo = QComboBox()
        form.addRow("A:", self.cmp_a_combo)
        form.addRow("B:", self.cmp_b_combo)
        cmp_v.addLayout(form)

        row_cmp_btn = QHBoxLayout()
        self.btn_compute_diff = QPushButton("Compute differences")
        row_cmp_btn.addWidget(self.btn_compute_diff)
        row_cmp_btn.addStretch(1)
        cmp_v.addLayout(row_cmp_btn)

        self.cmp_table = QTableWidget(0, 3)
        self.cmp_table.setHorizontalHeaderLabels(["Field", "A", "B"])
        try:
            self.cmp_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
            self.cmp_table.setSelectionMode(QAbstractItemView.NoSelection)
        except Exception:
            pass
        cmp_v.addWidget(self.cmp_table, 1)
        # Default column sizing (Field fits content; A/B share remaining space).
        try:
            from PySide6.QtWidgets import QHeaderView
            hdr = self.cmp_table.horizontalHeader()
            hdr.setSectionResizeMode(0, QHeaderView.ResizeToContents)
            hdr.setSectionResizeMode(1, QHeaderView.Stretch)
            hdr.setSectionResizeMode(2, QHeaderView.Stretch)
            try:
                hdr.setMinimumSectionSize(140)
            except Exception:
                pass
        except Exception:
            pass
        right_split.addWidget(compare)

        body.addWidget(right_split)
        try:
            body.setStretchFactor(0, 3)
            body.setStretchFactor(1, 7)
            right_split.setStretchFactor(0, 5)
            right_split.setStretchFactor(1, 5)
        except Exception:
            pass

        # Apply nicer default splitter sizes after the first layout pass.
        try:
            QTimer.singleShot(0, self._apply_conflict_dialog_default_layout)
        except Exception:
            pass

        # Bottom buttons
        row_btn = QHBoxLayout()
        row_btn.addStretch(1)
        self.btn_close = QPushButton("Close")
        row_btn.addWidget(self.btn_close)
        root.addLayout(row_btn)

        self.btn_close.clicked.connect(self.accept)
        self.btn_apply.clicked.connect(self._apply_current)
        self.btn_clear.clicked.connect(self._clear_current)
        self.listw.currentItemChanged.connect(self._on_sel_changed)
        try:
            self.btn_detect_identical.clicked.connect(self._detect_identical_all)
        except Exception:
            pass
        try:
            self.btn_auto_resolve_identical.clicked.connect(self._auto_resolve_identical_all)
            self.btn_auto_pick_quality.clicked.connect(self._auto_pick_best_quality_all)
        except Exception:
            pass
        try:
            self.chk_show_identical.toggled.connect(self._on_toggle_show_identical)
        except Exception:
            pass

        try:
            self.chk_unresolved_only.toggled.connect(self._on_filters_changed)
            self.chk_recommended_only.toggled.connect(self._on_filters_changed)
        except Exception:
            pass
        try:
            self.btn_next_unresolved.clicked.connect(self._goto_next_unresolved)
        except Exception:
            pass
        try:
            self.btn_apply_recommended.clicked.connect(self._apply_recommended_bulk)
        except Exception:
            pass

        try:
            self.cmp_a_combo.currentTextChanged.connect(self._on_compare_changed)
            self.cmp_b_combo.currentTextChanged.connect(self._on_compare_changed)
            self.btn_compute_diff.clicked.connect(self._compute_diff)
            self.btn_compute_diff.setEnabled(False)
        except Exception:
            pass


        # Speedrun P1: hotkeys (best-effort). These are intentionally simple and work across panes.
        # - A / B: pick compare A or B as Winner and Apply
        # - N / P: next / previous conflict
        # - Delete / Backspace: Clear override
        try:
            from PySide6.QtGui import QKeySequence, QShortcut

            def _mk(seq: str, cb) -> QShortcut:
                sc = QShortcut(QKeySequence(seq), self)
                try:
                    sc.setContext(Qt.WindowShortcut)
                except Exception:
                    pass
                sc.activated.connect(cb)
                return sc

            self._sc_next = _mk("N", self._goto_next)
            self._sc_prev = _mk("P", self._goto_prev)
            self._sc_next2 = _mk("Ctrl+Down", self._goto_next)
            self._sc_prev2 = _mk("Ctrl+Up", self._goto_prev)

            self._sc_pick_a = _mk("A", self._pick_compare_a)
            self._sc_pick_b = _mk("B", self._pick_compare_b)
            self._sc_pick_a2 = _mk("Ctrl+1", self._pick_compare_a)
            self._sc_pick_b2 = _mk("Ctrl+2", self._pick_compare_b)

            self._sc_clear = _mk("Delete", self._clear_current)
            self._sc_clear2 = _mk("Backspace", self._clear_current)
        except Exception:
            pass


        self._populate_list()
        if self.listw.count() > 0:
            self.listw.setCurrentRow(0)

    def overrides(self) -> Dict[int, str]:
        return dict(self._overrides or {})

    def _apply_conflict_dialog_default_layout(self) -> None:
        """Set sensible initial pane/column sizing for the Resolve Conflicts dialog.

        This is intentionally best-effort and only affects the initial layout.
        Users can still resize panes/columns freely.
        """
        # Pane minimums
        try:
            self.listw.setMinimumWidth(320)
        except Exception:
            pass
        try:
            self.table.setMinimumWidth(360)
        except Exception:
            pass

        # Splitter sizing (3-pane: conflicts | sources | compare)
        try:
            w = max(int(self.width() or 0), 1000)
        except Exception:
            w = 1000

        try:
            bs = getattr(self, "_conflict_body_split", None)
            if bs is not None:
                # Give the left list enough room for titles, but keep compare dominant.
                left_w = max(320, int(w * 0.34))
                bs.setSizes([left_w, max(520, w - left_w)])
        except Exception:
            pass

        try:
            rs = getattr(self, "_conflict_right_split", None)
            if rs is not None:
                # Inside right: sources table (left) vs compare (right)
                right_w = max(int(w - 320), 680)
                details_w = max(380, int(right_w * 0.44))
                rs.setSizes([details_w, max(420, right_w - details_w)])
        except Exception:
            pass

    def _populate_list(self) -> None:
        self.listw.clear()

        try:
            show_ident = bool(self.chk_show_identical.isChecked())
        except Exception:
            show_ident = False
        try:
            unresolved_only = bool(self.chk_unresolved_only.isChecked())
        except Exception:
            unresolved_only = False
        try:
            recommended_only = bool(self.chk_recommended_only.isChecked())
        except Exception:
            recommended_only = False

        for sid in self._ids:
            occs = self._conflicts.get(int(sid)) or ()
            title = ""
            artist = ""
            try:
                if occs:
                    title = str(getattr(occs[0], "title", "") or "")
                    artist = str(getattr(occs[0], "artist", "") or "")
            except Exception:
                pass
            txt = f"{sid} — {title} — {artist}".strip()
            ov = str(self._overrides.get(int(sid), "") or "").strip()

            # Filter: unresolved only
            if unresolved_only and ov:
                continue

            cls = ""
            summ = ""
            try:
                if self._identical_detection_ran:
                    cls = str(self._dupe_class_by_sid.get(int(sid), "") or "").strip().lower()
                    summ = str(self._dupe_summary_by_sid.get(int(sid), "") or "").strip()
            except Exception:
                cls = ""
                summ = ""

            # Hide identical duplicates by default (unless explicitly shown or overridden)
            if cls == "identical" and (not show_ident) and (not ov):
                continue

            # Filter: recommended only (implies unresolved)
            rec_lab = ""
            _rec_reason = ""
            if recommended_only:
                if ov:
                    continue
                try:
                    rec_lab, _rec_reason = self._get_recommendation_cached(int(sid), occs=occs)
                except Exception:
                    rec_lab, _rec_reason = ("", "")
                if not rec_lab:
                    continue
            else:
                # Avoid expensive scans here; only compute/display recommendation when it is cheap (identical)
                # or already cached due to user viewing/using the filter.
                try:
                    if (not ov) and self._identical_detection_ran and cls == "identical":
                        rec_lab, _rec_reason = self._get_recommendation_cached(int(sid), occs=occs)
                    elif (not ov):
                        rec_lab, _rec_reason = self._rec_cache_by_sid.get(int(sid), ("", ""))
                except Exception:
                    rec_lab, _rec_reason = ("", "")

            if ov:
                txt += f"  [Override: {ov}]"

            if self._identical_detection_ran and cls:
                if cls == "identical":
                    txt += "  [Identical]"
                elif cls == "effective":
                    if summ:
                        txt += f"  [Effectively identical: {summ}]"
                    else:
                        txt += "  [Effectively identical]"
                elif cls == "different":
                    if summ:
                        txt += f"  [Different: {summ}]"
                    else:
                        txt += "  [Different]"

            if rec_lab and (not ov):
                txt += f"  [Recommended: {rec_lab}]"

            it = QListWidgetItem(txt)
            it.setData(Qt.UserRole, int(sid))
            self.listw.addItem(it)


    def _rebuild_list(self, *, preserve_sid: Optional[int] = None, prefer_row: Optional[int] = None) -> None:
        """Rebuild the left list while keeping selection/scroll stable (best-effort)."""
        if preserve_sid is None:
            try:
                preserve_sid = self._current_song_id()
            except Exception:
                preserve_sid = None
        if prefer_row is None:
            try:
                prefer_row = int(self.listw.currentRow())
            except Exception:
                prefer_row = None

        try:
            sb = self.listw.verticalScrollBar()
            scroll_val = int(sb.value())
        except Exception:
            sb = None
            scroll_val = None

        # Block list signals while we rebuild to reduce flicker.
        try:
            self.listw.blockSignals(True)
        except Exception:
            pass

        self._populate_list()

        # Restore selection (prefer the same Song ID, else nearest row).
        chosen = False
        if preserve_sid is not None:
            try:
                for j in range(self.listw.count()):
                    it = self.listw.item(j)
                    if it is None:
                        continue
                    try:
                        if int(it.data(Qt.UserRole)) == int(preserve_sid):
                            self.listw.setCurrentRow(j)
                            chosen = True
                            break
                    except Exception:
                        continue
            except Exception:
                chosen = False

        if (not chosen) and self.listw.count() > 0:
            try:
                if prefer_row is None or int(prefer_row) < 0:
                    target = 0
                else:
                    target = max(0, min(int(prefer_row), int(self.listw.count()) - 1))
                self.listw.setCurrentRow(int(target))
            except Exception:
                pass

        try:
            self.listw.blockSignals(False)
        except Exception:
            pass

        # Restore scroll position (best-effort).
        try:
            if sb is not None and scroll_val is not None:
                sb.setValue(int(scroll_val))
        except Exception:
            pass

        # Ensure details refresh
        try:
            self._on_sel_changed()
        except Exception:
            pass

    def _on_toggle_show_identical(self, *_args) -> None:
        self._rebuild_list()

    def _on_filters_changed(self, *_args) -> None:
        self._rebuild_list()

    def _is_unresolved_sid(self, sid: int) -> bool:
        try:
            return not bool(str(self._overrides.get(int(sid), "") or "").strip())
        except Exception:
            return True

    def _goto_next_unresolved(self) -> None:
        """Jump to the next unresolved conflict in the current list (wraps)."""
        try:
            n = int(self.listw.count())
        except Exception:
            n = 0
        if n <= 0:
            return

        try:
            start = int(self.listw.currentRow()) + 1
        except Exception:
            start = 0
        if start < 0:
            start = 0

        # Search forward then wrap.
        for pass_no in (0, 1):
            rng = range(start, n) if pass_no == 0 else range(0, min(start, n))
            for i in rng:
                it = self.listw.item(i)
                if it is None:
                    continue
                try:
                    sid = int(it.data(Qt.UserRole))
                except Exception:
                    continue
                if self._is_unresolved_sid(int(sid)):
                    try:
                        self.listw.setCurrentRow(int(i))
                        self.listw.setFocus()
                    except Exception:
                        pass
                    return

    
    def _apply_recommended_bulk(self) -> None:
        """Apply recommended choices to all visible unresolved conflicts (only when candidates are verified identical)."""
        try:
            from PySide6.QtWidgets import QMessageBox, QProgressDialog, QApplication
        except Exception:
            return

        if not bool(getattr(self, "_identical_detection_ran", False)):
            try:
                QMessageBox.information(self, "Apply recommended", "Run 'Detect identical duplicates' first.")
            except Exception:
                pass
            return

        # Collect visible song ids from the current list (respects filters).
        sids: List[int] = []
        try:
            for i in range(int(self.listw.count())):
                it = self.listw.item(i)
                if it is None:
                    continue
                try:
                    sids.append(int(it.data(Qt.UserRole)))
                except Exception:
                    continue
        except Exception:
            sids = []

        if not sids:
            try:
                QMessageBox.information(self, "Apply recommended", "No items are visible to apply recommendations to.")
            except Exception:
                pass
            return

        cur_sid = None
        cur_row = None
        try:
            cur_sid = self._current_song_id()
            cur_row = int(self.listw.currentRow())
        except Exception:
            cur_sid = None
            cur_row = None

        applied = 0
        skipped_overridden = 0
        skipped_no_rec = 0
        skipped_invalid = 0
        processed = 0
        cancelled = False

        use_progress = len(sids) >= 40
        pd = None
        if use_progress:
            try:
                pd = QProgressDialog("Applying recommendations...", "Cancel", 0, len(sids), self)
                pd.setWindowTitle("Apply recommended")
                pd.setMinimumDuration(0)
                pd.setValue(0)
            except Exception:
                pd = None

        for idx, sid in enumerate(list(sids), start=1):
            processed = idx
            if pd is not None:
                try:
                    pd.setValue(idx - 1)
                    QApplication.processEvents()
                    if pd.wasCanceled():
                        cancelled = True
                        break
                except Exception:
                    pass

            try:
                if str(self._overrides.get(int(sid), "") or "").strip():
                    skipped_overridden += 1
                    continue
            except Exception:
                pass

            occs = self._conflicts.get(int(sid)) or ()
            try:
                rec_lab, _rec_reason = self._get_recommendation_cached(int(sid), occs=occs)
            except Exception:
                rec_lab = ""
            rec_lab = str(rec_lab or "").strip()
            if not rec_lab:
                skipped_no_rec += 1
                continue

            # Only apply if the recommendation is one of the candidate labels (defensive).
            ok = False
            try:
                for o in (occs or ()):
                    lab = str(getattr(o, "source_label", "") or "").strip()
                    if lab and lab == rec_lab:
                        ok = True
                        break
            except Exception:
                ok = True

            if not ok:
                skipped_invalid += 1
                continue

            try:
                self._overrides[int(sid)] = rec_lab
                applied += 1
            except Exception:
                skipped_invalid += 1

        if pd is not None:
            try:
                pd.setValue(len(sids))
            except Exception:
                pass

        try:
            self._rec_cache_by_sid.clear()
        except Exception:
            pass

        self._rebuild_list(preserve_sid=cur_sid, prefer_row=cur_row)

        msg = (
            f"Applied: {applied}.\n"
            f"Skipped (already overridden): {skipped_overridden}.\n"
            f"Skipped (no recommendation): {skipped_no_rec}."
        )
        if skipped_invalid:
            msg += f"\nSkipped (invalid): {skipped_invalid}."
        if cancelled:
            msg += f"\n\nStopped early ({max(0, processed - 1)}/{len(sids)})."

        try:
            QMessageBox.information(self, "Apply recommended", msg)
        except Exception:
            pass

    def _get_recommendation_cached(self, song_id: int, *, occs: Optional[Tuple[SongOccur, ...]] = None) -> Tuple[str, str]:
        """Return (label, reason) for a safe recommendation, cached per song_id."""
        try:
            sid = int(song_id)
        except Exception:
            return ("", "")
        try:
            cached = self._rec_cache_by_sid.get(int(sid))
            if cached:
                return (str(cached[0] or ""), str(cached[1] or ""))
        except Exception:
            pass

        if not bool(getattr(self, "_identical_detection_ran", False)):
            return ("", "")

        if occs is None:
            occs = self._conflicts.get(int(sid)) or ()

        labels: List[str] = []
        try:
            for o in (occs or ()):
                lab = str(getattr(o, "source_label", "") or "").strip()
                if lab:
                    labels.append(lab)
        except Exception:
            labels = []

        cls = ""
        try:
            cls = str(self._dupe_class_by_sid.get(int(sid), "") or "").strip().lower()
        except Exception:
            cls = ""

        try:
            rec_lab, rec_reason = self._recommend_winner(int(sid), labels, cls)
        except Exception:
            rec_lab, _rec_reason = ("", "")

        try:
            self._rec_cache_by_sid[int(sid)] = (str(rec_lab or ""), str(rec_reason or ""))
        except Exception:
            pass
        return (str(rec_lab or ""), str(rec_reason or ""))

    def _update_current_song_label(self) -> None:
        """Update the header 'current song' label with elide-right + tooltip (best-effort)."""
        try:
            lbl = getattr(self, "current_song_lbl", None)
            full = str(getattr(self, "_current_song_full", "") or "")
            if lbl is None:
                return
            if not full:
                try:
                    lbl.setText("")
                    lbl.setToolTip("")
                except Exception:
                    pass
                return
            try:
                w = int(lbl.width() or 0)
            except Exception:
                w = 0
            if w <= 10:
                try:
                    lbl.setText(full)
                    lbl.setToolTip(full)
                except Exception:
                    pass
                return
            try:
                from PySide6.QtGui import QFontMetrics
                el = QFontMetrics(lbl.font()).elidedText(full, Qt.ElideRight, max(10, int(w) - 8))
                lbl.setText(el)
                lbl.setToolTip(full)
            except Exception:
                try:
                    lbl.setText(full)
                    lbl.setToolTip(full)
                except Exception:
                    pass
        except Exception:
            pass

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        try:
            super().resizeEvent(event)
        except Exception:
            pass
        try:
            self._update_current_song_label()
        except Exception:
            pass

    def _current_song_id(self) -> Optional[int]:
        it = self.listw.currentItem()
        if not it:
            return None
        try:
            return int(it.data(Qt.UserRole))
        except Exception:
            return None


    def _auto_advance_enabled(self) -> bool:
        try:
            return bool(self.chk_auto_advance.isChecked())
        except Exception:
            return False

    def _goto_next(self) -> None:
        try:
            r = int(self.listw.currentRow())
        except Exception:
            r = -1
        if r < 0:
            return
        try:
            if r + 1 < int(self.listw.count()):
                self.listw.setCurrentRow(r + 1)
                try:
                    self.listw.setFocus()
                except Exception:
                    pass
        except Exception:
            pass

    def _goto_prev(self) -> None:
        try:
            r = int(self.listw.currentRow())
        except Exception:
            r = -1
        if r < 0:
            return
        try:
            if r - 1 >= 0:
                self.listw.setCurrentRow(r - 1)
                try:
                    self.listw.setFocus()
                except Exception:
                    pass
        except Exception:
            pass

    def _pick_compare_a(self) -> None:
        """Pick compare A as the winner and Apply (speedrun hotkey)."""
        try:
            lab = str(self.cmp_a_combo.currentText() or "").strip()
        except Exception:
            lab = ""
        if not lab:
            return
        try:
            self.winner_combo.setCurrentText(lab)
        except Exception:
            pass
        self._apply_current()

    def _pick_compare_b(self) -> None:
        """Pick compare B as the winner and Apply (speedrun hotkey)."""
        try:
            lab = str(self.cmp_b_combo.currentText() or "").strip()
        except Exception:
            lab = ""
        if not lab:
            return
        try:
            self.winner_combo.setCurrentText(lab)
        except Exception:
            pass
        self._apply_current()

    def _advance_after_action(self, prior_row: int, sid: int) -> None:
        """If auto-advance is enabled, move to the next conflict in the list.

        This is best-effort and intentionally simple: it advances by row index.
        """
        if not self._auto_advance_enabled():
            return

        try:
            # Prefer advancing from the song's current row (if still visible).
            idx = None
            for i in range(int(self.listw.count())):
                it = self.listw.item(i)
                if it is None:
                    continue
                try:
                    if int(it.data(Qt.UserRole)) == int(sid):
                        idx = i
                        break
                except Exception:
                    continue
            if idx is not None:
                target = int(idx) + 1
                if 0 <= target < int(self.listw.count()):
                    self.listw.setCurrentRow(target)
                    try:
                        self.listw.setFocus()
                    except Exception:
                        pass
                    return

            # If the current sid disappeared (e.g., cleared override and item got hidden),
            # choose the row that now occupies the old index.
            if int(self.listw.count()) > 0:
                target = min(int(prior_row), int(self.listw.count()) - 1)
                if 0 <= target < int(self.listw.count()):
                    self.listw.setCurrentRow(target)
                    try:
                        self.listw.setFocus()
                    except Exception:
                        pass
        except Exception:
            pass


    def _recommend_winner(self, song_id: int, labels: List[str], cls: str) -> Tuple[str, str]:
        """Conservative recommendation for which source to keep (only when obvious)."""
        cls = str(cls or "").strip().lower()
        labels = [str(x) for x in (labels or []) if str(x).strip()]
        if not labels:
            return ("", "")

        # If user already set an override, prefer to recommend that.
        try:
            cur = str(self._overrides.get(int(song_id), "") or "").strip()
        except Exception:
            cur = ""
        if cur and cur in labels:
            if cls in {"identical", "effective"}:
                return (cur, "already selected")

        if cls == "identical":
            if "Base" in labels:
                return ("Base", "identical duplicates; keep Base")
            return (labels[0], "identical duplicates")

        if cls != "effective":
            return ("", "")

        # Effective duplicates: recommend only if one is clearly "better" (assets/media).
        def _assets(lab: str) -> Dict[str, object]:
            root = str(self._export_roots_by_label.get(lab, "") or "")
            return self._scan_song_assets(label=lab, export_root_s=root, song_id=int(song_id))

        def _vid_info(lab: str) -> Dict[str, str]:
            root = str(self._export_roots_by_label.get(lab, "") or "")
            return self._read_media_info(label=lab, export_root_s=root, song_id=int(song_id), kind="video")

        def _aud_info(lab: str) -> Dict[str, str]:
            root = str(self._export_roots_by_label.get(lab, "") or "")
            return self._read_media_info(label=lab, export_root_s=root, song_id=int(song_id), kind="audio")

        # 1) Unique presence: one has video/audio, the other doesn't.
        try:
            has_video = {lab: int((_assets(lab).get("_video_size") or 0)) > 0 for lab in labels}
            if sum(1 for v in has_video.values() if v) == 1:
                lab = next(lab_i for lab_i, v in has_video.items() if v)
                return (lab, "only one with video")
        except Exception:
            pass

        try:
            has_audio = {lab: int((_assets(lab).get("_audio_size") or 0)) > 0 for lab in labels}
            if sum(1 for v in has_audio.values() if v) == 1:
                lab = next(lab_i for lab_i, v in has_audio.items() if v)
                return (lab, "only one with audio")
        except Exception:
            pass

        # If comparing exactly two labels, we can do clearer comparisons.
        if len(labels) != 2:
            return ("", "")
        a, b = labels[0], labels[1]

        # 2) Resolution: if both have video, recommend clearly higher resolution.
        try:
            ra = str(_vid_info(a).get("Resolution") or "")
            rb = str(_vid_info(b).get("Resolution") or "")
            def _parse_res(s: str) -> Optional[Tuple[int, int]]:
                m = re.search(r"(\d{2,5})\s*[x×]\s*(\d{2,5})", str(s))
                if not m:
                    return None
                return (int(m.group(1)), int(m.group(2)))
            pa = _parse_res(ra)
            pb = _parse_res(rb)
            if pa and pb:
                area_a = pa[0] * pa[1]
                area_b = pb[0] * pb[1]
                if area_a >= int(area_b * 1.5):
                    return (a, f"higher video resolution ({pa[0]}x{pa[1]} vs {pb[0]}x{pb[1]})")
                if area_b >= int(area_a * 1.5):
                    return (b, f"higher video resolution ({pb[0]}x{pb[1]} vs {pa[0]}x{pa[1]})")
        except Exception:
            pass

        # 3) File size (very conservative): if one video file is much larger, it *may* be higher quality.
        try:
            sa = int((_assets(a).get("_video_size") or 0))
            sb = int((_assets(b).get("_video_size") or 0))
            if sa and sb:
                if sa >= int(sb * 1.8):
                    return (a, "much larger video file")
                if sb >= int(sa * 1.8):
                    return (b, "much larger video file")
        except Exception:
            pass

        # 4) Otherwise: no recommendation.
        return ("", "")

    def _on_sel_changed(self, *_args) -> None:
        sid = self._current_song_id()
        if sid is None:
            return
        occs = self._conflicts.get(int(sid)) or ()
        # Title line
        try:
            title = str(getattr(occs[0], "title", "") or "") if occs else ""
            artist = str(getattr(occs[0], "artist", "") or "") if occs else ""
            self.title_lbl.setText(f"Song {sid}: {title} — {artist}")
            try:
                self._current_song_full = f"Current: Song {sid}: {title} — {artist}"
                self._update_current_song_label()
            except Exception:
                pass

        except Exception:
            pass

        # Status summary (from 'Detect identical duplicates')
        try:
            if not self._identical_detection_ran:
                self.status_lbl.setText("")
            else:
                cls = str(self._dupe_class_by_sid.get(int(sid), "") or "").strip().lower()
                summ = str(self._dupe_summary_by_sid.get(int(sid), "") or "").strip()
                if cls == "identical":
                    self.status_lbl.setText("Status: Identical duplicate (safe to hide)")
                elif cls == "effective":
                    self.status_lbl.setText(f"Status: Effectively identical (same melody) — {summ}" if summ else "Status: Effectively identical (same melody)")
                elif cls == "different":
                    self.status_lbl.setText(f"Status: Different — {summ}" if summ else "Status: Different")
                else:
                    self.status_lbl.setText("")

                # Conservative recommendation (only when obvious)
                try:
                    labels = []
                    for o in occs:
                        lab = str(getattr(o, "source_label", "") or "").strip()
                        if lab:
                            labels.append(lab)
                    rec_lab, rec_reason = self._get_recommendation_cached(int(sid), occs=occs)
                    if rec_lab:
                        base = ""
                        try:
                            base = str(self.status_lbl.text() or "")
                        except Exception:
                            base = ""
                        tail = f"Recommended: {rec_lab}" + (f" — {rec_reason}" if rec_reason else "")
                        self.status_lbl.setText((base + "\n" if base else "") + tail)
                except Exception:
                    pass
        except Exception:
            try:
                self.status_lbl.setText("")
            except Exception:
                pass

        # Table
        self.table.setRowCount(0)
        src_labels: List[str] = []
        for o in occs:
            try:
                lab = str(getattr(o, "source_label", "") or "")
                sha = str(getattr(o, "melody1_sha1", "") or "").strip() or "MISSING"
                fp = str(getattr(o, "melody1_fp", "") or "").strip() or "MISSING"
            except Exception:
                continue
            r = self.table.rowCount()
            self.table.insertRow(r)
            self.table.setItem(r, 0, QTableWidgetItem(lab))
            it_fp = QTableWidgetItem(fp[:12] if (fp and fp != "MISSING") else fp)
            try:
                it_fp.setToolTip(f"Melody fingerprint: {fp}\nRaw SHA1 (advanced): {sha}")
            except Exception:
                pass
            self.table.setItem(r, 1, it_fp)
            src_labels.append(lab)

        # Winner combo
        try:
            self.winner_combo.blockSignals(True)
        except Exception:
            pass
        try:
            self.winner_combo.clear()
            for lab in src_labels:
                self.winner_combo.addItem(str(lab))
            cur = str(self._overrides.get(int(sid), "") or "").strip()
            if cur and (cur in src_labels):
                self.winner_combo.setCurrentText(cur)
            elif src_labels:
                self.winner_combo.setCurrentIndex(0)
        finally:
            try:
                self.winner_combo.blockSignals(False)
            except Exception:
                pass

        # Compare panel (C1): populate source selectors for this conflict.
        try:
            self._set_compare_sources(src_labels)
        except Exception:
            pass


    def _set_compare_sources(self, src_labels: List[str]) -> None:
        """Populate A/B source selectors for the compare panel."""
        try:
            self.cmp_a_combo.blockSignals(True)
            self.cmp_b_combo.blockSignals(True)
        except Exception:
            pass
        try:
            self.cmp_a_combo.clear()
            self.cmp_b_combo.clear()
            for lab in (src_labels or []):
                self.cmp_a_combo.addItem(str(lab))
                self.cmp_b_combo.addItem(str(lab))

            # Default A: override winner if set, else Base if present, else first.
            sid = self._current_song_id()
            preferred_a = ""
            try:
                if sid is not None:
                    preferred_a = str(self._overrides.get(int(sid), "") or "").strip()
            except Exception:
                preferred_a = ""

            a = preferred_a if (preferred_a and preferred_a in src_labels) else ("Base" if "Base" in src_labels else (src_labels[0] if src_labels else ""))
            if a:
                try:
                    self.cmp_a_combo.setCurrentText(str(a))
                except Exception:
                    pass

            # Default B: first non-A (if any)
            b = ""
            for lab in (src_labels or []):
                if str(lab) != str(a):
                    b = str(lab)
                    break
            if not b and src_labels:
                b = str(src_labels[0])
            if b:
                try:
                    self.cmp_b_combo.setCurrentText(str(b))
                except Exception:
                    pass
        finally:
            try:
                self.cmp_a_combo.blockSignals(False)
                self.cmp_b_combo.blockSignals(False)
            except Exception:
                pass

        self._reset_compare_table()
        self._update_compare_info()

    def _on_compare_changed(self, *_args) -> None:
        self._reset_compare_table()
        self._update_compare_info()

    def _compare_selected_labels(self) -> Tuple[str, str]:
        try:
            a = str(self.cmp_a_combo.currentText() or "").strip()
        except Exception:
            a = ""
        try:
            b = str(self.cmp_b_combo.currentText() or "").strip()
        except Exception:
            b = ""
        return a, b

    def _update_compare_info(self) -> None:
        sid = self._current_song_id()
        a, b = self._compare_selected_labels()

        # enable compute only when two different sources are selected
        try:
            self.btn_compute_diff.setEnabled(bool(sid is not None and a and b and a != b))
        except Exception:
            pass

        if sid is None or not a or not b:
            try:
                self.cmp_info_lbl.setText("Select a conflict on the left to compare two sources.")
            except Exception:
                pass
            return

        try:
            title = ""
            artist = ""
            occs = self._conflicts.get(int(sid)) or ()
            if occs:
                title = str(getattr(occs[0], "title", "") or "")
                artist = str(getattr(occs[0], "artist", "") or "")
        except Exception:
            title, artist = "", ""

        a_root = str(self._export_roots_by_label.get(a, "") or "")
        b_root = str(self._export_roots_by_label.get(b, "") or "")
        lines = [f"Song {sid}: {title} — {artist}".strip(), f"A: {a}", f"B: {b}"]
        if a_root:
            lines.append(f"Export A: {a_root}")
        if b_root:
            lines.append(f"Export B: {b_root}")
        try:
            if self._identical_detection_ran and int(sid) in self._identical_by_sid:
                if bool(self._identical_by_sid.get(int(sid), False)):
                    lines.append("Status: Identical duplicate")
                else:
                    summ = str(self._identical_summary_by_sid.get(int(sid), "") or "").strip()
                    if summ:
                        lines.append(f"Status: Differences: {summ}")
                    else:
                        lines.append("Status: Different")
        except Exception:
            pass
        try:
            self.cmp_info_lbl.setText("\n".join(lines))
        except Exception:
            pass

    def _reset_compare_table(self) -> None:
        try:
            self.cmp_table.setRowCount(0)
        except Exception:
            return
        # lightweight placeholder
        try:
            self._cmp_add_row("(not computed)", "Click 'Compute differences'", "")
        except Exception:
            pass

    def _cmp_add_row(self, field: str, a_val: str, b_val: str) -> None:
        r = int(self.cmp_table.rowCount())
        self.cmp_table.insertRow(r)
        it0 = QTableWidgetItem(str(field))
        it1 = QTableWidgetItem(str(a_val))
        it2 = QTableWidgetItem(str(b_val))
        # Group headers: field starts with an em dash marker.
        try:
            if str(field).strip().startswith("—"):
                f = it0.font()
                f.setBold(True)
                it0.setFont(f)
                it1.setFont(f)
                it2.setFont(f)
        except Exception:
            pass
        self.cmp_table.setItem(r, 0, it0)
        self.cmp_table.setItem(r, 1, it1)
        self.cmp_table.setItem(r, 2, it2)

    def _render_cmp_rows(self, rows: List[Tuple[str, str, str]]) -> None:
        """Render cached compare rows into the table."""
        try:
            self.cmp_table.setRowCount(0)
        except Exception:
            return
        for field, a_val, b_val in (rows or []):
            try:
                self._cmp_add_row(str(field), str(a_val), str(b_val))
            except Exception:
                continue

    @staticmethod
    def _fmt_bytes(n: int) -> str:
        try:
            n = int(n)
        except Exception:
            return str(n)
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if n < 1024 or unit == "TB":
                return f"{n:.1f} {unit}" if unit != "B" else f"{n} {unit}"
            n = n / 1024.0
        return f"{n:.1f} TB"

    @staticmethod
    def _strip_ns(tag: str) -> str:
        if "}" in tag:
            return tag.split("}", 1)[1]
        return tag

    @staticmethod
    def _norm_root_str(export_root_s: str) -> str:
        s = str(export_root_s or "").strip()
        if not s:
            return ""
        p = Path(s).expanduser()
        try:
            p = p.resolve()
        except Exception:
            pass
        return str(p)

    @staticmethod
    def _file_sig(p: Optional[Path]) -> Tuple[str, int, int]:
        """Return a cheap signature (path, mtime_ns, size) for invalidation."""
        if not p:
            return ("", 0, 0)
        try:
            st = p.stat()
            return (str(p), int(getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9))), int(st.st_size))
        except Exception:
            return (str(p), 0, 0)

    def _glob_sig(self, export_root_s: str, patterns: List[str]) -> Tuple[Tuple[str, int, int], ...]:
        root_s = self._norm_root_str(export_root_s)
        if not root_s:
            return tuple()
        root = Path(root_s)
        seen = set()
        for pat in (patterns or []):
            try:
                for f in root.glob(str(pat)):
                    try:
                        if not f.is_file():
                            continue
                    except Exception:
                        continue
                    sig = self._file_sig(f)
                    # store just name+mtime+size to keep it stable across machines
                    seen.add((Path(sig[0]).name, sig[1], sig[2]))
            except Exception:
                continue
        return tuple(sorted(seen))

    @staticmethod
    def _parse_int_text(s: str) -> Optional[int]:
        try:
            s = str(s or "").strip()
            if not s:
                return None
            if s.isdigit():
                return int(s)
            # allow +digits
            if s.startswith("+") and s[1:].isdigit():
                return int(s[1:])
        except Exception:
            return None
        return None

    @staticmethod
    def _parse_time_to_ms(s: str) -> Optional[int]:
        s = str(s or "").strip()
        if not s:
            return None
        # mm:ss or hh:mm:ss
        if ":" in s:
            parts = [p.strip() for p in s.split(":")]
            try:
                parts_i = [int(p) for p in parts]
            except Exception:
                return None
            if len(parts_i) == 2:
                mm, ss = parts_i
                return (mm * 60 + ss) * 1000
            if len(parts_i) == 3:
                hh, mm, ss = parts_i
                return (hh * 3600 + mm * 60 + ss) * 1000
            return None
        # plain int
        n = ConflictResolverDialog._parse_int_text(s)
        if n is None:
            return None
        # heuristic: small numbers are seconds, larger are ms
        if n < 10_000:
            return n * 1000
        return n

    @staticmethod
    def _fmt_ms(ms: Optional[int]) -> str:
        if ms is None:
            return ""
        try:
            ms = int(ms)
        except Exception:
            return str(ms)
        sec = ms // 1000
        m = sec // 60
        s = sec % 60
        return f"{m}:{s:02d} ({ms} ms)"

    @staticmethod
    def _find_text_by_tag(el: ET.Element, tags: List[str]) -> str:
        try:
            for t in tags:
                for ch in el.iter():
                    if ConflictResolverDialog._strip_ns(str(ch.tag)) == t:
                        v = (ch.text or "").strip()
                        if v:
                            return v
        except Exception:
            pass
        return ""


    @staticmethod
    def _find_text_by_tag_ci(el: ET.Element, tags: List[str]) -> str:
        try:
            want = {str(t or "").strip().upper() for t in (tags or []) if str(t or "").strip()}
            if not want:
                return ""
            for ch in el.iter():
                if ConflictResolverDialog._strip_ns(str(ch.tag)).upper() in want:
                    v = (ch.text or "").strip()
                    if v:
                        return v
        except Exception:
            pass
        return ""

    @staticmethod
    def _find_attr_ci(el: ET.Element, keys: List[str]) -> str:
        try:
            want = {str(k or "").strip().upper() for k in (keys or []) if str(k or "").strip()}
            if not want:
                return ""
            for ak, av in (el.attrib or {}).items():
                if str(ak or "").strip().upper() in want:
                    v = str(av or "").strip()
                    if v:
                        return v
        except Exception:
            pass
        return ""

    @staticmethod
    def _find_value_ci(el: ET.Element, keys: List[str]) -> str:
        # Prefer attribute forms first, then child tags.
        v = ConflictResolverDialog._find_attr_ci(el, keys)
        if v:
            return v
        return ConflictResolverDialog._find_text_by_tag_ci(el, keys)
    @staticmethod
    def _song_id_from_el(el: ET.Element) -> Optional[int]:
        # Attribute forms (case-insensitive)
        try:
            want = {"ID", "SONG_ID", "SONGID"}
            for ak, av in (el.attrib or {}).items():
                if str(ak or "").strip().upper() in want:
                    v = str(av or "").strip()
                    if v.isdigit():
                        return int(v)
        except Exception:
            pass

        # Child tag forms (case-insensitive)
        try:
            want = {"ID", "SONG_ID", "SONGID"}
            for ch in el.iter():
                if ConflictResolverDialog._strip_ns(str(ch.tag)).upper() in want:
                    v = (ch.text or "").strip()
                    if v.isdigit():
                        return int(v)
                    break
        except Exception:
            pass
        return None

    def _acts_map_from_export(self, export_root: Path) -> Dict[int, str]:
        """Map ACT id -> name for a given export root (cached + invalidated by acts_*.xml stats)."""
        export_root_s = self._norm_root_str(str(export_root))
        if not export_root_s:
            return {}

        sig = self._glob_sig(export_root_s, ["acts_*.xml"])
        try:
            cached = self._cmp_acts_cache.get(export_root_s)
            if cached and cached.get("_sig") == sig and isinstance(cached.get("_map"), dict):
                return dict(cached.get("_map") or {})
        except Exception:
            pass

        root = Path(export_root_s)
        candidates: List[Path] = []
        try:
            candidates.extend(sorted(root.glob("acts_*_0.xml"), key=lambda p: p.name.lower()))
            candidates.extend(sorted(root.glob("acts_*.xml"), key=lambda p: p.name.lower()))
        except Exception:
            candidates = []

        best_map: Dict[int, str] = {}
        best_count = -1
        for p in candidates:
            tmp: Dict[int, str] = {}
            try:
                for _ev, el in ET.iterparse(str(p), events=("end",)):
                    if ConflictResolverDialog._strip_ns(str(el.tag)) != "ACT":
                        continue
                    aid = ConflictResolverDialog._song_id_from_el(el)
                    if aid is None:
                        el.clear()
                        continue
                    name = ConflictResolverDialog._find_text_by_tag(el, ["NAME", "NAME_KEY"])
                    if name:
                        tmp[int(aid)] = str(name)
                    el.clear()
            except Exception:
                continue
            if len(tmp) > best_count:
                best_map = tmp
                best_count = len(tmp)

        out = dict(best_map)
        try:
            self._cmp_acts_cache[export_root_s] = {"_sig": sig, "_map": dict(out)}
        except Exception:
            pass
        return out

    def _read_song_meta(self, *, label: str, export_root_s: str, song_id: int) -> Dict[str, str]:
        root_s = self._norm_root_str(export_root_s)
        key = (root_s, str(label), int(song_id))

        sig_songs = self._glob_sig(root_s, ["songs_*.xml"]) if root_s else tuple()
        sig_acts = self._glob_sig(root_s, ["acts_*.xml"]) if root_s else tuple()

        try:
            cached = self._cmp_meta_cache.get(key)
            if cached and isinstance(cached, dict):
                if cached.get("_sig_songs") == sig_songs and cached.get("_sig_acts") == sig_acts:
                    d = {str(k): str(v) for k, v in cached.items() if not str(k).startswith("_")}
                    if d:
                        return d
        except Exception:
            pass

        if not root_s:
            meta = {"Title": "(unknown)", "Artist": "(unknown)"}
            try:
                self._cmp_meta_cache[key] = dict(meta)
            except Exception:
                pass
            return meta

        export_root = Path(root_s)

        # Start with what we already know from the conflict list (fast + reliable).
        title = ""
        artist = ""
        try:
            occs = self._conflicts.get(int(song_id)) or ()
            for o in occs:
                if str(getattr(o, "source_label", "") or "").strip() == str(label):
                    title = str(getattr(o, "title", "") or "").strip()
                    artist = str(getattr(o, "artist", "") or "").strip()
                    break
        except Exception:
            pass

        duration = ""
        preview = ""
        year = ""
        language = ""
        genre = ""

        acts_map = self._acts_map_from_export(export_root)

        # Scan songs xml files until we find this song_id. Some discs don't use the *_0 naming.
        candidates: List[Path] = []
        try:
            pref = list(sorted(export_root.glob("songs_*_0.xml"), key=lambda p: p.name.lower()))
            any_ = list(sorted(export_root.glob("songs_*.xml"), key=lambda p: p.name.lower()))
            seen = set()
            for p in (pref + any_):
                ps = str(p)
                if ps in seen:
                    continue
                seen.add(ps)
                candidates.append(p)
        except Exception:
            candidates = []

        # Key sets (case-insensitive) for attribute/tag lookup.
        title_keys = ["TITLE", "SONG_NAME", "NAME", "TITLE_KEY", "SONG_NAME_KEY", "NAME_KEY"]
        artist_keys = ["PERFORMANCE_NAME", "PERFORMANCE_NAME_KEY", "ARTIST", "ARTIST_NAME", "ARTIST_KEY", "ARTIST_NAME_KEY"]
        dur_keys = ["LENGTH", "LENGTH_MS", "SONG_LENGTH", "DURATION", "DURATION_MS", "DUR", "DUR_MS"]
        pstart_keys = ["PREVIEW_START", "PREVIEW_START_MS", "PREVIEW_IN", "PREVIEW_IN_MS"]
        pend_keys = ["PREVIEW_END", "PREVIEW_END_MS", "PREVIEW_OUT", "PREVIEW_OUT_MS"]
        year_keys = ["YEAR", "RELEASE_YEAR"]
        lang_keys = ["LANGUAGE", "LANG"]
        genre_keys = ["GENRE", "STYLE"]

        for p in candidates:
            try:
                for _ev, el in ET.iterparse(str(p), events=("end",)):
                    if ConflictResolverDialog._strip_ns(str(el.tag)).upper() != "SONG":
                        continue
                    sid0 = ConflictResolverDialog._song_id_from_el(el)
                    if sid0 is None or int(sid0) != int(song_id):
                        el.clear()
                        continue

                    if not title:
                        title = ConflictResolverDialog._find_value_ci(el, title_keys)
                    if not artist:
                        # artist: PERFORMANCE_NAME preferred; fall back to ACT mapping via PERFORMED_BY
                        artist = ConflictResolverDialog._find_value_ci(el, artist_keys)
                        if not artist:
                            try:
                                for ch in el.iter():
                                    if ConflictResolverDialog._strip_ns(str(ch.tag)).upper() == "PERFORMED_BY":
                                        aid = ConflictResolverDialog._song_id_from_el(ch)
                                        if aid is not None and int(aid) in acts_map:
                                            artist = str(acts_map[int(aid)])
                                        break
                            except Exception:
                                pass

                    # Duration / preview
                    dur_raw = ConflictResolverDialog._find_value_ci(el, dur_keys)
                    if dur_raw and not duration:
                        ms = ConflictResolverDialog._parse_time_to_ms(dur_raw)
                        duration = ConflictResolverDialog._fmt_ms(ms) if ms is not None else str(dur_raw)

                    pstart_raw = ConflictResolverDialog._find_value_ci(el, pstart_keys)
                    pend_raw = ConflictResolverDialog._find_value_ci(el, pend_keys)
                    if (pstart_raw or pend_raw) and not preview:
                        ms_s = ConflictResolverDialog._parse_time_to_ms(pstart_raw) if pstart_raw else None
                        ms_e = ConflictResolverDialog._parse_time_to_ms(pend_raw) if pend_raw else None
                        if ms_s is not None and ms_e is not None:
                            preview = f"{ConflictResolverDialog._fmt_ms(ms_s)} → {ConflictResolverDialog._fmt_ms(ms_e)}"
                        elif ms_s is not None:
                            preview = ConflictResolverDialog._fmt_ms(ms_s)
                        elif ms_e is not None:
                            preview = ConflictResolverDialog._fmt_ms(ms_e)
                        else:
                            preview = str(pstart_raw or pend_raw)

                    if not year:
                        year = str(ConflictResolverDialog._find_value_ci(el, year_keys) or "")
                    if not language:
                        language = str(ConflictResolverDialog._find_value_ci(el, lang_keys) or "")
                    if not genre:
                        genre = str(ConflictResolverDialog._find_value_ci(el, genre_keys) or "")

                    el.clear()
                    raise StopIteration()
            except StopIteration:
                break
            except Exception:
                continue

        meta: Dict[str, str] = {
            "Title": title or "(unknown)",
            "Artist": artist or "(unknown)",
        }
        if duration:
            meta["Duration"] = str(duration)
        if preview:
            meta["Preview"] = str(preview)
        if year:
            meta["Year"] = str(year).strip()
        if language:
            meta["Language"] = str(language).strip()
        if genre:
            meta["Genre"] = str(genre).strip()

        try:
            c = dict(meta)
            c["_sig_songs"] = sig_songs  # type: ignore[assignment]
            c["_sig_acts"] = sig_acts  # type: ignore[assignment]
            self._cmp_meta_cache[key] = c
        except Exception:
            pass
        return meta

    def _find_song_dir(self, export_root: Path, song_id: int) -> Optional[Path]:
        # Common: Export/<song_id>
        candidates = [export_root / str(song_id), export_root / f"{song_id:04d}", export_root / f"{song_id:05d}"]
        for p in candidates:
            try:
                if p.exists() and p.is_dir():
                    return p
            except Exception:
                continue
        # fallback: scan immediate children numeric dirs
        try:
            for ch in export_root.iterdir():
                if ch.is_dir() and ch.name.isdigit() and int(ch.name) == int(song_id):
                    return ch
        except Exception:
            pass
        return None

    def _find_melody1_path(self, export_root_s: str, song_id: int) -> Optional[Path]:
        """Return path to melody_1.xml if present for song_id within export_root_s."""
        root_s = self._norm_root_str(export_root_s)
        if not root_s:
            return None
        export_root = Path(root_s)
        song_dir = self._find_song_dir(export_root, int(song_id))
        if not song_dir:
            return None
        try:
            for nm in ["melody_1.xml", "MELODY_1.XML"]:
                p = song_dir / nm
                if p.exists() and p.is_file():
                    return p
        except Exception:
            return None
        return None



    def _scan_song_assets(self, *, label: str, export_root_s: str, song_id: int) -> Dict[str, object]:
        root_s = self._norm_root_str(export_root_s)
        key = (root_s, str(label), int(song_id))

        if not root_s:
            d = {
                "Song folder": "(unknown)",
                "melody_1.xml": "(unknown)",
                "Audio": "(unknown)",
                "Video": "(unknown)",
                "Files": "(unknown)",
                "_total_files": None,
                "_total_bytes": None,
                "_audio_size": None,
                "_video_size": None,
                "_melody1_present": None,
                "_audio_path": "",
                "_video_path": "",
            }
            try:
                self._cmp_assets_cache[key] = dict(d)
            except Exception:
                pass
            return d

        # Fast cache validation: directory mtime + cached melody/audio/video stat.
        try:
            cached = self._cmp_assets_cache.get(key)
            if cached and isinstance(cached, dict) and "_sig_dir_mtime_ns" in cached:
                song_dir_s = str(cached.get("Song folder") or "")
                song_dir = Path(song_dir_s) if song_dir_s and song_dir_s not in {"MISSING", "(unknown)"} else None
                if song_dir:
                    try:
                        dir_mtime = int(song_dir.stat().st_mtime_ns)
                    except Exception:
                        dir_mtime = -1

                    if dir_mtime == int(cached.get("_sig_dir_mtime_ns") or -2):
                        # validate important files we previously selected
                        mel_sig = tuple(cached.get("_sig_melody") or ())
                        aud_sig = tuple(cached.get("_sig_audio") or ())
                        vid_sig = tuple(cached.get("_sig_video") or ())
                        cur_mel = self._file_sig(Path(str(mel_sig[0]))) if (mel_sig and mel_sig[0]) else self._file_sig(None)
                        cur_aud = self._file_sig(Path(str(aud_sig[0]))) if (aud_sig and aud_sig[0]) else self._file_sig(None)
                        cur_vid = self._file_sig(Path(str(vid_sig[0]))) if (vid_sig and vid_sig[0]) else self._file_sig(None)
                        mel_ok = tuple(mel_sig or ("", 0, 0)) == cur_mel
                        aud_ok = tuple(aud_sig or ("", 0, 0)) == cur_aud
                        vid_ok = tuple(vid_sig or ("", 0, 0)) == cur_vid
                        if mel_ok and aud_ok and vid_ok:
                            return dict(cached)
        except Exception:
            pass

        export_root = Path(root_s)

        song_dir = self._find_song_dir(export_root, int(song_id))
        if not song_dir:
            d = {
                "Song folder": "MISSING",
                "melody_1.xml": "MISSING",
                "Audio": "MISSING",
                "Video": "MISSING",
                "Files": "0 (0 B)",
                "_total_files": 0,
                "_total_bytes": 0,
                "_audio_size": 0,
                "_video_size": 0,
                "_melody1_present": False,
                "_audio_path": "",
                "_video_path": "",
                "_sig_dir_mtime_ns": 0,
                "_sig_melody": ("", 0, 0),
                "_sig_audio": ("", 0, 0),
                "_sig_video": ("", 0, 0),
            }
            try:
                self._cmp_assets_cache[key] = dict(d)
            except Exception:
                pass
            return d

        # detect presence
        melody_path = None
        try:
            for nm in ["melody_1.xml", "MELODY_1.XML"]:
                p = song_dir / nm
                if p.exists():
                    melody_path = p
                    break
        except Exception:
            melody_path = None

        audio_exts = {".mp3", ".wav", ".ogg", ".at3", ".aac", ".m4a", ".ac3", ".flac", ".wma", ".aif", ".aiff", ".vag"}
        video_exts = {".mp4", ".m2v", ".mpg", ".mpeg", ".avi", ".mov", ".mkv", ".wmv", ".h264", ".264", ".vob"}

        total_files = 0
        total_bytes = 0
        best_audio = ("", 0)
        best_audio_path = ""
        best_video_path = ""
        best_video = ("", 0)

        try:
            for root, _dirs, files in os.walk(str(song_dir)):
                for fn in files:
                    p = Path(root) / fn
                    try:
                        st = p.stat()
                        size = int(st.st_size)
                    except Exception:
                        size = 0
                    total_files += 1
                    total_bytes += size
                    ext = p.suffix.lower()
                    if ext in audio_exts or ("audio" in p.name.lower() and size > 0):
                        if size > best_audio[1]:
                            best_audio = (p.name, size)
                            best_audio_path = str(p)
                    if ext in video_exts or ("video" in p.name.lower() and size > 0):
                        if size > best_video[1]:
                            best_video = (p.name, size)
                            best_video_path = str(p)
        except Exception:
            pass

        audio_s = "MISSING"
        if best_audio[0]:
            audio_s = f"{best_audio[0]} ({self._fmt_bytes(best_audio[1])})"
        video_s = "MISSING"
        if best_video[0]:
            video_s = f"{best_video[0]} ({self._fmt_bytes(best_video[1])})"

        try:
            dir_mtime = int(song_dir.stat().st_mtime_ns)
        except Exception:
            dir_mtime = 0

        mel_sig = self._file_sig(melody_path)
        aud_sig = self._file_sig(Path(best_audio_path) if best_audio_path else None)
        vid_sig = self._file_sig(Path(best_video_path) if best_video_path else None)

        d = {
            "Song folder": str(song_dir),
            "melody_1.xml": "OK" if melody_path else "MISSING",
            "Audio": audio_s,
            "Video": video_s,
            "Files": f"{total_files} ({self._fmt_bytes(total_bytes)})",
            "_audio_path": best_audio_path,
            "_video_path": best_video_path,
            "_total_files": int(total_files),
            "_total_bytes": int(total_bytes),
            "_audio_size": int(best_audio[1] or 0),
            "_video_size": int(best_video[1] or 0),
            "_melody1_present": bool(melody_path),
            "_sig_dir_mtime_ns": int(dir_mtime),
            "_sig_melody": mel_sig,
            "_sig_audio": aud_sig,
            "_sig_video": vid_sig,
        }
        try:
            self._cmp_assets_cache[key] = dict(d)
        except Exception:
            pass
        return d

    def _fmt_kbps(bit_s: Optional[str]) -> str:
        try:
            if bit_s is None:
                return ""
            n = int(float(str(bit_s).strip()))
            if n <= 0:
                return ""
            return f"{n/1000.0:.0f} kbps"
        except Exception:
            return ""

    @staticmethod
    def _fmt_fps(rate_s: Optional[str]) -> str:
        s = str(rate_s or "").strip()
        if not s:
            return ""
        try:
            if "/" in s:
                num_s, den_s = s.split("/", 1)
                num = float(num_s)
                den = float(den_s)
                if den == 0:
                    return ""
                fps = num / den
            else:
                fps = float(s)
            if fps <= 0:
                return ""
            return f"{fps:.2f}"
        except Exception:
            return ""

    def _ffprobe_path(self) -> str:
        try:
            return str(shutil.which("ffprobe") or "")
        except Exception:
            return ""

    def _probe_media_ffprobe(self, media_path: str, kind: str) -> Dict[str, str]:
        out: Dict[str, str] = {}
        ffprobe = self._ffprobe_path()
        if not ffprobe:
            return {"Status": "ffprobe not found"}

        media_path = str(media_path or "").strip()
        if not media_path:
            return {"Status": "MISSING"}

        p = Path(media_path)
        try:
            if not p.exists():
                return {"Status": "MISSING"}
        except Exception:
            pass

        cmd = [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration,bit_rate:stream=codec_type,codec_name,width,height,r_frame_rate,avg_frame_rate,sample_rate,channels,bit_rate,duration",
            "-of",
            "json",
            str(p),
        ]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=2.0)
        except Exception as e:
            return {"Status": f"ERROR: {e}"}

        if getattr(r, "returncode", 1) != 0:
            err = (r.stderr or "").strip()
            if err:
                err = err.splitlines()[-1].strip()
            return {"Status": f"ERROR: {err or 'ffprobe failed'}"}

        try:
            j = json.loads(r.stdout or "{}")
        except Exception as e:
            return {"Status": f"ERROR: bad json ({e})"}

        streams = []
        fmt = {}
        try:
            streams = list(j.get("streams") or [])
            fmt = dict(j.get("format") or {})
        except Exception:
            streams = []
            fmt = {}

        st = None
        try:
            for s in streams:
                if str(s.get("codec_type") or "").strip() == str(kind):
                    st = s
                    break
        except Exception:
            st = None

        if not st:
            return {"Status": f"no {kind} stream"}

        # Common fields
        try:
            out["Codec"] = str(st.get("codec_name") or "")
        except Exception:
            out["Codec"] = ""

        # Duration
        dur_s = ""
        try:
            dur_s = str(st.get("duration") or "") or str(fmt.get("duration") or "")
        except Exception:
            dur_s = ""
        try:
            dur_f = float(str(dur_s).strip()) if str(dur_s).strip() else 0.0
        except Exception:
            dur_f = 0.0
        if dur_f > 0:
            out["Duration"] = self._fmt_ms(int(round(dur_f * 1000.0)))

        # Bitrate
        br = ""
        try:
            br = str(st.get("bit_rate") or "") or str(fmt.get("bit_rate") or "")
        except Exception:
            br = ""
        kbps = self._fmt_kbps(br if br else None)
        if kbps:
            out["Bitrate"] = kbps

        if kind == "video":
            try:
                w = st.get("width")
                h = st.get("height")
                if w and h:
                    out["Resolution"] = f"{int(w)}×{int(h)}"
            except Exception:
                pass
            # FPS
            fps = self._fmt_fps(st.get("avg_frame_rate") or st.get("r_frame_rate"))
            if fps:
                out["FPS"] = fps
        elif kind == "audio":
            try:
                sr = str(st.get("sample_rate") or "").strip()
                if sr.isdigit():
                    out["Sample rate"] = f"{int(sr)} Hz"
            except Exception:
                pass
            try:
                ch = st.get("channels")
                if ch:
                    out["Channels"] = str(int(ch))
            except Exception:
                pass

        if not out:
            out["Status"] = "unknown"
        return out

    def _read_media_info(self, *, label: str, export_root_s: str, song_id: int, kind: str) -> Dict[str, str]:
        kind = str(kind or "").strip().lower()
        if kind not in {"audio", "video"}:
            return {"Status": "unknown"}

        root_s = self._norm_root_str(export_root_s)
        key = (root_s, str(label), int(song_id), kind)

        media_path = ""
        try:
            assets = self._scan_song_assets(label=label, export_root_s=export_root_s, song_id=int(song_id))
            if kind == "video":
                media_path = str(assets.get("_video_path") or "").strip()
            else:
                media_path = str(assets.get("_audio_path") or "").strip()
        except Exception:
            media_path = ""

        sig = self._file_sig(Path(media_path) if media_path else None)

        try:
            cached = self._cmp_media_cache.get(key)
            if cached and isinstance(cached, dict):
                if cached.get("_sig") == sig and str(cached.get("_path") or "") == str(media_path):
                    return dict(cached)
        except Exception:
            pass

        if not media_path:
            out: Dict[str, str] = {"Status": "MISSING"}
        else:
            out = dict(self._probe_media_ffprobe(media_path, kind) or {})
            if "Status" not in out:
                out["Status"] = "OK"

        try:
            c = dict(out)
            c["_sig"] = sig  # type: ignore[assignment]
            c["_path"] = str(media_path)  # type: ignore[assignment]
            self._cmp_media_cache[key] = c
        except Exception:
            pass
        return out

    def _read_melody_stats(self, *, label: str, export_root_s: str, song_id: int) -> Dict[str, str]:
        root_s = self._norm_root_str(export_root_s)
        key = (root_s, str(label), int(song_id))
        p = self._find_melody1_path(export_root_s, int(song_id))
        sig = self._file_sig(p if p else None)
        try:
            cached = self._cmp_melody_cache.get(key)
            if cached and isinstance(cached, dict) and cached.get("_sig") == sig:
                return dict(cached)
        except Exception:
            pass

        if not p:
            d = {
                "Notes": "MISSING",
                "Pitch range": "",
                "Avg pitch": "",
                "Span": "",
                "Density": "",
                "Longest note": "",
                "Coverage": "",
                "_notes": 0,
                "_pitch_min": None,
                "_pitch_max": None,
                "_avg_pitch": None,
                "_span_ms": None,
                "_density": None,
                "_longest_ms": None,
                "_coverage_pct": None,
            }
            d["_sig"] = sig
            try:
                self._cmp_melody_cache[key] = dict(d)
            except Exception:
                pass
            return d

        notes = 0
        pitch_min = None
        pitch_max = None
        pitch_sum = 0.0
        longest = 0
        t_min = None
        t_max_end = None
        intervals: List[Tuple[int, int]] = []

        parse_err = ""
        try:
            # Streaming parse to keep memory low.
            for _ev, el in ET.iterparse(str(p), events=("end",)):
                tag_u = ConflictResolverDialog._strip_ns(str(el.tag)).upper()
                # Candidate note elements: NOTE-ish or anything with time/pitch fields.
                if tag_u in {"NOTE", "NOTES", "NOT"} or el.attrib:
                    tpl = self._extract_note_fields(el)
                    if tpl is None:
                        el.clear()
                        continue
                    start_ms, dur_ms, pitch_i = tpl
                    end_ms = start_ms + dur_ms
                    notes += 1
                    if pitch_min is None or pitch_i < pitch_min:
                        pitch_min = pitch_i
                    if pitch_max is None or pitch_i > pitch_max:
                        pitch_max = pitch_i
                    pitch_sum += float(pitch_i)
                    if dur_ms > longest:
                        longest = dur_ms
                    if t_min is None or start_ms < t_min:
                        t_min = start_ms
                    if t_max_end is None or end_ms > t_max_end:
                        t_max_end = end_ms
                    if dur_ms > 0:
                        intervals.append((start_ms, end_ms))
                el.clear()
        except Exception as e:
            parse_err = str(e)

        if notes <= 0 or pitch_min is None or pitch_max is None or t_min is None or t_max_end is None:
            d = {
                "Notes": str(notes) if notes else "0",
                "Pitch range": "",
                "Avg pitch": "",
                "Span": "",
                "Density": "",
                "Longest note": "",
                "Coverage": "",
                "_notes": int(notes or 0),
                "_pitch_min": pitch_min,
                "_pitch_max": pitch_max,
                "_avg_pitch": None,
                "_span_ms": None,
                "_density": None,
                "_longest_ms": int(longest or 0),
                "_coverage_pct": None,
            }
            if parse_err:
                d["Parse"] = f"ERROR: {parse_err}"
            else:
                d["Parse"] = "No notes found"
            d["_sig"] = sig
            try:
                self._cmp_melody_cache[key] = dict(d)
            except Exception:
                pass
            return d

        span = max(0, int(t_max_end - t_min))
        avg_pitch = pitch_sum / float(notes) if notes else 0.0
        density = (float(notes) / (span / 1000.0)) if span > 0 else 0.0

        coverage_pct = ""
        try:
            if intervals and span > 0:
                intervals.sort()
                covered = 0
                cur_s, cur_e = intervals[0]
                for s, e in intervals[1:]:
                    if s <= cur_e:
                        cur_e = max(cur_e, e)
                    else:
                        covered += max(0, cur_e - cur_s)
                        cur_s, cur_e = s, e
                covered += max(0, cur_e - cur_s)
                coverage_pct = f"{(covered / span * 100.0):.1f}%"
        except Exception:
            coverage_pct = ""

        d = {
            "Notes": str(notes),
            "Pitch range": f"{pitch_min}–{pitch_max}",
            "Avg pitch": f"{avg_pitch:.1f}",
            "Span": self._fmt_ms(span),
            "Density": f"{density:.2f} notes/s" if span > 0 else "",
            "Longest note": self._fmt_ms(longest) if longest else "",
            "Coverage": coverage_pct,
            "_notes": int(notes),
            "_pitch_min": int(pitch_min),
            "_pitch_max": int(pitch_max),
            "_avg_pitch": float(avg_pitch),
            "_span_ms": int(span),
            "_density": float(density),
            "_longest_ms": int(longest),
            "_coverage_pct": None,
        }
        if parse_err:
            d["Parse"] = f"ERROR: {parse_err}"

        d["_sig"] = sig
        try:
            self._cmp_melody_cache[key] = dict(d)
        except Exception:
            pass
        return d


    def _detect_identical_all(self) -> None:
        """Classify SHA-mismatch duplicates as identical / effectively identical / different."""
        try:
            from PySide6.QtWidgets import QProgressDialog, QMessageBox, QApplication
        except Exception:
            return

        total = len(self._ids or [])
        if total <= 0:
            return

        cur_sid = None
        try:
            cur_sid = self._current_song_id()
        except Exception:
            cur_sid = None

        dlg = QProgressDialog("Classifying duplicates…", "Cancel", 0, total, self)
        try:
            dlg.setWindowTitle("Detect identical duplicates")
            dlg.setMinimumDuration(0)
            dlg.setValue(0)
        except Exception:
            pass

        checked = 0
        identical = 0
        effective = 0
        different = 0

        for i, sid in enumerate(list(self._ids or []), start=1):
            try:
                dlg.setValue(i - 1)
            except Exception:
                pass
            try:
                QApplication.processEvents()
            except Exception:
                pass
            try:
                if dlg.wasCanceled():
                    break
            except Exception:
                pass

            cls, summ = self._classify_conflict(int(sid))
            cls = str(cls or "").strip().lower()
            try:
                self._dupe_class_by_sid[int(sid)] = str(cls)
                if summ:
                    self._dupe_summary_by_sid[int(sid)] = str(summ)
                else:
                    self._dupe_summary_by_sid.pop(int(sid), None)
            except Exception:
                pass
            # Back-compat: maintain the old bool map for callers that still read it.
            try:
                self._identical_by_sid[int(sid)] = (cls == "identical")
            except Exception:
                pass

            checked += 1
            if cls == "identical":
                identical += 1
            elif cls == "effective":
                effective += 1
            else:
                different += 1

        try:
            dlg.setValue(total)
        except Exception:
            pass

        self._identical_detection_ran = True
        try:
            # Classification changed; clear recommendation cache.
            self._rec_cache_by_sid.clear()
        except Exception:
            pass
        try:
            self.btn_auto_resolve_identical.setEnabled(True)
        except Exception:
            pass
        try:
            self.btn_auto_pick_quality.setEnabled(True)
        except Exception:
            pass
        try:
            self.chk_recommended_only.setEnabled(True)
        except Exception:
            pass
        try:
            self.btn_apply_recommended.setEnabled(True)
        except Exception:
            pass

        self._rebuild_list(preserve_sid=cur_sid)

        msg = (
            f"Checked {checked} item(s).\n"
            f"Identical duplicates (hidden by default): {identical}.\n"
            f"Effectively identical (same melody): {effective}.\n"
            f"Different: {different}."
        )
        try:
            if checked < total:
                msg += f"\n\nStopped early ({checked}/{total})."
        except Exception:
            pass
        try:
            QMessageBox.information(self, "Duplicate classification", msg)
        except Exception:
            pass



    @staticmethod
    def _is_base_label(label: str) -> bool:
        try:
            return str(label or "").strip().lower().startswith("base")
        except Exception:
            return False

    def _auto_pick_winner_label(self, song_id: int) -> str:
        """Pick a deterministic winner label for auto-resolve.

        Rule:
          - Prefer Base (any label starting with 'Base')
          - Otherwise use the first source label in occurrence order
        """
        occs = self._conflicts.get(int(song_id)) or ()
        labels: List[str] = []
        try:
            for o in occs:
                lab = str(getattr(o, "source_label", "") or "").strip()
                if lab and lab not in labels:
                    labels.append(lab)
        except Exception:
            labels = []

        if not labels:
            return ""

        try:
            for lab in labels:
                if self._is_base_label(lab):
                    return str(lab)
        except Exception:
            pass

        return str(labels[0])

    def _auto_resolve_identical_all(self) -> None:
        """Auto-apply winner overrides for items classified as 'identical'."""
        try:
            from PySide6.QtWidgets import QMessageBox
        except Exception:
            return

        if not bool(getattr(self, "_identical_detection_ran", False)):
            try:
                QMessageBox.information(self, "Auto-resolve identical", "Run 'Detect identical duplicates' first.")
            except Exception:
                pass
            return

        applied = 0
        skipped_overridden = 0
        skipped_not_identical = 0
        skipped_no_winner = 0

        cur_sid = None
        try:
            cur_sid = self._current_song_id()
        except Exception:
            cur_sid = None

        for sid in list(self._ids or []):
            cls = ""
            try:
                cls = str(self._dupe_class_by_sid.get(int(sid), "") or "").strip().lower()
            except Exception:
                cls = ""

            if cls != "identical":
                skipped_not_identical += 1
                continue

            try:
                if str(self._overrides.get(int(sid), "") or "").strip():
                    skipped_overridden += 1
                    continue
            except Exception:
                pass

            winner = ""
            try:
                winner = str(self._auto_pick_winner_label(int(sid)) or "").strip()
            except Exception:
                winner = ""

            if not winner:
                skipped_no_winner += 1
                continue

            self._overrides[int(sid)] = winner
            applied += 1

        try:
            self._rec_cache_by_sid.clear()
        except Exception:
            pass
        self._rebuild_list(preserve_sid=cur_sid)


        msg = (
            f"Applied overrides: {applied}.\n"
            f"Skipped (already overridden): {skipped_overridden}.\n"
            f"Skipped (not identical): {skipped_not_identical}.\n"
            f"Skipped (no winner): {skipped_no_winner}."
        )
        try:
            QMessageBox.information(self, "Auto-resolve identical", msg)
        except Exception:
            pass


    @staticmethod
    def _parse_resolution_px(res_s: str) -> Tuple[int, int, int]:
        """Parse a resolution string like '1280×720' or '1280x720'. Returns (w,h,pixels)."""
        s = str(res_s or "").strip()
        if not s:
            return (0, 0, 0)
        try:
            m = re.search(r"(\d+)\s*[x×]\s*(\d+)", s)
            if not m:
                return (0, 0, 0)
            w = int(m.group(1))
            h = int(m.group(2))
            if w <= 0 or h <= 0:
                return (0, 0, 0)
            return (w, h, int(w * h))
        except Exception:
            return (0, 0, 0)

    @staticmethod
    def _parse_kbps_int(kbps_s: str) -> int:
        s = str(kbps_s or "").strip().lower()
        if not s:
            return 0
        try:
            m = re.search(r"(\d+)\s*kbps", s)
            if m:
                return int(m.group(1))
        except Exception:
            pass
        try:
            n = int(float(s))
            if n > 0:
                return int(n)
        except Exception:
            pass
        return 0

    @staticmethod
    def _parse_fps_milli(fps_s: str) -> int:
        s = str(fps_s or "").strip()
        if not s:
            return 0
        try:
            f = float(s)
            if f > 0:
                return int(round(f * 1000.0))
        except Exception:
            pass
        return 0

    def _quality_score_for_label(self, *, song_id: int, label: str, idx: int) -> Tuple[int, int, int, int, int, int, int]:
        """Return a sortable score tuple for 'best quality' picking.

        Highest wins. The tuple order is chosen to be robust even when ffprobe is missing:
          1) video pixel count (resolution)
          2) video bitrate (kbps)
          3) fps (milli-fps)
          4) video file size (bytes)
          5) total file size (bytes)
          6) base label (tie-break only)
          7) earlier occurrence (stable tie-break)
        """
        pixels = 0
        v_kbps = 0
        fps_m = 0
        v_bytes = 0
        t_bytes = 0

        export_root = str(self._export_roots_by_label.get(str(label), "") or "").strip()
        if export_root:
            assets = self._scan_song_assets(label=str(label), export_root_s=export_root, song_id=int(song_id))
            try:
                v_bytes = int(assets.get("_video_size") or 0)
            except Exception:
                v_bytes = 0
            try:
                t_bytes = int(assets.get("_total_bytes") or 0)
            except Exception:
                t_bytes = 0

            info = self._read_media_info(label=str(label), export_root_s=export_root, song_id=int(song_id), kind="video")
            try:
                _w, _h, pixels = self._parse_resolution_px(info.get("Resolution") or "")
            except Exception:
                pixels = 0
            try:
                v_kbps = self._parse_kbps_int(info.get("Bitrate") or "")
            except Exception:
                v_kbps = 0
            try:
                fps_m = self._parse_fps_milli(info.get("FPS") or "")
            except Exception:
                fps_m = 0

        base = 1 if self._is_base_label(str(label)) else 0
        earlier = -int(idx)  # idx=0 beats idx=1 on tie

        return (int(pixels), int(v_kbps), int(fps_m), int(v_bytes), int(t_bytes), int(base), int(earlier))

    def _auto_pick_best_quality_label(self, song_id: int) -> str:
        """Pick the 'best quality' winner label for an effectively-identical duplicate."""
        occs = self._conflicts.get(int(song_id)) or ()
        labels: List[str] = []
        try:
            for o in occs:
                lab = str(getattr(o, "source_label", "") or "").strip()
                if lab and lab not in labels:
                    labels.append(lab)
        except Exception:
            labels = []

        if len(labels) < 2:
            return ""

        best_lab = ""
        best_score = None
        for idx, lab in enumerate(labels):
            try:
                score = self._quality_score_for_label(song_id=int(song_id), label=str(lab), idx=int(idx))
            except Exception:
                score = (0, 0, 0, 0, 0, 0, -idx)
            if best_score is None or score > best_score:
                best_score = score
                best_lab = str(lab)

        return str(best_lab or "").strip()

    def _auto_pick_best_quality_all(self) -> None:
        """Auto-apply winner overrides for items classified as 'effective' (same melody, different assets)."""
        try:
            from PySide6.QtWidgets import QMessageBox, QProgressDialog, QApplication
        except Exception:
            return

        if not bool(getattr(self, "_identical_detection_ran", False)):
            try:
                QMessageBox.information(self, "Auto-pick best quality", "Run 'Detect identical duplicates' first.")
            except Exception:
                pass
            return

        targets: List[int] = []
        for sid in list(self._ids or []):
            cls = ""
            try:
                cls = str(self._dupe_class_by_sid.get(int(sid), "") or "").strip().lower()
            except Exception:
                cls = ""
            if cls == "effective":
                targets.append(int(sid))

        dlg = QProgressDialog("Picking best quality…", "Cancel", 0, len(targets), self)
        try:
            dlg.setWindowTitle("Auto-pick best quality")
            dlg.setMinimumDuration(0)
            dlg.setValue(0)
        except Exception:
            pass

        applied = 0
        skipped_overridden = 0
        skipped_not_effective = 0
        skipped_no_winner = 0
        checked = 0

        cur_sid = None
        try:
            cur_sid = self._current_song_id()
        except Exception:
            cur_sid = None

        for sid in list(self._ids or []):
            cls = ""
            try:
                cls = str(self._dupe_class_by_sid.get(int(sid), "") or "").strip().lower()
            except Exception:
                cls = ""

            if cls != "effective":
                skipped_not_effective += 1
                continue

            checked += 1
            try:
                dlg.setValue(checked - 1)
            except Exception:
                pass
            try:
                QApplication.processEvents()
            except Exception:
                pass
            try:
                if dlg.wasCanceled():
                    break
            except Exception:
                pass

            try:
                if str(self._overrides.get(int(sid), "") or "").strip():
                    skipped_overridden += 1
                    continue
            except Exception:
                pass

            winner = ""
            try:
                winner = str(self._auto_pick_best_quality_label(int(sid)) or "").strip()
            except Exception:
                winner = ""

            if not winner:
                skipped_no_winner += 1
                continue

            self._overrides[int(sid)] = winner
            applied += 1

        try:
            dlg.setValue(len(targets))
        except Exception:
            pass

        try:
            self._rec_cache_by_sid.clear()
        except Exception:
            pass
        self._rebuild_list(preserve_sid=cur_sid)


        msg = (
            f"Applied overrides: {applied}.\n"
            f"Skipped (already overridden): {skipped_overridden}.\n"
            f"Skipped (not effectively identical): {skipped_not_effective}.\n"
            f"Skipped (no winner): {skipped_no_winner}."
        )
        try:
            if checked < len(targets):
                msg += f"\n\nStopped early ({checked}/{len(targets)})."
        except Exception:
            pass

        try:
            QMessageBox.information(self, "Auto-pick best quality", msg)
        except Exception:
            pass

    @staticmethod
    def _ms_from_fmt(s: str) -> Optional[int]:
        s = str(s or "").strip()
        if not s:
            return None
        try:
            m = re.search(r"\((\d+)\s*ms\)", s)
            if m:
                return int(m.group(1))
        except Exception:
            pass
        try:
            if ":" in s:
                parts = [p.strip() for p in s.split(":")]
                if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                    return (int(parts[0]) * 60 + int(parts[1])) * 1000
        except Exception:
            pass
        return None

    @staticmethod
    def _norm_ci(s: str) -> str:
        return " ".join(str(s or "").strip().lower().split())

    def _classify_conflict(self, song_id: int) -> Tuple[str, str]:
        """Return (class, summary) where class is one of: identical, effective, different."""
        occs = self._conflicts.get(int(song_id)) or ()
        labels: List[str] = []
        try:
            for o in occs:
                lab = str(getattr(o, "source_label", "") or "").strip()
                if lab and lab not in labels:
                    labels.append(lab)
        except Exception:
            labels = []

        if len(labels) < 2:
            return "different", ""

        # Determine whether all semantic melody fingerprints match (and are present)
        fp_list: List[str] = []
        missing_fp = False
        try:
            for o in occs:
                lab = str(getattr(o, "source_label", "") or "").strip()
                if lab not in labels:
                    continue
                fp = str(getattr(o, "melody1_fp", "") or "").strip()
                if not fp:
                    missing_fp = True
                fp_list.append(fp or "MISSING")
        except Exception:
            missing_fp = True

        semantic_same = (not missing_fp) and (len(set(fp_list)) <= 1)

        # Collect diffs across pairs (unique, first few) for summaries.
        a = labels[0]
        diffs_all: List[str] = []
        for b in labels[1:]:
            diffs = self._pair_diffs(song_id=int(song_id), a=a, b=b)
            if diffs:
                diffs_all.extend(diffs)

        uniq: List[str] = []
        for d in diffs_all:
            if d and d not in uniq:
                uniq.append(d)

        # If semantic fingerprints do not match (or are missing), this is a true conflict.
        if not semantic_same:
            return "different", "; ".join(uniq[:4])

        # Semantic fingerprints match. If there are other diffs, it's "effectively identical".
        # Filter out any melody-fingerprint diagnostics that might sneak in.
        uniq2 = [d for d in uniq if d not in ("melody fingerprint differs", "melody fingerprint missing")]
        if uniq2:
            return "effective", "; ".join(uniq2[:4])

        # Only SHA mismatch / trivial diffs remain.
        return "identical", ""

    def _pair_diffs(self, *, song_id: int, a: str, b: str) -> List[str]:
        diffs: List[str] = []
        a_root = str(self._export_roots_by_label.get(str(a), "") or "")
        b_root = str(self._export_roots_by_label.get(str(b), "") or "")
        if not a_root or not b_root:
            return ["missing export root"]

        meta_a = self._read_song_meta(label=a, export_root_s=a_root, song_id=int(song_id))
        meta_b = self._read_song_meta(label=b, export_root_s=b_root, song_id=int(song_id))

        # Semantic melody fingerprint (primary)
        try:
            occs = self._conflicts.get(int(song_id)) or ()
            fp_map: Dict[str, str] = {}
            for o in occs:
                lab0 = str(getattr(o, "source_label", "") or "").strip()
                fp0 = str(getattr(o, "melody1_fp", "") or "").strip() or ""
                if lab0:
                    fp_map[lab0] = fp0
            fpa = fp_map.get(str(a), "") or ""
            fpb = fp_map.get(str(b), "") or ""
            if fpa and fpb and fpa != fpb:
                diffs.append("melody fingerprint differs")
            if (not fpa) or (not fpb):
                # If fingerprint missing, we can't be confident; flag it.
                diffs.append("melody fingerprint missing")
        except Exception:
            pass


        try:
            ta = self._norm_ci(meta_a.get("Title", ""))
            tb = self._norm_ci(meta_b.get("Title", ""))
            aa = self._norm_ci(meta_a.get("Artist", ""))
            ab = self._norm_ci(meta_b.get("Artist", ""))
            if ta and tb and ta != tb:
                diffs.append("title differs")
            if aa and ab and aa != ab:
                diffs.append("artist differs")
        except Exception:
            pass

        try:
            da = self._ms_from_fmt(str(meta_a.get("Duration", "") or ""))
            db = self._ms_from_fmt(str(meta_b.get("Duration", "") or ""))
            if da is not None and db is not None and abs(int(da) - int(db)) > 250:
                diffs.append("duration differs")
        except Exception:
            pass

        try:
            ya = str(meta_a.get("Year", "") or "").strip()
            yb = str(meta_b.get("Year", "") or "").strip()
            if ya and yb and ya != yb:
                diffs.append("year differs")
        except Exception:
            pass

        assets_a = self._scan_song_assets(label=a, export_root_s=a_root, song_id=int(song_id))
        assets_b = self._scan_song_assets(label=b, export_root_s=b_root, song_id=int(song_id))
        try:
            if str(assets_a.get("melody_1.xml", "")) != str(assets_b.get("melody_1.xml", "")):
                diffs.append("melody_1.xml presence differs")
        except Exception:
            pass

        def _int_key(d: Dict[str, object], k: str) -> Optional[int]:
            try:
                v = d.get(k)
                if v is None:
                    return None
                return int(v)
            except Exception:
                return None

        a_total = _int_key(assets_a, "_total_bytes")
        b_total = _int_key(assets_b, "_total_bytes")
        if a_total is not None and b_total is not None and a_total != b_total:
            diffs.append("total size differs")

        a_aud = _int_key(assets_a, "_audio_size")
        b_aud = _int_key(assets_b, "_audio_size")
        if a_aud is not None and b_aud is not None and a_aud != b_aud:
            diffs.append("audio differs")

        a_vid = _int_key(assets_a, "_video_size")
        b_vid = _int_key(assets_b, "_video_size")
        if a_vid is not None and b_vid is not None and a_vid != b_vid:
            diffs.append("video differs")

        mel_a = self._read_melody_stats(label=a, export_root_s=a_root, song_id=int(song_id))
        mel_b = self._read_melody_stats(label=b, export_root_s=b_root, song_id=int(song_id))
        try:
            na = int(mel_a.get("_notes") or 0)
            nb = int(mel_b.get("_notes") or 0)
            if na != nb:
                diffs.append("note count differs")
        except Exception:
            pass
        try:
            pa_min = mel_a.get("_pitch_min")
            pb_min = mel_b.get("_pitch_min")
            pa_max = mel_a.get("_pitch_max")
            pb_max = mel_b.get("_pitch_max")
            if pa_min is not None and pb_min is not None and int(pa_min) != int(pb_min):
                diffs.append("pitch min differs")
            if pa_max is not None and pb_max is not None and int(pa_max) != int(pb_max):
                diffs.append("pitch max differs")
        except Exception:
            pass
        try:
            sa = mel_a.get("_span_ms")
            sb = mel_b.get("_span_ms")
            if sa is not None and sb is not None and abs(int(sa) - int(sb)) > 250:
                diffs.append("melody span differs")
        except Exception:
            pass

        if diffs:
            return diffs

        try:
            if self._ffprobe_path():
                vid_a = self._read_media_info(label=a, export_root_s=a_root, song_id=int(song_id), kind="video")
                vid_b = self._read_media_info(label=b, export_root_s=b_root, song_id=int(song_id), kind="video")
                ra = str(vid_a.get("Resolution", "") or "")
                rb = str(vid_b.get("Resolution", "") or "")
                if ra and rb and ra != rb:
                    diffs.append("video resolution differs")
                fa = str(vid_a.get("FPS", "") or "")
                fb = str(vid_b.get("FPS", "") or "")
                if fa and fb and fa != fb:
                    diffs.append("video fps differs")

                aud_a = self._read_media_info(label=a, export_root_s=a_root, song_id=int(song_id), kind="audio")
                aud_b = self._read_media_info(label=b, export_root_s=b_root, song_id=int(song_id), kind="audio")
                ca = str(aud_a.get("Channels", "") or "")
                cb = str(aud_b.get("Channels", "") or "")
                if ca and cb and ca != cb:
                    diffs.append("audio channels differs")
                sr_a = str(aud_a.get("Sample rate", "") or "")
                sr_b = str(aud_b.get("Sample rate", "") or "")
                if sr_a and sr_b and sr_a != sr_b:
                    diffs.append("audio sample rate differs")
        except Exception:
            pass

        return diffs

    def _compute_diff(self) -> None:
        """Compute metadata + asset presence diffs (human-readable)."""
        sid = self._current_song_id()
        if sid is None:
            return

        a, b = self._compare_selected_labels()
        if not a or not b or a == b:
            return

        occs = self._conflicts.get(int(sid)) or ()
        sha_by_label: Dict[str, str] = {}
        fp_by_label: Dict[str, str] = {}
        try:
            for o in occs:
                lab = str(getattr(o, "source_label", "") or "").strip()
                sha = str(getattr(o, "melody1_sha1", "") or "").strip() or "MISSING"
                fp = str(getattr(o, "melody1_fp", "") or "").strip() or "MISSING"
                if lab:
                    sha_by_label[lab] = sha
                    fp_by_label[lab] = fp
        except Exception:
            sha_by_label = {}
            fp_by_label = {}

        a_root = str(self._export_roots_by_label.get(a, "") or "")
        b_root = str(self._export_roots_by_label.get(b, "") or "")

        # C5: cache diff rows, invalidated by cheap signatures.
        cache_key = (int(sid), str(a), str(b))
        try:
            a_root_n = self._norm_root_str(a_root)
            b_root_n = self._norm_root_str(b_root)
        except Exception:
            a_root_n = str(a_root or "")
            b_root_n = str(b_root or "")

        try:
            assets_a = self._scan_song_assets(label=a, export_root_s=a_root, song_id=int(sid))
            assets_b = self._scan_song_assets(label=b, export_root_s=b_root, song_id=int(sid))
            mel_a = self._read_melody_stats(label=a, export_root_s=a_root, song_id=int(sid))
            mel_b = self._read_melody_stats(label=b, export_root_s=b_root, song_id=int(sid))
            vid_a = self._read_media_info(label=a, export_root_s=a_root, song_id=int(sid), kind="video")
            vid_b = self._read_media_info(label=b, export_root_s=b_root, song_id=int(sid), kind="video")
            aud_a = self._read_media_info(label=a, export_root_s=a_root, song_id=int(sid), kind="audio")
            aud_b = self._read_media_info(label=b, export_root_s=b_root, song_id=int(sid), kind="audio")
        except Exception:
            assets_a = {}
            assets_b = {}
            mel_a = {}
            mel_b = {}
            vid_a = {}
            vid_b = {}
            aud_a = {}
            aud_b = {}

        sig = (
            a_root_n,
            b_root_n,
            tuple(self._glob_sig(a_root_n, ["songs_*.xml"])) if a_root_n else tuple(),
            tuple(self._glob_sig(a_root_n, ["acts_*.xml"])) if a_root_n else tuple(),
            tuple(self._glob_sig(b_root_n, ["songs_*.xml"])) if b_root_n else tuple(),
            tuple(self._glob_sig(b_root_n, ["acts_*.xml"])) if b_root_n else tuple(),
            tuple(assets_a.get("_sig_melody") or ()),
            tuple(assets_a.get("_sig_audio") or ()),
            tuple(assets_a.get("_sig_video") or ()),
            tuple(assets_b.get("_sig_melody") or ()),
            tuple(assets_b.get("_sig_audio") or ()),
            tuple(assets_b.get("_sig_video") or ()),
            tuple(mel_a.get("_sig") or ()),
            tuple(mel_b.get("_sig") or ()),
            tuple(vid_a.get("_sig") or ()),
            tuple(vid_b.get("_sig") or ()),
            tuple(aud_a.get("_sig") or ()),
            tuple(aud_b.get("_sig") or ()),
            str(fp_by_label.get(a, "MISSING")),
            str(fp_by_label.get(b, "MISSING")),
            str(sha_by_label.get(a, "MISSING")),
            str(sha_by_label.get(b, "MISSING")),
        )

        try:
            cached = self._cmp_diff_cache.get(cache_key)
            if cached and isinstance(cached, dict) and cached.get("_sig") == sig and isinstance(cached.get("rows"), list):
                self._render_cmp_rows(cached.get("rows") or [])
                return
        except Exception:
            pass

        rows: List[Tuple[str, str, str]] = []

        def add(field: str, a_val: str, b_val: str) -> None:
            rows.append((str(field), str(a_val), str(b_val)))

        # Identity rows
        add("Source", a, b)
        add("Export root", a_root or "(unknown)", b_root or "(unknown)")
        add("melody fingerprint", fp_by_label.get(a, "MISSING"), fp_by_label.get(b, "MISSING"))
        add("melody_1.xml sha1 (advanced)", sha_by_label.get(a, "MISSING"), sha_by_label.get(b, "MISSING"))

        # Metadata diffs
        add("— Metadata —", "", "")
        meta_a = self._read_song_meta(label=a, export_root_s=a_root, song_id=int(sid))
        meta_b = self._read_song_meta(label=b, export_root_s=b_root, song_id=int(sid))

        # stable-ish field order
        meta_fields = ["Title", "Artist", "Duration", "Preview", "Year", "Language", "Genre"]
        for f in meta_fields:
            av = str(meta_a.get(f, "") or "")
            bv = str(meta_b.get(f, "") or "")
            if not av:
                av = "(unknown)"
            if not bv:
                bv = "(unknown)"
            add(f, av, bv)

        # Asset presence diffs
        add("— Assets —", "", "")
        asset_fields = ["Song folder", "melody_1.xml", "Audio", "Video", "Files"]
        for f in asset_fields:
            av = str(assets_a.get(f, "") or "")
            bv = str(assets_b.get(f, "") or "")
            if not av:
                av = "(unknown)"
            if not bv:
                bv = "(unknown)"
            add(f, av, bv)

        # Melody stats (C3)
        add("— Melody stats —", "", "")
        mel_fields = ["Notes", "Pitch range", "Avg pitch", "Span", "Density", "Longest note", "Coverage", "Parse"]
        for f in mel_fields:
            av = str(mel_a.get(f, "") or "")
            bv = str(mel_b.get(f, "") or "")
            if not av and not bv:
                continue
            add(f, av, bv)

        # Media info (C4) — best-effort via ffprobe (if available)
        add("— Media info —", "", "")
        for f in ["Status", "Codec", "Resolution", "FPS", "Duration", "Bitrate"]:
            av = str(vid_a.get(f, "") or "")
            bv = str(vid_b.get(f, "") or "")
            if not av and not bv:
                continue
            add(f"Video {f}", av, bv)

        for f in ["Status", "Codec", "Sample rate", "Channels", "Duration", "Bitrate"]:
            av = str(aud_a.get(f, "") or "")
            bv = str(aud_b.get(f, "") or "")
            if not av and not bv:
                continue
            add(f"Audio {f}", av, bv)

        self._render_cmp_rows(rows)
        try:
            self._cmp_diff_cache[cache_key] = {"_sig": sig, "rows": list(rows)}
        except Exception:
            pass

    def _apply_current(self) -> None:
        sid = self._current_song_id()
        if sid is None:
            return
        try:
            prior_row = int(self.listw.currentRow())
        except Exception:
            prior_row = -1
        lab = str(self.winner_combo.currentText() or "").strip()
        if not lab:
            return
        self._overrides[int(sid)] = lab
        try:
            self._rec_cache_by_sid.pop(int(sid), None)
        except Exception:
            pass
        self._rebuild_list(preserve_sid=int(sid), prefer_row=prior_row)

        self._advance_after_action(prior_row=prior_row, sid=int(sid))


    def _clear_current(self) -> None:
        sid = self._current_song_id()
        if sid is None:
            return
        try:
            prior_row = int(self.listw.currentRow())
        except Exception:
            prior_row = -1

        try:
            if int(sid) in self._overrides:
                self._overrides.pop(int(sid), None)
        except Exception:
            pass
        try:
            self._rec_cache_by_sid.pop(int(sid), None)
        except Exception:
            pass
        self._rebuild_list(preserve_sid=int(sid), prefer_row=prior_row)

        self._advance_after_action(prior_row=prior_row, sid=int(sid))



