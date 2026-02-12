# ruff: noqa
from __future__ import annotations

"""Qt UI widget creation (internal).

Extracted from `spcdb_tool/qt/main_window.py` as part of the incremental Qt refactor.
Behavior is intended to be unchanged.

Imported lazily via `MainWindow`.
"""

from typing import Dict, List, Set, Tuple

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QLabel,
    QLineEdit,
    QMenu,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTextEdit,
    QToolButton,
    QSizePolicy,
)

from ..controller import SongAgg, SongOccur
from ..util import ensure_default_extractor_dir

from .delegates import (
    _NoFocusItemDelegate,
    _SourcesTintDelegate,
    _NoAccentProxyStyle,
    _TABLE_NOFOCUS_QSS,
)


def create_widgets(win) -> None:
    """Create and initialize all Qt widgets used by MainWindow.

    This function is intentionally permissive (lots of try/except) to preserve
    legacy behavior and avoid UI startup regressions.
    """

    # Keep the original variable name used in main_window to minimize risk.
    self = win
    self.base_edit = QLineEdit()
    self.output_edit = QLineEdit()
    self.extractor_edit = QLineEdit()
    try:
        # Recommended location: ./extractor (not bundled).
        ensure_default_extractor_dir()
    except Exception:
        pass
    try:
        self.extractor_edit.setPlaceholderText("Recommended: put scee_london(.exe) in ./extractor/ then Browse…")
    except Exception:
        pass

    self.chk_validate_write_report = QCheckBox("Write validate_report.txt")
    self.chk_preflight = QCheckBox("Preflight before Build (validate discs)")
    self.chk_block_build = QCheckBox("Block Build when Validate has Errors")

    # Allow rebuilding into an existing output folder (safe: temp build then atomic replace).
    self.chk_allow_overwrite = QCheckBox("Allow overwrite existing output")
    self.chk_keep_backup = QCheckBox("Keep backup of existing output (recommended)")
    try:
        self.chk_keep_backup.setChecked(True)
        self.chk_keep_backup.setEnabled(False)  # enabled when overwrite is enabled
    except Exception:
        pass

    # Disc Branding (XMB): optional ICON0.PNG + PIC1.PNG overrides applied at build time.
    self.disc_icon_path_edit = QLineEdit()
    try:
        self.disc_icon_path_edit.setPlaceholderText("ICON0.PNG override (optional)")
        self.disc_icon_path_edit.setReadOnly(True)
    except Exception:
        pass
    self.btn_disc_icon_choose = QPushButton("Choose...")
    self.btn_disc_icon_clear = QPushButton("Clear")

    self.disc_bg_path_edit = QLineEdit()
    try:
        self.disc_bg_path_edit.setPlaceholderText("PIC1.PNG override (optional)")
        self.disc_bg_path_edit.setReadOnly(True)
    except Exception:
        pass
    self.btn_disc_bg_choose = QPushButton("Choose...")
    self.btn_disc_bg_clear = QPushButton("Clear")

    # Disc Branding previews
    self.disc_icon_preview_lbl = QLabel()
    try:
        self.disc_icon_preview_lbl.setFixedHeight(88)
        self.disc_icon_preview_lbl.setMinimumWidth(0)
        try:
            self.disc_icon_preview_lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        except Exception:
            pass
        self.disc_icon_preview_lbl.setAlignment(Qt.AlignCenter)
        self.disc_icon_preview_lbl.setText("No icon")
        self.disc_icon_preview_lbl.setStyleSheet("border: 1px solid palette(mid);")
    except Exception:
        pass

    self.disc_icon_source_lbl = QLabel("Source: -")
    try:
        self.disc_icon_source_lbl.setStyleSheet("color: palette(mid); font-size: 11px;")
    except Exception:
        pass

    self.disc_bg_preview_lbl = QLabel()
    try:
        self.disc_bg_preview_lbl.setFixedHeight(135)
        self.disc_bg_preview_lbl.setMinimumWidth(0)
        try:
            self.disc_bg_preview_lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        except Exception:
            pass
        self.disc_bg_preview_lbl.setAlignment(Qt.AlignCenter)
        self.disc_bg_preview_lbl.setText("No background")
        self.disc_bg_preview_lbl.setStyleSheet("border: 1px solid palette(mid);")
    except Exception:
        pass

    self.disc_bg_source_lbl = QLabel("Source: -")
    try:
        self.disc_bg_source_lbl.setStyleSheet("color: palette(mid); font-size: 11px;")
    except Exception:
        pass

    self.chk_disc_branding_autoresize = QCheckBox("Auto-resize to PS3-friendly sizes")
    self.chk_disc_branding_apply = QCheckBox("Apply to output disc on Build")
    self.btn_disc_branding_apply_existing = QPushButton("Apply to existing output…")
    try:
        self.btn_disc_branding_apply_existing.setToolTip(
            "Apply ICON0.PNG / PIC1.PNG overrides into an already-built output disc folder (no rebuild).\n"
            "Choose the output disc folder (the one containing PS3_GAME)."
        )
    except Exception:
        pass
    try:
        self.chk_disc_branding_autoresize.setChecked(True)
        self.chk_disc_branding_apply.setChecked(True)
    except Exception:
        pass
    # Sources table (0.8e): Path moved to the last column.
    self.sources_table = QTableWidget(0, 3)
    self.sources_table.setHorizontalHeaderLabels(["Label", "State", "Path"])
    self.sources_title_lbl = QLabel("Sources: 0")
    self.sources_tallies_lbl = QLabel("Status (shown): -")

    # Sources filtering (v0.9.37)
    self.sources_filter_edit = QLineEdit()
    try:
        self.sources_filter_edit.setPlaceholderText("Filter sources (Label/Path)...")
    except Exception:
        pass

    try:
        self.sources_filter_edit.setToolTip("Filter the Sources table by Label/Path.")
    except Exception:
        pass

    self.btn_sources_states = QToolButton()
    self.btn_sources_states.setText("States…")
    try:
        self.btn_sources_states.setToolTip("Filter sources by disc state.")
    except Exception:
        pass
    self._src_state_actions: Dict[str, QAction] = {}
    try:
        m_states = QMenu(self)
        try:
            m_states.setToolTipsVisible(True)
        except Exception:
            pass
        for key, tip in [
            ("Extracted", "Show extracted sources"),
            ("Packed", "Show packed sources"),
            ("Partial", "Show partially extracted sources"),
            ("Needs extract", "Show sources needing extraction"),
            ("Errors", "Show sources with validation errors"),
            ("Other", "Show sources not matching the above"),
        ]:
            act = QAction(key, self)
            act.setCheckable(True)
            act.setChecked(True)
            try:
                act.setToolTip(tip)
            except Exception:
                pass
            self._src_state_actions[key] = act
            m_states.addAction(act)
        self.btn_sources_states.setMenu(m_states)
        self.btn_sources_states.setPopupMode(QToolButton.InstantPopup)
    except Exception:
        pass

    self.btn_sources_select_shown = QPushButton("Select shown")
    try:
        self.btn_sources_select_shown.setToolTip("Select (highlight) all currently shown Sources (excludes Base).")
    except Exception:
        pass

    self.btn_sources_clear_sel = QPushButton("Clear sel")
    try:
        self.btn_sources_clear_sel.setToolTip("Clear selection in Sources.")
    except Exception:
        pass

    # Resize: user-resizable columns (Interactive). Keep State compact by default, Path wide.
    try:
        from PySide6.QtWidgets import QHeaderView
        hdr = self.sources_table.horizontalHeader()
        for i in range(3):
            hdr.setSectionResizeMode(i, QHeaderView.Interactive)
        try:
            # Don't force stretch-to-last; it can fight manual resizing.
            hdr.setStretchLastSection(False)
        except Exception:
            pass
        try:
            self.sources_table.setColumnWidth(0, 180)
            self.sources_table.setColumnWidth(1, 140)
            self.sources_table.setColumnWidth(2, 520)
        except Exception:
            pass
    except Exception:
        pass


    try:
        # Keep Sources non-editable; remove focus outline artefacts (blue carets in some styles).
        self.sources_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.sources_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.sources_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.sources_table.setItemDelegate(_SourcesTintDelegate(self.sources_table))
        self.sources_table.setStyleSheet(_TABLE_NOFOCUS_QSS)
        try:
            self.sources_table.setStyle(_NoAccentProxyStyle(self.sources_table.style()))
        except Exception:
            pass
        try:
            self.sources_table.setFocusPolicy(Qt.StrongFocus)
        except Exception:
            pass
    except Exception:
        pass

    # ---- Songs (Build selection) ----
    self.song_search_edit = QLineEdit()
    try:
        self.song_search_edit.setPlaceholderText("Search songs (Title/Artist/ID)...")
    except Exception:
        pass

    try:
        self.song_search_edit.setToolTip(
            "Search matches Title / Artist / ID.\n"
            "Split by spaces for multiple terms."
        )
    except Exception:
        pass
    self.song_source_combo = QComboBox()
    self.song_source_combo.addItems(["All"])

    # Source filter: normal dropdown (search via the main search box).
    try:
        self.song_source_combo.setEditable(False)
    except Exception:
        pass
    try:
        self.song_source_combo.setMinimumWidth(220)
        self.song_source_combo.setMaximumWidth(420)
    except Exception:
        pass
    try:
        self.song_source_combo.view().setTextElideMode(Qt.ElideNone)
    except Exception:
        pass


    try:
        self.song_source_combo.setToolTip(
            "Filter the Songs table by source.\n"
            "Selected discs uses the selected rows in the Sources table (left)."
        )
    except Exception:
        pass

    self.song_selected_only_chk = QCheckBox("Included only")


    try:
        self.song_selected_only_chk.setToolTip(
            "Show only songs enabled for build (On checkbox ticked).\n"
            "This is not the same as the highlighted row."
        )
    except Exception:
        pass

    # 0.8c: Quick presets / saved filter presets
    self.song_preset_combo = QComboBox()
    self.song_preset_combo.setMinimumWidth(180)


    try:
        self.song_preset_combo.setToolTip(
            "Quick views (filters only): All songs, Conflicts, Duplicates, Overrides, Disabled.\n"
            "Presets do not modify disc files."
        )
    except Exception:
        pass

    # Preset state
    self._active_preset_name: str = "All songs"
    self._qt_state_loaded: bool = False
    self._qt_state_selection_initialized: bool = False
    self._qt_state_had_disabled_key: bool = False
    self._qt_state_had_selected_key: bool = False
    self._qt_state_applied_disabled_ids: bool = False
    self._qt_state_applied_selected_ids: bool = False
    self._qt_state_last_all_song_ids: set[int] = set()

    self._applying_preset: bool = False

    # Extra filter flags (beyond search/source/selected_only)
    self._filter_conflicts_only = False
    self._filter_duplicates_only = False
    self._filter_overrides_only = False
    self._filter_disabled_only = False

    self.btn_refresh_songs = QPushButton("Refresh Songs")


    try:
        self.btn_refresh_songs.setToolTip(
            "Rebuild the Songs table from the current disc index/cache.\n"
            "Use after adding/removing discs or after extraction."
        )
    except Exception:
        pass

    self.btn_select_all_visible = QPushButton("Select All (visible)")
    self.btn_clear_visible = QPushButton("Clear (visible)")
    self.btn_invert_visible = QPushButton("Invert (visible)")


    try:
        self.btn_select_all_visible.setToolTip(
            "Enable On for all visible songs (based on your current filters)."
        )
        self.btn_clear_visible.setToolTip(
            "Disable On for all visible songs (based on your current filters)."
        )
        self.btn_invert_visible.setToolTip(
            "Invert On for all visible songs (based on your current filters)."
        )
    except Exception:
        pass

    # Songs table columns (0.8e): move Song ID to the end.
    self.songs_table = QTableWidget(0, 6)
    self.songs_table.setHorizontalHeaderLabels(["On", "Title", "Artist", "Preferred", "Sources", "ID"])
    try:
        self.songs_table.verticalHeader().setVisible(False)
    except Exception:
        pass
    # Allow user-resizing (do not force stretch-to-last; it fights user sizing).
    try:
        self.songs_table.horizontalHeader().setStretchLastSection(False)
    except Exception:
        pass
    try:
        # Keep table non-editable (prevents text cursor/blue carets). We'll toggle the 'On' checkbox via a click handler.
        self.songs_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.songs_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.songs_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        # Remove focus outline artefacts on selected cells.
        self.songs_table.setItemDelegate(_NoFocusItemDelegate(self.songs_table))
        self.songs_table.setStyleSheet(_TABLE_NOFOCUS_QSS)
        try:
            self.songs_table.setStyle(_NoAccentProxyStyle(self.songs_table.style()))
        except Exception:
            pass
        try:
            self.songs_table.setFocusPolicy(Qt.StrongFocus)
        except Exception:
            pass
    except Exception:
        pass

    # Make the 'On' checkbox column reliably clickable/visible (avoid auto-shrinking).
    try:
        from PySide6.QtWidgets import QHeaderView
        hdr2 = self.songs_table.horizontalHeader()
        hdr2.setSectionResizeMode(0, QHeaderView.Fixed)
        self.songs_table.setColumnWidth(0, 44)
        # 0.8e: user-resizable columns.
        for i in range(1, 6):
            hdr2.setSectionResizeMode(i, QHeaderView.Interactive)
        try:
            self.songs_table.setColumnWidth(1, 420)  # Title
            self.songs_table.setColumnWidth(2, 260)  # Artist
            self.songs_table.setColumnWidth(3, 150)  # Preferred
            self.songs_table.setColumnWidth(4, 460)  # Sources
            self.songs_table.setColumnWidth(5, 90)   # ID
        except Exception:
            pass
    except Exception:
        try:
            self.songs_table.setColumnWidth(0, 44)
        except Exception:
            pass


    self.songs_status_lbl = QLabel("Songs: 0 | Included: 0")
    try:
        self.songs_status_lbl.setToolTip(
            "Status bar help:\n"
            "Songs: total songs found (shown = after filters)\n"
            "Included: songs that will appear in-game\n"
            "Picked: songs you ticked On\n"
            "Duplicate title: same Title + Artist picked more than once (game may show one)\n"
            "Conflicts: same Song ID differs between sources (needs resolving)\n"
            "ID dupes: Song IDs present in multiple sources (normal)"
        )
    except Exception:
        pass
    self.cache_status_lbl = QLabel("Cache: -")
    try:
        self.cache_status_lbl.setToolTip(
            "Cache shows how many discs were loaded from the saved song index.\n"
            "Indexed discs make Refresh Songs faster.\n"
            "If a disc has no index or it's stale, it will be scanned again."
        )
    except Exception:
        pass

    self._songs_refresh_last_key = ""
    self._songs_refresh_last_ts = 0.0
    self._qt_state_last_write_ts = 0.0
    self._qt_state_wanted_source = "All"
    self._qt_state_version = 0
    self._qt_state_default_all_disabled = True

    self._songs_all: List[SongAgg] = []
    self._songs_by_id: Dict[int, SongAgg] = {}
    self._dedupe_songs_with_dups = 0
    self._dedupe_extra_hidden = 0
    self._disc_song_ids_by_label: Dict[str, set[int]] = {}
    self._selected_song_ids: Set[int] = set()
    self._disabled_song_ids: Set[int] = set()  # song_ids explicitly turned off by user
    self._songs_all_raw: List[SongAgg] = []
    self._export_roots_by_label: Dict[str, str] = {}
    self._song_conflicts: Dict[int, Tuple[SongOccur, ...]] = {}
    self._song_source_overrides: Dict[int, str] = {}
    self._display_dup_keep_overrides: Dict[str, int] = {}  # display-key -> kept song_id (autofix)
    self._songs_group_song_ids: Dict[str, List[int]] = {}  # label -> song_ids in current render (for group toggles)
    self._songs_visible_ids: List[int] = []
    # Disc grouping/collapsing (0.6b)
    self._song_group_order_labels: List[str] = []  # Base + sources in UI order
    self._song_group_expanded: Dict[str, bool] = {}  # label -> expanded?
    self._songs_header_rows: Dict[int, str] = {}  # table row -> disc label (header rows)
    self._songs_last_targets: List[tuple[str, str, bool]] = []  # targets used for last refresh
    self._qt_state_collapsed_groups: List[str] = []  # loaded from qt state file (best-effort)
    self._songs_table_loading = False
    self._songs_thread = None
    self._songs_worker = None

    # filter hooks
    # persist filters (best-effort)

    # Presets (0.8c)

    # Populate preset combo (built-ins + saved)
    try:
        self._rebuild_preset_combo()
    except Exception:
        pass

    # Default view should be 'All songs' (v0.8g)
    try:
        self._set_preset_combo_to_name(getattr(self, '_active_preset_name', 'All songs') or 'All songs')
    except Exception:
        pass

    self.log_edit = QTextEdit()
    self.log_edit.setReadOnly(True)
    # Actions (wired in v0.5.10c1b: Validate + Copy report + Cancel)
    self.btn_validate = QPushButton("Validate Selected")

    self.btn_extract = QPushButton("Extract Selected")

    self.btn_build = QPushButton("Build Selected")
    self.btn_update_existing = QPushButton("Update Existing…")
    try:
        self.btn_update_existing.setToolTip(
            "Update an already-built output disc folder in-place (keeps a backup).\n"
            "Much faster when you only add a few songs or change branding.\n"
            "You will be asked to choose the existing output disc folder (contains PS3_GAME)."
        )
    except Exception:
        pass


    try:
        self.btn_validate.setToolTip(
            "Validate selected discs for common issues (missing files, conflicts, blockers).\n"
            "Does not modify disc content."
        )
        self.btn_extract.setToolTip(
            "Extract selected packed sources using the external extractor tool.\n"
            "Packed sources must be extracted before they can be used for build."
        )
        self.btn_build.setToolTip(
            "Build the merged output disc from your current selections.\n"
            "Conflicts may need resolving before build."
        )
    except Exception:
        pass

    self.btn_copy_report = QPushButton("Copy report")
    self.btn_copy_report.setEnabled(False)

    self.btn_cancel = QPushButton("Cancel")
    self.btn_cancel.setEnabled(False)

    # Build UX (v0.5.10c8b): phase label + progress bar fed by @@PROGRESS messages.
    self.op_phase_lbl = QLabel("Idle")
    self.op_detail_lbl = QLabel("")
    try:
        self.op_detail_lbl.setWordWrap(True)
    except Exception:
        pass
    self.op_elapsed_lbl = QLabel("00:00")
    self.op_eta_lbl = QLabel("—")
    self.op_eta_title_lbl = QLabel("ETA:")
    self.op_progress = QProgressBar()
    try:
        self.op_progress.setTextVisible(False)
    except Exception:
        pass
    self.op_progress.setRange(0, 100)
    self.op_progress.setValue(0)
    self.op_progress.setVisible(False)

    self._last_validate_report_text = ""
    self._validate_badge_by_path: Dict[str, str] = {}
    self._validate_thread = None
    self._validate_worker = None
    self._cancel_token = None
    self._extract_thread = None
    self._extract_worker = None
    self._build_thread = None
    self._build_worker = None
    self._copy_thread = None
    self._copy_worker = None
    self._cleanup_thread = None
    self._cleanup_worker = None
    self._active_op = None  # "validate" | "extract" | "build" | "scan" | None
    self._busy = False
    # Op clock + ETA (v0.9.34)
    self._op_start_ts = None  # monotonic seconds
    self._op_clock_timer = QTimer(self)
    try:
        self._op_clock_timer.setInterval(500)
    except Exception:
        pass
    self._eta_phase = None
    self._eta_total = None
    self._eta_current = None
    self._eta_last_ts = None
    self._eta_last_current = None
    self._eta_spu_ema = None
    self._eta_phase_start_ts = None
    self._eta_indeterminate = True
    self._eta_phase_ema_sec: Dict[str, float] = {}
    self._eta_hist_current_key = None
    self._eta_hist_phase_start_ts = None
    self._eta_hist_dirty = False

    # Status bar hints (hover): short summaries shown in the main status bar.
    try:
        self.base_edit.setToolTip("Base disc folder (extracted). Required for Build.")
        self.base_edit.setStatusTip("Base disc folder (extracted).")
    except Exception:
        pass

    try:
        self.output_edit.setToolTip("Output parent folder for the built disc.")
        self.output_edit.setStatusTip("Output folder for Build.")
    except Exception:
        pass

    try:
        self.extractor_edit.setStatusTip("SCEE extractor executable (needed for packed sources).")
    except Exception:
        pass

    try:
        self.sources_filter_edit.setStatusTip("Filter Sources by Label/Path.")
    except Exception:
        pass

    try:
        self.btn_sources_states.setStatusTip("Filter Sources by state.")
    except Exception:
        pass

    try:
        self.btn_sources_select_shown.setStatusTip("Select all shown Source rows (for Validate/Extract).")
    except Exception:
        pass

    try:
        self.btn_sources_clear_sel.setStatusTip("Clear Source row selection.")
    except Exception:
        pass

    try:
        self.song_search_edit.setStatusTip("Filter Songs by Title/Artist/ID.")
    except Exception:
        pass

    try:
        self.song_source_combo.setStatusTip("Filter Songs by disc label (or Selected discs).")
    except Exception:
        pass

    try:
        self.song_selected_only_chk.setStatusTip("Show only songs enabled for Build (On ticked).")
    except Exception:
        pass

    try:
        self.song_preset_combo.setStatusTip("Apply a quick view preset (filters only).")
    except Exception:
        pass

    for _attr, _tip in [
        ('btn_select_all_visible', 'Enable all visible songs for Build.'),
        ('btn_clear_visible', 'Disable all visible songs for Build.'),
        ('btn_invert_visible', 'Invert visible song selection (On).'),
        ('btn_refresh_songs', 'Refresh the Songs index from selected discs.'),
        ('btn_validate', 'Validate selected discs.'),
        ('btn_extract', 'Extract selected discs.'),
        ('btn_build', 'Build output disc from selected songs.'),
        ('btn_update_existing', 'Update an already-built output disc folder in-place (faster; keeps backup).'),
        ('btn_cancel', 'Cancel the current operation.'),
        ('btn_copy_report', 'Copy the latest validate/preflight report.'),
    ]:
        try:
            w = getattr(self, _attr, None)
            if w is not None:
                w.setStatusTip(str(_tip))
        except Exception:
            pass

    # Disc state badges for Sources table
    self._disc_validation_badge: Dict[str, str] = {}  # normalized_path -> "V"/"W"/"X"
    self._disc_extraction_verified: Dict[str, bool] = {}  # normalized_path -> True/False
    self._extract_post_cleanup_mode: str | None = None  # 'skip' | 'pkd_out' | 'both'
    self._pending_auto_refresh_roots: List[str] = []

    # Scan worker
    self._scan_thread = None
    self._scan_worker = None

