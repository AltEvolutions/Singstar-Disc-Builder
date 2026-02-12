# ruff: noqa
from __future__ import annotations

"""Qt MainWindow (internal).

Extracted from `spcdb_tool/qt_app.py` as part of the incremental Qt refactor.
Behavior is intended to be unchanged.

This module is imported lazily from `spcdb_tool.qt_app.run_qt_gui()`.
"""

import logging
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .. import __version__ as APP_VERSION
from ..controller import (
    SongAgg,
    _load_settings,
    _save_settings,
    clear_index_cache,
)
from ..util import ensure_default_extractor_dir, detect_default_extractor_exe

from .conflicts_dialog import ConflictResolverDialog
from .about_dialog import show_about_dialog
from .branding import (
    disc_branding_base_asset_path,
    update_disc_branding_ui,
    save_disc_branding_settings,
    write_branding_png,
    apply_disc_branding_to_output,
)

from .layout import capture_ui_layout, apply_ui_layout
from .sources_panel import build_sources_panel
from .songs_panel import build_songs_panel
from .right_panel import build_right_panel
from .menus import build_main_menus
from .ui_create import create_widgets
from .ui_connect import connect_signals
from .ui_helpers import (
    fmt_duration as _fmt_duration_impl,
    open_logs_folder as _open_logs_folder_impl,
    show_msg_with_logs as _show_msg_with_logs_impl,
    show_critical_with_logs as _show_critical_with_logs_impl,
    show_warning_with_logs as _show_warning_with_logs_impl,
    browse_base as _browse_base_impl,
    browse_output as _browse_output_impl,
    browse_extractor as _browse_extractor_impl,
    qt_state_path as _qt_state_path_impl,
)
from .ui_state import (
    install_window_state_tracker as _install_window_state_tracker_impl,
    apply_default_window_geometry as _apply_default_window_geometry_impl,
    clamp_to_screen as _clamp_to_screen_impl,
    current_song_refresh_key as _current_song_refresh_key_impl,
    load_qt_state_into_ui as _load_qt_state_into_ui_impl,
    save_qt_state as _save_qt_state_impl,
)
from .ui_progress import (
    start_op_clock as _start_op_clock_impl,
    stop_op_clock as _stop_op_clock_impl,
    tick_op_clock as _tick_op_clock_impl,
    eta_full_key as _eta_full_key_impl,
    eta_record_phase_sample as _eta_record_phase_sample_impl,
    eta_track_phase as _eta_track_phase_impl,
    eta_finalize_phase_tracking as _eta_finalize_phase_tracking_impl,
    render_eta_indeterminate as _render_eta_indeterminate_impl,
    update_eta_state as _update_eta_state_impl,
    render_eta as _render_eta_impl,
    reset_progress_ui as _reset_progress_ui_impl,
    set_progress_ui as _set_progress_ui_impl,
    map_build_phase_group as _map_build_phase_group_impl,
    handle_structured_progress as _handle_structured_progress_impl,
)
from .ui_ops import (
    collect_validate_targets as _collect_validate_targets_impl,
    start_validate as _start_validate_impl,
    cancel_active as _cancel_active_impl,
    cleanup_validate as _cleanup_validate_impl,
    write_validate_report_file as _write_validate_report_file_impl,
    on_validate_done as _on_validate_done_impl,
    on_validate_cancelled as _on_validate_cancelled_impl,
    on_validate_error as _on_validate_error_impl,
    copy_validate_report as _copy_validate_report_impl,
    collect_extract_targets as _collect_extract_targets_impl,
    collect_packed_extract_targets as _collect_packed_extract_targets_impl,
    start_extract_targets as _start_extract_targets_impl,
    start_extract_packed_only as _start_extract_packed_only_impl,
    start_extract as _start_extract_impl,
    cleanup_extract as _cleanup_extract_impl,
    on_extract_done as _on_extract_done_impl,
    on_extract_cancelled as _on_extract_cancelled_impl,
    on_extract_error as _on_extract_error_impl,
    start_build as _start_build_impl,
    start_update_existing as _start_update_existing_impl,
    cleanup_build as _cleanup_build_impl,
    on_preflight_report as _on_preflight_report_impl,
    on_build_done as _on_build_done_impl,
    on_build_cancelled as _on_build_cancelled_impl,
    on_build_blocked as _on_build_blocked_impl,
    on_build_error as _on_build_error_impl,
)

from .ui_cleanup import (
    start_cleanup_targets as _start_cleanup_targets_impl,
    cleanup_cleanup as _cleanup_cleanup_impl,
    on_cleanup_tool_done as _on_cleanup_tool_done_impl,
    on_cleanup_tool_cancelled as _on_cleanup_tool_cancelled_impl,
    on_cleanup_tool_error as _on_cleanup_tool_error_impl,
    confirm_permanent_delete_cleanup as _confirm_permanent_delete_cleanup_impl,
    cleanup_pkd_artifacts_action as _cleanup_pkd_artifacts_action_impl,
    cleanup_cleanup_scan as _cleanup_cleanup_scan_impl,
    cleanup_cleanup_preview as _cleanup_cleanup_preview_impl,
    on_cleanup_preview_progress_cancelled as _on_cleanup_preview_progress_cancelled_impl,
    start_cleanup_preview as _start_cleanup_preview_impl,
    show_cleanup_preview_confirm_dialog as _show_cleanup_preview_confirm_dialog_impl,
    on_cleanup_preview_done as _on_cleanup_preview_done_impl,
    on_cleanup_preview_cancelled as _on_cleanup_preview_cancelled_impl,
    on_cleanup_preview_error as _on_cleanup_preview_error_impl,
    on_cleanup_scan_done_worker as _on_cleanup_scan_done_worker_impl,
    on_cleanup_scan_cancelled as _on_cleanup_scan_cancelled_impl,
    on_cleanup_scan_error as _on_cleanup_scan_error_impl,
    on_cleanup_scan_done as _on_cleanup_scan_done_impl,
    on_cleanup_done as _on_cleanup_done_impl,
    on_cleanup_cancelled as _on_cleanup_cancelled_impl,
    on_cleanup_error as _on_cleanup_error_impl,
)

from .ui_songs_table import (
    render_songs_table as _render_songs_table_impl,
    update_group_header_states as _update_group_header_states_impl,
    toggle_disc_group_all as _toggle_disc_group_all_impl,
    toggle_song_group as _toggle_song_group_impl,
    songs_event_filter as _songs_event_filter_impl,
    on_song_item_changed as _on_song_item_changed_impl,
    bulk_select_visible as _bulk_select_visible_impl,
    update_song_status as _update_song_status_impl,
)

from .ui_songs_flow import (
    collect_song_targets as _collect_song_targets_impl,
    auto_refresh_songs_for_roots as _auto_refresh_songs_for_roots_impl,
    start_refresh_songs as _start_refresh_songs_impl,
    cleanup_songs as _cleanup_songs_impl,
    on_songs_done as _on_songs_done_impl,
    on_songs_cancelled as _on_songs_cancelled_impl,
    on_songs_error as _on_songs_error_impl,
)


from .ui_filters_presets import (
    base_disc_folder_name as _base_disc_folder_name_impl,
    display_label_for_source as _display_label_for_source_impl,
    normalize_source_key as _normalize_source_key_impl,
    song_source_filter_key as _song_source_filter_key_impl,
    selected_source_labels_for_filter as _selected_source_labels_for_filter_impl,
    update_song_source_combo_tooltip as _update_song_source_combo_tooltip_impl,
    commit_song_source_combo_edit as _commit_song_source_combo_edit_impl,
    maybe_apply_song_filter_from_sources_selection as _maybe_apply_song_filter_from_sources_selection_impl,
    refresh_song_source_combo as _refresh_song_source_combo_impl,
    builtin_presets as _builtin_presets_impl,
    rebuild_preset_combo as _rebuild_preset_combo_impl,
    set_preset_combo_to_name as _set_preset_combo_to_name_impl,
    current_filter_payload as _current_filter_payload_impl,
    apply_filter_payload as _apply_filter_payload_impl,
    apply_preset_from_combo as _apply_preset_from_combo_impl,
    apply_song_filter as _apply_song_filter_impl,
)

from .ui_sources_table import (
    update_sources_title as _update_sources_title_impl,
    sources_filter_active as _sources_filter_active_impl,
    source_state_category as _source_state_category_impl,
    apply_sources_filter as _apply_sources_filter_impl,
    select_sources_shown as _select_sources_shown_impl,
    norm_key as _norm_key_impl,
    compute_disc_state as _compute_disc_state_impl,
    apply_source_row_decor as _apply_source_row_decor_impl,
    refresh_source_states as _refresh_source_states_impl,
    add_source_path as _add_source_path_impl,
    clear_sources as _clear_sources_impl,
    cleanup_scan as _cleanup_scan_impl,
    on_scan_done as _on_scan_done_impl,
    on_scan_cancelled as _on_scan_cancelled_impl,
    on_scan_error as _on_scan_error_impl,
    scan_sources_root as _scan_sources_root_impl,
    add_source as _add_source_impl,
    remove_selected_sources as _remove_selected_sources_impl,
)

from .ui_inspector import (
    update_inspector_context as _update_inspector_context_impl,
    pv_strip_ns as _pv_strip_ns_impl,
    pv_int as _pv_int_impl,
    pv_resolution_beats as _pv_resolution_beats_impl,
    pv_unit_seconds as _pv_unit_seconds_impl,
    pv_extract_times as _pv_extract_times_impl,
    pv_fmt as _pv_fmt_impl,
    pv_find_song_dir as _pv_find_song_dir_impl,
    pv_scan_media as _pv_scan_media_impl,
    pv_selected_song_id as _pv_selected_song_id_impl,
    pv_selected_label as _pv_selected_label_impl,
    pv_choose_window as _pv_choose_window_impl,
    pv_choose_start as _pv_choose_start_impl,
    update_preview_context as _update_preview_context_impl,
    pv_player_cmd as _pv_player_cmd_impl,
    preview_start as _preview_start_impl,
    preview_stop as _preview_stop_impl,
    preview_on_finished as _preview_on_finished_impl,
    preview_on_error as _preview_on_error_impl,
)

from .ui_reset import (
    reset_ui_state_action as _reset_ui_state_action_impl,
    apply_default_ui_splitters as _apply_default_ui_splitters_impl,
    apply_default_ui_columns as _apply_default_ui_columns_impl,
    reset_layout_action as _reset_layout_action_impl,
    reset_columns_action as _reset_columns_action_impl,
)

from .ui_support_bundle import (
    export_support_bundle_action as _export_support_bundle_action_impl,
)

from .ui_copy_disc import (
    first_available_outdir as _first_available_outdir_impl,
    start_copy_disc as _start_copy_disc_impl,
)

_FILELOG = logging.getLogger("spcdb_tool.gui")




class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"SingStar Disc Builder v{APP_VERSION}")
        # Initial window sizing is applied at show-time based on the current screen.

        # Window geometry persistence (Qt-only). Stored in the qt state JSON.
        self._qt_window_geometry_loaded: bool = False
        self._qt_window_was_maximized: bool = False

        self._loading = True

        # ---- widgets ----
        create_widgets(self)

        # ---- layout ----
        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)

        # Main 3-column layout (Layout D)
        main_split = QSplitter(Qt.Horizontal)
        try:
            main_split.setHandleWidth(8)
        except Exception:
            pass
        self._main_split = main_split
        outer.addWidget(main_split, 1)

        # ---------- Left: Sources + global paths ----------
        left = build_sources_panel(self)
        self._left_panel = left
        self._left_sidebar_visible = True
        self._left_sidebar_sizes_before_hide = None
        main_split.addWidget(left)

        # ---------- Center: Songs + Log ----------
        center = build_songs_panel(self)
        main_split.addWidget(center)

        # ---------- Right: Inspector / Actions ----------
        right_scroll = build_right_panel(self)
        self._right_scroll = right_scroll
        self._right_sidebar_visible = True
        self._right_sidebar_sizes_before_hide = None
        main_split.addWidget(right_scroll)

        # Initial sizing: center dominates
        try:
            main_split.setStretchFactor(0, 0)
            main_split.setStretchFactor(1, 1)
            main_split.setStretchFactor(2, 0)
            main_split.setSizes([320, 760, 320])
        except Exception:
            pass
        # Signal wiring (R18)
        try:
            connect_signals(self)
        except Exception:
            pass

        # Track window geometry/state continuously so close/save can't capture bogus values.
        try:
            _install_window_state_tracker_impl(self)
        except Exception:
            pass

        # Menu
        try:
            build_main_menus(self)
        except Exception:
            pass

        # Load settings
        self._load_into_ui()
        # Load Qt-only state (song selection + filters)
        try:
            self._load_qt_state_into_ui()
        except Exception:
            pass
        self._loading = False
        self._log("Qt UI loaded settings.")
        try:
            self._update_inspector_context()
        except Exception:
            pass

        # Auto-refresh song catalog on startup (v0.8g)
        # If Base is set, refresh immediately so the user sees songs without manual action.
        # Startup refresh is allowed to do a full parse (not cache-only), but still skips packed/unextracted discs.
        # Note: Sources may be empty; Base-only setups should still populate the catalog from cache/parse.
        try:
            if self.base_edit.text().strip():
                QTimer.singleShot(0, lambda: self._start_refresh_songs(auto=True, startup=True))
        except Exception:
            pass

    # ---- UI helpers ----

    def showEvent(self, event) -> None:  # noqa: N802
            """First-show hook: restore or choose a sane window geometry.
    
            v0.9.128+ uses a dedicated, robust window state file with a simple rect + maximized flag.
            This avoids flaky saveGeometry()/restoreGeometry() behavior on some Windows setups.
            """
            try:
                super().showEvent(event)
            except Exception:
                pass
    
            try:
                if getattr(self, "_did_first_show", False):
                    return
                self._did_first_show = True
            except Exception:
                return
    
            applied = False
            try:
                from .window_state import apply_window_state_on_first_show
                applied = bool(apply_window_state_on_first_show(self))
            except Exception:
                applied = False
    
            # If no saved window state exists, apply a sensible default (but don't fight maximize).
            if not applied:
                try:
                    if not bool(self.isMaximized()):
                        self._apply_default_window_geometry()
                except Exception:
                    pass
    

    def _apply_default_window_geometry(self) -> None:
        _apply_default_window_geometry_impl(self)

    def _clamp_to_screen(self) -> None:
        _clamp_to_screen_impl(self)

    def _fmt_duration(self, secs: float) -> str:
        return _fmt_duration_impl(secs)
    def _start_op_clock(self) -> None:
        _start_op_clock_impl(self)

    def _stop_op_clock(self) -> None:
        _stop_op_clock_impl(self)

    def _tick_op_clock(self) -> None:
        _tick_op_clock_impl(self)

    def _eta_full_key(self, phase: str) -> str:
        return _eta_full_key_impl(self, phase)

    def _eta_record_phase_sample(self, key: str, duration_sec: float) -> None:
        _eta_record_phase_sample_impl(self, key, duration_sec)

    def _eta_track_phase(self, phase: str) -> None:
        _eta_track_phase_impl(self, phase)

    def _eta_finalize_phase_tracking(self) -> None:
        _eta_finalize_phase_tracking_impl(self)

    def _render_eta_indeterminate(self) -> None:
        _render_eta_indeterminate_impl(self)

    def _update_eta_state(
        self,
        *,
        phase: str,
        current: Optional[int],
        total: Optional[int],
        indeterminate: bool,
    ) -> None:
        _update_eta_state_impl(
            self,
            phase=str(phase or ''),
            current=current,
            total=total,
            indeterminate=bool(indeterminate),
        )

    def _render_eta(self) -> None:
        _render_eta_impl(self)

    def _reset_progress_ui(self) -> None:
        _reset_progress_ui_impl(self)

    def _update_inspector_context(self) -> None:
        _update_inspector_context_impl(self)


    def _apply_song_source_overrides(self, songs: List[SongAgg]) -> List[SongAgg]:
        """Apply persisted per-song winner overrides to the catalog.

        Overrides are only applied when the overridden label is actually present in the song's sources.
        Any stale overrides are pruned.
        """
        try:
            ov = dict(self._song_source_overrides or {})
        except Exception:
            ov = {}
        if not ov:
            return list(songs or [])

        out: List[SongAgg] = []
        pruned: Dict[int, str] = {}

        for s in (songs or []):
            try:
                sid = int(getattr(s, 'song_id', 0) or 0)
            except Exception:
                out.append(s)
                continue
            try:
                srcs = tuple(getattr(s, 'sources', ()) or ())
            except Exception:
                srcs = ()

            try:
                wanted = str(ov.get(int(sid), '') or '').strip()
            except Exception:
                wanted = ''

            try:
                cur_pref = str(getattr(s, 'preferred_source', '') or '')
            except Exception:
                cur_pref = ''

            if wanted and (wanted in srcs):
                pref = wanted
                pruned[int(sid)] = wanted
            else:
                pref = cur_pref

            if pref != cur_pref:
                try:
                    out.append(
                        SongAgg(
                            song_id=int(sid),
                            title=str(getattr(s, 'title', '') or ''),
                            artist=str(getattr(s, 'artist', '') or ''),
                            preferred_source=str(pref),
                            sources=tuple(srcs),
                        )
                    )
                except Exception:
                    out.append(s)
            else:
                out.append(s)

        try:
            self._song_source_overrides = dict(pruned)
        except Exception:
            pass
        return out

    def _open_conflict_resolver(self) -> None:
        try:
            conflicts = dict(self._song_conflicts or {})
        except Exception:
            conflicts = {}

        if not conflicts:
            QMessageBox.information(self, "Conflicts", "No conflicts detected.")
            return

        try:
            cur_ov = dict(self._song_source_overrides or {})
        except Exception:
            cur_ov = {}

        dlg = ConflictResolverDialog(self, conflicts=conflicts, overrides=cur_ov, export_roots_by_label=dict(getattr(self, '_export_roots_by_label', {}) or {}))
        res = dlg.exec()
        try:
            accepted = int(res) == int(QDialog.Accepted)
        except Exception:
            accepted = True

        if not accepted:
            return

        try:
            new_ov = dlg.overrides() or {}
            clean: Dict[int, str] = {}
            for k, v in (new_ov or {}).items():
                try:
                    sid = int(k)
                except Exception:
                    continue
                lab = str(v or '').strip()
                if lab:
                    clean[int(sid)] = lab
            self._song_source_overrides = clean
        except Exception:
            pass

        # Re-apply overrides to the current catalog and re-render.
        try:
            self._songs_all = self._apply_song_source_overrides(self._songs_all_raw)
            self._songs_by_id = {int(s.song_id): s for s in (self._songs_all or [])}
        except Exception:
            pass
        try:
            self._apply_song_filter()
        except Exception:
            pass
        try:
            self._save_qt_state(force=True)
        except Exception:
            pass
        try:
            self._update_inspector_context()
        except Exception:
            pass



    def _set_progress_ui(
        self,
        *,
        phase: str,
        detail: str = "",
        current: Optional[int] = None,
        total: Optional[int] = None,
        indeterminate: bool = False,
    ) -> None:
        _set_progress_ui_impl(
            self,
            phase=str(phase or ''),
            detail=str(detail or ''),
            current=current,
            total=total,
            indeterminate=bool(indeterminate),
        )

    def _map_build_phase_group(self, raw_phase: str) -> str:
        return _map_build_phase_group_impl(str(raw_phase or ''))

    def _handle_structured_progress(self, payload_text: str) -> None:
        _handle_structured_progress_impl(self, payload_text)

    def _log(self, msg: str) -> None:
        s = str(msg or "")

        # Mirror UI log to file logs (if logging was initialised).
        try:
            if s.startswith("@@PROGRESS "):
                _FILELOG.debug(s)
            else:
                _FILELOG.info(s)
        except Exception:
            pass

        # Build progress (subset.py emits structured progress as @@PROGRESS JSON)
        if s.startswith("@@PROGRESS "):
            self._handle_structured_progress(s[len("@@PROGRESS ") :])
            return

        # Heuristics for build preflight phase.
        if self._active_op == "build":
            if s.startswith("[preflight]"):
                self._set_progress_ui(phase="Preflight", detail=s[len("[preflight]") :].strip(), indeterminate=True)

        self.log_edit.append(s)



    def _open_logs_folder(self) -> None:
        _open_logs_folder_impl()
    def _show_msg_with_logs(
        self,
        title: str,
        text: str,
        *,
        icon: str = 'critical',
        tip: str | None = None,
        details: str | None = None,
    ) -> None:
        _show_msg_with_logs_impl(
            self,
            self._open_logs_folder,
            title,
            text,
            icon=icon,
            tip=tip,
            details=details,
        )
    def _show_critical_with_logs(self, title: str, text: str, *, tip: str | None = None, details: str | None = None) -> None:
        _show_critical_with_logs_impl(self, self._open_logs_folder, title, text, tip=tip, details=details)
    def _show_warning_with_logs(self, title: str, text: str, *, tip: str | None = None, details: str | None = None) -> None:
        _show_warning_with_logs_impl(self, self._open_logs_folder, title, text, tip=tip, details=details)
    def _collect_validate_targets(self) -> List[tuple[str, str]]:
        return _collect_validate_targets_impl(self)

    def _any_op_running(self) -> bool:
        return bool(self._busy) or (self._validate_thread is not None) or (self._extract_thread is not None) or (self._cleanup_thread is not None) or (self._build_thread is not None) or (self._songs_thread is not None) or (self._scan_thread is not None) or (self._copy_thread is not None) or (getattr(self, "_cleanup_scan_thread", None) is not None)

    def _set_op_running(self, running: bool) -> None:
        self._busy = bool(running)

        try:
            if bool(running):
                if getattr(self, '_op_start_ts', None) is None:
                    self._start_op_clock()
            else:
                self._stop_op_clock()
        except Exception:
            pass

        # Core actions
        self.btn_validate.setEnabled(not running)
        self.btn_extract.setEnabled(not running)
        self.btn_build.setEnabled(not running)
        try:
            self.btn_update_existing.setEnabled(not running)
        except Exception:
            pass
        try:
            _has_report = bool(str(getattr(self, "_last_validate_report_text", "") or "").strip())
        except Exception:
            _has_report = False
        self.btn_copy_report.setEnabled((not running) and _has_report)
        self.btn_cancel.setEnabled(bool(running) or self._any_op_running())

        # Base / Output / Extractor
        self.base_edit.setEnabled(not running)
        self.output_edit.setEnabled(not running)
        self.extractor_edit.setEnabled(not running)
        for attr in ("btn_browse_base", "btn_browse_output", "btn_browse_extractor"):
            try:
                w = getattr(self, attr, None)
                if w is not None:
                    w.setEnabled(not running)
            except Exception:
                pass

        # Sources
        try:
            self.sources_table.setEnabled(not running)
        except Exception:
            pass
        for attr in ("btn_add_discs", "btn_remove_sources", "btn_clear_sources"):
            try:
                w = getattr(self, attr, None)
                if w is not None:
                    w.setEnabled(not running)
            except Exception:
                pass

        for attr in ("sources_filter_edit", "btn_sources_states", "btn_sources_select_shown", "btn_sources_clear_sel"):

            try:

                w = getattr(self, attr, None)

                if w is not None:

                    w.setEnabled(not running)

            except Exception:

                pass


        # Toggles + save/settings
        try:
            self.chk_validate_write_report.setEnabled(not running)
            self.chk_preflight.setEnabled(not running)
            self.chk_block_build.setEnabled(not running)
            try:
                self.chk_allow_overwrite.setEnabled(not running)
                self.chk_keep_backup.setEnabled(bool((not running) and self.chk_allow_overwrite.isChecked()))
            except Exception:
                pass
        except Exception:
            pass
        try:
            if getattr(self, "btn_save_settings", None) is not None:
                self.btn_save_settings.setEnabled(not running)
        except Exception:
            pass
        try:
            self.menuBar().setEnabled(not running)
        except Exception:
            pass

        # Songs UI
        self.btn_refresh_songs.setEnabled(not running)
        self.btn_select_all_visible.setEnabled(not running)
        self.btn_clear_visible.setEnabled(not running)
        self.btn_invert_visible.setEnabled(not running)
        self.song_search_edit.setEnabled(not running)
        self.song_source_combo.setEnabled(not running)
        self.song_selected_only_chk.setEnabled(not running)
        try:
            self.songs_table.setEnabled(not running)
        except Exception:
            pass

        if running:
            # Avoid stale copy-report during a new run; re-enable once a new report is produced.
            self.btn_copy_report.setEnabled(False)

            # Give immediate phase feedback; structured @@PROGRESS will refine this during Build.
            if self._active_op == "validate":
                self._set_progress_ui(phase="Validate", detail="Running...", indeterminate=True)
            elif self._active_op == "extract":
                self._set_progress_ui(phase="Extract", detail="Running...", indeterminate=True)
            elif self._active_op == "songs":
                self._set_progress_ui(phase="Index", detail="Refreshing songs...", indeterminate=True)
            elif self._active_op == "scan":
                self._set_progress_ui(phase="Scan", detail="Scanning for discs...", indeterminate=True)
            elif self._active_op == "build":
                ph = "Preflight" if bool(self.chk_preflight.isChecked()) else "Copy"
                self._set_progress_ui(phase=ph, detail="Starting...", indeterminate=True)
            else:
                self._set_progress_ui(phase="Running", detail="...", indeterminate=True)
        else:
            self._reset_progress_ui()

    def _start_validate(self) -> None:
        _start_validate_impl(self)

    def _cancel_active(self) -> None:
        _cancel_active_impl(self)

    def _cleanup_validate(self) -> None:
        _cleanup_validate_impl(self)

    def _write_validate_report_file(self, report_text: str) -> str:
        return _write_validate_report_file_impl(self, report_text)

    def _on_validate_done(self, report_text: str, results: object) -> None:
        _on_validate_done_impl(self, report_text, results)

    def _on_validate_cancelled(self) -> None:
        _on_validate_cancelled_impl(self)

    def _on_validate_error(self, msg: str) -> None:
        _on_validate_error_impl(self, msg)

    def _copy_validate_report(self) -> None:
        _copy_validate_report_impl(self)

    def _qt_state_path(self) -> Path:
        return _qt_state_path_impl()
    def _capture_ui_layout(self) -> dict:
        return capture_ui_layout(self)

    def _apply_ui_layout(self, layout: dict) -> None:
        apply_ui_layout(self, layout)



    def _current_song_refresh_key(self) -> str:
        return _current_song_refresh_key_impl(self)

    def _load_qt_state_into_ui(self) -> None:
        _load_qt_state_into_ui_impl(self)

    def _save_qt_state(self, force: bool = False) -> None:
        # During startup load, widget setters can fire signals that would otherwise
        # overwrite the persisted Qt state (including window geometry/maximize).
        try:
            if bool(getattr(self, "_loading", False)):
                return
        except Exception:
            pass
        _save_qt_state_impl(self, force=force)


    def _base_disc_folder_name(self) -> str:
        return _base_disc_folder_name_impl(self)



    def _display_label_for_source(self, label: str) -> str:
        return _display_label_for_source_impl(self, label)



    def _normalize_source_key(self, val: str) -> str:
        return _normalize_source_key_impl(self, val)



    def _song_source_filter_key(self) -> str:
        return _song_source_filter_key_impl(self)



    def _selected_source_labels_for_filter(self) -> Set[str]:
        return _selected_source_labels_for_filter_impl(self)



    def _update_song_source_combo_tooltip(self) -> None:
        return _update_song_source_combo_tooltip_impl(self)



    def _commit_song_source_combo_edit(self) -> None:
        return _commit_song_source_combo_edit_impl(self)



    def _maybe_apply_song_filter_from_sources_selection(self) -> None:
        return _maybe_apply_song_filter_from_sources_selection_impl(self)


    def _is_base_row(self, row: int) -> bool:
        return int(row) == 0

    def _ensure_base_row(self) -> None:
        """Ensure the Base Disc is present as row 0 in the Sources table."""
        try:
            base_path = self.base_edit.text().strip()
        except Exception:
            base_path = ""

        # Ensure at least one row exists
        try:
            if self.sources_table.rowCount() <= 0:
                self.sources_table.insertRow(0)
        except Exception:
            try:
                self.sources_table.setRowCount(1)
            except Exception:
                return

        # Column 0: label
        try:
            base_label = "BASE DISC"
            if base_path:
                try:
                    base_label = f"{Path(str(base_path)).name} (Base Disc)"
                except Exception:
                    base_label = f"{str(base_path)} (Base Disc)"
            it0 = self.sources_table.item(0, 0)
            if it0 is None:
                it0 = QTableWidgetItem(str(base_label))
                self.sources_table.setItem(0, 0, it0)
            else:
                it0.setText(str(base_label))
            try:
                f = it0.font()
                f.setBold(True)
                it0.setFont(f)
            except Exception:
                pass
        except Exception:
            return

        # Column 2: path (0.8e)
        try:
            itp = self.sources_table.item(0, 2)
            if itp is None:
                itp = QTableWidgetItem(str(base_path))
                self.sources_table.setItem(0, 2, itp)
            else:
                itp.setText(str(base_path))
        except Exception:
            pass

        # Column 1: state (0.8e)
        try:
            state = self._compute_disc_state(str(base_path))
            its = self.sources_table.item(0, 1)
            if its is None:
                its = QTableWidgetItem(str(state))
                try:
                    its.setTextAlignment(Qt.AlignCenter)
                except Exception:
                    pass
                self.sources_table.setItem(0, 1, its)
            else:
                its.setText(str(state))
                try:
                    its.setTextAlignment(Qt.AlignCenter)
                except Exception:
                    pass
        except Exception:
            pass

        # Lock Base row cells from editing (still selectable for Inspector)
        try:
            flags = Qt.ItemIsSelectable | Qt.ItemIsEnabled
            for c in range(3):
                it = self.sources_table.item(0, c)
                if it is not None:
                    it.setFlags(flags)
        except Exception:
            pass
        # Apply row tinting (base row is green)
        try:
            state_txt = str(state)
        except Exception:
            state_txt = ""
        try:
            self._apply_source_row_decor(0, state_txt)
        except Exception:
            pass

    def _on_base_changed(self) -> None:
        if bool(getattr(self, "_loading", False)):
            return
        try:
            self._ensure_base_row()
            self._update_sources_title()
            self._refresh_source_states()
        except Exception:
            pass
        try:
            self._update_disc_branding_ui()
        except Exception:
            pass
        # Best-effort: keep songs view in sync with base changes
        try:
            self._start_refresh_songs(auto=True)
        except Exception:
            pass


    def _collect_song_targets(self) -> List[tuple[str, str, bool]]:
        return _collect_song_targets_impl(self)

    def _auto_refresh_songs_for_roots(self, disc_roots: List[str]) -> None:
        _auto_refresh_songs_for_roots_impl(self, disc_roots)

    def _start_refresh_songs(self, auto: bool = False, *, only_extracted: bool = False, startup: bool = False) -> None:
        _start_refresh_songs_impl(self, auto=auto, only_extracted=only_extracted, startup=startup)

    def _cleanup_songs(self) -> None:
        _cleanup_songs_impl(self)

    def _on_songs_done(self, songs_out: object, disc_song_ids_by_label: object, export_roots_by_label: object, conflicts_by_song_id: object) -> None:
        _on_songs_done_impl(self, songs_out, disc_song_ids_by_label, export_roots_by_label, conflicts_by_song_id)

    def _on_songs_cancelled(self) -> None:
        _on_songs_cancelled_impl(self)

    def _on_songs_error(self, msg: str) -> None:
        _on_songs_error_impl(self, msg)


    def _refresh_song_source_combo(self) -> None:
        return _refresh_song_source_combo_impl(self)



    def _builtin_presets(self) -> Dict[str, dict]:
        return _builtin_presets_impl(self)



    def _rebuild_preset_combo(self) -> None:
        return _rebuild_preset_combo_impl(self)



    def _set_preset_combo_to_name(self, name: str) -> None:
        return _set_preset_combo_to_name_impl(self, name)



    def _current_filter_payload(self) -> dict:
        return _current_filter_payload_impl(self)



    def _apply_filter_payload(self, payload: dict) -> None:
        return _apply_filter_payload_impl(self, payload)



    def _apply_preset_from_combo(self) -> None:
        return _apply_preset_from_combo_impl(self)



    def _apply_song_filter(self) -> None:
        return _apply_song_filter_impl(self)


    def _render_songs_table(self, songs: List[SongAgg]) -> List[int]:
        return _render_songs_table_impl(self, songs)

    def _update_group_header_states(self) -> None:
        _update_group_header_states_impl(self)

    def _toggle_disc_group_all(self, label: str) -> None:
        _toggle_disc_group_all_impl(self, label)

    def _toggle_song_group(self, label: str) -> None:
        _toggle_song_group_impl(self, label)

    def eventFilter(self, obj, event):  # type: ignore[override]
        # IMPORTANT: the fallback must call the superclass implementation using *self*.
        # If we call `super()` in a nested function that receives a QWidget (`obj`) as
        # its first arg, Python will treat that QWidget as the implicit `self` for
        # super(), causing: `TypeError: super(type, obj): obj ... is not ... MainWindow`.
        def _fallback(o, e):
            return QMainWindow.eventFilter(self, o, e)

        return _songs_event_filter_impl(self, obj, event, _fallback)

    def _on_song_item_changed(self, item: QTableWidgetItem) -> None:
        _on_song_item_changed_impl(self, item)

    def _bulk_select_visible(self, mode: str = "select") -> None:
        _bulk_select_visible_impl(self, mode=mode)

    def _update_song_status(self, total: Optional[int] = None, visible: Optional[int] = None) -> None:
        _update_song_status_impl(self, total=total, visible=visible)

    def _collect_extract_targets(self) -> List[tuple[str, str]]:
        return _collect_extract_targets_impl(self)

    def _start_extract_targets(self, targets: List[tuple[str, str]]) -> None:
        _start_extract_targets_impl(self, targets)

    def _collect_packed_extract_targets(self) -> List[tuple[str, str]]:
        return _collect_packed_extract_targets_impl(self)

    def _start_extract_packed_only(self) -> None:
        _start_extract_packed_only_impl(self)

    def _start_extract(self) -> None:
        _start_extract_impl(self)

    def _cleanup_extract(self) -> None:
        _cleanup_extract_impl(self)

    def _start_cleanup_targets(self, disc_roots: List[str], *, include_pkd_files: bool) -> None:
        _start_cleanup_targets_impl(self, disc_roots, include_pkd_files=include_pkd_files)

    def _cleanup_cleanup(self) -> None:
        _cleanup_cleanup_impl(self)

    def _on_cleanup_tool_done(self, results: object) -> None:
        _on_cleanup_tool_done_impl(self, results)

    def _on_cleanup_tool_cancelled(self) -> None:
        _on_cleanup_tool_cancelled_impl(self)

    def _on_cleanup_tool_error(self, msg: str) -> None:
        _on_cleanup_tool_error_impl(self, msg)

    def _on_extract_done(self, results: object) -> None:
        _on_extract_done_impl(self, results)

    def _on_extract_cancelled(self) -> None:
        _on_extract_cancelled_impl(self)

    def _on_extract_error(self, msg: str) -> None:
        _on_extract_error_impl(self, msg)

    def _suggest_output_name(self, n_songs: int) -> str:
        try:
            n = int(n_songs)
        except Exception:
            n = 0
        return f"SPCDB_Subset_{n}songs"

    def _first_available_outdir(self, parent: Path, name: str) -> Path:
        return _first_available_outdir_impl(self, parent, name)

    def _collect_build_sources(self) -> List[tuple[str, str]]:
        sources: List[tuple[str, str]] = []
        selected_rows = sorted({i.row() for i in self.sources_table.selectedIndexes()})
        rows = selected_rows if selected_rows else list(range(self.sources_table.rowCount()))

        for r in rows:
            if self._is_base_row(r):
                continue
            label = (self.sources_table.item(r, 0).text() if self.sources_table.item(r, 0) else '').strip()
            path = (self.sources_table.item(r, 2).text() if self.sources_table.item(r, 2) else '').strip()
            if not path:
                continue
            if not label:
                label = Path(path).name
            sources.append((label, path))

        return sources

    def _start_build(self) -> None:
        _start_build_impl(self)

    def _start_update_existing(self) -> None:
        _start_update_existing_impl(self)

    def _cleanup_build(self) -> None:
        _cleanup_build_impl(self)

    def _on_preflight_report(self, report_text: str) -> None:
        _on_preflight_report_impl(self, report_text)

    def _start_copy_disc(self, disc_dir: Path) -> None:
        _start_copy_disc_impl(self, disc_dir)

    def _on_build_done(self, out_dir: str) -> None:
        _on_build_done_impl(self, out_dir)

    def _on_build_cancelled(self) -> None:
        _on_build_cancelled_impl(self)

    def _on_build_blocked(self, msg: str) -> None:
        _on_build_blocked_impl(self, msg)

    def _on_build_error(self, msg: str) -> None:
        _on_build_error_impl(self, msg)

    def _about(self) -> None:
        show_about_dialog(self, APP_VERSION)

    def _clear_index_cache_action(self) -> None:
        """Clear index cache from Tools menu (best-effort)."""
        try:
            ok, msg = clear_index_cache()
        except Exception as e:
            ok, msg = False, str(e)

        if ok:
            self._log(f"[cache] Clear index cache: {msg}")
            try:
                QMessageBox.information(self, "Cache", f"Index cache cleared.\n\n{msg}")
            except Exception:
                pass
            try:
                self.cache_status_lbl.setText("Cache: cleared")
            except Exception:
                pass
        else:
            self._log(f"[cache] Clear index cache FAILED: {msg}")
            try:
                QMessageBox.warning(self, "Cache", f"Failed to clear index cache.\n\n{msg}")
            except Exception:
                pass

        # Refresh badges (I flag)
        try:
            self._refresh_source_states()
        except Exception:
            pass
    def _repo_root(self) -> Path:
        """Best-effort locate the app root (directory containing LICENSE)."""
        try:
            here = Path(__file__).resolve()
        except Exception:
            return Path.cwd()

        # Walk upwards a few levels to find the app root that contains LICENSE.
        try:
            for parent in list(here.parents)[:6]:
                if (parent / "LICENSE").is_file():
                    return parent
        except Exception:
            pass

        # Fallback: assume .../<app_root>/spcdb_tool/qt/main_window.py
        try:
            return here.parents[2]
        except Exception:
            return Path.cwd()

    def _open_repo_file(self, rel_name: str) -> None:
        try:
            p = self._repo_root() / str(rel_name)
            if not p.exists():
                QMessageBox.warning(self, "Not found", f"File not found: {p}")
                return
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(p)))
        except Exception as e:
            QMessageBox.warning(self, "Open failed", f"Could not open file: {e}")

    def _open_license(self) -> None:
        self._open_repo_file("LICENSE")

    def _open_third_party_notices(self) -> None:
        self._open_repo_file("THIRD_PARTY_NOTICES.md")


    def _export_support_bundle_action(self) -> None:
        _export_support_bundle_action_impl(self)

    def _reset_ui_state_action(self) -> None:
        _reset_ui_state_action_impl(self)

    def _apply_default_ui_splitters(self) -> None:
        _apply_default_ui_splitters_impl(self)

    def _apply_default_ui_columns(self) -> None:
        _apply_default_ui_columns_impl(self)

    def _reset_layout_action(self) -> None:
        _reset_layout_action_impl(self)

    def _reset_columns_action(self) -> None:
        _reset_columns_action_impl(self)

    def _confirm_permanent_delete_cleanup(self, *, disc_count: int, mode_txt: str) -> bool:
        return _confirm_permanent_delete_cleanup_impl(self, disc_count=disc_count, mode_txt=mode_txt)


    def _toggle_left_sidebar(self, checked: bool) -> None:
        """Show/hide the left sidebar in the main splitter."""
        self._set_left_sidebar_visible(bool(checked))

    def _set_left_sidebar_visible(self, visible: bool) -> None:
        ms = getattr(self, "_main_split", None)
        ls = getattr(self, "_left_panel", None)
        if ms is None or ls is None:
            return

        try:
            cur = bool(getattr(self, "_left_sidebar_visible", True))
        except Exception:
            cur = True
        if cur == bool(visible):
            return

        if not bool(visible):
            # Save current sizes before hiding
            try:
                self._left_sidebar_sizes_before_hide = list(ms.sizes())
            except Exception:
                self._left_sidebar_sizes_before_hide = None
            try:
                ls.hide()
            except Exception:
                pass
            # Reallocate space to center/right (best-effort)
            try:
                sizes = list(ms.sizes())
                if len(sizes) >= 3:
                    ms.setSizes([0, sizes[0] + sizes[1], sizes[2]])
            except Exception:
                pass
            try:
                self._left_sidebar_visible = False
            except Exception:
                pass
            try:
                sb = self.statusBar()
                if sb is not None:
                    sb.showMessage("Left sidebar hidden - View -> Left sidebar (F8) to restore.", 8000)
            except Exception:
                pass
        else:
            try:
                ls.show()
            except Exception:
                pass
            # Restore previous sizes if available
            sizes = getattr(self, "_left_sidebar_sizes_before_hide", None)
            try:
                if isinstance(sizes, (list, tuple)) and len(sizes) >= 3:
                    ms.setSizes(list(sizes))
                else:
                    ms.setSizes([320, 760, 320])
            except Exception:
                pass
            try:
                self._left_sidebar_visible = True
            except Exception:
                pass

        # Keep menu action state in sync
        act = getattr(self, "_act_toggle_left_sidebar", None)
        try:
            if act is not None:
                act.blockSignals(True)
                act.setChecked(bool(visible))
                act.blockSignals(False)
        except Exception:
            try:
                act.blockSignals(False)
            except Exception:
                pass

    def _toggle_right_sidebar(self, checked: bool) -> None:
        """Show/hide the right sidebar in the main splitter."""
        self._set_right_sidebar_visible(bool(checked))

    def _set_right_sidebar_visible(self, visible: bool) -> None:
        ms = getattr(self, "_main_split", None)
        rs = getattr(self, "_right_scroll", None)
        if ms is None or rs is None:
            return

        try:
            cur = bool(getattr(self, "_right_sidebar_visible", True))
        except Exception:
            cur = True
        if cur == bool(visible):
            return

        if not bool(visible):
            # Save current sizes before hiding
            try:
                self._right_sidebar_sizes_before_hide = list(ms.sizes())
            except Exception:
                self._right_sidebar_sizes_before_hide = None
            try:
                rs.hide()
            except Exception:
                pass
            # Reallocate space to left/center (best-effort)
            try:
                sizes = list(ms.sizes())
                if len(sizes) >= 3:
                    ms.setSizes([sizes[0], sizes[1] + sizes[2], 0])
            except Exception:
                pass
            try:
                self._right_sidebar_visible = False
            except Exception:
                pass
            try:
                sb = self.statusBar()
                if sb is not None:
                    sb.showMessage("Right sidebar hidden - View -> Right sidebar (F9) to restore.", 8000)
            except Exception:
                pass
        else:
            try:
                rs.show()
            except Exception:
                pass
            # Restore previous sizes if available
            sizes = getattr(self, "_right_sidebar_sizes_before_hide", None)
            try:
                if isinstance(sizes, (list, tuple)) and len(sizes) >= 3:
                    ms.setSizes(list(sizes))
                else:
                    ms.setSizes([320, 760, 320])
            except Exception:
                pass
            try:
                self._right_sidebar_visible = True
            except Exception:
                pass

        # Keep menu action state in sync
        act = getattr(self, "_act_toggle_right_sidebar", None)
        try:
            if act is not None:
                act.blockSignals(True)
                act.setChecked(bool(visible))
                act.blockSignals(False)
        except Exception:
            try:
                act.blockSignals(False)
            except Exception:
                pass

    def _cleanup_pkd_artifacts_action(self) -> None:
        _cleanup_pkd_artifacts_action_impl(self)

    def _cleanup_cleanup_scan(self) -> None:
        _cleanup_cleanup_scan_impl(self)

    def _cleanup_cleanup_preview(self) -> None:
        _cleanup_cleanup_preview_impl(self)

    def _on_cleanup_preview_progress_cancelled(self) -> None:
        _on_cleanup_preview_progress_cancelled_impl(self)

    def _start_cleanup_preview(self, paths: list[str], *, mode_txt: str, include_pkd_files: bool) -> None:
        _start_cleanup_preview_impl(self, paths, mode_txt=mode_txt, include_pkd_files=include_pkd_files)

    def _show_cleanup_preview_confirm_dialog(
        self,
        preview_rows: list[dict],
        *,
        include_pkd_files: bool,
        mode_txt: str,
        trash_root_dir: Optional[str] = None,
        empty_trash_first: bool = False,
    ) -> tuple[bool, bool, bool]:
        return _show_cleanup_preview_confirm_dialog_impl(
            self,
            preview_rows,
            include_pkd_files=include_pkd_files,
            mode_txt=mode_txt,
            trash_root_dir=trash_root_dir,
            empty_trash_first=empty_trash_first,
        )

    def _on_cleanup_preview_done(self, preview_obj: object) -> None:
        _on_cleanup_preview_done_impl(self, preview_obj)

    def _on_cleanup_preview_cancelled(self) -> None:
        _on_cleanup_preview_cancelled_impl(self)

    def _on_cleanup_preview_error(self, msg: str) -> None:
        _on_cleanup_preview_error_impl(self, msg)

    def _on_cleanup_scan_done_worker(self, found: list[str]) -> None:
        _on_cleanup_scan_done_worker_impl(self, found)

    def _on_cleanup_scan_cancelled(self) -> None:
        _on_cleanup_scan_cancelled_impl(self)

    def _on_cleanup_scan_error(self, msg: str) -> None:
        _on_cleanup_scan_error_impl(self, msg)

    def _on_cleanup_scan_done(self, found_paths: object, *, root_dir: str, include_pkd_files: bool, empty_trash_first: bool) -> None:
        _on_cleanup_scan_done_impl(
            self,
            found_paths,
            root_dir=root_dir,
            include_pkd_files=include_pkd_files,
            empty_trash_first=empty_trash_first,
        )

    def _on_cleanup_done(self, results: object) -> None:
        _on_cleanup_done_impl(self, results)

    def _on_cleanup_cancelled(self) -> None:
        _on_cleanup_cancelled_impl(self)

    def _on_cleanup_error(self, msg: str) -> None:
        _on_cleanup_error_impl(self, msg)

    def _browse_base(self) -> None:
        _browse_base_impl(self)
    def _browse_output(self) -> None:
        _browse_output_impl(self)
    def _browse_extractor(self) -> None:
        _browse_extractor_impl(self)
    def _update_sources_title(self) -> None:
        return _update_sources_title_impl(self)
    def _sources_filter_active(self) -> bool:
        return bool(_sources_filter_active_impl(self))
    def _source_state_category(self, state: str) -> str:
        return str(_source_state_category_impl(state))
    def _apply_sources_filter(self) -> None:
        return _apply_sources_filter_impl(self)
    def _select_sources_shown(self) -> None:
        return _select_sources_shown_impl(self)
    def _norm_key(self, p: str) -> str:
        return str(_norm_key_impl(p))
    def _compute_disc_state(self, disc_root: str) -> str:
        return str(_compute_disc_state_impl(self, disc_root))
    def _apply_source_row_decor(self, row: int, state: str) -> None:
        return _apply_source_row_decor_impl(self, row, state)
    def _refresh_source_states(self) -> None:
        return _refresh_source_states_impl(self)
    def _add_source_path(self, path: str) -> bool:
        return bool(_add_source_path_impl(self, path))
    def _add_source(self) -> None:
        return _add_source_impl(self)
    def _clear_sources(self) -> None:
        return _clear_sources_impl(self)
    def _cleanup_scan(self) -> None:
        return _cleanup_scan_impl(self)
    def _on_scan_done(self, found_paths) -> None:
        return _on_scan_done_impl(self, found_paths)
    def _on_scan_cancelled(self) -> None:
        return _on_scan_cancelled_impl(self)
    def _on_scan_error(self, msg: str) -> None:
        return _on_scan_error_impl(self, msg)
    def _scan_sources_root(self) -> None:
        return _scan_sources_root_impl(self)
    def _remove_selected_sources(self) -> None:
        return _remove_selected_sources_impl(self)
    def _load_into_ui(self) -> None:
        s = _load_settings() or {}
        self.base_edit.setText(str(s.get("base_path", "") or ""))
        self.output_edit.setText(str(s.get("output_path", "") or ""))
        # Auto-detect extractor if user placed it in ./extractor and no path is configured yet.
        exe = str(s.get("extractor_exe_path", "") or "").strip()
        if not exe:
            try:
                ensure_default_extractor_dir()
                det = detect_default_extractor_exe()
                if det is not None and det.exists():
                    exe = str(det)
                    s["extractor_exe_path"] = exe
                    try:
                        _save_settings(s)
                    except Exception:
                        pass
            except Exception:
                pass
        self.extractor_edit.setText(exe)

        self.chk_validate_write_report.setChecked(bool(s.get("validate_write_report", False)))
        self.chk_preflight.setChecked(bool(s.get("preflight_before_build", False)))
        self.chk_block_build.setChecked(bool(s.get("block_build_on_validate_errors", False)))

        try:
            self.chk_allow_overwrite.setChecked(bool(s.get("allow_overwrite_output", False)))
            self.chk_keep_backup.setChecked(bool(s.get("keep_backup_of_existing_output", True)))
            self.chk_keep_backup.setEnabled(bool(self.chk_allow_overwrite.isChecked()))
        except Exception:
            pass

        # Disc Branding (XMB)
        try:
            self.disc_icon_path_edit.setText(str(s.get("disc_branding_icon_path", "") or ""))
        except Exception:
            pass
        try:
            self.disc_bg_path_edit.setText(str(s.get("disc_branding_pic1_path", "") or ""))
        except Exception:
            pass
        try:
            self.chk_disc_branding_autoresize.setChecked(bool(s.get("disc_branding_autoresize", True)))
        except Exception:
            pass
        try:
            self.chk_disc_branding_apply.setChecked(bool(s.get("disc_branding_apply_on_build", True)))
        except Exception:
            pass
        try:
            self._update_disc_branding_ui()
        except Exception:
            pass

        self.sources_table.setRowCount(0)
        self._ensure_base_row()
        raw = s.get("sources", [])
        if isinstance(raw, list):
            for item in raw:
                try:
                    path = str((item or {}).get("path", "") or "").strip()
                    label = str((item or {}).get("label", "") or "").strip() or (Path(path).name if path else "")
                except Exception:
                    continue
                if not path:
                    continue
                row = self.sources_table.rowCount()
                self.sources_table.insertRow(row)
                self.sources_table.setItem(row, 0, QTableWidgetItem(label))
                # State (col 1) will be computed by _refresh_source_states.
                self.sources_table.setItem(row, 2, QTableWidgetItem(path))

        self._update_sources_title()
        self._refresh_source_states()


    def _save_from_ui(self) -> None:
        # Preserve unknown keys in settings.
        s = _load_settings() or {}

        base_path = self.base_edit.text().strip()
        out_path = self.output_edit.text().strip()
        exe_path = self.extractor_edit.text().strip()

        sources: List[Dict[str, str]] = []
        for r in range(self.sources_table.rowCount()):
            if self._is_base_row(r):
                continue
            label = (self.sources_table.item(r, 0).text() if self.sources_table.item(r, 0) else "").strip()
            path = (self.sources_table.item(r, 2).text() if self.sources_table.item(r, 2) else "").strip()
            if not path:
                continue
            if not label:
                label = Path(path).name
            sources.append({"path": path, "label": label})

        s.update(
            {
                "base_path": base_path,
                "sources": sources,
                "output_path": out_path,
                "extractor_exe_path": exe_path,
                "validate_write_report": bool(self.chk_validate_write_report.isChecked()),
                "preflight_before_build": bool(self.chk_preflight.isChecked()),
                "block_build_on_validate_errors": bool(self.chk_block_build.isChecked()),
                "allow_overwrite_output": bool(getattr(self, 'chk_allow_overwrite', None).isChecked() if getattr(self, 'chk_allow_overwrite', None) is not None else False),
                "keep_backup_of_existing_output": bool(getattr(self, 'chk_keep_backup', None).isChecked() if getattr(self, 'chk_keep_backup', None) is not None else True),
                "disc_branding_icon_path": str(self.disc_icon_path_edit.text().strip()),
                "disc_branding_pic1_path": str(self.disc_bg_path_edit.text().strip()),
                "disc_branding_autoresize": bool(self.chk_disc_branding_autoresize.isChecked()),
                "disc_branding_apply_on_build": bool(self.chk_disc_branding_apply.isChecked()),
            }
        )
        _save_settings(s)
        self._log("Saved settings.")




    # -------------------------
    # Disc Branding (XMB)
    # -------------------------

    def _disc_branding_base_asset_path(self, fname_upper: str) -> Optional[Path]:
        return disc_branding_base_asset_path(self, fname_upper)

    def _update_disc_branding_ui(self) -> None:
        update_disc_branding_ui(self)

    def _save_disc_branding_settings(self) -> None:
        save_disc_branding_settings(self)


    def _choose_disc_branding_file(self, *, title: str, current_path: str) -> Optional[str]:
        """Pick an image file for disc branding (ICON0/PIC1).

        We keep this inside MainWindow so right_panel wiring can connect reliably.
        """
        try:
            from PySide6.QtWidgets import QFileDialog
        except Exception:
            return None

        start_dir = ""
        cur = str(current_path or "").strip()
        if cur:
            try:
                cp = Path(cur).expanduser()
                if cp.exists():
                    start_dir = str(cp.parent)
            except Exception:
                start_dir = ""

        if not start_dir:
            try:
                base_s = str(self.base_edit.text() or "").strip()
            except Exception:
                base_s = ""
            if base_s:
                try:
                    bp = Path(base_s).expanduser()
                    start_dir = str(bp if bp.is_dir() else bp.parent)
                except Exception:
                    start_dir = ""

        filt = "Images (*.png *.jpg *.jpeg *.bmp *.webp *.gif);;All files (*.*)"
        try:
            fname, _sel = QFileDialog.getOpenFileName(self, title, start_dir, filt)
        except Exception:
            return None

        fname = str(fname or "").strip()
        return fname or None


    def _choose_disc_branding_icon(self) -> None:
        """Choose a custom ICON0 image.

        This updates the text field + preview and persists branding-only settings.
        """
        try:
            cur = str(self.disc_icon_path_edit.text() or "").strip()
        except Exception:
            cur = ""
        picked = self._choose_disc_branding_file(title="Choose ICON0 image", current_path=cur)
        if not picked:
            return
        try:
            self.disc_icon_path_edit.setText(picked)
        except Exception:
            return
        try:
            self._save_disc_branding_settings()
            self._update_disc_branding_ui()
        except Exception:
            pass


    def _clear_disc_branding_icon(self) -> None:
        """Clear custom ICON0 override (fallback to Base disc preview)."""
        try:
            self.disc_icon_path_edit.setText("")
        except Exception:
            return
        try:
            self._save_disc_branding_settings()
            self._update_disc_branding_ui()
        except Exception:
            pass


    def _choose_disc_branding_background(self) -> None:
        """Choose a custom PIC1 background image.

        This updates the text field + preview and persists branding-only settings.
        """
        try:
            cur = str(self.disc_bg_path_edit.text() or "").strip()
        except Exception:
            cur = ""
        picked = self._choose_disc_branding_file(title="Choose PIC1 background image", current_path=cur)
        if not picked:
            return
        try:
            self.disc_bg_path_edit.setText(picked)
        except Exception:
            return
        try:
            self._save_disc_branding_settings()
            self._update_disc_branding_ui()
        except Exception:
            pass


    def _clear_disc_branding_background(self) -> None:
        """Clear custom PIC1 override (fallback to Base disc preview)."""
        try:
            self.disc_bg_path_edit.setText("")
        except Exception:
            return
        try:
            self._save_disc_branding_settings()
            self._update_disc_branding_ui()
        except Exception:
            pass

    def _write_branding_png(
        self,
        src_path: Path,
        dst_path: Path,
        *,
        target_size: Optional[Tuple[int, int]],
        pad_mode: str,
    ) -> None:
        write_branding_png(src_path, dst_path, target_size=target_size, pad_mode=pad_mode)

    def _apply_disc_branding_to_output(self, disc_dir: Path) -> None:
        apply_disc_branding_to_output(self, disc_dir)


    def _apply_disc_branding_to_existing_output(self) -> None:
        """Apply ICON0/PIC1 into an already-built output disc folder (no rebuild)."""
        if self._any_op_running():
            try:
                sb = self.statusBar()
                sb.showMessage("Busy: wait for the current operation to finish before applying branding.", 8000)
            except Exception:
                pass
            return

        try:
            from PySide6.QtWidgets import QFileDialog
        except Exception:
            return

        # Start browsing from the configured output parent if available.
        start_dir = ""
        try:
            out_parent = str(self.output_edit.text() or "").strip()
            if out_parent:
                op = Path(out_parent).expanduser()
                if op.exists():
                    start_dir = str(op)
        except Exception:
            start_dir = ""

        try:
            d = QFileDialog.getExistingDirectory(
                self,
                "Apply Disc Branding to existing output (select disc folder containing PS3_GAME)",
                start_dir,
            )
        except Exception:
            return

        d = str(d or "").strip()
        if not d:
            return

        try:
            icon_src = str(self.disc_icon_path_edit.text() or "").strip()
        except Exception:
            icon_src = ""
        try:
            bg_src = str(self.disc_bg_path_edit.text() or "").strip()
        except Exception:
            bg_src = ""
        try:
            autoresize = bool(self.chk_disc_branding_autoresize.isChecked())
        except Exception:
            autoresize = True

        try:
            from ..branding_apply import apply_branding_to_existing_output, BrandingError
        except Exception:
            # Extremely defensive: if import fails, just log and exit.
            try:
                self._log("[branding] Cannot import branding_apply helpers.")
            except Exception:
                pass
            return

        try:
            res = apply_branding_to_existing_output(
                d,
                icon_src=(icon_src or None),
                background_src=(bg_src or None),
                autoresize=autoresize,
                logger=self._log,
            )
        except BrandingError as e:
            try:
                self._show_warning_with_logs("Branding apply failed", str(e))
            except Exception:
                try:
                    self._log(f"[branding] Apply failed: {e}")
                except Exception:
                    pass
            return
        except Exception as e:
            try:
                self._show_warning_with_logs("Branding apply failed", f"Unexpected error: {e}")
            except Exception:
                pass
            return

        # Success feedback.
        parts = []
        if res.wrote_icon:
            parts.append("ICON0")
        if res.wrote_background:
            parts.append("PIC1")
        msg = "Branding applied to existing output: " + (", ".join(parts) if parts else "nothing written")
        try:
            sb = self.statusBar()
            sb.showMessage(msg, 8000)
        except Exception:
            pass
        try:
            self._log("[branding] " + msg)
        except Exception:
            pass



    # -------------------------
    # Preview (external player)
    # -------------------------

    @staticmethod
    def _pv_strip_ns(tag: str) -> str:
        return _pv_strip_ns_impl(tag)

    @staticmethod
    def _pv_int(v: object) -> Optional[int]:
        return _pv_int_impl(v)

    @staticmethod
    def _pv_resolution_beats(resolution: str) -> float:
        return _pv_resolution_beats_impl(resolution)

    def _pv_unit_seconds(self, melody_xml: Path) -> Optional[float]:
        return _pv_unit_seconds_impl(self, melody_xml)

    def _pv_extract_times(self, melody_xml: Path) -> Tuple[Dict[str, float], Optional[float]]:
        return _pv_extract_times_impl(self, melody_xml)

    @staticmethod
    def _pv_fmt(sec: float) -> str:
        return _pv_fmt_impl(sec)

    def _pv_find_song_dir(self, export_root: Path, song_id: int) -> Optional[Path]:
        return _pv_find_song_dir_impl(self, export_root, song_id)

    def _pv_scan_media(self, song_dir: Path) -> Dict[str, str]:
        return _pv_scan_media_impl(self, song_dir)

    def _pv_selected_song_id(self) -> Optional[int]:
        return _pv_selected_song_id_impl(self)

    def _pv_selected_label(self, song_id: int) -> str:
        return _pv_selected_label_impl(self, song_id)

    def _pv_choose_window(
        self,
        melody_xml: Optional[Path],
        start_mode: str,
        clip_mode: str,
    ) -> Tuple[float, Optional[float], str, str]:
        return _pv_choose_window_impl(self, melody_xml, start_mode, clip_mode)

    def _pv_choose_start(self, melody_xml: Optional[Path], mode: str) -> Tuple[float, str]:
        return _pv_choose_start_impl(self, melody_xml, mode)

    def _update_preview_context(self) -> None:
        _update_preview_context_impl(self)

    def _pv_player_cmd(
        self,
        media_path: str,
        start_s: float,
        end_s: Optional[float],
    ) -> Tuple[str, List[str], str]:
        return _pv_player_cmd_impl(self, media_path, start_s, end_s)

    def _preview_start(self) -> None:
        _preview_start_impl(self)

    def _preview_stop(self) -> None:
        _preview_stop_impl(self)

    def _preview_on_finished(self) -> None:
        _preview_on_finished_impl(self)

    def _preview_on_error(self) -> None:
        _preview_on_error_impl(self)


    def closeEvent(self, event) -> None:  # type: ignore[override]
        try:
            self._qt_shutting_down = True
        except Exception:
            pass
        try:
            from .window_state import save_window_state
            save_window_state(self)
        except Exception:
            pass
        try:
            self._save_qt_state(force=True)
        except Exception:
            pass
        try:
            self._save_from_ui()
        except Exception:
            pass
        try:
            self._preview_stop()
        except Exception:
            pass
        super().closeEvent(event)


# NOTE: QApplication / splash bootstrapping lives in spcdb_tool.qt_app.run_qt_gui()
# (keep imports lazy and avoid doing GUI work at module import time).
