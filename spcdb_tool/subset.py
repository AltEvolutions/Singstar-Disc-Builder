from __future__ import annotations

import json
import os
import shutil
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set, Tuple

from .layout import ResolvedInput
from .melody_fingerprint import melody_fingerprint_file
from .merge import (
    MergeError,
    CancelRequested,
    _build_act_map,
    _build_config,
    _collect_covers,
    _collect_songs,
    _ensure_lowercase_textures,
    _ensure_versioned_melody_files,
    _extract_cover_page_num,
    _list_texture_pages,
    _max_page_index,
    _normalize_key,
    _ns_tag,
    _parse_int_attr,
    _parse_songs_and_acts,
    _parse_songlists,
    _parse_covers,
    _rebuild_chc,
    _rewrite_cover_page,
    _strip_ns,
    _validate_chc,
    _write_xml,
_copy_selected_texture_pages_with_renumber,
    _merge_songlists_union_by_name,
    _choose_bank,
    _detect_max_bank,
    _read_xml,
)


ProgressFn = Callable[[str], None]


class BuildCancelled(RuntimeError):
    """Raised when a build is cancelled (disc/step boundary)."""

    def __init__(self, out_dir: Path, message: str = "Build cancelled") -> None:
        super().__init__(message)
        self.out_dir = Path(out_dir)


@dataclass(frozen=True)
class SubsetOptions:
    target_version: int = 6
    mode: str = "update-required"  # update-required | self-contained
    songlist_mode: str = "union-by-name"  # future expansion
    verbose: bool = False


def _rename_dir_with_retries(
    src: Path,
    dst: Path,
    *,
    max_attempts: int = 20,
    sleep_s: float = 0.1,
) -> None:
    """Rename a directory with retries.

    On Windows, freshly-written files inside a directory can be briefly locked
    by AV/Defender or indexing, causing transient access-denied errors on rename.
    """
    import gc
    import time

    last_err: Exception | None = None
    for i in range(int(max_attempts)):
        try:
            src.rename(dst)
            return
        except PermissionError as e:
            last_err = e
        except OSError as e:
            # Windows can surface access-denied or sharing violations here too.
            last_err = e
            winerr = getattr(e, "winerror", None)
            if winerr not in (5, 32):  # access denied, sharing violation
                raise

        if i >= int(max_attempts) - 1:
            assert last_err is not None
            raise last_err

        try:
            gc.collect()
        except Exception:
            pass
        try:
            time.sleep(float(sleep_s))
        except Exception:
            pass


def _compute_copy_root_and_rel_export(ri: ResolvedInput) -> tuple[Path, Path]:
    """Return (copy_root, rel_export_path).

    copy_root is the folder we will copy into the output disc root.
    rel_export_path is the relative path from copy_root to the Export folder.

    This is important because users sometimes point the GUI at PS3_GAME (or deeper),
    but the output must be a disc root that contains PS3_GAME and PS3_DISC.SFB.
    """
    exp = ri.export_root.resolve()

    # Typical PS3 layout: <disc_root>/PS3_GAME/USRDIR/FileSystem/Export
    ps3_game_parent: Optional[Path] = None
    for p in [exp] + list(exp.parents):
        if p.name.upper() == "PS3_GAME":
            ps3_game_parent = p.parent
            break

    if ps3_game_parent is not None and (ps3_game_parent / "PS3_GAME").exists():
        copy_root = ps3_game_parent
        try:
            rel_export = exp.relative_to(copy_root)
            return copy_root, rel_export
        except ValueError:
            # fall through
            pass

    # If original is a directory, prefer that as the copy root.
    if ri.original.exists() and ri.original.is_dir():
        orig = ri.original.resolve()

        # If user selected PS3_GAME directly, we want the parent disc root if present.
        if orig.name.upper() == "PS3_GAME" and orig.parent.exists():
            parent = orig.parent
            if (parent / "PS3_GAME").exists():
                try:
                    return parent, exp.relative_to(parent)
                except ValueError:
                    pass

        try:
            return orig, exp.relative_to(orig)
        except ValueError:
            # If orig isn't an ancestor of export, fall back to resolved_root
            pass

    # For zip_extracted inputs, ri.original is the .zip file path; use resolved_root as a sane copy root.
    if ri.resolved_root.exists() and ri.resolved_root.is_dir():
        rr = ri.resolved_root.resolve()
        try:
            return rr, exp.relative_to(rr)
        except ValueError:
            # last resort: treat resolved_root as export root
            return rr, Path("")

    # Final fallback
    return exp, Path("")


def _delete_unselected_song_folders(export_root: Path, keep_song_ids: Set[int], progress: Optional[ProgressFn] = None) -> None:
    # Remove numeric Export/<id>/ folders not in selection.
    for p in export_root.iterdir():
        if not p.is_dir():
            continue
        if not p.name.isdigit():
            continue
        sid = int(p.name)
        if sid in keep_song_ids:
            continue
        try:
            shutil.rmtree(p)
        except Exception:
            # best-effort cleanup; keep going
            pass
    if progress:
        progress(f"Pruned song folders: kept {len(keep_song_ids)} selected ids.")


def _is_effectively_empty_dir(p: Path) -> bool:
    """Return True if a directory contains no meaningful entries.

    This treats common OS junk files as ignorable.
    """
    try:
        for c in p.iterdir():
            try:
                name = c.name
            except Exception:
                return False
            if name in {".DS_Store", "Thumbs.db"}:
                continue
            return False
    except Exception:
        return False
    return True


def _looks_like_spcdb_output_folder(root: Path) -> tuple[bool, str]:
    """Best-effort guardrail check for overwrite safety.

    We consider it "safe-ish" to overwrite when the folder looks like an extracted SingStar disc/output,
    i.e. it contains an Export root with songs XML (and usually config.xml), or it is empty.

    This is intentionally heuristic; it is meant to prevent obvious foot-guns (e.g. choosing Documents/).
    """
    if not root.exists() or not root.is_dir():
        return False, "path is not a directory"

    if _is_effectively_empty_dir(root):
        return True, "folder is empty"

    # Candidates ordered by most common on PS3.
    candidates = [
        root / "PS3_GAME" / "USRDIR" / "FileSystem" / "Export",
        root / "USRDIR" / "FileSystem" / "Export",
        root / "Export",
        root,
    ]

    def _has_numeric_song_folders(exp: Path) -> bool:
        try:
            for p in exp.iterdir():
                if p.is_dir() and str(p.name).isdigit():
                    return True
        except Exception:
            return False
        return False

    for exp in candidates:
        try:
            if not exp.exists() or not exp.is_dir():
                continue
            has_songs = bool(list(exp.glob("songs_*_0.xml"))) or bool(list(exp.glob("songs_*.xml")))
            if not has_songs:
                continue
            has_cfg = (exp / "config.xml").is_file()
            has_covers = (exp / "covers.xml").is_file()
            has_numeric = _has_numeric_song_folders(exp)
            if has_cfg or has_covers or has_numeric:
                try:
                    rel = str(exp.relative_to(root))
                except Exception:
                    rel = str(exp)
                return True, f"found Export signature at {rel}"
        except Exception:
            continue

    if (root / "PS3_GAME").exists():
        return False, "PS3_GAME exists but no Export signature (songs/config) was found"
    return False, "no Export signature (songs/config) was found"


def _overwrite_input_paths_guard(
    base_ri: ResolvedInput,
    source_ris: List[Tuple[str, ResolvedInput]],
    out_dir: Path,
) -> None:
    """Refuse to overwrite if the output folder appears to be one of the inputs (base/donor).

    This is a stronger guardrail than "looks like Export" because base/donor folders also look valid.
    """
    try:
        out_abs = out_dir.resolve()
    except Exception:
        out_abs = out_dir

    def _all_paths(label: str, ri: ResolvedInput) -> list[tuple[str, Path]]:
        out: list[tuple[str, Path]] = []
        for attr in ("original", "resolved_root", "export_root"):
            try:
                p = getattr(ri, attr, None)
                if p is None:
                    continue
                pp = Path(str(p))
                try:
                    pp = pp.resolve()
                except Exception:
                    pass
                out.append((f"{label}:{attr}", pp))
            except Exception:
                continue
        # de-dupe
        seen: set[Path] = set()
        uniq: list[tuple[str, Path]] = []
        for k, p in out:
            if p in seen:
                continue
            seen.add(p)
            uniq.append((k, p))
        return uniq

    checks: list[tuple[str, Path]] = []
    checks.extend(_all_paths("base", base_ri))
    for lbl, ri in (source_ris or []):
        checks.extend(_all_paths(f"donor:{lbl}", ri))

    hits: list[str] = []
    for k, p in checks:
        try:
            if out_abs == p:
                hits.append(k)
        except Exception:
            continue

    if hits:
        show = ", ".join(hits[:3])
        more = "" if len(hits) <= 3 else f" (+{len(hits) - 3} more)"
        raise MergeError(
            "Refusing to overwrite the selected output folder because it matches one of your inputs (base/donor).\n"
            f"Output: {out_dir}\n"
            f"Matches: {show}{more}\n\n"
            "Choose a dedicated output folder that is NOT any of the selected discs/exports."
        )




def _find_export_root_from_disc_root(root: Path) -> Path:
    """Locate the Export folder within a disc/output root (best-effort)."""
    root = Path(root)
    candidates = [
        root / "PS3_GAME" / "USRDIR" / "FileSystem" / "Export",
        root / "USRDIR" / "FileSystem" / "Export",
        root / "Export",
        root,
    ]
    for p in candidates:
        try:
            if p.exists() and p.is_dir():
                return p
        except Exception:
            continue
    raise MergeError(f"Could not locate Export folder under: {root}")


def _copytree_hardlink_or_copy(src: Path, dst: Path, *, ignore=None) -> None:
    """Copy a folder tree, preferring hardlinks for files (falls back to copy2).

    Hardlinks can dramatically speed up "update" builds when seeding from a previous output.
    If hardlinking is not possible (different volume, permissions), we fall back to copying.
    """
    src = Path(src)
    dst = Path(dst)
    if dst.exists():
        raise MergeError(f"Destination already exists: {dst}")

    # Create root folder first so empty dirs are preserved.
    dst.mkdir(parents=True, exist_ok=False)

    def _link_or_copy_file(sp: Path, dp: Path) -> None:
        try:
            if sp.is_symlink():
                shutil.copy2(sp, dp)
                return
        except Exception:
            pass
        try:
            os.link(str(sp), str(dp))
        except Exception:
            shutil.copy2(sp, dp)

    for root_s, dirs, files in os.walk(str(src), topdown=True, followlinks=False):
        root_p = Path(root_s)
        rel = root_p.relative_to(src)
        dst_root = dst / rel
        if not dst_root.exists():
            dst_root.mkdir(parents=True, exist_ok=True)

        ignored: set[str] = set()
        if ignore is not None:
            try:
                ignored = set(ignore(str(root_p), list(dirs) + list(files)) or set())
            except Exception:
                ignored = set()

        # Prune ignored dirs from traversal.
        if ignored:
            dirs[:] = [d for d in dirs if d not in ignored]
            files = [f for f in files if f not in ignored]

        # Ensure directories exist.
        for d in dirs:
            try:
                (dst_root / d).mkdir(parents=True, exist_ok=True)
            except Exception:
                pass

        # Link/copy files.
        for f in files:
            sp = root_p / f
            dp = dst_root / f
            _link_or_copy_file(sp, dp)


def _copytree_maybe_hardlink(src: Path, dst: Path, *, ignore=None, use_hardlinks: bool = False) -> None:
    if not use_hardlinks:
        shutil.copytree(src, dst, ignore=ignore)
        return
    _copytree_hardlink_or_copy(src, dst, ignore=ignore)


def build_subset(
    base_ri: ResolvedInput,
    source_ris: List[Tuple[str, ResolvedInput]],
    out_dir: Path,
    selected_song_ids: Set[int],
    opts: SubsetOptions,
    preferred_source_by_song_id: Optional[Dict[int, str]] = None,
    allow_overwrite: bool = False,
    keep_backup: bool = True,
    fast_update_existing_output: bool = False,
    progress: Optional[ProgressFn] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> None:
    """
    Build a new extracted 'disc folder' output that contains ONLY the selected songs,
    using base_ri as the template. Songs not present in base (or explicitly overridden) are pulled from labeled sources.
    """
    if not selected_song_ids:
        raise MergeError("No songs selected.")

    # Allow immediate cancellation before any work starts.
    if cancel_check is not None:
        try:
            if bool(cancel_check()):
                raise BuildCancelled(out_dir, "Cancelled before start")
        except BuildCancelled:
            raise
        except Exception:
            pass

    preferred_source_by_song_id = preferred_source_by_song_id or {}
    if opts.target_version < 1:
        raise MergeError("target_version must be >=1")
    if opts.mode not in {"update-required", "self-contained"}:
        raise MergeError("mode must be update-required or self-contained")
    # Safe build folder strategy (v0.5.7c): build into a temporary folder, then rename on success.
    final_out_dir = out_dir
    tmp_out_dir = final_out_dir.parent / f"{final_out_dir.name}._BUILDING_tmp"
    backup_dir: Optional[Path] = None
    if final_out_dir.exists():
        if not allow_overwrite:
            raise MergeError(f"Output already exists: {final_out_dir}")

        # Guardrails: do NOT allow overwriting obvious unsafe targets.
        # 1) Output must not match any selected inputs (base/donor).
        _overwrite_input_paths_guard(base_ri=base_ri, source_ris=source_ris, out_dir=final_out_dir)

        # 2) Output should look like a prior SSPCDB output (or be empty).
        ok, reason = _looks_like_spcdb_output_folder(final_out_dir)
        if not ok:
            raise MergeError(
                "Refusing to overwrite existing output because it does not look like an SSPCDB output folder.\n"
                f"Folder: {final_out_dir}\n"
                f"Reason: {reason}\n\n"
                "Choose a dedicated empty output folder, or delete/rename the existing folder first.\n"
                "If you intended to rebuild an existing SSPCDB output, make sure it contains an Export folder with songs_*_0.xml (and usually config.xml)."
            )
        if progress:
            progress(f"Overwrite guardrail OK: {reason}")

        # Safer overwrite strategy: rename existing output out of the way first.
        # Default behavior keeps a backup folder so the user can recover if needed.
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        if keep_backup:
            backup_dir = final_out_dir.parent / f"{final_out_dir.name}.__BACKUP_{ts}"
            suffix = 2
            while backup_dir.exists():
                backup_dir = final_out_dir.parent / f"{final_out_dir.name}.__BACKUP_{ts}_{suffix}"
                suffix += 1
            if progress:
                progress(f"Output exists; moving existing output to backup: {backup_dir}")
            try:
                _rename_dir_with_retries(final_out_dir, backup_dir)
            except Exception as e:
                raise MergeError(f"Failed to backup existing output folder: {e}")
        else:
            old_dir = final_out_dir.parent / f"{final_out_dir.name}.__OVERWRITTEN_{ts}"
            suffix = 2
            while old_dir.exists():
                old_dir = final_out_dir.parent / f"{final_out_dir.name}.__OVERWRITTEN_{ts}_{suffix}"
                suffix += 1
            if progress:
                progress(f"Output exists; moving existing output aside (no backup): {old_dir}")
            try:
                _rename_dir_with_retries(final_out_dir, old_dir)
            except Exception as e:
                raise MergeError(f"Failed to move existing output folder aside: {e}")
            try:
                shutil.rmtree(old_dir)
            except Exception:
                # Best-effort cleanup only; leaving the renamed folder is safer than deleting.
                pass
    if tmp_out_dir.exists():
        raise MergeError(
            f"Temp build folder already exists: {tmp_out_dir}. "
            "A previous build may have failed; delete it or choose a different output folder."
        )

    out_dir = tmp_out_dir


    def _is_cancel_requested() -> bool:
        if cancel_check is None:
            return False
        try:
            return bool(cancel_check())
        except Exception:
            return False

    def _cancel_out(reason: str) -> None:
        # Best-effort: mark and keep partial output in a predictable folder name.
        actual_dir = out_dir
        try:
            if out_dir.exists():
                try:
                    (out_dir / '__BUILD_CANCELLED__.txt').write_text(
                        f'Build cancelled.\nReason: {reason}\n', encoding='utf-8'
                    )
                except Exception:
                    pass
                cancelled_dir = final_out_dir.parent / f"{final_out_dir.name}.__CANCELLED"
                suffix = 2
                while cancelled_dir.exists():
                    cancelled_dir = final_out_dir.parent / f"{final_out_dir.name}.__CANCELLED_{suffix}"
                    suffix += 1
                try:
                    _rename_dir_with_retries(out_dir, cancelled_dir)
                    actual_dir = cancelled_dir
                except Exception:
                    actual_dir = out_dir
        except Exception:
            actual_dir = out_dir
        raise BuildCancelled(actual_dir, reason)

    def _check_cancel(reason: str) -> None:
        if _is_cancel_requested():
            _cancel_out(reason)

    def _emit_progress(
        phase: str,
        message: str,
        *,
        current: int | None = None,
        total: int | None = None,
        indeterminate: bool = False,
    ) -> None:
        if not progress:
            return
        try:
            payload = {
                "phase": phase,
                "message": message,
                "current": current,
                "total": total,
                "indeterminate": bool(indeterminate),
            }
            progress('@@PROGRESS ' + json.dumps(payload))
        except Exception:
            pass
        # Also emit a human-readable line for the log.
        try:
            if total is not None and current is not None:
                progress(f"[{phase}] {message} ({current}/{total})")
            else:
                progress(f"[{phase}] {message}")
        except Exception:
            pass

    # Preflight: figure out which base song folders we actually need.
    # This avoids copying the full base Export tree and then pruning it, which can look like
    # "more than the selected songs" were copied first.
    keep_base_song_folders: Set[int] = set(selected_song_ids)
    try:
        bmax = _detect_max_bank(base_ri.export_root)
        bbank = _choose_bank(base_ri.export_root, bmax)
        base_songs_tree_for_ids, _base_acts_tree_unused = _parse_songs_and_acts(base_ri.export_root, bbank)
        base_song_ids_for_copy = set((_collect_songs(base_songs_tree_for_ids) or {}).keys())
        overridden_to_other: Set[int] = {sid for sid, lab in (preferred_source_by_song_id or {}).items() if lab != "Base"}
        keep_base_song_folders = set(int(x) for x in (selected_song_ids.intersection(base_song_ids_for_copy) or set()))
        keep_base_song_folders.difference_update(overridden_to_other)
    except Exception:
        # Fall back to copying selected ids only; pruning later will still enforce correctness.
        keep_base_song_folders = set(int(x) for x in (selected_song_ids or set()))

    _emit_progress('Copy', f'Copying base disc folder (selected songs only) -> {out_dir} (temp; will finalize to {final_out_dir.name})', indeterminate=True)

    copy_root, rel_export = _compute_copy_root_and_rel_export(base_ri)

    keep_song_folders_for_initial_copy: Set[int] = set(int(x) for x in (keep_base_song_folders or set()))
    use_hardlinks = False

    # Fast update: if we're overwriting an existing output (now moved to backup), seed from that backup
    # so we can keep already-copied donor songs and avoid re-copying huge trees.
    if bool(fast_update_existing_output) and backup_dir is not None:
        try:
            backup_export = _find_export_root_from_disc_root(backup_dir)
            copy_root = backup_dir
            rel_export = backup_export.relative_to(copy_root)
            keep_song_folders_for_initial_copy = set(int(x) for x in (selected_song_ids or set()))
            use_hardlinks = True
            _emit_progress(
                'Copy',
                f'Fast update: seeding from previous output backup -> {out_dir} (temp; will finalize to {final_out_dir.name})',
                indeterminate=True,
            )
        except Exception:
            # Fall back to normal base copy.
            use_hardlinks = False

    # copy_root should be the disc root when possible (contains PS3_GAME and PS3_DISC.SFB)
    export_abs = copy_root / rel_export
    try:
        export_norm = os.path.normcase(os.path.abspath(str(export_abs)))
    except Exception:
        export_norm = str(export_abs)

    def _ignore_pkd(dirpath: str, names: list[str]) -> set[str]:
        ignored: set[str] = set()
        for n in names:
            nl = n.lower()
            # ignore raw package files and extractor outputs
            if nl.startswith('pack') and nl.endswith('.pkd'):
                ignored.add(n)
            if '.pkd_out' in nl:
                ignored.add(n)

        # Only copy selected song folders from the base Export root.
        try:
            dir_norm = os.path.normcase(os.path.abspath(str(dirpath)))
        except Exception:
            dir_norm = str(dirpath)
        if dir_norm == export_norm:
            for n in names:
                if n.isdigit():
                    try:
                        sid = int(n)
                    except Exception:
                        continue
                    if sid not in keep_song_folders_for_initial_copy:
                        ignored.add(n)
        return ignored

    _copytree_maybe_hardlink(copy_root, out_dir, ignore=_ignore_pkd, use_hardlinks=use_hardlinks)

    _check_cancel('Cancelled after base copy')

    # Resolve output Export folder by mirroring the relative export path from the chosen copy root.
    out_export = out_dir / rel_export
    if not out_export.exists() or not out_export.is_dir():
        raise MergeError(
            f"Output Export folder not found after copying base. Expected: {out_export}. "
            "Check that the selected Base disc folder is the extracted disc root (contains PS3_GAME)."
        )
    if not out_export.is_dir():
        raise MergeError(f"Output Export root missing after copy: {out_export}")

    out_textures = _ensure_lowercase_textures(out_export)
    page_pairs = _list_texture_pages(out_textures)
    current_max_page = _max_page_index(page_pairs)

    # Determine base bank (usually 6)
    base_max = _detect_max_bank(base_ri.export_root)
    base_bank = _choose_bank(base_ri.export_root, base_max)

    # Parse base XML
    base_songs_tree, base_acts_tree = _parse_songs_and_acts(base_ri.export_root, base_bank)
    base_songlists_tree = _parse_songlists(base_ri.export_root, base_bank)
    base_covers_tree = _parse_covers(base_ri.export_root)
    base_config_tree = _read_xml(base_ri.export_root / "config.xml")

    base_songs = _collect_songs(base_songs_tree)
    base_song_ids = set(base_songs.keys())

    # Start from selected songs that exist in base
    # Start from selected songs that exist in base, but exclude any explicitly overridden to a non-base source.
    overridden_to_other: Set[int] = {sid for sid, lab in preferred_source_by_song_id.items() if lab != "Base"}
    merged_song_ids: Set[int] = set(sorted(selected_song_ids.intersection(base_song_ids)))
    merged_song_ids.difference_update(overridden_to_other)

    merged_songs: Dict[int, ET.Element] = {sid: base_songs[sid] for sid in merged_song_ids}

    base_covers_bits = _collect_covers(base_covers_tree)
    merged_covers_bits: Dict[int, ET.Element] = {}
    for sid in merged_song_ids:
        if sid in base_covers_bits:
            merged_covers_bits[sid] = base_covers_bits[sid]

    donor_songlists_trees: List[ET.ElementTree] = []

    # Act merging setup (same logic as merge_build)
    base_act_map_old = _build_act_map(base_acts_tree.getroot())
    act_key_to_newid: Dict[str, int] = {}
    newid_to_actnode: Dict[int, ET.Element] = {}

    for old_id, (name, name_key) in base_act_map_old.items():
        key = _normalize_key(name_key or name)
        if not key:
            continue
        if key in act_key_to_newid:
            continue
        act_key_to_newid[key] = old_id
        act_node = None
        for a in base_acts_tree.getroot().findall(f".//{_ns_tag('ACT')}"):
            if _parse_int_attr(a, "ID") == old_id:
                act_node = ET.fromstring(ET.tostring(a, encoding="utf-8"))
                break
        if act_node is not None:
            newid_to_actnode[old_id] = act_node

    def _next_act_id() -> int:
        return (max(newid_to_actnode.keys()) + 1) if newid_to_actnode else 1

    def _remap_song_acts(song_el: ET.Element, act_old_to_key: Dict[int, str]) -> None:
        pb = song_el.find(f"./{_ns_tag('PERFORMED_BY')}")
        if pb is not None:
            old = _parse_int_attr(pb, "ID")
            if old is not None:
                key = act_old_to_key.get(old)
                new = act_key_to_newid.get(key) if key else None
                if new is not None:
                    pb.attrib["ID"] = str(new)
        for act in song_el.findall(f".//{_ns_tag('ACT')}"):
            old = _parse_int_attr(act, "ID")
            if old is None:
                continue
            key = act_old_to_key.get(old)
            if key:
                new = act_key_to_newid.get(key)
                if new is not None:
                    act.attrib["ID"] = str(new)

    # Prune base song folders we definitely don't want before copying donor folders
    _emit_progress('Prune', 'Deleting unselected song folders...', indeterminate=True)
    _delete_unselected_song_folders(out_export, selected_song_ids, progress=progress)

    _check_cancel('Cancelled after prune')


    present_song_ids: Set[int] = set()
    if bool(fast_update_existing_output):
        try:
            for p in out_export.iterdir():
                if p.is_dir() and p.name.isdigit():
                    present_song_ids.add(int(p.name))
        except Exception:
            present_song_ids = set()


    # Fast-update can seed from an existing output backup. That backup may not contain newly-selected
    # base songs, so make sure any missing base song folders are restored from the base disc export.
    if bool(fast_update_existing_output):
        try:
            missing_base = sorted(set(base_song_ids).intersection(selected_song_ids) - present_song_ids)
        except Exception:
            missing_base = []
        if missing_base:
            _emit_progress('Copy', f'Fast update: restoring {len(missing_base)} missing base song folder(s)...', indeterminate=True)
            for sid in missing_base:
                _check_cancel('Cancelled during base song restore')
                src = base_ri.export_root / str(sid)
                dst = out_export / str(sid)
                if dst.is_dir():
                    continue
                if not src.is_dir():
                    raise MergeError(f"Base disc missing selected song folder: {src}")
                _copytree_maybe_hardlink(src, dst, use_hardlinks=True)
            try:
                for sid in missing_base:
                    present_song_ids.add(int(sid))
            except Exception:
                pass

    # Precompute a project-wide total for "Copy songs" so ETA does not reset per source disc.
    planned_copy_songs_by_source: Dict[str, List[int]] = {}
    copy_songs_total_overall = 0
    copy_songs_done_overall = 0

    # Build a lightweight plan of which selected songs will be copied from which donor source.
    # This mirrors the selection routing and duplicate detection logic in the donor loop below.
    explicit_assigned: Set[int] = set(preferred_source_by_song_id.keys())
    planned_present: Set[int] = set(merged_song_ids)
    fp_source_by_sid: Dict[int, Path] = {sid: base_ri.export_root for sid in merged_song_ids}
    if present_song_ids:
        planned_present.update(present_song_ids)
        for sid in present_song_ids:
            fp_source_by_sid.setdefault(sid, out_export)

    for src_label, sri in source_ris:
        # Determine bank for this source
        dmax = _detect_max_bank(sri.export_root)
        dbank = _choose_bank(sri.export_root, dmax)

        donor_songs_tree_tmp, _donor_acts_tree_tmp = _parse_songs_and_acts(sri.export_root, dbank)
        donor_songs_tmp = _collect_songs(donor_songs_tree_tmp)
        donor_song_ids_all_tmp = set(donor_songs_tmp.keys())

        desired_from_this_source: Set[int] = {
            sid for sid, lab in preferred_source_by_song_id.items() if lab == src_label and sid in selected_song_ids
        }

        implicit_needed: Set[int] = set(sorted(donor_song_ids_all_tmp.intersection(selected_song_ids)))
        # Only pull implicitly if it doesn't exist in base (since base was copied) and isn't explicitly assigned elsewhere.
        implicit_needed.difference_update(base_song_ids)
        implicit_needed.difference_update(explicit_assigned)

        donor_song_ids_tmp: Set[int] = set(sorted(desired_from_this_source.union(implicit_needed)))

        if present_song_ids:
            donor_song_ids_tmp = {
                sid for sid in donor_song_ids_tmp
                if (sid not in present_song_ids) or (preferred_source_by_song_id.get(sid) == src_label)
            }

        # Duplicate detection (restricted to selection)
        if donor_song_ids_tmp:
            dups = planned_present.intersection(donor_song_ids_tmp)
            if dups:
                nonidentical: List[int] = []
                for sid in sorted(dups):
                    src_root = fp_source_by_sid.get(sid, base_ri.export_root)
                    b_fp = melody_fingerprint_file(Path(src_root) / str(sid) / "melody_1.xml")
                    d_fp = melody_fingerprint_file(sri.export_root / str(sid) / "melody_1.xml")
                    if b_fp and d_fp and b_fp == d_fp:
                        donor_song_ids_tmp.discard(sid)
                    else:
                        nonidentical.append(sid)
                if nonidentical:
                    raise MergeError(
                        "Selected song IDs have non-identical duplicates (melody fingerprint differs) across sources: "
                        f"{nonidentical[:50]}. Use conflict resolution to choose the preferred source per song."
                    )

        donor_list_tmp = sorted(donor_song_ids_tmp)
        if donor_list_tmp:
            planned_copy_songs_by_source[src_label] = donor_list_tmp
            copy_songs_total_overall += len(donor_list_tmp)
            planned_present.update(donor_list_tmp)
            for sid in donor_list_tmp:
                fp_source_by_sid[sid] = sri.export_root

    # For each additional source disc, pull selected songs not already present
    for src_label, sri in source_ris:
        # Determine bank for this source
        dmax = _detect_max_bank(sri.export_root)
        dbank = _choose_bank(sri.export_root, dmax)

        donor_songs_tree, donor_acts_tree = _parse_songs_and_acts(sri.export_root, dbank)
        donor_songlists_tree = _parse_songlists(sri.export_root, dbank)
        donor_covers_tree = _parse_covers(sri.export_root)
        donor_songlists_trees.append(donor_songlists_tree)

        donor_songs = _collect_songs(donor_songs_tree)
        donor_song_ids_all = set(donor_songs.keys())

        # Selection routing:
        # - If a song_id is explicitly assigned via preferred_source_by_song_id, import it ONLY from that source.
        # - Otherwise, if it is missing from base/merged, import it from the first source that contains it.
        explicit_assigned: Set[int] = set(preferred_source_by_song_id.keys())
        desired_from_this_source: Set[int] = {sid for sid, lab in preferred_source_by_song_id.items() if lab == src_label and sid in selected_song_ids}

        implicit_needed: Set[int] = set(sorted(donor_song_ids_all.intersection(selected_song_ids)))
        # Only pull implicitly if it doesn't exist in base (since base was copied) and isn't explicitly assigned elsewhere.
        implicit_needed.difference_update(base_song_ids)
        implicit_needed.difference_update(explicit_assigned)

        donor_song_ids: Set[int] = set(sorted(desired_from_this_source.union(implicit_needed)))

        if present_song_ids:
            donor_song_ids = {
                sid for sid in donor_song_ids
                if (sid not in present_song_ids) or (preferred_source_by_song_id.get(sid) == src_label)
            }

        planned_list = planned_copy_songs_by_source.get(src_label)
        if planned_list is not None:
            donor_song_ids = set(planned_list)

        if present_song_ids:
            donor_song_ids = {
                sid for sid in donor_song_ids
                if (sid not in present_song_ids) or (preferred_source_by_song_id.get(sid) == src_label)
            }

        if not donor_song_ids:
            continue

        # Duplicate detection (restricted to selection)
        if planned_list is None:
            dups = merged_song_ids.intersection(donor_song_ids)
            identical_dups: Set[int] = set()
            if dups:
                nonidentical: List[int] = []
                for sid in sorted(dups):
                    b_fp = melody_fingerprint_file(out_export / str(sid) / "melody_1.xml")
                    d_fp = melody_fingerprint_file(sri.export_root / str(sid) / "melody_1.xml")
                    if b_fp and d_fp and b_fp == d_fp:
                        identical_dups.add(sid)
                    else:
                        nonidentical.append(sid)
                if nonidentical:
                    raise MergeError(f"Selected song IDs have non-identical duplicates (melody fingerprint differs) across sources: {nonidentical[:50]}. Use conflict resolution to choose the preferred source per song.")
                # keep existing copy (base or earlier donor)
                for sid in identical_dups:
                    donor_song_ids.discard(sid)
                    donor_songs.pop(sid, None)

        if not donor_song_ids:
            continue

        _emit_progress('Import', f'Importing {len(donor_song_ids)} selected songs from {src_label}', indeterminate=True)

        # Copy required song folders
        donor_list = sorted(donor_song_ids)
        total_songs = len(donor_list)
        
        def _song_tick(i: int) -> None:
            # update about every 10 songs (or each song for small batches)
            if total_songs <= 40 or i == 1 or i == total_songs or (i % 10) == 0:
                if copy_songs_total_overall > 0:
                    overall_i = copy_songs_done_overall + i
                    _emit_progress(
                        'Copy songs',
                        f'{src_label}: copying song folders ({i}/{total_songs} disc, {overall_i}/{copy_songs_total_overall} overall)',
                        current=overall_i,
                        total=copy_songs_total_overall,
                    )
                else:
                    _emit_progress('Copy songs', f'{src_label}: copying song folders', current=i, total=total_songs)

        for i, sid in enumerate(donor_list, start=1):
            _song_tick(i)
            _check_cancel('Cancelled during song folder copy')
            dst = out_export / str(sid)
            if dst.exists():
                # If explicitly assigned to this donor, replace the base copy.
                if preferred_source_by_song_id.get(sid) == src_label:
                    try:
                        shutil.rmtree(dst)
                    except Exception as e:
                        raise MergeError(f"Failed to remove existing song folder for override {sid}: {e}") from e
                else:
                    raise MergeError(f"Output already contains song folder {sid} unexpectedly.")
            _copytree_maybe_hardlink(sri.export_root / str(sid), dst, use_hardlinks=bool(fast_update_existing_output))

        copy_songs_done_overall += total_songs

        # Merge covers + textures
        donor_bits_all = _collect_covers(donor_covers_tree)
        donor_textures = sri.export_root / "textures"
        if not donor_textures.is_dir():
            raise MergeError(f"Donor textures folder missing (must be Export/textures): {donor_textures}")

        # Copy ONLY the texture pages required for the selected songs from this donor.
        needed_pages: Set[int] = set()
        for sid in sorted(donor_song_ids):
            bit0 = donor_bits_all.get(sid)
            if bit0 is None:
                raise MergeError(f"Missing covers.xml entry for selected song {sid} in donor {sri.original}")
            page0 = _extract_cover_page_num(bit0)
            if page0 is None:
                raise MergeError(f"Unrecognized cover TEXTURE for song {sid}: {bit0.attrib.get('TEXTURE')}")
            needed_pages.add(int(page0))

        _emit_progress('Textures', f"{src_label}: copying {len(needed_pages)} texture page(s) for selected songs (renumbering pages)...", indeterminate=True)
        offset = current_max_page + 1
        try:
            copied, page_map = _copy_selected_texture_pages_with_renumber(
                donor_textures, out_textures, pages=needed_pages, page_offset=offset, cancel_check=cancel_check
            )
        except CancelRequested:
            _cancel_out('Cancelled during textures copy')
        # update max precisely
        current_max_page = max(current_max_page, _max_page_index(_list_texture_pages(out_textures)))

        for sid in sorted(donor_song_ids):
            _check_cancel('Cancelled during covers merge')
            bit = donor_bits_all.get(sid)
            if bit is None:
                raise MergeError(f"Missing covers.xml entry for selected song {sid} in donor {sri.original}")
            if sid in merged_covers_bits:
                raise MergeError(f"Duplicate cover entry for selected song {sid}")
            page = _extract_cover_page_num(bit)
            if page is None:
                raise MergeError(f"Unrecognized cover TEXTURE for song {sid}: {bit.attrib.get('TEXTURE')}")
            if page not in page_map:
                raise MergeError(f"Cover references texture page_{page} but it was not found in donor textures folder")
            new_page = page_map[page]
            _rewrite_cover_page(bit, new_page)
            merged_covers_bits[sid] = bit

        # Merge acts: build mapping old_id -> canonical key from donor acts
        donor_act_map_old = _build_act_map(donor_acts_tree.getroot())
        donor_old_to_key: Dict[int, str] = {}
        for old_id, (name, name_key) in donor_act_map_old.items():
            key = _normalize_key(name_key or name)
            donor_old_to_key[old_id] = key
            if not key:
                continue
            if key in act_key_to_newid:
                continue
            new_id = _next_act_id()
            act_key_to_newid[key] = new_id
            act_node = None
            for a in donor_acts_tree.getroot().findall(f".//{_ns_tag('ACT')}"):
                if _parse_int_attr(a, "ID") == old_id:
                    act_node = ET.fromstring(ET.tostring(a, encoding="utf-8"))
                    break
            if act_node is None:
                act_node = ET.Element(_ns_tag("ACT"), {"ID": str(new_id)})
                ET.SubElement(act_node, _ns_tag("NAME")).text = name
                ET.SubElement(act_node, _ns_tag("NAME_KEY")).text = name_key or _normalize_key(name)
            act_node.attrib["ID"] = str(new_id)
            newid_to_actnode[new_id] = act_node

        # Remap acts in imported songs and add them
        for sid in sorted(donor_song_ids):
            song_node = donor_songs.get(sid)
            if song_node is None:
                raise MergeError(f"Internal: donor song node missing for {sid}")
            _remap_song_acts(song_node, donor_old_to_key)
            merged_songs[sid] = song_node
            merged_song_ids.add(sid)

    # Ensure base songlists included as well for union mode
    donor_songlists_trees = [t for t in donor_songlists_trees if t is not None]
    # Build merged songs XML by editing base root in-place (preserves non-SONG nodes)
    songs_root = base_songs_tree.getroot()
    for child in list(songs_root):
        if _strip_ns(child.tag) == "SONG":
            songs_root.remove(child)
    for sid in sorted(merged_songs.keys()):
        songs_root.append(merged_songs[sid])

    # Build merged acts XML
    acts_root = base_acts_tree.getroot()
    for child in list(acts_root):
        if _strip_ns(child.tag) == "ACT":
            acts_root.remove(child)
    for aid in sorted(newid_to_actnode.keys()):
        acts_root.append(newid_to_actnode[aid])

    # Build merged covers XML tree
    covers_root = base_covers_tree.getroot()
    for child in list(covers_root):
        if _strip_ns(child.tag) == "TPAGE_BIT":
            covers_root.remove(child)
    for sid in sorted(merged_covers_bits.keys()):
        covers_root.append(merged_covers_bits[sid])

    # Merge songlists
    if opts.songlist_mode == "union-by-name":
        songlists_tree = _merge_songlists_union_by_name(base_songlists_tree, donor_songlists_trees, merged_song_ids)
    else:
        songlists_tree = base_songlists_tree

    missing_covers = sorted(list(merged_song_ids - set(merged_covers_bits.keys())))
    if missing_covers:
        raise MergeError(f"Missing covers.xml entries for {len(missing_covers)} selected songs (sample: {missing_covers[:30]})")

    _check_cancel('Cancelled before XML write')

    _emit_progress('Write', 'Writing songs/acts/songlists XML...', indeterminate=True)
    # Write replicated bank files
    for bank in range(1, opts.target_version + 1):
        _check_cancel('Cancelled during XML write')
        _write_xml(ET.ElementTree(songs_root), out_export / f"songs_{bank}_0.xml")
        _write_xml(ET.ElementTree(acts_root), out_export / f"acts_{bank}_0.xml")
        _write_xml(songlists_tree, out_export / f"songlists_{bank}.xml")

    # Write covers (single file)
    _write_xml(ET.ElementTree(covers_root), out_export / "covers.xml")

    _emit_progress('Melody', f'Ensuring melody_{opts.target_version}.xml for selected songs...', indeterminate=True)
    # Ensure melody_<version>.xml exists for all selected songs
    try:
        _ensure_versioned_melody_files(out_export, merged_song_ids, opts.target_version, cancel_check=cancel_check)
    except CancelRequested:
        _cancel_out('Cancelled during melody synthesis')

    _emit_progress('CHC', 'Rebuilding melodies_*.chc...', indeterminate=True)
    try:
        chc_bytes = _rebuild_chc(
            sorted(list(merged_song_ids)), out_export, melody_version=opts.target_version, cancel_check=cancel_check
        )
    except CancelRequested:
        _cancel_out('Cancelled during CHC rebuild')
    _emit_progress('CHC', 'Validating melodies_*.chc...', indeterminate=True)
    _validate_chc(chc_bytes, set(merged_song_ids), out_export, melody_version=opts.target_version)
    for bank in range(1, opts.target_version + 1):
        (out_export / f"melodies_{bank}.chc").write_bytes(chc_bytes)

    _check_cancel('Cancelled before config write')

    _emit_progress('Config', f'Writing config.xml (target v{opts.target_version}, mode {opts.mode})...', indeterminate=True)
    config_tree = _build_config(base_config_tree, opts.target_version, opts.mode)
    _write_xml(config_tree, out_export / "config.xml")

    # Final validation: referenced pages exist
    referenced_pages: Set[int] = set()
    for bit in covers_root.findall(f".//{_ns_tag('TPAGE_BIT')}"):
        page = _extract_cover_page_num(bit)
        if page is not None:
            referenced_pages.add(page)
    for p in referenced_pages:
        ok = False
        for ext in ("jpg", "png", "gtf", "dds", "bmp"):
            if (out_textures / f"page_{p}.{ext}").exists():
                ok = True
                break
        if not ok:
            raise MergeError(f"covers.xml references page_{p} but no corresponding file exists in Export/textures")
    _check_cancel('Cancelled before finalize')

    _emit_progress('Finalize', f'Renaming temp output -> {final_out_dir}', indeterminate=True)
    try:
        _rename_dir_with_retries(out_dir, final_out_dir)
    except Exception as e:
        raise MergeError(
            f"Build finished writing, but failed to rename temp output folder: {e}. Temp output remains at {out_dir}"
        )

    _emit_progress('Done', f'Build complete: {len(merged_song_ids)} songs -> {final_out_dir}', indeterminate=False, current=len(merged_song_ids), total=len(merged_song_ids))
