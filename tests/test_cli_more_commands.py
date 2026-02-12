from __future__ import annotations

import json
from pathlib import Path

import pytest

import spcdb_tool.cli as cli
from spcdb_tool.layout import resolve_input

from tests.fixtures.fake_disc import make_fake_disc


def test_cli_inspect_json_real_disc(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    disc = make_fake_disc(
        tmp_path,
        label="BaseDisc",
        layout="ps3_game",
        bank=1,
        song_ids=[1, 2],
        include_chc=True,
        include_textures=False,
        include_covers=False,
    )

    rc = cli.main(["inspect", str(disc.disc_root), "--json"])
    assert int(rc) == 0

    out = capsys.readouterr().out.strip()
    data = json.loads(out)
    assert data["kind"] in ("disc_folder", "export_folder", "zip_extracted")
    assert int(data["max_version_in_config"] or 0) >= 1
    assert (data.get("product_code") or "").startswith("BASEDISC")


def test_cli_merge_json_smoke_builds_output(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    base = make_fake_disc(
        tmp_path,
        label="Base",
        layout="ps3_game",
        bank=1,
        song_ids=[1, 2],
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

    out_dir = tmp_path / "OUT_MERGE"
    rc = cli.main(
        [
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
            "--json",
        ]
    )
    assert int(rc) == 0

    txt = capsys.readouterr().out.strip()
    stats = json.loads(txt)
    assert int(stats["base_song_count"]) == 2
    assert int(stats["donor_song_count"]) == 1
    assert int(stats["merged_song_count"]) >= 2

    # Verify output resolves to an Export root and contains basic expected files.
    ri = resolve_input(str(out_dir))
    try:
        exp = Path(ri.export_root)
        assert (exp / "config.xml").exists()
        assert any(exp.glob("songs_*.xml"))
    finally:
        if ri.temp_dir is not None:
            ri.temp_dir.cleanup()


def test_cli_merge_requires_donor(tmp_path: Path) -> None:
    base = make_fake_disc(tmp_path, label="Base", layout="ps3_game", bank=1, song_ids=[1], include_chc=True)
    out_dir = tmp_path / "OUT_FAIL"

    with pytest.raises(SystemExit) as e:
        cli.main(["merge", "--base", str(base.disc_root), "--out", str(out_dir)])

    msg = str(e.value)
    assert "at least one" in msg.lower()
