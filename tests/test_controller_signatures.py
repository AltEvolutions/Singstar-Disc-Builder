from __future__ import annotations

import time
from pathlib import Path

import spcdb_tool.controller as ctl
from spcdb_tool.controller import DiscIndex

from tests.fixtures.fake_disc import make_fake_disc


def test_normalize_input_path_handles_empty_and_relative(tmp_path: Path) -> None:
    assert ctl._normalize_input_path("") == ""
    assert ctl._normalize_input_path("   ") == ""
    # Relative -> absolute resolved (best effort)
    p = tmp_path / "rel"
    p.mkdir()
    rel = str(p.relative_to(tmp_path))
    # Chdir to tmp_path so rel resolves consistently
    cwd = Path.cwd()
    try:
        import os as _os
        _os.chdir(tmp_path)
        out = ctl._normalize_input_path(rel)
        assert out.endswith(str(p))
    finally:
        import os as _os
        _os.chdir(cwd)


def test_stat_sig_changes_when_file_changes(tmp_path: Path) -> None:
    f = tmp_path / "a.txt"
    f.write_text("hello", encoding="utf-8")
    sig1 = ctl._stat_sig(f)
    time.sleep(0.01)
    f.write_text("hello world", encoding="utf-8")
    sig2 = ctl._stat_sig(f)
    assert sig1 != sig2

    missing = tmp_path / "missing.txt"
    assert ctl._stat_sig(missing).endswith(":missing")


def test_compute_disc_signature_changes_on_songs_edit(tmp_path: Path) -> None:
    disc = make_fake_disc(
        tmp_path,
        label="SigDisc",
        layout="ps3_game",
        bank=1,
        song_ids=[1, 2],
        include_chc=True,
        include_textures=False,
        include_covers=False,
    )
    exp = disc.export_root
    songs = exp / "songs_1_0.xml"
    acts = exp / "acts_1_0.xml"
    sig1 = ctl._compute_disc_signature(str(exp), str(songs), str(acts))
    time.sleep(0.01)
    songs.write_text(songs.read_text(encoding="utf-8") + "\n<!-- edit -->\n", encoding="utf-8")
    sig2 = ctl._compute_disc_signature(str(exp), str(songs), str(acts))
    assert sig1 != sig2

    idx = DiscIndex(
        input_path=str(disc.disc_root),
        export_root=str(exp),
        product_code="X",
        product_desc="X",
        max_bank=1,
        chosen_bank=1,
        songs_xml=str(songs),
        acts_xml=str(acts),
        song_count=2,
        warnings=[],
    )
    sig3 = ctl._compute_disc_signature_for_idx(idx)
    assert sig3 == sig2


def test_compute_dedupe_stats_histogram_and_winners() -> None:
    selected = {1, 2, 3}
    winners = {1: "Base", 2: "DonorA", 3: "DonorA"}
    stats = ctl._compute_dedupe_stats(selected, winners, None)
    assert stats["selected_unique"] == 3
    assert stats["winner_counts"]["DonorA"] == 2

    sources = {1: ["Base"], 2: ["Base", "DonorA"], 3: ["Base", "DonorA", "DonorB"]}
    stats2 = ctl._compute_dedupe_stats(selected, winners, sources)
    assert stats2["songs_with_duplicates"] == 2
    assert stats2["extra_occurrences_hidden"] == (1 + 2)  # (2-1) + (3-1)
    assert stats2["dup_count_histogram"]["1"] == 1
    assert stats2["dup_count_histogram"]["2"] == 1
    assert stats2["dup_count_histogram"]["3"] == 1


def test_format_seconds_hhmmss() -> None:
    assert ctl._format_seconds_hhmmss(0) == "0:00"
    assert ctl._format_seconds_hhmmss(1) == "0:01"
    assert ctl._format_seconds_hhmmss(61) == "1:01"
    assert ctl._format_seconds_hhmmss(3661) == "1:01:01"
