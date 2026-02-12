from __future__ import annotations

from pathlib import Path

import spcdb_tool.controller as ctl
from tests.fixtures.fake_disc import make_fake_disc


def _codes(items: list[dict] | None) -> set[str]:
    if not items:
        return set()
    out: set[str] = set()
    for i in items:
        if isinstance(i, dict) and i.get("code"):
            out.add(str(i["code"]))
    return out


def test_validate_one_disc_warns_when_config_missing_and_textures_missing(tmp_path: Path) -> None:
    # Create a disc with covers.xml and songs xml, but:
    # - delete config.xml (forces validate_one_disc to fall back to minimal scan)
    # - ensure textures folder is missing (forces NO_TEXTURES + missing cover pages)
    disc = make_fake_disc(
        tmp_path,
        label="NoCfgNoTex",
        layout="ps3_game",
        bank=1,
        song_ids=[1],
        include_chc=False,
        include_textures=False,
        include_covers=True,
    )

    export_root = disc.export_root
    cfg = export_root / "config.xml"
    assert cfg.exists()
    cfg.unlink()

    rep = ctl.validate_one_disc("disc", str(disc.disc_root))

    assert rep.get("ok") is True
    assert rep.get("severity") in ("WARN", "OK")

    warn_codes = _codes(rep.get("warnings"))
    err_codes = _codes(rep.get("errors"))

    # Layout warnings
    assert "NO_CONFIG" in warn_codes
    assert "NO_TEXTURES" in warn_codes

    # Because covers.xml references at least page_0 but textures folder is missing.
    assert "MISSING_COVER_PAGES" in warn_codes

    # Because config.xml is missing, inspect_export cannot read referenced files.
    assert "MISSING_CONFIG_XML" in warn_codes

    assert err_codes == set()


def test_validate_one_disc_fails_when_no_songs_xml(tmp_path: Path) -> None:
    disc = make_fake_disc(
        tmp_path,
        label="NoSongsXml",
        layout="ps3_game",
        bank=1,
        song_ids=[1, 2],
        include_chc=False,
        include_textures=False,
        include_covers=False,
    )

    # Remove the songs XML file(s).
    for p in disc.export_root.glob("songs_*_0.xml"):
        p.unlink()

    rep = ctl.validate_one_disc("disc", str(disc.disc_root))

    assert rep.get("ok") is False
    assert rep.get("severity") == "FAIL"

    warn_codes = _codes(rep.get("warnings"))
    err_codes = _codes(rep.get("errors"))
    assert "NO_SONGS_XML" in err_codes
    assert "NO_SONGS_XML" not in warn_codes


def test_validate_one_disc_reports_textures_casing_hazard(tmp_path: Path) -> None:
    disc = make_fake_disc(
        tmp_path,
        label="TexCase",
        layout="ps3_game",
        bank=1,
        song_ids=[1],
        include_chc=False,
        include_textures=True,
        include_covers=False,
    )

    # On a case-sensitive FS, make it look like a PS3 casing hazard: Textures instead of textures.
    tex = disc.export_root / "textures"
    assert tex.is_dir()
    tex_renamed = disc.export_root / "Textures"
    tex.rename(tex_renamed)

    rep = ctl.validate_one_disc("disc", str(disc.disc_root))
    warn_codes = _codes(rep.get("warnings"))
    assert "LAYOUT" in warn_codes
