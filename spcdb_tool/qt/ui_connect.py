# ruff: noqa
from __future__ import annotations

"""Qt signal wiring (internal).

Part of the incremental Qt refactor: keep UI construction and signal wiring separate.

Behavior is intended to be unchanged.
"""


def connect_signals(win) -> None:
    """Connect all persistent UI signals for the given MainWindow instance."""

    # Keep the original variable name used elsewhere to minimize risk.
    self = win

    # ---- Sources: filter + states ----
    try:
        for key, act in (getattr(self, "_src_state_actions", {}) or {}).items():
            try:
                # Default-arg captures key to avoid late-binding.
                act.toggled.connect(lambda _v, _k=key: self._apply_sources_filter())
            except Exception:
                pass
    except Exception:
        pass

    try:
        self.btn_sources_select_shown.clicked.connect(self._select_sources_shown)
    except Exception:
        pass
    try:
        self.btn_sources_clear_sel.clicked.connect(lambda: self.sources_table.clearSelection())
    except Exception:
        pass
    try:
        self.sources_filter_edit.textChanged.connect(lambda _t: self._apply_sources_filter())
    except Exception:
        pass

    # ---- Songs: refresh / bulk ----
    try:
        self.btn_refresh_songs.clicked.connect(self._start_refresh_songs)
    except Exception:
        pass
    try:
        self.btn_select_all_visible.clicked.connect(lambda: self._bulk_select_visible(mode="select"))
        self.btn_clear_visible.clicked.connect(lambda: self._bulk_select_visible(mode="clear"))
        self.btn_invert_visible.clicked.connect(lambda: self._bulk_select_visible(mode="invert"))
    except Exception:
        pass

    # ---- Songs table ----
    try:
        self.songs_table.itemChanged.connect(self._on_song_item_changed)
    except Exception:
        pass

    try:
        # Single-click toggling for the 'On' column (see eventFilter in MainWindow).
        self.songs_table.viewport().installEventFilter(self)
        # Capture keyboard (spacebar) for checkbox toggling.
        self.songs_table.installEventFilter(self)
    except Exception:
        pass


    # ---- Songs filters / view presets ----
    try:
        self.song_search_edit.textChanged.connect(lambda _t: self._apply_song_filter())
        self.song_source_combo.currentIndexChanged.connect(lambda _i: self._apply_song_filter())
        self.song_selected_only_chk.stateChanged.connect(lambda _s: self._apply_song_filter())
    except Exception:
        pass

    try:
        self.song_source_combo.currentIndexChanged.connect(lambda _i: self._update_song_source_combo_tooltip())
    except Exception:
        pass

    try:
        # Remember Qt-only state for these controls.
        self.song_search_edit.textChanged.connect(lambda _t: self._save_qt_state())
        self.song_source_combo.currentIndexChanged.connect(lambda _i: self._save_qt_state())
        self.song_selected_only_chk.stateChanged.connect(lambda _s: self._save_qt_state())
    except Exception:
        pass

    try:
        # View presets (optional).
        self.song_preset_combo.currentIndexChanged.connect(lambda _i: self._apply_preset_from_combo())
    except Exception:
        pass

    # ---- Right panel / actions ----
    try:
        self.btn_validate.clicked.connect(self._start_validate)
        self.btn_extract.clicked.connect(self._start_extract)
        self.btn_build.clicked.connect(self._start_build)
        try:
            self.btn_update_existing.clicked.connect(self._start_update_existing)
        except Exception:
            pass
        self.btn_copy_report.clicked.connect(self._copy_validate_report)
        self.btn_cancel.clicked.connect(self._cancel_active)
    except Exception:
        pass

    # ---- Progress clock ----
    try:
        self._op_clock_timer.timeout.connect(self._tick_op_clock)
    except Exception:
        pass

    # ---- Inspector context hooks ----
    try:
        self.sources_table.itemSelectionChanged.connect(self._update_inspector_context)
        try:
            self.sources_table.itemSelectionChanged.connect(self._maybe_apply_song_filter_from_sources_selection)
        except Exception:
            pass
        try:
            self.sources_table.itemSelectionChanged.connect(self._update_sources_title)
        except Exception:
            pass
    except Exception:
        pass

    try:
        self.songs_table.itemSelectionChanged.connect(self._update_preview_context)
    except Exception:
        pass

    # Update inspector context when key inputs change.
    try:
        self.base_edit.textChanged.connect(lambda _t: self._update_inspector_context())
        self.output_edit.textChanged.connect(lambda _t: self._update_inspector_context())
        self.song_search_edit.textChanged.connect(lambda _t: self._update_inspector_context())
        self.song_source_combo.currentIndexChanged.connect(lambda _i: self._update_inspector_context())
        self.song_selected_only_chk.stateChanged.connect(lambda _s: self._update_inspector_context())
    except Exception:
        pass


    # Overwrite output toggle: enable/disable "keep backup" option.
    try:
        self.chk_allow_overwrite.toggled.connect(lambda v: self.chk_keep_backup.setEnabled(bool(v)))
        self.chk_allow_overwrite.toggled.connect(lambda v: self.chk_keep_backup.setChecked(True) if bool(v) else None)
    except Exception:
        pass
