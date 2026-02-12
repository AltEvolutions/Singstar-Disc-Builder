"""Songs refresh pipeline helpers (Qt).

This module extracts the heavier *song catalog refresh* logic out of
`spcdb_tool/qt/main_window.py`.

Intent: behavior-preserving refactor only.

Notes:
- We keep the helper surface small and deliberately use dynamic access to
  MainWindow attributes.
- Filtering/rendering is handled elsewhere (songs table helpers + MainWindow).
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import List, Set

from PySide6.QtCore import QThread
from PySide6.QtWidgets import QMessageBox

from ..controller import CancelToken, SongAgg, get_index_cache_status
from .songs_refresh import start_songs_refresh_thread
from .ui_helpers import show_status_message


def collect_song_targets(main_window: object) -> List[tuple[str, str, bool]]:
    """Collect the disc roots to index for the Songs catalog.

    Targets are derived from:
    - Base path (always first if set)
    - All Source rows (selection does NOT affect refresh scope)

    Returns:
        List of (label, disc_root, is_base).
    """

    targets: List[tuple[str, str, bool]] = []

    base_edit = getattr(main_window, 'base_edit', None)
    try:
        base_path = str(base_edit.text() if base_edit is not None else '').strip()
    except Exception:
        base_path = ''
    if base_path:
        targets.append(('Base', base_path, True))

    sources_table = getattr(main_window, 'sources_table', None)
    if sources_table is None:
        return targets

    try:
        row_count = int(sources_table.rowCount())
    except Exception:
        row_count = 0

    # IMPORTANT: Refresh Songs should index ALL sources, regardless of which rows are selected
    # in the Sources table. Selecting a disc is a UI/navigation action, not a refresh scope.
    rows = list(range(row_count))

    is_base_row = getattr(main_window, '_is_base_row')
    for r in rows:
        try:
            if bool(is_base_row(r)):
                continue
        except Exception:
            continue

        try:
            it_label = sources_table.item(r, 0)
            label = (it_label.text() if it_label else '').strip()
        except Exception:
            label = ''
        try:
            it_path = sources_table.item(r, 2)
            path = (it_path.text() if it_path else '').strip()
        except Exception:
            path = ''
        if not path:
            continue
        if not label:
            try:
                label = Path(path).name
            except Exception:
                label = path
        targets.append((label, path, False))

    return targets


def auto_refresh_songs_for_roots(main_window: object, disc_roots: List[str]) -> None:
    """Auto-refresh songs after Sources change.

    We treat Sources table selection as a pure UI/navigation concern; it must NOT
    influence refresh scope. Therefore we no longer temporarily select rows here.

    Args:
        main_window: MainWindow instance.
        disc_roots: Disc roots that changed. If empty, do nothing (keeps the old debounce behavior).
    """

    try:
        roots = [str(x or '').strip() for x in (disc_roots or []) if str(x or '').strip()]
    except Exception:
        roots = []
    if not roots:
        return

    try:
        # startup=True disables cache-only pruning; we want an accurate full catalog after source changes.
        getattr(main_window, '_start_refresh_songs')(auto=True, startup=True)
    except Exception:
        pass


def start_refresh_songs(
    main_window: object,
    auto: bool = False,
    *,
    only_extracted: bool = False,
    startup: bool = False,
) -> None:
    """Begin a song catalog refresh in the background."""

    any_op_running = getattr(main_window, '_any_op_running')
    log = getattr(main_window, '_log')

    if bool(any_op_running()):
        if not auto:
            try:
                log('[songs] Another operation is already running.')
            except Exception:
                pass
        return

    targets = collect_song_targets(main_window)

    compute_disc_state = getattr(main_window, '_compute_disc_state')

    # Skip packed/unextracted discs. They cannot be indexed until extracted.
    filtered: List[tuple[str, str, bool]] = []
    skipped = 0
    for (lbl, disc_root, is_base) in list(targets or []):
        st = compute_disc_state(str(disc_root))
        if 'Extracted' not in str(st):
            if bool(is_base):
                if auto:
                    try:
                        log('[songs] Auto-refresh skipped: Base is not extracted.')
                    except Exception:
                        pass
                else:
                    QMessageBox.warning(
                        main_window,
                        'Songs',
'Base disc is not extracted.\n\nPick an extracted Base disc folder (with FileSystem/Export).',
                    )
                return
            skipped += 1
            continue
        filtered.append((lbl, disc_root, bool(is_base)))

    if skipped:
        try:
            log(f"[songs] Skipping {int(skipped)} packed/unextracted disc(s).")
        except Exception:
            pass

    targets = filtered

    # Auto-refresh: stay lightweight on large inputs (avoid parsing many new discs automatically).
    # If there are only Base + <=1 source, allow a full parse. Otherwise, only load discs that
    # already have a fresh song cache.
    if auto and (not bool(startup)) and len(targets) > 2:
        cache_only: List[tuple[str, str, bool]] = []
        for (lbl, disc_root, is_base) in list(targets or []):
            if bool(is_base):
                cache_only.append((lbl, disc_root, True))
                continue
            st = get_index_cache_status(str(disc_root))
            if bool(st.get('exists')) and (not bool(st.get('stale'))) and bool(st.get('has_songs')):
                cache_only.append((lbl, disc_root, False))
        if len(cache_only) != len(targets):
            try:
                log(f"[songs] Auto-refresh: cache-only ({len(cache_only)}/{len(targets)} discs).")
            except Exception:
                pass
        targets = cache_only

    # only_extracted currently just reinforces the skip behavior above (kept for call-site clarity).
    _ = bool(only_extracted)

    # Remember the exact target order used for this refresh (for grouping/order).
    try:
        setattr(main_window, '_songs_last_targets', list(targets or []))
    except Exception:
        setattr(main_window, '_songs_last_targets', [])

    if not targets:
        if not auto:
            QMessageBox.warning(
                main_window,
                'Songs',
                'Nothing to index.\n\nSet Base and/or add at least one Source.',
            )
        else:
            try:
                log('[songs] Skipping auto-refresh (no Base/Sources).')
            except Exception:
                pass
        return

    base_path = str(targets[0][1] or '').strip() if targets else ''
    if not base_path:
        if not auto:
            QMessageBox.warning(main_window, 'Songs', 'Base path is empty. Set Base first.')
        return

    # Debounce repeated refresh requests (double-clicks / auto-refresh overlap).
    try:
        now_ts = float(time.time())
    except Exception:
        now_ts = 0.0

    try:
        last_ts = float(getattr(main_window, '_songs_refresh_last_ts', 0.0) or 0.0)
    except Exception:
        last_ts = 0.0

    if (now_ts > 0.0) and ((now_ts - last_ts) < 0.75):
        if not auto:
            try:
                log('[songs] Refresh ignored (debounced).')
            except Exception:
                pass
        return

    try:
        key_parts = [f"{str(lbl)}::{str(pth)}::{int(bool(is_base))}" for (lbl, pth, is_base) in targets]
        refresh_key = '|'.join(key_parts)
    except Exception:
        refresh_key = ''

    # Auto-refresh only: if inputs unchanged and we already have a catalog, avoid extra work.
    try:
        if auto and refresh_key and (refresh_key == str(getattr(main_window, '_songs_refresh_last_key', '') or '')) and bool(getattr(main_window, '_songs_all', [])):
            try:
                log('[songs] Auto-refresh skipped (inputs unchanged; using loaded catalog).')
            except Exception:
                pass
            try:
                getattr(main_window, '_apply_song_filter')()
            except Exception:
                pass
            return
    except Exception:
        pass

    try:
        setattr(main_window, '_songs_refresh_last_ts', now_ts)
        setattr(main_window, '_songs_refresh_last_key', refresh_key)
    except Exception:
        pass

    # Cache indicator: how many discs should be a cache hit vs rebuild.
    try:
        total = int(len(targets))
        hits = 0
        for (_lbl, disc_root, _is_base) in targets:
            st = get_index_cache_status(str(disc_root))
            if bool(st.get('exists')) and (not bool(st.get('stale'))) and bool(st.get('has_songs')):
                hits += 1
        misses = max(0, total - hits)
        cache_status_lbl = getattr(main_window, 'cache_status_lbl', None)
        if cache_status_lbl is not None:
            cache_status_lbl.setText("Cache: OK" if (total > 0 and misses == 0) else f"Cache: {hits}/{max(1,total)} cached (+{misses} scan)")
        try:
            log(f"[cache] Song cache: indexed {hits}/{total} | scan {misses}")
        except Exception:
            pass
    except Exception:
        pass

    # Mark active op + lock UI
    try:
        setattr(main_window, '_active_op', 'songs')
        setattr(main_window, '_cancel_token', CancelToken())
        getattr(main_window, '_set_op_running')(True)
    except Exception:
        pass

    try:
        log(f"[songs] Refreshing song catalog ({len(targets)} disc(s))...")
    except Exception:
        pass

    try:
        start_songs_refresh_thread(main_window, targets, getattr(main_window, '_cancel_token'))
    except Exception as e:
        try:
            log(f"[songs] ERROR: failed to start refresh thread: {e}")
        except Exception:
            pass
        try:
            getattr(main_window, '_set_op_running')(False)
        except Exception:
            pass
        try:
            setattr(main_window, '_active_op', None)
        except Exception:
            pass


def cleanup_songs(main_window: object) -> None:
    """Cleanup after songs refresh finishes/cancels/errors."""

    # Ensure the background thread event loop stops; otherwise the UI can remain locked.
    try:
        t = getattr(main_window, '_songs_thread', None)
        if t is not None:
            try:
                t.quit()
            except Exception:
                pass
            try:
                if QThread.currentThread() is not t:
                    t.wait(1500)
            except Exception:
                pass
    except Exception:
        pass

    try:
        setattr(main_window, '_songs_thread', None)
        setattr(main_window, '_songs_worker', None)
        setattr(main_window, '_cancel_token', None)
    except Exception:
        pass

    try:
        getattr(main_window, '_set_op_running')(False)
    except Exception:
        pass

    try:
        setattr(main_window, '_active_op', None)
    except Exception:
        pass


def on_songs_done(
    main_window: object,
    songs_out: object,
    disc_song_ids_by_label: object,
    export_roots_by_label: object,
    conflicts_by_song_id: object,
) -> None:
    """UI callback when the songs refresh worker finishes successfully."""

    log = getattr(main_window, '_log')

    songs_list_raw: List[SongAgg] = list(songs_out or [])
    try:
        setattr(main_window, '_songs_all_raw', songs_list_raw)
    except Exception:
        pass

    try:
        songs_all = getattr(main_window, '_apply_song_source_overrides')(songs_list_raw)
    except Exception:
        songs_all = songs_list_raw

    try:
        setattr(main_window, '_songs_all', songs_all)
        setattr(main_window, '_songs_by_id', {int(s.song_id): s for s in (songs_all or [])})
    except Exception:
        setattr(main_window, '_songs_by_id', {})

    # Dedupe stats (visibility): how many songs appear in multiple discs
    try:
        dups = 0
        extra = 0
        for s in (songs_all or []):
            try:
                n = int(len(getattr(s, 'sources', ()) or ()))
            except Exception:
                n = 0
            if n > 1:
                dups += 1
                extra += (n - 1)
        setattr(main_window, '_dedupe_songs_with_dups', int(dups))
        setattr(main_window, '_dedupe_extra_hidden', int(extra))
    except Exception:
        setattr(main_window, '_dedupe_songs_with_dups', 0)
        setattr(main_window, '_dedupe_extra_hidden', 0)

    try:
        setattr(main_window, '_disc_song_ids_by_label', dict(disc_song_ids_by_label or {}))
    except Exception:
        setattr(main_window, '_disc_song_ids_by_label', {})

    try:
        setattr(main_window, '_export_roots_by_label', dict(export_roots_by_label or {}))
    except Exception:
        setattr(main_window, '_export_roots_by_label', {})

    try:
        setattr(main_window, '_song_conflicts', dict(conflicts_by_song_id or {}))
    except Exception:
        setattr(main_window, '_song_conflicts', {})

    try:
        conflicts = getattr(main_window, '_song_conflicts', {}) or {}
        getattr(main_window, 'inspector_conflicts_lbl').setText(f"Conflicts: {int(len(conflicts))}")
        getattr(main_window, 'btn_resolve_conflicts').setEnabled(bool(conflicts))
    except Exception:
        pass

    # Disc group order: Base first, then Sources in UI order used for refresh.
    try:
        t = list(getattr(main_window, '_songs_last_targets', []) or [])
        if not t:
            t = list(collect_song_targets(main_window) or [])
    except Exception:
        t = []

    order_labels: List[str] = []
    try:
        for (lbl, _pth, is_base) in (t or []):
            if bool(is_base):
                continue
            if lbl and (lbl not in order_labels):
                order_labels.append(str(lbl))
    except Exception:
        pass

    try:
        setattr(main_window, '_song_group_order_labels', ['Base'] + [x for x in order_labels if str(x) != 'Base'])
    except Exception:
        setattr(main_window, '_song_group_order_labels', ['Base'])

    # Initialize expanded state for any new labels
    try:
        expanded = getattr(main_window, '_song_group_expanded')
        for k in (getattr(main_window, '_song_group_order_labels', []) or []):
            expanded.setdefault(str(k), True)
    except Exception:
        pass

    # Apply any persisted collapsed groups (best-effort)
    try:
        collapsed = getattr(main_window, '_qt_state_collapsed_groups', []) or []
        expanded = getattr(main_window, '_song_group_expanded')
        for k in collapsed:
            if str(k) in (getattr(main_window, '_song_group_order_labels', []) or []):
                expanded[str(k)] = False
    except Exception:
        pass

    all_ids: Set[int] = set()
    try:
        all_ids = {int(s.song_id) for s in (songs_all or [])}
    except Exception:
        all_ids = set()

    # Persisted OFF state wins: keep disabled songs disabled across refreshes.
    try:
        disabled = set(int(x) for x in (getattr(main_window, '_disabled_song_ids', set()) or set())) & all_ids
        setattr(main_window, '_disabled_song_ids', disabled)
    except Exception:
        setattr(main_window, '_disabled_song_ids', set())

    # Back-compat: if we only have an explicit selection (older state), derive disabled from it.
    try:
        if (not getattr(main_window, '_disabled_song_ids', set())) and bool(getattr(main_window, '_selected_song_ids', set())):
            sel = set(int(x) for x in (getattr(main_window, '_selected_song_ids', set()) or set())) & all_ids
            setattr(main_window, '_selected_song_ids', sel)
            setattr(main_window, '_disabled_song_ids', set(all_ids) - set(sel))
    except Exception:
        pass

    # Default selection logic (v0.8g+): keep existing disabled set; new IDs default OFF.
    try:
        prev_all = set(getattr(main_window, '_qt_state_last_all_song_ids', set()) or set())
    except Exception:
        prev_all = set()

    try:
        had_state = bool(getattr(main_window, '_qt_state_loaded', False))
    except Exception:
        had_state = False

    try:
        default_all_off = bool(getattr(main_window, '_qt_state_default_all_disabled', True))
    except Exception:
        default_all_off = True

    try:
        st_ver = int(getattr(main_window, '_qt_state_version', 0) or 0)
    except Exception:
        st_ver = 0

    try:
        sel_init = bool(getattr(main_window, '_qt_state_selection_initialized', False))
    except Exception:
        sel_init = False

    if default_all_off and had_state and (not sel_init):
        try:
            setattr(main_window, '_selected_song_ids', set())
            setattr(main_window, '_disabled_song_ids', set(all_ids))
            setattr(main_window, '_qt_state_selection_initialized', True)
        except Exception:
            pass

    if default_all_off and st_ver < 2:
        try:
            sel = set(getattr(main_window, '_selected_song_ids', set()) or set())
            if (not getattr(main_window, '_disabled_song_ids', set())) and (not sel or (sel == set(all_ids))):
                setattr(main_window, '_selected_song_ids', set())
                setattr(main_window, '_disabled_song_ids', set(all_ids))
        except Exception:
            pass

    if (not had_state) and (not prev_all):
        try:
            setattr(main_window, '_disabled_song_ids', set(all_ids))
            setattr(main_window, '_qt_state_selection_initialized', True)
        except Exception:
            pass
    else:
        if prev_all:
            try:
                new_ids = set(all_ids) - set(prev_all)
                if new_ids:
                    dis = set(getattr(main_window, '_disabled_song_ids', set()) or set())
                    dis |= set(int(x) for x in new_ids)
                    setattr(main_window, '_disabled_song_ids', dis)
            except Exception:
                pass
        else:
            try:
                applied_dis = bool(getattr(main_window, '_qt_state_applied_disabled_ids', False))
            except Exception:
                applied_dis = False
            try:
                applied_sel = bool(getattr(main_window, '_qt_state_applied_selected_ids', False))
            except Exception:
                applied_sel = False
            if (not applied_dis) and (not applied_sel):
                try:
                    setattr(main_window, '_disabled_song_ids', set(all_ids))
                    setattr(main_window, '_qt_state_selection_initialized', True)
                except Exception:
                    pass

    try:
        disabled = set(getattr(main_window, '_disabled_song_ids', set()) or set())
        setattr(main_window, '_selected_song_ids', set(all_ids) - set(disabled))
    except Exception:
        setattr(main_window, '_selected_song_ids', set())

    try:
        setattr(main_window, '_qt_state_last_all_song_ids', set(int(x) for x in all_ids))
    except Exception:
        pass

    try:
        getattr(main_window, '_refresh_song_source_combo')()
    except Exception:
        pass

    try:
        getattr(main_window, '_apply_song_filter')()
    except Exception:
        pass

    try:
        getattr(main_window, '_save_qt_state')(force=True)
    except Exception:
        pass

    try:
        log(f"[songs] Loaded: {len(songs_all or [])} songs")
    except Exception:
        pass

    # Cache indicator (post-refresh): should now be all hits unless a disc is invalid.
    try:
        collect = getattr(main_window, '_collect_song_targets')
        total = int(len(collect() or []))
        hits = 0
        for (_lbl, disc_root, _is_base) in (collect() or []):
            st = get_index_cache_status(str(disc_root))
            if bool(st.get('exists')) and (not bool(st.get('stale'))) and bool(st.get('has_songs')):
                hits += 1
        cache_status_lbl = getattr(main_window, 'cache_status_lbl', None)
        if cache_status_lbl is not None:
            cache_status_lbl.setText("Cache: OK" if (total > 0 and hits >= total) else f"Cache: {hits}/{max(1,total)} cached")
    except Exception:
        pass

    try:
        getattr(main_window, '_refresh_source_states')()
    except Exception:
        pass

    try:
        conflicts = getattr(main_window, "_song_conflicts", {}) or {}
        show_status_message(main_window, f"Songs refreshed: {len(songs_all or [])} songs. Conflicts: {len(conflicts)}.", 6000)
    except Exception:
        pass

    cleanup_songs(main_window)


def on_songs_cancelled(main_window: object) -> None:
    try:
        getattr(main_window, '_log')('[songs] Cancelled.')
    except Exception:
        pass

    try:
        show_status_message(main_window, 'Songs refresh cancelled.', 5000)
    except Exception:
        pass

    cleanup_songs(main_window)


def on_songs_error(main_window: object, msg: str) -> None:
    try:
        getattr(main_window, '_log')(f"[songs] ERROR: {msg}")
    except Exception:
        pass

    try:
        show_status_message(main_window, 'Songs refresh failed. See logs for details.', 8000)
    except Exception:
        pass

    try:
        getattr(main_window, '_show_critical_with_logs')(
            'Songs',
            str(msg or 'Unknown error'),
            tip='Tip: Check the logs, then try Refresh Songs again.',
        )
    except Exception:
        pass

    cleanup_songs(main_window)
