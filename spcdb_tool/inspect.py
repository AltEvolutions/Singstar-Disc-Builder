from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Set

from .util import is_probably_numeric_dir, relpath_posix


NS = {"ss": "http://www.singstargame.com"}  # config uses default ns; we match via this prefix
VERSION_RE = re.compile(r"^songs_(\d+)_0\.xml$")


@dataclass
class VersionRefs:
    version: int
    song_list: Optional[str]
    act_list: Optional[str]
    songlists: Optional[str]
    melody_cache: Optional[str]


@dataclass
class InspectReport:
    input_path: str
    kind: str
    resolved_root: str
    export_root: str
    product_code: Optional[str]
    product_desc: Optional[str]
    versions_in_config: list[int]
    max_version_in_config: Optional[int]
    referenced_files: dict[str, list[str]]  # keys: "all", "max"
    existence: dict[str, dict[str, bool]]  # relpath -> exists
    counts: dict[str, int]
    warnings: list[str]


def _parse_xml(path: Path) -> ET.Element:
    txt = path.read_bytes()
    try:
        return ET.fromstring(txt)
    except ET.ParseError as e:
        raise ValueError(f"XML parse failed for {path}: {e}") from e



def _check_retail_xml_style(path: Path, warnings: list[str], *, check_run_on_subset: bool = False) -> None:
    """Warn on common XML formatting drift that can affect brittle parsers."""
    try:
        data = path.read_bytes()
    except Exception:
        return

    name = path.name

    # 1) Line endings
    if b"\r" in data:
        warnings.append(f"{name}: contains CR characters (expected LF-only).")

    # 2) Namespace declaration drift
    if b"xmlns:ss=\"http://www.singstargame.com\"" not in data:
        warnings.append(f"{name}: missing xmlns:ss declaration (retail exports often include it).")

    # 3) Self-closing tag style drift
    if b" />" in data:
        warnings.append(f"{name}: contains ' />' self-closing style (retail typically uses '/>').")

    # 4) Run-on subset tags (songlists)
    if check_run_on_subset:
        n = data.count(b"</SUBSET><SUBSET")
        if n:
            warnings.append(f"{name}: contains {n} run-on '</SUBSET><SUBSET' occurrences (expected 0).")

def _find_text(el: ET.Element, xpath: str) -> Optional[str]:
    found = el.find(xpath, namespaces=NS)
    if found is None or found.text is None:
        return None
    return found.text.strip()


def _strip_ns(tag: str) -> str:
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _config_versions(root: ET.Element) -> list[ET.Element]:
    # config uses default ns; ElementTree stores full {ns}TAG names.
    out = []
    for child in list(root):
        if _strip_ns(child.tag) == "VERSION":
            out.append(child)
    return out


def _collect_version_refs(v_el: ET.Element) -> VersionRefs:
    ver_attr = v_el.attrib.get("version")
    if ver_attr is None:
        raise ValueError("VERSION element missing 'version' attribute.")
    v = int(ver_attr)

    song_list = _find_text(v_el, ".//ss:SONGS/ss:SONG_LIST")
    act_list = _find_text(v_el, ".//ss:SONGS/ss:ACT_LIST")
    songlists = _find_text(v_el, ".//ss:SONG_LISTS/ss:FILE")
    melody_cache = _find_text(v_el, ".//ss:MELODY_CACHE/ss:FILE")

    return VersionRefs(version=v, song_list=song_list, act_list=act_list, songlists=songlists, melody_cache=melody_cache)


def _collect_common_refs(cfg_root: ET.Element) -> list[str]:
    refs: list[str] = []
    # covers
    covers_list = _find_text(cfg_root, ".//ss:COVERS/ss:LIST")
    if covers_list:
        refs.append(covers_list)

    # optional files
    for xp in [
        ".//ss:GAME_CREDITS/ss:FILE",
        ".//ss:FILTERS/ss:FILE",
    ]:
        t = _find_text(cfg_root, xp)
        if t:
            refs.append(t)

    # errata refs
    for err in cfg_root.findall(".//ss:ERRATA/ss:FILE", namespaces=NS):
        if err.text:
            refs.append(err.text.strip())

    return refs


def _resolve_ref_to_paths(export_root: Path, ref: str) -> list[Path]:
    # Config often stores "FileSystem/Export/<file>" even when we're inspecting a loose export folder.
    # Try a few interpretations:
    #  1) treat as relative to resolved_root parent of FileSystem (i.e. .../USRDIR or .../ ??) -> can't easily from export_root
    #  2) if it starts with "FileSystem/Export/" or "/FileSystem/Export/", strip and resolve under export_root
    #  3) if it starts with "Export/", strip and resolve under export_root
    #  4) treat as relative to export_root.parent.parent (FileSystem) (for disc_folder kind)

    ref_norm = relpath_posix(ref).lstrip("/")
    paths: list[Path] = []

    # a) disc-like: relative to the folder that contains FileSystem
    # export_root is .../FileSystem/Export
    filesystem_root = export_root.parent  # .../FileSystem
    discish = filesystem_root.parent  # maybe .../USRDIR or the disc root
    paths.append(discish / ref_norm)

    # b) strip common prefixes
    for prefix in ["FileSystem/Export/", "Export/"]:
        if ref_norm.startswith(prefix):
            paths.append(export_root / ref_norm[len(prefix):])

    # c) if ref is just a filename, try export_root directly
    if "/" not in ref_norm:
        paths.append(export_root / ref_norm)

    # d) if ref includes FileSystem/ at front, try under filesystem_root
    if ref_norm.startswith("FileSystem/"):
        paths.append(discish / ref_norm)

    # de-dupe while preserving order
    out: list[Path] = []
    seen: set[Path] = set()
    for p in paths:
        p = p.resolve()
        if p in seen:
            continue
        seen.add(p)
        out.append(p)
    return out


def _exists_any(paths: list[Path]) -> bool:
    return any(p.exists() for p in paths)


def inspect_export(export_root: Path, kind: str, input_path: str, warnings: list[str]) -> InspectReport:
    cfg_path = export_root / "config.xml"
    if not cfg_path.exists():
        raise FileNotFoundError(f"config.xml not found at Export root: {cfg_path}")

    _check_retail_xml_style(cfg_path, warnings)
    cfg_root = _parse_xml(cfg_path)

    product_code = _find_text(cfg_root, ".//ss:PRODUCT_CODE")
    product_desc = _find_text(cfg_root, ".//ss:PRODUCT_DESC")

    version_els = _config_versions(cfg_root)
    version_refs: list[VersionRefs] = [_collect_version_refs(v) for v in version_els]
    versions = sorted({v.version for v in version_refs})
    max_v = max(versions) if versions else None

    common_refs = _collect_common_refs(cfg_root)
    all_refs: list[str] = []
    max_refs: list[str] = []

    for vr in version_refs:
        for r in [vr.song_list, vr.act_list, vr.songlists, vr.melody_cache]:
            if r:
                all_refs.append(r)
                if max_v is not None and vr.version == max_v:
                    max_refs.append(r)

    # covers+credits+filters+errata are common (not bank-specific)
    all_refs.extend(common_refs)
    max_refs.extend(common_refs)

    # existence checks
    existence_all: dict[str, bool] = {}
    for ref in sorted(set(all_refs)):
        candidates = _resolve_ref_to_paths(export_root, ref)
        existence_all[ref] = _exists_any(candidates)

    # counts / extra scanning
    numeric_dirs = 0
    try:
        for p in export_root.iterdir():
            if p.is_dir() and is_probably_numeric_dir(p.name):
                numeric_dirs += 1
    except Exception:
        pass

    # Retail-style XML sanity checks (helps catch subtle serializer drift)
    for p in sorted(export_root.glob("songlists_*.xml")):
        _check_retail_xml_style(p, warnings, check_run_on_subset=True)

    songs_xmls = list(export_root.glob("songs_*_0.xml"))
    banks_from_files: Set[int] = set()
    for f in songs_xmls:
        m = VERSION_RE.match(f.name)
        if m:
            banks_from_files.add(int(m.group(1)))

    chc_files = list(export_root.glob("melodies_*.chc"))

    textures_dir = export_root / "textures"
    texture_pages = 0
    if textures_dir.exists():
        texture_pages = len(list(textures_dir.glob("page_*.jpg"))) + len(list(textures_dir.glob("Page_*.jpg")))

    counts = {
        "numeric_song_folders": numeric_dirs,
        "songs_xml_files": len(songs_xmls),
        "banks_from_songs_xml": len(banks_from_files),
        "melodies_chc_files": len(chc_files),
        "texture_pages": texture_pages,
    }

    # additional warnings: mismatched config vs present banks
    if max_v is not None and banks_from_files and max_v not in banks_from_files:
        warnings.append(f"config.xml max bank is {max_v} but songs_{max_v}_0.xml was not found at Export root.")
    if banks_from_files and versions and set(versions) != set(sorted(banks_from_files)):
        warnings.append(f"Bank set mismatch: config banks={versions} vs files banks={sorted(banks_from_files)} (this can be normal for partial donors).")

    return InspectReport(
        input_path=input_path,
        kind=kind,
        resolved_root=str(export_root.parent.parent if kind == "disc_folder" else export_root),
        export_root=str(export_root),
        product_code=product_code,
        product_desc=product_desc,
        versions_in_config=versions,
        max_version_in_config=max_v,
        referenced_files={"all": sorted(set(all_refs)), "max": sorted(set(max_refs))},
        existence={"all": existence_all},
        counts=counts,
        warnings=warnings,
    )
