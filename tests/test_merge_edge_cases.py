from __future__ import annotations

from pathlib import Path

import pytest

import spcdb_tool.merge as merge
from spcdb_tool.layout import resolve_input

from tests.fixtures.fake_disc import make_fake_disc


def _merge_opts() -> merge.MergeOptions:
    return merge.MergeOptions(
        target_version=1,
        mode="update-required",
        collision_policy="fail",
        songlist_mode="union-by-name",
        verbose=False,
    )


def test_merge_build_raises_mergeerror_on_malformed_xml(tmp_path: Path) -> None:
    base = make_fake_disc(
        tmp_path,
        label="Base",
        layout="ps3_game",
        bank=1,
        song_ids=[1],
        include_chc=True,
        include_textures=True,
        include_covers=True,
    )
    donor = make_fake_disc(
        tmp_path,
        label="Donor",
        layout="ps3_game",
        bank=1,
        song_ids=[2],
        include_chc=True,
        include_textures=True,
        include_covers=True,
    )

    # Corrupt a required XML file.
    (donor.export_root / "songs_1_0.xml").write_text("<SONGS><broken>", encoding="utf-8")

    out_dir = tmp_path / "OUT_BAD_XML"
    with pytest.raises(merge.MergeError) as e:
        merge.merge_build(
            base_ri=resolve_input(str(base.disc_root)),
            donor_ris=[resolve_input(str(donor.disc_root))],
            out_dir=out_dir,
            opts=_merge_opts(),
        )

    assert "xml parse failed" in str(e.value).lower()


def test_merge_build_fails_when_donor_textures_missing(tmp_path: Path) -> None:
    base = make_fake_disc(
        tmp_path,
        label="BaseTex",
        layout="ps3_game",
        bank=1,
        song_ids=[1],
        include_chc=True,
        include_textures=True,
        include_covers=True,
    )
    donor = make_fake_disc(
        tmp_path,
        label="DonorNoTex",
        layout="ps3_game",
        bank=1,
        song_ids=[2],
        include_chc=True,
        include_textures=False,
        include_covers=True,
    )

    out_dir = tmp_path / "OUT_NO_TEX"
    with pytest.raises(merge.MergeError) as e:
        merge.merge_build(
            base_ri=resolve_input(str(base.disc_root)),
            donor_ris=[resolve_input(str(donor.disc_root))],
            out_dir=out_dir,
            opts=_merge_opts(),
        )

    assert "textures" in str(e.value).lower()
    assert "missing" in str(e.value).lower()


def test_merge_build_detects_uppercase_textures_folder(tmp_path: Path) -> None:
    base = make_fake_disc(
        tmp_path,
        label="BaseTex2",
        layout="ps3_game",
        bank=1,
        song_ids=[1],
        include_chc=True,
        include_textures=True,
        include_covers=True,
    )
    donor = make_fake_disc(
        tmp_path,
        label="DonorUpper",
        layout="ps3_game",
        bank=1,
        song_ids=[2],
        include_chc=True,
        include_textures=True,
        include_covers=True,
    )

    # Rename Export/textures -> Export/Textures to simulate casing hazard.
    lower = donor.export_root / "textures"
    upper = donor.export_root / "Textures"
    assert lower.is_dir()
    lower.rename(upper)

    out_dir = tmp_path / "OUT_UPPER_TEX"
    with pytest.raises(merge.MergeError) as e:
        merge.merge_build(
            base_ri=resolve_input(str(base.disc_root)),
            donor_ris=[resolve_input(str(donor.disc_root))],
            out_dir=out_dir,
            opts=_merge_opts(),
        )

    msg = str(e.value).lower()
    assert "export/textures" in msg
    assert "ps3" in msg or "casing" in msg


def test_merge_build_fails_when_cover_references_missing_texture_page(tmp_path: Path) -> None:
    base = make_fake_disc(
        tmp_path,
        label="BaseCover",
        layout="ps3_game",
        bank=1,
        song_ids=[1],
        include_chc=True,
        include_textures=True,
        include_covers=True,
    )
    donor = make_fake_disc(
        tmp_path,
        label="DonorBadCover",
        layout="ps3_game",
        bank=1,
        song_ids=[2],
        include_chc=True,
        include_textures=True,
        include_covers=True,
    )

    # Donor has only page_0.jpg, but covers.xml will reference page_5.
    covers_p = donor.export_root / "covers.xml"
    covers_p.write_text(
        (
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<COVERS xmlns="http://www.singstargame.com">\n'
            '  <TPAGE_BIT NAME="cover_2" TEXTURE="page_5" />\n'
            '</COVERS>\n'
        ),
        encoding="utf-8",
    )

    out_dir = tmp_path / "OUT_BAD_COVER"
    with pytest.raises(merge.MergeError) as e:
        merge.merge_build(
            base_ri=resolve_input(str(base.disc_root)),
            donor_ris=[resolve_input(str(donor.disc_root))],
            out_dir=out_dir,
            opts=_merge_opts(),
        )

    assert "cover" in str(e.value).lower()
    assert "texture" in str(e.value).lower()
