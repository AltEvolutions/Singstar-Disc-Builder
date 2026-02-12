from __future__ import annotations

import csv
import hashlib
import json
import locale
import os
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from . import __version__
from .layout import resolve_input, ResolvedInput
from .inspect import inspect_export
from .melody_fingerprint import melody_fingerprint_file
from .file_utils import sha1_file
from .subset import build_subset, BuildCancelled, SubsetOptions
from .constants import (
    LOGS_DIRNAME,
    SUPPORT_BUNDLE_DIR_PREFIX,
    SUPPORT_BUNDLE_LOG_GLOB,
    SUPPORT_BUNDLE_MAX_LOG_BYTES,
    SUPPORT_BUNDLE_MAX_LOG_FILES,
    SUPPORT_BUNDLE_TOKEN_PREFIX_DISC,
    SUPPORT_BUNDLE_TOKEN_PREFIX_PATH,
)

# Shared SingStar XML namespace
SS_NS = {"ss": "http://www.singstargame.com"}


@dataclass(frozen=True)
class DiscIndex:
    input_path: str
    export_root: str
    product_code: Optional[str]
    product_desc: Optional[str]
    max_bank: int
    chosen_bank: int
    songs_xml: Optional[str]
    acts_xml: Optional[str]
    song_count: int
    warnings: list[str]


@dataclass(frozen=True)
class SongAgg:
    song_id: int
    title: str
    artist: str
    preferred_source: str  # label
    sources: tuple[str, ...]  # labels (unique)


@dataclass(frozen=True)
class SongOccur:
    song_id: int
    title: str
    artist: str
    source_label: str
    melody1_sha1: Optional[str]
    melody1_fp: Optional[str]


def _strip_ns(tag: str) -> str:
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _sha1_path(p: Path) -> Optional[str]:
    return sha1_file(p)


# Covers.xml helper:
# - covers.xml entries look like: NAME="cover_<songid>" TEXTURE="page_<n>"
_COVER_NAME_RE = re.compile(r"^cover_(\d+)$", re.IGNORECASE)
_COVER_PAGE_RE = re.compile(r"^page_(\d+)$", re.IGNORECASE)



def compute_song_id_conflicts(
    songs: Sequence[SongAgg],
    export_roots_by_label: Dict[str, str],
) -> Dict[int, Tuple[SongOccur, ...]]:
    """Detect duplicated Song IDs that need resolution.

    We treat a song_id as a candidate when it exists in 2+ sources and the raw
    Export/<song_id>/melody_1.xml SHA1 differs (cheap first pass).

    For each candidate we also compute a semantic melody fingerprint from note
    events. The UI can then classify the candidate as:
    - Identical duplicate (safe to hide)
    - Effectively identical (same melody, but other assets/metadata differ)
    - Different (true conflict)

    Returns: song_id -> tuple of SongOccur (one per source)
    """
    conflicts: Dict[int, Tuple[SongOccur, ...]] = {}
    if not songs:
        return conflicts

    try:
        roots = dict(export_roots_by_label or {})
    except Exception:
        roots = {}

    for s in songs:
        try:
            song_id = int(getattr(s, "song_id", 0) or 0)
            srcs = tuple(getattr(s, "sources", ()) or ())
            if song_id <= 0 or len(srcs) <= 1:
                continue
            title = str(getattr(s, "title", "") or "")
            artist = str(getattr(s, "artist", "") or "")
        except Exception:
            continue

        occs: list[SongOccur] = []


        sha_fp: list[str] = []


        sha_mismatch = False



        # First pass: raw SHA1 is cheap; use it as a candidate filter only.


        for lab in srcs:


            label = str(lab)


            root_s = str(roots.get(label, "") or "")


            sha = None


            try:


                if root_s:


                    p = Path(root_s) / str(song_id) / "melody_1.xml"


                    sha = _sha1_path(p)


            except Exception:


                sha = None


            sha_fp.append(str(sha or "MISSING"))


            occs.append(


                SongOccur(


                    song_id=song_id,


                    title=title,


                    artist=artist,


                    source_label=label,


                    melody1_sha1=sha,


                    melody1_fp=None,


                )


            )



        try:


            sha_mismatch = len(set(sha_fp)) > 1


        except Exception:


            sha_mismatch = True



        if not sha_mismatch:


            continue



        # Second pass (semantic): compute a canonical fingerprint from note events.


        fp_vals: Dict[str, Optional[str]] = {}


        for i, o in enumerate(list(occs)):


            try:


                label = str(getattr(o, "source_label", "") or "")


                root_s = str(roots.get(label, "") or "")


                fp = None


                if root_s:


                    p = Path(root_s) / str(song_id) / "melody_1.xml"


                    fp = melody_fingerprint_file(p)


                fp_vals[label] = fp


                occs[i] = SongOccur(


                    song_id=o.song_id,


                    title=o.title,


                    artist=o.artist,


                    source_label=o.source_label,


                    melody1_sha1=o.melody1_sha1,


                    melody1_fp=fp,


                )


            except Exception:


                continue



        # Include all SHA-mismatch duplicates. The caller/UI will classify them.
        conflicts[int(song_id)] = tuple(occs)

    return conflicts


def _covers_song_to_page(export_root: Path) -> Dict[int, int]:
    """Parse Export/covers.xml and return song_id -> page_num."""
    covers = export_root / "covers.xml"
    out: Dict[int, int] = {}
    if not covers.exists():
        return out
    try:
        for _ev, el in ET.iterparse(str(covers), events=("end",)):
            if _strip_ns(el.tag) != "TPAGE_BIT":
                continue
            name = (el.attrib.get("NAME") or "").strip()
            tex = (el.attrib.get("TEXTURE") or "").strip()
            m = _COVER_NAME_RE.match(name)
            if not m:
                el.clear()
                continue
            try:
                sid = int(m.group(1))
            except Exception:
                el.clear()
                continue
            m2 = _COVER_PAGE_RE.match(tex)
            if not m2:
                el.clear()
                continue
            try:
                page = int(m2.group(1))
            except Exception:
                el.clear()
                continue
            out[sid] = page
            el.clear()
    except ET.ParseError:
        return out
    except Exception:
        return out
    return out


def _texture_page_exists(textures_dir: Path, page_num: int) -> bool:
    for ext in ("jpg", "png", "gtf", "dds", "bmp"):
        if (textures_dir / f"page_{page_num}.{ext}").exists():
            return True
    return False


GUI_SETTINGS_FILE = "spcdb_gui_settings.json"


def _settings_path() -> Path:
    # Store alongside the tool (portable)
    return Path(__file__).resolve().parent / GUI_SETTINGS_FILE


def _load_settings() -> dict:
    p = _settings_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_settings(data: dict) -> None:
    p = _settings_path()
    try:
        p.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    except Exception:
        # best-effort only
        pass


# -------- Persistent disc index/song cache (v0.5.8d) --------

INDEX_CACHE_DIR = "_index_cache"
INDEX_CACHE_SCHEMA = 1


def _normalize_input_path(p: str) -> str:
    """Normalize an input path for stable cache keys."""
    s = str(p or "").strip()
    if not s:
        return ""
    try:
        return str(Path(s).expanduser().resolve())
    except Exception:
        try:
            return os.path.abspath(s)
        except Exception:
            return s


def _index_cache_dir() -> Path:
    # Store alongside the tool (portable).
    return Path(__file__).resolve().parent / INDEX_CACHE_DIR


def _index_cache_path_for_input(input_path: str) -> Path:
    norm = _normalize_input_path(input_path)
    key = hashlib.sha1(norm.encode("utf-8", errors="ignore")).hexdigest()
    return _index_cache_dir() / f"{key}.json"


def _stat_sig(p: Path) -> str:
    try:
        st = p.stat()
        # Use mtime_ns + size to catch edits, plus name for clarity.
        return f"{p.name}:{int(getattr(st, 'st_mtime_ns', int(st.st_mtime * 1e9)))}:{int(st.st_size)}"
    except Exception:
        return f"{p.name}:missing"


def _compute_disc_signature(export_root: str, songs_xml: Optional[str], acts_xml: Optional[str]) -> str:
    """Compute a cheap-ish signature for a disc's indexed files.

    We include Export/config.xml + the chosen bank's songs/acts XML (when known),
    plus the export directory stat to catch broader structural changes.
    """
    parts: list[str] = []
    try:
        er = Path(export_root)
    except Exception:
        er = Path(str(export_root))

    parts.append(_stat_sig(er))
    parts.append(_stat_sig(er / 'config.xml'))
    if songs_xml:
        parts.append(_stat_sig(Path(songs_xml)))
    if acts_xml:
        parts.append(_stat_sig(Path(acts_xml)))
    raw = "|".join(parts)
    return hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()


def _compute_disc_signature_for_idx(idx: DiscIndex) -> str:
    return _compute_disc_signature(idx.export_root, idx.songs_xml, idx.acts_xml)


def _load_index_cache(input_path: str) -> tuple[Optional[DiscIndex], Optional[Dict[int, Tuple[str, str]]], bool, str]:
    """Load cached DiscIndex (+ optional songs) for this input_path.

    Returns (idx, songs_map, stale, reason). If stale is True, the cache exists
    but the on-disk files no longer match the stored signature.
    """
    cache_path = _index_cache_path_for_input(input_path)
    if not cache_path.exists():
        return None, None, False, ""

    try:
        raw = json.loads(cache_path.read_text(encoding="utf-8"))
    except Exception as e:
        return None, None, False, f"cache read failed: {e}"

    try:
        if int(raw.get('schema', 0) or 0) != INDEX_CACHE_SCHEMA:
            return None, None, False, 'schema mismatch'
    except Exception:
        return None, None, False, 'schema mismatch'

    # Build idx from record
    rec = raw.get('disc_index') if isinstance(raw.get('disc_index'), dict) else raw
    if not isinstance(rec, dict):
        return None, None, False, 'invalid cache record'

    export_root = str(rec.get('export_root') or '')
    songs_xml = rec.get('songs_xml')
    acts_xml = rec.get('acts_xml')

    stored_sig = str(raw.get('signature') or rec.get('signature') or '')
    cur_sig = ''
    try:
        cur_sig = _compute_disc_signature(export_root, songs_xml, acts_xml)
    except Exception:
        cur_sig = ''

    if stored_sig and cur_sig and stored_sig != cur_sig:
        # Cache exists but no longer matches disc contents.
        return None, None, True, 'signature mismatch'

    # If we can't compute a signature, be conservative and treat as stale.
    if not stored_sig or not cur_sig:
        return None, None, True, 'signature unavailable'

    # Songs cache (optional)
    songs_map: Optional[Dict[int, Tuple[str, str]]] = None
    try:
        songs_raw = raw.get('songs')
        if isinstance(songs_raw, list):
            sm: Dict[int, Tuple[str, str]] = {}
            for row in songs_raw:
                if not isinstance(row, (list, tuple)) or len(row) < 3:
                    continue
                try:
                    sid = int(row[0])
                except Exception:
                    continue
                title = str(row[1] or '')
                artist = str(row[2] or '')
                sm[sid] = (title, artist)
            songs_map = sm
    except Exception:
        songs_map = None

    # Create DiscIndex; prefer current input_path (user may have different casing).
    try:
        warnings = rec.get('warnings') or []
        if not isinstance(warnings, (list, tuple)):
            warnings = []
        idx = DiscIndex(
            input_path=str(input_path),
            export_root=export_root,
            product_code=rec.get('product_code'),
            product_desc=rec.get('product_desc'),
            max_bank=int(rec.get('max_bank') or 0),
            chosen_bank=int(rec.get('chosen_bank') or 0),
            songs_xml=rec.get('songs_xml'),
            acts_xml=rec.get('acts_xml'),
            warnings=[str(x) for x in warnings],
            song_count=int(rec.get('song_count') or (len(songs_map) if songs_map else 0)),
        )
    except Exception as e:
        return None, None, False, f"cache parse failed: {e}"

    return idx, songs_map, False, 'ok'


def _write_index_cache(idx: DiscIndex, songs: Optional[Dict[int, Tuple[str, str]]] = None) -> None:
    """Write/refresh the cache record for a disc index (and optional songs)."""
    try:
        cache_dir = _index_cache_dir()
        cache_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        return

    cache_path = _index_cache_path_for_input(idx.input_path)

    # If we are only writing the index and not songs, do NOT keep old songs
    # because signature may have changed. Songs will be rebuilt on refresh.
    sig = ''
    try:
        sig = _compute_disc_signature_for_idx(idx)
    except Exception:
        sig = ''

    payload: dict = {
        'schema': INDEX_CACHE_SCHEMA,
        'version': str(__version__),
        'signature': sig,
        'saved_utc': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'disc_index': {
            'input_path': str(idx.input_path),
            'input_path_norm': _normalize_input_path(idx.input_path),
            'export_root': str(idx.export_root),
            'product_code': idx.product_code,
            'product_desc': idx.product_desc,
            'max_bank': int(idx.max_bank),
            'chosen_bank': int(idx.chosen_bank),
            'songs_xml': idx.songs_xml,
            'acts_xml': idx.acts_xml,
            'warnings': list(idx.warnings or ()),
            'song_count': int(idx.song_count or 0),
        },
    }

    if songs is not None:
        rows: list[list[object]] = []
        try:
            for sid, (title, artist) in songs.items():
                rows.append([int(sid), str(title or ''), str(artist or '')])
        except Exception:
            rows = []
        rows.sort(key=lambda r: int(r[0]) if r else 0)
        payload['songs'] = rows

    try:
        cache_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding='utf-8')
    except Exception:
        # best-effort only
        return


def get_index_cache_status(input_path: str) -> dict:
    """Return status info about the persistent index cache for an input path.

    This is intentionally lightweight and UI-agnostic.
    """
    cache_path = _index_cache_path_for_input(input_path)
    status: dict = {
        "path": str(cache_path),
        "exists": bool(cache_path.exists()),
        "stale": False,
        "reason": "",
        "saved_utc": "",
        "version": "",
        "has_songs": False,
        "song_count": 0,
    }
    if not cache_path.exists():
        status["reason"] = "missing"
        return status

    raw = None
    try:
        raw = json.loads(cache_path.read_text(encoding="utf-8"))
        status["saved_utc"] = str(raw.get("saved_utc") or "")
        status["version"] = str(raw.get("version") or "")
    except Exception as e:
        status["reason"] = f"cache read failed: {e}"
        return status

    try:
        idx, songs_map, stale, reason = _load_index_cache(input_path)
        status["stale"] = bool(stale)
        status["reason"] = str(reason or "")
        status["has_songs"] = songs_map is not None
        if idx is not None:
            try:
                status["song_count"] = int(idx.song_count or 0)
            except Exception:
                status["song_count"] = 0
        elif songs_map is not None:
            status["song_count"] = int(len(songs_map))
    except Exception as e:
        status["reason"] = f"cache status failed: {e}"
    return status


def clear_index_cache() -> tuple[bool, str]:
    """Delete the persistent index cache directory (best-effort)."""
    d = _index_cache_dir()
    try:
        if not d.exists():
            return True, "cache directory does not exist"
        # Remove only our known cache files
        for p in d.glob("*.json"):
            try:
                p.unlink()
            except Exception:
                pass
        # Remove dir if empty
        try:
            if d.exists() and d.is_dir() and not any(d.iterdir()):
                d.rmdir()
        except Exception:
            pass
        return True, "cache cleared"
    except Exception as e:
        return False, str(e)



def _parse_config(export_root: Path) -> tuple[Optional[str], Optional[str], list[int]]:
    cfg = export_root / "config.xml"
    if not cfg.exists():
        return None, None, []

    data = cfg.read_bytes()
    try:
        root = ET.fromstring(data)
    except ET.ParseError as e:
        raise ValueError(f"XML parse failed for {cfg}: {e}") from e

    def _find_text(xpath: str) -> Optional[str]:
        el = root.find(xpath, namespaces=SS_NS)
        if el is None or el.text is None:
            return None
        t = el.text.strip()
        return t or None

    product_code = _find_text(".//ss:PRODUCT_CODE")
    product_desc = _find_text(".//ss:PRODUCT_DESC")

    versions: list[int] = []
    for child in list(root):
        if _strip_ns(child.tag) != "VERSION":
            continue
        v = child.attrib.get("version")
        if v is None:
            continue
        try:
            versions.append(int(v))
        except ValueError:
            continue
    versions = sorted(set(versions))
    return product_code, product_desc, versions


def _best_bank_files(export_root: Path, preferred_bank: int) -> tuple[Optional[int], Optional[Path], Optional[Path]]:
    """Return (bank, songs_xml_path, acts_xml_path) for a disc."""
    songs_p = export_root / f"songs_{preferred_bank}_0.xml"
    acts_p = export_root / f"acts_{preferred_bank}_0.xml"
    if songs_p.exists() and acts_p.exists():
        return preferred_bank, songs_p, acts_p

    best_v: Optional[int] = None
    best_s: Optional[Path] = None
    best_a: Optional[Path] = None
    for p in export_root.glob("songs_*_0.xml"):
        name = p.name
        if not name.startswith("songs_") or not name.endswith("_0.xml"):
            continue
        mid = name[len("songs_") : -len("_0.xml")]
        try:
            v = int(mid)
        except ValueError:
            continue
        a = export_root / f"acts_{v}_0.xml"
        if not a.exists():
            continue
        if best_v is None or v > best_v:
            best_v = v
            best_s = p
            best_a = a
    if best_v is None:
        return None, None, None
    return best_v, best_s, best_a


def _parse_song_id(el: ET.Element) -> Optional[int]:
    for key in ("ID", "id", "SONG_ID", "song_id"):
        if key in el.attrib:
            try:
                return int(el.attrib[key])
            except ValueError:
                return None
    return None


def _extract_song_ids_count(songs_xml: Path) -> int:
    ids: set[int] = set()
    try:
        for _ev, el in ET.iterparse(str(songs_xml), events=("end",)):
            if _strip_ns(el.tag) != "SONG":
                continue
            sid = _parse_song_id(el)
            if sid is not None:
                ids.add(sid)
            el.clear()
    except ET.ParseError as e:
        raise ValueError(f"XML parse failed for {songs_xml}: {e}") from e

    return len(ids)


# --- Controller API (Block D / 0.5.10a2) ---------------------------------

def index_disc(input_path: str) -> DiscIndex:
    """Index a disc folder (UI-agnostic).

    This resolves the input folder (supports extracted/unextracted layouts),
    parses Export/config.xml to pick the best bank, and returns a DiscIndex.
    """
    # Fast path: reuse cached DiscIndex when still valid.
    try:
        cached_idx, _songs_map, stale, _reason = _load_index_cache(input_path)
        if (cached_idx is not None) and (not stale):
            return cached_idx
    except Exception:
        pass

    ri = resolve_input(input_path)
    export_root = ri.export_root

    warnings: list[str] = list(getattr(ri, "warnings", []) or [])

    product_code, product_desc, versions = _parse_config(export_root)
    max_bank = max(versions) if versions else 1
    chosen_bank = max_bank

    bank, songs_xml, acts_xml = _best_bank_files(export_root, preferred_bank=chosen_bank)
    if bank is None or songs_xml is None or acts_xml is None:
        warnings.append("No songs_<bank>_0.xml + acts_<bank>_0.xml pair found under Export root.")
        idx = DiscIndex(
            input_path=str(ri.original),
            export_root=str(export_root),
            product_code=product_code,
            product_desc=product_desc,
            max_bank=max_bank,
            chosen_bank=chosen_bank,
            songs_xml=None,
            acts_xml=None,
            song_count=0,
            warnings=warnings,
        )
        try:
            _write_index_cache(idx, songs=None)
        except Exception:
            pass
        return idx
    chosen_bank = bank

    # Avoid heavy parsing during disc indexing; totals are computed when refreshing songs list.
    song_count = 0

    idx = DiscIndex(
        input_path=str(ri.original),
        export_root=str(export_root),
        product_code=product_code,
        product_desc=product_desc,
        max_bank=max_bank,
        chosen_bank=chosen_bank,
        songs_xml=str(songs_xml),
        acts_xml=str(acts_xml),
        song_count=song_count,
        warnings=warnings,
    )
    try:
        _write_index_cache(idx, songs=None)
    except Exception:
        pass
    return idx


def _act_map_from_xml(acts_xml: Path) -> Dict[int, str]:
    out: Dict[int, str] = {}
    try:
        for _ev, el in ET.iterparse(str(acts_xml), events=("end",)):
            if _strip_ns(el.tag) != "ACT":
                continue
            aid = _parse_song_id(el)  # ACT uses ID too
            if aid is None:
                el.clear()
                continue
            name: str = ""
            # prefer NAME, else NAME_KEY
            for ch in list(el):
                t = _strip_ns(ch.tag)
                if t == "NAME" and (ch.text or "").strip():
                    name = (ch.text or "").strip()
                    break
            if not name:
                for ch in list(el):
                    t = _strip_ns(ch.tag)
                    if t == "NAME_KEY" and (ch.text or "").strip():
                        name = (ch.text or "").strip()
                        break
            if name:
                out[aid] = name
            el.clear()
    except ET.ParseError as e:
        raise ValueError(f"XML parse failed for {acts_xml}: {e}") from e
    return out


def _find_text_by_tag(song_el: ET.Element, tags: list[str]) -> Optional[str]:
    for tag in tags:
        for el in song_el.iter():
            if _strip_ns(el.tag) == tag:
                t = (el.text or "").strip()
                if t:
                    return t
    return None


def _song_title(song_el: ET.Element) -> str:
    # Be permissive; different discs use slightly different tag conventions.
    t = _find_text_by_tag(song_el, ["TITLE", "SONG_NAME", "NAME"])
    if t:
        return t
    t = _find_text_by_tag(song_el, ["TITLE_KEY", "SONG_NAME_KEY", "NAME_KEY"])
    return t or ""


def _song_artist(song_el: ET.Element, act_map: Dict[int, str]) -> str:
    # Prefer explicit PERFORMANCE_NAME, else PERFORMED_BY -> ACT NAME, else key-ish fallbacks.
    t = _find_text_by_tag(song_el, ["PERFORMANCE_NAME"])
    if t:
        return t

    # PERFORMED_BY element with ID attribute
    for el in song_el.iter():
        if _strip_ns(el.tag) == "PERFORMED_BY":
            aid = _parse_song_id(el)
            if aid is not None and aid in act_map:
                return act_map[aid]
            break

    t = _find_text_by_tag(song_el, ["PERFORMANCE_NAME_KEY", "ARTIST", "ARTIST_NAME"])
    return t or ""


def _load_songs_for_disc(idx: DiscIndex) -> Dict[int, Tuple[str, str]]:
    """Return song_id -> (title, artist) for a disc index."""
    if not idx.songs_xml or not idx.acts_xml:
        return {}

    acts_xml = Path(idx.acts_xml)
    songs_xml = Path(idx.songs_xml)

    act_map = _act_map_from_xml(acts_xml)

    out: Dict[int, Tuple[str, str]] = {}
    try:
        for _ev, el in ET.iterparse(str(songs_xml), events=("end",)):
            if _strip_ns(el.tag) != "SONG":
                continue
            sid = _parse_song_id(el)
            if sid is None:
                el.clear()
                continue
            title = _song_title(el)
            artist = _song_artist(el, act_map)
            out[sid] = (title, artist)
            el.clear()
    except ET.ParseError as e:
        raise ValueError(f"XML parse failed for {songs_xml}: {e}") from e
    return out


def _load_songs_for_disc_cached(idx: DiscIndex) -> Dict[int, Tuple[str, str]]:
    """Return song_id -> (title, artist), using persistent cache when valid."""
    # Try disk cache first
    try:
        di, songs_map, stale, _reason = _load_index_cache(idx.input_path)
        if (not stale) and (songs_map is not None):
            # Ensure cache signature matches the *current* idx (bank may differ).
            try:
                if di is not None and _compute_disc_signature_for_idx(idx) == _compute_disc_signature_for_idx(di):
                    return songs_map
            except Exception:
                pass
    except Exception:
        pass

    # Fall back to parsing
    out = _load_songs_for_disc(idx)
    try:
        _write_index_cache(idx, songs=out)
    except Exception:
        pass
    return out




def build_song_catalog(
    discs: Sequence[Tuple[str, DiscIndex, bool]],
    cancel: Optional["CancelToken"] = None,
    log: Optional[Callable[[str], None]] = None,
) -> Tuple[List[SongAgg], Dict[str, set[int]]]:
    """Build an aggregated song catalog (UI-agnostic).

    discs: sequence of (label, DiscIndex, is_base). Prefer base first.
    Returns (songs_out, disc_song_ids_by_label).
    """
    disc_song_ids_by_label: Dict[str, set[int]] = {}
    agg: Dict[int, Dict[str, object]] = {}

    for label, di, is_base in discs:
        if cancel is not None:
            cancel.raise_if_cancelled("Cancelled")
        if log is not None:
            try:
                log(f"[songs] Reading {label}...")
            except Exception:
                pass

        songs = _load_songs_for_disc_cached(di)

        try:
            disc_song_ids_by_label.setdefault(label, set()).update(set(songs.keys()))
        except Exception:
            disc_song_ids_by_label.setdefault(label, set())

        for sid, (title, artist) in songs.items():
            if sid not in agg:
                agg[sid] = {
                    "song_id": sid,
                    "title": title,
                    "artist": artist,
                    "preferred": label,
                    "sources": {label},
                    "in_base": bool(is_base),
                }
            else:
                a = agg[sid]
                try:
                    srcs = a["sources"]  # type: ignore[assignment]
                    srcs.add(label)  # type: ignore[union-attr]
                except Exception:
                    pass
                # If this is base, prefer its metadata
                if is_base:
                    a["preferred"] = "Base"
                    a["in_base"] = True
                    if title:
                        a["title"] = title
                    if artist:
                        a["artist"] = artist

    songs_out: List[SongAgg] = []
    for _sid, a in agg.items():
        sources = sorted(list(a["sources"]))  # type: ignore[index]
        songs_out.append(
            SongAgg(
                song_id=int(a["song_id"]),  # type: ignore[arg-type]
                title=str(a.get("title") or ""),
                artist=str(a.get("artist") or ""),
                preferred_source=str(a.get("preferred") or "Base"),
                sources=tuple(sources),
            )
        )
    songs_out.sort(key=lambda s: s.song_id)
    return songs_out, disc_song_ids_by_label

# --- Cancellation token + disc validation operations (Block D / 0.5.10a3) ---

class BuildBlockedError(RuntimeError):
    """Raised when a build is intentionally blocked (e.g., preflight validation failures)."""

    pass


class CancelledError(Exception):
    pass


class CancelToken:
    """Lightweight cancellation token.

    You can pass either an explicit token (and call cancel()), or provide a
    check callable that returns True when cancellation is requested.
    """

    def __init__(self, check: Optional[Callable[[], bool]] = None) -> None:
        self._cancelled = False
        self._check = check

    def cancel(self) -> None:
        self._cancelled = True

    def cancelled(self) -> bool:
        if self._cancelled:
            return True
        if self._check is None:
            return False
        try:
            return bool(self._check())
        except Exception:
            return False

    def raise_if_cancelled(self, message: str = "Cancelled") -> None:
        if self.cancelled():
            raise CancelledError(message)


def _minimal_export_scan(export_root: Path) -> dict:
    """Best-effort scan when config.xml is missing (common for partial XML-only donors)."""
    numeric_dirs = 0
    try:
        for p in export_root.iterdir():
            if p.is_dir() and str(p.name).isdigit():
                numeric_dirs += 1
    except Exception:
        pass

    songs_xmls = list(export_root.glob("songs_*_0.xml"))
    banks_from_files: set[int] = set()
    try:
        for f in songs_xmls:
            m = re.match(r"^songs_(\d+)_0\.xml$", f.name)
            if m:
                banks_from_files.add(int(m.group(1)))
    except Exception:
        pass

    chc_files = list(export_root.glob("melodies_*.chc"))

    textures_dir = export_root / "textures"
    texture_pages = 0
    try:
        if textures_dir.exists():
            for ext in ("jpg", "png", "gtf", "dds", "bmp"):
                texture_pages += len(list(textures_dir.glob(f"page_*.{ext}")))
                texture_pages += len(list(textures_dir.glob(f"Page_*.{ext}")))
    except Exception:
        pass

    return {
        "numeric_song_folders": int(numeric_dirs),
        "songs_xml_files": int(len(songs_xmls)),
        "banks_from_songs_xml": int(len(banks_from_files)),
        "melodies_chc_files": int(len(chc_files)),
        "texture_pages": int(texture_pages),
    }


def validate_one_disc(label: str, input_path: str) -> dict:
    """Validate a disc path (UI-agnostic) and return a structured result dict."""
    res: dict = {
        "label": str(label),
        "input_path": str(input_path),
        "ok": False,
        "severity": "FAIL",
        "kind": "",
        "resolved_root": "",
        "export_root": "",
        "product": "",
        "summary": "",
        "errors": [],
        "warnings": [],
        "missing_refs": [],
        "counts": {},
        "covers": {},
    }

    def add_issue(level: str, code: str, message: str, fix: str) -> None:
        it = {"code": str(code), "message": str(message), "fix": str(fix)}
        if str(level).upper() == "ERROR":
            res["errors"].append(it)
        else:
            res["warnings"].append(it)

    raw_warnings: list[str] = []

    # Resolve Export root
    try:
        ri = resolve_input(str(input_path))
        res["kind"] = str(getattr(ri, "kind", "") or "")
        try:
            res["resolved_root"] = str(getattr(ri, "resolved_root", "") or "")
        except Exception:
            res["resolved_root"] = ""
        res["export_root"] = str(getattr(ri, "export_root", "") or "")
        raw_warnings = list(getattr(ri, "warnings", []) or [])
    except Exception as e:
        add_issue(
            "ERROR",
            "RESOLVE_EXPORT_ROOT",
            f"Could not locate Export root: {e}",
            "Make sure the disc is extracted and points to a folder containing PS3_GAME/USRDIR/FileSystem/Export, or point directly at an Export folder.",
        )
        res["summary"] = "Could not locate Export root (needs extraction or wrong path)."
        return res

    export_root = Path(str(res["export_root"])).resolve()

    if not export_root.exists():
        add_issue(
            "ERROR",
            "EXPORT_MISSING",
            f"Export folder does not exist: {export_root}",
            "Re-extract the disc or fix the selected path so Export exists.",
        )
        res["summary"] = "Export folder missing."
        return res

    # Interpret layout warnings
    for w in raw_warnings:
        lw = str(w).lower()
        if "export folder name" in lw or "casing" in lw:
            add_issue("WARN", "CASING", str(w), "Rename folders to match: FileSystem/Export, and Export/textures (textures lowercase).")
        elif "no textures folder found" in lw:
            add_issue("WARN", "NO_TEXTURES", str(w), "For real discs/output, ensure Export/textures exists and contains page_*.jpg.")
        elif "no config.xml" in lw:
            add_issue("WARN", "NO_CONFIG", str(w), "If this should be a full disc, re-extract the starting pack so Export/config.xml exists.")
        else:
            add_issue("WARN", "LAYOUT", str(w), "Review the folder layout under Export and re-extract if needed.")

    # Try full inspect (needs config.xml)
    missing_refs: list[str] = []
    counts: dict = {}
    try:
        report_obj = inspect_export(export_root=export_root, kind=str(res["kind"] or ""), input_path=str(input_path), warnings=[])
        counts = dict(getattr(report_obj, "counts", {}) or {})
        try:
            prod = getattr(report_obj, "product_desc", None) or getattr(report_obj, "product_code", None) or ""
            res["product"] = str(prod)
        except Exception:
            pass
        try:
            existence = getattr(report_obj, "existence", {}) or {}
            all_ex = (existence.get("all") or {}) if isinstance(existence, dict) else {}
            for ref, ok in (all_ex.items() if isinstance(all_ex, dict) else []):
                if not bool(ok):
                    missing_refs.append(str(ref))
        except Exception:
            missing_refs = []
        try:
            for w in list(getattr(report_obj, "warnings", []) or []):
                add_issue("WARN", "INSPECT", str(w), "Re-extract if this looks wrong; partial donors may be OK.")
        except Exception:
            pass
    except FileNotFoundError as e:
        add_issue(
            "WARN",
            "MISSING_CONFIG_XML",
            str(e),
            "If this should be a full disc, re-extract the starting pack so Export/config.xml exists. For XML-only donors this can be OK.",
        )
        counts = _minimal_export_scan(export_root)
    except Exception as e:
        add_issue("ERROR", "INSPECT_FAILED", f"Inspect failed: {e}", "Re-extract the disc (starting pack) and try again.")
        res["counts"] = counts
        res["missing_refs"] = sorted(set(missing_refs))
        res["summary"] = "Inspect failed."
        return res

    res["missing_refs"] = sorted(set(missing_refs))
    res["counts"] = counts

    if res["missing_refs"]:
        show = ", ".join(res["missing_refs"][:6])
        more = "" if len(res["missing_refs"]) <= 6 else f" (+{len(res['missing_refs']) - 6} more)"
        add_issue(
            "WARN",
            "MISSING_REFERENCED_FILES",
            f"Missing referenced files: {show}{more}",
            "Re-extract the disc and ensure the referenced files exist under Export (some partial donors may omit them).",
        )

    # Covers/pages check (best-effort)
    covers_info = {"covers": 0, "unique_pages": 0, "missing_pages": 0}
    try:
        song_to_page = _covers_song_to_page(export_root)
        covers_info["covers"] = int(len(song_to_page))
        pages = sorted(set(song_to_page.values()))
        covers_info["unique_pages"] = int(len(pages))
        textures_dir = export_root / "textures"
        missing = 0
        if textures_dir.exists():
            for pnum in pages:
                if not _texture_page_exists(textures_dir, int(pnum)):
                    missing += 1
        else:
            missing = int(len(pages))
        covers_info["missing_pages"] = int(missing)
    except Exception:
        pass

    res["covers"] = covers_info

    if int(covers_info.get("missing_pages", 0) or 0) > 0:
        add_issue(
            "WARN",
            "MISSING_COVER_PAGES",
            f"Some cover pages are missing in Export/textures (missing pages: {covers_info.get('missing_pages')}).",
            "Re-extract textures and ensure page_*.jpg exists under Export/textures.",
        )

    # Media sanity checks (preview/video). Missing or corrupt media means the extraction is not usable.
    try:
        idx0 = index_disc(str(input_path))
        songs_map0 = _load_songs_for_disc_cached(idx0)
        song_ids0 = set(int(k) for k in (songs_map0 or {}).keys())
    except Exception:
        song_ids0 = set()

    try:
        if song_ids0:
            media0 = _scan_missing_or_corrupt_media(
                export_root,
                song_ids0,
                min_preview_bytes=1024,
                min_video_bytes=1024,
            )
        else:
            media0 = None
    except Exception:
        media0 = None

    if media0:
        mp = list(media0.get('missing_preview_ids') or [])
        mv = list(media0.get('missing_video_ids') or [])
        cp = dict(media0.get('corrupt_preview') or {})
        cv = dict(media0.get('corrupt_video') or {})

        # Treat as ERRORs: these discs cannot contribute playable songs.
        if mp or mv or cp or cv:
            # Store counts for UI/report.
            try:
                res_counts = dict(res.get('counts') or {})
                res_counts['missing_preview_files'] = int(len(mp))
                res_counts['missing_video_files'] = int(len(mv))
                res_counts['corrupt_preview_files'] = int(len(cp))
                res_counts['corrupt_video_files'] = int(len(cv))
                res['counts'] = res_counts
            except Exception:
                pass

            show_ids = sorted(set([int(x) for x in (mp + mv + list(cp.keys()) + list(cv.keys()))]))
            show = ", ".join([str(x) for x in show_ids[:10]])
            more = "" if len(show_ids) <= 10 else f" (+{len(show_ids) - 10} more)"

            add_issue(
                'ERROR',
                'MISSING_MEDIA_FILES',
                f"Missing/corrupt preview/video files for {len(show_ids)} song(s): {show}{more}",
                "Re-extract this disc (starting pack) and re-run Verify/Validate. If this is an extracted disc, your extractor output is incomplete/corrupt.",
            )
    

    # Errors that should block a disc being usable
    try:
        if int((counts or {}).get("songs_xml_files", 0) or 0) == 0:
            add_issue(
                "ERROR",
                "NO_SONGS_XML",
                "No songs_*_0.xml files found at Export root.",
                "Ensure you are pointing at the extracted starting pack Export folder and that songs_<bank>_0.xml exists.",
            )
    except Exception:
        pass

    # Severity + summary
    if res["errors"]:
        res["severity"] = "FAIL"
        res["ok"] = False
    elif res["warnings"]:
        res["severity"] = "WARN"
        res["ok"] = True
    else:
        res["severity"] = "OK"
        res["ok"] = True

    try:
        songs_xml = int((counts or {}).get("songs_xml_files", 0) or 0)
        banks = int((counts or {}).get("banks_from_songs_xml", 0) or 0)
        tex = int((counts or {}).get("texture_pages", 0) or 0)
        miss_refs_n = int(len(res["missing_refs"] or []))
        miss_pages_n = int((covers_info.get("missing_pages", 0) or 0))
        res["summary"] = f"songs_xml={songs_xml}, banks={banks}, textures={tex}, missing_refs={miss_refs_n}, missing_cover_pages={miss_pages_n}"
    except Exception:
        res["summary"] = "Validation complete."

    return res


def validate_one_disc_from_export_root(label: str, input_path: str, export_root: Path, kind: str, layout_warnings: list[str]) -> dict:
    """Validate using a known Export root (avoids re-resolving inputs).

    Used for validate-before-build preflight (v0.5.9a4+).
    """
    res: dict = {
        "label": str(label),
        "input_path": str(input_path),
        "ok": False,
        "severity": "FAIL",
        "kind": str(kind or ""),
        "resolved_root": "",
        "export_root": str(export_root),
        "product": "",
        "summary": "",
        "errors": [],
        "warnings": [],
        "missing_refs": [],
        "counts": {},
        "covers": {},
    }

    def add_issue(level: str, code: str, message: str, fix: str) -> None:
        it = {"code": str(code), "message": str(message), "fix": str(fix)}
        if str(level).upper() == "ERROR":
            res["errors"].append(it)
        else:
            res["warnings"].append(it)

    try:
        export_root = Path(str(export_root)).resolve()
    except Exception:
        export_root = Path(str(export_root))

    if not export_root.exists():
        add_issue(
            "ERROR",
            "EXPORT_MISSING",
            f"Export folder does not exist: {export_root}",
            "Re-extract the disc or fix the selected path so Export exists.",
        )
        res["summary"] = "Export folder missing."
        return res

    # Interpret layout warnings (same mapping as validate_one_disc)
    for w in list(layout_warnings or []):
        lw = str(w).lower()
        if "export folder name" in lw or "casing" in lw:
            add_issue("WARN", "CASING", str(w), "Rename folders to match: FileSystem/Export, and Export/textures (textures lowercase).")
        elif "no textures folder found" in lw:
            add_issue("WARN", "NO_TEXTURES", str(w), "For real discs/output, ensure Export/textures exists and contains page_*.jpg.")
        elif "no config.xml" in lw:
            add_issue("WARN", "NO_CONFIG", str(w), "If this should be a full disc, re-extract the starting pack so Export/config.xml exists.")
        else:
            add_issue("WARN", "LAYOUT", str(w), "Review the folder layout under Export and re-extract if needed.")

    missing_refs: list[str] = []
    counts: dict = {}
    try:
        report_obj = inspect_export(export_root=export_root, kind=str(kind or ""), input_path=str(input_path), warnings=[])
        counts = dict(getattr(report_obj, "counts", {}) or {})
        try:
            prod = getattr(report_obj, "product_desc", None) or getattr(report_obj, "product_code", None) or ""
            res["product"] = str(prod)
        except Exception:
            pass
        try:
            existence = getattr(report_obj, "existence", {}) or {}
            all_ex = (existence.get("all") or {}) if isinstance(existence, dict) else {}
            for ref, ok in (all_ex.items() if isinstance(all_ex, dict) else []):
                if not bool(ok):
                    missing_refs.append(str(ref))
        except Exception:
            missing_refs = []
        try:
            for w in list(getattr(report_obj, "warnings", []) or []):
                add_issue("WARN", "INSPECT", str(w), "Re-extract if this looks wrong; partial donors may be OK.")
        except Exception:
            pass
    except FileNotFoundError as e:
        add_issue(
            "WARN",
            "MISSING_CONFIG_XML",
            str(e),
            "If this should be a full disc, re-extract the starting pack so Export/config.xml exists. For XML-only donors this can be OK.",
        )
        counts = _minimal_export_scan(export_root)
    except Exception as e:
        add_issue("ERROR", "INSPECT_FAILED", f"Inspect failed: {e}", "Re-extract the disc (starting pack) and try again.")
        res["counts"] = counts
        res["missing_refs"] = sorted(set(missing_refs))
        res["summary"] = "Inspect failed."
        return res

    res["missing_refs"] = sorted(set(missing_refs))
    res["counts"] = counts

    if res["missing_refs"]:
        show = ", ".join(res["missing_refs"][:6])
        more = "" if len(res["missing_refs"]) <= 6 else f" (+{len(res['missing_refs']) - 6} more)"
        add_issue(
            "WARN",
            "MISSING_REFERENCED_FILES",
            f"Missing referenced files: {show}{more}",
            "Re-extract the disc and ensure the referenced files exist under Export (some partial donors may omit them).",
        )

    # Covers/pages check (best-effort)
    covers_info = {"covers": 0, "unique_pages": 0, "missing_pages": 0}
    try:
        song_to_page = _covers_song_to_page(export_root)
        covers_info["covers"] = int(len(song_to_page))
        pages = sorted(set(song_to_page.values()))
        covers_info["unique_pages"] = int(len(pages))
        textures_dir = export_root / "textures"
        missing = 0
        if textures_dir.exists():
            for pnum in pages:
                if not _texture_page_exists(textures_dir, int(pnum)):
                    missing += 1
        else:
            missing = int(len(pages))
        covers_info["missing_pages"] = int(missing)
    except Exception:
        pass

    res["covers"] = covers_info

    if int(covers_info.get("missing_pages", 0) or 0) > 0:
        add_issue(
            "WARN",
            "MISSING_COVER_PAGES",
            f"Some cover pages are missing in Export/textures (missing pages: {covers_info.get('missing_pages')}).",
            "Re-extract textures and ensure page_*.jpg exists under Export/textures.",
        )

    # Media sanity checks (preview/video). Missing or corrupt media means the extraction is not usable.
    try:
        idx0 = index_disc(str(input_path))
        songs_map0 = _load_songs_for_disc_cached(idx0)
        song_ids0 = set(int(k) for k in (songs_map0 or {}).keys())
    except Exception:
        song_ids0 = set()

    try:
        if song_ids0:
            media0 = _scan_missing_or_corrupt_media(
                export_root,
                song_ids0,
                min_preview_bytes=1024,
                min_video_bytes=1024,
            )
        else:
            media0 = None
    except Exception:
        media0 = None

    if media0:
        mp = list(media0.get('missing_preview_ids') or [])
        mv = list(media0.get('missing_video_ids') or [])
        cp = dict(media0.get('corrupt_preview') or {})
        cv = dict(media0.get('corrupt_video') or {})

        # Treat as ERRORs: these discs cannot contribute playable songs.
        if mp or mv or cp or cv:
            # Store counts for UI/report.
            try:
                res_counts = dict(res.get('counts') or {})
                res_counts['missing_preview_files'] = int(len(mp))
                res_counts['missing_video_files'] = int(len(mv))
                res_counts['corrupt_preview_files'] = int(len(cp))
                res_counts['corrupt_video_files'] = int(len(cv))
                res['counts'] = res_counts
            except Exception:
                pass

            show_ids = sorted(set([int(x) for x in (mp + mv + list(cp.keys()) + list(cv.keys()))]))
            show = ", ".join([str(x) for x in show_ids[:10]])
            more = "" if len(show_ids) <= 10 else f" (+{len(show_ids) - 10} more)"

            add_issue(
                'ERROR',
                'MISSING_MEDIA_FILES',
                f"Missing/corrupt preview/video files for {len(show_ids)} song(s): {show}{more}",
                "Re-extract this disc (starting pack) and re-run Verify/Validate. If this is an extracted disc, your extractor output is incomplete/corrupt.",
            )
    

    # Errors that should block a disc being usable
    try:
        if int((counts or {}).get("songs_xml_files", 0) or 0) == 0:
            add_issue(
                "ERROR",
                "NO_SONGS_XML",
                "No songs_*_0.xml files found at Export root.",
                "Ensure you are pointing at the extracted starting pack Export folder and that songs_<bank>_0.xml exists.",
            )
    except Exception:
        pass

    # Severity + summary
    if res["errors"]:
        res["severity"] = "FAIL"
        res["ok"] = False
    elif res["warnings"]:
        res["severity"] = "WARN"
        res["ok"] = True
    else:
        res["severity"] = "OK"
        res["ok"] = True

    try:
        songs_xml = int((counts or {}).get("songs_xml_files", 0) or 0)
        banks = int((counts or {}).get("banks_from_songs_xml", 0) or 0)
        tex = int((counts or {}).get("texture_pages", 0) or 0)
        miss_refs_n = int(len(res["missing_refs"] or []))
        miss_pages_n = int((covers_info.get("missing_pages", 0) or 0))
        res["summary"] = f"songs_xml={songs_xml}, banks={banks}, textures={tex}, missing_refs={miss_refs_n}, missing_cover_pages={miss_pages_n}"
    except Exception:
        res["summary"] = "Validation complete."

    return res


def format_validate_report(results: Sequence[dict], preflight: bool = False) -> str:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines: list[str] = []
    if preflight:
        lines.append(f"Validate Disc report (preflight) (v{__version__}) - {ts}")
    else:
        lines.append(f"Validate Disc report (v{__version__}) - {ts}")
    lines.append("")

    for r in results or []:
        block: list[str] = []
        block.append(f"=== {r.get('label','Disc')} ===")
        block.append(f"Path: {r.get('input_path','')}")
        if r.get("product"):
            block.append(f"Product: {r.get('product')}")
        block.append(f"Result: {r.get('severity','?')} - {r.get('summary','')}")

        errs = list(r.get("errors") or [])
        warns = list(r.get("warnings") or [])

        if errs:
            block.append("Errors:")
            for it in errs:
                msg = str(it.get("message") or "")
                fix = str(it.get("fix") or "")
                block.append(f" - {msg}")
                block.append(f"   Fix: {fix}")

        if warns:
            block.append("Warnings:")
            for it in warns:
                msg = str(it.get("message") or "")
                fix = str(it.get("fix") or "")
                block.append(f" - {msg}")
                block.append(f"   Fix: {fix}")

        try:
            counts = dict(r.get("counts") or {})
            covers = dict(r.get("covers") or {})
            block.append(
                f"Info: songs_xml={counts.get('songs_xml_files',0)}, banks={counts.get('banks_from_songs_xml',0)}, textures={counts.get('texture_pages',0)}, missing_refs={len(r.get('missing_refs') or [])}, missing_cover_pages={covers.get('missing_pages',0)}"
            )
        except Exception:
            pass

        block.append("")
        lines.extend(block)

    return "\n".join(lines).rstrip() + "\n"


def validate_discs(
    targets: Sequence[Tuple[str, str]],
    *,
    log_cb: Optional[Callable[[str], None]] = None,
    cancel_token: Optional[CancelToken] = None,
) -> tuple[list[dict], str]:
    """Validate multiple discs by (label, input_path).

    Returns (results, report_text). If log_cb is provided, it is called with
    per-disc report block lines as they are generated (no timestamps).
    """
    results: list[dict] = []
    for label, pth in targets or []:
        if cancel_token is not None:
            cancel_token.raise_if_cancelled()
        r = validate_one_disc(str(label), str(pth))
        results.append(r)

        # Stream a copyable report block (no timestamps) to log_cb
        if log_cb is not None:
            block: list[str] = []
            block.append(f"=== {r.get('label','Disc')} ===")
            block.append(f"Path: {r.get('input_path','')}")
            if r.get("product"):
                block.append(f"Product: {r.get('product')}")
            block.append(f"Result: {r.get('severity','?')} - {r.get('summary','')}")
            errs = list(r.get("errors") or [])
            warns = list(r.get("warnings") or [])
            if errs:
                block.append("Errors:")
                for it in errs:
                    msg = str(it.get("message") or "")
                    fix = str(it.get("fix") or "")
                    block.append(f" - {msg}")
                    block.append(f"   Fix: {fix}")
            if warns:
                block.append("Warnings:")
                for it in warns:
                    msg = str(it.get("message") or "")
                    fix = str(it.get("fix") or "")
                    block.append(f" - {msg}")
                    block.append(f"   Fix: {fix}")
            try:
                counts = dict(r.get("counts") or {})
                covers = dict(r.get("covers") or {})
                block.append(
                    f"Info: songs_xml={counts.get('songs_xml_files',0)}, banks={counts.get('banks_from_songs_xml',0)}, textures={counts.get('texture_pages',0)}, missing_refs={len(r.get('missing_refs') or [])}, missing_cover_pages={covers.get('missing_pages',0)}"
                )
            except Exception:
                pass
            block.append("")
            for line in block:
                try:
                    log_cb(str(line).rstrip())
                except Exception:
                    pass

    report_text = format_validate_report(results, preflight=False)
    return results, report_text


# --- PKD extraction operations (Block D / 0.5.10a5) ---

def sanitize_console_line(s: str) -> str:
    """Remove control chars / ANSI escapes and replacement glyphs that can show up as �.

    This is UI-agnostic and helps keep logs readable in both Tk and Qt.
    """
    try:
        # Strip ANSI escape sequences
        s = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", s)
        s = re.sub(r"\x1b\][^\x07]*\x07", "", s)  # OSC ... BEL
    except Exception:
        pass
    # Remove common replacement glyphs
    s = s.replace("\ufffd", "").replace("�", "")
    # Drop control characters except tab
    cleaned: list[str] = []
    for ch in s:
        o = ord(ch)
        if ch == "\t":
            cleaned.append(ch)
        elif o < 32:
            continue
        else:
            cleaned.append(ch)
    return "".join(cleaned).strip()


def _decode_bytes(b: bytes, enc_candidates: Sequence[str]) -> str:
    for enc in enc_candidates:
        try:
            return b.decode(enc)
        except Exception:
            continue
    return b.decode("cp1252", errors="replace")


def _locate_ps3_usrdir_under(root: Path, *, max_depth: int = 4) -> Optional[Path]:
    """Best-effort locate a PS3_GAME/USRDIR directory under a user-provided root.

    Users sometimes point the app at a wrapper folder that contains the real disc folder.
    We search a few levels deep (bounded by max_depth) for PS3_GAME/USRDIR.
    """
    root = Path(root).expanduser()
    try:
        root = root.resolve()
    except Exception:
        pass

    direct = root / "PS3_GAME" / "USRDIR"
    if direct.is_dir():
        return direct

    try:
        base = root
        for dirpath, dirnames, _filenames in os.walk(str(root)):
            try:
                depth = len(Path(dirpath).resolve().relative_to(base).parts)
            except Exception:
                depth = 0
            if depth > max_depth:
                dirnames[:] = []
                continue

            # Prune obvious irrelevant trees.
            try:
                for dn in list(dirnames):
                    if dn.lower() in {"_spcdb_trash", ".git", "__pycache__"}:
                        dirnames.remove(dn)
            except Exception:
                pass

            pth = Path(dirpath)
            try:
                if pth.name.upper() == "PS3_GAME":
                    # Prefer an exact "USRDIR" child if present.
                    u = pth / "USRDIR"
                    if u.is_dir():
                        return u
                    # Case-variant child (rare, but safe)
                    for dn in list(dirnames):
                        if str(dn).upper() == "USRDIR":
                            cand = pth / dn
                            if cand.is_dir():
                                return cand
            except Exception:
                continue
    except Exception:
        return None

    return None


def extract_disc_pkds(
    extractor_exe: Path,
    disc_root: Path,
    log_cb: Callable[[str], None],
    *,
    cancel_token: Optional[CancelToken] = None,
    allow_mid_disc_cancel: bool = False,
    stats_out: Optional[dict] = None,
) -> tuple[Path, int]:
    """Extract all Pack*.pkd files for a disc using the external extractor and harvest Export.

    Returns (dest_export_path, harvested_file_count).

    Cancellation: by default, this does NOT interrupt an in-flight disc extraction (matches GUI semantics).
    If allow_mid_disc_cancel is True and cancel_token is provided, cancellation is checked between PKDs
    and during harvest loops (best-effort).
    """
    st: Optional[dict] = stats_out if isinstance(stats_out, dict) else None

    def _st_set(key: str, val) -> None:
        if st is None:
            return
        try:
            st[key] = val
        except Exception:
            pass

    def _st_inc(key: str, n: int = 1) -> None:
        if st is None:
            return
        try:
            st[key] = int(st.get(key, 0) or 0) + int(n)
        except Exception:
            pass

    def _st_append(key: str, item) -> None:
        if st is None:
            return
        try:
            arr = st.get(key)
            if not isinstance(arr, list):
                arr = []
                st[key] = arr
            arr.append(item)
        except Exception:
            pass

    if st is not None:
        try:
            st.clear()
        except Exception:
            pass
        # Stable keys for UI/logging
        _st_set("pkds_found", 0)
        _st_set("pkds_to_extract", 0)
        _st_set("pkds_skipped", 0)
        _st_set("pkd_out_incomplete", 0)
        _st_set("pkd_out_moved_aside", 0)
        _st_set("pkd_out_moved_aside_samples", [])
        _st_set("harvested", 0)
        _st_set("dest_export", "")
        _st_set("has_config_xml", False)

    exe_p = Path(extractor_exe)
    if not str(exe_p).strip():
        raise RuntimeError("Extractor not set. Please select scee_london (or scee_london.exe) first.")
    if not exe_p.exists():
        raise RuntimeError(f"Extractor exe not found: {exe_p}")

    # On Linux/macOS, the extractor is typically a no-suffix binary and must be executable.
    if os.name != "nt":
        try:
            if not os.access(str(exe_p), os.X_OK):
                raise RuntimeError(
                    f"Extractor is not executable: {exe_p}\n\n"
                    "Linux/macOS: run `chmod +x scee_london` (or on the file you selected).\n"
                    "macOS may also require: `xattr -d com.apple.quarantine scee_london`\n"
                )
        except RuntimeError:
            raise
        except Exception:
            # If we can't check permissions, proceed and let subprocess raise.
            pass

    # Resolve the actual disc root + USRDIR.
    # IMPORTANT: Extraction MUST look under PS3_GAME/USRDIR (not the top-level root).
    disc_root = Path(disc_root).expanduser()
    try:
        disc_root = disc_root.resolve()
    except Exception:
        pass

    usrdir = disc_root / "PS3_GAME" / "USRDIR"
    if not usrdir.is_dir():
        found_usrdir = _locate_ps3_usrdir_under(disc_root, max_depth=4)
        if found_usrdir is not None:
            usrdir = Path(found_usrdir)
            # Canonical disc root is parent of PS3_GAME.
            try:
                disc_root = usrdir.parent.parent
            except Exception:
                pass

    if not usrdir.is_dir():
        raise RuntimeError(
            f"PS3_GAME/USRDIR not found under: {disc_root}\n\n"
            "Tip: the disc folder you add should contain PS3_GAME at its top level."
        )

    # Find Pack*.pkd files (case-insensitive) under USRDIR.
    pkds: list[Path] = []
    try:
        # Fast path: scan immediate children of USRDIR.
        for cand in usrdir.iterdir():
            try:
                if not cand.is_file():
                    continue
                nl = cand.name.lower()
                if nl.startswith("pack") and nl.endswith(".pkd"):
                    pkds.append(cand)
            except Exception:
                continue
    except Exception:
        pkds = []

    # If not directly under USRDIR, search a little deeper but stop at the first folder that contains Pack*.pkd.
    if not pkds:
        try:
            for cur, dirnames, filenames in os.walk(str(usrdir)):
                if allow_mid_disc_cancel and cancel_token is not None:
                    cancel_token.raise_if_cancelled("Cancelled")
                # Prune irrelevant/huge trees within USRDIR.
                try:
                    for dn in list(dirnames):
                        if dn.lower() in {"_spcdb_trash", ".git", "filesystem", "export", "__pycache__"}:
                            dirnames.remove(dn)
                except Exception:
                    pass

                hits: list[Path] = []
                for fn in list(filenames or []):
                    f = str(fn)
                    fl = f.lower()
                    if fl.startswith("pack") and fl.endswith(".pkd"):
                        hits.append(Path(cur) / f)
                if hits:
                    # Collect all Pack*.pkd in this folder and stop walking deeper.
                    pkds.extend(sorted(hits, key=lambda p: str(p).lower()))
                    break
        except Exception:
            pass

    # De-dupe (defensive: prevents duplicate extraction if paths repeat for any reason).
    try:
        uniq: dict[str, Path] = {}
        for pp in pkds:
            try:
                key = str(pp.resolve())
            except Exception:
                key = str(pp)
            uniq[key.lower()] = pp
        pkds = sorted(uniq.values(), key=lambda p: str(p).lower())
    except Exception:
        # Best-effort
        pkds = list(dict.fromkeys(pkds))

    if not pkds:
        raise RuntimeError(f"No Pack*.pkd files found under: {usrdir} (disc root: {disc_root})")

    try:
        log_cb(f"Using extractor: {exe_p}")
        log_cb(f"Disc root: {disc_root}")
        log_cb(f"USRDIR: {usrdir}")
        log_cb(f"Found {len(pkds)} PKD file(s)")
    except Exception:
        pass

    # Prefer OEM/locale encodings before UTF-8 to avoid replacement glyphs.
    enc_candidates: list[str] = []
    try:
        enc_candidates.append(locale.getpreferredencoding(False))
        enc_candidates.extend(["cp850", "cp437", "cp1252", "utf-8"])
    except Exception:
        enc_candidates = ["cp850", "cp437", "cp1252", "utf-8"]
    # Decide which PKDs actually need extraction.
    pkds_sorted = sorted(pkds, key=lambda p: str(p).lower())
    pkds_to_extract: list[Path] = []
    skipped_pkds: list[tuple[Path, Path]] = []

    def _looks_like_extractor_output(out_dir: Path) -> bool:
        """Heuristic: a successful extractor run produces a non-empty *_out folder
        containing FileSystem/filesystem, typically with filesystem/export."""
        try:
            if not out_dir.is_dir():
                return False
            # Must not be empty
            try:
                if not any(out_dir.iterdir()):
                    return False
            except Exception:
                # If we cannot list it, treat as incomplete
                return False
            fs1 = out_dir / "filesystem"
            fs2 = out_dir / "FileSystem"
            if not fs1.is_dir() and not fs2.is_dir():
                return False
            # Require an export dir under filesystem/FileSystem
            for cand in (
                fs1 / "export",
                fs1 / "Export",
                fs2 / "export",
                fs2 / "Export",
            ):
                try:
                    if cand.is_dir():
                        return True
                except Exception:
                    continue
            return False
        except Exception:
            return False

    def _move_aside_incomplete_out(out_dir: Path) -> Optional[Path]:
        """Rename a partial pkd_out folder aside to avoid future false 'already extracted' skips."""
        try:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        except Exception:
            ts = "unknown"
        base = out_dir.with_name(out_dir.name + f"_incomplete_{ts}")
        target = base
        for i in range(50):
            try:
                if not target.exists():
                    break
            except Exception:
                break
            target = Path(str(base) + f"_{i+1}")
        try:
            out_dir.rename(target)
            return target
        except Exception:
            return None

    try:
        _st_set("pkds_found", int(len(pkds_sorted)))
    except Exception:
        pass

    for pkd in pkds_sorted:
        try:
            out_dir = pkd.with_name(pkd.name + "_out")
        except Exception:
            out_dir = Path(str(pkd) + "_out")
        try:
            if out_dir.is_dir():
                if _looks_like_extractor_output(out_dir):
                    skipped_pkds.append((pkd, out_dir))
                else:
                    _st_inc("pkd_out_incomplete", 1)
                    moved_path = _move_aside_incomplete_out(out_dir)
                    if moved_path is not None:
                        _st_inc("pkd_out_moved_aside", 1)
                        _st_append("pkd_out_moved_aside_samples", (str(out_dir), str(moved_path)))
                    pkds_to_extract.append(pkd)
            else:
                pkds_to_extract.append(pkd)
        except Exception:
            pkds_to_extract.append(pkd)

    try:
        _st_set("pkds_to_extract", int(len(pkds_to_extract)))
        _st_set("pkds_skipped", int(len(skipped_pkds)))
    except Exception:
        pass

    try:
        if skipped_pkds:
            for pkd, out_dir in skipped_pkds:
                log_cb(f"Skipping already extracted: {pkd.name} (found {out_dir.name})")
        if st is not None:
            try:
                inc = int(st.get("pkd_out_incomplete", 0) or 0)
                moved_count = int(st.get("pkd_out_moved_aside", 0) or 0)
                if inc:
                    log_cb(f"Found {inc} incomplete pkd_out folder(s); will re-extract those PKD(s).")
                if moved_count:
                    log_cb(f"Moved aside {moved_count} incomplete pkd_out folder(s) (suffix _incomplete_*).")
            except Exception:
                pass
        log_cb(f"Will extract {len(pkds_to_extract)} PKD(s) (skipping {len(skipped_pkds)} already extracted).")
        if not pkds_to_extract:
            log_cb("All PKD(s) already extracted; skipping extractor step.")
    except Exception:
        pass


    # Run extractor for each pkd; output is Pack*.pkd_out alongside the pkd.
    for i, pkd in enumerate(pkds_to_extract, start=1):
        if allow_mid_disc_cancel and cancel_token is not None:
            cancel_token.raise_if_cancelled("Cancelled")

        try:
            log_cb(f"Extracting ({i}/{len(pkds_to_extract)}): {pkd.name}")
        except Exception:
            pass

        creationflags = 0
        try:
            if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW"):
                creationflags = subprocess.CREATE_NO_WINDOW
        except Exception:
            creationflags = 0

        proc = subprocess.Popen(
            [str(exe_p), str(pkd)],
            cwd=str(pkd.parent),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            creationflags=creationflags,
        )
        assert proc.stdout is not None

        last_lines: list[str] = []

        # Read extractor output in a background thread so we can poll for cancellation
        # even while the child process is still running.
        import queue
        import threading

        q: queue.Queue[bytes | None] = queue.Queue()

        def _reader() -> None:
            try:
                while True:
                    b = proc.stdout.readline()
                    if not b:
                        break
                    q.put(b)
            except Exception:
                pass
            finally:
                try:
                    q.put(None)
                except Exception:
                    pass

        t_reader = threading.Thread(target=_reader, name='spcdb_extractor_reader', daemon=True)
        t_reader.start()

        cancelled_here = False
        while True:
            if allow_mid_disc_cancel and cancel_token is not None and cancel_token.cancelled():
                if not cancelled_here:
                    cancelled_here = True
                    try:
                        log_cb('Cancelled: terminating extractor process...')
                    except Exception:
                        pass
                    try:
                        proc.terminate()
                    except Exception:
                        pass

            try:
                item = q.get(timeout=0.10)
            except queue.Empty:
                # If process ended and no more output is queued, we're done.
                if proc.poll() is not None and q.empty():
                    break
                continue

            if item is None:
                break

            line = sanitize_console_line(_decode_bytes(item, enc_candidates))
            if not line:
                continue
            last_lines.append(line)
            if len(last_lines) > 200:
                last_lines = last_lines[-200:]
            try:
                log_cb(line)
            except Exception:
                pass

        # Wait for process exit (best-effort) then honour cancellation.
        try:
            if cancelled_here:
                rc = proc.wait(timeout=3)
            else:
                rc = proc.wait()
        except Exception:
            try:
                rc = proc.wait()
            except Exception:
                rc = -1

        if cancelled_here:
            try:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait(timeout=2)
            except Exception:
                pass
            raise CancelledError('Cancelled')

        if rc != 0:
            tail = "\n".join(last_lines[-40:])
            raise RuntimeError(f"Extractor failed for {pkd.name} (code {rc})\n\n{tail}")

    # Harvest export folders from Pack*.pkd_out/filesystem/export into PS3_GAME/USRDIR/FileSystem/Export
    dest_export = disc_root / "PS3_GAME" / "USRDIR" / "FileSystem" / "Export"
    dest_export.mkdir(parents=True, exist_ok=True)

    out_dirs: list[Path] = []
    try:
        for pkd in pkds_sorted:
            try:
                od = pkd.with_name(pkd.name + "_out")
            except Exception:
                od = Path(str(pkd) + "_out")
            try:
                if od.is_dir():
                    out_dirs.append(od)
            except Exception:
                continue
    except Exception:
        out_dirs = []

    # Fallback: case-insensitive search under USRDIR (avoid crawling huge Export trees).
    if not out_dirs:
        try:
            for cur, dirnames, _filenames in os.walk(str(usrdir)):
                if allow_mid_disc_cancel and cancel_token is not None:
                    cancel_token.raise_if_cancelled("Cancelled")
                # Prune known-huge/irrelevant trees
                try:
                    for dn in list(dirnames):
                        if dn.lower() in {"_spcdb_trash", ".git", "filesystem", "export", "__pycache__"}:
                            dirnames.remove(dn)
                except Exception:
                    pass
                for dn in list(dirnames):
                    dnl = dn.lower()
                    if dnl.startswith("pack") and dnl.endswith(".pkd_out"):
                        out_dirs.append(Path(cur) / dn)
        except Exception:
            pass

    if not out_dirs:
        raise RuntimeError(f"No Pack*.pkd_out folders found under: {disc_root}")


    harvested = 0
    for od in sorted(set(out_dirs)):
        if allow_mid_disc_cancel and cancel_token is not None:
            cancel_token.raise_if_cancelled("Cancelled")

        # find filesystem/export in a case-insensitive way (fast, depth-limited)
        fs_dir: Optional[Path] = None
        for cand in (
            od / 'filesystem' / 'export',
            od / 'filesystem' / 'Export',
            od / 'FileSystem' / 'export',
            od / 'FileSystem' / 'Export',
        ):
            try:
                if cand.is_dir():
                    fs_dir = cand
                    break
            except Exception:
                continue

        if fs_dir is None:
            # Depth-limited walk: look for a 'filesystem' dir and then an 'export' child.
            try:
                base = od
                for cur, dirnames, _filenames in os.walk(str(base)):
                    if allow_mid_disc_cancel and cancel_token is not None:
                        cancel_token.raise_if_cancelled('Cancelled')

                    try:
                        depth = len(Path(cur).resolve().relative_to(base).parts)
                    except Exception:
                        depth = 0
                    if depth > 3:
                        dirnames[:] = []
                        continue

                    # Prune irrelevant/large trees.
                    try:
                        for dn in list(dirnames):
                            dnl = str(dn).lower()
                            if dnl in {'_spcdb_trash', '.git', '__pycache__', 'export'} or dnl.endswith('.pkd_out'):
                                dirnames.remove(dn)
                    except Exception:
                        pass

                    pcur = Path(cur)
                    if pcur.name.lower() == 'filesystem':
                        for exn in ('export', 'Export'):
                            cand = pcur / exn
                            try:
                                if cand.is_dir():
                                    fs_dir = cand
                                    break
                            except Exception:
                                continue
                    if fs_dir is not None:
                        break
            except Exception:
                fs_dir = None

        if fs_dir is None:
            continue


        try:
            log_cb(f"Harvesting: {fs_dir} -> {dest_export}")
        except Exception:
            pass

        # merge copy (os.walk is faster than Path.rglob)
        copied = 0
        for dirpath, dirnames, filenames in os.walk(str(fs_dir)):
            if allow_mid_disc_cancel and cancel_token is not None:
                cancel_token.raise_if_cancelled('Cancelled')

            src_dir = Path(dirpath)
            try:
                rel_dir = src_dir.relative_to(fs_dir)
            except Exception:
                rel_dir = Path('.')

            dst_dir = dest_export / rel_dir
            try:
                dst_dir.mkdir(parents=True, exist_ok=True)
            except Exception:
                pass

            # Prune nothing here: we want the whole export tree.
            for fn in list(filenames or []):
                if allow_mid_disc_cancel and cancel_token is not None:
                    cancel_token.raise_if_cancelled('Cancelled')

                src = src_dir / fn
                dst = dst_dir / fn

                # Count the file as "harvested" even if it already exists at the destination.
                harvested += 1

                try:
                    if dst.exists():
                        try:
                            if src.stat().st_size == dst.stat().st_size:
                                # If size matches, skip copy (content is almost certainly identical for extractor outputs).
                                continue
                        except Exception:
                            pass
                except Exception:
                    pass

                try:
                    shutil.copy2(src, dst)
                    copied += 1
                except Exception:
                    # Best-effort: keep going to harvest what we can.
                    continue

        try:
            if copied:
                log_cb(f'Harvested {harvested} file(s) ({copied} copied) into {dest_export}')
        except Exception:
            pass


    if harvested == 0:
        raise RuntimeError("No files harvested from pkd_out filesystem/export folders.")

    try:
        log_cb(f"Harvested {harvested} file(s) into {dest_export}")
    except Exception:
        pass

    try:
        _st_set("harvested", int(harvested))
        _st_set("dest_export", str(dest_export))
        _st_set("has_config_xml", bool((dest_export / "config.xml").is_file()))
    except Exception:
        pass

    if not (dest_export / "config.xml").exists():
        try:
            log_cb("Warning: Export/config.xml not found after harvest. Check extractor output.")
        except Exception:
            pass

    return dest_export, harvested




def _find_extraction_artifacts(disc_root: Path) -> dict:
    """Find legacy extraction artifacts (Pack*.pkd and Pack*.pkd_out).

    Returns a dict with lists of absolute paths:
      { "pkd_files": [..], "pkd_out_dirs": [..] }
    """
    disc_root = Path(disc_root)
    pkd_files: list[str] = []
    pkd_out_dirs: list[str] = []

    usrdir = disc_root / "PS3_GAME" / "USRDIR"

    # Pack*.pkd files (prefer USRDIR)
    for d in (usrdir, disc_root):
        try:
            if not d.exists():
                continue
            for pat in ("Pack*.pkd", "pack*.pkd", "PACK*.PKD", "pack*.PKD", "Pack*.PKD"):
                for p in d.glob(pat):
                    try:
                        if p.is_file():
                            pkd_files.append(str(p.resolve()))
                    except Exception:
                        continue
            if pkd_files:
                break
        except Exception:
            continue

    # Pack*.pkd_out dirs (anywhere under disc_root)
    #
    # IMPORTANT: Avoid crawling huge Export trees (PS3_GAME/USRDIR/FileSystem/Export),
    # because this is often very large and unrelated to pkd_out discovery.
    # pkd_out folders are usually alongside Pack*.pkd files, so we can safely prune.
    try:
        for cur, dirnames, _filenames in os.walk(str(disc_root)):
            # Prune known-huge / irrelevant trees early.
            try:
                for dn in list(dirnames):
                    dnl = dn.lower()
                    if dnl in {"_spcdb_trash", ".git", "filesystem", "export"}:
                        dirnames.remove(dn)
            except Exception:
                pass

            # Detect pkd_out folders at this level and avoid walking inside them.
            try:
                for dn in list(dirnames):
                    dnl = dn.lower()
                    if dnl.startswith("pack") and dnl.endswith(".pkd_out"):
                        try:
                            pkd_out_dirs.append(str((Path(cur) / dn).resolve()))
                        except Exception:
                            pkd_out_dirs.append(str(Path(cur) / dn))
                        try:
                            dirnames.remove(dn)
                        except Exception:
                            pass
            except Exception:
                pass
    except Exception:
        pass

    # De-dupe, stable order
    try:
        pkd_files = sorted(set(pkd_files), key=lambda s: s.lower())
    except Exception:
        pkd_files = list(dict.fromkeys(pkd_files))
    try:
        pkd_out_dirs = sorted(set(pkd_out_dirs), key=lambda s: s.lower())
    except Exception:
        pkd_out_dirs = list(dict.fromkeys(pkd_out_dirs))

    return {"pkd_files": pkd_files, "pkd_out_dirs": pkd_out_dirs}


def _find_media_file(song_dir: Path, stem: str) -> Optional[Path]:
    """Return a candidate media file for a song folder.

    We prefer <stem>.mp4, but accept common case variants and .m4v.
    """
    try:
        song_dir = Path(song_dir)
    except Exception:
        return None

    # Fast exact hits
    for ext in ("mp4", "m4v"):
        cand = song_dir / f"{stem}.{ext}"
        if cand.exists() and cand.is_file():
            return cand

    # Case-insensitive scan (cross-platform safe)
    want = {f"{stem}.mp4", f"{stem}.m4v"}
    want_l = {w.lower() for w in want}
    try:
        for ch in song_dir.iterdir():
            if not ch.is_file():
                continue
            if ch.name.lower() in want_l:
                return ch
    except Exception:
        pass
    return None


def _is_probably_valid_mp4(path: Path, *, min_bytes: int = 1024) -> tuple[bool, str]:
    """Fast, dependency-free MP4 sanity check.

    This does NOT guarantee the file is fully decodable, but it catches common
    extraction failures (missing/zero-byte/truncated/garbled files) without
    running ffprobe.

    Checks:
      - exists + size >= min_bytes
      - 'ftyp' marker in the first ~1KB
      - 'moov' or 'mdat' marker in head/tail windows
    """
    try:
        path = Path(path)
        st = path.stat()
        sz = int(getattr(st, 'st_size', 0) or 0)
        if sz < int(min_bytes):
            return False, f"too small ({sz} bytes)"

        head = b""
        tail = b""
        try:
            with path.open('rb') as f:
                head = f.read(65536)
                # Tail window: last 256KB (or whole file)
                try:
                    win = 262144
                    if sz > win:
                        f.seek(max(0, sz - win))
                        tail = f.read(win)
                    else:
                        tail = head
                except Exception:
                    tail = b""
        except Exception as e:
            return False, f"read failed: {e}"

        if b'ftyp' not in head[:2048]:
            return False, "missing ftyp marker"

        # MP4s should contain at least one of these box type markers.
        if (b'moov' not in head and b'moov' not in tail) and (b'mdat' not in head and b'mdat' not in tail):
            return False, "missing moov/mdat markers"

        return True, ""
    except Exception as e:
        return False, str(e)


def _scan_missing_or_corrupt_media(
    export_root: Path,
    song_ids: set[int],
    *,
    min_preview_bytes: int = 1024,
    min_video_bytes: int = 1024,
) -> dict:
    """Return missing/corrupt preview/video info for a set of song IDs."""
    missing_preview: list[int] = []
    missing_video: list[int] = []
    corrupt_preview: dict[int, str] = {}
    corrupt_video: dict[int, str] = {}

    for sid in sorted(song_ids or set()):
        try:
            song_dir = Path(export_root) / str(int(sid))
        except Exception:
            continue
        if not song_dir.is_dir():
            continue

        pv = _find_media_file(song_dir, 'preview')
        vd = _find_media_file(song_dir, 'video')

        if pv is None:
            missing_preview.append(int(sid))
        else:
            ok, reason = _is_probably_valid_mp4(pv, min_bytes=int(min_preview_bytes))
            if not ok:
                corrupt_preview[int(sid)] = str(reason)

        if vd is None:
            missing_video.append(int(sid))
        else:
            ok, reason = _is_probably_valid_mp4(vd, min_bytes=int(min_video_bytes))
            if not ok:
                corrupt_video[int(sid)] = str(reason)

    any_bad = sorted(set(missing_preview + missing_video + list(corrupt_preview.keys()) + list(corrupt_video.keys())))

    return {
        'missing_preview_ids': [int(x) for x in missing_preview],
        'missing_video_ids': [int(x) for x in missing_video],
        'corrupt_preview': {int(k): str(v) for k, v in corrupt_preview.items()},
        'corrupt_video': {int(k): str(v) for k, v in corrupt_video.items()},
        'any_bad_ids': [int(x) for x in any_bad],
    }


def verify_disc_extraction(
    disc_root: Path,
    *,
    log_cb: Optional[Callable[[str], None]] = None,
) -> dict:
    """Verify a disc looks correctly extracted (safe to cleanup PKD artifacts).

    This is intentionally UI-agnostic and relatively fast:
      - resolves Export root
      - ensures songs/acts XMLs exist and are parseable
      - ensures each SONG ID has a corresponding Export/<id>/ folder
      - ensures cover texture pages referenced by covers.xml exist

    Returns a dict with:
      ok: bool
      warnings: list[str]
      errors: list[str]
      counts: { songs, missing_song_dirs, missing_cover_entries, missing_texture_pages }
      artifacts: { pkd_files, pkd_out_dirs }
    """

    def _emit(msg: str) -> None:
        try:
            if log_cb is not None:
                log_cb(str(msg))
        except Exception:
            pass

    errors: list[str] = []
    warnings: list[str] = []

    disc_root = Path(disc_root).expanduser()
    try:
        disc_root = disc_root.resolve()
    except Exception:
        pass

    try:
        idx = index_disc(str(disc_root))
    except Exception as e:
        errors.append(f"Index failed: {e}")
        return {
            "ok": False,
            "warnings": warnings,
            "errors": errors,
            "counts": {},
            "artifacts": _find_extraction_artifacts(disc_root),
        }

    warnings.extend(list(getattr(idx, "warnings", []) or []))

    export_root = Path(getattr(idx, "export_root", "") or "")
    if not str(export_root).strip() or not export_root.exists():
        errors.append("Export root not found (disc does not appear extracted).")
        return {
            "ok": False,
            "warnings": warnings,
            "errors": errors,
            "counts": {},
            "artifacts": _find_extraction_artifacts(disc_root),
        }

    songs_xml_s = str(getattr(idx, "songs_xml", "") or "")
    acts_xml_s = str(getattr(idx, "acts_xml", "") or "")
    if not songs_xml_s:
        errors.append("songs XML not found (songs_<bank>_0.xml missing).")
    if not acts_xml_s:
        errors.append("acts XML not found (acts_<bank>_0.xml missing).")

    song_ids: set[int] = set()
    if songs_xml_s:
        songs_xml = Path(songs_xml_s)
        if not songs_xml.exists():
            errors.append(f"songs XML file missing: {songs_xml}")
        else:
            try:
                for _ev, el in ET.iterparse(str(songs_xml), events=("end",)):
                    if _strip_ns(el.tag) != "SONG":
                        continue
                    sid = _parse_song_id(el)
                    if sid is not None:
                        song_ids.add(int(sid))
                    el.clear()
            except ET.ParseError as e:
                errors.append(f"songs XML parse failed: {e}")
            except Exception as e:
                errors.append(f"songs XML read failed: {e}")

    missing_song_dirs: list[int] = []
    if song_ids:
        for sid in sorted(song_ids):
            try:
                if not (export_root / str(int(sid))).is_dir():
                    missing_song_dirs.append(int(sid))
            except Exception:
                missing_song_dirs.append(int(sid))

    # Media verification (preview/video) - catch incomplete/corrupt extractions
    media = {
        'missing_preview_ids': [],
        'missing_video_ids': [],
        'corrupt_preview': {},
        'corrupt_video': {},
        'any_bad_ids': [],
    }
    try:
        if song_ids:
            media = _scan_missing_or_corrupt_media(
                export_root,
                song_ids,
                min_preview_bytes=1024,
                min_video_bytes=1024,
            )
    except Exception:
        pass

    missing_preview_ids = list(media.get('missing_preview_ids') or [])
    missing_video_ids = list(media.get('missing_video_ids') or [])
    corrupt_preview = dict(media.get('corrupt_preview') or {})
    corrupt_video = dict(media.get('corrupt_video') or {})

    _emit(
        f"[verify] Media: missing_preview={len(missing_preview_ids)} missing_video={len(missing_video_ids)} "
        f"corrupt_preview={len(corrupt_preview)} corrupt_video={len(corrupt_video)}"
    )


    # Covers / textures verification
    missing_cover_entries = 0
    missing_texture_pages: set[int] = set()
    try:
        covers_map = _covers_song_to_page(export_root)
    except Exception:
        covers_map = {}

    if song_ids:
        for sid in song_ids:
            if int(sid) not in covers_map:
                missing_cover_entries += 1

    textures_dir = export_root / "textures"
    if not textures_dir.exists():
        textures_dir = export_root / "Textures"

    for _sid, page in (covers_map or {}).items():
        try:
            if not _texture_page_exists(textures_dir, int(page)):
                missing_texture_pages.add(int(page))
        except Exception:
            missing_texture_pages.add(int(page))

    # Summaries
    _emit(f"[verify] Export root: {export_root}")
    _emit(f"[verify] Songs: {len(song_ids)} | Missing song folders: {len(missing_song_dirs)}")
    _emit(
        f"[verify] Covers missing for songs: {missing_cover_entries} | Missing texture pages: {len(missing_texture_pages)}"
    )

    ok = True
    if errors:
        ok = False
    if missing_song_dirs:
        ok = False
        warnings.append(f"Missing Export/<song_id> folders: {len(missing_song_dirs)}")
    if missing_texture_pages:
        ok = False
        warnings.append(f"Missing cover texture pages: {len(missing_texture_pages)}")

    if missing_preview_ids or missing_video_ids or corrupt_preview or corrupt_video:
        ok = False
        if missing_preview_ids:
            warnings.append(f"Missing preview media files: {len(missing_preview_ids)}")
        if missing_video_ids:
            warnings.append(f"Missing video media files: {len(missing_video_ids)}")
        if corrupt_preview:
            warnings.append(f"Corrupt/unreadable preview media files: {len(corrupt_preview)}")
        if corrupt_video:
            warnings.append(f"Corrupt/unreadable video media files: {len(corrupt_video)}")

    return {
        "ok": bool(ok),
        "warnings": warnings,
        "errors": errors,
        "counts": {
            "songs": int(len(song_ids)),
            "missing_song_dirs": int(len(missing_song_dirs)),
            "missing_cover_entries": int(missing_cover_entries),
            "missing_texture_pages": int(len(missing_texture_pages)),
            "missing_preview_files": int(len(missing_preview_ids)),
            "missing_video_files": int(len(missing_video_ids)),
            "corrupt_preview_files": int(len(corrupt_preview)),
            "corrupt_video_files": int(len(corrupt_video)),
        },
        "samples": {
            "missing_song_dir_ids": [int(x) for x in missing_song_dirs[:20]],
            "missing_texture_pages": [int(x) for x in sorted(missing_texture_pages)[:20]],
            "missing_preview_ids": [int(x) for x in missing_preview_ids[:20]],
            "missing_video_ids": [int(x) for x in missing_video_ids[:20]],
            "corrupt_preview_ids": [int(x) for x in sorted(corrupt_preview.keys())[:20]],
            "corrupt_video_ids": [int(x) for x in sorted(corrupt_video.keys())[:20]],
            "corrupt_preview_samples": {int(k): str(corrupt_preview[k]) for k in list(sorted(corrupt_preview.keys()))[:10]},
            "corrupt_video_samples": {int(k): str(corrupt_video[k]) for k in list(sorted(corrupt_video.keys()))[:10]},
        },
        "artifacts": _find_extraction_artifacts(disc_root),
    }


def cleanup_extraction_artifacts(
    disc_root: Path,
    *,
    include_pkd_out_dirs: bool = True,
    include_pkd_files: bool = False,
    delete_instead: bool = False,
    trash_root_dir: Optional[Path] = None,
    trash_ts: Optional[str] = None,
    log_cb: Optional[Callable[[str], None]] = None,
) -> dict:
    """Cleanup legacy extraction artifacts (destructive).

    By default, this removes artifacts from the disc folder by MOVING them into a sibling
    trash folder under the disc *parent* (typically the scanned "discs folder"):

      <discs_folder>/_spcdb_trash/<timestamp>/<disc_folder_name>/

    If delete_instead=True, artifacts are PERMANENTLY DELETED (cannot be undone).

    Returns a dict including:
      - trash_dir (str|None)  # the session folder: <discs_folder>/_spcdb_trash/<timestamp>/
      - moved_files / moved_dirs
      - deleted_files / deleted_dirs
      - moved / deleted (list[str])
    """

    def _emit(msg: str) -> None:
        try:
            if log_cb is not None:
                log_cb(str(msg))
        except Exception:
            pass

    disc_root = Path(disc_root).expanduser()
    try:
        disc_root = disc_root.resolve()
    except Exception:
        pass

    artifacts = _find_extraction_artifacts(disc_root)
    pkd_files = list(artifacts.get("pkd_files", []) or [])
    pkd_out_dirs = list(artifacts.get("pkd_out_dirs", []) or [])

    candidates: list[Path] = []
    if include_pkd_out_dirs:
        candidates.extend([Path(p) for p in pkd_out_dirs])
    if include_pkd_files:
        candidates.extend([Path(p) for p in pkd_files])

    # Filter only items that still exist
    filtered: list[Path] = []
    for p in candidates:
        try:
            if p.exists():
                filtered.append(p)
        except Exception:
            continue

    if not filtered:
        return {
            "trash_dir": None,
            "moved_files": 0,
            "moved_dirs": 0,
            "deleted_files": 0,
            "deleted_dirs": 0,
            "moved": [],
            "deleted": [],
        }

    moved_files = 0
    moved_dirs = 0
    deleted_files = 0
    deleted_dirs = 0
    moved: list[str] = []
    deleted: list[str] = []

    if delete_instead:
        _emit("[cleanup] PERMANENT DELETE mode enabled")
        for src in filtered:
            try:
                if src.is_dir():
                    _emit(f"[cleanup] Deleting dir: {src}")
                    shutil.rmtree(str(src), ignore_errors=False)
                    deleted_dirs += 1
                    deleted.append(str(src))
                else:
                    _emit(f"[cleanup] Deleting file: {src}")
                    try:
                        src.unlink()
                    except Exception:
                        # Fallback for weird readonly situations
                        os.chmod(str(src), 0o666)
                        src.unlink()
                    deleted_files += 1
                    deleted.append(str(src))
            except Exception as e:
                _emit(f"[cleanup] ERROR deleting {src}: {e}")
                raise

        return {
            "trash_dir": None,
            "moved_files": 0,
            "moved_dirs": 0,
            "deleted_files": deleted_files,
            "deleted_dirs": deleted_dirs,
            "moved": [],
            "deleted": deleted,
        }

    # MOVE-to-trash mode (default)
    ts = str(trash_ts or datetime.now().strftime("%Y%m%d_%H%M%S"))

    # Place trash alongside disc folders (NOT inside an individual disc folder).
    # This avoids breaking extracted/unextracted layouts and keeps cleanup reversible.
    base_dir: Path
    if trash_root_dir is not None:
        base_dir = Path(trash_root_dir).expanduser()
        try:
            base_dir = base_dir.resolve()
        except Exception:
            pass
    else:
        base_dir = disc_root.parent

    trash_session_dir = base_dir / "_spcdb_trash" / ts
    trash_disc_dir = trash_session_dir / disc_root.name
    trash_disc_dir.mkdir(parents=True, exist_ok=True)

    for src in filtered:
        try:
            try:
                rel = src.relative_to(disc_root)
            except Exception:
                rel = Path(src.name)
            # Keep the disc folder name inside the trash session so multiple discs stay tidy.
            dst = trash_disc_dir / rel

            # Avoid collisions
            if dst.exists():
                stem = dst.name
                parent = dst.parent
                i = 2
                while True:
                    cand = parent / f"{stem}_{i}"
                    if not cand.exists():
                        dst = cand
                        break
                    i += 1

            dst.parent.mkdir(parents=True, exist_ok=True)
            _emit(f"[cleanup] Moving: {src} -> {dst}")
            shutil.move(str(src), str(dst))
            moved.append(str(dst))
            if dst.is_dir():
                moved_dirs += 1
            else:
                moved_files += 1
        except Exception as e:
            _emit(f"[cleanup] ERROR moving {src}: {e}")
            raise

    return {
        "trash_dir": str(trash_session_dir),
        "moved_files": moved_files,
        "moved_dirs": moved_dirs,
        "deleted_files": 0,
        "deleted_dirs": 0,
        "moved": moved,
        "deleted": [],
    }

def _compute_dedupe_stats(
    selected_song_ids: set[int],
    preferred_source_by_song_id: Dict[int, str],
    song_sources_by_id: Optional[Dict[int, Sequence[str]]],
) -> dict:
    """Compute simple dedupe stats for the selected song set.

    song_sources_by_id maps song_id -> iterable of source labels where the song exists.
    """
    stats: dict = {
        "selected_unique": int(len(selected_song_ids or set())),
        "songs_with_duplicates": 0,
        "extra_occurrences_hidden": 0,
        "dup_count_histogram": {},
        "winner_counts": {},
    }

    # Winner counts (always available)
    try:
        wc: Dict[str, int] = {}
        for sid in selected_song_ids or set():
            w = str((preferred_source_by_song_id or {}).get(int(sid), "Base") or "Base")
            wc[w] = int(wc.get(w, 0)) + 1
        stats["winner_counts"] = wc
    except Exception:
        pass

    if not song_sources_by_id:
        return stats

    try:
        songs_with_dups = 0
        extra = 0
        hist: Dict[str, int] = {}
        for sid in selected_song_ids or set():
            srcs = list(song_sources_by_id.get(int(sid), []) or [])
            try:
                srcs = list(dict.fromkeys([str(x) for x in srcs if str(x)]))
            except Exception:
                srcs = [str(x) for x in srcs if str(x)]
            k = int(len(srcs))
            if k > 1:
                songs_with_dups += 1
                extra += (k - 1)
            hist[str(k)] = int(hist.get(str(k), 0)) + 1

        stats["songs_with_duplicates"] = int(songs_with_dups)
        stats["extra_occurrences_hidden"] = int(extra)
        stats["dup_count_histogram"] = hist
    except Exception:
        pass

    return stats


# --- Song list verification (v0.9.191) ------------------------------------

def _norm_song_text(v: object) -> str:
    try:
        s = str(v or "")
    except Exception:
        return ""
    s = s.replace("\u00a0", " ")
    return " ".join(s.split()).strip()

def _coerce_expected_row(row: dict) -> Optional[dict]:
    """Normalise an expected-song row passed from the GUI."""
    try:
        sid = int(row.get("song_id"))
    except Exception:
        return None
    title = _norm_song_text(row.get("title"))
    artist = _norm_song_text(row.get("artist"))
    chosen = _norm_song_text(row.get("chosen_source") or "Base") or "Base"
    srcs = row.get("available_sources") or []
    try:
        srcs_list = [str(x) for x in (srcs or []) if str(x)]
    except Exception:
        srcs_list = []
    return {
        "song_id": sid,
        "title": title,
        "artist": artist,
        "chosen_source": chosen,
        "available_sources": srcs_list,
    }

def _write_csv_rows(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: ("" if r.get(k) is None else r.get(k)) for k in fieldnames})

def _build_song_verification_sidecars(
    *,
    out_dir: Path,
    selected_song_ids: set[int],
    preferred_source_by_song_id: Dict[int, str],
    song_sources_by_id: Optional[Dict[int, Sequence[str]]],
    expected_song_rows: Optional[Sequence[dict]],
    log_cb: Optional[Callable[[str], None]] = None,
) -> Optional[dict]:
    """Write expected/built song lists + a diff CSV next to the output folder."""
    disc_dir = Path(out_dir).resolve()
    parent = disc_dir.parent
    parent.mkdir(parents=True, exist_ok=True)
    safe_name = disc_dir.name or "disc"

    # ---- expected rows (prefer GUI-provided title/artist)
    expected_by_id: Dict[int, dict] = {}
    if expected_song_rows:
        for r in expected_song_rows:
            rr = _coerce_expected_row(dict(r or {}))
            if rr is None:
                continue
            expected_by_id[int(rr["song_id"])] = rr

    for sid in (selected_song_ids or set()):
        sid_i = int(sid)
        if sid_i not in expected_by_id:
            expected_by_id[sid_i] = {
                "song_id": sid_i,
                "title": "",
                "artist": "",
                "chosen_source": _norm_song_text(preferred_source_by_song_id.get(sid_i, "Base") or "Base") or "Base",
                "available_sources": [str(x) for x in (song_sources_by_id.get(sid_i) or []) if str(x)] if song_sources_by_id else [],
            }
        else:
            # Ensure chosen/source fields are consistent even if GUI row omitted them
            if not expected_by_id[sid_i].get("chosen_source"):
                expected_by_id[sid_i]["chosen_source"] = _norm_song_text(preferred_source_by_song_id.get(sid_i, "Base") or "Base") or "Base"
            if song_sources_by_id and not expected_by_id[sid_i].get("available_sources"):
                expected_by_id[sid_i]["available_sources"] = [str(x) for x in (song_sources_by_id.get(sid_i) or []) if str(x)]

    expected_ids = set(expected_by_id.keys())

    # ---- built rows (parse output songs XML)
    built_by_id: Dict[int, dict] = {}
    parse_ok = True
    try:
        out_idx = index_disc(str(disc_dir))
        songs_map = _load_songs_for_disc_cached(out_idx)
        for sid, (title, artist) in (songs_map or {}).items():
            sid_i = int(sid)
            exp = expected_by_id.get(sid_i)
            built_by_id[sid_i] = {
                "song_id": sid_i,
                "title": _norm_song_text(title),
                "artist": _norm_song_text(artist),
                "chosen_source": (exp.get("chosen_source") if exp else ""),
                "available_sources": (exp.get("available_sources") if exp else []),
            }
    except Exception:
        # If indexing/parsing fails, still emit expected list; diff will be empty.
        parse_ok = False
        built_by_id = {}

    built_ids = set(built_by_id.keys())

    expected_csv = parent / f"{safe_name}_expected_songs.csv"
    built_csv = parent / f"{safe_name}_built_songs.csv"
    diff_csv = parent / f"{safe_name}_song_diff.csv"

    def _prep(rows: list[dict]) -> list[dict]:
        out_rows: list[dict] = []
        for r in rows:
            rr = dict(r or {})
            try:
                rr["available_sources"] = ";".join([str(x) for x in (rr.get("available_sources") or []) if str(x)])
            except Exception:
                rr["available_sources"] = ""
            out_rows.append(rr)
        return out_rows

    fields = ["song_id", "title", "artist", "chosen_source", "available_sources"]
    _write_csv_rows(expected_csv, fields, _prep([expected_by_id[s] for s in sorted(expected_by_id.keys())]))
    _write_csv_rows(built_csv, fields, _prep([built_by_id[s] for s in sorted(built_by_id.keys())]))

    missing_ids = sorted(expected_ids - built_ids)
    extra_ids = sorted(built_ids - expected_ids)

    diff_fields = [
        "status",
        "song_id",
        "expected_title",
        "expected_artist",
        "built_title",
        "built_artist",
        "chosen_source",
        "available_sources",
    ]

    mismatch_n = 0
    diff_rows: list[dict] = []
    for sid in sorted(expected_ids | built_ids):
        exp = expected_by_id.get(sid)
        b = built_by_id.get(sid)
        if exp is not None and b is None:
            diff_rows.append({
                "status": "MISSING_IN_OUTPUT",
                "song_id": sid,
                "expected_title": exp.get("title", ""),
                "expected_artist": exp.get("artist", ""),
                "built_title": "",
                "built_artist": "",
                "chosen_source": exp.get("chosen_source", ""),
                "available_sources": ";".join([str(x) for x in (exp.get("available_sources") or []) if str(x)]),
            })
            continue
        if b is not None and exp is None:
            diff_rows.append({
                "status": "EXTRA_IN_OUTPUT",
                "song_id": sid,
                "expected_title": "",
                "expected_artist": "",
                "built_title": b.get("title", ""),
                "built_artist": b.get("artist", ""),
                "chosen_source": b.get("chosen_source", ""),
                "available_sources": ";".join([str(x) for x in (b.get("available_sources") or []) if str(x)]),
            })
            continue

        # both present
        et = _norm_song_text(exp.get("title", ""))
        ea = _norm_song_text(exp.get("artist", ""))
        bt = _norm_song_text(b.get("title", ""))
        ba = _norm_song_text(b.get("artist", ""))
        status = "OK"
        if (et and bt and et != bt) or (ea and ba and ea != ba):
            status = "META_MISMATCH"
            mismatch_n += 1
        diff_rows.append({
            "status": status,
            "song_id": sid,
            "expected_title": exp.get("title", ""),
            "expected_artist": exp.get("artist", ""),
            "built_title": b.get("title", ""),
            "built_artist": b.get("artist", ""),
            "chosen_source": exp.get("chosen_source", ""),
            "available_sources": ";".join([str(x) for x in (exp.get("available_sources") or []) if str(x)]),
        })

    _write_csv_rows(diff_csv, diff_fields, diff_rows)

    if log_cb is not None:
        try:
            log_cb(
                f"[build] Song list diff: expected={len(expected_ids)} built={len(built_ids)} "
                f"missing={len(missing_ids)} extra={len(extra_ids)} mismatches={int(mismatch_n)}"
            )
            log_cb(f"[build] Wrote song list CSVs: {expected_csv.name}, {built_csv.name}, {diff_csv.name}")
        except Exception:
            pass

    return {
        "expected_count": int(len(expected_ids)),
        "built_count": int(len(built_ids)),
        "parse_ok": bool(parse_ok),
        "missing_count": int(len(missing_ids)),
        "extra_count": int(len(extra_ids)),
        "meta_mismatch_count": int(mismatch_n),
        "missing_ids_sample": [int(x) for x in missing_ids[:100]],
        "extra_ids_sample": [int(x) for x in extra_ids[:100]],
        "files": {
            "expected_csv": str(expected_csv),
            "built_csv": str(built_csv),
            "diff_csv": str(diff_csv),
        },
    }


def _write_build_report(out_dir: Path, report: dict) -> Optional[Path]:
    """Write a build report JSON next to the built disc folder."""
    try:
        out_dir = Path(out_dir).resolve()
        out_dir.mkdir(parents=True, exist_ok=True)
        disc_dir = Path(out_dir).resolve()
        report_dir = disc_dir.parent
        report_dir.mkdir(parents=True, exist_ok=True)
        safe_name = disc_dir.name or 'disc'
        rp = report_dir / f"{safe_name}_build_report.json"
        with rp.open("w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        return rp
    except Exception:
        return None


def _format_seconds_hhmmss(seconds: float) -> str:
    try:
        s = int(round(float(seconds)))
    except Exception:
        return ""
    hh = s // 3600
    mm = (s % 3600) // 60
    ss = s % 60
    if hh > 0:
        return f"{hh:d}:{mm:02d}:{ss:02d}"
    return f"{mm:d}:{ss:02d}"


def _format_build_report_text(report: dict) -> str:
    """Format a human-readable build report (written next to the disc folder)."""
    try:
        lines: list[str] = []
        tool = str(report.get('tool') or 'SPCDB')
        ver = str(report.get('version') or '')
        ts = str(report.get('timestamp') or '')
        out_dir = str(report.get('output_dir') or '')

        lines.append(f"{tool} - Build report")
        if ver or ts:
            lines.append(f"Version: {ver}    Time: {ts}".rstrip())
        if out_dir:
            lines.append(f"Output: {out_dir}")
        lines.append("")

        sel_n = report.get('selected_song_ids_count')
        if sel_n is not None:
            lines.append(f"Included songs: {int(sel_n)}")

        # Preflight plan summary (if available)
        plan = report.get('preflight_plan')
        if isinstance(plan, dict) and plan:
            donors = plan.get('donor_order') or []
            planned = plan.get('planned_counts') or {}
            overrides = plan.get('override_counts') or {}
            implicit = plan.get('implicit_counts') or {}

            # Plan dict key names come from _format_preflight_summary()
            missing_all = plan.get('missing_in_all_sources') or plan.get('missing_all') or []
            mismatched = plan.get('mismatched_preferred_source') or plan.get('mismatched_prefs') or []
            unused_needed = plan.get('unused_needed_donors') or plan.get('unused_needed') or []

            lines.append("Plan:")
            if donors:
                lines.append("  Donor order: " + ", ".join([str(x) for x in donors if str(x)]))
            if planned:
                lines.append("  Song winners (count):")
                for k in sorted(planned.keys(), key=lambda s: (s != 'Base', str(s).lower())):
                    lines.append(f"    - {k}: {int(planned.get(k) or 0)}")
            if overrides:
                lines.append("  Overrides (preferred != Base):")
                for k in sorted(overrides.keys(), key=lambda s: str(s).lower()):
                    lines.append(f"    - {k}: {int(overrides.get(k) or 0)}")
            if implicit:
                lines.append("  Implicit donor winners (not overrides):")
                for k in sorted(implicit.keys(), key=lambda s: str(s).lower()):
                    lines.append(f"    - {k}: {int(implicit.get(k) or 0)}")
            if missing_all:
                lines.append("  Missing in all sources (IDs): " + ", ".join([str(x) for x in list(missing_all)[:50]]))
            if mismatched:
                lines.append("  Preferred source doesn't contain song (IDs): " + ", ".join([str(x) for x in list(mismatched)[:50]]))
            if unused_needed:
                lines.append("  Unused donors (no songs routed): " + ", ".join([str(x) for x in list(unused_needed)[:50] if str(x)]))
            lines.append("")

        # Dedupe stats
        dedupe = report.get('dedupe')
        if isinstance(dedupe, dict) and dedupe:
            lines.append("Duplicates:")
            swd = dedupe.get('songs_with_duplicates')
            extra = dedupe.get('extra_occurrences_hidden')
            if swd is not None:
                lines.append(f"  Songs with duplicates: {int(swd)}")
            if extra is not None:
                lines.append(f"  Extra occurrences hidden: {int(extra)}")
            wc = dedupe.get('winner_counts')
            if isinstance(wc, dict) and wc:
                lines.append("  Winners (count):")
                for k in sorted(wc.keys(), key=lambda s: (s != 'Base', str(s).lower())):
                    lines.append(f"    - {k}: {int(wc.get(k) or 0)}")
            lines.append("")

        # Song list verification (expected vs output songs.xml)
        sd = report.get('song_diff')
        if isinstance(sd, dict) and sd:
            lines.append('Song list verification:')
            exp_c = sd.get('expected_count')
            bu_c = sd.get('built_count')
            mi_c = sd.get('missing_count')
            ex_c = sd.get('extra_count')
            mm_c = sd.get('meta_mismatch_count')
            if exp_c is not None and bu_c is not None:
                lines.append(f"  Expected (selected): {int(exp_c)}")
                lines.append(f"  Built (songs.xml): {int(bu_c)}")
            if mi_c is not None:
                lines.append(f"  Missing: {int(mi_c)}")
            if ex_c is not None:
                lines.append(f"  Extra: {int(ex_c)}")
            if mm_c is not None and int(mm_c) > 0:
                lines.append(f"  Metadata mismatches: {int(mm_c)}")
            try:
                files = sd.get('files') or {}
                if isinstance(files, dict) and files:
                    e = Path(str(files.get('expected_csv') or '')).name
                    b = Path(str(files.get('built_csv') or '')).name
                    d = Path(str(files.get('diff_csv') or '')).name
                    lines.append('  CSVs:')
                    if e:
                        lines.append(f"    - {e}")
                    if b:
                        lines.append(f"    - {b}")
                    if d:
                        lines.append(f"    - {d}")
            except Exception:
                pass
            lines.append('')

        elapsed_sec = report.get('elapsed_sec')
        if elapsed_sec is not None:
            try:
                lines.append(f"Elapsed: {_format_seconds_hhmmss(float(elapsed_sec))}")
            except Exception:
                pass

        return "\n".join(lines).rstrip() + "\n"
    except Exception:
        return ""


def _write_build_report_text(out_dir: Path, report: dict) -> Optional[Path]:
    """Write a human-readable build report text file next to the built disc folder."""
    try:
        disc_dir = Path(out_dir).resolve()
        parent = disc_dir.parent
        parent.mkdir(parents=True, exist_ok=True)
        safe_name = disc_dir.name or 'disc'
        rp = parent / f"{safe_name}_build_report.txt"
        payload = _format_build_report_text(report)
        if not payload:
            return None
        rp.write_text(payload, encoding='utf-8')
        return rp
    except Exception:
        return None



def _write_transfer_notes(
    out_dir: Path,
    *,
    base_path: str,
    src_label_paths: Sequence[Tuple[str, str]],
    selected_song_ids_count: int,
) -> Optional[Path]:
    """Write transfer notes next to the built disc folder (NOT inside it)."""
    try:
        disc_dir = Path(out_dir).resolve()
        parent = disc_dir.parent
        parent.mkdir(parents=True, exist_ok=True)
        safe_name = disc_dir.name or "disc"
        rp = parent / f"{safe_name}_transfer_notes.txt"

        lines: list[str] = []
        lines.append("SingStar Disc Builder - Transfer notes")
        lines.append("")
        lines.append(f"Built disc folder: {disc_dir}")
        lines.append("")
        lines.append("This tool builds an extracted PS3 disc folder (no zip).")
        lines.append("Copy the entire built disc folder as-is to your extracted games folder on your internal (via FTP) or external drive.")
        lines.append("")
        lines.append("Checklist:")
        lines.append("  - Keep the folder structure intact (PS3_GAME / PS3_DISC.SFB etc).")
        lines.append("  - If you use a USB/network transfer, ensure the destination filesystem supports large files.")
        lines.append("")
        lines.append("Build inputs:")
        lines.append(f"  Base: {str(base_path)}")
        lines.append("  Sources:")
        lines.append(f"    - Base: {str(base_path)}")
        for lab, sp in (src_label_paths or []):
            lines.append(f"    - {str(lab)}: {str(sp)}")
        lines.append(f"  Included songs: {int(selected_song_ids_count)}")
        lines.append("")
        lines.append("Extractor note (packed discs):")
        lines.append("  If you added packed/unextracted discs, you must configure the external extractor executable in Settings,")
        lines.append("  then Extract those discs before they can contribute songs to a build.")
        lines.append("")
        lines.append("Related files (next to the disc folder):")
        lines.append(f"  - {safe_name}_preflight_summary.txt")
        lines.append(f"  - {safe_name}_build_report.json")
        lines.append(f"  - {safe_name}_build_report.txt")
        lines.append(f"  - {safe_name}_expected_songs.csv")
        lines.append(f"  - {safe_name}_built_songs.csv")
        lines.append(f"  - {safe_name}_song_diff.csv")
        lines.append(f"  - {safe_name}_transfer_notes.txt (this file)")
        lines.append("")

        rp.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return rp
    except Exception:
        return None


def _write_preflight_summary(out_dir: Path, text: str) -> Optional[Path]:
    # Write a preflight summary next to the disc folder (NOT inside it).
    try:
        disc_dir = Path(out_dir).resolve()
        parent = disc_dir.parent
        parent.mkdir(parents=True, exist_ok=True)
        safe_name = disc_dir.name or "disc"
        rp = parent / f"{safe_name}_preflight_summary.txt"
        payload = str(text or "")
        if not payload.endswith("\n"):
            payload += "\n"
        rp.write_text(payload, encoding="utf-8")
        return rp
    except Exception:
        return None


def _format_preflight_summary(
    *,
    out_dir: Path,
    selected_song_ids: set[int],
    needed_donors: set[str],
    preferred_source_by_song_id: Dict[int, str],
    song_sources_by_id: Optional[Dict[int, Sequence[str]]],
    donor_order: Sequence[str],
) -> tuple[str, list[str], dict]:
    # Return (full_text_for_file, key_lines_for_log).
    from datetime import datetime

    selected = set(int(x) for x in (selected_song_ids or set()))
    preferred = {int(k): str(v) for k, v in (preferred_source_by_song_id or {}).items()}

    donors = [str(x) for x in (donor_order or []) if str(x)]
    needed = set(str(x) for x in (needed_donors or set()) if str(x))

    planned_counts: Dict[str, int] = {"Base": 0}
    override_counts: Dict[str, int] = {}
    implicit_counts: Dict[str, int] = {}

    missing_all: list[int] = []
    mismatched_prefs: list[int] = []
    songs_with_dups = 0

    def _uniq_keep_order(items: Sequence[str]) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for it in items or []:
            s = str(it)
            if not s or s in seen:
                continue
            seen.add(s)
            out.append(s)
        return out

    for sid in sorted(selected):
        srcs: list[str] = []
        if song_sources_by_id:
            try:
                srcs = _uniq_keep_order(song_sources_by_id.get(int(sid), []) or [])
            except Exception:
                srcs = []

        if srcs and len(srcs) > 1:
            songs_with_dups += 1

        explicit = preferred.get(int(sid))
        planned: str | None = None
        is_implicit = False

        if explicit:
            planned = explicit
            if srcs and planned not in srcs:
                mismatched_prefs.append(int(sid))
        else:
            if srcs:
                if "Base" in srcs:
                    planned = "Base"
                else:
                    # Pick first donor (in UI order) that contains it.
                    for lab in donors:
                        if lab in srcs:
                            planned = lab
                            break
                    if planned is None:
                        # Fall back to any non-base source.
                        for lab in srcs:
                            if lab != "Base":
                                planned = lab
                                break
                    if planned is not None and planned != "Base":
                        is_implicit = True
            else:
                planned = "Base"

        if planned is None:
            missing_all.append(int(sid))
            continue

        planned_counts[planned] = int(planned_counts.get(planned, 0)) + 1

        # Overrides: selected exists in Base but user explicitly routes to a non-base donor.
        if planned != "Base" and explicit and explicit != "Base" and srcs and ("Base" in srcs):
            override_counts[planned] = int(override_counts.get(planned, 0)) + 1
        if planned != "Base" and is_implicit:
            implicit_counts[planned] = int(implicit_counts.get(planned, 0)) + 1

    donors_in_plan = {k for k in planned_counts.keys() if k != "Base"}
    unused_needed = sorted([d for d in needed if d not in donors_in_plan])

    lines: list[str] = []
    lines.append("SingStar Disc Builder - Preflight summary")
    lines.append(f"Timestamp: {datetime.now().isoformat(timespec='seconds')}")
    lines.append(f"Output folder: {Path(out_dir)}")
    lines.append("")
    lines.append(f"Included songs: {len(selected)}")
    lines.append("")
    lines.append("Planned song sources:")
    lines.append(f"  Base: {planned_counts.get('Base', 0)}")

    for d in donors:
        n = int(planned_counts.get(d, 0))
        if n <= 0:
            continue
        ov = int(override_counts.get(d, 0))
        imp = int(implicit_counts.get(d, 0))
        extra: list[str] = []
        if ov:
            extra.append(f"overrides {ov}")
        if imp:
            extra.append(f"implicit {imp}")
        suffix = f" ({', '.join(extra)})" if extra else ""
        lines.append(f"  {d}: {n}{suffix}")

    # Any planned donors not in donor_order.
    other_donors = sorted([k for k in planned_counts.keys() if k not in (["Base"] + donors)])
    for d in other_donors:
        n = int(planned_counts.get(d, 0))
        if n > 0:
            lines.append(f"  {d}: {n}")

    lines.append("")
    lines.append("Donors:")
    if needed:
        lines.append(f"  Needed donors: {', '.join(sorted(needed))}")
    else:
        lines.append("  Needed donors: (none)")
    if unused_needed:
        lines.append(f"  Unused donors (no songs routed): {', '.join(unused_needed)}")

    lines.append("")
    lines.append("Duplicates across sources:")
    lines.append(f"  Songs appearing in 2+ sources: {songs_with_dups}")
    if songs_with_dups:
        lines.append(
            "  Note: identical duplicates are auto-handled; non-identical will block the build until resolved in Conflict Resolver."
        )

    if missing_all or mismatched_prefs:
        lines.append("")
        lines.append("Potential issues:")
        if missing_all:
            show = missing_all[:30]
            tail = "" if len(missing_all) <= 30 else f" (+{len(missing_all) - 30} more)"
            lines.append(f"  Missing in all sources: {show}{tail}")
        if mismatched_prefs:
            show = mismatched_prefs[:30]
            tail = "" if len(mismatched_prefs) <= 30 else f" (+{len(mismatched_prefs) - 30} more)"
            lines.append(f"  Preferred source doesn't contain song: {show}{tail}")

    # Key log lines (keep concise)
    log_lines: list[str] = []
    base_n = int(planned_counts.get('Base', 0))
    donor_parts: list[str] = []
    for d in donors:
        n = int(planned_counts.get(d, 0))
        if n > 0:
            donor_parts.append(f"{d} {n}")
    donors_str = (", ".join(donor_parts) if donor_parts else "(no donors)")
    log_lines.append(f"Build plan: {len(selected)} songs -> Base {base_n}, {donors_str}")
    if songs_with_dups:
        log_lines.append(f"Duplicates across sources: {songs_with_dups} song(s) (identical OK; non-identical requires Conflict Resolver)")
    if missing_all:
        log_lines.append(f"WARN: missing in all sources: {missing_all[:10]}{' ...' if len(missing_all) > 10 else ''}")
    if mismatched_prefs:
        log_lines.append(f"WARN: preferred source missing song: {mismatched_prefs[:10]}{' ...' if len(mismatched_prefs) > 10 else ''}")

    full_text = "\n".join(lines) + "\n"
    plan = {
        "selected_song_count": len(selected),
        "planned_counts": {k: int(v) for k, v in planned_counts.items()},
        "override_counts": {k: int(v) for k, v in override_counts.items()},
        "implicit_counts": {k: int(v) for k, v in implicit_counts.items()},
        "songs_with_duplicates": int(songs_with_dups),
        "needed_donors": sorted(list(needed)),
        "donor_order": list(donors),
        "unused_needed_donors": list(unused_needed),
        "missing_in_all_sources": list(missing_all),
        "mismatched_preferred_source": list(mismatched_prefs),
    }
    return full_text, log_lines, plan




def run_build_subset(
    *,
    base_path: str,
    src_label_paths: Sequence[Tuple[str, str]],
    out_dir: Path,
    allow_overwrite_output: bool = False,
    keep_backup_of_existing_output: bool = True,
    fast_update_existing_output: bool = False,
    selected_song_ids: set[int],
    needed_donors: set[str],
    preferred_source_by_song_id: Dict[int, str],
    preflight_validate: bool,
    block_on_errors: bool,
    log_cb: Callable[[str], None],
    song_sources_by_id: Optional[Dict[int, Sequence[str]]] = None,
    expected_song_rows: Optional[Sequence[dict]] = None,
    preflight_report_cb: Optional[Callable[[str], None]] = None,
    cancel_token: Optional[CancelToken] = None,
) -> None:
    """Resolve inputs, optionally validate, then build a subset into out_dir.

    This is UI-agnostic: the caller provides callbacks for log/report and a cancellation token.
    """
    if cancel_token is None:
        cancel_token = CancelToken()

    temp_dirs: list[Any] = []
    try:
        cancel_token.raise_if_cancelled("Cancelled")

        base_ri = resolve_input(str(base_path))
        if getattr(base_ri, "temp_dir", None) is not None:
            temp_dirs.append(base_ri.temp_dir)

        # Resolve ALL sources once (needed for optional preflight validate), then select donors.
        base_norm = str(Path(base_ri.original).resolve())
        resolved_sources: list[tuple[str, str, ResolvedInput]] = []  # (label, input_path, ri)
        for lab, sp in (src_label_paths or []):
            cancel_token.raise_if_cancelled("Cancelled")
            try:
                ri = resolve_input(str(sp))
                if getattr(ri, "temp_dir", None) is not None:
                    temp_dirs.append(ri.temp_dir)
                if str(Path(ri.original).resolve()) == base_norm:
                    continue
                resolved_sources.append((str(lab), str(sp), ri))
            except Exception as e:
                try:
                    log_cb(f"[preflight] WARN: Could not resolve source '{lab}': {e}")
                except Exception:
                    pass

        # Optional: validate discs before build (log-only; build proceeds regardless unless block_on_errors)
        if preflight_validate:
            cancel_token.raise_if_cancelled("Cancelled")
            try:
                msg = "[preflight] Validate-before-build: running disc checks"
                if block_on_errors:
                    msg += " (block on Errors)..."
                else:
                    msg += " (log-only)..."
                log_cb(msg)
            except Exception:
                pass

            ok_n = 0
            warn_n = 0
            fail_n = 0
            any_fail = False
            preflight_results: list[dict] = []

            def _tally_and_log(label: str, r: dict) -> None:
                nonlocal ok_n, warn_n, fail_n, any_fail
                try:
                    r["label"] = str(label)
                except Exception:
                    pass
                preflight_results.append(r)

                sev = str(r.get("severity", "") or "").upper()
                if sev == "OK":
                    ok_n += 1
                elif sev == "WARN":
                    warn_n += 1
                else:
                    fail_n += 1
                    any_fail = True

                try:
                    log_cb(
                        f"[preflight] {label}: {sev} ({len(r.get('errors') or [])}E/{len(r.get('warnings') or [])}W)"
                    )
                    if sev == "FAIL":
                        for it in list(r.get("errors") or [])[:2]:
                            log_cb(f"[preflight]   ERROR: {it.get('message','')}")
                            log_cb(f"[preflight]   Fix: {it.get('fix','')}")
                except Exception:
                    pass

            def _warn_result(label: str, input_path: str, msg: str) -> dict:
                return {
                    "label": str(label),
                    "input_path": str(input_path),
                    "severity": "WARN",
                    "summary": "Validation failed (exception).",
                    "errors": [],
                    "warnings": [
                        {
                            "code": "VALIDATE_EXCEPTION",
                            "message": str(msg),
                            "fix": "Check the disc path / Export folder and try again.",
                        }
                    ],
                    "counts": {},
                    "covers": {},
                    "missing_refs": [],
                    "product": "",
                }

            # Base
            cancel_token.raise_if_cancelled("Cancelled")
            try:
                r_base = validate_one_disc_from_export_root(
                    "Base",
                    str(base_path),
                    Path(base_ri.export_root),
                    str(getattr(base_ri, "kind", "") or ""),
                    list(getattr(base_ri, "warnings", []) or []),
                )
                _tally_and_log("Base", r_base)
            except Exception as e:
                try:
                    log_cb(f"[preflight] Base: WARN (validate failed: {e})")
                except Exception:
                    pass
                warn_n += 1
                preflight_results.append(_warn_result("Base", str(base_path), str(e)))

            # Sources
            for lab, sp, ri in resolved_sources:
                cancel_token.raise_if_cancelled("Cancelled")
                try:
                    r = validate_one_disc_from_export_root(
                        str(lab),
                        str(sp),
                        Path(getattr(ri, "export_root", "")),
                        str(getattr(ri, "kind", "") or ""),
                        list(getattr(ri, "warnings", []) or []),
                    )
                    _tally_and_log(str(lab), r)
                except Exception as e:
                    try:
                        log_cb(f"[preflight] {lab}: WARN (validate failed: {e})")
                    except Exception:
                        pass
                    warn_n += 1
                    preflight_results.append(_warn_result(str(lab), str(sp), str(e)))

            # Store report for Copy report (Validation panel)
            try:
                report_text = format_validate_report(preflight_results, preflight=True)
                if preflight_report_cb is not None:
                    preflight_report_cb(report_text)
            except Exception:
                pass

            try:
                if block_on_errors and any_fail:
                    log_cb(
                        f"[preflight] Done. OK={ok_n}, WARN={warn_n}, FAIL={fail_n}. -> BUILD BLOCKED (errors present)"
                    )
                    log_cb("================ BUILD BLOCKED ================")
                    log_cb(
                        "[preflight] Fix the ERRORs above, then run Build again (or disable blocking in Output)."
                    )
                    log_cb("[preflight] Tip: use 'Copy report' (Validation panel) for the full report.")
                    raise BuildBlockedError(
                        "BUILD BLOCKED: Preflight validation found Errors (FAIL). See the log for details."
                    )

                log_cb(f"[preflight] Done. OK={ok_n}, WARN={warn_n}, FAIL={fail_n}.")
                log_cb("[preflight] Tip: use 'Copy report' (Validation panel) for the full report.")
            except Exception:
                if block_on_errors and any_fail:
                    raise

            cancel_token.raise_if_cancelled("Cancelled")

        # Select donor sources needed for this build
        src_ris: list[tuple[str, ResolvedInput]] = []
        for lab, _sp, ri in resolved_sources:
            if lab not in (needed_donors or set()):
                continue
            src_ris.append((lab, ri))




        preflight_plan: dict | None = None

        # Build plan summary (written next to output folder + shown in log)
        try:
            donor_order = [str(lab) for (lab, _ri) in (src_ris or []) if str(lab)]
            summary_text, summary_log_lines, preflight_plan = _format_preflight_summary(
                out_dir=Path(out_dir),
                selected_song_ids=set(selected_song_ids or set()),
                needed_donors=set(needed_donors or set()),
                preferred_source_by_song_id=dict(preferred_source_by_song_id or {}),
                song_sources_by_id=(song_sources_by_id if song_sources_by_id else None),
                donor_order=donor_order,
            )
            for ln in (summary_log_lines or []):
                try:
                    log_cb(f"[preflight] {ln}")
                except Exception:
                    pass
            rp = _write_preflight_summary(Path(out_dir), summary_text)
            if rp is not None:
                log_cb(f"[preflight] Wrote preflight summary: {rp}")
        except Exception:
            pass
        opts = SubsetOptions(target_version=6, mode="update-required")

        def _progress(msg: str) -> None:
            try:
                log_cb(str(msg))
            except Exception:
                pass

        try:
            t0 = time.perf_counter()
            build_subset(
                base_ri=base_ri,
                source_ris=src_ris,
                out_dir=Path(out_dir),
                selected_song_ids=set(selected_song_ids),
                opts=opts,
                preferred_source_by_song_id=dict(preferred_source_by_song_id or {}),
                allow_overwrite=bool(allow_overwrite_output),
                keep_backup=bool(keep_backup_of_existing_output),
            fast_update_existing_output=bool(fast_update_existing_output),
                progress=_progress,
                cancel_check=cancel_token.cancelled,
            )

            elapsed_sec = max(0.0, time.perf_counter() - t0)

            # Emit expected/built song lists and a diff CSV (helps spot extraction/copy issues)
            song_diff = None
            try:
                song_diff = _build_song_verification_sidecars(
                    out_dir=Path(out_dir),
                    selected_song_ids=set(int(x) for x in (selected_song_ids or set())),
                    preferred_source_by_song_id=dict(preferred_source_by_song_id or {}),
                    song_sources_by_id=(song_sources_by_id if song_sources_by_id else None),
                    expected_song_rows=(expected_song_rows if expected_song_rows else None),
                    log_cb=log_cb,
                )
            except Exception:
                song_diff = None

            # Write a lightweight build report (dedupe + winners) for downstream tooling/UI.
            try:
                report = {
                    "tool": "SPCDB",
                    "version": str(__version__),
                    "timestamp": datetime.now().isoformat(timespec="seconds"),
                    "elapsed_sec": float(elapsed_sec),
                    "base_path": str(base_path),
                    "sources": [{"label": str(lab), "path": str(sp)} for (lab, sp) in (src_label_paths or [])],
                    "output_dir": str(Path(out_dir)),
                    "selected_song_ids_count": int(len(selected_song_ids or set())),
                    "dedupe": _compute_dedupe_stats(
                        set(int(x) for x in (selected_song_ids or set())),
                        dict(preferred_source_by_song_id or {}),
                        (song_sources_by_id if song_sources_by_id else None),
                    ),
                }
                if preflight_plan is not None:
                    report["preflight_plan"] = preflight_plan
                if song_diff is not None:
                    report["song_diff"] = song_diff
                rp = _write_build_report(Path(out_dir), report)
                if rp is not None:
                    log_cb(f"[build] Wrote build report: {rp}")
                rpt = _write_build_report_text(Path(out_dir), report)
                if rpt is not None:
                    log_cb(f"[build] Wrote build report (text): {rpt}")
                tp = _write_transfer_notes(
                    Path(out_dir),
                    base_path=str(base_path),
                    src_label_paths=[(str(lab), str(sp)) for (lab, sp) in (src_label_paths or [])],
                    selected_song_ids_count=int(len(selected_song_ids or set())),
                )
                if tp is not None:
                    log_cb(f"[build] Wrote transfer notes: {tp}")
            except Exception:
                pass

        except BuildCancelled as ce:
            raise CancelledError(str(ce))

    finally:
        for td in temp_dirs:
            try:
                td.cleanup()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Support bundle export (v0.9.83)
# ---------------------------------------------------------------------------

def _bundle_redact_token(value: str, prefix: str = SUPPORT_BUNDLE_TOKEN_PREFIX_PATH) -> str:
    """Return a stable, non-reversible token for a path-like value."""
    try:
        h = hashlib.md5(str(value).encode("utf-8", errors="ignore")).hexdigest()[:8]
    except Exception:
        h = "unknown"
    return f"<{prefix}_{h}>"


def _sanitize_settings_for_bundle(settings: dict, redact_paths: bool = True) -> dict:
    """Return a privacy-safe copy of GUI settings for bundling."""
    s = dict(settings or {})
    # Always drop extractor paths (external dependency + privacy).
    for k in list(s.keys()):
        lk = str(k).lower()
        if lk in ("extractor_exe_path", "extractor_path", "extractor_dir"):
            s.pop(k, None)

    if not redact_paths:
        return s

    # Redact known path-ish keys (and any nested 'path' fields).
    def _redact_obj(obj):
        if isinstance(obj, dict):
            out = {}
            for k, v in obj.items():
                lk = str(k).lower()
                if lk == "path" or lk.endswith("_path") or lk.endswith("_dir") or lk in ("base_path", "output_path"):
                    if isinstance(v, str) and v.strip():
                        out[k] = _bundle_redact_token(v.strip(), prefix=SUPPORT_BUNDLE_TOKEN_PREFIX_PATH)
                    elif isinstance(v, list):
                        out[k] = [_bundle_redact_token(str(x), prefix=SUPPORT_BUNDLE_TOKEN_PREFIX_PATH) for x in v]
                    else:
                        out[k] = v
                else:
                    out[k] = _redact_obj(v)
            return out
        if isinstance(obj, list):
            return [_redact_obj(x) for x in obj]
        return obj

    return _redact_obj(s)


def _copy_log_file_capped(src: Path, dst: Path, max_log_bytes: int) -> str:
    """Copy a log file, truncating to the last max_log_bytes if needed.

    Returns a note describing what was copied.
    """
    try:
        size = int(src.stat().st_size)
    except Exception:
        size = 0

    if size <= 0:
        try:
            dst.write_text("", encoding="utf-8")
        except Exception:
            pass
        return "empty"

    if size <= max_log_bytes:
        try:
            shutil.copy2(src, dst)
            return "full"
        except Exception:
            # fall back to best-effort read/write
            try:
                dst.write_bytes(src.read_bytes())
                return "full"
            except Exception:
                return "failed"

    # Large file: copy only the tail.
    try:
        with src.open("rb") as f:
            try:
                f.seek(-max_log_bytes, os.SEEK_END)
            except Exception:
                f.seek(0)
            data = f.read()
        dst.write_bytes(data)
        return f"tail({len(data)}b)"
    except Exception:
        return "failed"


def export_support_bundle(
    output_path: Path,
    disc_states: list[dict] | None = None,
    redact_paths: bool = True,
) -> dict:
    """Export a privacy-safe support bundle zip for troubleshooting.

    Includes:
      * recent logs (last 10; large logs capped)
      * sanitized GUI settings (no extractor path; optional path redaction)
      * disc states (label/state/path; optional path redaction)
      * index cache summary (counts only)
      * system summary (version/platform/python/pyside6)
    Excludes:
      * disc assets / copyrighted content
      * extractor binaries/paths
      * cache contents

    Args:
        output_path: Where to save the .zip bundle (suffix auto-added if missing)
        disc_states: Optional list of disc metadata dicts (from GUI)
        redact_paths: Replace paths with stable hash tokens (recommended)

    Returns:
        dict with bundle_path, size_mb, included, redact_paths
    """
    import platform
    import sys
    import zipfile
    from datetime import datetime as _dt, timezone as _tz

    outp = Path(output_path)
    if outp.suffix.lower() != ".zip":
        outp = outp.with_suffix(".zip")

    ts = _dt.now().strftime("%Y%m%d_%H%M%S")
    bundle_dir = outp.parent / f"{SUPPORT_BUNDLE_DIR_PREFIX}{ts}"
    included: list[str] = []
    manifest: dict[str, Any] = {
        "created_local": _dt.now().isoformat(timespec="seconds"),
        "created_utc": _dt.now(_tz.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "version": str(__version__),
        "redact_paths": bool(redact_paths),
    }

    # Cap very large logs to keep bundles reasonable.
    max_log_bytes = SUPPORT_BUNDLE_MAX_LOG_BYTES  # per-log cap

    def _safe_mkdir(p: Path) -> None:
        try:
            p.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

    try:
        _safe_mkdir(bundle_dir)

        # 1) Recent logs
        try:
            from .app_logging import _find_app_root  # type: ignore
            app_root = _find_app_root(Path(__file__).resolve().parent)
            logs_dir = Path(app_root) / LOGS_DIRNAME
        except Exception:
            logs_dir = Path.cwd() / LOGS_DIRNAME

        log_notes: list[dict[str, str]] = []
        if logs_dir.exists():
            try:
                files = [p for p in logs_dir.glob(SUPPORT_BUNDLE_LOG_GLOB) if p.is_file()]
                files.sort(key=lambda x: x.stat().st_mtime if x.exists() else 0.0)
                files = files[-SUPPORT_BUNDLE_MAX_LOG_FILES:]
                if files:
                    dst_logs = bundle_dir / LOGS_DIRNAME
                    _safe_mkdir(dst_logs)
                    for lf in files:
                        mode = _copy_log_file_capped(lf, dst_logs / lf.name, max_log_bytes=max_log_bytes)
                        log_notes.append({"file": lf.name, "copy": mode})
                    included.append(f"logs (last {SUPPORT_BUNDLE_MAX_LOG_FILES}, capped)")
            except Exception:
                pass
        if log_notes:
            try:
                (bundle_dir / "logs_manifest.json").write_text(
                    json.dumps({"source": str(logs_dir), "files": log_notes}, indent=2),
                    encoding="utf-8",
                )
            except Exception:
                pass

        # 2) Sanitized settings
        try:
            raw = _load_settings() or {}
            safe = _sanitize_settings_for_bundle(raw, redact_paths=redact_paths)
            (bundle_dir / "settings.json").write_text(json.dumps(safe, indent=2), encoding="utf-8")
            included.append("settings (sanitized)")
        except Exception:
            pass

        # 3) Disc states (optional)
        if disc_states:
            try:
                ds = list(disc_states)
                if redact_paths:
                    red = []
                    for d in ds:
                        try:
                            dd = dict(d or {})
                        except Exception:
                            dd = {}
                        pth = str(dd.get("path", "") or "").strip()
                        if pth:
                            dd["path"] = _bundle_redact_token(pth, prefix=SUPPORT_BUNDLE_TOKEN_PREFIX_DISC)
                        red.append(dd)
                    ds = red
                (bundle_dir / "disc_states.json").write_text(json.dumps(ds, indent=2), encoding="utf-8")
                included.append("disc states")
            except Exception:
                pass

        # 4) Cache info (counts only)
        try:
            cache_dir = _index_cache_dir()
            cache_info = {
                "exists": bool(cache_dir.exists()),
                "dir": _bundle_redact_token(str(cache_dir), prefix=SUPPORT_BUNDLE_TOKEN_PREFIX_PATH) if redact_paths else str(cache_dir),
                "file_count": int(len(list(cache_dir.glob("*.json")))) if cache_dir.exists() else 0,
            }
            try:
                total_bytes = 0
                if cache_dir.exists():
                    for fp in cache_dir.glob("*.json"):
                        try:
                            total_bytes += int(fp.stat().st_size)
                        except Exception:
                            pass
                cache_info["total_bytes"] = int(total_bytes)
            except Exception:
                pass
            (bundle_dir / "cache_info.json").write_text(json.dumps(cache_info, indent=2), encoding="utf-8")
            included.append("cache info (counts only)")
        except Exception:
            pass

        # 5) System summary
        try:
            summary = {
                "version": str(__version__),
                "platform": platform.platform(),
                "python": platform.python_version(),
                "executable": str(getattr(sys, "executable", "")),
            }
            try:
                import PySide6  # type: ignore

                summary["pyside6"] = getattr(PySide6, "__version__", "unknown")
            except Exception:
                summary["pyside6"] = "not installed"

            (bundle_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
            included.append("system summary")
        except Exception:
            pass

        # Bundle README
        try:
            readme = (
                "SingStar Disc Builder Support Bundle\n"
                "===================================\n\n"
                "This zip is intended for troubleshooting. It contains:\n"
                "  - Recent logs (last 10; large logs may be capped to keep the bundle small)\n"
                "  - Sanitized settings (no extractor path; optional path redaction)\n"
                "  - Disc states (if exported from the GUI)\n"
                "  - Index cache summary (counts only; no cached content)\n"
                "  - System summary (version/platform/python/pyside6)\n\n"
                "It does NOT include disc assets/copyrighted content.\n"
            )
            (bundle_dir / "README.txt").write_text(readme, encoding="utf-8")
        except Exception:
            pass

        # Manifest (top-level metadata)
        manifest["included"] = included
        try:
            (bundle_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        except Exception:
            pass

        # 6) Zip everything
        with zipfile.ZipFile(outp, "w", zipfile.ZIP_DEFLATED) as zf:
            for file in bundle_dir.rglob("*"):
                if file.is_file():
                    zf.write(file, file.relative_to(bundle_dir))

        # Cleanup temp dir
        try:
            shutil.rmtree(bundle_dir, ignore_errors=True)
        except Exception:
            pass

        try:
            size_mb = float(outp.stat().st_size) / (1024.0 * 1024.0)
        except Exception:
            size_mb = 0.0

        return {
            "bundle_path": str(outp),
            "size_mb": float(size_mb),
            "included": included,
            "redact_paths": bool(redact_paths),
        }

    except Exception:
        # Cleanup on failure
        try:
            if bundle_dir.exists():
                shutil.rmtree(bundle_dir, ignore_errors=True)
        except Exception:
            pass
        raise
