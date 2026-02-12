from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from spcdb_tool.layout import resolve_input
from spcdb_tool.subset import SubsetOptions, build_subset
from tests.fixtures.fake_disc import make_fake_disc


def _strip_ns(tag: str) -> str:
    return tag.split('}', 1)[-1] if '}' in tag else tag


def test_build_subset_happy_path_base_plus_one_donor(tmp_path: Path) -> None:
    """End-to-end-ish subset build using tiny synthetic discs.

    This intentionally exercises the real build pipeline (copy base, import a donor song,
    renumber textures, rewrite covers, synthesize melody_6, rebuild/validate CHC, write config).
    """

    # Base disc provides song 1.
    base = make_fake_disc(
        tmp_path,
        label="BaseDisc",
        layout="ps3_game",
        song_ids=[1],
        include_textures=True,
        include_covers=True,
        include_chc=True,
    )

    # Donor export provides song 2.
    donor = make_fake_disc(
        tmp_path,
        label="DonorDisc",
        layout="export_only",
        song_ids=[2],
        include_textures=True,
        include_covers=True,
        include_chc=True,
    )

    base_ri = resolve_input(str(base.disc_root))
    donor_ri = resolve_input(str(donor.export_root))

    out_dir = tmp_path / "OUT_DISC"
    opts = SubsetOptions(target_version=6, mode="update-required")

    build_subset(
        base_ri,
        source_ris=[("Donor", donor_ri)],
        out_dir=out_dir,
        selected_song_ids={1, 2},
        opts=opts,
        preferred_source_by_song_id=None,
        progress=None,
        cancel_check=None,
    )

    assert out_dir.is_dir()
    assert not (tmp_path / "OUT_DISC._BUILDING_tmp").exists()

    out_export = out_dir / "PS3_GAME" / "USRDIR" / "FileSystem" / "Export"
    assert out_export.is_dir(), f"Expected Export root at {out_export}"

    # Song folders present
    assert (out_export / "1").is_dir()
    assert (out_export / "2").is_dir()

    # Texture renumber: base page_0 stays, donor page_0 becomes page_1
    out_tex = out_export / "textures"
    assert (out_tex / "page_0.jpg").is_file()
    assert (out_tex / "page_1.jpg").is_file()

    # Covers rewritten to match textures
    covers_p = out_export / "covers.xml"
    root = ET.parse(covers_p).getroot()
    bits = [el for el in root.iter() if _strip_ns(el.tag) == "TPAGE_BIT"]
    by_name = {el.attrib.get("NAME", ""): el.attrib.get("TEXTURE", "") for el in bits}
    assert by_name.get("cover_1") == "page_0"
    assert by_name.get("cover_2") == "page_1"

    # Target-bank outputs exist
    assert (out_export / "songs_6_0.xml").is_file()
    assert (out_export / "acts_6_0.xml").is_file()
    assert (out_export / "songlists_6.xml").is_file()
    assert (out_export / "melodies_6.chc").is_file()

    # Melody synthesis for target version
    assert (out_export / "1" / "melody_6.xml").is_file()
    assert (out_export / "2" / "melody_6.xml").is_file()
