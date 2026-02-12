from __future__ import annotations

import json
import os
import sys
import locale
import re
from datetime import datetime
import time
import hashlib
import queue
import threading
import subprocess
import shutil
import fnmatch
import tkinter as tk
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from .util import ensure_default_extractor_dir, default_extractor_dir, detect_default_extractor_exe
from tkinter import filedialog, messagebox, ttk
from typing import Dict, List, Optional, Set, Tuple

from . import __version__
from .layout import resolve_input, ResolvedInput
from .merge import MergeError
from .util import dumps_pretty


# NOTE: UI-agnostic helpers/types are being extracted into controller.py (Block D / 0.5.10a).
from .controller import (
    SS_NS,
    DiscIndex,
    SongAgg,
    SongOccur,
    CancelToken,
    CancelledError,
    BuildBlockedError,
    run_build_subset,
    format_validate_report,
    validate_discs,
    validate_one_disc_from_export_root,
    index_disc,
    build_song_catalog,
    extract_disc_pkds,
    verify_disc_extraction,
    cleanup_extraction_artifacts,
    _load_songs_for_disc_cached,
    _best_bank_files,
    _compute_disc_signature,
    _compute_disc_signature_for_idx,
    _covers_song_to_page,
    _extract_song_ids_count,
    _load_index_cache,
    _load_settings,
    _normalize_input_path,
    _parse_config,
    _parse_song_id,
    _save_settings,
    _settings_path,
    _sha1_path,
    _strip_ns,
    _texture_page_exists,
    _write_index_cache,
)

def scan_for_disc_inputs(root: Path, max_depth: int = 4) -> list[str]:
    """Find candidate disc folders beneath root.

    This finds both extracted and unextracted PS3 disc folders by detecting
    PS3_GAME/USRDIR plus SingStar-ish contents (pack*.pkd and/or FileSystem/Export).

    We keep this lightweight and heuristic-driven. For extracted discs we can
    further confirm by calling resolve_input(); for unextracted discs we still
    include them so they can be extracted in-app.
    """
    root = root.expanduser().resolve()
    out: list[str] = []
    seen: set[str] = set()

    def _normalize_disc_root(p: Path) -> Path:
        if p.name.upper() == "PS3_GAME" and p.parent.exists():
            return p.parent
        for parent in [p] + list(p.parents):
            if parent.name.upper() == "PS3_GAME":
                return parent.parent
        return p

    def _looks_like_singstar_usrdir(usr: Path) -> bool:
        try:
            if (usr / "FileSystem" / "Export").is_dir() or (usr / "filesystem" / "export").is_dir():
                return True
            for pat in ("pack*.pkd", "pack*.PKD", "*.pkd", "*.PKD"):
                try:
                    if any(usr.glob(pat)):
                        return True
                except Exception:
                    continue
        except Exception:
            return False
        return False

    def _add_candidate(p: Path) -> bool:
        # First: try to treat it as a disc root (works for unextracted too).
        disc_root = _normalize_disc_root(p)
        usrdir = disc_root / "PS3_GAME" / "USRDIR"
        if usrdir.is_dir() and _looks_like_singstar_usrdir(usrdir):
            try:
                key = str(disc_root.resolve())
            except Exception:
                key = str(disc_root)
            if key in seen:
                return True
            seen.add(key)
            out.append(str(disc_root))
            return True

        # Fallback: extracted/looser layouts; let resolve_input() canonicalize.
        try:
            ri = resolve_input(str(p))
        except Exception:
            return False
        try:
            key = str(Path(ri.original).resolve())
        except Exception:
            key = str(ri.original)
        if key in seen:
            return True
        seen.add(key)
        out.append(str(ri.original))
        return True

    for dirpath, dirnames, _filenames in os.walk(root):
        try:
            depth = len(Path(dirpath).resolve().relative_to(root).parts)
        except Exception:
            depth = 0
        if depth > max_depth:
            dirnames[:] = []
            continue

        # Ignore our own trash/cache folders.
        try:
            for dn in list(dirnames):
                if str(dn).lower() in {"_spcdb_trash", ".git", "__pycache__"}:
                    dirnames.remove(dn)
        except Exception:
            pass

        p = Path(dirpath)

        # Common PS3 disc roots (extracted or not).
        try:
            if (p / "PS3_GAME" / "USRDIR").is_dir():
                if _add_candidate(p):
                    dirnames[:] = []
                    continue
        except Exception:
            pass

        # If we are inside a PS3_GAME folder, prefer the disc root one level up.
        try:
            if p.name.upper() == "PS3_GAME" and (p / "USRDIR").is_dir():
                if _add_candidate(p.parent):
                    dirnames[:] = []
                    continue
        except Exception:
            pass

        # If we are inside USRDIR, try the parent disc root.
        try:
            if p.name.upper() == "USRDIR":
                if _add_candidate(p):
                    dirnames[:] = []
                    continue
        except Exception:
            pass

        # Looser extracted layouts.
        try:
            ex = p / "Export"
            if ex.is_dir() and ((ex / "config.xml").is_file() or (ex / "covers.xml").is_file()):
                if _add_candidate(p):
                    dirnames[:] = []
                    continue
        except Exception:
            pass

    out.sort(key=lambda s: s.lower())
    return out


def _is_expected_base(idx: DiscIndex) -> bool:
    # On some discs, PRODUCT_CODE is just "00011" even though the title ID is BCES00011.
    code = (idx.product_code or "").strip().upper()
    desc = (idx.product_desc or "").strip().upper()
    if code in {"BCES00011", "00011"}:
        return True
    if "BCES00011" in desc:
        return True
    return False



class _Tooltip:
    """Simple hover tooltip for Tkinter widgets."""

    def __init__(self, widget: tk.Widget, text: str, *, delay_ms: int = 450) -> None:
        self.widget = widget
        self.text = text
        self.delay_ms = delay_ms
        self._after_id = None
        self._tip = None

        self.widget.bind("<Enter>", self._on_enter, add=True)
        self.widget.bind("<Leave>", self._on_leave, add=True)
        self.widget.bind("<ButtonPress>", self._on_leave, add=True)

    def _on_enter(self, _evt=None) -> None:
        self._schedule()

    def _on_leave(self, _evt=None) -> None:
        self._unschedule()
        self._hide()

    def _schedule(self) -> None:
        self._unschedule()
        try:
            self._after_id = self.widget.after(self.delay_ms, self._show)
        except Exception:
            self._after_id = None

    def _unschedule(self) -> None:
        if self._after_id is None:
            return
        try:
            self.widget.after_cancel(self._after_id)
        except Exception:
            pass
        self._after_id = None

    def _show(self) -> None:
        if self._tip is not None:
            return
        try:
            # Position near cursor, but keep within screen bounds.
            x = self.widget.winfo_pointerx() + 12
            y = self.widget.winfo_pointery() + 14
            scr_w = self.widget.winfo_screenwidth()
            scr_h = self.widget.winfo_screenheight()

            tip = tk.Toplevel(self.widget)
            tip.wm_overrideredirect(True)
            tip.attributes("-topmost", True)

            lbl = ttk.Label(tip, text=self.text, justify=tk.LEFT)
            lbl.pack(ipadx=8, ipady=5)

            tip.update_idletasks()
            w = tip.winfo_reqwidth()
            h = tip.winfo_reqheight()
            if x + w > scr_w - 8:
                x = max(scr_w - w - 8, 0)
            if y + h > scr_h - 8:
                y = max(scr_h - h - 8, 0)
            tip.geometry(f"+{x}+{y}")

            self._tip = tip
        except Exception:
            self._tip = None

    def _hide(self) -> None:
        if self._tip is None:
            return
        try:
            self._tip.destroy()
        except Exception:
            pass
        self._tip = None


class SPCDBGui(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"SingStar Disc Builder v{__version__}")

        # App icon (best-effort; png works on Tk 8.6+)
        try:
            icon_path = Path(__file__).resolve().parent / 'branding' / 'spcdb_icon.png'
            if icon_path.exists():
                self._app_icon_img = tk.PhotoImage(file=str(icon_path))
                self.iconphoto(True, self._app_icon_img)
        except Exception:
            pass

        # Settings (portable, stored alongside the tool)
        _s = _load_settings()

        # UI theme
        self._dark_mode_var = tk.BooleanVar(value=bool(_s.get("dark_mode", True)))
        self._style = ttk.Style(self)
        self._apply_theme(dark=self._dark_mode_var.get())
        # Re-apply Base badge style after theme change
        try:
            self._set_base_badge(self.base_badge_text_var.get(), getattr(self, "_base_badge_level", "neutral"))
        except Exception:
            pass

        # Persistence debounce
        self._persist_job = None

        self._queue: "queue.Queue[tuple[str, object]]" = queue.Queue()
        self._src_counter = 0
        self._src_labels: Dict[str, str] = {}

        self.base_path_var = tk.StringVar(value=str(_s.get("base_path", "")) or "")
        self.base_info_var = tk.StringVar(value="Base: not set")

        # Base disc health badge (v0.5.5a)
        self.base_badge_text_var = tk.StringVar(value="NOT SET")
        self._base_badge_level = "neutral"
        self.base_badge_label = None

        # Extractor (SCEE London Studio PACKAGE tool)
        self.extractor_exe_var = tk.StringVar(value=str(_s.get("extractor_exe_path", "")) or "")
        # Auto-detect extractor if user placed it in ./extractor and no path is configured yet.
        try:
            if not (self.extractor_exe_var.get() or "").strip():
                ensure_default_extractor_dir()
                det = detect_default_extractor_exe()
                if det is not None and det.exists():
                    self.extractor_exe_var.set(str(det))
                    try:
                        s2 = _load_settings() or {}
                        s2["extractor_exe_path"] = str(det)
                        _save_settings(s2)
                    except Exception:
                        pass
        except Exception:
            pass

        self.output_path_var = tk.StringVar(value=str(_s.get("output_path", "")) or "")

        # Disc validation options (v0.5.9a2)
        self.validate_write_report_var = tk.BooleanVar(value=bool(_s.get("validate_write_report", False)))

        # Build options (v0.5.9a4)
        self.preflight_before_build_var = tk.BooleanVar(value=bool(_s.get("preflight_before_build", False)))

        # Build options (v0.5.9a5)
        self.block_build_on_validate_errors_var = tk.BooleanVar(value=bool(_s.get("block_build_on_validate_errors", False)))

        # Build overwrite options (v0.9.184)
        self.allow_overwrite_output_var = tk.BooleanVar(value=bool(_s.get("allow_overwrite_output", False)))
        self.keep_backup_of_existing_output_var = tk.BooleanVar(value=bool(_s.get("keep_backup_of_existing_output", True)))

        # Output path auto-suggestion:
        # - If user manually chooses/edits the output folder, we stop auto-updating it.
        # - If the saved output path looks like an auto-generated SPCDB_Subset_<n>songs folder under the base parent,
        #   treat it as auto-managed and keep updating as selection count changes.
        self._output_path_user_set = bool(_s.get("output_path_user_set", False))
        try:
            if "output_path_user_set" not in _s:
                outp = (self.output_path_var.get() or "").strip()
                if not outp:
                    self._output_path_user_set = False
                else:
                    basep = (self.base_path_var.get() or "").strip()
                    auto_re = re.compile(r"^SPCDB_Subset_\d+songs(?:_\d+)?$")
                    try:
                        op = Path(outp)
                        if basep and auto_re.match(op.name):
                            bp = Path(basep)
                            self._output_path_user_set = (op.parent != bp.parent)
                        else:
                            self._output_path_user_set = True
                    except Exception:
                        self._output_path_user_set = True
        except Exception:
            pass
        self._build_running = False

        # Build readiness / issues / last build summary (v0.5.5b)
        self.readiness_var = tk.StringVar(value="")
        self.issues_var = tk.StringVar(value="")
        self.last_build_var = tk.StringVar(value="")
        self._last_build = {}
        try:
            lb = _s.get("last_build", {})
            if isinstance(lb, dict):
                self._last_build = lb
        except Exception:
            self._last_build = {}
        self._build_started_ts = None
        self._build_overall_pct = 0.0
        self._build_overall_last_phase = None

        self._last_preflight = {}

        # Job activity tracking (for safe auto-refresh)
        self._active_index_jobs = 0
        self._active_extract_jobs = 0
        self._songs_refresh_running = False
        self._pending_refresh_songs = False
        self._pending_refresh_reason = ""
        self._refresh_songs_job = None

        # Jobs mini-queue (v0.5.8e1)
        self._jobs_tree = None
        self._job_seq = 0
        self._job_iids: Dict[str, str] = {}

        # Startup auto-index sequencing
        self._startup_auto_ran = False
        self._startup_index_queue = []  # list[(kind, input_path, row_iid)]
        self._startup_index_inflight = False
        self._startup_current = None  # tuple(kind, row_iid, input_path)

        # Index cancellation (v0.5.8e3)
        self._index_cancel_requested = False
        self.cancel_index_btn = None

        # Extraction cancellation (v0.5.8e4)
        self._extract_cancel_requested = False
        self.cancel_extract_btn = None

        # Build cancellation (v0.5.8e5)
        self._build_cancel_requested = False
        self.cancel_build_btn = None

        # Disc validation helper (v0.5.9a2)
        self._disc_validate_running = False
        self.validate_selected_btn = None
        self.copy_validate_btn = None
        self._last_validate_report_text = ''

        # Per-session persistent log file (best-effort)
        self._session_log_path: Optional[Path] = None
        try:
            logs_dir = Path(__file__).resolve().parent / "logs"
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            self._session_log_path = logs_dir / f"spcdb_gui_{ts}.log"
        except Exception:
            self._session_log_path = None

        # sources: row_iid -> DiscIndex
        self._base_idx: Optional[DiscIndex] = None
        self._src_indexes: Dict[str, DiscIndex] = {}

        # songs model
        self._songs: List[SongAgg] = []
        self._selected_song_ids: Set[int] = set()
        # Songs tree view state (v0.5.6a)
        self._song_group_open_state: Dict[str, bool] = {}
        self._song_tree_last_focus: Optional[str] = None
        # conflict detection/resolution
        self._conflicts: Dict[int, List[SongOccur]] = {}
        self._conflict_choices: Dict[int, str] = {}
        # per-disc song metadata cache: input_path -> {song_id: (title, artist)}
        self._disc_song_cache: Dict[str, Dict[int, Tuple[str, str]]] = {}

        # Persistent cache stale tracking (v0.5.8d)
        self._base_index_stale = False
        self._stale_source_iids: Set[str] = set()
        self._stale_index_queue = []  # list[(kind, input_path, row_iid)]
        self._stale_index_inflight = False
        self._stale_current = None  # tuple(kind, row_iid, input_path)

        # Per-disc song ID sets (for selected/total counts in Sources)
        self._disc_song_ids_by_label: Dict[str, Set[int]] = {}
        self._base_song_ids: Set[int] = set()
        self._base_product_display: str = '(unknown)'

        # filters
        self.filter_text_var = tk.StringVar(value=str(_s.get("filter_text", "")) or "")
        self.filter_source_var = tk.StringVar(value=str(_s.get("filter_source", "All")) or "All")
        self.filter_selected_only_var = tk.BooleanVar(value=bool(_s.get("filter_selected_only", False)))

        self._filter_job: Optional[str] = None
        self._search_entry = None

        self._build_ui()

        # Load last build summary (v0.5.5b)
        self._refresh_last_build_ui()
        self._update_build_panels()

        # Restore saved sources list (no auto-index in v0.5.4a)
        self._restore_saved_sources()

        # v0.5.8d: try to restore cached disc indexes/song metadata for faster reopen
        try:
            self._restore_cached_indexes()
        except Exception:
            pass

        # Helpful hint if Base path is pre-filled but not indexed yet
        try:
            if self.base_path_var.get().strip() and self._base_idx is None:
                self.base_info_var.set("Base: saved path (press Enter or Browse to index)")
                self._set_base_badge("NOT INDEXED", "neutral")
        except Exception:
            pass


        try:
            if not self.base_path_var.get().strip() and self._base_idx is None:
                self._set_base_badge("NOT SET", "neutral")
        except Exception:
            pass

        try:
            self._set_sources_dropdown()
        except Exception:
            pass

        # v0.5.4b: Startup auto-index (no auto-extract)
        try:
            self.after(350, self._startup_auto_index_if_ready)
        except Exception:
            pass


        self._bind_shortcuts()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self.after(100, self._poll_queue)




    

    # -------- Settings persistence (v0.5.4a) --------

    def _collect_gui_settings(self) -> dict:
        sources: List[Dict[str, str]] = []
        try:
            if hasattr(self, "src_tree") and self.src_tree is not None:
                for iid in self.src_tree.get_children():
                    try:
                        path = str(self.src_tree.set(iid, "path") or "").strip()
                        label = str(self.src_tree.set(iid, "label") or "").strip()
                    except Exception:
                        continue
                    if not path:
                        continue
                    sources.append({"path": path, "label": label or Path(path).name})
        except Exception:
            sources = []

        return {
            "dark_mode": bool(self._dark_mode_var.get()),
            "base_path": str(getattr(self, "base_path_var", tk.StringVar(value="")).get()).strip(),
            "sources": sources,
            "output_path": str(getattr(self, "output_path_var", tk.StringVar(value="")).get()).strip(),
            "output_path_user_set": bool(getattr(self, "_output_path_user_set", False)),
            "filter_text": str(getattr(self, "filter_text_var", tk.StringVar(value="")).get()),
            "filter_source": str(getattr(self, "filter_source_var", tk.StringVar(value="All")).get()) or "All",
            "filter_selected_only": bool(getattr(self, "filter_selected_only_var", tk.BooleanVar(value=False)).get()),
            "extractor_exe_path": str(getattr(self, "extractor_exe_var", tk.StringVar(value="")).get()).strip(),
            "validate_write_report": bool(getattr(self, "validate_write_report_var", tk.BooleanVar(value=False)).get()),
            "preflight_before_build": bool(getattr(self, "preflight_before_build_var", tk.BooleanVar(value=False)).get()),
            "block_build_on_validate_errors": bool(getattr(self, "block_build_on_validate_errors_var", tk.BooleanVar(value=False)).get()),
            "allow_overwrite_output": bool(getattr(self, "allow_overwrite_output_var", tk.BooleanVar(value=False)).get()),
            "keep_backup_of_existing_output": bool(getattr(self, "keep_backup_of_existing_output_var", tk.BooleanVar(value=True)).get()),
        }

    def _debounced_persist_gui_state(self) -> None:
        try:
            if self._persist_job is not None:
                self.after_cancel(self._persist_job)
        except Exception:
            pass
        self._persist_job = self.after(280, self._persist_gui_state_now)

    def _persist_gui_state_now(self) -> None:
        self._persist_job = None
        try:
            s = _load_settings()
            s.update(self._collect_gui_settings())
            _save_settings(s)
        except Exception:
            pass

    def _restore_saved_sources(self) -> None:
        try:
            if not hasattr(self, "src_tree") or self.src_tree is None:
                return
            existing = set()
            for iid in self.src_tree.get_children():
                try:
                    existing.add(str(self.src_tree.set(iid, "path") or "").strip())
                except Exception:
                    pass

            s = _load_settings()
            raw = s.get("sources", [])
            if not isinstance(raw, list):
                return

            for item in raw:
                path = ""
                label = ""
                if isinstance(item, str):
                    path = item
                elif isinstance(item, dict):
                    path = str(item.get("path") or "")
                    label = str(item.get("label") or "")
                path = (path or "").strip()
                if not path or path in existing:
                    continue

                self._src_counter += 1
                iid = f"src_{self._src_counter}"
                if not label:
                    label = Path(path).name
                status = "not indexed"
                if path and not Path(path).exists():
                    status = "missing"
                self.src_tree.insert("", "end", iid=iid, values=(label, "(saved)", "", "", status, path))
                self._src_labels[iid] = label
                existing.add(path)
        except Exception:
            return

        # v0.5.8c: keep the sources count label in sync.
        try:
            self._update_source_disc_count()
        except Exception:
            pass


        # v0.5.8d: also attempt to restore cached disc indexes for fast reopen.


    def _restore_cached_indexes(self) -> None:
        """Restore cached disc indexes (and optional song metadata) if still valid."""
        # Reset stale tracking
        self._base_index_stale = False
        self._stale_source_iids = set()

        # ---- Base ----
        base_path = str(self.base_path_var.get() or '').strip()
        if base_path:
            bp = Path(base_path)
            if bp.exists():
                try:
                    idx, songs, stale, reason = _load_index_cache(base_path)
                    if idx is not None:
                        product = idx.product_desc or idx.product_code or '(unknown)'
                        if idx.product_code and idx.product_desc:
                            product = f"{idx.product_desc} [{idx.product_code}]"
                        self._base_idx = idx
                        self._base_product_display = product
                        total = len(songs) if songs else int(idx.song_count or 0)
                        self.base_info_var.set(f"Base: {product} | max bank {idx.max_bank} | sel 0/{total}")
                        self._set_base_badge('OK (cached)', 'ok')
                        if songs:
                            try:
                                self._disc_song_cache[idx.input_path] = songs
                                sids = set(songs.keys())
                                self._disc_song_ids_by_label['Base'] = sids
                                self._base_song_ids = set(sids)
                            except Exception:
                                pass
                    elif stale:
                        self._base_index_stale = True
                        self.base_info_var.set('Base: INDEX STALE (press Enter/Browse to reindex)')
                        self._set_base_badge('INDEX STALE', 'warn')
                        if reason:
                            self._log(f"Base cache stale: {reason}")
                except Exception as e:
                    self._log(f"Base cache restore failed: {e}")

        # ---- Sources ----
        try:
            for iid in self.src_tree.get_children(''):
                try:
                    folder = str(self.src_tree.set(iid, 'path') or '').strip()
                except Exception:
                    folder = ''
                if not folder:
                    continue
                fp = Path(folder)
                if not fp.exists():
                    continue

                try:
                    idx, songs, stale, reason = _load_index_cache(folder)
                    if idx is not None:
                        product = idx.product_desc or idx.product_code or '(unknown)'
                        if idx.product_code and idx.product_desc:
                            product = f"{idx.product_desc} [{idx.product_code}]"

                        self._src_indexes[iid] = idx
                        label = None
                        try:
                            label = self.src_tree.set(iid, 'label') or Path(folder).name
                        except Exception:
                            label = Path(folder).name
                        self._src_labels[iid] = label

                        total = len(songs) if songs else int(idx.song_count or 0)
                        try:
                            self.src_tree.item(iid, values=(label, product, str(idx.max_bank), f"0/{total}", 'OK (cached)', folder))
                        except Exception:
                            try:
                                self.src_tree.set(iid, 'status', 'OK (cached)')
                                self.src_tree.set(iid, 'product', product)
                                self.src_tree.set(iid, 'banks', str(idx.max_bank))
                                self.src_tree.set(iid, 'songs', f"0/{total}")
                            except Exception:
                                pass

                        if songs:
                            try:
                                self._disc_song_cache[idx.input_path] = songs
                                self._disc_song_ids_by_label[label] = set(songs.keys())
                            except Exception:
                                pass
                    elif stale:
                        self._stale_source_iids.add(iid)
                        try:
                            self.src_tree.set(iid, 'status', 'INDEX STALE')
                        except Exception:
                            pass
                        if reason:
                            self._log(f"Source cache stale ({Path(folder).name}): {reason}")
                except Exception:
                    # ignore cache failures for this disc
                    pass
        except Exception:
            pass

        try:
            self._update_disc_selection_counts()
        except Exception:
            pass

        try:
            self._update_source_disc_count()
        except Exception:
            pass

        try:
            self._update_reindex_stale_button()
        except Exception:
            pass

        # If base is available (cached), schedule a songs refresh.
        # This will also use the persistent song cache when available.
        if self._base_idx is not None:
            try:
                self.request_refresh_songs('startup-cache')
            except Exception:
                pass


    def _update_reindex_stale_button(self) -> None:
        """Enable/disable the Reindex stale button based on current stale state."""
        btn = getattr(self, "reindex_stale_btn", None)
        if btn is None:
            return

        # If a stale reindex batch is currently running, keep the button disabled.
        try:
            if bool(getattr(self, "_stale_index_inflight", False)) or bool(getattr(self, "_stale_index_queue", [])):
                btn.configure(text="Reindex stale (running)", state="disabled")
                return
        except Exception:
            pass

        stale_count = 0
        try:
            if bool(getattr(self, "_base_index_stale", False)):
                stale_count += 1
        except Exception:
            pass
        try:
            stale_count += len(getattr(self, "_stale_source_iids", set()) or set())
        except Exception:
            pass

        if stale_count <= 0:
            try:
                btn.configure(text="Reindex stale", state="disabled")
            except Exception:
                pass
            return

        try:
            btn.configure(text=f"Reindex stale ({stale_count})", state="normal")
        except Exception:
            pass



    # -------- Index cancellation (v0.5.8e3) --------

    def _index_activity(self) -> bool:
        # Index running or queued (startup/scan/stale/manual).
        try:
            if int(getattr(self, '_active_index_jobs', 0) or 0) > 0:
                return True
        except Exception:
            pass
        try:
            if bool(getattr(self, '_startup_index_inflight', False)) or bool(getattr(self, '_startup_index_queue', []) or []):
                return True
        except Exception:
            pass
        try:
            if bool(getattr(self, '_scan_index_inflight', False)) or bool(getattr(self, '_scan_index_queue', []) or []):
                return True
        except Exception:
            pass
        try:
            if bool(getattr(self, '_stale_index_inflight', False)) or bool(getattr(self, '_stale_index_queue', []) or []):
                return True
        except Exception:
            pass
        return False

    def _update_cancel_index_ui(self) -> None:
        btn = getattr(self, 'cancel_index_btn', None)
        if btn is None:
            return
        active = False
        try:
            active = self._index_activity()
        except Exception:
            active = False
        canceling = bool(getattr(self, '_index_cancel_requested', False))
        if canceling and active:
            try:
                btn.configure(text='Cancelling...', state='disabled')
            except Exception:
                pass
            return
        if active:
            try:
                btn.configure(text='Cancel Index', state='normal')
            except Exception:
                pass
        else:
            try:
                btn.configure(text='Cancel Index', state='disabled')
            except Exception:
                pass

    def _maybe_finish_index_cancel(self) -> None:
        if not bool(getattr(self, '_index_cancel_requested', False)):
            return
        try:
            if self._index_activity():
                return
        except Exception:
            pass
        try:
            self._index_cancel_requested = False
        except Exception:
            pass
        try:
            self._log('Cancel Index: complete.')
        except Exception:
            pass
        try:
            self._update_cancel_index_ui()
        except Exception:
            pass

    def _cancel_index(self) -> None:
        # Disc-boundary cancel: clear queued index tasks; allow current disc to finish.
        try:
            startup_cleared = len(getattr(self, '_startup_index_queue', []) or [])
        except Exception:
            startup_cleared = 0
        try:
            scan_cleared = len(getattr(self, '_scan_index_queue', []) or [])
        except Exception:
            scan_cleared = 0
        try:
            stale_cleared = len(getattr(self, '_stale_index_queue', []) or [])
        except Exception:
            stale_cleared = 0

        try:
            self._index_cancel_requested = True
        except Exception:
            pass

        # Clear queued tasks (do not interrupt the currently running index job).
        try:
            self._startup_index_queue = []
        except Exception:
            pass
        try:
            self._scan_index_queue = []
        except Exception:
            pass
        try:
            self._stale_index_queue = []
        except Exception:
            pass

        msg = f'Cancel Index requested: cleared queued discs (startup {startup_cleared}, scan {scan_cleared}, stale {stale_cleared}).'
        running = False
        try:
            running = self._index_activity()
        except Exception:
            running = False
        if running:
            msg += ' Current disc will finish, then indexing will stop.'
        else:
            msg += ' No indexing is currently running.'
        try:
            self._log(msg)
        except Exception:
            pass

        # If nothing is running now, clear the cancel state immediately.
        try:
            if not self._index_activity():
                self._index_cancel_requested = False
                self._log('Cancel Index: queues cleared.')
        except Exception:
            pass

        try:
            self._update_cancel_index_ui()
        except Exception:
            pass


    # ---- Extraction cancellation (v0.5.8e4) ----

    def _extract_activity(self) -> bool:
        try:
            if int(getattr(self, '_active_extract_jobs', 0) or 0) > 0:
                return True
        except Exception:
            pass
        try:
            if bool(getattr(self, '_extract_queue', []) or []):
                return True
        except Exception:
            pass
        return False

    def _update_cancel_extract_ui(self) -> None:
        btn = getattr(self, 'cancel_extract_btn', None)
        if btn is None:
            return
        active = False
        try:
            active = self._extract_activity()
        except Exception:
            active = False
        canceling = bool(getattr(self, '_extract_cancel_requested', False))
        if canceling and active:
            try:
                btn.configure(text='Cancelling...', state='disabled')
            except Exception:
                pass
            return
        if active:
            try:
                btn.configure(text='Cancel Extract', state='normal')
            except Exception:
                pass
        else:
            try:
                btn.configure(text='Cancel Extract', state='disabled')
            except Exception:
                pass

    def _maybe_finish_extract_cancel(self) -> None:
        if not bool(getattr(self, '_extract_cancel_requested', False)):
            return
        try:
            if self._extract_activity():
                return
        except Exception:
            pass
        try:
            self._extract_cancel_requested = False
        except Exception:
            pass
        try:
            self._log('Cancel Extract: complete.')
        except Exception:
            pass
        try:
            self._update_cancel_extract_ui()
        except Exception:
            pass

    def _cancel_extract(self) -> None:
        # PKD-boundary cancel: clear queued extraction tasks; allow current extraction to finish.
        q = list(getattr(self, '_extract_queue', []) or [])
        queued_cleared = len(q)
        queued_iids = [iid for (iid, _p) in q]

        try:
            self._extract_cancel_requested = True
        except Exception:
            pass

        try:
            self._extract_queue = []
        except Exception:
            pass

        # Restore queued rows back to a neutral "needs extraction" state.
        for iid in queued_iids:
            try:
                if str(self.src_tree.set(iid, 'status') or '').strip().lower() != 'extracting…':
                    self.src_tree.set(iid, 'status', 'needs extraction')
            except Exception:
                pass

        msg = f'Cancel Extract requested: cleared queued discs ({queued_cleared}).'
        running = False
        try:
            running = self._extract_activity()
        except Exception:
            running = False
        if running:
            msg += ' Current extraction will finish, then extraction will stop.'
        else:
            msg += ' No extraction is currently running.'
        try:
            self._log(msg)
        except Exception:
            pass

        # If nothing is running now, clear the cancel state immediately.
        try:
            if not self._extract_activity():
                self._extract_cancel_requested = False
                self._log('Cancel Extract: queues cleared.')
        except Exception:
            pass

        try:
            self._update_cancel_extract_ui()
        except Exception:
            pass



    # ---- Build cancellation (v0.5.8e5) ----

    def _update_cancel_build_ui(self) -> None:
        btn = getattr(self, 'cancel_build_btn', None)
        if btn is None:
            return
        running = bool(getattr(self, '_build_running', False))
        canceling = bool(getattr(self, '_build_cancel_requested', False))
        if running and canceling:
            try:
                btn.configure(text='Cancelling...', state='disabled')
            except Exception:
                pass
            return
        if running:
            try:
                btn.configure(text='Cancel Build', state='normal')
            except Exception:
                pass
        else:
            try:
                btn.configure(text='Cancel Build', state='disabled')
            except Exception:
                pass

    def _cancel_build(self) -> None:
        if not bool(getattr(self, '_build_running', False)):
            return
        if bool(getattr(self, '_build_cancel_requested', False)):
            return
        try:
            self._build_cancel_requested = True
        except Exception:
            pass
        try:
            self._log('Cancel Build requested: will stop after the current step completes.')
        except Exception:
            pass
        try:
            self._update_cancel_build_ui()
        except Exception:
            pass

    # ---- Disc validation helper (v0.5.9a2) ----

    def _update_validate_ui(self) -> None:
        btn = getattr(self, 'validate_selected_btn', None)
        copy_btn = getattr(self, 'copy_validate_btn', None)
        if btn is None:
            return
        running = bool(getattr(self, '_disc_validate_running', False))
        if running:
            try:
                btn.configure(text='Validating...', state='disabled')
            except Exception:
                pass
        else:
            try:
                btn.configure(text='Validate Selected', state='normal')
            except Exception:
                pass

        if copy_btn is not None:
            try:
                if running:
                    copy_btn.configure(state='disabled')
                else:
                    txt = str(getattr(self, '_last_validate_report_text', '') or '').strip()
                    copy_btn.configure(state=('normal' if txt else 'disabled'))
            except Exception:
                pass

    def _copy_validate_report(self) -> None:
        txt = str(getattr(self, '_last_validate_report_text', '') or '')
        if not txt.strip():
            return
        try:
            self.clipboard_clear()
            self.clipboard_append(txt)
            self._log('[validate] Copied validate report to clipboard.')
        except Exception:
            pass

    def _collect_validate_targets(self) -> list[tuple[str, str]]:
        targets: list[tuple[str, str]] = []
        selected = ()
        try:
            selected = self.src_tree.selection()
        except Exception:
            selected = ()
        if selected:
            for iid in selected:
                try:
                    label = str(self._src_labels.get(iid) or self.src_tree.set(iid, 'label') or 'Source').strip()
                except Exception:
                    label = 'Source'
                try:
                    pth = str(self.src_tree.set(iid, 'path') or '').strip()
                except Exception:
                    pth = ''
                if pth:
                    targets.append((label or 'Source', pth))
        else:
            # No selection: validate Base (if set) + all Sources.
            try:
                base_path = str(self.base_path_var.get() or '').strip()
            except Exception:
                base_path = ''
            if base_path:
                targets.append(('Base', base_path))
            try:
                for iid in self.src_tree.get_children():
                    try:
                        label = str(self._src_labels.get(iid) or self.src_tree.set(iid, 'label') or 'Source').strip()
                    except Exception:
                        label = 'Source'
                    try:
                        pth = str(self.src_tree.set(iid, 'path') or '').strip()
                    except Exception:
                        pth = ''
                    if pth:
                        targets.append((label or 'Source', pth))
            except Exception:
                pass

        # De-dupe by normalized path (keep first label)
        out: list[tuple[str, str]] = []
        seen: set[str] = set()
        for label, pth in targets:
            try:
                norm = _normalize_input_path(pth)
            except Exception:
                norm = pth
            key = norm or pth
            if key in seen:
                continue
            seen.add(key)
            out.append((label, pth))
        return out

    def _validate_selected_discs_async(self) -> None:
        if bool(getattr(self, '_disc_validate_running', False)):
            return
        targets = self._collect_validate_targets()
        if not targets:
            try:
                self._log('[validate] Nothing to validate.')
            except Exception:
                pass
            return

        try:
            self._disc_validate_running = True
        except Exception:
            pass
        try:
            self._last_validate_report_text = ''
        except Exception:
            pass
        try:
            self._update_validate_ui()
        except Exception:
            pass

        try:
            self._log(f"[validate] Validating {len(targets)} disc(s)...")
            if bool(getattr(self, 'validate_write_report_var', tk.BooleanVar(value=False)).get()):
                self._log('[validate] Write report file is enabled: will write validate_report.txt into the Output folder when done.')
        except Exception:
            pass

        t = threading.Thread(target=self._validate_discs_worker, args=(targets,), daemon=True)
        t.start()

    def _validate_discs_worker(self, targets: list[tuple[str, str]]) -> None:
        try:
            def _emit(line: str) -> None:
                try:
                    self._queue.put(('disc_validate_log', ('[validate] ' + str(line)).rstrip()))
                except Exception:
                    pass

            results, report_text = validate_discs(targets, log_cb=_emit)
            self._queue.put(('disc_validate_done', (results, report_text)))
        except CancelledError as ce:
            self._queue.put(('disc_validate_err', str(ce)))
        except Exception as e:
            self._queue.put(('disc_validate_err', str(e)))
    def _write_validate_report_file(self, report_text: str) -> str:
        try:
            out_dir = str(getattr(self, 'output_path_var', tk.StringVar(value='')).get() or '').strip()
        except Exception:
            out_dir = ''
        if not out_dir:
            return ''
        try:
            od = Path(out_dir)
            if not od.exists() or not od.is_dir():
                return ''
            rp = od / 'validate_report.txt'
            rp.write_text(str(report_text), encoding='utf-8')
            return str(rp)
        except Exception:
            return ''

    def _handle_disc_validate_done(self, results: list[dict], report_text: str = '') -> None:
        try:
            self._disc_validate_running = False
        except Exception:
            pass

        try:
            self._last_validate_report_text = str(report_text or '')
        except Exception:
            pass

        try:
            self._update_validate_ui()
        except Exception:
            pass

        ok_n = 0
        warn_n = 0
        fail_n = 0
        try:
            for r in results or []:
                sev = str(r.get('severity', '') or '').upper()
                if sev == 'OK':
                    ok_n += 1
                elif sev == 'WARN':
                    warn_n += 1
                else:
                    fail_n += 1
        except Exception:
            pass

        try:
            self._log(f"[validate] Done. OK={ok_n}, WARN={warn_n}, FAIL={fail_n}.")
        except Exception:
            pass

        # Optional report file
        try:
            write_on = bool(getattr(self, 'validate_write_report_var', tk.BooleanVar(value=False)).get())
        except Exception:
            write_on = False

        if write_on and str(report_text or '').strip():
            rp = self._write_validate_report_file(str(report_text))
            if rp:
                try:
                    self._log(f"[validate] Wrote validate_report.txt: {rp}")
                except Exception:
                    pass
            else:
                try:
                    self._log('[validate] Write report file is enabled, but Output folder is not set or does not exist. Skipping.')
                except Exception:
                    pass

    def _handle_disc_validate_err(self, err: str) -> None:
        try:
            self._disc_validate_running = False
        except Exception:
            pass
        try:
            self._last_validate_report_text = ''
        except Exception:
            pass
        try:
            self._update_validate_ui()
        except Exception:
            pass
        try:
            self._log(f"[validate] ERROR: {err}")
        except Exception:
            pass

    def _reindex_stale_all(self) -> None:
        """Re-index Base + Sources that are marked INDEX STALE (sequentially)."""
        try:
            if self._any_long_job_running():
                messagebox.showinfo("Reindex stale", "Please wait for current jobs to finish before reindexing stale discs.")
                return
        except Exception:
            pass

        tasks: list[tuple[str, str, Optional[str]]] = []

        # Base (if stale)
        base_path = str(getattr(self, "base_path_var", tk.StringVar(value="")).get() or "").strip()
        try:
            if bool(getattr(self, "_base_index_stale", False)) and base_path:
                tasks.append(("base", base_path, None))
        except Exception:
            pass

        # Sources (if stale)
        stale_iids: list[str] = []
        try:
            stale_iids = sorted(list(getattr(self, "_stale_source_iids", set()) or set()))
        except Exception:
            stale_iids = []

        for iid in stale_iids:
            try:
                folder = str(self.src_tree.set(iid, "path") or "").strip()
            except Exception:
                folder = ""
            if not folder:
                continue
            tasks.append(("source", folder, iid))

        # Keep stale markers until each disc successfully reindexes (cleared in _handle_index_ok).

        if not tasks:
            try:
                self._update_reindex_stale_button()
            except Exception:
                pass
            return

        self._stale_index_queue = list(tasks)
        self._stale_index_inflight = False
        self._stale_current = None

        try:
            self._log(f"Reindex stale: queued {len(tasks)} disc(s).")
        except Exception:
            pass

        try:
            self._update_reindex_stale_button()
        except Exception:
            pass

        self._stale_kick_next_index()

    def _stale_kick_next_index(self) -> None:
        if bool(getattr(self, "_stale_index_inflight", False)):
            return
        q = list(getattr(self, "_stale_index_queue", []) or [])
        if not q:
            try:
                if bool(getattr(self, "_index_cancel_requested", False)):
                    self._log("Reindex stale: cancelled.")
                else:
                    self._log("Reindex stale: complete.")
            except Exception:
                pass
            try:
                self._update_reindex_stale_button()
            except Exception:
                pass
            try:
                self.request_refresh_songs("reindex-stale")
            except Exception:
                pass
            try:
                self._maybe_finish_index_cancel()
            except Exception:
                pass
            try:
                self._update_cancel_index_ui()
            except Exception:
                pass
            return

        kind, input_path, row_iid = q.pop(0)
        self._stale_index_queue = q
        self._stale_index_inflight = True
        self._stale_current = (kind, row_iid, input_path)

        if kind == "base":
            try:
                self.base_info_var.set("Base: reindexing stale…")
            except Exception:
                pass
            self._set_base_badge("INDEXING…", "neutral")
            try:
                self._progress_update("Indexing", "Base (stale)", indeterminate=True)
            except Exception:
                pass
            try:
                self._log(f"Reindex stale: indexing base: {input_path}")
            except Exception:
                pass
        else:
            label = None
            try:
                if row_iid is not None:
                    label = self.src_tree.set(row_iid, "label") or Path(input_path).name
                    self.src_tree.set(row_iid, "product", "(indexing...)")
                    self.src_tree.set(row_iid, "status", "indexing…")
            except Exception:
                label = None
            try:
                self._progress_update("Indexing", f"{label or Path(input_path).name} (stale)", indeterminate=True)
            except Exception:
                pass
            try:
                self._log(f"Reindex stale: indexing source: {input_path}")
            except Exception:
                pass

        self._start_index_job(kind=kind, input_path=input_path, row_iid=row_iid)

    def _stale_note_index_done(self, kind: str, row_iid: Optional[str], input_path: str) -> None:
        cur = getattr(self, "_stale_current", None)
        if not cur:
            return
        ck, ciid, cpath = cur
        try:
            if ck != kind:
                return
            if ciid != row_iid:
                return
            if str(Path(cpath).resolve()) != str(Path(input_path).resolve()):
                return
        except Exception:
            return

        self._stale_current = None
        self._stale_index_inflight = False
        try:
            self.after(60, self._stale_kick_next_index)
        except Exception:
            self._stale_kick_next_index()


    def _update_source_disc_count(self) -> None:
        """Update the small 'Sources: N' summary label."""
        if not hasattr(self, "src_tree") or self.src_tree is None:
            return
        total = 0
        ok = 0
        needs_extract = 0
        other = 0
        missing = 0
        stale = 0
        try:
            iids = list(self.src_tree.get_children(""))
        except Exception:
            iids = []
        total = len(iids)
        for iid in iids:
            try:
                st = str(self.src_tree.set(iid, "status") or "").strip().lower()
            except Exception:
                st = ""
            if not st:
                other += 1
            elif st.startswith("ok"):
                ok += 1
            elif 'stale' in st:
                stale += 1
            elif "needs extraction" in st or "extracting" in st:
                needs_extract += 1
            elif "missing" in st:
                missing += 1
            else:
                other += 1

        txt = f"Sources: {total} (OK: {ok}, Needs extract: {needs_extract}"
        if missing:
            txt += f", Missing: {missing}"
        if stale:
            txt += f", Stale: {stale}"
        if other:
            txt += f", Other: {other}"
        txt += ")"

        try:
            self.src_count_var.set(txt)
        except Exception:
            pass


    def _set_base_badge(self, text: str, level: str = "neutral") -> None:
        # Set the Base disc health badge text + style.
        try:
            self.base_badge_text_var.set(text)
        except Exception:
            pass
        try:
            self._base_badge_level = level
        except Exception:
            pass
        lbl = getattr(self, "base_badge_label", None)
        if lbl is None:
            return
        style = {
            "ok": "SPCDB.BadgeOK.TLabel",
            "warn": "SPCDB.BadgeWarn.TLabel",
            "err": "SPCDB.BadgeErr.TLabel",
        }.get(level, "SPCDB.BadgeNeutral.TLabel")
        try:
            lbl.configure(style=style)
        except Exception:
            pass

    def _on_close(self) -> None:
        self._persist_gui_state_now()
        try:
            self.destroy()
        except Exception:
            pass

    def _on_dark_mode_toggle(self) -> None:
        self._apply_theme(dark=self._dark_mode_var.get())
        self._debounced_persist_gui_state()

        # v0.5.8c: update sources count summary.
        try:
            self._update_source_disc_count()
        except Exception:
            pass

    def _on_allow_overwrite_toggle(self) -> None:
        """Toggle handler for 'Allow overwrite existing output'.

        Enables/disables the 'Keep backup of existing output' option and persists UI state.
        """
        try:
            allow = bool(getattr(self, 'allow_overwrite_output_var').get())
        except Exception:
            allow = False

        try:
            chk = getattr(self, 'keep_backup_of_existing_output_chk', None)
            if chk is not None:
                if allow:
                    try:
                        chk.state(['!disabled'])
                    except Exception:
                        try:
                            chk.configure(state='normal')
                        except Exception:
                            pass
                    # Recommended default: ensure backup remains enabled when overwrite is enabled.
                    try:
                        if not bool(getattr(self, 'keep_backup_of_existing_output_var').get()):
                            getattr(self, 'keep_backup_of_existing_output_var').set(True)
                    except Exception:
                        pass
                else:
                    try:
                        chk.state(['disabled'])
                    except Exception:
                        try:
                            chk.configure(state='disabled')
                        except Exception:
                            pass
        except Exception:
            pass

        try:
            self._debounced_persist_gui_state()
        except Exception:
            pass


    def _bind_shortcuts(self) -> None:
        try:
            self.bind_all("<Control-f>", self._on_ctrl_f, add=True)
            self.bind_all("<Control-F>", self._on_ctrl_f, add=True)
            self.bind_all("<Escape>", self._on_escape, add=True)
        except Exception:
            pass

    def _on_ctrl_f(self, _e=None):
        try:
            if getattr(self, "_search_entry", None) is not None:
                self._search_entry.focus_set()
                try:
                    self._search_entry.selection_range(0, tk.END)
                except Exception:
                    pass
                return "break"
        except Exception:
            pass
        return None

    def _on_escape(self, _e=None):
        try:
            if str(self.filter_text_var.get() or ""):
                self.filter_text_var.set("")
                self._debounced_persist_gui_state()
                try:
                    if getattr(self, "_search_entry", None) is not None:
                        self._search_entry.focus_set()
                except Exception:
                    pass
                return "break"
        except Exception:
            pass
        return None


    # -------- Job activity / safe refresh (v0.5.4b) --------

    def _any_long_job_running(self) -> bool:
        try:
            if getattr(self, "_build_running", False):
                return True
            if getattr(self, "_songs_refresh_running", False):
                return True
            if int(getattr(self, "_active_index_jobs", 0) or 0) > 0:
                return True
            if int(getattr(self, "_active_extract_jobs", 0) or 0) > 0:
                return True
        except Exception:
            return False
        return False

    def request_refresh_songs(self, reason: str = "auto") -> None:
        """Debounced refresh request; will only run when no extract/index/build is active."""
        try:
            self._pending_refresh_songs = True
            self._pending_refresh_reason = str(reason or "auto")
            if self._refresh_songs_job is not None:
                try:
                    self.after_cancel(self._refresh_songs_job)
                except Exception:
                    pass
                self._refresh_songs_job = None
            self._refresh_songs_job = self.after(350, self._maybe_run_refresh_songs)
        except Exception:
            pass

    def _maybe_run_refresh_songs(self) -> None:
        self._refresh_songs_job = None
        try:
            if not getattr(self, "_pending_refresh_songs", False):
                return

            # If base isn't indexed yet, wait a bit (unless base path is empty).
            if getattr(self, "_base_idx", None) is None:
                if not str(getattr(self, "base_path_var", tk.StringVar(value="")).get()).strip():
                    self._pending_refresh_songs = False
                    return
                self._refresh_songs_job = self.after(600, self._maybe_run_refresh_songs)
                return

            if self._any_long_job_running():
                self._refresh_songs_job = self.after(500, self._maybe_run_refresh_songs)
                return

            # Run once.
            self._pending_refresh_songs = False
            reason = str(getattr(self, "_pending_refresh_reason", "auto") or "auto")
            self._pending_refresh_reason = ""
            self._log(f"Auto-refreshing songs list ({reason})…")
            self._refresh_songs()
        except Exception:
            pass

    def _refresh_songs_safe(self) -> None:
        """Manual refresh button handler that respects the same safety rules."""
        if self._any_long_job_running():
            self._log("Busy (extract/index/build). Songs refresh will run when idle…")
            self.request_refresh_songs("manual")
            return
        self._refresh_songs()

    # -------- Startup auto-index (v0.5.4b) --------

    def _startup_auto_index_if_ready(self) -> None:
        # Run once per launch.
        if getattr(self, "_startup_auto_ran", False):
            return
        self._startup_auto_ran = True

        # Don't interfere if the user already kicked off work.
        if self._any_long_job_running():
            self._log("Startup: jobs already running; skipping auto-index.")
            return

        tasks: list[tuple[str, str, Optional[str]]] = []

        # Base first (if present and extracted enough to index)
        base = self.base_path_var.get().strip()
        if base:
            bp = Path(base)
            if not bp.exists():
                self.base_info_var.set("Base: missing")
                self._set_base_badge("MISSING", "err")
                self._log(f"Startup: saved base path missing: {bp}")
            else:
                # If base was restored from cache (and is OK), don't auto-index it again.
                try:
                    if getattr(self, "_base_idx", None) is not None and not bool(getattr(self, "_base_index_stale", False)):
                        pass
                    elif bool(getattr(self, "_base_index_stale", False)):
                        self._log("Startup: base cache is stale; leaving for manual reindex.")
                    else:
                        if self._needs_export(bp):
                            self.base_info_var.set("Base: needs extraction (missing FileSystem/Export)")
                            self._set_base_badge("NEEDS EXTRACT", "warn")
                            self._log("Startup: base needs extraction; not auto-extracting.")
                        else:
                            tasks.append(("base", str(bp), None))
                except Exception:
                    try:
                        if self._needs_export(bp):
                            self.base_info_var.set("Base: needs extraction (missing FileSystem/Export)")
                            self._set_base_badge("NEEDS EXTRACT", "warn")
                            self._log("Startup: base needs extraction; not auto-extracting.")
                        else:
                            tasks.append(("base", str(bp), None))
                    except Exception:
                        tasks.append(("base", str(bp), None))

        # Sources next
        try:
            for iid in self.src_tree.get_children():
                try:
                    folder = str(self.src_tree.set(iid, "path") or "").strip()
                except Exception:
                    folder = ""
                if not folder:
                    continue
                fp = Path(folder)
                if not fp.exists():
                    try:
                        self.src_tree.set(iid, "status", "missing")
                    except Exception:
                        pass
                    continue

                # If this source was restored from cache (and is OK), or is stale, skip auto-index.
                try:
                    if iid in getattr(self, "_src_indexes", {}):
                        continue
                    if iid in getattr(self, "_stale_source_iids", set()):
                        continue
                except Exception:
                    pass

                try:
                    if self._needs_export(fp):
                        try:
                            self.src_tree.set(iid, "status", "needs extraction")
                        except Exception:
                            pass
                        continue
                except Exception:
                    pass

                tasks.append(("source", str(fp), iid))
        except Exception:
            pass

        if not tasks:
            return

        self._startup_index_queue = list(tasks)
        self._log(f"Startup: auto-index queued {len(tasks)} disc(s).")
        self._startup_kick_next_index()

    def _startup_kick_next_index(self) -> None:
        if getattr(self, "_startup_index_inflight", False):
            return
        q = list(getattr(self, "_startup_index_queue", []) or [])
        if not q:
            if bool(getattr(self, "_index_cancel_requested", False)):
                self._log("Startup: auto-index cancelled.")
            else:
                self._log("Startup: auto-index complete.")
            # After indexing everything, refresh songs list once (safely).
            self.request_refresh_songs("startup")
            try:
                self._maybe_finish_index_cancel()
            except Exception:
                pass
            try:
                self._update_cancel_index_ui()
            except Exception:
                pass
            return

        kind, input_path, row_iid = q.pop(0)
        self._startup_index_queue = q
        self._startup_index_inflight = True
        self._startup_current = (kind, row_iid, input_path)

        if kind == "base":
            self.base_info_var.set("Base: indexing...")
            self._set_base_badge("INDEXING…", "neutral")
            self._progress_update("Indexing", "Base", indeterminate=True)
            self._log(f"Startup: indexing base: {input_path}")
        else:
            label = None
            try:
                if row_iid is not None:
                    label = self.src_tree.set(row_iid, "label") or Path(input_path).name
                    self.src_tree.set(row_iid, "product", "(indexing...)")
                    self.src_tree.set(row_iid, "status", "indexing…")
            except Exception:
                label = None
            self._progress_update("Indexing", label or Path(input_path).name, indeterminate=True)
            self._log(f"Startup: indexing source: {input_path}")

        self._start_index_job(kind=kind, input_path=input_path, row_iid=row_iid)

    def _startup_note_index_done(self, kind: str, row_iid: Optional[str], input_path: str) -> None:
        cur = getattr(self, "_startup_current", None)
        if not cur:
            return
        ck, ciid, cpath = cur
        try:
            if ck != kind:
                return
            if ciid != row_iid:
                return
            # Compare normalized paths
            if str(Path(cpath).resolve()) != str(Path(input_path).resolve()):
                return
        except Exception:
            # If any path logic fails, be conservative and don't advance.
            return

        self._startup_current = None
        self._startup_index_inflight = False
        try:
            self.after(60, self._startup_kick_next_index)
        except Exception:
            self._startup_kick_next_index()


    def _persist_extractor_path(self) -> None:
        self._debounced_persist_gui_state()

    def _browse_extractor_exe(self) -> None:
        start_dir = ""
        try:
            # Recommended location: ./extractor (not bundled).
            ensure_default_extractor_dir()
            cur = str(self.extractor_exe_var.get() or "").strip()
            if cur:
                cp = Path(cur)
                if cp.exists():
                    start_dir = str(cp.parent)
            if not start_dir:
                start_dir = str(default_extractor_dir())
        except Exception:
            start_dir = ""
        p = filedialog.askopenfilename(
            title="Select scee_london (or scee_london.exe)",
            filetypes=(
                [("Extractor (scee_london.exe)", "scee_london.exe"), ("Windows executable", "*.exe"), ("All files", "*.*")]
                if os.name == "nt"
                else [("Extractor (scee_london)", "scee_london*"), ("All files", "*.*")]
            ),
            initialdir=start_dir or None,
        )
        if not p:
            return
        self.extractor_exe_var.set(p)
        self._persist_extractor_path()

    def _get_disc_root_for_path(self, p: Path) -> Path:
        # If user selects PS3_GAME, go up one.
        if p.name.upper() == "PS3_GAME" and p.parent.exists():
            return p.parent
        # If they select inside PS3_GAME, try find PS3_GAME in parents and return its parent.
        for parent in [p] + list(p.parents):
            if parent.name.upper() == "PS3_GAME":
                return parent.parent
        return p

    def _needs_export(self, disc_path: Path) -> bool:
        """True if this input likely needs PKD extraction to produce a usable Export root.

        Be permissive: many discs index fine without Export/config.xml.
        """
        try:
            ri = resolve_input(str(disc_path))
            export_root = Path(ri.export_root)
        except Exception:
            disc_root = self._get_disc_root_for_path(disc_path)
            export_root = disc_root / "PS3_GAME" / "USRDIR" / "FileSystem" / "Export"

        if not export_root.exists() or not export_root.is_dir():
            return True

        # Strong signals Export is present/usable
        for name in ("config.xml", "covers.xml"):
            if (export_root / name).exists():
                return False

        # Any of these patterns also counts as "extracted enough to index"
        patterns = (
            "songs_*_0.xml",
            "acts_*_0.xml",
            "songlists_*.xml",
            "melodies_*.chc",
            "melodies_*.xml",
            "*.chc",
        )
        for pat in patterns:
            try:
                if any(export_root.glob(pat)):
                    return False
            except Exception:
                pass

        return True


    def _sanitize_console_line(self, s: str) -> str:
        """Remove control chars / ANSI escapes and replacement glyphs that show up as � in Tk."""
        try:
            # Strip ANSI escape sequences
            s = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", s)
            s = re.sub(r"\x1b\][^\x07]*\x07", "", s)  # OSC ... BEL
        except Exception:
            pass
        # Remove common replacement glyphs
        s = s.replace("\ufffd", "").replace("�", "")
        # Drop control characters except tab
        cleaned = []
        for ch in s:
            o = ord(ch)
            if ch == "\t":
                cleaned.append(ch)
            elif o < 32:
                continue
            else:
                cleaned.append(ch)
        return "".join(cleaned).strip()

    def _start_extract_job(self, kind: str, input_path: str, row_iid: Optional[str]) -> None:
        try:
            self._active_extract_jobs = int(getattr(self, "_active_extract_jobs", 0) or 0) + 1
        except Exception:
            self._active_extract_jobs = 1

        try:
            self._update_cancel_extract_ui()
        except Exception:
            pass

        def _log(msg: str) -> None:
            self._queue.put(("build_log", f"[extract] {msg}"))

        def _worker() -> None:
            try:
                disc_root = self._get_disc_root_for_path(Path(input_path))
                exe = self.extractor_exe_var.get().strip()
                if not exe:
                    raise RuntimeError("Extractor exe not set. Please select scee_london (or scee_london.exe) first.")
                exe_p = Path(exe)

                # Controller-driven extraction (Block D / 0.5.10a5). Keep GUI semantics:
                # do not interrupt an in-flight extraction when Cancel Extract is pressed.
                token = CancelToken(lambda: bool(getattr(self, "_extract_cancel_requested", False)))
                extract_disc_pkds(
                    exe_p,
                    disc_root,
                    _log,
                    cancel_token=token,
                    allow_mid_disc_cancel=False,
                )

                verify = verify_disc_extraction(disc_root, log_cb=_log)

                self._queue.put(("extract_ok", (kind, row_iid, str(disc_root), verify)))
            except Exception as e:
                self._queue.put(("extract_err", (kind, row_iid, input_path, str(e))))

        t = threading.Thread(target=_worker, daemon=True)
        t.start()

    def _extract_base(self) -> None:
        try:
            if bool(getattr(self, '_extract_cancel_requested', False)):
                self._extract_cancel_requested = False
        except Exception:
            pass
        try:
            self._update_cancel_extract_ui()
        except Exception:
            pass
        p = self.base_path_var.get().strip()
        if not p:
            messagebox.showerror("Extract base", "Base disc folder is not set.")
            return
        if not self._needs_export(Path(p)):
            messagebox.showinfo("Extract base", "Base disc already appears to be extracted (Export/config.xml found).")
            return
        self._start_extract_job("base", p, None)

    def _extract_selected_source(self) -> None:
        try:
            if bool(getattr(self, '_extract_cancel_requested', False)):
                self._extract_cancel_requested = False
        except Exception:
            pass
        try:
            self._update_cancel_extract_ui()
        except Exception:
            pass
        sel = list(self.src_tree.selection() or [])
        if not sel:
            messagebox.showerror("Extract source", "Select one or more source disc rows first.")
            return

        exe = self.extractor_exe_var.get().strip()
        if not exe:
            messagebox.showerror("Extract source", "Extractor exe is not set. Please select scee_london (or scee_london.exe) first.")
            return

        queued = 0
        already = 0
        missing = 0

        q: list[tuple[str, str]] = list(getattr(self, "_extract_queue", []) or [])
        q_set = {iid for (iid, _p) in q}

        for iid in sel:
            folder = str(self.src_tree.set(iid, "path") or "").strip()
            if not folder:
                missing += 1
                continue
            try:
                if not self._needs_export(Path(folder)):
                    already += 1
                    continue
            except Exception:
                # If we can't determine, still queue it.
                pass

            if iid in q_set:
                continue
            q.append((iid, folder))
            q_set.add(iid)
            queued += 1
            try:
                # Light feedback while queued.
                if str(self.src_tree.set(iid, "status") or "").strip().lower() != "extracting…":
                    self.src_tree.set(iid, "status", "needs extraction")
            except Exception:
                pass

        self._extract_queue = q

        try:
            self._update_cancel_extract_ui()
        except Exception:
            pass

        try:
            self._update_source_disc_count()
        except Exception:
            pass

        if queued == 0:
            if missing:
                messagebox.showinfo("Extract source", "No extractable discs selected (some rows are missing a path).")
            else:
                messagebox.showinfo("Extract source", "Selected disc(s) already appear to be extracted (or are already queued).")
            return

        self._log(f"[extract] Queued {queued} source disc(s) for extraction.")
        try:
            self.after(50, self._kick_next_extract_queue)
        except Exception:
            self._kick_next_extract_queue()


    def _kick_next_extract_queue(self) -> None:
        """Start the next queued source extraction when no other extract is running."""
        try:
            if bool(getattr(self, '_extract_cancel_requested', False)):
                return
        except Exception:
            pass
        try:
            if getattr(self, "_build_running", False):
                # Avoid kicking extraction during a build.
                self.after(400, self._kick_next_extract_queue)
                return
        except Exception:
            pass

        try:
            if int(getattr(self, "_active_extract_jobs", 0) or 0) > 0:
                return
        except Exception:
            return

        q: list[tuple[str, str]] = list(getattr(self, "_extract_queue", []) or [])
        if not q:
            try:
                self._update_cancel_extract_ui()
            except Exception:
                pass
            try:
                self.after(180, self._maybe_finish_extract_cancel)
            except Exception:
                pass
            return

        iid, folder = q.pop(0)
        self._extract_queue = q

        label = None
        try:
            label = self.src_tree.set(iid, "label") or Path(folder).name
            self.src_tree.set(iid, "status", "extracting…")
        except Exception:
            label = label or Path(folder).name

        self._progress_update("Extracting PKD", label or "Source", indeterminate=True)
        self._start_extract_job("source", folder, iid)

    def _index_selected_source(self) -> None:
        sel = self.src_tree.selection()
        if not sel:
            messagebox.showerror("Index source", "Select a source disc row first.")
            return
        iid = sel[0]
        folder = self.src_tree.set(iid, "path")
        if not folder:
            messagebox.showerror("Index source", "Source disc path missing.")
            return

        label = self.src_tree.set(iid, "label") or Path(folder).name
        try:
            self.src_tree.set(iid, "product", "(indexing...)")
            self.src_tree.set(iid, "status", "indexing…")
        except Exception:
            pass

        # If the selected folder isn't extracted yet, extract first (then we'll index on extract_ok).
        try:
            if self._needs_export(Path(folder)):
                exe = self.extractor_exe_var.get().strip()
                if exe:
                    try:
                        self.src_tree.set(iid, "status", "extracting…")
                    except Exception:
                        pass
                    try:
                        if bool(getattr(self, '_extract_cancel_requested', False)):
                            self._extract_cancel_requested = False
                    except Exception:
                        pass
                    try:
                        self._update_cancel_extract_ui()
                    except Exception:
                        pass
                    self._log(f"[extract] Source needs extraction; starting extractor… ({folder})")
                    self._progress_update("Extracting PKD", label, indeterminate=True)
                    self._start_extract_job("source", folder, iid)
                    try:
                        self._update_cancel_extract_ui()
                    except Exception:
                        pass
                    self._debounced_persist_gui_state()
                    return
        except Exception:
            pass

        self._progress_update("Indexing", label, indeterminate=True)
        self._log(f"Indexing source: {folder}")
        self._start_index_job(kind="source", input_path=folder, row_iid=iid)
        self._debounced_persist_gui_state()

    def _apply_theme(self, dark: bool) -> None:
        """Apply a cohesive dark/light theme to ttk + tk widgets."""
        # Use a ttk theme that respects Style.configure.
        try:
            self._style.theme_use("clam")
        except Exception:
            pass

        if dark:
            bg = "#141414"
            fg = "#e8e8e8"
            muted = "#b8b8b8"
            field_bg = "#1e1e1e"
            border = "#303030"
            sel_bg = "#3b82f6"
            sel_fg = "#ffffff"
            btn_bg = "#1a1a1a"
            btn_active = "#232323"
        else:
            bg = "#f3f3f3"
            fg = "#111111"
            muted = "#444444"
            field_bg = "#ffffff"
            border = "#c9c9c9"
            sel_bg = "#2563eb"
            sel_fg = "#ffffff"
            btn_bg = "#f3f3f3"
            btn_active = "#e7e7e7"

        try:
            self.configure(background=bg)
        except Exception:
            pass

        s = self._style

        # Global defaults (helps catch widgets we didn't style explicitly)
        s.configure(".", background=bg, foreground=fg)

        # Containers
        s.configure("TFrame", background=bg)
        s.configure("TPanedwindow", background=bg)

        # Labels / group boxes
        s.configure("TLabel", background=bg, foreground=fg)
        s.configure("TLabelframe", background=bg, foreground=fg, bordercolor=border, lightcolor=border, darkcolor=border)
        s.configure("TLabelframe.Label", background=bg, foreground=fg)

        # Buttons
        s.configure("TButton", background=btn_bg, foreground=fg, bordercolor=border, focusthickness=1, focuscolor=border)
        s.map(
            "TButton",
            background=[("active", btn_active), ("pressed", btn_active), ("disabled", bg)],
            foreground=[("disabled", muted)],
        )

        # Toggles
        s.configure("TCheckbutton", background=bg, foreground=fg)
        s.configure("TRadiobutton", background=bg, foreground=fg)

        # Separators
        s.configure("TSeparator", background=border)

        # Inputs
        s.configure("TEntry", fieldbackground=field_bg, background=field_bg, foreground=fg, bordercolor=border)
        s.map("TEntry", fieldbackground=[("disabled", field_bg), ("readonly", field_bg)])

        s.configure("TCombobox", fieldbackground=field_bg, background=field_bg, foreground=fg, bordercolor=border)
        s.map("TCombobox", fieldbackground=[("readonly", field_bg)], foreground=[("readonly", fg)])

        # Scrollbars (dark mode contrast)
        try:
            s.configure("TScrollbar", background=btn_bg, troughcolor=bg, bordercolor=border, arrowcolor=fg)
            s.map(
                "TScrollbar",
                background=[("active", btn_active), ("pressed", btn_active)],
                troughcolor=[("active", bg), ("pressed", bg)],
            )
        except Exception:
            pass

        # Progressbar (more visible in dark mode)
        try:
            s.configure(
                "SPCDB.Horizontal.TProgressbar",
                troughcolor=field_bg,
                background=sel_bg,
                lightcolor=sel_bg,
                darkcolor=sel_bg,
                bordercolor=border,
                thickness=14,
            )
        except Exception:
            pass


        # Badges (Base health) (v0.5.5a)
        try:
            s.configure("SPCDB.BadgeNeutral.TLabel", background=field_bg, foreground=muted, padding=(8, 2))
            if dark:
                ok_bg, ok_fg = "#123c22", "#b7f7c8"
                warn_bg, warn_fg = "#4a2a0a", "#ffddb0"
                err_bg, err_fg = "#4a0f14", "#ffb4bf"
            else:
                ok_bg, ok_fg = "#d1fae5", "#065f46"
                warn_bg, warn_fg = "#ffedd5", "#9a3412"
                err_bg, err_fg = "#fee2e2", "#991b1b"
            s.configure("SPCDB.BadgeOK.TLabel", background=ok_bg, foreground=ok_fg, padding=(8, 2))
            s.configure("SPCDB.BadgeWarn.TLabel", background=warn_bg, foreground=warn_fg, padding=(8, 2))
            s.configure("SPCDB.BadgeErr.TLabel", background=err_bg, foreground=err_fg, padding=(8, 2))
            s.configure("SPCDB.Issues.TLabel", background=warn_bg, foreground=warn_fg, padding=(8, 4))
        except Exception:
            pass

        # Tables
        s.configure(
            "Treeview",
            background=field_bg,
            fieldbackground=field_bg,
            foreground=fg,
            bordercolor=border,
            lightcolor=border,
            darkcolor=border,
            rowheight=22,
        )
        s.map("Treeview", background=[("selected", sel_bg)], foreground=[("selected", sel_fg)])

        s.configure("Treeview.Heading", background=btn_bg, foreground=fg, relief="flat")
        s.map("Treeview.Heading", background=[("active", btn_active)], foreground=[("active", fg)])

        self._theme_colors = {
            "bg": bg,
            "fg": fg,
            "muted": muted,
            "field_bg": field_bg,
            "border": border,
            "sel_bg": sel_bg,
            "sel_fg": sel_fg,
        }

        self._post_apply_theme()
        # Ensure the full UI is visible on first open.
        self.after(60, self._fit_window_to_content)

    def _post_apply_theme(self) -> None:
        """Apply theme colors to tk widgets that aren't covered by ttk styles."""
        colors = getattr(self, "_theme_colors", None)
        if not colors:
            return
        fg = colors["fg"]
        field_bg = colors["field_bg"]
        border = colors["border"]

        # log Text
        if hasattr(self, "log_text") and self.log_text is not None:
            try:
                self.log_text.configure(
                    background=field_bg,
                    foreground=fg,
                    insertbackground=fg,
                    relief="solid",
                    bd=1,
                    highlightthickness=1,
                    highlightbackground=border,
                )
            except Exception:
                pass

    def _build_ui(self) -> None:


        root = ttk.Frame(self, padding=8)
        root.pack(fill=tk.BOTH, expand=True)

        # Compact banner (single line) + theme toggle
        banner_row = ttk.Frame(root)
        banner_row.pack(fill=tk.X)

        ttk.Checkbutton(
            banner_row,
            text="Dark mode",
            variable=self._dark_mode_var,
            command=self._on_dark_mode_toggle,
        ).pack(side=tk.RIGHT)

        ttk.Separator(root).pack(fill=tk.X, pady=6)

        # Two-column layout
        paned = ttk.Panedwindow(root, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True)

        left = ttk.Frame(paned, padding=0)
        right = ttk.Frame(paned, padding=0)
        paned.add(left, weight=1)
        paned.add(right, weight=4)

        # LEFT: Sources + Status + Output + Log (collapsible)
        sources_frame = ttk.LabelFrame(left, text="Base + Sources", padding=8)
        sources_frame.pack(fill=tk.X, expand=False)
        self._build_sources_tab(sources_frame)

        status_frame = ttk.LabelFrame(left, text="Status", padding=8)
        status_frame.pack(fill=tk.X, expand=False, pady=(8, 0))

        self.status_var = tk.StringVar(value="Status: Not validated yet.")
        ttk.Label(status_frame, textvariable=self.status_var, justify=tk.LEFT).grid(row=0, column=0, sticky="w")

        btns = ttk.Frame(status_frame)
        btns.grid(row=0, column=1, sticky="e")

        self.resolve_btn = ttk.Button(btns, text="Resolve…", command=self._open_conflict_resolver, state="disabled")
        self.resolve_btn.pack(side=tk.RIGHT, padx=(8, 0))
        ttk.Button(btns, text="Re-check", command=self._run_validation_async).pack(side=tk.RIGHT)
        # Progress (extract/index/build)
        self._progress_phase_var = tk.StringVar(value="Overall: Idle")
        self._progress_item_var = tk.StringVar(value="Step: —")

        # Progress flicker control + state
        self._progress_last_apply_ts = 0.0
        self._progress_after_id = None
        self._progress_pending = None

        # Build overall percent tracking
        try:
            self._build_overall_pct = 0.0
            self._build_overall_last_phase = None
        except Exception:
            pass
        self._phase_running = False
        self._item_running = False
        self._phase_mode = None
        self._item_mode = None
        self._item_last_max = None
        self._item_last_val = None

        # Step progress (top)
        self.step_label = ttk.Label(status_frame, textvariable=self._progress_item_var)
        self.step_label.grid(row=1, column=0, columnspan=2, sticky="w", pady=(6, 0))
        self.item_pb = ttk.Progressbar(status_frame, mode="determinate", style="SPCDB.Horizontal.TProgressbar")
        self.item_pb.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(2, 0))

        # Overall activity (bottom)
        self.overall_label = ttk.Label(status_frame, textvariable=self._progress_phase_var)
        self.overall_label.grid(row=3, column=0, columnspan=2, sticky="w", pady=(6, 0))
        self.phase_pb = ttk.Progressbar(status_frame, mode="determinate", style="SPCDB.Horizontal.TProgressbar")
        self.phase_pb.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(2, 0))

        # Tooltips
        _Tooltip(self.step_label, "Current step progress (X/Y when known; otherwise animates).")
        _Tooltip(self.item_pb, "Current step progress (X/Y when known; otherwise animates).")
        _Tooltip(self.overall_label, "Overall activity. Animates while extracting, indexing, refreshing, or building.")
        _Tooltip(self.phase_pb, "Overall activity. Animates while extracting, indexing, refreshing, or building.")

        # Ensure progress bars start empty.
        self._progress_reset()


        # Jobs panel removed in v0.5.8e2 (activity is reported in the Log).

        status_frame.columnconfigure(0, weight=1)

        out_frame = ttk.LabelFrame(left, text="Output", padding=8)
        out_frame.pack(fill=tk.X, expand=False, pady=(8, 0))

        ttk.Label(out_frame, text="Output folder:").grid(row=0, column=0, sticky="w")
        out_ent = ttk.Entry(out_frame, textvariable=self.output_path_var, width=42)
        out_ent.grid(row=0, column=1, sticky="ew", padx=(6, 6))
        out_ent.bind("<KeyRelease>", lambda _e: (self._mark_output_path_user_set(), self._debounced_persist_gui_state(), self._update_build_panels()))

        ttk.Button(out_frame, text="Browse...", command=self._browse_output_parent).grid(row=0, column=2, sticky="e")
        ttk.Button(out_frame, text="Open", command=self._open_output_folder).grid(row=0, column=3, sticky="e", padx=(6, 0))
        ttk.Button(out_frame, text="Copy", command=self._copy_output_path).grid(row=0, column=4, sticky="e", padx=(6, 0))

        self.readiness_label = ttk.Label(out_frame, textvariable=self.readiness_var, justify=tk.LEFT)
        self.readiness_label.grid(row=1, column=0, columnspan=5, sticky="w", pady=(6, 0))

        self.issues_row = ttk.Frame(out_frame)
        self.issues_row.grid(row=2, column=0, columnspan=5, sticky="ew", pady=(4, 0))
        try:
            self.issues_row.grid_remove()
        except Exception:
            pass
        self.issues_label = ttk.Label(
            self.issues_row,
            textvariable=self.issues_var,
            style="SPCDB.Issues.TLabel",
            justify=tk.LEFT,
            wraplength=420,
        )
        self.issues_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.view_issues_btn = ttk.Button(self.issues_row, text="View...", command=self._view_issues, state="disabled")
        self.view_issues_btn.pack(side=tk.RIGHT, padx=(8, 0))

        # Build workflow options
        try:
            self.preflight_before_build_var.get()
        except Exception:
            self.preflight_before_build_var = tk.BooleanVar(value=False)

        self.preflight_before_build_chk = ttk.Checkbutton(
            out_frame,
            text="Preflight before Build (validate discs)",
            variable=self.preflight_before_build_var,
            command=self._debounced_persist_gui_state,
        )
        self.preflight_before_build_chk.grid(row=3, column=0, columnspan=5, sticky="w", pady=(6, 0))

        # v0.5.9a5: optionally block build when preflight validate finds Errors
        try:
            self.block_build_on_validate_errors_var.get()
        except Exception:
            self.block_build_on_validate_errors_var = tk.BooleanVar(value=False)

        self.block_build_on_validate_errors_chk = ttk.Checkbutton(
            out_frame,
            text="Block Build when Validate has Errors",
            variable=self.block_build_on_validate_errors_var,
            command=self._debounced_persist_gui_state,
        )
        self.block_build_on_validate_errors_chk.grid(row=4, column=0, columnspan=5, sticky="w", pady=(2, 0))

        # v0.9.184: optionally allow overwriting an existing output folder (safe: keep backup by default).
        self.allow_overwrite_output_chk = ttk.Checkbutton(
            out_frame,
            text="Allow overwrite existing output",
            variable=self.allow_overwrite_output_var,
            command=self._on_allow_overwrite_toggle,
        )
        self.allow_overwrite_output_chk.grid(row=5, column=0, columnspan=5, sticky="w", pady=(2, 0))

        self.keep_backup_of_existing_output_chk = ttk.Checkbutton(
            out_frame,
            text="Keep backup of existing output (recommended)",
            variable=self.keep_backup_of_existing_output_var,
            command=self._debounced_persist_gui_state,
        )
        self.keep_backup_of_existing_output_chk.grid(row=6, column=0, columnspan=5, sticky="w", pady=(2, 0))

        # Initial enabled state.
        try:
            if not bool(self.allow_overwrite_output_var.get()):
                self.keep_backup_of_existing_output_chk.state(["disabled"])
        except Exception:
            pass

        self.build_btn = ttk.Button(out_frame, text="Build Selected", command=self._start_build_selected)
        self.build_btn.grid(row=7, column=0, columnspan=5, sticky="ew", pady=(6, 0))
        self._build_tooltip = _Tooltip(self.build_btn, "")

        self.last_build_row = ttk.Frame(out_frame)
        self.last_build_row.grid(row=8, column=0, columnspan=5, sticky="ew", pady=(6, 0))
        self.last_build_label = ttk.Label(self.last_build_row, textvariable=self.last_build_var, justify=tk.LEFT, wraplength=420)
        self.last_build_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.log_last_build_btn = ttk.Button(self.last_build_row, text="Log", command=self._open_last_build_log, state="disabled")
        self.log_last_build_btn.pack(side=tk.RIGHT, padx=(6, 0))
        self.report_last_build_btn = ttk.Button(self.last_build_row, text="Report", command=self._open_last_build_report, state="disabled")
        self.report_last_build_btn.pack(side=tk.RIGHT, padx=(6, 0))
        self.copy_last_build_btn = ttk.Button(self.last_build_row, text="Copy", command=self._copy_last_build_path, state="disabled")
        self.copy_last_build_btn.pack(side=tk.RIGHT, padx=(6, 0))
        self.open_last_build_btn = ttk.Button(self.last_build_row, text="Open last", command=self._open_last_build_folder, state="disabled")
        self.open_last_build_btn.pack(side=tk.RIGHT, padx=(6, 0))

        out_frame.columnconfigure(1, weight=1)

        # Log (open by default)
        log_controls = ttk.Frame(left)
        log_controls.pack(fill=tk.X, pady=(8, 0))

        self._log_visible = tk.BooleanVar(value=True)
        self._log_autoscroll = tk.BooleanVar(value=True)

        self.log_btn = ttk.Button(log_controls, text="Hide Log", command=self._toggle_log_visibility)
        self.log_btn.pack(side=tk.LEFT)

        ttk.Checkbutton(log_controls, text="Auto-scroll", variable=self._log_autoscroll).pack(side=tk.LEFT, padx=(10, 0))

        ttk.Button(log_controls, text="Copy", command=self._copy_log).pack(side=tk.RIGHT)
        ttk.Button(log_controls, text="Save…", command=self._save_log_as).pack(side=tk.RIGHT, padx=(8, 0))
        ttk.Button(log_controls, text="Clear", command=self._clear_log).pack(side=tk.RIGHT, padx=(8, 0))

        self.log_frame = ttk.LabelFrame(left, text="Log", padding=8)
        self.log_frame.pack(fill=tk.BOTH, expand=True, pady=(6, 0))

        self.log_text = tk.Text(self.log_frame, height=10, wrap="word")
        self.log_text.pack(fill=tk.BOTH, expand=True)
        self._post_apply_theme()

# RIGHT: Songs (main space)
        songs_frame = ttk.LabelFrame(right, text="Songs (tick to include)", padding=8)
        songs_frame.pack(fill=tk.BOTH, expand=True)
        self._build_songs_tab(songs_frame, show_refresh_button=True)

        self._log("Ready. Set Base disc, add source discs, then Refresh Songs List. Tick songs, then Build Selected.")
        self._update_status_from_validation()
        self._post_apply_theme()


    # -------- Sources tab --------


    def _build_sources_tab(self, parent: ttk.Frame) -> None:
        base_frame = ttk.LabelFrame(parent, text="Base Disc (template)", padding=8)
        base_frame.pack(fill=tk.X)

        ttk.Label(base_frame, text="Base disc folder (recommended: SingStar [BCES00011]; most discs work similarly—avoid MegaHits / Ultimate Party as Base; install SingStar 6.00 update + launch once):").grid(row=0, column=0, sticky="w")
        entry = ttk.Entry(base_frame, textvariable=self.base_path_var)
        entry.grid(row=1, column=0, sticky="ew", padx=(0, 8), pady=(6, 0))
        entry.bind("<Return>", lambda _e: self._index_base())

        entry.bind("<KeyRelease>", lambda _e: self._debounced_persist_gui_state())
        entry.bind("<FocusOut>", lambda _e: self._debounced_persist_gui_state())

        btn = ttk.Button(base_frame, text="Browse...", command=self._browse_base)
        btn.grid(row=1, column=1, sticky="e", pady=(6, 0))

        info = ttk.Label(base_frame, textvariable=self.base_info_var)
        info.grid(row=2, column=0, sticky="w", pady=(6, 0))

        # Base health badge (right)
        self.base_badge_label = ttk.Label(base_frame, textvariable=self.base_badge_text_var, style="SPCDB.BadgeNeutral.TLabel")
        self.base_badge_label.grid(row=2, column=1, sticky="e", pady=(6, 0))

        base_frame.columnconfigure(0, weight=1)

        src_frame = ttk.LabelFrame(parent, text="Source Discs (inputs)", padding=8)
        src_frame.pack(fill=tk.BOTH, expand=False)

        cols = ("label", "product", "banks", "songs", "status", "path")
        # v0.5.8c: allow multi-select so users can extract multiple discs in one go.
        self.src_tree = ttk.Treeview(src_frame, columns=cols, show="headings", height=7, selectmode="extended")
        self.src_tree.heading("label", text="Label")
        self.src_tree.heading("product", text="Product")
        self.src_tree.heading("banks", text="Max bank")
        self.src_tree.heading("songs", text="Sel/Total")
        self.src_tree.heading("status", text="Status")
        self.src_tree.heading("path", text="Path")

        self.src_tree.column("label", width=180, anchor="w")
        self.src_tree.column("product", width=260, anchor="w")
        self.src_tree.column("banks", width=80, anchor="center")
        self.src_tree.column("songs", width=80, anchor="center")
        self.src_tree.column("status", width=120, anchor="w")
        self.src_tree.column("path", width=400, anchor="w")

        self.src_tree.pack(fill=tk.BOTH, expand=True)

        # v0.5.8c: quick summary of how many source discs are loaded.
        self.src_count_var = tk.StringVar(value="Sources: 0")
        self.src_count_label = ttk.Label(src_frame, textvariable=self.src_count_var)
        self.src_count_label.pack(anchor="w", pady=(6, 0))

        actions_row = ttk.Frame(src_frame)
        actions_row.pack(fill=tk.X, pady=(8, 0))

        actions_left = ttk.Frame(actions_row)
        actions_left.pack(side=tk.LEFT)

        ttk.Button(actions_left, text="Add Disc…", command=self._add_source).pack(side=tk.LEFT)
        ttk.Button(actions_left, text="Add discs…", command=self._scan_sources_root).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(actions_left, text="Remove", command=self._remove_selected).pack(side=tk.LEFT, padx=(8, 0))

        actions_right = ttk.Frame(actions_row)
        actions_right.pack(side=tk.RIGHT)

        validate_group = ttk.Frame(actions_right)
        validate_group.pack(side=tk.LEFT, padx=(0, 8))

        self.validate_selected_btn = ttk.Button(validate_group, text="Validate Selected", command=self._validate_selected_discs_async)
        self.validate_selected_btn.pack(side=tk.LEFT)

        self.copy_validate_btn = ttk.Button(validate_group, text="Copy report", command=self._copy_validate_report, state="disabled")
        self.copy_validate_btn.pack(side=tk.LEFT, padx=(8, 0))

        try:
            self.validate_write_report_var.get()
        except Exception:
            self.validate_write_report_var = tk.BooleanVar(value=False)
        self.validate_write_report_chk = ttk.Checkbutton(validate_group, text="Write report file", variable=self.validate_write_report_var, command=self._debounced_persist_gui_state)
        self.validate_write_report_chk.pack(side=tk.LEFT, padx=(8, 0))

        self.reindex_stale_btn = ttk.Button(actions_right, text="Reindex stale", command=self._reindex_stale_all, state="disabled")
        self.reindex_stale_btn.pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(actions_right, text="Index Selected", command=self._index_selected_source).pack(side=tk.LEFT)
        self.cancel_index_btn = ttk.Button(actions_right, text="Cancel Index", command=self._cancel_index, state="disabled")
        self.cancel_index_btn.pack(side=tk.LEFT, padx=(8, 0))

        # Extraction controls (for non-extracted discs)
        ext_group = ttk.LabelFrame(src_frame, text="Extraction (advanced)", padding=8)
        ext_group.pack(fill=tk.X, pady=(8, 0))

        ext_row = ttk.Frame(ext_group)
        ext_row.pack(fill=tk.X)

        ttk.Label(ext_row, text="Extractor (scee_london / scee_london.exe):").pack(side=tk.LEFT)
        ext_ent = ttk.Entry(ext_row, textvariable=self.extractor_exe_var, width=42)
        ext_ent.pack(side=tk.LEFT, padx=(6, 6), fill=tk.X, expand=True)
        ext_ent.bind("<FocusOut>", lambda _e: self._persist_extractor_path())

        ttk.Button(ext_row, text="Browse...", command=self._browse_extractor_exe).pack(side=tk.LEFT)

        ext_btn_row = ttk.Frame(ext_group)
        ext_btn_row.pack(fill=tk.X, pady=(6, 0))

        ttk.Button(ext_btn_row, text="Extract Base", command=self._extract_base).pack(side=tk.LEFT)
        ttk.Button(ext_btn_row, text="Extract Selected", command=self._extract_selected_source).pack(side=tk.LEFT, padx=(8, 0))

        self.cancel_extract_btn = ttk.Button(ext_btn_row, text="Cancel Extract", command=self._cancel_extract, state="disabled")
        self.cancel_extract_btn.pack(side=tk.LEFT, padx=(8, 0))

        ttk.Label(ext_group, text="Tip: Add discs scans a folder and lists both extracted and unextracted discs.").pack(anchor="w", pady=(6, 0))

    def _toggle_log_visibility(self) -> None:
        try:
            vis = bool(self._log_visible.get())
        except Exception:
            vis = True
        if vis:
            # hide
            try:
                self.log_frame.pack_forget()
            except Exception:
                pass
            try:
                self._log_visible.set(False)
            except Exception:
                pass
            try:
                self.log_btn.configure(text="Show Log")
            except Exception:
                pass
        else:
            # show
            try:
                self.log_frame.pack(fill=tk.BOTH, expand=True, pady=(6, 0))
            except Exception:
                pass
            try:
                self._log_visible.set(True)
            except Exception:
                pass
            try:
                self.log_btn.configure(text="Hide Log")
            except Exception:
                pass

    def _copy_log(self) -> None:
        try:
            data = self.log_text.get("1.0", tk.END)
        except Exception:
            data = ""
        try:
            self.clipboard_clear()
            self.clipboard_append(data)
        except Exception:
            pass

    def _save_log_as(self) -> None:
        path = filedialog.asksaveasfilename(
            title="Save log",
            defaultextension=".log",
            filetypes=[("Log", "*.log"), ("Text", "*.txt"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            data = self.log_text.get("1.0", tk.END)
            Path(path).write_text(data, encoding="utf-8")
        except Exception as e:
            messagebox.showerror("Save log", str(e))

    def _clear_log(self) -> None:
        try:
            self.log_text.delete("1.0", tk.END)
        except Exception:
            pass

    def _progress_reset(self) -> None:
        # Reset to an "idle" empty state.
        try:
            self._progress_phase_var.set("Overall: Idle")
            self._progress_item_var.set("Step: —")
        except Exception:
            pass

        # Stop animations first (indeterminate can leave a chunk behind if not stopped)
        try:
            self.phase_pb.stop()
        except Exception:
            pass
        try:
            self.item_pb.stop()
        except Exception:
            pass

        # Force bars to an empty determinate 0 state.
        try:
            self.phase_pb.configure(mode="determinate", maximum=100, value=0)
            self.phase_pb["value"] = 0
        except Exception:
            pass
        try:
            self.item_pb.configure(mode="determinate", maximum=100, value=0)
            self.item_pb["value"] = 0
        except Exception:
            pass

        # Internal state
        self._phase_running = False
        self._item_running = False
        self._phase_mode = "determinate"
        self._item_mode = "determinate"
        self._item_last_max = None
        self._item_last_val = None
        self._progress_pending = None

        # Build overall percent tracking
        try:
            self._build_overall_pct = 0.0
            self._build_overall_last_phase = None
        except Exception:
            pass

        if getattr(self, "_progress_after_id", None) is not None:
            try:
                self.after_cancel(self._progress_after_id)
            except Exception:
                pass
            self._progress_after_id = None

        try:
            self.update_idletasks()
        except Exception:
            pass


    def _fit_window_to_content(self) -> None:
        """Size the window so the full layout is visible, capped to the screen."""
        try:
            self.update_idletasks()
            req_w = int(self.winfo_reqwidth())
            req_h = int(self.winfo_reqheight())
            scr_w = int(self.winfo_screenwidth())
            scr_h = int(self.winfo_screenheight())

            max_w = max(900, scr_w - 60)
            max_h = max(700, scr_h - 100)

            w = min(max(req_w + 20, 1200), max_w)
            h = min(max(req_h + 20, 760), max_h)

            x = max((scr_w - w) // 2, 0)
            y = max((scr_h - h) // 2, 0)
            self.geometry(f"{w}x{h}+{x}+{y}")
            self.minsize(min(w, 1200), min(h, 760))
        except Exception:
            try:
                self.geometry("1400x850")
            except Exception:
                pass


    def _progress_update(
        self,
        phase: str,
        item: str,
        *,
        indeterminate: bool = False,
        current: int | None = None,
        total: int | None = None,
    ) -> None:
        """Update progress bars + labels with flicker control."""
        data = (phase, item, indeterminate, current, total)

        now = time.time()
        if now - self._progress_last_apply_ts < 0.06:
            self._progress_pending = data
            if self._progress_after_id is None:
                self._progress_after_id = self.after(70, self._flush_progress_update)
            return

        self._apply_progress_update(data)
    def _flush_progress_update(self) -> None:
        try:
            self._progress_after_id = None
            data = self._progress_pending
            self._progress_pending = None
            if data is None:
                return
            self._apply_progress_update(data)
        except Exception:
            self._progress_after_id = None

    def _compute_build_overall_pct(
        self,
        phase: str,
        indeterminate: bool,
        current: int | None,
        total: int | None,
    ) -> int | None:
        """Compute a monotonic 0-100 overall build percentage from subset.py progress phases.

        Notes:
          - Most phases are indeterminate; we assign them a small fixed bump.
          - 'Copy songs' is the main determinate phase and drives most of the bar.
          - We keep this monotonic (never decreases) even if phases repeat per source disc.
        """
        try:
            key = re.sub(r"\s+", " ", str(phase or "").strip().lower())
        except Exception:
            key = ""
        # Phase weight ranges (start%, end%)
        ranges = {
            "copy": (0.0, 5.0),
            "prune": (5.0, 10.0),
            "import": (10.0, 15.0),
            "copy songs": (15.0, 70.0),
            "textures": (70.0, 80.0),
            "write": (80.0, 87.0),
            "melody": (87.0, 92.0),
            "chc": (92.0, 98.0),
            "config": (98.0, 99.0),
            "done": (100.0, 100.0),
            "build": (0.0, 0.0),
        }

        if key not in ranges:
            return None

        start, end = ranges[key]
        pct = end
        if key == "copy songs" and (not indeterminate) and (current is not None) and (total is not None):
            try:
                mx = max(int(total), 1)
                val = max(0, min(int(current), int(total)))
                frac = float(val) / float(mx)
                pct = start + frac * (end - start)
            except Exception:
                pct = start
        elif key == "build":
            pct = 0.0
        elif key == "done":
            pct = 100.0

        # Monotonic clamp
        try:
            prev = float(getattr(self, "_build_overall_pct", 0.0) or 0.0)
        except Exception:
            prev = 0.0
        pct = max(prev, float(pct))
        pct = max(0.0, min(100.0, pct))
        try:
            self._build_overall_pct = pct
        except Exception:
            pass
        try:
            self._build_overall_last_phase = key
        except Exception:
            pass
        return int(round(pct))

    def _apply_progress_update(self, data) -> None:
        try:
            phase, item, indeterminate, current, total = data
            self._progress_last_apply_ts = time.time()
        except Exception:
            return

        step_txt = str(phase or "Working").strip()
        msg_txt = str(item or "").strip()

        # Labels
        try:
            suffix = ""
            if (not indeterminate) and (current is not None) and (total is not None):
                suffix = f" ({int(current)}/{int(total)})"
            if msg_txt:
                self._progress_item_var.set(f"Step: {step_txt} — {msg_txt}{suffix}")
            else:
                self._progress_item_var.set(f"Step: {step_txt}{suffix}")
        except Exception:
            pass

        # Overall bar:
        #  - During Build: determinate 0–100% percentage that climbs to 100%.
        #  - Otherwise: indeterminate activity indicator during work.
        try:
            build_active = bool(getattr(self, "_build_running", False))
        except Exception:
            build_active = False

        if build_active:
            try:
                pct = self._compute_build_overall_pct(step_txt, indeterminate, current, total)
            except Exception:
                pct = None
            if pct is None:
                try:
                    pct = int(getattr(self, "_build_overall_pct", 0) or 0)
                except Exception:
                    pct = 0

            try:
                if self._phase_running:
                    self.phase_pb.stop()
                    self._phase_running = False
            except Exception:
                pass
            try:
                if self._phase_mode != "determinate":
                    self.phase_pb.configure(mode="determinate")
                    self._phase_mode = "determinate"
                self.phase_pb.configure(maximum=100)
                self.phase_pb["value"] = int(max(0, min(100, int(pct))))
            except Exception:
                pass
            try:
                self._progress_phase_var.set(f"Overall: {int(max(0, min(100, int(pct))))}%")
            except Exception:
                pass
        else:
            try:
                self._progress_phase_var.set("Overall: Working...")
            except Exception:
                pass
            try:
                if self._phase_mode != "indeterminate":
                    self.phase_pb.configure(mode="indeterminate")
                    self._phase_mode = "indeterminate"
                if not self._phase_running:
                    self.phase_pb.start(12)
                    self._phase_running = True
            except Exception:
                pass

# Step bar can be determinate or indeterminate
        try:
            if indeterminate or total is None or current is None:
                if self._item_mode != "indeterminate":
                    self.item_pb.configure(mode="indeterminate")
                    self._item_mode = "indeterminate"
                if not self._item_running:
                    self.item_pb.start(12)
                    self._item_running = True
            else:
                if self._item_running:
                    self.item_pb.stop()
                    self._item_running = False
                if self._item_mode != "determinate":
                    self.item_pb.configure(mode="determinate")
                    self._item_mode = "determinate"

                mx = max(int(total), 1)
                val = max(0, min(int(current), int(total)))
                # Avoid redundant config churn (reduces flicker)
                if self._item_last_max != mx:
                    self.item_pb.configure(maximum=mx)
                    self._item_last_max = mx
                if self._item_last_val != val:
                    self.item_pb["value"] = val
                    self._item_last_val = val
        except Exception:
            pass


    def _maybe_handle_progress_line(self, s: str) -> bool:
        # Progress messages emitted by subset.py
        if not s.startswith("@@PROGRESS"):
            return False
        try:
            _, payload = s.split(" ", 1)
            obj = json.loads(payload)
            phase = str(obj.get("phase") or "")
            msg = str(obj.get("message") or "")
            ind = bool(obj.get("indeterminate") or False)
            cur = obj.get("current")
            tot = obj.get("total")
            current = int(cur) if cur is not None else None
            total = int(tot) if tot is not None else None
            self._progress_update(phase or "Working", msg, indeterminate=ind, current=current, total=total)
            return True
        except Exception:
            return False

    def _log(self, msg: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {msg}"

        # GUI log view
        try:
            self.log_text.insert(tk.END, line + "\n")
            if getattr(self, "_log_autoscroll", None) is None or bool(self._log_autoscroll.get()):
                self.log_text.see(tk.END)
        except Exception:
            pass

        # Best-effort persistent log (append)
        try:
            pth = getattr(self, "_session_log_path", None)
            if pth is not None:
                Path(pth).parent.mkdir(parents=True, exist_ok=True)
                with Path(pth).open("a", encoding="utf-8") as f:
                    f.write(line + "\n")
        except Exception:
            pass

    # -------- Jobs mini-queue (v0.5.8e1) --------

    def _job_add(self, kind: str, target: str, status: str = "Pending") -> Optional[str]:
        """Add a job row to the Jobs panel. Returns a job_id or None if Jobs UI not ready."""
        try:
            if getattr(self, '_jobs_tree', None) is None:
                return None
            self._job_seq = int(getattr(self, '_job_seq', 0) or 0) + 1
            job_id = f"job_{self._job_seq}"
            iid = self.jobs_tree.insert('', 'end', values=(kind, target, status))
            self._job_iids[job_id] = iid
            return job_id
        except Exception:
            return None

    def _job_set_status(self, job_id: Optional[str], status: str) -> None:
        if not job_id:
            return
        try:
            iid = self._job_iids.get(job_id)
            if not iid:
                return
            vals = list(self.jobs_tree.item(iid, 'values') or ())
            if len(vals) >= 3:
                vals[2] = status
                self.jobs_tree.item(iid, values=tuple(vals))
        except Exception:
            return

    def _job_set_target(self, job_id: Optional[str], target: str) -> None:
        if not job_id:
            return
        try:
            iid = self._job_iids.get(job_id)
            if not iid:
                return
            vals = list(self.jobs_tree.item(iid, 'values') or ())
            if len(vals) >= 2:
                vals[1] = target
                self.jobs_tree.item(iid, values=tuple(vals))
        except Exception:
            return


    def _browse_base(self) -> None:
        folder = filedialog.askdirectory(title="Select Base Disc Folder")
        if not folder:
            return
        self.base_path_var.set(folder)
        self._debounced_persist_gui_state()
        self._index_base()

    def _index_base(self) -> None:
        path = self.base_path_var.get().strip()
        if not path:
            messagebox.showwarning("Base disc", "Please select a base disc folder.")
            return

        # If the selected folder isn't extracted yet, extract first (then we'll index on extract_ok).
        try:
            if self._needs_export(Path(path)):
                exe = self.extractor_exe_var.get().strip()
                if exe:
                    self._log("[extract] Base needs extraction; starting extractor…")
                    self._set_base_badge("EXTRACTING…", "warn")
                    self._progress_update("Extracting PKD", "Base", indeterminate=True)
                    self._start_extract_job("base", path, None)
                    return
        except Exception:
            pass
        self.base_info_var.set("Base: indexing...")
        self._set_base_badge("INDEXING…", "neutral")
        self._progress_update("Indexing", "Base", indeterminate=True)
        self._log(f"Indexing base: {path}")
        self._start_index_job(kind="base", input_path=path, row_iid=None)

    def _add_source(self) -> None:
        if not hasattr(self, '_src_labels'):
            self._src_labels = {}
        folder = filedialog.askdirectory(title="Select Disc Folder")
        if not folder:
            return
        label = Path(folder).name
        self._src_counter += 1
        iid = f"src_{self._src_counter}"
        self.src_tree.insert("", "end", iid=iid, values=(label, "(indexing...)", "", "", "indexing…", folder))
        self._src_labels[iid] = label
        try:
            self._update_source_disc_count()
        except Exception:
            pass
        self._debounced_persist_gui_state()
        # If this source disc isn't extracted yet, extract first (then we'll index on extract_ok).
        try:
            if self._needs_export(Path(folder)):
                exe = self.extractor_exe_var.get().strip()
                if exe:
                    try:
                        self.src_tree.set(iid, "status", "extracting…")
                    except Exception:
                        pass
                    try:
                        if bool(getattr(self, '_extract_cancel_requested', False)):
                            self._extract_cancel_requested = False
                    except Exception:
                        pass
                    try:
                        self._update_cancel_extract_ui()
                    except Exception:
                        pass
                    self._log(f"[extract] Source needs extraction; starting extractor… ({folder})")
                    self._progress_update("Extracting PKD", label, indeterminate=True)
                    self._start_extract_job("source", folder, iid)
                    return

                # No extractor configured: keep the row but mark it clearly.
                try:
                    self.src_tree.set(iid, "status", "needs extraction")
                    self.src_tree.set(iid, "product", "(pending)")
                except Exception:
                    pass
                try:
                    self._update_source_disc_count()
                except Exception:
                    pass
                self._log(f"[extract] Source needs extraction. Set scee_london path, then use Extract Selected. ({folder})")
                try:
                    self._progress_reset()
                except Exception:
                    pass
                return
        except Exception:
            pass

        self._progress_update("Indexing", label, indeterminate=True)
        self._log(f"Indexing source: {folder}")
        self._start_index_job(kind="source", input_path=folder, row_iid=iid)

    def _scan_sources_root(self) -> None:
        root = filedialog.askdirectory(title="Scan folder for SingStar discs (extracted or not)")
        if not root:
            return

        rp = Path(root)
        if not rp.exists():
            messagebox.showerror("Scan folder", f"Folder not found:\n\n{rp}")
            return

        # Don't block the UI; scanning can be slow on big trees.
        self._log(f"Scanning for discs under: {rp}")
        self._progress_update("Scanning", rp.name or str(rp), indeterminate=True)

        def _worker() -> None:
            try:
                found = scan_for_disc_inputs(rp, max_depth=4)
                self._queue.put(("scan_ok", (str(rp), found)))
            except Exception as e:
                self._queue.put(("scan_err", (str(rp), str(e))))

        threading.Thread(target=_worker, daemon=True).start()

    def _handle_scan_err(self, root_path: str, err: str) -> None:
        self._progress_reset()
        self._log(f"Scan error ({root_path}): {err}")
        messagebox.showerror("Scan folder", f"{root_path}\n\n{err}")

    def _handle_scan_ok(self, root_path: str, found_paths: list[str]) -> None:
        self._progress_reset()

        # Existing source paths (normalized)
        existing: set[str] = set()
        try:
            for iid in self.src_tree.get_children():
                p = str(self.src_tree.set(iid, "path") or "").strip()
                if not p:
                    continue
                try:
                    existing.add(str(Path(p).resolve()))
                except Exception:
                    existing.add(p)
        except Exception:
            pass

        added_iids: list[str] = []
        index_tasks: list[tuple[str, str, str]] = []  # (kind, input_path, row_iid)

        for p_str in (found_paths or []):
            try:
                p = self._get_disc_root_for_path(Path(p_str))
            except Exception:
                p = Path(p_str)

            if not p.exists():
                continue

            try:
                key = str(p.resolve())
            except Exception:
                key = str(p)
            if key in existing:
                continue

            label = p.name

            # Insert row
            self._src_counter += 1
            iid = f"src_{self._src_counter}"
            status = "queued"
            try:
                if self._needs_export(p):
                    status = "needs extraction"
            except Exception:
                pass

            self.src_tree.insert("", "end", iid=iid, values=(label, "(pending)", "", "", status, str(p)))
            if not hasattr(self, "_src_labels"):
                self._src_labels = {}
            self._src_labels[iid] = label
            existing.add(key)
            added_iids.append(iid)

            # Queue auto-index for extracted discs only
            if status == "queued":
                index_tasks.append(("source", str(p), iid))

        self._debounced_persist_gui_state()

        if not added_iids:
            self._log(f"Scan complete: no new discs found under {root_path}.")
            return

        self._log(f"Scan complete: added {len(added_iids)} new source disc(s).")

        # Auto-index newly added sources sequentially (similar to startup auto-index).
        if index_tasks:
            self._scan_index_queue = list(index_tasks)
            self._scan_index_inflight = False
            try:
                self.after(100, self._scan_kick_next_index)
            except Exception:
                self._scan_kick_next_index()

    def _scan_kick_next_index(self) -> None:
        if getattr(self, "_scan_index_inflight", False):
            return

        # Don't start if busy; try again soon.
        if self._any_long_job_running():
            try:
                self.after(300, self._scan_kick_next_index)
            except Exception:
                pass
            return

        q = list(getattr(self, "_scan_index_queue", []) or [])
        if not q:
            if bool(getattr(self, "_index_cancel_requested", False)):
                self._log("Scan: auto-index cancelled.")
            else:
                self._log("Scan: auto-index complete.")
            self.request_refresh_songs("scan")
            try:
                self._maybe_finish_index_cancel()
            except Exception:
                pass
            try:
                self._update_cancel_index_ui()
            except Exception:
                pass
            return

        kind, input_path, row_iid = q.pop(0)
        self._scan_index_queue = q
        self._scan_index_inflight = True
        self._scan_current = (kind, row_iid, input_path)

        label = None
        try:
            if row_iid is not None:
                label = self.src_tree.set(row_iid, "label") or Path(input_path).name
                self.src_tree.set(row_iid, "product", "(indexing...)")
                self.src_tree.set(row_iid, "status", "indexing…")
        except Exception:
            label = None

        self._progress_update("Indexing", label or Path(input_path).name, indeterminate=True)
        self._log(f"Scan: indexing source: {input_path}")
        self._start_index_job(kind=kind, input_path=input_path, row_iid=row_iid)

    def _scan_note_index_done(self, kind: str, row_iid: Optional[str], input_path: str) -> None:
        cur = getattr(self, "_scan_current", None)
        if not cur:
            return
        ck, ciid, cpath = cur
        try:
            if ck != kind:
                return
            if ciid != row_iid:
                return
            if str(Path(cpath).resolve()) != str(Path(input_path).resolve()):
                return
        except Exception:
            return

        self._scan_current = None
        self._scan_index_inflight = False
        try:
            self.after(60, self._scan_kick_next_index)
        except Exception:
            self._scan_kick_next_index()

    def _remove_selected(self) -> None:
        sel = self.src_tree.selection()
        if not sel:
            return
        for iid in sel:
            self.src_tree.delete(iid)
            if iid in self._src_indexes:
                idx = self._src_indexes[iid]
                del self._src_indexes[iid]
                # drop label mapping
                if iid in self._src_labels:
                    del self._src_labels[iid]
                # drop cached song map
                if getattr(self, '_disc_song_cache', None) is not None:
                    self._disc_song_cache.pop(idx.input_path, None)
        # keep songs list as-is until refresh
        self._debounced_persist_gui_state()
        try:
            self._update_source_disc_count()
        except Exception:
            pass

    def _start_index_job(self, kind: str, input_path: str, row_iid: Optional[str], job_id: Optional[str] = None) -> None:
        try:
            self._active_index_jobs = int(getattr(self, "_active_index_jobs", 0) or 0) + 1
        except Exception:
            self._active_index_jobs = 1

        try:
            self._update_cancel_index_ui()
        except Exception:
            pass

        # Jobs panel: create/mark an Index job as running (v0.5.8e1)
        if job_id is None:
            try:
                if kind == 'base':
                    target = 'Base'
                else:
                    target = Path(input_path).name
                    if row_iid is not None:
                        try:
                            target = self.src_tree.set(row_iid, 'label') or target
                        except Exception:
                            pass
                job_id = self._job_add('Index', target, status='Running')
            except Exception:
                job_id = None
        else:
            try:
                self._job_set_status(job_id, 'Running')
            except Exception:
                pass

        def _worker() -> None:
            try:
                idx = index_disc(input_path)
                self._queue.put(("index_ok", (kind, row_iid, idx, job_id)))
            except Exception as e:
                self._queue.put(("index_err", (kind, row_iid, input_path, str(e), job_id)))

        t = threading.Thread(target=_worker, daemon=True)
        t.start()

    # -------- Songs tab --------

    def _build_songs_tab(self, parent: ttk.Frame, show_refresh_button: bool = True) -> None:
        top = ttk.Frame(parent)
        top.pack(fill=tk.X)

        ttk.Label(top, text="Search:").pack(side=tk.LEFT)
        ent = ttk.Entry(top, textvariable=self.filter_text_var, width=40)
        ent.pack(side=tk.LEFT, padx=(6, 14))
        self._search_entry = ent
        self.filter_text_var.trace_add("write", lambda *_: (self._debounced_apply_filter(), self._debounced_persist_gui_state()))

        ttk.Label(top, text="Source:").pack(side=tk.LEFT)
        self.source_combo = ttk.Combobox(top, textvariable=self.filter_source_var, width=28, state="readonly")
        self.source_combo["values"] = ("All",)
        self.source_combo.current(0)
        self.source_combo.pack(side=tk.LEFT, padx=(6, 14))
        self.source_combo.bind("<<ComboboxSelected>>", lambda _e: (self._apply_filter(), self._debounced_persist_gui_state()))

        sel_only = ttk.Checkbutton(top, text="Selected only", variable=self.filter_selected_only_var, command=lambda: (self._apply_filter(), self._debounced_persist_gui_state()))
        sel_only.pack(side=tk.LEFT)

        if show_refresh_button:
            ttk.Button(top, text="Refresh Songs List", command=self._refresh_songs_safe).pack(side=tk.RIGHT)

        mid = ttk.Frame(parent)
        mid.pack(fill=tk.X, pady=(8, 6))

        ttk.Button(mid, text="Select All (filtered)", command=lambda: self._bulk_select(mode="select")).pack(side=tk.LEFT)
        ttk.Button(mid, text="Clear (filtered)", command=lambda: self._bulk_select(mode="clear")).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(mid, text="Invert (filtered)", command=lambda: self._bulk_select(mode="invert")).pack(side=tk.LEFT, padx=(8, 0))

        ttk.Button(mid, text="Expand All", command=lambda: self._set_all_song_groups_open(True)).pack(side=tk.LEFT, padx=(14, 0))
        ttk.Button(mid, text="Collapse All", command=lambda: self._set_all_song_groups_open(False)).pack(side=tk.LEFT, padx=(8, 0))

        ttk.Button(mid, text="Invert All", command=lambda: self._bulk_select_all(mode="invert")).pack(side=tk.RIGHT)
        ttk.Button(mid, text="Clear All", command=lambda: self._bulk_select_all(mode="clear")).pack(side=tk.RIGHT, padx=(8, 0))
        ttk.Button(mid, text="Select All", command=lambda: self._bulk_select_all(mode="select")).pack(side=tk.RIGHT, padx=(8, 0))

        ttk.Separator(parent).pack(fill=tk.X, pady=6)

        cols = ("sel", "song_id", "artist", "source")
        tree_wrap = ttk.Frame(parent)
        tree_wrap.pack(fill=tk.BOTH, expand=True)
        tree_wrap.columnconfigure(0, weight=1)
        tree_wrap.rowconfigure(0, weight=1)

        self.songs_tree = ttk.Treeview(tree_wrap, columns=cols, show="tree headings", height=20)
        self.songs_tree.heading("#0", text="Title / Disc")
        self.songs_tree.heading("sel", text="✓")
        self.songs_tree.heading("song_id", text="Song ID")
        self.songs_tree.heading("artist", text="Artist/Act")
        self.songs_tree.heading("source", text="Source(s)")

        self.songs_tree.column("#0", width=520, anchor="w")
        self.songs_tree.column("sel", width=40, anchor="center")
        self.songs_tree.column("song_id", width=90, anchor="center")
        self.songs_tree.column("artist", width=300, anchor="w")
        self.songs_tree.column("source", width=320, anchor="w")

        # Songs list scrollbar (v0.5.6a): use grid to avoid pack/layout quirks on some themes.
        yscroll = ttk.Scrollbar(tree_wrap, orient="vertical", command=self.songs_tree.yview)
        self.songs_tree.configure(yscrollcommand=yscroll.set)
        self.songs_tree.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")

        self.songs_tree.bind("<Button-1>", self._on_song_click)
        self.songs_tree.bind("<<TreeviewOpen>>", self._on_song_group_toggle)
        self.songs_tree.bind("<<TreeviewClose>>", self._on_song_group_toggle)

        bottom = ttk.Frame(parent)
        bottom.pack(fill=tk.X, pady=(6, 0))

        self.songs_status_var = tk.StringVar(value="Songs: 0 | Selected: 0")
        ttk.Label(bottom, textvariable=self.songs_status_var).pack(side=tk.LEFT)

        ttk.Button(bottom, text="Save selection...", command=self._save_selection).pack(side=tk.RIGHT)
        ttk.Button(bottom, text="Load selection...", command=self._load_selection).pack(side=tk.RIGHT, padx=(0, 8))

        tip_fg = getattr(getattr(self, "_theme_colors", None) or {}, "get", lambda _k, _d=None: _d)("muted", "#666")
        ttk.Label(parent, text="Tip: Click the ✓ column to toggle a song. Click a disc header to collapse/expand.", foreground=tip_fg).pack(anchor="w", pady=(6, 0))

    def _set_sources_dropdown(self) -> None:
        values = ["All", "Base"]
        # source labels
        for iid in self.src_tree.get_children():
            label = self.src_tree.set(iid, "label")
            if label and label not in values:
                values.append(label)
        self.source_combo["values"] = tuple(values)
        if self.filter_source_var.get() not in values:
            self.filter_source_var.set("All")

    def _refresh_songs(self) -> None:
        # Build aggregated song model in background
        if getattr(self, '_songs_refresh_running', False):
            return
        if self._base_idx is None:
            messagebox.showwarning("Songs", "Please set and index the Base disc first.")
            return

        self._songs_refresh_running = True

        self._progress_update("Indexing songs", "Building song list…", indeterminate=True)
        self._log("Refreshing songs list (this can take a few seconds on large libraries)...")
        self.songs_status_var.set("Songs: indexing...")
        self._update_disc_selection_counts()
        self._set_sources_dropdown()
        self._run_validation_async()

        base_idx = self._base_idx
        src_indexes = dict(self._src_indexes)  # snapshot

        def _worker() -> None:
            try:
                # label -> disc index
                discs: List[Tuple[str, DiscIndex, bool]] = [("Base", base_idx, True)]
                for iid, di in src_indexes.items():
                    label = Path(di.input_path).name
                    # keep the user-facing label from treeview if present
                    try:
                        label = self.src_tree.set(iid, "label") or label
                    except Exception:
                        pass
                    discs.append((label, di, False))

                songs_out, disc_song_ids_by_label = build_song_catalog(discs)
                self._queue.put(("songs_ok", (songs_out, disc_song_ids_by_label)))
            except Exception as e:
                self._queue.put(("songs_err", str(e)))

        threading.Thread(target=_worker, daemon=True).start()

    def _debounced_apply_filter(self) -> None:
        if self._filter_job is not None:
            try:
                self.after_cancel(self._filter_job)
            except Exception:
                pass
        self._filter_job = self.after(160, self._apply_filter)

    def _apply_filter(self) -> None:
        self._filter_job = None
        q = self.filter_text_var.get().strip().lower()
        src = self.filter_source_var.get()
        sel_only = bool(self.filter_selected_only_var.get())

        def match(song: SongAgg) -> bool:
            if src and src != "All":
                if src not in song.sources:
                    return False
            if sel_only and song.song_id not in self._selected_song_ids:
                return False
            if q:
                if q not in str(song.song_id) and q not in (song.title or "").lower() and q not in (song.artist or "").lower():
                    return False
            return True

        visible = [s for s in self._songs if match(s)]
        self._render_songs_table(visible)
        self.songs_status_var.set(
            f"Songs: {len(self._songs)} | Visible: {len(visible)} | Selected: {len(self._selected_song_ids)}"
        )
        self._update_output_suggestion()
        self._update_disc_selection_counts()
        self._run_validation_async()

    def _render_songs_table(self, rows: List[SongAgg]) -> None:
        # Collapsible groups by disc (v0.5.6a: preserve group open state + scroll + selection)
        yview = None
        open_by_group: Dict[str, bool] = dict(getattr(self, "_song_group_open_state", {}) or {})
        focus_item: Optional[str] = None
        focus_group_label: Optional[str] = None
        sel_item: Optional[str] = None
        sel_group_label: Optional[str] = None

        try:
            yview = self.songs_tree.yview()
        except Exception:
            yview = None

        # Capture current group open/close state + selection/focus before we clear the tree.
        try:
            for gid in self.songs_tree.get_children(""):
                try:
                    txt = str(self.songs_tree.item(gid, "text") or "")
                    label = (txt.split("  (", 1)[0] if "  (" in txt else txt).strip()
                    if label:
                        open_by_group[label] = bool(self.songs_tree.item(gid, "open"))
                except Exception:
                    continue
            self._song_group_open_state = open_by_group
        except Exception:
            pass

        try:
            f = str(self.songs_tree.focus() or "")
            if f:
                if f.startswith("song_"):
                    focus_item = f
                else:
                    try:
                        txt = str(self.songs_tree.item(f, "text") or "")
                        focus_group_label = (txt.split("  (", 1)[0] if "  (" in txt else txt).strip() or None
                    except Exception:
                        focus_group_label = None
        except Exception:
            pass

        try:
            sels = [str(i) for i in (self.songs_tree.selection() or ())]
            for s in sels:
                if s.startswith("song_"):
                    sel_item = s
                    break
            if sel_item is None and sels:
                try:
                    txt = str(self.songs_tree.item(sels[0], "text") or "")
                    sel_group_label = (txt.split("  (", 1)[0] if "  (" in txt else txt).strip() or None
                except Exception:
                    sel_group_label = None
        except Exception:
            pass

        try:
            self.songs_tree.delete(*self.songs_tree.get_children())
        except Exception:
            return

        src_filter = self.filter_source_var.get()

        groups: Dict[str, List[SongAgg]] = {}
        if src_filter and src_filter != "All":
            groups[src_filter] = list(rows)
        else:
            for s in rows:
                key = (s.preferred_source or "Base")
                groups.setdefault(key, []).append(s)

        # Stable ordering: Base first, then alphabetical
        ordered = list(groups.keys())
        if "Base" in ordered:
            ordered.remove("Base")
            ordered = ["Base"] + sorted(ordered)
        else:
            ordered = sorted(ordered)

        gnum = 0
        group_iid_by_label: Dict[str, str] = {}
        for gkey in ordered:
            songs = groups.get(gkey) or []
            if not songs:
                continue
            gnum += 1
            sel_count = sum(1 for s in songs if s.song_id in self._selected_song_ids)
            header = f"{gkey}  (sel {sel_count}/{len(songs)})"
            gid = f"grp_{gnum}"
            open_state = bool(open_by_group.get(gkey, True))
            self.songs_tree.insert("", "end", iid=gid, text=header, values=("", "", "", ""), open=open_state, tags=("group",))
            group_iid_by_label[gkey] = gid

            for s in sorted(songs, key=lambda x: x.song_id):
                iid = f"song_{s.song_id}"
                mark = "☑" if s.song_id in self._selected_song_ids else "☐"
                src_disp = s.preferred_source
                if len(s.sources) > 1:
                    extra = len(s.sources) - 1
                    src_disp = f"{src_disp} (+{extra})"
                self.songs_tree.insert(
                    gid,
                    "end",
                    iid=iid,
                    text=s.title,
                    values=(mark, str(s.song_id), s.artist, src_disp),
                    tags=("song",),
                )
        # Restore focus/selection (do not force-scroll; keep user's scroll position)
        try:
            target: Optional[str] = None
            if sel_item and self.songs_tree.exists(sel_item):
                target = sel_item
            elif focus_item and self.songs_tree.exists(focus_item):
                target = focus_item
            elif sel_group_label and sel_group_label in group_iid_by_label:
                target = group_iid_by_label[sel_group_label]
            elif focus_group_label and focus_group_label in group_iid_by_label:
                target = group_iid_by_label[focus_group_label]
            if target:
                try:
                    self.songs_tree.selection_set(target)
                except Exception:
                    pass
                try:
                    self.songs_tree.focus(target)
                except Exception:
                    pass
        except Exception:
            pass

        try:
            if yview is not None:
                self.songs_tree.yview_moveto(float(yview[0]))
        except Exception:
            pass


    def _on_song_group_toggle(self, _event=None) -> None:
        """Track disc group expand/collapse so refresh/filter keeps it stable (v0.5.6a)."""
        try:
            iid = str(self.songs_tree.focus() or "")
            if not iid:
                return
            if iid.startswith("song_"):
                try:
                    iid = str(self.songs_tree.parent(iid) or iid)
                except Exception:
                    return
            txt = str(self.songs_tree.item(iid, "text") or "")
            label = (txt.split("  (", 1)[0] if "  (" in txt else txt).strip()
            if not label:
                return
            self._song_group_open_state[label] = bool(self.songs_tree.item(iid, "open"))
        except Exception:
            pass


    def _on_song_click(self, event) -> None:
        region = self.songs_tree.identify("region", event.x, event.y)
        if region != "cell":
            return
        col = self.songs_tree.identify_column(event.x)
        # Only toggle when clicking the ✓ column
        if col != "#1":
            return
        row = self.songs_tree.identify_row(event.y)
        if not row or not str(row).startswith("song_"):
            return
        try:
            sid = int(str(row).replace("song_", ""))
        except ValueError:
            return

        if sid in self._selected_song_ids:
            self._selected_song_ids.remove(sid)
        else:
            self._selected_song_ids.add(sid)

        # update row
        vals = list(self.songs_tree.item(row, "values"))
        if vals:
            vals[0] = "☑" if sid in self._selected_song_ids else "☐"
            self.songs_tree.item(row, values=tuple(vals))

        # Update group header counts (cheap: re-render visible set)
        self._apply_filter()

    def _bulk_select_all(self, mode: str) -> None:
        sids = [s.song_id for s in self._songs]
        if mode == "select":
            self._selected_song_ids.update(sids)
        elif mode == "clear":
            self._selected_song_ids.clear()
        elif mode == "invert":
            cur = set(self._selected_song_ids)
            self._selected_song_ids = set(sids).difference(cur)
        else:
            return
        self._apply_filter()

    def _bulk_select(self, mode: str) -> None:
        # Apply to currently visible song rows (children of groups)
        sids: List[int] = []
        for gid in list(self.songs_tree.get_children("")):
            for iid in list(self.songs_tree.get_children(gid)):
                if not str(iid).startswith("song_"):
                    continue
                try:
                    sids.append(int(str(iid).replace("song_", "")))
                except ValueError:
                    continue

        if mode == "select":
            self._selected_song_ids.update(sids)
        elif mode == "clear":
            for sid in sids:
                self._selected_song_ids.discard(sid)
        elif mode == "invert":
            for sid in sids:
                if sid in self._selected_song_ids:
                    self._selected_song_ids.remove(sid)
                else:
                    self._selected_song_ids.add(sid)
        else:
            return

        self._apply_filter()

    def _set_all_song_groups_open(self, open_: bool) -> None:
        try:
            for gid in list(self.songs_tree.get_children("")):
                self.songs_tree.item(gid, open=bool(open_))
        except Exception:
            pass

    def _save_selection(self) -> None:
        if not self._selected_song_ids:
            messagebox.showinfo("Save selection", "No songs selected.")
            return
        path = filedialog.asksaveasfilename(
            title="Save selection",
            defaultextension=".json",
            filetypes=[("JSON", "*.json")],
        )
        if not path:
            return
        data = {"selected_song_ids": sorted(self._selected_song_ids)}
        Path(path).write_text(json.dumps(data, indent=2), encoding="utf-8")
        messagebox.showinfo("Save selection", f"Saved {len(self._selected_song_ids)} songs.")

    def _load_selection(self) -> None:
        path = filedialog.askopenfilename(
            title="Load selection",
            filetypes=[("JSON", "*.json")],
        )
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            ids = data.get("selected_song_ids", [])
            new_sel: Set[int] = set()
            for x in ids:
                try:
                    new_sel.add(int(x))
                except Exception:
                    continue
            self._selected_song_ids = new_sel
            self._apply_filter()
            self._update_disc_selection_counts()
            messagebox.showinfo("Load selection", f"Loaded {len(self._selected_song_ids)} selected songs.")
        except Exception as e:
            messagebox.showerror("Load selection", str(e))

    # -------- Queue handlers --------

    def _poll_queue(self) -> None:
        try:
            while True:
                status, payload = self._queue.get_nowait()
                if status == "index_ok":
                    try:
                        self._active_index_jobs = max(0, int(getattr(self, "_active_index_jobs", 0) or 0) - 1)
                    except Exception:
                        self._active_index_jobs = 0
                    job_id = None
                    try:
                        if isinstance(payload, tuple) and len(payload) == 4:
                            kind, row_iid, idx, job_id = payload  # type: ignore[misc]
                        else:
                            kind, row_iid, idx = payload  # type: ignore[misc]
                    except Exception:
                        kind, row_iid, idx = payload  # type: ignore[misc]
                    try:
                        self._job_set_status(job_id, 'Done')
                    except Exception:
                        pass
                    self._handle_index_ok(kind, row_iid, idx)
                    try:
                        self._update_cancel_index_ui()
                    except Exception:
                        pass
                    try:
                        # Defer cancel completion slightly so any queue "cancelled/complete" logs can run first.
                        self.after(180, self._maybe_finish_index_cancel)
                    except Exception:
                        pass
                elif status == "index_err":
                    try:
                        self._active_index_jobs = max(0, int(getattr(self, "_active_index_jobs", 0) or 0) - 1)
                    except Exception:
                        self._active_index_jobs = 0
                    job_id = None
                    try:
                        if isinstance(payload, tuple) and len(payload) == 5:
                            kind, row_iid, input_path, err, job_id = payload  # type: ignore[misc]
                        else:
                            kind, row_iid, input_path, err = payload  # type: ignore[misc]
                    except Exception:
                        kind, row_iid, input_path, err = payload  # type: ignore[misc]
                    try:
                        self._job_set_status(job_id, 'Failed')
                    except Exception:
                        pass
                    self._handle_index_err(kind, row_iid, input_path, err)
                    try:
                        self._update_cancel_index_ui()
                    except Exception:
                        pass
                    try:
                        # Defer cancel completion slightly so any queue "cancelled/complete" logs can run first.
                        self.after(180, self._maybe_finish_index_cancel)
                    except Exception:
                        pass
                elif status == "scan_ok":
                    root_path, found_paths = payload  # type: ignore[misc]
                    self._handle_scan_ok(str(root_path), list(found_paths or []))
                elif status == "scan_err":
                    root_path, err = payload  # type: ignore[misc]
                    self._handle_scan_err(str(root_path), str(err))
                elif status == "songs_ok":
                    try:
                        self._songs_refresh_running = False
                    except Exception:
                        pass
                    disc_map = None
                    songs_out = payload
                    if isinstance(payload, tuple) and len(payload) == 2:
                        songs_out, disc_map = payload
                    self._handle_songs_ok(songs_out, disc_map)
                elif status == "songs_err":
                    try:
                        self._songs_refresh_running = False
                    except Exception:
                        pass
                    err = payload  # type: ignore[assignment]
                    self._handle_songs_err(err)
                elif status == "build_log":
                    msg = payload  # type: ignore[assignment]
                    s = str(msg)
                    if not self._maybe_handle_progress_line(s):
                        self._log(s)
                elif status == "build_ok":
                    outp = payload  # type: ignore[assignment]
                    self._handle_build_ok(str(outp))
                elif status == "build_cancel":
                    outp, msg = payload  # type: ignore[misc]
                    self._handle_build_cancel(str(outp), str(msg))
                elif status == "build_err":
                    err = payload  # type: ignore[assignment]
                    self._handle_build_err(str(err))

                elif status == "preflight_validate_report":
                    report_text = str(payload or '')
                    try:
                        self._last_validate_report_text = report_text
                    except Exception:
                        pass
                    try:
                        self._update_validate_ui()
                    except Exception:
                        pass
                    # Optional: also write validate_report.txt (uses the existing Validate setting)
                    write_on = False
                    try:
                        write_on = bool(getattr(self, 'validate_write_report_var', tk.BooleanVar(value=False)).get())
                    except Exception:
                        write_on = False
                    if write_on and report_text.strip():
                        rp = self._write_validate_report_file(report_text)
                        if rp:
                            try:
                                self._log(f"[preflight] Wrote validate_report.txt: {rp}")
                            except Exception:
                                pass

                elif status == "disc_validate_log":
                    msg = payload  # type: ignore[assignment]
                    self._log(str(msg))
                elif status == "disc_validate_done":
                    results = payload  # type: ignore[assignment]
                    report_text = ''
                    if isinstance(payload, tuple) and len(payload) >= 2:
                        results = payload[0]
                        report_text = str(payload[1] or '')
                    try:
                        self._handle_disc_validate_done(list(results or []), report_text=report_text)
                    except Exception:
                        self._handle_disc_validate_done([], report_text=report_text)
                elif status == "disc_validate_err":
                    err = payload  # type: ignore[assignment]
                    self._handle_disc_validate_err(str(err))


                elif status == "extract_ok":
                    try:
                        self._active_extract_jobs = max(0, int(getattr(self, "_active_extract_jobs", 0) or 0) - 1)
                    except Exception:
                        self._active_extract_jobs = 0
                    try:
                        self._update_cancel_extract_ui()
                    except Exception:
                        pass
                    verify = {}
                    try:
                        if isinstance(payload, tuple) and len(payload) >= 4:
                            kind, row_iid, disc_root, verify = payload  # type: ignore[misc]
                        else:
                            kind, row_iid, disc_root = payload  # type: ignore[misc]
                    except Exception:
                        kind, row_iid, disc_root = payload  # type: ignore[misc]
                        verify = {}

                    try:
                        if isinstance(verify, dict) and verify:
                            if bool(verify.get("ok")):
                                self._log(f"[verify] OK: {disc_root}")
                            else:
                                errs = verify.get("errors") or []
                                if errs:
                                    self._log(f"[verify] FAIL: {disc_root}: {errs[0]}")
                                else:
                                    self._log(f"[verify] FAIL: {disc_root} (see log)")
                    except Exception:
                        pass

                    # Offer cleanup (move Pack*.pkd_out into _spcdb_trash) only if verification passed.
                    try:
                        if isinstance(verify, dict) and bool(verify.get("ok")):
                            arts = verify.get("artifacts") or {}
                            pkd_out_dirs = list(arts.get("pkd_out_dirs", []) or [])
                            pkd_files = list(arts.get("pkd_files", []) or [])
                            if pkd_out_dirs or pkd_files:
                                if messagebox.askyesno(
                                    "Cleanup extraction artifacts?",
                                    "Extraction verified.\n\n"
                                    "Clean up legacy extraction artifacts now?\n"
                                    "This will MOVE Pack*.pkd_out folders into:\n"
                                    "<discs_folder>/_spcdb_trash/<timestamp>/<disc_folder>/\n\n"
                                    "This is destructive (but recoverable from _spcdb_trash).",
                                ):
                                    def _cleanup_worker() -> None:
                                        try:
                                            cleanup_extraction_artifacts(
                                                Path(disc_root),
                                                include_pkd_out_dirs=True,
                                                include_pkd_files=False,
                                                log_cb=lambda m: self._queue.put(("build_log", str(m))),
                                            )
                                        except Exception as e:
                                            self._queue.put(("build_log", f"[cleanup] ERROR: {e}"))

                                    threading.Thread(target=_cleanup_worker, daemon=True).start()
                    except Exception:
                        pass

                    self._log(f"[extract] Done: {disc_root}. Re-indexing...")
                    # Re-index the same input path (use disc_root to be safe)
                    if kind == "base":
                        self._set_base_badge("INDEXING…", "neutral")
                        self._start_index_job("base", disc_root, None)
                    else:
                        # update displayed path to disc_root for consistency
                        if row_iid is not None:
                            self.src_tree.set(row_iid, "path", disc_root)
                            try:
                                self.src_tree.set(row_iid, "status", "indexing…")
                            except Exception:
                                pass
                        self._debounced_persist_gui_state()
                        self._start_index_job("source", disc_root, row_iid)

                    # v0.5.8c: if multiple extracts were queued, kick the next one (unless cancelling).
                    try:
                        if not bool(getattr(self, '_extract_cancel_requested', False)):
                            self._kick_next_extract_queue()
                    except Exception:
                        pass
                    try:
                        # Defer cancel completion slightly so any follow-up logs run first.
                        self.after(180, self._maybe_finish_extract_cancel)
                    except Exception:
                        pass
                elif status == "extract_err":
                    try:
                        self._active_extract_jobs = max(0, int(getattr(self, "_active_extract_jobs", 0) or 0) - 1)
                    except Exception:
                        self._active_extract_jobs = 0
                    try:
                        self._update_cancel_extract_ui()
                    except Exception:
                        pass
                    self._progress_reset()
                    kind, row_iid, input_path, err = payload  # type: ignore[misc]
                    messagebox.showerror("Extraction failed", f"{input_path}\n\n{err}")
                    if kind == "base":
                        self._set_base_badge("FAILED", "err")
                    self._log(f"[extract] ERROR: {input_path}: {err}")

                    # v0.5.8c: continue any queued extractions (unless cancelling).
                    try:
                        if not bool(getattr(self, '_extract_cancel_requested', False)):
                            self._kick_next_extract_queue()
                    except Exception:
                        pass
                    try:
                        # Defer cancel completion slightly so any follow-up logs run first.
                        self.after(180, self._maybe_finish_extract_cancel)
                    except Exception:
                        pass

                elif status == "validate_ok":
                    conflicts = payload  # type: ignore[assignment]
                    self._conflicts = conflicts
                    # ensure choices contain only valid labels
                    for sid in list(self._conflict_choices.keys()):
                        if sid not in self._conflicts:
                            self._conflict_choices.pop(sid, None)
                    self._update_status_from_validation()
                elif status == "validate_err":
                    err = payload  # type: ignore[assignment]
                    self._log(f"Validation error: {err}")
                    self._update_status_from_validation()
        except queue.Empty:
            pass
        self.after(120, self._poll_queue)

    def _handle_index_ok(self, kind: str, row_iid: Optional[str], idx: DiscIndex) -> None:
        self._progress_reset()
        product = idx.product_desc or idx.product_code or "(unknown)"
        if idx.product_code and idx.product_desc:
            product = f"{idx.product_desc} [{idx.product_code}]"

        if kind == "base":
            self._base_idx = idx
            self._base_product_display = product
            self.base_info_var.set(f"Base: {product} | max bank {idx.max_bank} | sel 0/{idx.song_count}")
            self._set_base_badge("OK", "ok")
            self._update_disc_selection_counts()
            if not _is_expected_base(idx):
                self._log(
                    f"Warning: Base appears to be '{idx.product_desc or idx.product_code}'. "
                    "Tested baseline is SingStar [BCES00011]."
                )
        else:
            if row_iid is None:
                return
            self._src_indexes[row_iid] = idx
            label = self.src_tree.set(row_iid, "label")
            self._src_labels[row_iid] = label
            path = self.src_tree.set(row_iid, "path")
            self.src_tree.item(row_iid, values=(label, product, str(idx.max_bank), f"0/{idx.song_count}", "OK", path))


        # v0.5.8d: refresh persistent index cache record and clear stale markers.
        try:
            _write_index_cache(idx, songs=None)
        except Exception:
            pass
        try:
            if kind == "base":
                self._base_index_stale = False
            else:
                if row_iid is not None:
                    try:
                        self._stale_source_iids.discard(row_iid)
                    except Exception:
                        pass
        except Exception:
            pass
        try:
            self._update_reindex_stale_button()
        except Exception:
            pass

        if idx.warnings:
            for w in idx.warnings[:10]:
                self._log(f"Warning: {w}")
            if len(idx.warnings) > 10:
                self._log(f"Warning: ... and {len(idx.warnings) - 10} more")

        self._update_disc_selection_counts()
        self._set_sources_dropdown()
        self._run_validation_async()

        # Safe auto-refresh of songs list after indexing changes
        self.request_refresh_songs("index")

        # If this index was started by startup auto-index, advance the queue
        try:
            self._startup_note_index_done(kind, row_iid, idx.input_path)
        except Exception:
            pass

        # If this index was started by Scan Folder auto-index, advance that queue too.
        try:
            self._scan_note_index_done(kind, row_iid, idx.input_path)
        except Exception:
            pass

        # If this index was started by Reindex stale, advance that queue too.
        try:
            self._stale_note_index_done(kind, row_iid, idx.input_path)
        except Exception:
            pass

        try:
            self._update_source_disc_count()
        except Exception:
            pass


    def _handle_index_err(self, kind: str, row_iid: Optional[str], input_path: str, err: str) -> None:
        self._progress_reset()
        needs_extract = "Could not locate an Export root" in err
        if kind == "base":
            self._base_idx = None
            if needs_extract:
                self.base_info_var.set("Base: needs extraction (missing FileSystem/Export)")
                self._set_base_badge("NEEDS EXTRACT", "warn")
                messagebox.showwarning(
                    "Base disc needs extraction",
                    f"{input_path}\n\nExport folder not found. Select scee_london (or scee_london.exe) and extract the base disc.",
                )
            else:
                self.base_info_var.set("Base: failed to index")
                self._set_base_badge("FAILED", "err")
                messagebox.showerror("Base disc indexing failed", f"{input_path}\n\n{err}")
        else:
            if row_iid is not None:
                if needs_extract:
                    try:
                        self.src_tree.set(row_iid, "status", "needs extraction")
                    except Exception:
                        pass
                else:
                    # Keep the row (safer) and just mark it failed so the user can retry.
                    try:
                        self.src_tree.set(row_iid, "status", "failed")
                        self.src_tree.set(row_iid, "product", "(failed)")
                    except Exception:
                        pass
                    self._src_indexes.pop(row_iid, None)

            if needs_extract:
                messagebox.showwarning(
                    "Source disc needs extraction",
                    f"{input_path}\n\nExport folder not found. Select scee_london (or scee_london.exe) and extract this disc.",
                )
            else:
                messagebox.showerror("Source disc indexing failed", f"{input_path}\n\n{err}")

        # If this index was started by startup auto-index, advance the queue
        try:
            self._startup_note_index_done(kind, row_iid, input_path)
        except Exception:
            pass

        # If this index was started by Scan Folder auto-index, advance that queue too.
        try:
            self._scan_note_index_done(kind, row_iid, input_path)
        except Exception:
            pass

        # If this index was started by Reindex stale, advance that queue too.
        try:
            self._stale_note_index_done(kind, row_iid, input_path)
        except Exception:
            pass

        self._log(f"ERROR indexing {input_path}: {err}")

        try:
            self._update_source_disc_count()
        except Exception:
            pass


    def _update_disc_selection_counts(self) -> None:
        """Update Sel/Total counts for Base + each Source disc."""
        try:
            selected = set(self._selected_song_ids)
        except Exception:
            selected = set()

        # Base totals
        base_ids = set()
        try:
            base_ids = set(getattr(self, "_disc_song_ids_by_label", {}).get("Base", set()))
        except Exception:
            base_ids = set()

        if base_ids:
            base_total = len(base_ids)
            base_sel = len(selected.intersection(base_ids))
        else:
            base_total = int(getattr(getattr(self, "_base_idx", None), "song_count", 0) or 0)
            base_sel = 0

        # Update Base info line
        try:
            if self._base_idx is not None:
                product = getattr(self, "_base_product_display", "") or (self._base_idx.product_desc or self._base_idx.product_code or "(unknown)")
                self.base_info_var.set(f"Base: {product} | max bank {self._base_idx.max_bank} | sel {base_sel}/{base_total}")
        except Exception:
            pass

        disc_map = {}
        try:
            disc_map = getattr(self, "_disc_song_ids_by_label", {}) or {}
        except Exception:
            disc_map = {}

        # Update each source row Sel/Total when we know disc->song_ids
        try:
            for iid in self.src_tree.get_children(""):
                label = ""
                try:
                    label = self.src_tree.set(iid, "label") or ""
                except Exception:
                    pass
                ids = set(disc_map.get(label, set())) if label else set()
                if ids:
                    total = len(ids)
                    selc = len(selected.intersection(ids))
                    try:
                        self.src_tree.set(iid, "songs", f"{selc}/{total}")
                    except Exception:
                        pass
        except Exception:
            pass
        try:
            self._update_build_panels()
        except Exception:
            pass




    def _handle_songs_ok(self, songs_out: List[SongAgg], disc_song_ids_by_label=None) -> None:
        self._songs = songs_out
        try:
            if disc_song_ids_by_label is None:
                self._disc_song_ids_by_label = {}
            else:
                # Ensure plain sets (some payloads may be lists/tuples)
                self._disc_song_ids_by_label = {k: set(v) for k, v in dict(disc_song_ids_by_label).items()}
            self._base_song_ids = set(self._disc_song_ids_by_label.get('Base', set()))
        except Exception:
            self._disc_song_ids_by_label = {}
            self._base_song_ids = set()

        self._progress_reset()
        self._log(f"Songs list ready: {len(self._songs)} songs indexed.")
        self._update_disc_selection_counts()
        self._update_output_suggestion()
        self._run_validation_async()
        self._update_disc_selection_counts()
        self._apply_filter()
        self._run_validation_async()

    
    def _handle_build_ok(self, out_dir: str) -> None:
        self._build_running = False
        self._progress_reset()
        try:
            self.build_btn.configure(state="normal")
        except Exception:
            pass

        dur = None
        try:
            st = getattr(self, "_build_started_ts", None)
            if isinstance(st, (int, float)):
                dur = float(time.time() - float(st))
        except Exception:
            dur = None
        try:
            self._build_started_ts = None
        except Exception:
            pass
        try:
            self._build_overall_pct = 0.0
            self._build_overall_last_phase = None
        except Exception:
            pass

        report_path = self._write_build_report(out_dir=out_dir, ok=True, duration_s=dur)

        self._set_last_build_record(ok=True, out_dir=out_dir, duration_s=dur, report_path=report_path)
        self._update_build_panels()

        messagebox.showinfo("Build subset", f"Subset build complete:\n{out_dir}")
        self._log(f"Subset build complete: {out_dir}")


    



    def _handle_build_cancel(self, out_dir: str, msg: str = "Cancelled") -> None:
        self._build_running = False
        try:
            self._build_cancel_requested = False
        except Exception:
            pass
        try:
            self.build_btn.configure(state="normal")
        except Exception:
            pass
        try:
            self._update_cancel_build_ui()
        except Exception:
            pass

        dur = None
        try:
            st = getattr(self, "_build_started_ts", None)
            if isinstance(st, (int, float)):
                dur = float(time.time() - float(st))
        except Exception:
            dur = None
        try:
            self._build_started_ts = None
        except Exception:
            pass
        try:
            self._build_overall_pct = 0.0
            self._build_overall_last_phase = None
        except Exception:
            pass

        self._progress_reset()

        report_path = ""
        try:
            report_path = self._write_build_report(out_dir=out_dir, ok=False, duration_s=dur, err="Cancelled")
        except Exception:
            report_path = ""
        self._set_last_build_record(ok=False, out_dir=str(out_dir or ""), err="Cancelled", duration_s=dur, report_path=report_path)
        self._update_build_panels()

        try:
            self._log(f"Build cancelled: {out_dir}")
        except Exception:
            pass
    def _handle_build_err(self, err: str) -> None:
        self._build_running = False
        try:
            self._build_cancel_requested = False
        except Exception:
            pass
        try:
            self.build_btn.configure(state="normal")
        except Exception:
            pass
        try:
            self._update_cancel_build_ui()
        except Exception:
            pass

        dur = None
        try:
            st = getattr(self, "_build_started_ts", None)
            if isinstance(st, (int, float)):
                dur = float(time.time() - float(st))
        except Exception:
            dur = None
        try:
            self._build_started_ts = None
        except Exception:
            pass
        try:
            self._build_overall_pct = 0.0
            self._build_overall_last_phase = None
        except Exception:
            pass

        hint = ""
        if "non-identical duplicates" in err.lower() or "duplicates across sources" in err.lower():
            hint = "\n\nHint: Use \'Resolve Conflicts...\' in the Status panel to pick which source to use."
        self._progress_reset()

        self._set_last_build_record(ok=False, out_dir=str(self.output_path_var.get() or ""), err=err, duration_s=dur)
        self._update_build_panels()

        messagebox.showerror("Build subset failed", err + hint)
        self._log(f"ERROR build subset: {err}")



    


    def _handle_songs_err(self, err: str) -> None:
        self._progress_reset()
        self.songs_status_var.set("Songs: failed")
        messagebox.showerror("Songs indexing failed", err)
        self._log(f"ERROR refreshing songs: {err}")


    # -------- Output / Build --------

    def _suggest_output_name(self) -> str:
        n = len(self._selected_song_ids)
        return f"SPCDB_Subset_{n}songs"

    def _first_available_outdir(self, parent: Path, name: str) -> Path:
        cand = parent / name
        if not cand.exists():
            return cand
        i = 2
        while True:
            cand2 = parent / f"{name}_{i}"
            if not cand2.exists():
                return cand2
            i += 1

    def _mark_output_path_user_set(self) -> None:
        self._output_path_user_set = True

    def _update_output_suggestion(self) -> None:
        if self._output_path_user_set:
            return
        base = self.base_path_var.get().strip()
        if not base:
            return
        try:
            parent = Path(base).parent
        except Exception:
            return
        name = self._suggest_output_name()
        outp = self._first_available_outdir(parent, name)
        self.output_path_var.set(str(outp))
        self._debounced_persist_gui_state()
        self._update_build_panels()



    def _open_output_folder(self) -> None:
        p = (self.output_path_var.get() or "").strip()
        if not p:
            messagebox.showwarning("Open output folder", "Output folder path is empty.")
            return
        try:
            target = Path(p)
            if target.exists() and target.is_dir():
                open_path = target
            else:
                open_path = target.parent if target.parent.exists() else target
        except Exception:
            open_path = None

        if open_path is None:
            messagebox.showerror("Open output folder", f"Could not resolve a folder from:\n{p}")
            return

        try:
            if os.name == "nt":
                os.startfile(str(open_path))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.run(["open", str(open_path)], check=False)
            else:
                subprocess.run(["xdg-open", str(open_path)], check=False)
            self._log(f"Opened folder: {open_path}")
        except Exception as e:
            messagebox.showerror("Open output folder", f"Failed to open:\n{open_path}\n\n{e}")
            self._log(f"ERROR opening folder: {open_path}: {e}")

    def _copy_output_path(self) -> None:
        p = (self.output_path_var.get() or "").strip()
        if not p:
            messagebox.showwarning("Copy output path", "Output folder path is empty.")
            return
        try:
            self.clipboard_clear()
            self.clipboard_append(p)
            self._log("Copied output path to clipboard.")
        except Exception as e:
            messagebox.showerror("Copy output path", f"Failed to copy to clipboard:\n{e}")
            self._log(f"ERROR copying output path: {e}")




    def _refresh_last_build_ui(self) -> None:
        # Render last build summary + enable/disable buttons.
        lb = {}
        try:
            lb = dict(getattr(self, "_last_build", {}) or {})
        except Exception:
            lb = {}

        txt = "Last build: —"
        try:
            ts = str(lb.get("ts") or "")
            ok = bool(lb.get("ok")) if "ok" in lb else None
            out_dir = str(lb.get("out_dir") or "")
            song_count = lb.get("song_count")
            dur_s = lb.get("duration_s")
            if ts and out_dir:
                mark = "✓" if ok else ("✗" if ok is False else "•")
                parts = [f"Last build: {mark}"]
                if isinstance(song_count, int):
                    parts.append(f"{song_count} songs")
                if isinstance(dur_s, (int, float)):
                    parts.append(f"in {self._format_duration(float(dur_s))}")
                parts.append(f"→ {Path(out_dir).name}")
                parts.append(f"({ts})")
                txt = " ".join(parts)
            elif ts:
                mark = "✓" if ok else ("✗" if ok is False else "•")
                txt = f"Last build: {mark} ({ts})"
        except Exception:
            txt = "Last build: —"

        try:
            self.last_build_var.set(txt)
        except Exception:
            pass

        # Buttons
        out_dir = str(lb.get("out_dir") or "").strip()
        log_path = str(lb.get("log_path") or "").strip()

        # Report button: build report JSON is written next to the built disc folder (v0.8g)
        report_path = str(lb.get("report_path") or "").strip()
        try:
            if (not report_path) and out_dir:
                disc_dir = Path(out_dir)
                rp_new = disc_dir.parent / f"{disc_dir.name or 'disc'}_build_report.json"
                if rp_new.exists():
                    report_path = str(rp_new)
                else:
                    # Back-compat
                    rp_old = disc_dir / "build_report.json"
                    if rp_old.exists():
                        report_path = str(rp_old)
        except Exception:
            report_path = report_path

        try:
            self.open_last_build_btn.configure(state=("normal" if out_dir else "disabled"))
        except Exception:
            pass
        try:
            self.copy_last_build_btn.configure(state=("normal" if out_dir else "disabled"))
        except Exception:
            pass
        try:
            self.log_last_build_btn.configure(state=("normal" if log_path else "disabled"))
        except Exception:
            pass
        try:
            if hasattr(self, "report_last_build_btn") and self.report_last_build_btn is not None:
                ok2 = False
                if report_path:
                    try:
                        ok2 = Path(report_path).exists()
                    except Exception:
                        ok2 = False
                self.report_last_build_btn.configure(state=("normal" if ok2 else "disabled"))
        except Exception:
            pass

    def _set_last_build_record(self, *, ok: bool, out_dir: str = "", err: str = "", duration_s: Optional[float] = None, report_path: str = "") -> None:
        # Persist last build info into settings.
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        rec = {
            "ts": ts,
            "ok": bool(ok),
            "out_dir": str(out_dir or ""),
            "song_count": int(len(getattr(self, "_selected_song_ids", set()) or set())),
            "duration_s": float(duration_s) if duration_s is not None else None,
            "err": str(err or ""),
            "report_path": str(report_path or ""),
        }
        try:
            pth = getattr(self, "_session_log_path", None)
            if pth is not None:
                rec["log_path"] = str(pth)
        except Exception:
            pass

        self._last_build = rec
        try:
            s = _load_settings()
            s["last_build"] = rec
            _save_settings(s)
        except Exception:
            pass
        self._refresh_last_build_ui()


    def _format_duration(self, seconds: float) -> str:
        try:
            s = int(round(float(seconds)))
        except Exception:
            return "—"
        m, sec = divmod(s, 60)
        h, m = divmod(m, 60)
        if h:
            return f"{h:d}:{m:02d}:{sec:02d}"
        return f"{m:d}:{sec:02d}"

    def _write_build_report(self, *, out_dir: str, ok: bool, duration_s: Optional[float], err: str = "") -> str:
        """Write a build report JSON next to the built disc folder (v0.8g).

        Returns the report path string on success, or "" on failure.
        """
        try:
            od = Path(out_dir)
            if not od.exists() or not od.is_dir():
                return ""
        except Exception:
            return ""

        # Pull preflight routing info captured at build start (best-effort).
        pre = dict(getattr(self, "_last_preflight", {}) or {})
        provider = pre.get("provider") if isinstance(pre.get("provider"), dict) else {}
        dupe_ids = pre.get("dupe_ids") if isinstance(pre.get("dupe_ids"), list) else []
        needed_donors = pre.get("needed_donors") if isinstance(pre.get("needed_donors"), list) else []
        prefer = pre.get("prefer") if isinstance(pre.get("prefer"), dict) else {}

        # Base + sources info
        base_idx = getattr(self, "_base_idx", None)
        sources: List[dict] = []
        try:
            if base_idx is not None:
                sources.append({
                    "label": "Base",
                    "input_path": str(base_idx.input_path),
                    "export_root": str(base_idx.export_root),
                    "product_code": base_idx.product_code,
                    "product_desc": base_idx.product_desc,
                    "chosen_bank": int(base_idx.chosen_bank),
                    "song_count": int(base_idx.song_count),
                    "used": True,
                })
        except Exception:
            pass

        used_set = set(["Base"] + [str(x) for x in needed_donors])
        try:
            for row_iid, idx in getattr(self, "_src_indexes", {}).items():
                lab = self._src_labels.get(row_iid, self.src_tree.set(row_iid, "label") or "Source")
                sources.append({
                    "label": str(lab),
                    "input_path": str(idx.input_path),
                    "export_root": str(idx.export_root),
                    "product_code": idx.product_code,
                    "product_desc": idx.product_desc,
                    "chosen_bank": int(idx.chosen_bank),
                    "song_count": int(idx.song_count),
                    "used": (str(lab) in used_set),
                })
        except Exception:
            pass

        selected_ids = sorted(set(getattr(self, "_selected_song_ids", set()) or set()))
        conflict_count = 0
        try:
            conflict_count = int(len(getattr(self, "_conflicts", {}) or {}))
        except Exception:
            conflict_count = 0

        # Conflicts detail (small but useful)
        conflicts_detail: List[dict] = []
        try:
            for sid, occs in (getattr(self, "_conflicts", {}) or {}).items():
                item = {
                    "song_id": int(sid),
                    "chosen": str((getattr(self, "_conflict_choices", {}) or {}).get(int(sid), "")),
                    "occurrences": [],
                }
                for o in occs:
                    item["occurrences"].append({
                        "source": str(o.source_label),
                        "title": str(o.title),
                        "artist": str(o.artist),
                        "melody1_sha1": o.melody1_sha1,
                    })
                conflicts_detail.append(item)
        except Exception:
            conflicts_detail = []

        # Include a compact song meta list for selected songs (id/title/artist/provider).
        song_meta: List[dict] = []
        try:
            # Build id->(title,artist) from current songs list
            meta_map = {}
            for s in getattr(self, "_songs", []) or []:
                try:
                    meta_map[int(s.song_id)] = (str(s.title), str(s.artist))
                except Exception:
                    continue
            for sid in selected_ids:
                t, a = meta_map.get(int(sid), ("", ""))
                prov = provider.get(int(sid)) if isinstance(provider, dict) else None
                song_meta.append({
                    "song_id": int(sid),
                    "title": t,
                    "artist": a,
                    "provider": str(prov) if prov else "",
                })
        except Exception:
            song_meta = []

        # Count duplicates (song IDs present in >1 disc) and how many were auto-resolved.
        dup_total = 0
        try:
            dup_total = int(len(set(int(x) for x in dupe_ids)))
        except Exception:
            dup_total = 0
        auto_resolved = max(0, dup_total - conflict_count)

        report = {
            "tool": {
                "name": "SingStar Disc Builder",
                "version": str(__version__),
            },
            "result": {
                "ok": bool(ok),
                "error": str(err or ""),
                "built_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "duration_s": float(duration_s) if isinstance(duration_s, (int, float)) else None,
            },
            "paths": {
                "output_dir": str(out_dir),
                "report_path": str((od.parent / f"{od.name or 'disc'}_build_report.json")),
                "session_log_path": str(getattr(self, "_session_log_path", "") or ""),
            },
            "selection": {
                "song_count": int(len(selected_ids)),
                "song_ids": selected_ids,
                "duplicates_song_ids": sorted(set(int(x) for x in dupe_ids))[:500],
                "duplicates_count": int(dup_total),
                "duplicates_auto_resolved_count": int(auto_resolved),
                "conflicts_count": int(conflict_count),
            },
            "routing": {
                "provider_by_song_id": provider,
                "preferred_source_by_song_id": prefer,
            },
            "sources": sources,
            "conflicts": conflicts_detail,
            "songs": song_meta,
        }

        try:
            rp = od.parent / f"{od.name or 'disc'}_build_report.json"
            with rp.open("w", encoding="utf-8") as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
            return str(rp)
        except Exception:
            return ""

    def _compute_build_blocker(self) -> Optional[str]:
        # Returns a short, actionable reason why Build is disabled, or None if ready.
        try:
            if self._any_long_job_running():
                return "Busy: a job is running"
        except Exception:
            pass

        if getattr(self, "_base_idx", None) is None:
            return "Index the Base disc first"

        try:
            if not getattr(self, "_selected_song_ids", set()):
                return "Select at least 1 song"
        except Exception:
            return "Select at least 1 song"

        outp = (self.output_path_var.get() or "").strip()
        if not outp:
            return "Choose an output folder"

        try:
            out_dir = Path(outp)
            if out_dir.exists():
                return "Output already exists"
            if not out_dir.parent.exists():
                return "Output parent folder is missing"
            try:
                if not os.access(str(out_dir.parent), os.W_OK):
                    return "Output parent folder is not writable"
            except Exception:
                pass
        except Exception:
            return "Output path is invalid"

        return None

    def _update_build_panels(self) -> None:
        # Update readiness line, issues banner, and Build button enablement.
        blocker = self._compute_build_blocker()
        ready = blocker is None

        # Readiness line
        if ready:
            msg = "Ready to build ✅"
        else:
            msg = f"Not ready: {blocker}"
        try:
            self.readiness_var.set(msg)
        except Exception:
            pass

        # Issues banner (non-blocking)
        issues: List[str] = []
        try:
            n_conf = len(getattr(self, "_conflicts", {}) or {})
            if n_conf:
                issues.append(f"Conflicts: {n_conf} song ID(s) differ across discs")
        except Exception:
            pass

        issues_txt = ""
        if issues:
            issues_txt = "⚠️ " + " | ".join(issues)
        try:
            self.issues_var.set(issues_txt)
        except Exception:
            pass

        # View issues button
        try:
            self.view_issues_btn.configure(state=("normal" if issues else "disabled"))
        except Exception:
            pass

        
        # Hide the issues banner row entirely when empty (avoids blank orange bar)
        try:
            if issues:
                self.issues_row.grid()
            else:
                self.issues_row.grid_remove()
        except Exception:
            pass

        # Build gating
        try:
            if getattr(self, "_build_running", False):
                self.build_btn.configure(state="disabled")
            else:
                self.build_btn.configure(state=("normal" if ready else "disabled"))
        except Exception:
            pass

        # Tooltip
        try:
            tip = getattr(self, "_build_tooltip", None)
            if tip is not None:
                if ready:
                    if issues:
                        tip.text = "Ready to build. Conflicts detected: you can build with defaults or resolve them in Status."
                    else:
                        tip.text = "Ready to build."
                else:
                    tip.text = str(blocker or "Not ready.")
        except Exception:
            pass

    def _view_issues(self) -> None:
        # Show the most relevant issues details.
        try:
            if getattr(self, "_conflicts", None):
                self._open_conflict_resolver()
                return
        except Exception:
            pass
        try:
            msg = str(self.issues_var.get() or "").strip()
        except Exception:
            msg = ""
        if not msg:
            messagebox.showinfo("Issues", "No issues detected.")
            return
        messagebox.showinfo("Issues", msg)

    def _open_path_in_os(self, path: Path) -> None:
        try:
            if os.name == "nt":
                os.startfile(str(path))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.run(["open", str(path)], check=False)
            else:
                subprocess.run(["xdg-open", str(path)], check=False)
        except Exception as e:
            messagebox.showerror("Open", f"Failed to open:\n{path}\n\n{e}")

    def _open_last_build_folder(self) -> None:
        lb = dict(getattr(self, "_last_build", {}) or {})
        out_dir = str(lb.get("out_dir") or "").strip()
        if not out_dir:
            messagebox.showwarning("Last build", "No last build output folder recorded yet.")
            return
        p = Path(out_dir)
        # Open folder if present, otherwise open parent.
        target = p if p.exists() else (p.parent if p.parent.exists() else p)
        self._open_path_in_os(target)

    def _copy_last_build_path(self) -> None:
        lb = dict(getattr(self, "_last_build", {}) or {})
        out_dir = str(lb.get("out_dir") or "").strip()
        if not out_dir:
            messagebox.showwarning("Last build", "No last build output folder recorded yet.")
            return
        try:
            self.clipboard_clear()
            self.clipboard_append(out_dir)
            self._log("Copied last build output path to clipboard.")
        except Exception as e:
            messagebox.showerror("Copy", f"Failed to copy to clipboard:\n{e}")

    def _open_last_build_log(self) -> None:
        lb = dict(getattr(self, "_last_build", {}) or {})
        log_path = str(lb.get("log_path") or "").strip()
        if not log_path:
            messagebox.showwarning("Last build log", "No log path recorded yet.")
            return
        p = Path(log_path)
        if not p.exists():
            messagebox.showwarning("Last build log", f"Log file not found:\n{p}")
            return
        self._open_path_in_os(p)


    def _open_last_build_report(self) -> None:
        lb = dict(getattr(self, "_last_build", {}) or {})
        report_path = str(lb.get("report_path") or "").strip()
        out_dir = str(lb.get("out_dir") or "").strip()

        p: Optional[Path] = None
        try:
            if report_path:
                p = Path(report_path)
            elif out_dir:
                disc_dir = Path(out_dir)
                p = disc_dir.parent / f"{disc_dir.name or 'disc'}_build_report.json"
                if not p.exists():
                    # Back-compat
                    p = disc_dir / "build_report.json"
        except Exception:
            p = None

        if p is None:
            messagebox.showwarning("Build report", "No build report path recorded yet.")
            return
        if not p.exists():
            messagebox.showwarning("Build report", f"Build report not found:\n{p}")
            return
        self._open_path_in_os(p)

    def _browse_output_parent(self) -> None:
        base = self.base_path_var.get().strip()
        initial = Path(base).parent if base else Path.cwd()
        folder = filedialog.askdirectory(title="Choose parent folder for output", initialdir=str(initial))
        if not folder:
            return
        self._output_path_user_set = True
        parent = Path(folder)
        name = self._suggest_output_name()
        outp = self._first_available_outdir(parent, name)
        self.output_path_var.set(str(outp))
        self._debounced_persist_gui_state()
        self._update_build_panels()


    def _preflight_build(
        self,
        *,
        out_dir: Path,
        prefer: Dict[int, str],
        src_label_paths: List[Tuple[str, str]],
    ) -> Tuple[Set[str], Dict[int, str], List[int], List[str]]:
        """Fail-fast checks before starting an expensive build.
    
        Returns (needed_donor_labels, provider_by_song_id, duplicate_song_ids, errors).
        """
        errors: List[str] = []
    
        # Output parent sanity + writability (best-effort probe).
        try:
            parent = out_dir.parent
            if not parent.exists():
                errors.append(f"Output parent folder is missing: {parent}")
            else:
                test_dir = parent / f".spcdb_write_test_{int(time.time())}"
                try:
                    test_dir.mkdir(exist_ok=False)
                    test_dir.rmdir()
                except Exception as e:
                    errors.append(f"Output parent folder is not writable: {parent} ({e})")
        except Exception as e:
            errors.append(f"Output path validation failed: {e}")
    
        base_idx = getattr(self, "_base_idx", None)
        if base_idx is None:
            errors.append("Base disc is not indexed.")
            return set(), {}, [], errors
    
        # Build label -> DiscIndex map (Base + GUI sources).
        label_to_idx: Dict[str, DiscIndex] = {"Base": base_idx}
        try:
            for row_iid, idx in self._src_indexes.items():
                lab = self._src_labels.get(row_iid, self.src_tree.set(row_iid, "label") or "Source")
                label_to_idx[lab] = idx
        except Exception:
            pass
    
        # Load per-disc song maps (song_id -> (title, artist))
        disc_song_maps: Dict[str, Dict[int, Tuple[str, str]]] = {}
        for lab, idx in label_to_idx.items():
            try:
                disc_song_maps[lab] = self._get_disc_song_map(idx)
            except Exception:
                disc_song_maps[lab] = {}
    
        base_song_ids: Set[int] = set(disc_song_maps.get("Base", {}).keys())
        explicit_donor: Set[int] = {sid for sid, lab in prefer.items() if lab != "Base"}
    
        # Preserve GUI source ordering for "first donor wins" implicit routing.
        donor_order: List[str] = [lab for lab, _p in src_label_paths]
    
        provider: Dict[int, str] = {}
        needed: Set[str] = {"Base"}
    
        for sid in sorted(set(getattr(self, "_selected_song_ids", set()) or set())):
            chosen: Optional[str] = None
    
            # 1) Explicit preferred source (conflict resolution)
            if sid in prefer and prefer[sid] != "Base":
                pref = prefer[sid]
                if pref in label_to_idx:
                    chosen = pref
                else:
                    errors.append(f"Song {sid}: preferred source '{pref}' is not available.")
    
            # 2) Base provides unless explicitly overridden to a donor
            if chosen is None:
                if sid in base_song_ids and sid not in explicit_donor:
                    chosen = "Base"
    
            # 3) Otherwise: first donor in GUI order that contains the song id
            if chosen is None:
                for dlab in donor_order:
                    if sid in disc_song_maps.get(dlab, {}):
                        chosen = dlab
                        break
    
            if chosen is None:
                errors.append(f"Song {sid}: not found in Base or any source songs XML.")
                continue
    
            provider[sid] = chosen
            needed.add(chosen)
    
        # Disc-level required files for involved discs.
        disc_covers_map: Dict[str, Dict[int, int]] = {}
        disc_textures_dir: Dict[str, Path] = {}
    
        for lab in sorted(needed, key=lambda x: (x != "Base", x)):
            idx = label_to_idx.get(lab)
            if idx is None:
                continue
            exp = Path(idx.export_root)
    
            if not exp.exists() or not exp.is_dir():
                errors.append(f"{lab}: Export folder missing: {exp}")
                continue
    
            cfg = exp / "config.xml"
            if not cfg.exists():
                errors.append(f"{lab}: missing Export/config.xml")
    
            cov = exp / "covers.xml"
            if not cov.exists():
                errors.append(f"{lab}: missing Export/covers.xml")
    
            tex = exp / "textures"
            if not tex.is_dir():
                errors.append(f"{lab}: missing Export/textures folder: {tex}")
            disc_textures_dir[lab] = tex
    
            if not idx.songs_xml or not Path(idx.songs_xml).exists():
                errors.append(f"{lab}: missing songs_<bank>_0.xml under Export (disc not indexed correctly).")
            if not idx.acts_xml or not Path(idx.acts_xml).exists():
                errors.append(f"{lab}: missing acts_<bank>_0.xml under Export (disc not indexed correctly).")
    
            try:
                bank = int(idx.chosen_bank)
                sl = exp / f"songlists_{bank}.xml"
                if not sl.exists():
                    errors.append(f"{lab}: missing Export/songlists_{bank}.xml")
            except Exception:
                errors.append(f"{lab}: invalid chosen bank; re-index this disc.")
    
            disc_covers_map[lab] = _covers_song_to_page(exp)
    
        # Per-song checks on the chosen provider disc.
        for sid, lab in provider.items():
            idx = label_to_idx.get(lab)
            if idx is None:
                continue
            exp = Path(idx.export_root)
            song_dir = exp / str(sid)
            if not song_dir.is_dir():
                errors.append(f"Song {sid} ({lab}): missing song folder: {song_dir}")
                continue
    
            has_melody = False
            try:
                has_melody = any(song_dir.glob("melody_*.xml"))
            except Exception:
                has_melody = False
            if not has_melody:
                errors.append(f"Song {sid} ({lab}): no melody_*.xml found in {song_dir}")
    
            covmap = disc_covers_map.get(lab, {})
            if sid not in covmap:
                errors.append(f"Song {sid} ({lab}): missing covers.xml entry (cover_{sid})")
            else:
                page = covmap[sid]
                texdir = disc_textures_dir.get(lab)
                if texdir is not None and texdir.is_dir():
                    if not _texture_page_exists(texdir, page):
                        errors.append(f"Song {sid} ({lab}): covers.xml references page_{page} but file is missing in textures")
                else:
                    errors.append(f"Song {sid} ({lab}): textures folder missing (cannot validate cover page)")
    

        # Duplicate IDs (present in >1 disc) for the current selection (useful diagnostics).
        dupe_ids: List[int] = []
        try:
            for sid in provider.keys():
                present = 0
                for lab in label_to_idx.keys():
                    if sid in disc_song_maps.get(lab, {}):
                        present += 1
                        if present > 1:
                            dupe_ids.append(int(sid))
                            break
        except Exception:
            dupe_ids = []


        needed_donors = set(needed)
        needed_donors.discard("Base")
        return needed_donors, provider, dupe_ids, errors

    def _start_build_selected(self) -> None:
        if self._build_running:
            return
        if self._base_idx is None:
            messagebox.showwarning("Build subset", "Please set and index the Base disc first.")
            return
        if not self._selected_song_ids:
            messagebox.showwarning("Build subset", "No songs selected. Tick songs in the list first.")
            return
    
        outp = self.output_path_var.get().strip()
        if not outp:
            messagebox.showwarning("Build subset", "Please choose an output folder.")
            return
        out_dir = Path(outp)
        if out_dir.exists() and not bool(getattr(self, 'allow_overwrite_output_var', tk.BooleanVar(value=False)).get()):
            messagebox.showerror(
                "Build subset",
                f"Output already exists:\n{out_dir}\n\nTip: enable 'Allow overwrite existing output' to rebuild into the same folder (recommended: keep backup on).",
            )
            return
    
        base_path = self.base_path_var.get().strip()
    
        # Resolve GUI sources in their current order (label, input_path).
        src_label_paths: List[Tuple[str, str]] = []
        for row_iid, idx in self._src_indexes.items():
            lab = self._src_labels.get(row_iid, self.src_tree.set(row_iid, "label") or "Source")
            src_label_paths.append((lab, idx.input_path))
    
        # Pre-build validation: detect non-identical duplicates across sources for selected IDs.
        try:
            self._conflicts = self._compute_conflicts(self._base_idx, set(self._selected_song_ids))
            self._update_status_from_validation()
        except Exception as e:
            messagebox.showerror("Build subset", f"Validation failed:\n{e}")
            return
    
        if self._conflicts:
            self._log(
                f"Warning: {len(self._conflicts)} conflicting song ID(s) detected across sources. "
                "Default choices will be used unless you resolve them in the Status panel."
            )
    
        # Build preferred source mapping for conflicts (used by subset builder to avoid duplicate errors).
        prefer: Dict[int, str] = {}
        for sid, occs in (getattr(self, "_conflicts", {}) or {}).items():
            if sid in self._conflict_choices:
                prefer[sid] = self._conflict_choices[sid]
                continue
            labels = [o.source_label for o in occs]
            prefer[sid] = "Base" if "Base" in labels else (labels[0] if labels else "Base")
    
        # Fail-fast preflight checks (avoid copying GBs before discovering missing files).
        needed_donors, provider, dupe_ids, preflight_errs = self._preflight_build(out_dir=out_dir, prefer=prefer, src_label_paths=src_label_paths)
        if preflight_errs:
            self._log(f"Preflight failed: {len(preflight_errs)} issue(s).")
            for ln in preflight_errs[:80]:
                self._log(f"  - {ln}")
            msg_lines = preflight_errs[:25]
            msg = "Preflight failed:\n\n" + "\n".join(msg_lines)
            if len(preflight_errs) > 25:
                msg += f"\n\n...and {len(preflight_errs) - 25} more."
            messagebox.showerror("Build subset", msg)
            try:
                self._update_build_panels()
            except Exception:
                pass
            return
    

        # Capture routing info for build_report.json (v0.5.7b)
        try:
            self._last_preflight = {
                "provider": dict(provider) if isinstance(provider, dict) else {},
                "dupe_ids": list(dupe_ids) if isinstance(dupe_ids, list) else [],
                "needed_donors": sorted(list(needed_donors)) if isinstance(needed_donors, set) else [],
                "prefer": dict(prefer) if isinstance(prefer, dict) else {},
            }
        except Exception:
            self._last_preflight = {}


        # disable while running
        self._build_running = True
        try:
            self._build_cancel_requested = False
        except Exception:
            pass
        self._build_started_ts = time.time()
        try:
            self._build_overall_pct = 0.0
            self._build_overall_last_phase = None
        except Exception:
            pass
        try:
            self.build_btn.configure(state="disabled")
        except Exception:
            pass
        try:
            self._update_cancel_build_ui()
        except Exception:
            pass
    
        self._progress_update("Build", "Starting…", indeterminate=True)
        self._log(f"Building subset: {len(self._selected_song_ids)} songs -> {out_dir}")
    
        def _worker() -> None:
            try:
                # Read preflight toggles in the UI layer (Tk vars), then delegate the rest to controller.py
                do_preflight = False
                try:
                    do_preflight = bool(getattr(self, "preflight_before_build_var", tk.BooleanVar(value=False)).get())
                except Exception:
                    do_preflight = False

                block_on_errors = False
                try:
                    block_on_errors = bool(getattr(self, "block_build_on_validate_errors_var", tk.BooleanVar(value=False)).get())
                except Exception:
                    block_on_errors = False

                cancel_token = CancelToken(check=lambda: bool(getattr(self, '_build_cancel_requested', False)))

                def _log_cb(msg: str) -> None:
                    self._queue.put(("build_log", str(msg)))

                def _report_cb(report_text: str) -> None:
                    self._queue.put(("preflight_validate_report", str(report_text)))

                run_build_subset(
                    base_path=base_path,
                    src_label_paths=src_label_paths,
                    out_dir=out_dir,
                    allow_overwrite_output=bool(getattr(self, 'allow_overwrite_output_var', tk.BooleanVar(value=False)).get()),
                    keep_backup_of_existing_output=bool(getattr(self, 'keep_backup_of_existing_output_var', tk.BooleanVar(value=True)).get()),
                    selected_song_ids=set(self._selected_song_ids),
                    needed_donors=set(needed_donors),
                    preferred_source_by_song_id=dict(prefer),
                    preflight_validate=do_preflight,
                    block_on_errors=block_on_errors,
                    log_cb=_log_cb,
                    preflight_report_cb=_report_cb,
                    cancel_token=cancel_token,
                )

                self._queue.put(("build_ok", str(out_dir)))

            except BuildBlockedError as be:
                self._queue.put(("build_err", str(be)))
            except CancelledError as ce:
                self._queue.put(("build_cancel", (str(out_dir), str(ce))))
            except Exception as e:
                self._queue.put(("build_err", str(e)))

        threading.Thread(target=_worker, daemon=True).start()
    # -------- Validation / conflicts --------

    def _run_validation_async(self) -> None:
        # Run a quick pre-build check in a worker thread (hashing melody_1.xml for selected IDs where needed).
        if self._build_running:
            return

        base_idx = self._base_idx
        selected = set(self._selected_song_ids)

        def _worker() -> None:
            try:
                conflicts = self._compute_conflicts(base_idx, selected)
                self._queue.put(("validate_ok", conflicts))
            except Exception as e:
                self._queue.put(("validate_err", str(e)))

        threading.Thread(target=_worker, daemon=True).start()

    def _compute_conflicts(self, base_idx: Optional[DiscIndex], selected: Set[int]) -> Dict[int, List[SongOccur]]:
        out: Dict[int, List[SongOccur]] = {}
        if base_idx is None or not selected:
            return out

        # Build list of sources: base + donor discs
        sources: List[Tuple[str, DiscIndex]] = [("Base", base_idx)]
        for row_iid, idx in self._src_indexes.items():
            label = self._src_labels.get(row_iid, f"Source {row_iid}")
            sources.append((label, idx))

        # Load per-disc song maps (title/artist)
        disc_song_maps: Dict[str, Dict[int, Tuple[str, str]]] = {}
        for label, idx in sources:
            disc_song_maps[label] = self._get_disc_song_map(idx)

        # For each selected song_id, see which sources contain it.
        for sid in sorted(selected):
            present: List[Tuple[str, DiscIndex]] = []
            for label, idx in sources:
                if sid in disc_song_maps[label]:
                    present.append((label, idx))
            if len(present) <= 1:
                continue

            occs: List[SongOccur] = []
            sha_set: Set[str] = set()
            sha_none = False
            for label, idx in present:
                title, artist = disc_song_maps[label].get(sid, ("", ""))
                melody1 = Path(idx.export_root) / str(sid) / "melody_1.xml"
                sha1 = _sha1_path(melody1)
                if sha1 is None:
                    sha_none = True
                else:
                    sha_set.add(sha1)
                occs.append(SongOccur(song_id=sid, title=title, artist=artist, source_label=label, melody1_sha1=sha1, melody1_fp=None))

            # conflict if multiple distinct sha1s OR any missing sha1 mixed with present
            if len(sha_set) > 1 or (sha_none and len(sha_set) >= 1):
                out[sid] = occs

        return out

    def _get_disc_song_map(self, idx: DiscIndex) -> Dict[int, Tuple[str, str]]:
        # Cache by input_path (stable).
        key = idx.input_path
        if key in self._disc_song_cache:
            return self._disc_song_cache[key]
        m = _load_songs_for_disc_cached(idx)
        self._disc_song_cache[key] = m
        return m

    def _update_status_from_validation(self) -> None:
        # Compose a compact status block.
        lines: List[str] = []
        if self._base_idx is None:
            lines.append("✗ Base disc: not set")
        else:
            lines.append("✓ Base disc: set")

        lines.append(f"✓ Included songs: {len(self._selected_song_ids)}" if self._selected_song_ids else "✗ Included songs: 0")

        if self._conflicts:
            lines.append(f"✗ Conflicts: {len(self._conflicts)} song ID(s) need resolving")
        else:
            lines.append("✓ Conflicts: none")

        outp = self.output_path_var.get().strip()
        if not outp:
            lines.append("✗ Output: not set")
        else:
            out_dir = Path(outp)
            if out_dir.exists():
                lines.append("✗ Output: already exists")
            else:
                lines.append("✓ Output: OK")

        # Reminder
        lines.append("Note: Recommended setup is SingStar updated to 6.00 and launched once.")

        self.status_var.set("\n".join(lines))

        # Enable/disable resolve button
        try:
            self.resolve_btn.configure(state=("normal" if self._conflicts else "disabled"))
        except Exception:
            pass

        self._update_build_panels()

    def _open_conflict_resolver(self) -> None:
        if not self._conflicts:
            messagebox.showinfo("Conflicts", "No conflicts detected for the current selection.")
            return

        dlg = tk.Toplevel(self)
        try:
            colors = getattr(self, '_theme_colors', None)
            if colors:
                dlg.configure(background=colors['bg'])
        except Exception:
            pass
        dlg.title("Resolve Conflicts")
        dlg.geometry("900x520")
        dlg.transient(self)
        dlg.grab_set()

        left = ttk.Frame(dlg, padding=8)
        left.pack(side=tk.LEFT, fill=tk.Y)

        right = ttk.Frame(dlg, padding=8)
        right.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        ttk.Label(left, text="Conflicting songs").pack(anchor="w")
        lb = tk.Listbox(left, height=24)
        lb.pack(fill=tk.Y, expand=True, pady=(6, 0))
        # apply theme to listbox
        try:
            colors = getattr(self, '_theme_colors', None)
            if colors:
                lb.configure(background=colors['field_bg'], foreground=colors['fg'], selectbackground=colors['sel_bg'], selectforeground=colors['sel_fg'])
        except Exception:
            pass

        conflict_ids = sorted(self._conflicts.keys())
        for sid in conflict_ids:
            occs = self._conflicts[sid]
            title = occs[0].title or ""
            artist = occs[0].artist or ""
            display = f"{sid}  {title}  —  {artist}".strip()
            lb.insert(tk.END, display)

        detail_title = tk.StringVar(value="")
        detail_artist = tk.StringVar(value="")
        detail_sha = tk.StringVar(value="")

        ttk.Label(right, textvariable=detail_title, font=("Segoe UI", 11, "bold")).pack(anchor="w")
        ttk.Label(right, textvariable=detail_artist).pack(anchor="w", pady=(0, 8))

        ttk.Label(right, text="Choose which source to use for this song ID:").pack(anchor="w")

        choice_var = tk.StringVar(value="")
        radios_frame = ttk.Frame(right)
        radios_frame.pack(fill=tk.X, pady=(6, 0))

        occ_list_frame = ttk.Frame(right)
        occ_list_frame.pack(fill=tk.BOTH, expand=True, pady=(10, 0))

        cols = ("source", "sha1")
        occ_tree = ttk.Treeview(occ_list_frame, columns=cols, show="headings", height=12)
        occ_tree.heading("source", text="Source")
        occ_tree.heading("sha1", text="melody_1.xml sha1")
        occ_tree.column("source", width=220, anchor="w")
        occ_tree.column("sha1", width=520, anchor="w")
        occ_tree.pack(fill=tk.BOTH, expand=True)

        def _render_detail(idx: int) -> None:
            if idx < 0 or idx >= len(conflict_ids):
                return
            sid = conflict_ids[idx]
            occs = self._conflicts[sid]
            t = occs[0].title or ""
            a = occs[0].artist or ""
            detail_title.set(f"{sid}  {t}".strip())
            detail_artist.set(a)

            # clear old
            for c in radios_frame.winfo_children():
                c.destroy()
            for item in occ_tree.get_children():
                occ_tree.delete(item)

            # default choice: existing stored, else prefer Base if present, else first
            default = self._conflict_choices.get(sid)
            if not default:
                labels = [o.source_label for o in occs]
                default = "Base" if "Base" in labels else labels[0]
            choice_var.set(default)

            for o in occs:
                occ_tree.insert("", tk.END, values=(o.source_label, o.melody1_sha1 or "(missing)"))
                ttk.Radiobutton(radios_frame, text=o.source_label, value=o.source_label, variable=choice_var).pack(anchor="w")

        def _on_select(_e=None) -> None:
            sel = lb.curselection()
            if not sel:
                return
            _render_detail(sel[0])

        lb.bind("<<ListboxSelect>>", _on_select)

        def _save_choice() -> None:
            sel = lb.curselection()
            if not sel:
                return
            sid = conflict_ids[sel[0]]
            self._conflict_choices[sid] = choice_var.get()
            messagebox.showinfo("Conflicts", f"Choice saved for song_id {sid}: {choice_var.get()}")

        def _save_all_defaults() -> None:
            # Apply current choice to all conflicts (useful if you just want Base everywhere).
            val = choice_var.get() or "Base"
            for sid in conflict_ids:
                self._conflict_choices[sid] = val
            messagebox.showinfo("Conflicts", f"Applied '{val}' to all conflicts.")

        btn_row = ttk.Frame(right)
        btn_row.pack(fill=tk.X, pady=(10, 0))
        ttk.Button(btn_row, text="Save choice for this song", command=_save_choice).pack(side=tk.LEFT)
        ttk.Button(btn_row, text="Apply current choice to ALL", command=_save_all_defaults).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(btn_row, text="Close", command=dlg.destroy).pack(side=tk.RIGHT)

        # initialize selection
        if conflict_ids:
            lb.selection_set(0)
            _render_detail(0)

    # -------- Overrides --------
def run_gui() -> None:
    app = SPCDBGui()
    app.mainloop()
