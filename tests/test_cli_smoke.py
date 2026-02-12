from __future__ import annotations

import runpy
import sys
from pathlib import Path

import pytest

import spcdb_tool.cli as cli
from tests.conftest import make_export_root


def test_cli_help_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    # argparse help exits via SystemExit(0)
    with pytest.raises(SystemExit) as e:
        cli.main(["--help"])
    assert int(e.value.code or 0) == 0
    out = capsys.readouterr().out
    assert "SingStar Disc Builder" in out


def test_cli_inspect_help_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as e:
        cli.main(["inspect", "--help"])
    assert int(e.value.code or 0) == 0
    out = capsys.readouterr().out
    assert "Inspect" in out or "inspect" in out


def test_cli_plan_json_smoke(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # Minimal fixtures are enough for make_plan; run via CLI plumbing to lift coverage in cli.py.
    base = make_export_root(
        tmp_path,
        label="Base",
        song_ids=[1, 2],
        melodies={
            1: "<SENTENCE><NOTE MidiNote=\"60\" Duration=\"100\" Lyric=\"a\" /></SENTENCE>",
            2: "<SENTENCE><NOTE MidiNote=\"60\" Duration=\"100\" Lyric=\"b\" /></SENTENCE>",
        },
    )
    donor = make_export_root(
        tmp_path,
        label="Donor",
        song_ids=[2, 3],
        melodies={
            2: "<SENTENCE><NOTE MidiNote=\"60\" Duration=\"100\" Lyric=\"b\" /></SENTENCE>",
            3: "<SENTENCE><NOTE MidiNote=\"62\" Duration=\"100\" Lyric=\"c\" /></SENTENCE>",
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
            "--json",
        ]
    )
    assert int(rc) == 0
    out = capsys.readouterr().out
    # Should have printed JSON
    assert out.strip().startswith("{")
    assert '"base"' in out
    assert '"target_version"' in out


def test_python_m_spcdb_tool_help_executes___main__(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    # Execute spcdb_tool as a module within the same process so coverage sees __main__.py.
    monkeypatch.setattr(sys, "argv", ["spcdb_tool", "--help"])
    with pytest.raises(SystemExit) as e:
        runpy.run_module("spcdb_tool", run_name="__main__")
    assert int(e.value.code or 0) == 0
    out = capsys.readouterr().out
    assert "SingStar Disc Builder" in out
