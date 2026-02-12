from __future__ import annotations

from pathlib import Path

import pytest

import spcdb_tool.cli as cli
from tests.fixtures.fake_disc import make_fake_disc


def test_cli_plan_requires_donor(tmp_path: Path) -> None:
    base = make_fake_disc(tmp_path, label="Base", layout="ps3_game", bank=1, song_ids=[1], include_chc=True)

    with pytest.raises(SystemExit) as e:
        cli.main(["plan", "--base", str(base.disc_root), "--json"])
    assert "at least one" in str(e.value).lower()


def test_cli_validate_succeeds_on_valid_disc(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    disc = make_fake_disc(
        tmp_path,
        label="Disc",
        layout="ps3_game",
        bank=1,
        song_ids=[1],
        include_chc=True,
        include_textures=True,
    )
    rc = cli.main(["validate", str(disc.disc_root)])
    assert int(rc) in {0, 1}
    out = capsys.readouterr().out
    assert "VALIDATE" in out


def test_cli_merge_fails_when_out_exists(tmp_path: Path) -> None:
    base = make_fake_disc(tmp_path, label="Base", layout="ps3_game", bank=1, song_ids=[1], include_chc=True)
    donor = make_fake_disc(tmp_path, label="Donor", layout="ps3_game", bank=1, song_ids=[2], include_chc=True)

    out_dir = tmp_path / "OUT_EXISTS"
    out_dir.mkdir(parents=True, exist_ok=True)

    with pytest.raises(SystemExit) as e:
        cli.main(["merge", "--base", str(base.disc_root), "--donor", str(donor.disc_root), "--out", str(out_dir), "--target-version", "1"])
    assert "merge failed" in str(e.value).lower()



def test_cli_merge_malformed_xml_is_reported_as_merge_failed(tmp_path: Path) -> None:
    base = make_fake_disc(
        tmp_path,
        label="BaseM",
        layout="ps3_game",
        bank=1,
        song_ids=[1],
        include_chc=True,
        include_textures=True,
        include_covers=True,
    )
    donor = make_fake_disc(
        tmp_path,
        label="DonorM",
        layout="ps3_game",
        bank=1,
        song_ids=[2],
        include_chc=True,
        include_textures=True,
        include_covers=True,
    )

    # Break a required XML file so ElementTree raises ParseError.
    (donor.export_root / "songs_1_0.xml").write_text("<SONGS><broken>", encoding="utf-8")

    out_dir = tmp_path / "OUT_BAD_XML_CLI"
    with pytest.raises(SystemExit) as e:
        cli.main([
            "merge",
            "--base",
            str(base.disc_root),
            "--donor",
            str(donor.disc_root),
            "--out",
            str(out_dir),
            "--target-version",
            "1",
            "--mode",
            "update-required",
            "--collision-policy",
            "fail",
            "--songlist-mode",
            "union-by-name",
        ])

    msg = str(e.value)
    assert "MERGE FAILED" in msg
    assert "XML parse failed" in msg
