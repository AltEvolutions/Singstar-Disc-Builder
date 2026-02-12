from __future__ import annotations

from pathlib import Path

import pytest

import spcdb_tool.merge as merge
from tests.conftest import make_export_root


def test_ensure_versioned_melody_files_copies_forward(tmp_path: Path) -> None:
    export_root = make_export_root(
        tmp_path,
        label="MergeMelody",
        song_ids=[1],
        melodies={
            1: '<SENTENCE><NOTE MidiNote="60" Duration="100" Lyric="a" /></SENTENCE>',
        },
    )

    song_dir = export_root / "1"
    assert (song_dir / "melody_1.xml").exists()
    assert not (song_dir / "melody_6.xml").exists()

    merge._ensure_versioned_melody_files(export_root, [1], target_version=6)

    for v in range(1, 7):
        assert (song_dir / f"melody_{v}.xml").exists()

    assert (song_dir / "melody_6.xml").read_bytes() == (song_dir / "melody_1.xml").read_bytes()


def test_rebuild_and_validate_chc_roundtrip(tmp_path: Path) -> None:
    export_root = make_export_root(
        tmp_path,
        label="MergeCHC",
        song_ids=[1, 2],
        melodies={
            1: '<SENTENCE><NOTE MidiNote="60" Duration="100" Lyric="a" /></SENTENCE>',
            2: '<SENTENCE><NOTE MidiNote="62" Duration="100" Lyric="b" /></SENTENCE>',
        },
    )

    merge._ensure_versioned_melody_files(export_root, [1, 2], target_version=6)

    chc = merge._rebuild_chc([1, 2], export_root, melody_version=6)
    assert isinstance(chc, (bytes, bytearray))
    assert len(chc) > 4

    merge._validate_chc(bytes(chc), {1, 2}, export_root, melody_version=6, sample=10)


def test_validate_chc_detects_content_mismatch(tmp_path: Path) -> None:
    export_root = make_export_root(
        tmp_path,
        label="MergeCHCMismatch",
        song_ids=[1, 2],
        melodies={
            1: '<SENTENCE><NOTE MidiNote="60" Duration="100" Lyric="a" /></SENTENCE>',
            2: '<SENTENCE><NOTE MidiNote="62" Duration="100" Lyric="b" /></SENTENCE>',
        },
    )

    merge._ensure_versioned_melody_files(export_root, [1, 2], target_version=6)
    chc = merge._rebuild_chc([1, 2], export_root, melody_version=6)

    (export_root / "1" / "melody_6.xml").write_text(
        (
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<MELODY xmlns="http://www.singstargame.com">\n'
            '  <SENTENCE><NOTE MidiNote="70" Duration="100" Lyric="X" /></SENTENCE>\n'
            '</MELODY>\n'
        ),
        encoding="utf-8",
    )

    with pytest.raises(merge.MergeError):
        merge._validate_chc(bytes(chc), {1, 2}, export_root, melody_version=6, sample=10)
