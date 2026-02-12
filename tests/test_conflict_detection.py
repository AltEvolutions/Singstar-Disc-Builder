from __future__ import annotations

from pathlib import Path

from spcdb_tool.controller import SongAgg, compute_song_id_conflicts
from tests.conftest import make_export_root


def test_compute_song_id_conflicts_detects_sha_mismatch_and_fps(tmp_path: Path) -> None:
    # Same song_id exists in two sources; melody differs -> conflict.
    melodies_a = {
        1: """
  <SENTENCE>
    <NOTE MidiNote=\"60\" Duration=\"100\" Lyric=\"a\" />
  </SENTENCE>
""",
    }
    melodies_b = {
        1: """
  <SENTENCE>
    <NOTE MidiNote=\"61\" Duration=\"100\" Lyric=\"a\" />
  </SENTENCE>
""",
    }

    export_a = make_export_root(tmp_path, label="Base", song_ids=[1], melodies=melodies_a)
    export_b = make_export_root(tmp_path, label="Donor", song_ids=[1], melodies=melodies_b)

    songs = [
        SongAgg(song_id=1, title="T", artist="A", preferred_source="Base", sources=("Base", "Donor")),
    ]

    conflicts = compute_song_id_conflicts(
        songs=songs,
        export_roots_by_label={"Base": str(export_a), "Donor": str(export_b)},
    )

    assert 1 in conflicts
    occs = conflicts[1]
    assert len(occs) == 2
    # Both fingerprints should be present and different
    fps = {o.source_label: o.melody1_fp for o in occs}
    assert fps["Base"] and fps["Donor"]
    assert fps["Base"] != fps["Donor"]


def test_compute_song_id_conflicts_includes_missing_melody(tmp_path: Path) -> None:
    melodies_a = {
        2: """
  <SENTENCE>
    <NOTE MidiNote=\"60\" Duration=\"100\" Lyric=\"a\" />
  </SENTENCE>
""",
    }
    export_a = make_export_root(tmp_path, label="Base", song_ids=[2], melodies=melodies_a)
    export_b = make_export_root(tmp_path, label="Donor", song_ids=[2], melodies={})  # missing melody_1.xml

    songs = [
        SongAgg(song_id=2, title="T", artist="A", preferred_source="Base", sources=("Base", "Donor")),
    ]

    conflicts = compute_song_id_conflicts(
        songs=songs,
        export_roots_by_label={"Base": str(export_a), "Donor": str(export_b)},
    )

    assert 2 in conflicts
    occs = {o.source_label: o for o in conflicts[2]}
    assert occs["Base"].melody1_fp is not None
    assert occs["Donor"].melody1_fp is None
