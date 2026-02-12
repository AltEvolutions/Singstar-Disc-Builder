from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from .layout import ResolvedInput
from .inspect import inspect_export
from .melody_fingerprint import melody_fingerprint_file


def _parse_xml(path: Path) -> ET.Element:
    data = path.read_bytes()
    try:
        return ET.fromstring(data)
    except ET.ParseError as e:
        raise ValueError(f"XML parse failed for {path}: {e}") from e


def _strip_ns(tag: str) -> str:
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _extract_song_ids(songs_xml: Path) -> Set[int]:
    root = _parse_xml(songs_xml)
    ids: Set[int] = set()
    for el in root.iter():
        if _strip_ns(el.tag) != "SONG":
            continue
        # Seen variants: ID, id, song_id
        for key in ("ID", "id", "SONG_ID", "song_id"):
            if key in el.attrib:
                try:
                    ids.add(int(el.attrib[key]))
                except ValueError:
                    continue
                break
    if not ids:
        raise ValueError(f"No SONG ids found in {songs_xml}")
    return ids


@dataclass
class DatasetSummary:
    label: str
    input_path: str
    export_root: str
    max_bank: int
    chosen_bank: int
    song_count: int
    song_ids_sample: List[int]
    missing_song_folders: int
    missing_melody_xml: int
    warnings: List[str]


@dataclass
class CollisionInfo:
    song_id: int
    base_melody_fp: Optional[str]
    donor_melody_fp: Optional[str]
    identical: bool


@dataclass
class PlanReport:
    base: DatasetSummary
    donors: List[DatasetSummary]
    target_version: int
    merged_song_count: int
    collisions: List[CollisionInfo]
    identical_duplicates: List[int]
    unresolved_duplicates: List[int]
    notes: List[str]


def _dataset_from_input(ri: ResolvedInput, label: str, chosen_bank: Optional[int] = None) -> Tuple[DatasetSummary, Set[int], Dict[int, Optional[str]]]:
    rep = inspect_export(
        export_root=ri.export_root,
        kind=ri.kind if ri.kind != "zip_extracted" else "export_folder",
        input_path=str(ri.original),
        warnings=list(ri.warnings),
    )
    max_bank = rep.max_version_in_config or 1
    bank = chosen_bank if chosen_bank is not None else max_bank

    songs_xml = ri.export_root / f"songs_{bank}_0.xml"
    if not songs_xml.exists():
        # fallback: if chosen bank missing, try max bank
        songs_xml = ri.export_root / f"songs_{max_bank}_0.xml"
        bank = max_bank
    if not songs_xml.exists():
        raise FileNotFoundError(f"songs_{bank}_0.xml not found under Export root: {ri.export_root}")

    song_ids = _extract_song_ids(songs_xml)

    missing_song_folders = 0
    missing_melody = 0
    melody_hashes: Dict[int, Optional[str]] = {}
    for sid in song_ids:
        sdir = ri.export_root / str(sid)
        if not sdir.is_dir():
            missing_song_folders += 1
        # Prefer highest available melody_N.xml; some titles ship melody_6.xml etc.
        melody_re = re.compile(r"^melody_(\d+)\.xml$")
        best = None
        best_v = -1
        if sdir.is_dir():
            for mp in sdir.iterdir():
                if not mp.is_file():
                    continue
                m = melody_re.match(mp.name)
                if not m:
                    continue
                try:
                    v = int(m.group(1))
                except ValueError:
                    continue
                if v > best_v:
                    best_v = v
                    best = mp
        fp = melody_fingerprint_file(best) if best is not None else None
        if fp is None:
            missing_melody += 1
        melody_hashes[sid] = fp

    sample = sorted(song_ids)[:20]
    ds = DatasetSummary(
        label=label,
        input_path=str(ri.original),
        export_root=str(ri.export_root),
        max_bank=max_bank,
        chosen_bank=bank,
        song_count=len(song_ids),
        song_ids_sample=sample,
        missing_song_folders=missing_song_folders,
        missing_melody_xml=missing_melody,
        warnings=rep.warnings,
    )
    return ds, song_ids, melody_hashes


def make_plan(
    base_ri: ResolvedInput,
    donor_ris: List[ResolvedInput],
    target_version: int = 6,
    collision_policy: str = "fail",
) -> PlanReport:
    if target_version < 1:
        raise ValueError("target_version must be >= 1")
    if collision_policy not in {"fail", "prefer_base", "prefer_donor"}:
        raise ValueError("collision_policy must be one of: fail, prefer_base, prefer_donor")

    notes: List[str] = []
    base_ds, base_ids, base_hash = _dataset_from_input(base_ri, label="base")

    donors: List[DatasetSummary] = []
    donor_sets: List[Tuple[Set[int], Dict[int, Optional[str]]]] = []
    for i, dri in enumerate(donor_ris, start=1):
        ds, ids, hmap = _dataset_from_input(dri, label=f"donor_{i}")
        donors.append(ds)
        donor_sets.append((ids, hmap))

    merged_ids: Set[int] = set(base_ids)
    merged_hash: Dict[int, Optional[str]] = dict(base_hash)
    collisions: List[CollisionInfo] = []
    identical: Set[int] = set()
    unresolved: Set[int] = set()

    for (ids, hmap) in donor_sets:
        dups = merged_ids.intersection(ids)
        for sid in sorted(dups):
            b = merged_hash.get(sid)
            d = hmap.get(sid)
            same = (b is not None) and (d is not None) and (b == d)
            collisions.append(CollisionInfo(song_id=sid, base_melody_fp=b, donor_melody_fp=d, identical=same))
            if same:
                identical.add(sid)
            else:
                unresolved.add(sid)

        if collision_policy == "prefer_donor":
            for sid in ids:
                merged_ids.add(sid)
                merged_hash[sid] = hmap.get(sid)
        elif collision_policy == "prefer_base":
            for sid in (ids - dups):
                merged_ids.add(sid)
                merged_hash[sid] = hmap.get(sid)
        else:
            # fail policy: still compute merged count assuming no unresolved dups
            for sid in (ids - unresolved):
                merged_ids.add(sid)
                merged_hash[sid] = hmap.get(sid)

    if unresolved and collision_policy == "fail":
        notes.append(
            f"Unresolved duplicate song IDs detected ({len(unresolved)}). Default policy is fail; builder should stop until resolved."
        )
    if identical:
        notes.append(
            f"Identical duplicates detected ({len(identical)}). These can be safely de-duped (by melody fingerprint)."
        )

    # Multi-bank replication guidance
    notes.append(f"Planned output target_version={target_version}. Merged dataset should be replicated into banks 1..{target_version}.")
    notes.append("CHC (melodies_*.chc) must be rebuilt from merged Export/<id>/melody_<target>.xml set (do not concatenate). The builder will synthesize missing melody_1..melody_<target> files per song (by copying an existing melody_N.xml) and will REQUIRE melody_<target>.xml to exist for every song.")

    return PlanReport(
        base=base_ds,
        donors=donors,
        target_version=target_version,
        merged_song_count=len(merged_ids),
        collisions=collisions,
        identical_duplicates=sorted(identical),
        unresolved_duplicates=sorted(unresolved),
        notes=notes,
    )
