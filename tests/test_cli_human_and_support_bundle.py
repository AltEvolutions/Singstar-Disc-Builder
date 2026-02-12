from __future__ import annotations

from pathlib import Path

import json

import pytest

import spcdb_tool.cli as cli
from spcdb_tool.layout import resolve_input

from tests.conftest import make_export_root, write_melody_xml
from tests.fixtures.fake_disc import make_fake_disc


def test_cli_validate_reports_failure_for_missing_path(capsys: pytest.CaptureFixture[str]) -> None:
    rc = cli.main(["validate", "C:/does/not/matter"])
    assert int(rc) == 2
    out = capsys.readouterr().out
    assert "VALIDATE" in out
    assert "RESOLVE_EXPORT_ROOT" in out or "Could not locate Export root" in out


def test_cli_support_bundle_non_json_creates_zip(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out_zip = tmp_path / "bundle.zip"
    rc = cli.main(["support-bundle", "--out", str(out_zip)])
    assert int(rc) == 0
    assert out_zip.exists()

    out = capsys.readouterr().out
    assert "Support bundle written" in out


def test_cli_plan_human_output(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    base = make_export_root(
        tmp_path,
        label="Base",
        song_ids=[1, 2],
        melodies={
            1: '<SENTENCE><NOTE MidiNote="60" Duration="100" Lyric="a" /></SENTENCE>',
            2: '<SENTENCE><NOTE MidiNote="62" Duration="100" Lyric="b" /></SENTENCE>',
        },
    )
    donor = make_export_root(
        tmp_path,
        label="Donor",
        song_ids=[2, 3],
        melodies={
            2: '<SENTENCE><NOTE MidiNote="62" Duration="100" Lyric="b" /></SENTENCE>',
            3: '<SENTENCE><NOTE MidiNote="64" Duration="100" Lyric="c" /></SENTENCE>',
        },
    )

    rc = cli.main(
        [
            "plan",
            "--base",
            str(base),
            "--donor",
            str(donor),
            "--target-version",
            "1",
            "--collision-policy",
            "fail",
        ]
    )
    assert int(rc) == 0

    out = capsys.readouterr().out
    assert "== SingStar Disc Builder PLAN ==" in out
    assert "Target output version" in out


def test_cli_merge_human_output(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
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

    out_dir = tmp_path / "OUT_MERGE_HUMAN"
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
        ]
    )
    assert int(rc) == 0

    out = capsys.readouterr().out
    assert "== SingStar Disc Builder MERGE ==" in out
    assert "Next: run" in out

    # Output should resolve to an Export root.
    ri = resolve_input(str(out_dir))
    try:
        exp = Path(ri.export_root)
        assert (exp / "config.xml").exists()
        assert any(exp.glob("songs_*.xml"))
    finally:
        if ri.temp_dir is not None:
            ri.temp_dir.cleanup()


def test_cli_merge_collision_error_path(tmp_path: Path) -> None:
    base = make_fake_disc(
        tmp_path,
        label="Base",
        layout="ps3_game",
        bank=1,
        song_ids=[1],
        include_chc=True,
        include_textures=False,
        include_covers=False,
    )
    donor = make_fake_disc(
        tmp_path,
        label="Donor",
        layout="ps3_game",
        bank=1,
        song_ids=[1],
        include_chc=True,
        include_textures=False,
        include_covers=False,
    )

    # Make the donor melody differ so it's not an "identical" collision.
    write_melody_xml(
        donor.export_root / "1" / "melody_1.xml",
        body='<SENTENCE><NOTE MidiNote="70" Duration="100" Lyric="x" /></SENTENCE>',
    )

    out_dir = tmp_path / "OUT_COLLISION"
    with pytest.raises(SystemExit) as e:
        cli.main(
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
            ]
        )

    msg = str(e.value)
    assert "MERGE FAILED" in msg



def test_cli_support_bundle_json_creates_zip(tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    # Keep this test hermetic by forcing the app root under tmp_path.
    import spcdb_tool.app_logging as app_logging
    from spcdb_tool.constants import LOGS_DIRNAME

    monkeypatch.setattr(app_logging, "_find_app_root", lambda _start: tmp_path)

    logs_dir = tmp_path / LOGS_DIRNAME
    logs_dir.mkdir(parents=True, exist_ok=True)
    (logs_dir / "run.log").write_text("hello\n", encoding="utf-8")

    out_zip = tmp_path / "bundle.json.zip"
    rc = cli.main(["support-bundle", "--out", str(out_zip), "--json"])
    assert int(rc) == 0

    out = capsys.readouterr().out.strip()
    data = json.loads(out)

    bundle_path = Path(str(data.get("bundle_path") or ""))
    assert bundle_path.exists()
    assert bundle_path.suffix.lower() == ".zip"
