from __future__ import annotations

from pathlib import Path

import pytest

import spcdb_tool.controller as ctl

from tests.fixtures.fake_disc import make_fake_disc


def _patch_cache_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirect the persistent index cache into a temp folder for tests."""
    cache_dir = tmp_path / "_index_cache"
    monkeypatch.setattr(ctl, "_index_cache_dir", lambda: cache_dir)


def _write_acts_xml(path: Path, acts: dict[int, dict[str, str]]) -> None:
    """Write a minimal acts XML with namespace, supporting NAME and NAME_KEY."""
    parts: list[str] = [
        "<?xml version=\"1.0\" encoding=\"utf-8\"?>",
        "<ACTS xmlns=\"http://www.singstargame.com\">",
    ]
    for aid, data in acts.items():
        parts.append(f"  <ACT ID=\"{int(aid)}\">")
        if data.get("NAME"):
            parts.append(f"    <NAME>{data['NAME']}</NAME>")
        if data.get("NAME_KEY"):
            parts.append(f"    <NAME_KEY>{data['NAME_KEY']}</NAME_KEY>")
        parts.append("  </ACT>")
    parts.append("</ACTS>")
    path.write_text("\n".join(parts) + "\n", encoding="utf-8")


def _write_songs_xml(path: Path, songs: dict[int, dict[str, object]]) -> None:
    """Write a minimal songs XML with namespace.

    Supported fields per song dict:
      - TITLE / TITLE_KEY / NAME_KEY
      - PERFORMANCE_NAME / PERFORMANCE_NAME_KEY
      - PERFORMED_BY_ID (int)
    """
    parts: list[str] = [
        "<?xml version=\"1.0\" encoding=\"utf-8\"?>",
        "<SONGS xmlns=\"http://www.singstargame.com\">",
    ]
    for sid, data in songs.items():
        parts.append(f"  <SONG ID=\"{int(sid)}\">")
        for tag in ("TITLE", "TITLE_KEY", "NAME_KEY"):
            val = str(data.get(tag) or "").strip()
            if val:
                parts.append(f"    <{tag}>{val}</{tag}>")
        for tag in ("PERFORMANCE_NAME", "PERFORMANCE_NAME_KEY"):
            val = str(data.get(tag) or "").strip()
            if val:
                parts.append(f"    <{tag}>{val}</{tag}>")
        pb = data.get("PERFORMED_BY_ID")
        if pb is not None:
            parts.append(f"    <PERFORMED_BY ID=\"{int(pb)}\" />")
        parts.append("  </SONG>")
    parts.append("</SONGS>")
    path.write_text("\n".join(parts) + "\n", encoding="utf-8")


def test_build_song_catalog_prefers_base_metadata_and_aggregates_sources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_cache_dir(tmp_path, monkeypatch)

    base = make_fake_disc(
        tmp_path,
        label="BASE",
        layout="ps3_game",
        bank=1,
        song_ids=[1],
        include_chc=False,
        include_textures=False,
        include_covers=False,
    )
    donor = make_fake_disc(
        tmp_path,
        label="DONOR",
        layout="ps3_game",
        bank=1,
        song_ids=[1, 2],
        include_chc=False,
        include_textures=False,
        include_covers=False,
    )

    # Enrich metadata so we exercise title/artist parsing + fallbacks.
    _write_acts_xml(base.export_root / "acts_1_0.xml", {1: {"NAME": "Base Artist"}})
    _write_songs_xml(
        base.export_root / "songs_1_0.xml",
        {1: {"TITLE": "Base Song", "PERFORMED_BY_ID": 1}},
    )

    # Donor song 1 uses explicit performance name; song 2 uses key-ish fallbacks + act NAME_KEY.
    _write_acts_xml(donor.export_root / "acts_1_0.xml", {2: {"NAME_KEY": "Donor Act"}})
    _write_songs_xml(
        donor.export_root / "songs_1_0.xml",
        {
            1: {"TITLE_KEY": "Donor Song 1", "PERFORMANCE_NAME": "Donor Artist"},
            2: {"NAME_KEY": "Donor Song 2", "PERFORMED_BY_ID": 2},
        },
    )

    base_idx = ctl.index_disc(str(base.disc_root))
    donor_idx = ctl.index_disc(str(donor.disc_root))

    discs = [
        ("Base", base_idx, True),
        ("Donor", donor_idx, False),
    ]
    songs, by_label = ctl.build_song_catalog(discs)

    # Catalog should contain both songs.
    assert [s.song_id for s in songs] == [1, 2]

    s1 = songs[0]
    assert s1.title == "Base Song"
    assert s1.artist == "Base Artist"
    assert s1.preferred_source == "Base"
    assert set(s1.sources) == {"Base", "Donor"}

    s2 = songs[1]
    assert s2.title == "Donor Song 2"
    assert s2.artist == "Donor Act"
    assert s2.preferred_source == "Donor"

    assert by_label["Base"] == {1}
    assert by_label["Donor"] == {1, 2}

    # Second call should be able to hit the persistent songs cache.
    songs2, by_label2 = ctl.build_song_catalog(discs)
    assert songs2 == songs
    assert by_label2 == by_label
