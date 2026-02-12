"""Right sidebar (Inspector/Actions/Preview) construction helpers.

Split out of qt/main_window.py to keep the MainWindow constructor manageable.No behavior change intended."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt

from PySide6.QtCore import QProcess
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:  # pragma: no cover
    from .main_window import MainWindow


def build_right_panel(self: "MainWindow") -> QScrollArea:
    """Build the right sidebar as a scrollable widget for the main splitter."""
    right = QWidget()
    try:
        right.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
    except Exception:
        pass
    right_v = QVBoxLayout(right)
    try:
        right_v.setContentsMargins(0, 0, 0, 0)
    except Exception:
        pass


    gb_inspector = QGroupBox("Inspector")

    insp_v = QVBoxLayout(gb_inspector)

    self.inspector_title_lbl = QLabel("")
    try:
        self.inspector_title_lbl.setStyleSheet("font-weight: 600;")
    except Exception:
        pass
    try:
        self.inspector_title_lbl.setVisible(False)
    except Exception:
        pass
    insp_v.addWidget(self.inspector_title_lbl)

    # Conflicts (0.7c): show SHA1-mismatch conflicts and allow choosing a winning source.
    self.inspector_conflicts_lbl = QLabel("Conflicts: 0")
    try:
        self.inspector_conflicts_lbl.setToolTip(
            'Conflicts are Song IDs where the underlying files differ between sources.\n'
            'Use Resolve Conflicts… to choose which source should win for each song.'
        )
    except Exception:
        pass

    self.btn_resolve_conflicts = QPushButton("Resolve Conflicts…")
    try:
        self.btn_resolve_conflicts.setToolTip(
            'Open the conflict resolver to pick a winning source for each conflicting song.'
        )
    except Exception:
        pass
    try:
        self.btn_resolve_conflicts.setEnabled(False)
    except Exception:
        pass
    try:
        self.btn_resolve_conflicts.clicked.connect(self._open_conflict_resolver)
    except Exception:
        pass
    row_conf = QHBoxLayout()
    row_conf.addWidget(self.inspector_conflicts_lbl)
    row_conf.addStretch(1)
    row_conf.addWidget(self.btn_resolve_conflicts)
    insp_v.addLayout(row_conf)

    self.inspector_stack = QStackedWidget()

    # Songs context page
    self._inspector_page_songs = QWidget()
    songs_ctx_v = QVBoxLayout(self._inspector_page_songs)
    self.inspector_songs_summary_lbl = QLabel("Songs: 0 | Included: 0")
    try:
        self.inspector_songs_summary_lbl.setToolTip(
            "Dupes = number of Song IDs that appear in more than one source.\n"
            "extra = additional copies hidden (the table shows one row per Song ID).\n"
            "Example: a song in 3 sources -> Dupes=1, extra=2.\n\n"
            "Included = songs with the On checkbox ticked (not just the highlighted row)."
        )
    except Exception:
        pass
    self.inspector_songs_filter_lbl = QLabel("Filters: none")
    try:
        self.inspector_songs_filter_lbl.setToolTip(
            "Filters summarise what is currently limiting the Songs table.\n"
            "This includes Source dropdown, View preset, flags, and Search text."
        )
    except Exception:
        pass
    self.inspector_songs_hint_lbl = QLabel(
        "Tip: click a disc header row to collapse/expand that disc's songs.\n"
        "Select a Source on the left to see source details and Validate/Extract actions."
    )
    try:
        self.inspector_songs_hint_lbl.setWordWrap(True)
    except Exception:
        pass
    songs_ctx_v.addWidget(self.inspector_songs_summary_lbl)
    songs_ctx_v.addWidget(self.inspector_songs_filter_lbl)


    songs_ctx_v.addWidget(self.inspector_songs_hint_lbl)
    songs_ctx_v.addStretch(1)
    self.inspector_stack.addWidget(self._inspector_page_songs)

    # Source context page
    self._inspector_page_source = QWidget()
    src_ctx_v = QVBoxLayout(self._inspector_page_source)
    self.inspector_source_title_lbl = QLabel("Source: -")
    try:
        self.inspector_source_title_lbl.setStyleSheet("font-weight: 600;")
    except Exception:
        pass
    self.inspector_source_path_lbl = QLabel("-")
    self.inspector_source_state_lbl = QLabel("-")
    self.inspector_source_cache_lbl = QLabel("-")

    try:
        self.inspector_source_cache_lbl.setToolTip(
            "Index cache is a saved song index for this disc.\n"
            "ok (matches) = cache matches this disc; stale (will rescan) = disc changed and will be rescanned on Refresh Songs.\n"
            "The songs count is how many entries are in the cached index."
        )
    except Exception:
        pass

    try:
        self.inspector_source_path_lbl.setWordWrap(True)
    except Exception:
        pass

    src_form = QFormLayout()
    src_form.addRow(QLabel("Path:"), self.inspector_source_path_lbl)
    src_form.addRow(QLabel("State:"), self.inspector_source_state_lbl)
    src_form.addRow(QLabel("Index cache:"), self.inspector_source_cache_lbl)
    src_ctx_v.addWidget(self.inspector_source_title_lbl)
    src_ctx_v.addLayout(src_form)
    self.inspector_source_hint_lbl = QLabel("")
    try:
        self.inspector_source_hint_lbl.setWordWrap(True)
    except Exception:
        pass
    src_ctx_v.addWidget(self.inspector_source_hint_lbl)
    src_ctx_v.addStretch(1)
    self.inspector_stack.addWidget(self._inspector_page_source)

    insp_v.addWidget(self.inspector_stack, 1)
    right_v.addWidget(gb_inspector, 2)


    def _make_collapsible_panel(title: str, content: QWidget, expanded: bool = True) -> QGroupBox:
        """Make a bordered panel with a clickable disclosure header (arrow + title)."""
        panel = QGroupBox("")
        outer_l = QVBoxLayout(panel)
        try:
            outer_l.setContentsMargins(6, 6, 6, 6)
            outer_l.setSpacing(6)
        except Exception:
            pass

        hdr = QToolButton()
        hdr.setText(title)
        hdr.setCheckable(True)
        hdr.setChecked(expanded)
        hdr.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        hdr.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        try:
            hdr.setAutoRaise(True)
        except Exception:
            pass
        try:
            hdr.setCursor(Qt.PointingHandCursor)
            hdr.setToolTip("Click to expand/collapse")
        except Exception:
            pass

        try:
            hdr.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        except Exception:
            pass
        try:
            hdr.setStyleSheet("QToolButton{border:1px solid palette(mid); border-radius:6px; font-weight:600; text-align:left; padding:4px;} QToolButton:hover{background: palette(base);}")
        except Exception:
            pass

        outer_l.addWidget(hdr)
        outer_l.addWidget(content)

        content.setVisible(expanded)


        def _on_toggled(chk: bool) -> None:
            content.setVisible(chk)
            hdr.setArrowType(Qt.DownArrow if chk else Qt.RightArrow)

        try:
            hdr.toggled.connect(_on_toggled)
        except Exception:
            pass
        return panel

    act_content = QWidget()
    act_v = QVBoxLayout(act_content)
    try:
        act_v.setContentsMargins(0, 0, 0, 0)
    except Exception:
        pass
    act_v.addWidget(self.btn_validate)
    act_v.addWidget(self.btn_extract)

    gb_actions = _make_collapsible_panel("Source actions", act_content, expanded=False)
    self._gb_source_actions = gb_actions
    right_v.addWidget(gb_actions)

    opt_content = QWidget()
    opt_v = QVBoxLayout(opt_content)
    try:
        opt_v.setContentsMargins(0, 0, 0, 0)
    except Exception:
        pass
    opt_v.addWidget(self.chk_preflight)
    opt_v.addWidget(self.chk_block_build)
    try:
        opt_v.addWidget(self.chk_allow_overwrite)
        opt_v.addWidget(self.chk_keep_backup)
    except Exception:
        pass
    opt_v.addWidget(self.chk_validate_write_report)

    gb_options = _make_collapsible_panel("Quick options", opt_content, expanded=True)
    right_v.addWidget(gb_options)
    gb_branding = QGroupBox("Disc Branding (XMB)")
    br_v = QVBoxLayout(gb_branding)

    br_help = QLabel("Replaces PS3_GAME/ICON0.PNG and PS3_GAME/PIC1.PNG in the built output.")
    try:
        br_help.setWordWrap(True)
    except Exception:
        pass
    br_v.addWidget(br_help)

    row_icon = QHBoxLayout()
    row_icon.addWidget(QLabel("Icon:"))
    row_icon.addWidget(self.disc_icon_path_edit, 1)
    row_icon.addWidget(self.btn_disc_icon_choose)
    row_icon.addWidget(self.btn_disc_icon_clear)
    br_v.addLayout(row_icon)
    br_v.addWidget(self.disc_icon_source_lbl)
    br_v.addWidget(self.disc_icon_preview_lbl)

    row_bg = QHBoxLayout()
    row_bg.addWidget(QLabel("Background:"))
    row_bg.addWidget(self.disc_bg_path_edit, 1)
    row_bg.addWidget(self.btn_disc_bg_choose)
    row_bg.addWidget(self.btn_disc_bg_clear)
    br_v.addLayout(row_bg)
    br_v.addWidget(self.disc_bg_source_lbl)
    br_v.addWidget(self.disc_bg_preview_lbl)
    br_v.addSpacing(10)

    br_v.addWidget(self.chk_disc_branding_autoresize)
    br_v.addWidget(self.chk_disc_branding_apply)
    br_v.addWidget(self.btn_disc_branding_apply_existing)

    right_v.addWidget(gb_branding)


    gb_report = QGroupBox("Report")
    rep_v = QVBoxLayout(gb_report)
    rep_v.addWidget(self.btn_copy_report)
    right_v.addWidget(gb_report)

    gb_progress = QGroupBox("Progress + phase")
    prog_v = QVBoxLayout(gb_progress)
    row_phase = QHBoxLayout()
    row_phase.addWidget(QLabel("Phase:"))
    row_phase.addWidget(self.op_phase_lbl, 1)
    prog_v.addLayout(row_phase)
    row_time = QHBoxLayout()
    row_time.addWidget(QLabel("Elapsed:"))
    row_time.addWidget(self.op_elapsed_lbl)
    row_time.addSpacing(12)
    row_time.addWidget(self.op_eta_title_lbl)
    row_time.addWidget(self.op_eta_lbl)
    row_time.addStretch(1)
    prog_v.addLayout(row_time)
    prog_v.addWidget(self.op_detail_lbl)
    prog_v.addWidget(self.op_progress)
    right_v.addWidget(gb_progress)

    # ---- Preview (external player) ----
    gb_preview = QGroupBox("Preview")
    prev_v = QVBoxLayout(gb_preview)

    self.preview_song_lbl = QLabel("Song: (select a song)")
    try:
        self.preview_song_lbl.setToolTip("Select a song in the Songs table to enable preview.")
    except Exception:
        pass
    try:
        self.preview_song_lbl.setWordWrap(True)
    except Exception:
        pass
    prev_v.addWidget(self.preview_song_lbl)

    row_start = QHBoxLayout()
    row_start.addWidget(QLabel("Start:"))
    self.preview_start_combo = QComboBox()
    self.preview_start_combo.addItems(["MedleyNormalBegin", "MedleyMicroBegin", "First lyric note", "Start of song"])
    try:
        self.preview_start_combo.setToolTip(
            "Where preview starts. Uses melody_1.xml markers when available.\n"
            "• MedleyNormalBegin / MedleyMicroBegin: medley markers\n"
            "• First lyric note: first lyric NOTE in melody\n"
            "• Start of song: 00:00"
        )
    except Exception:
        pass
    row_start.addWidget(self.preview_start_combo, 1)
    prev_v.addLayout(row_start)

    row_clip = QHBoxLayout()
    row_clip.addWidget(QLabel("Clip:"))
    self.preview_clip_combo = QComboBox()
    self.preview_clip_combo.addItems(["Auto", "Medley segment (Begin -> End)", "20 seconds", "Full track"])
    try:
        self.preview_clip_combo.setToolTip(
            "How much to preview.\n"
            "• Auto: ~20 seconds\n"
            "• Medley segment: Begin → End markers (fallback ~20s)\n"
            "• 20 seconds: fixed length\n"
            "• Full track: no end limit"
        )
    except Exception:
        pass
    row_clip.addWidget(self.preview_clip_combo, 1)
    prev_v.addLayout(row_clip)

    row_btn = QHBoxLayout()
    self.btn_preview = QPushButton("Preview")
    try:
        self.btn_preview.setToolTip(
            "Play the selected song in an external player (mpv/ffplay if installed).\n"
            "Requires the source to be extracted (Export folder present)."
        )
    except Exception:
        pass
    self.btn_preview_stop = QPushButton("Stop")
    try:
        self.btn_preview_stop.setToolTip("Stop the external preview player.")
    except Exception:
        pass
    row_btn.addWidget(self.btn_preview)
    row_btn.addWidget(self.btn_preview_stop)
    prev_v.addLayout(row_btn)

    self.preview_status_lbl = QLabel("")
    try:
        self.preview_status_lbl.setWordWrap(True)
    except Exception:
        pass
    prev_v.addWidget(self.preview_status_lbl)

    right_v.addWidget(gb_preview)

    # Preview process handle
    self._preview_proc = QProcess(self)
    self._preview_time_cache = {}
    try:
        self._preview_proc.finished.connect(lambda *_a: self._preview_on_finished())
    except Exception:
        pass
    try:
        self._preview_proc.errorOccurred.connect(lambda *_a: self._preview_on_error())
    except Exception:
        pass

    try:
        self.btn_preview.clicked.connect(lambda: self._preview_start())
        self.btn_preview_stop.clicked.connect(self._preview_stop)
        self.preview_start_combo.currentIndexChanged.connect(lambda _i: self._update_preview_context())
        self.preview_clip_combo.currentIndexChanged.connect(lambda _i: self._update_preview_context())
    except Exception:
        pass

    try:
        self._update_preview_context()
    except Exception:
        pass


    right_v.addStretch(1)

    # Save button (also available in File menu)
    self.btn_save_settings = QPushButton("Save Settings")
    self.btn_save_settings.clicked.connect(self._save_from_ui)

    # Disc Branding (XMB) wiring
    try:
        self.btn_disc_icon_choose.clicked.connect(self._choose_disc_branding_icon)
        self.btn_disc_icon_clear.clicked.connect(self._clear_disc_branding_icon)
        self.btn_disc_bg_choose.clicked.connect(self._choose_disc_branding_background)
        self.btn_disc_bg_clear.clicked.connect(self._clear_disc_branding_background)
        self.chk_disc_branding_autoresize.toggled.connect(lambda _v: self._save_disc_branding_settings())
        self.chk_disc_branding_apply.toggled.connect(lambda _v: self._save_disc_branding_settings())
        self.btn_disc_branding_apply_existing.clicked.connect(self._apply_disc_branding_to_existing_output)
    except Exception:
        pass

    right_v.addWidget(self.btn_save_settings)


    # Status bar hints (hover): preview controls.
    try:
        self.preview_start_combo.setStatusTip('Preview start offset (seconds).')
        self.preview_clip_combo.setStatusTip('Preview clip length.')
        self.btn_preview.setStatusTip('Play preview clip.')
        self.btn_preview_stop.setStatusTip('Stop preview.')
    except Exception:
        pass

    right_scroll = QScrollArea()
    try:
        right_scroll.setWidgetResizable(True)
        right_scroll.setFrameShape(QFrame.NoFrame)
        right_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    except Exception:
        pass

    try:
        right.setMinimumWidth(0)
        right_scroll.setMinimumWidth(0)
        right_scroll.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Expanding)
    except Exception:
        pass


    right_scroll.setWidget(right)

    return right_scroll
