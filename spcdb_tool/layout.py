from __future__ import annotations

import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple


@dataclass(frozen=True)
class ResolvedInput:
    original: Path
    resolved_root: Path
    export_root: Path
    kind: str  # "disc_folder" | "export_folder" | "zip_extracted"
    warnings: list[str]
    temp_dir: Optional[tempfile.TemporaryDirectory] = None  # keep alive if zip


def _candidate_roots(p: Path) -> list[Tuple[str, Path]]:
    # Returns (kind, export_root) candidates ordered by preference.
    cands: list[Tuple[str, Path]] = []

    # Common layouts:
    #  - <disc>/USRDIR/FileSystem/Export
    #  - <disc>/FileSystem/Export
    #  - <disc>/PS3_GAME/USRDIR/FileSystem/Export
    #  - <export_only>/Export  OR <export_only>/ (loose export root)
    for base in [p, p / "PS3_GAME", p / "GAME", p / "BCES00011", p / "BCES00011SINGSTARFAMILY"]:
        cands.append(("disc_folder", base / "USRDIR" / "FileSystem" / "Export"))
        cands.append(("disc_folder", base / "FileSystem" / "Export"))

    cands.append(("export_folder", p / "Export"))
    cands.append(("export_folder", p))

    # De-dupe while preserving order
    seen: set[Path] = set()
    out: list[Tuple[str, Path]] = []
    for kind, ex in cands:
        ex = ex.resolve()
        if ex in seen:
            continue
        seen.add(ex)
        out.append((kind, ex))
    return out


def _looks_like_export_root(export_root: Path) -> bool:
    if not export_root.exists() or not export_root.is_dir():
        return False
    # minimum signal: config.xml, or songs_*.xml/covers.xml
    if (export_root / "config.xml").is_file():
        return True
    if (export_root / "covers.xml").is_file():
        return True
    for pat in ["songs_*_0.xml", "songs_*.xml", "acts_*_0.xml", "songlists_*.xml", "melodies_*.chc"]:
        if list(export_root.glob(pat)):
            return True
    return False


def resolve_input(path: str) -> ResolvedInput:
    p = Path(path).expanduser()

    if p.is_file() and p.suffix.lower() == ".zip":
        # Extract to temp and resolve as folder input
        td = tempfile.TemporaryDirectory(prefix="spcdb_zip_")
        with zipfile.ZipFile(p) as z:
            z.extractall(td.name)
        extracted_root = Path(td.name)
        # Prefer if zip has a single top-level folder
        kids = [k for k in extracted_root.iterdir() if k.name not in {"__MACOSX"}]
        if len(kids) == 1 and kids[0].is_dir():
            extracted_root = kids[0]
        ri = resolve_input(str(extracted_root))
        # override
        return ResolvedInput(
            original=p,
            resolved_root=ri.resolved_root,
            export_root=ri.export_root,
            kind="zip_extracted",
            warnings=ri.warnings + ["Input was a .zip; extracted to a temporary folder for inspection."],
            temp_dir=td,
        )

    # Folder input
    if not p.exists():
        raise FileNotFoundError(f"Input does not exist: {p}")

    # find best candidate export root
    for kind, export_root in _candidate_roots(p):
        if _looks_like_export_root(export_root):
            # resolved_root should be the folder that contains FileSystem (or Export-only)
            if kind == "disc_folder":
                # back up to a root containing USRDIR or FileSystem
                resolved_root = export_root.parent.parent  # .../(USRDIR)/FileSystem
                return ResolvedInput(
                    original=p,
                    resolved_root=resolved_root,
                    export_root=export_root,
                    kind="disc_folder",
                    warnings=_layout_warnings(export_root),
                )
            return ResolvedInput(
                original=p,
                resolved_root=export_root,
                export_root=export_root,
                kind="export_folder",
                warnings=_layout_warnings(export_root),
            )

    raise FileNotFoundError(
        f"Could not locate an Export root with config.xml/songs/covers under: {p}"
    )




def _case_mismatch_child(parent: Path, expected: str) -> str | None:
    """Return the actual child name if a case-insensitive match exists but casing differs.

    This helps detect PS3 casing hazards even on case-insensitive filesystems (e.g., Windows).
    """
    try:
        exp_l = expected.lower()
        for c in parent.iterdir():
            try:
                name = c.name
            except Exception:
                continue
            if name.lower() == exp_l and name != expected:
                return name
    except Exception:
        return None
    return None


def _layout_warnings(export_root: Path) -> list[str]:
    w: list[str] = []

    # casing expectations
    # Export folder casing:
    # Only warn when this really is a FileSystem/Export folder (PS3 layout). For loose export sets, any folder name is fine.
    if export_root.parent.name == "FileSystem" and export_root.name != "Export":
        w.append(f"Export folder name is '{export_root.name}' (expected 'Export').")

    # textures inside export
    # Detect casing hazards even on case-insensitive filesystems (Windows) by scanning
    # actual directory entries.
    mismatch = _case_mismatch_child(export_root, "textures")
    if mismatch is not None:
        w.append("Found '%s' folder; on PS3 hardware this should be lowercase 'textures' inside Export." % mismatch)
    else:
        textures = export_root / "textures"
        if textures.exists():
            if textures.name != "textures":
                w.append("Textures folder casing looks wrong (expected 'textures').")
        else:
            # might exist as 'Textures' or other
            alt = export_root / "Textures"
            if alt.exists():
                w.append("Found 'Textures' folder; on PS3 hardware this should be lowercase 'textures' inside Export.")
            else:
                w.append("No textures folder found under Export (ok for loose XML-only sets, but required for real discs/output).")

    # quick check for config paths style
    cfg = export_root / "config.xml"
    if cfg.exists():
        # ok
        pass
    else:
        w.append("No config.xml found at Export root (some donors may be partial).")

    return w
