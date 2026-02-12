from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from ..controller import CancelToken


def _scan_for_disc_inputs(
    root: Path,
    max_depth: int = 4,
    *,
    log=None,
    cancel: Optional[CancelToken] = None,
) -> list[str]:
    """Find candidate disc folders beneath root.

    Qt version: keep this UI-agnostic and lightweight.
    We detect both extracted and unextracted discs by finding PS3_GAME/USRDIR and
    then looking for either FileSystem/Export (extracted) or pack*.pkd (unextracted).
    """
    root = root.expanduser().resolve()
    out: list[str] = []
    seen: set[str] = set()

    def _emit(msg: str) -> None:
        try:
            if log is not None:
                log(str(msg))
        except Exception:
            pass

    def _normalize_disc_root(p: Path) -> Path:
        if p.name.upper() == 'PS3_GAME' and p.parent.exists():
            return p.parent
        for parent in [p] + list(p.parents):
            if parent.name.upper() == 'PS3_GAME':
                return parent.parent
        return p

    def _looks_like_usrdir(usr: Path) -> bool:
        try:
            if (usr / 'FileSystem' / 'Export').is_dir() or (usr / 'filesystem' / 'export').is_dir():
                return True
            for pat in ('pack*.pkd', 'pack*.PKD', '*.pkd', '*.PKD'):
                try:
                    if any(usr.glob(pat)):
                        return True
                except Exception:
                    continue
        except Exception:
            return False
        return False

    def _add_candidate(p: Path) -> bool:
        disc_root = _normalize_disc_root(p)
        usrdir = disc_root / 'PS3_GAME' / 'USRDIR'
        if usrdir.is_dir() and _looks_like_usrdir(usrdir):
            try:
                key = str(disc_root.resolve())
            except Exception:
                key = str(disc_root)
            if key in seen:
                return True
            seen.add(key)
            out.append(str(disc_root))
            return True

        # Looser extracted layouts (direct Export folder)
        try:
            ex = Path(p) / 'Export'
            if ex.is_dir() and ((ex / 'config.xml').is_file() or (ex / 'covers.xml').is_file()):
                try:
                    key = str(Path(p).resolve())
                except Exception:
                    key = str(p)
                if key in seen:
                    return True
                seen.add(key)
                out.append(str(p))
                return True
        except Exception:
            pass
        return False

    # Walk with max_depth to keep it fast.
    for dirpath, dirnames, _filenames in os.walk(root):
        if cancel is not None:
            try:
                cancel.raise_if_cancelled('Cancelled')
            except Exception:
                # CancelledError will be raised by token
                raise

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
                dnl = str(dn).lower()
                # Avoid crawling huge irrelevant trees for speed.
                if dnl in {"_spcdb_trash", ".git", "__pycache__", "export", "filesystem"} or dnl.endswith(".pkd_out"):
                    dirnames.remove(dn)
        except Exception:
            pass

        pth = Path(dirpath)

        # Common PS3 disc roots
        try:
            if (pth / 'PS3_GAME' / 'USRDIR').is_dir():
                if _add_candidate(pth):
                    dirnames[:] = []
                    continue
        except Exception:
            pass

        # Inside PS3_GAME
        try:
            if pth.name.upper() == 'PS3_GAME' and (pth / 'USRDIR').is_dir():
                if _add_candidate(pth.parent):
                    dirnames[:] = []
                    continue
        except Exception:
            pass

        # Inside USRDIR
        try:
            if pth.name.upper() == 'USRDIR':
                if _add_candidate(pth):
                    dirnames[:] = []
                    continue
        except Exception:
            pass

        # Looser extracted layouts
        try:
            ex = pth / 'Export'
            if ex.is_dir() and ((ex / 'config.xml').is_file() or (ex / 'covers.xml').is_file()):
                if _add_candidate(pth):
                    dirnames[:] = []
                    continue
        except Exception:
            pass

    out.sort(key=lambda s: s.lower())
    _emit(f'[scan] Found {len(out)} candidate disc(s) under: {root}')
    return out
