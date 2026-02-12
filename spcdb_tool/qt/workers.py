"""Qt worker objects (QThread/QObject) for long-running operations.

These are imported lazily by qt_app.py inside run_qt_gui() so importing SSPCDB
without PySide6 installed still works.
"""

from __future__ import annotations

import os
import shutil
import time

from pathlib import Path
from typing import Dict, Optional, Tuple

from PySide6.QtCore import QObject, Signal, Slot

from ..controller import (
    BuildBlockedError,
    CancelToken,
    CancelledError,
    build_song_catalog,
    cleanup_extraction_artifacts,
    compute_song_id_conflicts,
    extract_disc_pkds,
    index_disc,
    run_build_subset,
    validate_discs,
    verify_disc_extraction,
    _find_extraction_artifacts,
)

from .utils import _scan_for_disc_inputs

class ValidateWorker(QObject):
    log = Signal(str)
    done = Signal(str, object)  # report_text, results
    cancelled = Signal()
    error = Signal(str)
    finished = Signal()

    def __init__(self, targets, cancel_token: CancelToken) -> None:
        super().__init__()
        self._targets = list(targets)
        self._cancel_token = cancel_token

    @Slot()
    def run(self) -> None:
        try:
            results, report_text = validate_discs(
                self._targets, log_cb=self.log.emit, cancel_token=self._cancel_token
            )
            self.done.emit(str(report_text or ""), results)
        except CancelledError:
            self.cancelled.emit()
        except Exception as e:
            self.error.emit(str(e))
        finally:
            try:
                self.finished.emit()
            except Exception:
                pass


class ExtractWorker(QObject):
    log = Signal(str)
    done = Signal(object)  # list or dict payload
    cancelled = Signal()
    error = Signal(str)
    finished = Signal()

    def __init__(self, extractor_exe: str, targets, cancel_token: CancelToken) -> None:
        super().__init__()
        self._extractor_exe = str(extractor_exe or "").strip()
        self._targets = list(targets)
        self._cancel_token = cancel_token

    @Slot()
    def run(self) -> None:
        try:
            if not self._extractor_exe:
                raise RuntimeError("Extractor executable is empty. Set it first.")
            results = []
            exe_p = Path(self._extractor_exe)
            for (label, disc_root) in self._targets:
                # Best-effort cancellation between PKDs/harvest loops.
                self._cancel_token.raise_if_cancelled("Cancelled")
                self.log.emit(f"[extract] Starting: {label}: {disc_root}")
                stats: dict = {}
                dest_export, harvested = extract_disc_pkds(
                    exe_p,
                    Path(disc_root),
                    log_cb=self.log.emit,
                    cancel_token=self._cancel_token,
                    allow_mid_disc_cancel=True,
                    stats_out=stats,
                )
                results.append(
                    {
                        "label": str(label),
                        "disc_root": str(disc_root),
                        "dest_export": str(dest_export),
                        "harvested": int(harvested),
                        "extract_stats": dict(stats),
                    }
                )

                verify = verify_disc_extraction(Path(disc_root), log_cb=self.log.emit)
                try:
                    results[-1]["verify"] = verify
                except Exception:
                    pass
                if bool((verify or {}).get("ok")):
                    self.log.emit(f"[verify] OK: {label}")
                else:
                    errs = (verify or {}).get("errors") or []
                    if errs:
                        self.log.emit(f"[verify] FAIL: {label}: {'; '.join([str(x) for x in errs[:3]])}")
                    else:
                        self.log.emit(f"[verify] FAIL: {label} (see log)")
                try:
                    sf = int((stats or {}).get("pkds_found", 0) or 0)
                    se = int((stats or {}).get("pkds_to_extract", 0) or 0)
                    ss = int((stats or {}).get("pkds_skipped", 0) or 0)
                    si = int((stats or {}).get("pkd_out_incomplete", 0) or 0)
                    sm = int((stats or {}).get("pkd_out_moved_aside", 0) or 0)
                    hc = bool((stats or {}).get("has_config_xml", False))
                    self.log.emit(
                        f"[extract] Summary: {label}: pkd found={sf} extract={se} skip={ss} "
                        f"incomplete_out={si} moved_aside={sm} harvested={int(harvested)} config_xml={'Y' if hc else 'N'}"
                    )
                    if not hc:
                        self.log.emit(f"[extract][WARN] {label}: Export/config.xml missing after harvest (disc may be partial).")
                except Exception:
                    pass
                self.log.emit(f"[extract] Done: {label} (harvested {harvested})")
            self.done.emit(results)
        except CancelledError:
            self.cancelled.emit()
        except Exception as e:
            self.error.emit(str(e))
        finally:
            try:
                self.finished.emit()
            except Exception:
                pass



class CleanupWorker(QObject):
    log = Signal(str)
    done = Signal(object)  # list or dict payload
    cancelled = Signal()
    error = Signal(str)
    finished = Signal()

    def __init__(
        self,
        targets,
        *,
        include_pkd_files: bool,
        delete_instead: bool,
        cancel_token: CancelToken,
        trash_root_dir: Optional[str] = None,
        empty_trash_first: bool = False,
        skip_artifacts_cleanup: bool = False,
    ) -> None:
        super().__init__()
        self._targets = list(targets or [])
        self._include_pkd_files = bool(include_pkd_files)
        self._delete_instead = bool(delete_instead)
        self._cancel_token = cancel_token
        self._trash_root_dir = str(trash_root_dir or "").strip() or None
        self._empty_trash_first = bool(empty_trash_first)
        self._skip_artifacts_cleanup = bool(skip_artifacts_cleanup)

    @Slot()
    def run(self) -> None:
        try:
            results = []
            # Use a single timestamp so all cleaned discs land in the same session folder.
            trash_ts = time.strftime("%Y%m%d_%H%M%S")

            trash_emptied = None
            if self._empty_trash_first:
                # Derive trash folder(s). Trash lives alongside each disc folder:
                #   <discs_folder>/_spcdb_trash/<timestamp>/<disc_folder>/
                trash_dirs = []
                try:
                    if self._trash_root_dir:
                        trash_dirs = [Path(self._trash_root_dir) / "_spcdb_trash"]
                    else:
                        for d0 in self._targets:
                            try:
                                disc_root0 = Path(str(d0))
                                trash_dirs.append(disc_root0.parent / "_spcdb_trash")
                            except Exception:
                                pass
                except Exception:
                    trash_dirs = []

                # De-duplicate
                uniq_trash_dirs = []
                try:
                    seen = set()
                    for td in trash_dirs:
                        tds = str(td)
                        if tds in seen:
                            continue
                        seen.add(tds)
                        uniq_trash_dirs.append(td)
                except Exception:
                    uniq_trash_dirs = trash_dirs

                del_files = 0
                del_dirs = 0
                del_entries = 0
                emptied_dirs = []

                if not uniq_trash_dirs:
                    try:
                        self.log.emit("[cleanup][WARN] Empty trash requested but no trash folder could be derived.")
                    except Exception:
                        pass
                else:
                    for trash_dir in uniq_trash_dirs:
                        self._cancel_token.raise_if_cancelled("Cancelled")
                        try:
                            trash_dir = trash_dir.resolve()
                        except Exception:
                            pass

                        if not trash_dir.exists() or not trash_dir.is_dir():
                            try:
                                self.log.emit(f"[cleanup] Trash folder not found: {trash_dir} (nothing to empty)")
                            except Exception:
                                pass
                            continue

                        self.log.emit(f"[cleanup] Emptying trash folder (permanent delete): {trash_dir}")
                        try:
                            for ent in list(trash_dir.iterdir()):
                                self._cancel_token.raise_if_cancelled("Cancelled")
                                try:
                                    if ent.is_symlink():
                                        ent.unlink()
                                        del_files += 1
                                    elif ent.is_dir():
                                        shutil.rmtree(str(ent), ignore_errors=False)
                                        del_dirs += 1
                                    else:
                                        try:
                                            ent.unlink()
                                        except Exception:
                                            try:
                                                os.chmod(str(ent), 0o666)
                                            except Exception:
                                                pass
                                            ent.unlink()
                                        del_files += 1
                                    del_entries += 1
                                except Exception as e:
                                    self.log.emit(f"[cleanup][WARN] Failed to delete trash entry: {ent}: {e}")
                                    raise
                            emptied_dirs.append(str(trash_dir))
                        except Exception:
                            raise

                trash_emptied = {
                    "trash_dirs": list(emptied_dirs),
                    "deleted_entries": int(del_entries),
                    "deleted_files": int(del_files),
                    "deleted_dirs": int(del_dirs),
                }
                try:
                    self.log.emit(
                        f"[cleanup] Trash emptied: dirs={len(emptied_dirs)} entries={del_entries} files={del_files} dirs_rm={del_dirs}"
                    )
                except Exception:
                    pass
            if getattr(self, "_skip_artifacts_cleanup", False):
                # Empty-trash-only run: skip per-disc artifact moves/deletes.
                self.done.emit({"results": [], "trash_emptied": (trash_emptied or {})})
                return

            for d in self._targets:
                self._cancel_token.raise_if_cancelled("Cancelled")
                disc_root = Path(str(d))
                self.log.emit(f"[cleanup] Starting: {disc_root}")
                res = cleanup_extraction_artifacts(
                    disc_root,
                    include_pkd_out_dirs=True,
                    include_pkd_files=self._include_pkd_files,
                    delete_instead=self._delete_instead,
                    trash_root_dir=Path(self._trash_root_dir) if self._trash_root_dir else None,
                    trash_ts=trash_ts,
                    log_cb=self.log.emit,
                )
                results.append({"disc_root": str(disc_root), "result": res})
            self.done.emit({"results": results, "trash_emptied": (trash_emptied or {})})
        except CancelledError:
            self.cancelled.emit()
        except Exception as e:
            self.error.emit(str(e))
        finally:
            try:
                self.finished.emit()
            except Exception:
                pass

class ScanWorker(QObject):
    log = Signal(str)
    done = Signal(object)  # found_paths list
    cancelled = Signal()
    error = Signal(str)
    finished = Signal()

    def __init__(self, root_dir: str, *, max_depth: int = 4, cancel_token: Optional[CancelToken] = None) -> None:
        super().__init__()
        self._root_dir = str(root_dir or '').strip()
        self._max_depth = int(max_depth or 4)
        self._cancel_token = cancel_token

    @Slot()
    def run(self) -> None:
        try:
            found = _scan_for_disc_inputs(
                Path(self._root_dir),
                max_depth=self._max_depth,
                log=self.log.emit,
                cancel=self._cancel_token,
            )
            self.done.emit(found)
        except CancelledError:
            self.cancelled.emit()
        except Exception as e:
            self.error.emit(str(e))
        finally:
            try:
                self.finished.emit()
            except Exception:
                pass


class ArtifactsPreviewWorker(QObject):
    """Compute a per-disc preview of PKD artifacts.

    This runs in a background QThread so the UI stays responsive.
    """

    log = Signal(str)
    done = Signal(object)  # list[{disc_root, pkd_files, pkd_out_dirs}]
    cancelled = Signal()
    error = Signal(str)
    finished = Signal()

    def __init__(self, targets, *, cancel_token: CancelToken) -> None:
        super().__init__()
        self._targets = list(targets or [])
        self._cancel_token = cancel_token

    @Slot()
    def run(self) -> None:
        try:
            out = []
            total = int(len(self._targets))
            for i, d in enumerate(self._targets, start=1):
                self._cancel_token.raise_if_cancelled("Cancelled")
                disc_root = Path(str(d)).expanduser()
                try:
                    disc_root = disc_root.resolve()
                except Exception:
                    pass
                try:
                    arts = _find_extraction_artifacts(disc_root)
                except Exception as e:
                    arts = {"pkd_files": [], "pkd_out_dirs": []}
                    try:
                        self.log.emit(f"[cleanup] Preview warn: {disc_root}: {e}")
                    except Exception:
                        pass
                pkd_files = list((arts or {}).get("pkd_files", []) or [])
                pkd_out_dirs = list((arts or {}).get("pkd_out_dirs", []) or [])
                out.append(
                    {
                        "disc_root": str(disc_root),
                        "pkd_files": pkd_files,
                        "pkd_out_dirs": pkd_out_dirs,
                    }
                )
                try:
                    self.log.emit(
                        f"[cleanup] Preview ({i}/{total}): {disc_root.name} | pkd_out={len(pkd_out_dirs)} pkd={len(pkd_files)}"
                    )
                except Exception:
                    pass
            self.done.emit(out)
        except CancelledError:
            self.cancelled.emit()
        except Exception as e:
            self.error.emit(str(e))
        finally:
            try:
                self.finished.emit()
            except Exception:
                pass


class SongsWorker(QObject):
    log = Signal(str)
    done = Signal(object, object, object, object)  # songs_out, disc_song_ids_by_label, export_roots_by_label, conflicts_by_song_id
    cancelled = Signal()
    error = Signal(str)
    finished = Signal()

    def __init__(self, targets, cancel_token: CancelToken) -> None:
        super().__init__()
        # targets: list[(label, path, is_base)]
        self._targets = list(targets or [])
        self._cancel_token = cancel_token

    @Slot()
    def run(self) -> None:
        try:
            discs = []
            for (label, disc_root, is_base) in self._targets:
                self._cancel_token.raise_if_cancelled("Cancelled")
                di = index_disc(str(disc_root))
                discs.append((str(label), di, bool(is_base)))

            songs_out, disc_song_ids_by_label = build_song_catalog(
                discs, cancel=self._cancel_token, log=self.log.emit
            )
            export_roots_by_label: Dict[str, str] = {}
            try:
                for (lab, di, _is_base) in discs:
                    try:
                        export_roots_by_label[str(lab)] = str(getattr(di, "export_root", "") or "")
                    except Exception:
                        pass
            except Exception:
                export_roots_by_label = {}

            conflicts_by_song_id = {}
            try:
                conflicts_by_song_id = compute_song_id_conflicts(songs_out, export_roots_by_label)
            except Exception:
                conflicts_by_song_id = {}
            try:
                if conflicts_by_song_id:
                    self.log.emit(f"[conflicts] Found {len(conflicts_by_song_id)} conflict(s) (SHA1 mismatch).")
            except Exception:
                pass

            self.done.emit(songs_out, disc_song_ids_by_label, export_roots_by_label, conflicts_by_song_id)
        except CancelledError:
            self.cancelled.emit()
        except Exception as e:
            self.error.emit(str(e))
        finally:
            try:
                self.finished.emit()
            except Exception:
                pass


class BuildWorker(QObject):
    log = Signal(str)
    preflight_report = Signal(str)
    done = Signal(str)  # out_dir
    cancelled = Signal()
    blocked = Signal(str)
    error = Signal(str)
    finished = Signal()

    def __init__(
        self,
        *,
        base_path: str,
        src_label_paths,
        out_dir: str,
        allow_overwrite_output: bool = False,
        keep_backup_of_existing_output: bool = True,
        fast_update_existing_output: bool = False,
        selected_song_ids: set[int],
        needed_donors: set[str],
        preferred_source_by_song_id: Dict[int, str],
        song_sources_by_id: Optional[Dict[int, Tuple[str, ...]]] = None,
        expected_song_rows: Optional[list[dict]] = None,
        preflight_validate: bool,
        block_on_errors: bool,
        cancel_token: CancelToken,
    ) -> None:
        super().__init__()
        self._base_path = str(base_path or '').strip()
        self._src_label_paths = list(src_label_paths or [])
        self._out_dir = str(out_dir or '').strip()
        self._allow_overwrite_output = bool(allow_overwrite_output)
        self._keep_backup_of_existing_output = bool(keep_backup_of_existing_output)
        self._fast_update_existing_output = bool(fast_update_existing_output)
        self._selected_song_ids = set(int(x) for x in (selected_song_ids or set()))
        self._needed_donors = set(str(x) for x in (needed_donors or set()))
        self._preferred_source_by_song_id = dict((int(k), str(v)) for (k, v) in (preferred_source_by_song_id or {}).items())
        self._song_sources_by_id = dict((int(k), tuple(v or ())) for (k, v) in (song_sources_by_id or {}).items())
        self._expected_song_rows = list(expected_song_rows or [])
        self._preflight_validate = bool(preflight_validate)
        self._block_on_errors = bool(block_on_errors)
        self._cancel_token = cancel_token

    @Slot()
    def run(self) -> None:
        try:
            if not self._base_path:
                raise RuntimeError('Base path is empty.')
            if not self._out_dir:
                raise RuntimeError('Output location is empty.')
            if not self._selected_song_ids:
                raise RuntimeError('No songs selected. Use the Songs table to select at least one song.')

            out_dir_p = Path(self._out_dir).expanduser().resolve()
            if out_dir_p.exists() and not bool(self._allow_overwrite_output):
                raise RuntimeError(f'Output already exists: {out_dir_p}')

            self._cancel_token.raise_if_cancelled('Cancelled')

            # Sanity: ensure donors exist in src_label_paths
            known_src_labels = {str(lab) for (lab, _sp) in (self._src_label_paths or [])}

            # Normalize preferred sources: anything unknown -> Base
            prefer: Dict[int, str] = {}
            for sid in sorted(self._selected_song_ids):
                v = str(self._preferred_source_by_song_id.get(int(sid), 'Base') or 'Base')
                if v != 'Base' and v not in known_src_labels:
                    v = 'Base'
                prefer[int(sid)] = v

            # Donors needed: all preferred sources excluding Base
            needed_donors = {v for v in prefer.values() if v != 'Base'}

            def _report_cb(report_text: str) -> None:
                try:
                    self.preflight_report.emit(str(report_text or ''))
                except Exception:
                    pass

            run_build_subset(
                base_path=self._base_path,
                src_label_paths=[(str(lab), str(sp)) for (lab, sp) in (self._src_label_paths or [])],
                out_dir=out_dir_p,
                allow_overwrite_output=bool(self._allow_overwrite_output),
                keep_backup_of_existing_output=bool(self._keep_backup_of_existing_output),
                fast_update_existing_output=bool(self._fast_update_existing_output),
                selected_song_ids=set(int(x) for x in self._selected_song_ids),
                needed_donors=set(str(x) for x in needed_donors),
                preferred_source_by_song_id=dict(prefer),
                preflight_validate=bool(self._preflight_validate),
                block_on_errors=bool(self._block_on_errors),
                log_cb=self.log.emit,
                song_sources_by_id={int(k): tuple(v or ()) for (k, v) in (self._song_sources_by_id or {}).items()},
                expected_song_rows=list(self._expected_song_rows or []),
                preflight_report_cb=_report_cb,
                cancel_token=self._cancel_token,
            )

            self.done.emit(str(out_dir_p))

        except BuildBlockedError as be:
            self.blocked.emit(str(be))
        except CancelledError:
            self.cancelled.emit()
        except Exception as e:
            self.error.emit(str(e))
        finally:
            try:
                self.finished.emit()
            except Exception:
                pass



class CopyDiscWorker(QObject):
    log = Signal(str)
    done = Signal(str)  # dst_dir
    error = Signal(str)
    finished = Signal()

    def __init__(self, *, src_dir: str, dst_dir: str) -> None:
        super().__init__()
        self._src_dir = str(src_dir or '').strip()
        self._dst_dir = str(dst_dir or '').strip()

    @Slot()
    def run(self) -> None:
        try:
            if not self._src_dir:
                raise RuntimeError("Source folder is empty.")
            if not self._dst_dir:
                raise RuntimeError("Destination folder is empty.")
            src = Path(self._src_dir).expanduser().resolve()
            dst = Path(self._dst_dir).expanduser().resolve()
            if not src.exists() or not src.is_dir():
                raise RuntimeError(f"Source folder not found: {src}")
            if dst.exists():
                raise RuntimeError(f"Destination already exists: {dst}")

            try:
                self.log.emit(f"[copy] Copying disc folder to: {dst}")
            except Exception:
                pass

            shutil.copytree(src, dst)
            self.done.emit(str(dst))
        except Exception as e:
            self.error.emit(str(e))
        finally:
            try:
                self.finished.emit()
            except Exception:
                pass
