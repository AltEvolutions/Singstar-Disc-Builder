from __future__ import annotations

import copy
import re
import shutil
import xml.etree.ElementTree as ET
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple, Callable

from .layout import ResolvedInput
from .melody_fingerprint import melody_fingerprint_file


_NS = "http://www.singstargame.com"
ET.register_namespace("", _NS)  # keep default namespace


def _strip_ns(tag: str) -> str:
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _ns_tag(local: str) -> str:
    return f"{{{_NS}}}{local}"


def _read_xml(path: Path) -> ET.ElementTree:
    try:
        return ET.parse(path)
    except ET.ParseError as e:
        raise MergeError(f"XML parse failed: {path}: {e}") from e


def _ensure_retail_ns_decl(root: ET.Element) -> None:
    """Ensure the redundant retail-style namespace declaration exists.

    Many retail exports include both:
      - default xmlns="http://www.singstargame.com"
      - xmlns:ss="http://www.singstargame.com"

    Some console-era parsers can be brittle about serialization drift, so we
    force this declaration on disc-facing XML we emit.
    """
    if "xmlns:ss" in root.attrib:
        return
    # ElementTree can also represent xmlns declarations as '{xml-ns}ss' keys,
    # but setting the literal 'xmlns:ss' attribute reliably emits it.
    root.set("xmlns:ss", _NS)


def _write_xml(tree: ET.ElementTree, path: Path) -> None:
    """Write XML in a retail-compatible style (LF, stable formatting)."""
    path.parent.mkdir(parents=True, exist_ok=True)

    root = tree.getroot()
    if root is None:
        raise MergeError(f"Cannot write empty XML tree: {path}")

    # Avoid mutating the in-memory tree used for further merging.
    root_copy = copy.deepcopy(root)

    _ensure_retail_ns_decl(root_copy)

    # Pretty-print: one tag per line, stable indentation.
    try:
        ET.indent(root_copy, space="  ", level=0)  # py3.9+
    except Exception:
        pass

    data = ET.tostring(root_copy, encoding="UTF-8", xml_declaration=True)

    # Normalize to LF-only newlines.
    data = data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")

    # Match retail style for empty elements: '/>' (no space).
    data = data.replace(b" />", b"/>")

    # Ensure a trailing newline (common in retail exports and friendly for diff tools).
    if not data.endswith(b"\n"):
        data += b"\n"

    path.write_bytes(data)


def _iter_song_ids_from_songs_xml(root: ET.Element) -> Iterable[int]:
    for el in root.iter():
        if _strip_ns(el.tag) != "SONG":
            continue
        for key in ("ID", "id", "SONG_ID", "song_id"):
            if key in el.attrib:
                try:
                    yield int(el.attrib[key])
                except ValueError:
                    pass
                break


def _parse_int_attr(el: ET.Element, key: str) -> Optional[int]:
    if key not in el.attrib:
        return None
    try:
        return int(el.attrib[key])
    except ValueError:
        return None


_PAGE_RE = re.compile(r"^page_(\d+)\.(?P<ext>[A-Za-z0-9]+)$")


def _list_texture_pages(textures_dir: Path) -> List[Tuple[int, Path]]:
    pages: List[Tuple[int, Path]] = []
    if not textures_dir.is_dir():
        return pages
    for p in textures_dir.iterdir():
        if not p.is_file():
            continue
        m = _PAGE_RE.match(p.name)
        if not m:
            continue
        pages.append((int(m.group(1)), p))
    pages.sort(key=lambda t: t[0])
    return pages


def _max_page_index(pairs: List[Tuple[int, Path]]) -> int:
    return max((n for n, _p in pairs), default=-1)


@dataclass
class MergeOptions:
    target_version: int = 6
    mode: str = "update-required"  # update-required | self-contained (future)
    collision_policy: str = "fail"  # fail | dedupe_identical
    songlist_mode: str = "union-by-name"  # union-by-name | base-only (future)
    verbose: bool = False


@dataclass
class MergeStats:
    merged_song_count: int
    base_song_count: int
    donor_song_count: int
    acts_count: int
    texture_pages_copied: int
    chc_count: int


class MergeError(RuntimeError):
    pass


class CancelRequested(MergeError):
    """Internal exception used to unwind long operations when the user cancels."""
    pass


def _choose_bank(export_root: Path, max_bank: int) -> int:
    # canonical: highest bank
    for bank in range(max_bank, 0, -1):
        if (export_root / f"songs_{bank}_0.xml").exists():
            return bank
    return 1


def _load_config_versions(config_path: Path) -> List[int]:
    tree = _read_xml(config_path)
    root = tree.getroot()
    versions: List[int] = []
    for v in root.findall(f".//{_ns_tag('VERSION')}"):
        s = v.attrib.get("version")
        if s is None:
            continue
        try:
            versions.append(int(s))
        except ValueError:
            continue
    return sorted(set(versions))


def _detect_max_bank(export_root: Path) -> int:
    cfg = export_root / "config.xml"
    if cfg.exists():
        vs = _load_config_versions(cfg)
        return max(vs) if vs else 1
    # fallback: infer from songs_*.xml
    mx = 1
    for p in export_root.glob("songs_*_0.xml"):
        m = re.match(r"^songs_(\d+)_0\.xml$", p.name)
        if m:
            mx = max(mx, int(m.group(1)))
    return mx


def _parse_songs_and_acts(export_root: Path, bank: int) -> Tuple[ET.ElementTree, ET.ElementTree]:
    songs_p = export_root / f"songs_{bank}_0.xml"
    acts_p = export_root / f"acts_{bank}_0.xml"
    if not songs_p.exists():
        raise FileNotFoundError(f"Missing {songs_p}")
    if not acts_p.exists():
        raise FileNotFoundError(f"Missing {acts_p}")
    return _read_xml(songs_p), _read_xml(acts_p)


def _parse_songlists(export_root: Path, bank: int) -> ET.ElementTree:
    p = export_root / f"songlists_{bank}.xml"
    if not p.exists():
        raise FileNotFoundError(f"Missing {p}")
    return _read_xml(p)


def _parse_covers(export_root: Path) -> ET.ElementTree:
    p = export_root / "covers.xml"
    if not p.exists():
        raise FileNotFoundError(f"Missing {p}")
    return _read_xml(p)


def _normalize_key(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip()).upper()


def _build_act_map(acts_root: ET.Element) -> Dict[int, Tuple[str, str]]:
    # old_id -> (name, name_key)
    out: Dict[int, Tuple[str, str]] = {}
    for act in acts_root.findall(f".//{_ns_tag('ACT')}"):
        aid = _parse_int_attr(act, "ID")
        if aid is None:
            continue
        name = ""
        name_key = ""
        for ch in list(act):
            if _strip_ns(ch.tag) == "NAME":
                name = ch.text or ""
            if _strip_ns(ch.tag) == "NAME_KEY":
                name_key = ch.text or ""
        out[aid] = (name, name_key)
    return out


def _song_perf_key(song_el: ET.Element, act_map: Dict[int, Tuple[str, str]]) -> str:
    # Prefer PERFORMANCE_NAME_KEY, else performed_by->act NAME_KEY, else PERFORMANCE_NAME, else empty.
    pnk = song_el.find(f".//{_ns_tag('PERFORMANCE_NAME_KEY')}")
    if pnk is not None and (pnk.text or "").strip():
        return _normalize_key(pnk.text or "")
    # lookup act id
    pb = song_el.find(f".//{_ns_tag('PERFORMED_BY')}")
    if pb is not None:
        aid = _parse_int_attr(pb, "ID")
        if aid is not None and aid in act_map:
            _name, nk = act_map[aid]
            if nk.strip():
                return _normalize_key(nk)
    pn = song_el.find(f".//{_ns_tag('PERFORMANCE_NAME')}")
    if pn is not None and (pn.text or "").strip():
        return _normalize_key(pn.text or "")
    return ""


def _collect_songs(tree: ET.ElementTree) -> Dict[int, ET.Element]:
    root = tree.getroot()
    out: Dict[int, ET.Element] = {}
    for song in root.findall(f".//{_ns_tag('SONG')}"):
        sid = _parse_int_attr(song, "ID") or _parse_int_attr(song, "id")
        if sid is None:
            continue
        out[sid] = song
    return out


def _collect_covers(tree: ET.ElementTree) -> Dict[int, ET.Element]:
    root = tree.getroot()
    out: Dict[int, ET.Element] = {}
    for bit in root.findall(f".//{_ns_tag('TPAGE_BIT')}"):
        name = bit.attrib.get("NAME", "")
        m = re.match(r"^cover_(\d+)$", name)
        if not m:
            continue
        out[int(m.group(1))] = bit
    return out


def _extract_cover_page_num(bit: ET.Element) -> Optional[int]:
    tex = bit.attrib.get("TEXTURE", "")
    m = re.match(r"^page_(\d+)$", tex)
    if not m:
        return None
    return int(m.group(1))


def _rewrite_cover_page(bit: ET.Element, new_page: int) -> None:
    bit.attrib["TEXTURE"] = f"page_{new_page}"


def _copy_song_folder(src_export: Path, dst_export: Path, song_id: int) -> None:
    src = src_export / str(song_id)
    dst = dst_export / str(song_id)
    if not src.is_dir():
        raise MergeError(f"Missing song folder: {src}")
    if dst.exists():
        raise MergeError(f"Song folder already exists in output (collision?): {dst}")
    shutil.copytree(src, dst)


def _ensure_versioned_melody_files(export_root: Path, song_ids: Iterable[int], target_version: int, *, cancel_check: Optional[Callable[[], bool]] = None) -> None:
    """Ensure per-song melody_<version>.xml files exist for 1..target_version.

    Newer game logic (and/or newer base titles) may look for melody_<active_version>.xml
    (e.g. melody_6.xml) inside each song folder. Older discs often ship only melody_1.xml.
    We copy the highest available melody_N.xml forward to any missing versions so playback works.

    We do NOT overwrite existing files.
    """
    if target_version < 1:
        return
    melody_re = re.compile(r"^melody_(\d+)\.xml$")
    for sid in song_ids:
        if cancel_check is not None:
            try:
                if bool(cancel_check()):
                    raise CancelRequested('Cancelled')
            except CancelRequested:
                raise
            except Exception:
                pass
        sdir = export_root / str(sid)
        if not sdir.is_dir():
            raise MergeError(f"Missing song folder in output while ensuring melodies: {sdir}")
        candidates: Dict[int, Path] = {}
        for p in sdir.iterdir():
            if not p.is_file():
                continue
            m = melody_re.match(p.name)
            if not m:
                continue
            try:
                v = int(m.group(1))
            except ValueError:
                continue
            candidates[v] = p
        if not candidates:
            raise MergeError(f"No melody_*.xml files found for song {sid} in {sdir}")
        # Best source: highest version already present
        source_v = max(candidates.keys())
        source_p = candidates[source_v]
        for v in range(1, target_version + 1):
            dst = sdir / f"melody_{v}.xml"
            if dst.exists():
                continue
            shutil.copy2(source_p, dst)

        # Explicit requirement: the active melody file must exist.
        required = sdir / f"melody_{target_version}.xml"
        if not required.exists():
            raise MergeError(
                f"Required melody file missing after synthesis for song {sid}: {required}"
            )

def _case_sensitive_dir_status(parent: Path, expected_name: str) -> Tuple[bool, Optional[str]]:
    """
    Return (exact_exists, actual_ci_name).

    - exact_exists: True if a directory entry exists with *exactly* expected_name.
    - actual_ci_name: The on-disk name of a directory entry whose lowercased name matches expected_name.lower(),
      if any. (Used to detect casing hazards on case-insensitive filesystems.)
    """
    if not parent.is_dir():
        return False, None
    expected_lower = expected_name.lower()
    exact = False
    actual_ci: Optional[str] = None
    try:
        for p in parent.iterdir():
            if not p.is_dir():
                continue
            name = p.name
            if name == expected_name:
                exact = True
            if name.lower() == expected_lower:
                actual_ci = name
    except OSError:
        # If listing fails, fall back to normal existence checks elsewhere.
        return False, None
    return exact, actual_ci


def _ensure_lowercase_textures(export_root: Path) -> Path:
    # Ensure output is Export/textures (lowercase). If Export/Textures (or any other casing) exists, error.
    tex_lower = export_root / "textures"
    exact, actual = _case_sensitive_dir_status(export_root, "textures")
    if actual is not None and not exact:
        raise MergeError(
            f"Found Export/{actual} but expected Export/textures: {export_root / actual} (PS3 casing hazard)"
        )
    tex_lower.mkdir(parents=True, exist_ok=True)
    return tex_lower


def _require_lowercase_textures(export_root: Path, *, who: str = "donor") -> Path:
    tex_lower = export_root / "textures"
    exact, actual = _case_sensitive_dir_status(export_root, "textures")
    if actual is not None and not exact:
        raise MergeError(
            f"Found {who} Export/{actual} but expected Export/textures: {export_root / actual} (PS3 casing hazard)"
        )
    if not tex_lower.is_dir():
        raise MergeError(f"{who.title()} textures folder missing (must be Export/textures): {tex_lower}")
    return tex_lower


def _copy_textures_with_renumber(src_textures: Path, dst_textures: Path, page_offset: int, *, cancel_check: Optional[Callable[[], bool]] = None) -> Tuple[int, Dict[int, int]]:
    # Copy all page_N.* files, renaming N -> N+offset. Return (files_copied, mapping old->new).
    mapping: Dict[int, int] = {}
    copied = 0
    for n, p in _list_texture_pages(src_textures):
        if cancel_check is not None:
            try:
                if bool(cancel_check()):
                    raise CancelRequested('Cancelled')
            except CancelRequested:
                raise
            except Exception:
                pass
        new_n = n + page_offset
        mapping[n] = new_n
        m = _PAGE_RE.match(p.name)
        assert m is not None
        ext = m.group("ext")
        dst = dst_textures / f"page_{new_n}.{ext}"
        if dst.exists():
            raise MergeError(f"Refusing to overwrite existing texture page: {dst}")
        shutil.copy2(p, dst)
        copied += 1
    return copied, mapping


def _copy_selected_texture_pages_with_renumber(
    src_textures: Path,
    dst_textures: Path,
    pages: set[int],
    page_offset: int,
    *,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> Tuple[int, Dict[int, int]]:
    """Copy only the requested texture pages, renumbering N -> N+offset.

    Returns (files_copied, mapping old_page->new_page).
    """
    pages = set(int(p) for p in (pages or set()))
    if not pages:
        return 0, {}
    mapping: Dict[int, int] = {n: int(n) + int(page_offset) for n in pages}
    copied = 0
    found_pages: set[int] = set()
    for p in src_textures.iterdir():
        if cancel_check is not None:
            try:
                if bool(cancel_check()):
                    raise CancelRequested('Cancelled')
            except CancelRequested:
                raise
            except Exception:
                pass
        if not p.is_file():
            continue
        m = _PAGE_RE.match(p.name)
        if not m:
            continue
        try:
            n = int(m.group(1))
        except Exception:
            continue
        if n not in pages:
            continue
        ext = m.group('ext')
        dst = dst_textures / f"page_{mapping[n]}.{ext}"
        if dst.exists():
            raise MergeError(f"Refusing to overwrite existing texture page: {dst}")
        shutil.copy2(p, dst)
        copied += 1
        found_pages.add(n)
    missing = sorted(list(pages - found_pages))
    if missing:
        raise MergeError(f"Missing texture page files in donor textures folder for pages: {missing[:30]}")
    return copied, mapping


def _rebuild_chc(song_ids: List[int], export_root: Path, melody_version: int, *, cancel_check: Optional[Callable[[], bool]] = None) -> bytes:
    # Deterministic: sort song_ids.
    song_ids = sorted(song_ids)
    # Build data blobs
    blobs: List[Tuple[int, bytes, int]] = []
    for sid in song_ids:
        if cancel_check is not None:
            try:
                if bool(cancel_check()):
                    raise CancelRequested('Cancelled')
            except CancelRequested:
                raise
            except Exception:
                pass
        melody = export_root / str(sid) / f"melody_{melody_version}.xml"
        if not melody.exists():
            raise MergeError(
                f"Missing required melody file for song {sid}: {melody} (expected for active version)"
            )
        raw = melody.read_bytes()
        comp = zlib.compress(raw, level=9)
        blobs.append((sid, comp, len(raw)))

    count = len(blobs)
    header_size = 4 + count * 16
    entries: List[Tuple[int, int, int, int]] = []
    offset = header_size
    for sid, comp, usz in blobs:
        entries.append((sid, offset, len(comp), usz))
        offset += len(comp)

    out = bytearray()
    out += (count).to_bytes(4, "little")
    for sid, off, csz, usz in entries:
        out += sid.to_bytes(4, "little")
        out += off.to_bytes(4, "little")
        out += csz.to_bytes(4, "little")
        out += usz.to_bytes(4, "little")
    for sid, comp, _usz in blobs:
        out += comp
    return bytes(out)


def _validate_chc(chc_bytes: bytes, expected_song_ids: Set[int], export_root: Path, melody_version: int, sample: int = 10) -> None:
    """Basic CHC integrity check.

    We verify:
      - index structure + bounds
      - entry IDs match expected set
      - sample entries decompress and match the source melody XML bytes (melody_<version>.xml)

    This catches the common failure mode: songs appear, but none start (bad CHC).
    """

    if len(chc_bytes) < 4:
        raise MergeError('CHC too small')
    count = int.from_bytes(chc_bytes[0:4], 'little')
    header_size = 4 + count * 16
    if len(chc_bytes) < header_size:
        raise MergeError('CHC truncated header')

    entries = []  # (sid, off, csz, usz)
    seen = set()
    pos = 4
    for _ in range(count):
        sid = int.from_bytes(chc_bytes[pos:pos+4], 'little')
        pos += 4
        off = int.from_bytes(chc_bytes[pos:pos+4], 'little')
        pos += 4
        csz = int.from_bytes(chc_bytes[pos:pos+4], 'little')
        pos += 4
        usz = int.from_bytes(chc_bytes[pos:pos+4], 'little')
        pos += 4
        if sid in seen:
            raise MergeError(f'CHC duplicate entry for song {sid}')
        seen.add(sid)
        if off < header_size or csz <= 0 or usz <= 0:
            raise MergeError(f'CHC invalid entry for song {sid}: off={off} csz={csz} usz={usz}')
        if off + csz > len(chc_bytes):
            raise MergeError(f'CHC out-of-bounds blob for song {sid}: off+csz={off+csz} len={len(chc_bytes)}')
        entries.append((sid, off, csz, usz))

    if expected_song_ids and set(entries_sid for entries_sid, *_ in entries) != set(expected_song_ids):
        missing = sorted(list(set(expected_song_ids) - set(entries_sid for entries_sid, *_ in entries)))
        extra = sorted(list(set(entries_sid for entries_sid, *_ in entries) - set(expected_song_ids)))
        raise MergeError(f'CHC song-id set mismatch: missing={missing[:20]} extra={extra[:20]}')

    # Sample a few entries for decompression + source match
    for sid, off, csz, usz in entries[:max(0, min(sample, len(entries)))]:
        comp = chc_bytes[off:off+csz]
        try:
            raw = zlib.decompress(comp)
        except Exception as e:
            raise MergeError(f'CHC decompress failed for song {sid}: {e}') from e
        if len(raw) != usz:
            raise MergeError(f'CHC uncompressed size mismatch for song {sid}: got={len(raw)} expected={usz}')
        src = export_root / str(sid) / f'melody_{melody_version}.xml'
        if not src.exists():
            raise MergeError(
                f"Missing required source melody file for CHC validation (song {sid}): {src}"
            )
        if raw != src.read_bytes():
            raise MergeError(f"CHC content mismatch for song {sid} vs {src.name}")


def _build_config(base_config: ET.ElementTree, target_version: int, mode: str) -> ET.ElementTree:
    """Rewrite config.xml *schema-preservingly* using the existing file as a template.

    We do NOT invent new structures. We:
      - strip ERRATA in update-required mode
      - rebuild the VERSION list (either under <VERSIONS> or directly under <CONFIG>)
      - update any top-level SONGS/MELODY_CACHE/SONG_LISTS/COVERS blocks if present

    Tag names (e.g. LAYER vs LAYERS), ordering, and path shapes are preserved from the template.
    """

    root = base_config.getroot()

    # Strip ERRATA blocks in update-required mode
    if mode == "update-required":
        for err in list(root.findall(f".//{_ns_tag('ERRATA')}")):
            parent = _find_parent(root, err)
            if parent is not None:
                parent.remove(err)

    def _local(el: ET.Element) -> str:
        return _strip_ns(el.tag)

    def _direct_children(parent: ET.Element, local_name: str) -> list[ET.Element]:
        return [c for c in list(parent) if _local(c) == local_name]

    def _first_desc(el: ET.Element, local_name: str) -> Optional[ET.Element]:
        for x in el.iter():
            if _local(x) == local_name:
                return x
        return None

    def _set_first_desc_text(el: ET.Element, local_name: str, value: str) -> None:
        x = _first_desc(el, local_name)
        if x is not None:
            x.text = value

    # Detect schema variant: some configs have a <VERSIONS version="N"> container.
    versions_container: Optional[ET.Element] = None
    for ch in list(root):
        if _local(ch) == "VERSIONS":
            versions_container = ch
            break

    version_parent = versions_container if versions_container is not None else root

    # Collect existing VERSION nodes (direct children of version_parent)
    existing_versions = _direct_children(version_parent, "VERSION")

    def _ver_num(v: ET.Element) -> int:
        try:
            return int(v.attrib.get("version", "0"))
        except ValueError:
            return 0

    template_version: Optional[ET.Element] = None
    if existing_versions:
        template_version = max(existing_versions, key=_ver_num)

    # Fallback minimal template (should rarely happen)
    if template_version is None:
        template_version = ET.Element(_ns_tag("VERSION"), {"version": "1"})
        songs = ET.SubElement(template_version, _ns_tag("SONGS"))
        ET.SubElement(songs, _ns_tag("LAYER")).text = "0"
        ET.SubElement(songs, _ns_tag("SONG_LIST")).text = "FileSystem/Export/songs_1_0.xml"
        ET.SubElement(songs, _ns_tag("ACT_LIST")).text = "FileSystem/Export/acts_1_0.xml"
        ET.SubElement(songs, _ns_tag("PATH")).text = "FileSystem/Export/"
        mc = ET.SubElement(template_version, _ns_tag("MELODY_CACHE"))
        ET.SubElement(mc, _ns_tag("FILE")).text = "FileSystem/Export/melodies_1.chc"
        sl = ET.SubElement(template_version, _ns_tag("SONG_LISTS"))
        ET.SubElement(sl, _ns_tag("FILE")).text = "FileSystem/Export/songlists_1.xml"
        cv = ET.SubElement(template_version, _ns_tag("COVERS"))
        ET.SubElement(cv, _ns_tag("LIST")).text = "FileSystem/Export/covers.xml"
        ET.SubElement(cv, _ns_tag("PATH")).text = "FileSystem/Export/textures/"

    # Determine where VERSIONs live in the child list so we keep surrounding ordering stable.
    insert_at = 0
    if existing_versions:
        first_v = existing_versions[0]
        insert_at = list(version_parent).index(first_v)

    # Remove existing VERSION children
    for v in existing_versions:
        version_parent.remove(v)

    # If the schema has a <VERSIONS> container, keep its version attribute in sync.
    if versions_container is not None:
        versions_container.attrib["version"] = str(target_version)

    # Build new VERSION blocks (descending like real discs commonly do)
    new_versions: list[ET.Element] = []
    for i in range(target_version, 0, -1):
        v = copy.deepcopy(template_version)
        v.attrib["version"] = str(i)

        # Update file references inside this VERSION while preserving tag names and paths.
        songs = _first_desc(v, "SONGS")
        if songs is not None:
            _set_first_desc_text(songs, "SONG_LIST", f"FileSystem/Export/songs_{i}_0.xml")
            _set_first_desc_text(songs, "ACT_LIST", f"FileSystem/Export/acts_{i}_0.xml")
            # PATH is left untouched (schema varies: with/without trailing slash)

        mc = _first_desc(v, "MELODY_CACHE")
        if mc is not None:
            _set_first_desc_text(mc, "FILE", f"FileSystem/Export/melodies_{i}.chc")

        sl = _first_desc(v, "SONG_LISTS")
        if sl is not None:
            _set_first_desc_text(sl, "FILE", f"FileSystem/Export/songlists_{i}.xml")

        # Covers are single-file in our build; leave LIST/PATH as-is from template.
        new_versions.append(v)

    # Insert back at the original position
    for idx, v in enumerate(new_versions):
        version_parent.insert(insert_at + idx, v)

    # Some schema variants also include a "current" set of blocks at top-level:
    # <SONGS>, <MELODY_CACHE>, <SONG_LISTS>, <COVERS> (outside VERSION/VERSIONS).
    # If present, update them to point at target_version while preserving paths.
    top_songs = next((c for c in list(root) if _local(c) == "SONGS"), None)
    if top_songs is not None:
        _set_first_desc_text(top_songs, "SONG_LIST", f"FileSystem/Export/songs_{target_version}_0.xml")
        _set_first_desc_text(top_songs, "ACT_LIST", f"FileSystem/Export/acts_{target_version}_0.xml")

    top_mc = next((c for c in list(root) if _local(c) == "MELODY_CACHE"), None)
    if top_mc is not None:
        _set_first_desc_text(top_mc, "FILE", f"FileSystem/Export/melodies_{target_version}.chc")

    top_sl = next((c for c in list(root) if _local(c) == "SONG_LISTS"), None)
    if top_sl is not None:
        _set_first_desc_text(top_sl, "FILE", f"FileSystem/Export/songlists_{target_version}.xml")

    # Final sanity validation (fail fast rather than producing a disc that won't play songs).
    # - Ensure the rebuilt VERSION set is exactly 1..target_version.
    rebuilt = _direct_children(version_parent, "VERSION")
    nums = [_ver_num(v) for v in rebuilt]
    if set(nums) != set(range(1, target_version + 1)):
        raise MergeError(f"config.xml VERSION set mismatch: found={sorted(set(nums))} expected=1..{target_version}")

    # Ensure each VERSION points to the correct per-bank files.
    by_num = { _ver_num(v): v for v in rebuilt }
    for i in range(1, target_version + 1):
        v = by_num.get(i)
        if v is None:
            continue
        songs = _first_desc(v, "SONGS")
        mc = _first_desc(v, "MELODY_CACHE")
        sl = _first_desc(v, "SONG_LISTS")
        if songs is None or mc is None or sl is None:
            raise MergeError(f"config.xml VERSION {i} missing required blocks")
        # These elements are required for playback.
        def _must_text(parent: ET.Element, local_name: str) -> str:
            x = _first_desc(parent, local_name)
            if x is None or (x.text or '').strip() == '':
                raise MergeError(f"config.xml VERSION {i} missing {local_name}")
            return (x.text or '').strip()
        if _must_text(songs, "SONG_LIST") != f"FileSystem/Export/songs_{i}_0.xml":
            raise MergeError(f"config.xml VERSION {i} SONG_LIST mismatch")
        if _must_text(songs, "ACT_LIST") != f"FileSystem/Export/acts_{i}_0.xml":
            raise MergeError(f"config.xml VERSION {i} ACT_LIST mismatch")
        if _must_text(mc, "FILE") != f"FileSystem/Export/melodies_{i}.chc":
            raise MergeError(f"config.xml VERSION {i} MELODY_CACHE/FILE mismatch")
        if _must_text(sl, "FILE") != f"FileSystem/Export/songlists_{i}.xml":
            raise MergeError(f"config.xml VERSION {i} SONG_LISTS/FILE mismatch")

    return base_config

def _find_parent(root: ET.Element, target: ET.Element) -> Optional[ET.Element]:
    for el in root.iter():
        for ch in list(el):
            if ch is target:
                return el
    return None


def _merge_songlists_union_by_name(base_tree: ET.ElementTree, donor_trees: List[ET.ElementTree], merged_song_ids: Set[int]) -> ET.ElementTree:
    # Strategy: union SUBSET by NAME attr across entire doc, flatten donor subsets into Root group if needed.
    root = base_tree.getroot()

    # Find Root group
    root_group = None
    for g in root.findall(f".//{_ns_tag('GROUP')}"):
        if g.attrib.get("NAME") == "Root":
            root_group = g
            break
    if root_group is None:
        # if no group, use root itself
        root_group = root

    # Build subset map by NAME
    subset_map: Dict[str, ET.Element] = {}
    used_subset_ids: Set[int] = set()

    for subset in root.findall(f".//{_ns_tag('SUBSET')}"):
        name = subset.attrib.get("NAME", "")
        if name:
            subset_map[name] = subset
        sid = _parse_int_attr(subset, "ID")
        if sid is not None:
            used_subset_ids.add(sid)

    def _next_subset_id() -> int:
        return (max(used_subset_ids) + 1) if used_subset_ids else 1

    def _dedupe_song_refs(subset_el: ET.Element) -> None:
        seen: Set[int] = set()
        for sr in list(subset_el.findall(f"./{_ns_tag('SONG_REF')}")):
            sid = _parse_int_attr(sr, "ID")
            if sid is None:
                subset_el.remove(sr)
                continue
            if sid not in merged_song_ids:
                subset_el.remove(sr)
                continue
            if sid in seen:
                subset_el.remove(sr)
                continue
            seen.add(sid)

    # Clean base subsets (remove refs to missing songs, dedupe)
    for s in root.findall(f".//{_ns_tag('SUBSET')}"):
        _dedupe_song_refs(s)

    # Merge donor subsets
    for dt in donor_trees:
        droot = dt.getroot()
        for dsub in droot.findall(f".//{_ns_tag('SUBSET')}"):
            dname = dsub.attrib.get("NAME", "")
            if not dname:
                continue
            target = subset_map.get(dname)
            if target is None:
                # clone and append to Root group (flatten)
                cloned = ET.fromstring(ET.tostring(dsub, encoding="utf-8"))
                # ensure unique subset ID if present
                did = _parse_int_attr(cloned, "ID")
                if did is not None and did in used_subset_ids:
                    new_id = _next_subset_id()
                    cloned.attrib["ID"] = str(new_id)
                    used_subset_ids.add(new_id)
                elif did is not None:
                    used_subset_ids.add(did)
                _dedupe_song_refs(cloned)
                root_group.append(cloned)
                subset_map[dname] = cloned
            else:
                # union SONG_REF IDs into existing subset
                existing_ids = { _parse_int_attr(sr, "ID") for sr in target.findall(f"./{_ns_tag('SONG_REF')}") }
                existing_ids = {sid for sid in existing_ids if sid is not None}
                for sr in dsub.findall(f"./{_ns_tag('SONG_REF')}"):
                    sid = _parse_int_attr(sr, "ID")
                    if sid is None or sid not in merged_song_ids or sid in existing_ids:
                        continue
                    new_sr = ET.Element(_ns_tag("SONG_REF"), {"ID": str(sid)})
                    target.append(new_sr)
                    existing_ids.add(sid)
                _dedupe_song_refs(target)

    return base_tree


def merge_build(
    base_ri: ResolvedInput,
    donor_ris: List[ResolvedInput],
    out_dir: Path,
    opts: MergeOptions,
) -> MergeStats:
    if not donor_ris:
        raise MergeError("merge requires at least one donor")
    if opts.target_version < 1:
        raise MergeError("target_version must be >=1")
    if opts.mode not in {"update-required", "self-contained"}:
        raise MergeError("mode must be update-required or self-contained")
    if opts.collision_policy not in {"fail", "dedupe_identical"}:
        raise MergeError("collision_policy must be fail or dedupe_identical")

    # Copy full base disc folder to out (non-destructive)
    #
    # IMPORTANT: do a fast collision preflight *before* copying the base folder,
    # so we fail fast instead of waiting for GBs of data to copy.
    if out_dir.exists():
        raise MergeError(f"Output already exists: {out_dir}")

    # Preflight duplicate detection (mirrors `plan` behavior).
    # - Identical duplicates (same melody fingerprint) are safe and will be de-duped.
    # - Non-identical duplicates are unsafe and will fail.
    try:
        from .plan import make_plan
        pre = make_plan(
            base_ri=base_ri,
            donor_ris=donor_ris,
            target_version=int(opts.target_version),
            collision_policy='fail',
        )
        if pre.unresolved_duplicates:
            preview = pre.unresolved_duplicates[:50]
            raise MergeError(
                f"Duplicate song IDs detected (non-identical): {preview}{'...' if len(pre.unresolved_duplicates) > 50 else ''} "
                f"(collision_policy={opts.collision_policy})"
            )
        if opts.verbose and pre.identical_duplicates:
            print(
                f"INFO: Identical duplicate song IDs detected (safe to de-dupe): {len(pre.identical_duplicates)}; "
                f"example={pre.identical_duplicates[:20]}"
            )
    except MergeError:
        raise
    except Exception:
        # Preflight is best-effort; merge will still do in-stream duplicate checks.
        pass

    shutil.copytree(base_ri.original, out_dir)

    # Resolve output export_root by mirroring relative path from base resolved root
    # base_ri.original is the disc folder, base_ri.resolved_root points to .../USRDIR
    rel_usrdir = base_ri.resolved_root.relative_to(base_ri.original)
    out_usrdir = out_dir / rel_usrdir
    out_export = out_usrdir / "FileSystem" / "Export"
    if not out_export.is_dir():
        raise MergeError(f"Output Export root missing after copy: {out_export}")

    out_textures = _ensure_lowercase_textures(out_export)

    # Determine base/donor canonical banks
    base_max = _detect_max_bank(base_ri.export_root)
    base_bank = _choose_bank(base_ri.export_root, base_max)

    donor_infos: List[Tuple[ResolvedInput, int, int]] = []
    for dri in donor_ris:
        mx = _detect_max_bank(dri.export_root)
        bk = _choose_bank(dri.export_root, mx)
        donor_infos.append((dri, mx, bk))

    # Load base XMLs for chosen bank
    base_songs_tree, base_acts_tree = _parse_songs_and_acts(base_ri.export_root, base_bank)
    base_songlists_tree = _parse_songlists(base_ri.export_root, base_bank)
    base_covers_tree = _parse_covers(base_ri.export_root)
    base_config_tree = _read_xml(base_ri.export_root / "config.xml")

    # Collect base songs, acts map
    base_songs = _collect_songs(base_songs_tree)
    base_song_ids = set(base_songs.keys())
    base_act_map_old = _build_act_map(base_acts_tree.getroot())

    # Start merged structures from base copies
    merged_songs: Dict[int, ET.Element] = dict(base_songs)
    merged_song_ids: Set[int] = set(base_song_ids)

    merged_covers_bits: Dict[int, ET.Element] = _collect_covers(base_covers_tree)
    merged_cover_song_ids: Set[int] = set(merged_covers_bits.keys())

    # Copy donor song folders into output Export and merge XML nodes
    # Also merge covers + textures with page renumbering
    # Determine current max page index in output textures to avoid overwrites
    page_pairs = _list_texture_pages(out_textures)
    current_max_page = _max_page_index(page_pairs)

    donor_song_count_total = 0
    donor_songlists_trees: List[ET.ElementTree] = []

    # Act merging: canonical key -> new id; seed with base acts using base IDs
    act_key_to_newid: Dict[str, int] = {}
    newid_to_actnode: Dict[int, ET.Element] = {}

    # seed from base acts
    for old_id, (name, name_key) in base_act_map_old.items():
        key = _normalize_key(name_key or name)
        if not key:
            continue
        if key in act_key_to_newid:
            continue
        act_key_to_newid[key] = old_id
        # build act node (copy existing by finding in tree)
        act_node = None
        for a in base_acts_tree.getroot().findall(f".//{_ns_tag('ACT')}"):
            if _parse_int_attr(a, "ID") == old_id:
                act_node = ET.fromstring(ET.tostring(a, encoding="utf-8"))
                break
        if act_node is not None:
            newid_to_actnode[old_id] = act_node

    def _next_act_id() -> int:
        return (max(newid_to_actnode.keys()) + 1) if newid_to_actnode else 1

    # helper: map song performed_by IDs to merged act IDs
    def _remap_song_acts(song_el: ET.Element, act_old_to_key: Dict[int, str]) -> None:
        # Update PERFORMED_BY@ID and nested ACT@ID to new IDs based on canonical key
        pb = song_el.find(f"./{_ns_tag('PERFORMED_BY')}")
        if pb is not None:
            old = _parse_int_attr(pb, "ID")
            if old is not None:
                key = act_old_to_key.get(old) or _song_perf_key(song_el, {})
                new = act_key_to_newid.get(key)
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

    # For each donor
    for (dri, dmax, dbank) in donor_infos:
        donor_songs_tree, donor_acts_tree = _parse_songs_and_acts(dri.export_root, dbank)
        donor_songlists_tree = _parse_songlists(dri.export_root, dbank)
        donor_covers_tree = _parse_covers(dri.export_root)

        donor_songlists_trees.append(donor_songlists_tree)

        donor_songs = _collect_songs(donor_songs_tree)
        donor_song_ids = set(donor_songs.keys())
        donor_song_count_total += len(donor_song_ids)

        # Duplicate detection
        #
        # Important nuance:
        # - The same song ID can appear in multiple discs.
        # - If the content is identical (as measured by melody fingerprint), it is safe to de-dupe.
        #
        # Historically, we treated *any* duplicate as fatal when collision_policy=fail.
        # That contradicts the planner output (which already identifies identical duplicates
        # as safe). To keep the workflow predictable:
        #   - We ALWAYS de-dupe identical duplicates.
        #   - We FAIL only if there are non-identical duplicates.
        identical_dups: Set[int] = set()
        dups = merged_song_ids.intersection(donor_song_ids)
        if dups:
            nonidentical: List[int] = []
            for sid in sorted(dups):
                # Compare against the version that would end up in the output (base + any earlier donors)
                b_fp = melody_fingerprint_file(out_export / str(sid) / "melody_1.xml")
                d_fp = melody_fingerprint_file(dri.export_root / str(sid) / "melody_1.xml")
                if b_fp and d_fp and b_fp == d_fp:
                    identical_dups.add(sid)
                else:
                    nonidentical.append(sid)

            if nonidentical:
                # Unsafe duplicates: fail fast.
                preview = sorted(nonidentical)[:50]
                raise MergeError(
                    f"Duplicate song IDs detected (non-identical): {preview}{'...' if len(nonidentical) > 50 else ''} "
                    f"(collision_policy={opts.collision_policy})"
                )

            # Safe duplicates: drop the donor versions so we keep the base copy.
            for sid in sorted(identical_dups):
                donor_song_ids.discard(sid)
                donor_songs.pop(sid, None)
            if identical_dups and opts.verbose:
                print(
                    f"INFO: De-duped {len(identical_dups)} identical duplicate song IDs from donor {dri.original}: {sorted(list(identical_dups))[:20]}"
                )

        # Merge songs nodes (append donor songs)
        for sid, song_node in donor_songs.items():
            merged_songs[sid] = song_node
            merged_song_ids.add(sid)

        # Copy song folders for non-duplicate songs into output export
        for sid in sorted(donor_song_ids):
            _copy_song_folder(dri.export_root, out_export, sid)

        # Merge covers + textures:
        donor_bits = _collect_covers(donor_covers_tree)
        donor_textures = _require_lowercase_textures(dri.export_root, who="donor")

        # compute page offset based on current max in output textures to avoid overwrite
        offset = current_max_page + 1
        copied, page_map = _copy_textures_with_renumber(donor_textures, out_textures, page_offset=offset)
        current_max_page = current_max_page + copied  # approximate; safe enough for monotonic increase
        # Actually update max precisely
        current_max_page = max(current_max_page, _max_page_index(_list_texture_pages(out_textures)))

        # rewrite donor cover bits to new page numbers and merge
        for sid, bit in donor_bits.items():
            # If we de-duped this song ID (identical duplicate), we must also ignore its cover.
            if sid in identical_dups:
                continue
            if sid in merged_covers_bits:
                # allow if identical? covers should be unique by song id; treat as collision
                if opts.collision_policy == "fail":
                    raise MergeError(f"Duplicate cover entry for song {sid}")
                continue
            page = _extract_cover_page_num(bit)
            if page is None:
                raise MergeError(f"Unrecognized cover TEXTURE for song {sid}: {bit.attrib.get('TEXTURE')}")
            if page not in page_map:
                raise MergeError(f"Cover references texture page_{page} but it was not found in donor textures folder")
            new_page = page_map[page]
            _rewrite_cover_page(bit, new_page)
            merged_covers_bits[sid] = bit
            merged_cover_song_ids.add(sid)

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
            # clone act node and set new ID
            act_node = None
            for a in donor_acts_tree.getroot().findall(f".//{_ns_tag('ACT')}"):
                if _parse_int_attr(a, "ID") == old_id:
                    act_node = ET.fromstring(ET.tostring(a, encoding="utf-8"))
                    break
            if act_node is None:
                # synthesize
                act_node = ET.Element(_ns_tag("ACT"), {"ID": str(new_id)})
                ET.SubElement(act_node, _ns_tag("NAME")).text = name
                ET.SubElement(act_node, _ns_tag("NAME_KEY")).text = name_key or _normalize_key(name)
            act_node.attrib["ID"] = str(new_id)
            newid_to_actnode[new_id] = act_node

        # Remap act IDs in donor songs we merged
        for sid, song_node in donor_songs.items():
            _remap_song_acts(song_node, donor_old_to_key)

    # Remap base songs acts as well (so performed_by IDs match merged acts, even if base IDs preserved, this is no-op)
    base_old_to_key = {old_id: _normalize_key(nk or nm) for old_id, (nm, nk) in base_act_map_old.items()}
    for sid, song_node in list(merged_songs.items()):
        # base songs already have act IDs; remap in case key maps to same id
        _remap_song_acts(song_node, base_old_to_key)

    # Build merged songs XML tree (starting from base root, clearing SONG nodes)
    songs_root = base_songs_tree.getroot()
    # remove existing SONG children (direct children)
    for child in list(songs_root):
        if _strip_ns(child.tag) == "SONG":
            songs_root.remove(child)
    for sid in sorted(merged_songs.keys()):
        songs_root.append(merged_songs[sid])

    # Build merged acts XML tree
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

    # Validate essential: covers for each song id should exist
    missing_covers = sorted(list(merged_song_ids - set(merged_covers_bits.keys())))
    if missing_covers:
        raise MergeError(f"Missing covers.xml entries for {len(missing_covers)} songs (sample: {missing_covers[:30]})")

    # Write replicated bank files
    for bank in range(1, opts.target_version + 1):
        _write_xml(ET.ElementTree(songs_root), out_export / f"songs_{bank}_0.xml")
        _write_xml(ET.ElementTree(acts_root), out_export / f"acts_{bank}_0.xml")
        _write_xml(songlists_tree, out_export / f"songlists_{bank}.xml")

    # Write covers (single file)
    _write_xml(ET.ElementTree(covers_root), out_export / "covers.xml")

    # Rebuild CHC once and replicate
    # Ensure melody_<version>.xml exists for playback in the active target_version.
    _ensure_versioned_melody_files(out_export, merged_song_ids, opts.target_version)

    chc_bytes = _rebuild_chc(sorted(list(merged_song_ids)), out_export, melody_version=opts.target_version)
    _validate_chc(chc_bytes, set(merged_song_ids), out_export, melody_version=opts.target_version)
    for bank in range(1, opts.target_version + 1):
        (out_export / f"melodies_{bank}.chc").write_bytes(chc_bytes)

    # Build config.xml replicated versions
    config_tree = _build_config(base_config_tree, opts.target_version, opts.mode)
    _write_xml(config_tree, out_export / "config.xml")

    # Final validation: referenced pages exist
    referenced_pages: Set[int] = set()
    for bit in covers_root.findall(f".//{_ns_tag('TPAGE_BIT')}"):
        page = _extract_cover_page_num(bit)
        if page is not None:
            referenced_pages.add(page)
    # check for each referenced page there exists at least one file (jpg, gtf, etc)
    for p in referenced_pages:
        found = any((out_textures / f"page_{p}.{ext}").exists() for ext in ("jpg", "png", "gtf", "dds"))
        if not found:
            # as a fallback, check any file starting with page_{p}.
            if not any(f.name.startswith(f"page_{p}.") for f in out_textures.iterdir()):
                raise MergeError(f"Missing texture page files for referenced page_{p}.* in {out_textures}")

    return MergeStats(
        merged_song_count=len(merged_song_ids),
        base_song_count=len(base_song_ids),
        donor_song_count=donor_song_count_total,
        acts_count=len(newid_to_actnode),
        texture_pages_copied=len(_list_texture_pages(out_textures)),
        chc_count=opts.target_version,
    )
