from __future__ import annotations

import json
from pathlib import Path

import pytest

import spcdb_tool.controller as ctl
from spcdb_tool.controller import BuildBlockedError, CancelToken, CancelledError, run_build_subset

from tests.fixtures.fake_disc import make_fake_disc


def test_format_build_report_text_includes_plan_lists() -> None:
    report = {
        "tool": "SPCDB",
        "version": "X",
        "timestamp": "T",
        "output_dir": "OUT",
        "selected_song_ids_count": 3,
        "preflight_plan": {
            "donor_order": ["DonorA"],
            "planned_counts": {"Base": 1, "DonorA": 2},
            "override_counts": {"DonorA": 1},
            "implicit_counts": {"DonorA": 1},
            "missing_in_all_sources": [99],
            "mismatched_preferred_source": [2],
            "unused_needed_donors": ["DonorB"],
        },
        "dedupe": {},
    }

    text = ctl._format_build_report_text(report)
    assert "Plan:" in text
    assert "Missing in all sources" in text
    assert "99" in text
    assert "Preferred source doesn't contain song" in text
    assert "2" in text
    assert "Unused donors (no songs routed)" in text
    assert "DonorB" in text


def test_run_build_subset_preflight_and_reports(tmp_path: Path) -> None:
    # Base provides songs 1,2. Donor provides songs 1,3.
    base = make_fake_disc(
        tmp_path,
        label="BaseDisc",
        layout="ps3_game",
        song_ids=[1, 2],
        include_textures=True,
        include_covers=True,
        include_chc=True,
    )
    donor = make_fake_disc(
        tmp_path,
        label="DonorDisc",
        layout="export_only",
        song_ids=[1, 3],
        include_textures=True,
        include_covers=True,
        include_chc=True,
    )

    out_dir = tmp_path / "OUT_DISC"

    # Include a duplicate base path in sources to cover the "skip base in sources" logic,
    # and one bad source to cover the log-only resolution warning.
    bad_src = tmp_path / "MISSING_SRC_DOES_NOT_EXIST"

    logs: list[str] = []
    preflight_reports: list[str] = []

    def _log(msg: str) -> None:
        logs.append(str(msg))

    def _preflight_report(msg: str) -> None:
        preflight_reports.append(str(msg))

    run_build_subset(
        base_path=str(base.disc_root),
        src_label_paths=[
            ("BaseDup", str(base.disc_root)),
            ("Donor", str(donor.export_root)),
            ("Bad", str(bad_src)),
        ],
        out_dir=out_dir,
        selected_song_ids={1, 2, 3},
        needed_donors={"Donor"},
        preferred_source_by_song_id={1: "Donor"},
        preflight_validate=True,
        block_on_errors=False,
        log_cb=_log,
        song_sources_by_id={1: ["Base", "Donor"], 2: ["Base"], 3: ["Donor"]},
        preflight_report_cb=_preflight_report,
        cancel_token=None,
    )

    assert out_dir.is_dir()
    # Built disc should contain the base PS3_GAME wrapper.
    assert (out_dir / "PS3_GAME").is_dir()

    # Preflight report callback should have been called at least once.
    assert preflight_reports
    assert "Validate Disc report (preflight)" in preflight_reports[-1]

    # Summary/report files live next to the output disc folder.
    parent = out_dir.parent
    assert (parent / "OUT_DISC_preflight_summary.txt").is_file()
    assert (parent / "OUT_DISC_build_report.json").is_file()
    assert (parent / "OUT_DISC_build_report.txt").is_file()
    assert (parent / "OUT_DISC_transfer_notes.txt").is_file()

    report = json.loads((parent / "OUT_DISC_build_report.json").read_text(encoding="utf-8"))
    assert report.get("tool") == "SPCDB"
    assert isinstance(report.get("version"), str)
    assert report.get("preflight_plan") is not None

    plan = report["preflight_plan"]
    assert plan["planned_counts"]["Base"] >= 1
    assert plan["planned_counts"]["Donor"] >= 1
    assert plan["override_counts"]["Donor"] >= 1

    # Ensure the warning path was exercised for the bad source.
    assert any("Could not resolve source" in ln for ln in logs)


def test_run_build_subset_blocks_on_preflight_errors(tmp_path: Path) -> None:
    base = make_fake_disc(tmp_path, label="BaseDisc", layout="ps3_game", song_ids=[1], include_chc=False)
    donor = make_fake_disc(tmp_path, label="DonorDisc", layout="export_only", song_ids=[2], include_chc=False)

    # Force a preflight validation FAIL by removing songs XML.
    (base.export_root / "songs_1_0.xml").unlink()

    out_dir = tmp_path / "OUT_DISC_BLOCKED"
    logs: list[str] = []

    with pytest.raises(BuildBlockedError):
        run_build_subset(
            base_path=str(base.disc_root),
            src_label_paths=[("Donor", str(donor.export_root))],
            out_dir=out_dir,
            selected_song_ids={1, 2},
            needed_donors={"Donor"},
            preferred_source_by_song_id={},
            preflight_validate=True,
            block_on_errors=True,
            log_cb=lambda m: logs.append(str(m)),
            cancel_token=None,
        )

    assert not out_dir.exists()
    assert any("BUILD BLOCKED" in ln for ln in logs)


def test_run_build_subset_cancelled_short_circuits(tmp_path: Path) -> None:
    base = make_fake_disc(tmp_path, label="BaseDisc", layout="ps3_game", song_ids=[1], include_chc=False)
    donor = make_fake_disc(tmp_path, label="DonorDisc", layout="export_only", song_ids=[2], include_chc=False)

    out_dir = tmp_path / "OUT_DISC_CANCELLED"
    tok = CancelToken()
    tok.cancel()

    with pytest.raises(CancelledError):
        run_build_subset(
            base_path=str(base.disc_root),
            src_label_paths=[("Donor", str(donor.export_root))],
            out_dir=out_dir,
            selected_song_ids={1, 2},
            needed_donors={"Donor"},
            preferred_source_by_song_id={},
            preflight_validate=False,
            block_on_errors=False,
            log_cb=lambda _m: None,
            cancel_token=tok,
        )

    assert not out_dir.exists()



def test_run_build_subset_preflight_validate_exception_is_warn_and_continues(tmp_path: Path, monkeypatch) -> None:
    # Cover the validation exception -> WARN result path (should NOT block build).
    base = make_fake_disc(
        tmp_path,
        label="BaseDisc",
        layout="ps3_game",
        song_ids=[1, 2],
        include_textures=True,
        include_covers=True,
        include_chc=True,
    )
    donor = make_fake_disc(
        tmp_path,
        label="DonorDisc",
        layout="export_only",
        song_ids=[3],
        include_textures=True,
        include_covers=True,
        include_chc=True,
    )

    def _boom(*_a, **_kw):
        raise RuntimeError("boom")

    monkeypatch.setattr(ctl, "validate_one_disc_from_export_root", _boom)

    out_dir = tmp_path / "OUT_DISC_VALIDATE_EXC"
    logs: list[str] = []
    preflight_reports: list[str] = []

    run_build_subset(
        base_path=str(base.disc_root),
        src_label_paths=[("Donor", str(donor.export_root))],
        out_dir=out_dir,
        selected_song_ids={1, 2, 3},
        needed_donors={"Donor"},
        preferred_source_by_song_id={},
        preflight_validate=True,
        block_on_errors=True,
        log_cb=lambda m: logs.append(str(m)),
        preflight_report_cb=lambda m: preflight_reports.append(str(m)),
        cancel_token=None,
    )

    assert out_dir.is_dir()
    assert preflight_reports
    # The exception path is represented as WARN in the report text.
    assert "Validation failed (exception)." in preflight_reports[-1]
    assert any("validate failed" in ln.lower() for ln in logs)


def test_run_build_subset_maps_buildcancelled_to_cancellederror(tmp_path: Path, monkeypatch) -> None:
    # Cover the BuildCancelled -> CancelledError mapping.
    from spcdb_tool.subset import BuildCancelled

    base = make_fake_disc(tmp_path, label="BaseDisc", layout="ps3_game", song_ids=[1], include_chc=False)
    donor = make_fake_disc(tmp_path, label="DonorDisc", layout="export_only", song_ids=[2], include_chc=False)

    def _fake_build_subset(**kwargs):
        raise BuildCancelled(Path(kwargs["out_dir"]), "Stop now")

    monkeypatch.setattr(ctl, "build_subset", _fake_build_subset)

    out_dir = tmp_path / "OUT_DISC_CANCELLED_IN_BUILD"

    with pytest.raises(CancelledError) as e:
        run_build_subset(
            base_path=str(base.disc_root),
            src_label_paths=[("Donor", str(donor.export_root))],
            out_dir=out_dir,
            selected_song_ids={1, 2},
            needed_donors={"Donor"},
            preferred_source_by_song_id={},
            preflight_validate=False,
            block_on_errors=False,
            log_cb=lambda _m: None,
            cancel_token=None,
        )

    assert "Stop now" in str(e.value)
    assert not out_dir.exists()
