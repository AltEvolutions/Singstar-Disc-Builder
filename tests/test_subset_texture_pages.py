from __future__ import annotations

from pathlib import Path

import pytest

import spcdb_tool.controller as ctl
from spcdb_tool.layout import resolve_input
from spcdb_tool.merge import MergeError
from spcdb_tool.subset import SubsetOptions, build_subset
from tests.fixtures.fake_disc import make_fake_disc


def _out_export_root(out_dir: Path) -> Path:
    # Output is an extracted disc folder (ps3_game layout).
    return out_dir / "PS3_GAME" / "USRDIR" / "FileSystem" / "Export"


def test_subset_renumbers_donor_texture_pages_and_rewrites_covers(tmp_path: Path) -> None:
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
        song_ids=[3],
        include_chc=True,
        include_textures=True,
        include_covers=True,
    )

    base_ri = resolve_input(str(base.disc_root))
    donor_ri = resolve_input(str(donor.disc_root))

    out_dir = tmp_path / "OUT_SUBSET"
    opts = SubsetOptions(target_version=1, mode="update-required")

    try:
        build_subset(
            base_ri=base_ri,
            source_ris=[("Donor", donor_ri)],
            out_dir=out_dir,
            selected_song_ids={1, 3},
            opts=opts,
        )
    finally:
        if base_ri.temp_dir is not None:
            base_ri.temp_dir.cleanup()
        if donor_ri.temp_dir is not None:
            donor_ri.temp_dir.cleanup()

    out_export = _out_export_root(out_dir)
    assert out_export.exists()

    out_textures = out_export / "textures"
    assert (out_textures / "page_0.jpg").exists()
    # Donor's page_0 should have been copied as page_1 (offset since base already had page_0).
    assert (out_textures / "page_1.jpg").exists()

    pages = ctl._covers_song_to_page(out_export)
    assert pages.get(1) == 0
    assert pages.get(3) == 1


def test_subset_raises_when_base_covers_reference_missing_textures(tmp_path: Path) -> None:
    base = make_fake_disc(
        tmp_path,
        label="BaseBadCovers",
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
        song_ids=[3],
        include_chc=True,
        include_textures=True,
        include_covers=True,
    )

    # Break base covers.xml to reference a non-existent page_9.
    covers = base.export_root / "covers.xml"
    txt = covers.read_text(encoding="utf-8")
    txt = txt.replace("page_0", "page_9")
    covers.write_text(txt, encoding="utf-8")

    base_ri = resolve_input(str(base.disc_root))
    donor_ri = resolve_input(str(donor.disc_root))

    out_dir = tmp_path / "OUT_SUBSET_FAIL"
    opts = SubsetOptions(target_version=1, mode="update-required")

    try:
        with pytest.raises(MergeError) as e:
            build_subset(
                base_ri=base_ri,
                source_ris=[("Donor", donor_ri)],
                out_dir=out_dir,
                selected_song_ids={1, 3},
                opts=opts,
            )
        assert "covers.xml references page_9" in str(e.value)
    finally:
        if base_ri.temp_dir is not None:
            base_ri.temp_dir.cleanup()
        if donor_ri.temp_dir is not None:
            donor_ri.temp_dir.cleanup()
        # Clean up temp build dir if it exists (build_subset uses a temp folder strategy).
        tmp_build = out_dir.parent / f"{out_dir.name}._BUILDING_tmp"
        if tmp_build.exists():
            import shutil
            shutil.rmtree(tmp_build, ignore_errors=True)
