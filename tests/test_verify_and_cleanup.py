from __future__ import annotations

from pathlib import Path

import pytest

import spcdb_tool.controller as ctl

from tests.fixtures.fake_disc import make_fake_disc


def _patch_cache_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirect the persistent index cache into a temp folder for tests."""
    cache_dir = tmp_path / "_index_cache"
    monkeypatch.setattr(ctl, "_index_cache_dir", lambda: cache_dir)


def test_verify_disc_extraction_ok_and_reports_artifacts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_cache_dir(tmp_path, monkeypatch)

    disc = make_fake_disc(
        tmp_path,
        label="VerifyOK",
        layout="ps3_game",
        bank=1,
        song_ids=[1, 2],
        include_chc=False,
        include_textures=True,
        include_covers=True,
    )

    usrdir = disc.disc_root / "PS3_GAME" / "USRDIR"
    usrdir.mkdir(parents=True, exist_ok=True)
    pkd = usrdir / "Pack001.pkd"
    pkd.write_bytes(b"PKD")
    pkd_out = disc.disc_root / "Pack001.pkd_out"
    (pkd_out / "dummy.txt").parent.mkdir(parents=True, exist_ok=True)
    (pkd_out / "dummy.txt").write_text("x", encoding="utf-8")

    logs: list[str] = []
    rep = ctl.verify_disc_extraction(disc.disc_root, log_cb=logs.append)

    assert rep["ok"] is True
    assert rep["counts"]["songs"] == 2
    assert rep["counts"]["missing_song_dirs"] == 0
    assert rep["counts"]["missing_texture_pages"] == 0
    assert pkd.resolve().as_posix() in {Path(p).as_posix() for p in rep["artifacts"]["pkd_files"]}
    assert pkd_out.resolve().as_posix() in {Path(p).as_posix() for p in rep["artifacts"]["pkd_out_dirs"]}

    assert any("[verify] Export root" in s for s in logs)


def test_verify_disc_extraction_flags_missing_media_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_cache_dir(tmp_path, monkeypatch)

    disc = make_fake_disc(
        tmp_path,
        label="VerifyMissingMedia",
        layout="ps3_game",
        bank=1,
        song_ids=[1],
        include_chc=False,
        include_textures=True,
        include_covers=True,
        include_media=False,
    )

    rep = ctl.verify_disc_extraction(disc.disc_root)
    assert rep["ok"] is False
    assert rep["counts"]["missing_preview_files"] == 1
    assert rep["counts"]["missing_video_files"] == 1
    assert any("Missing preview media files" in w for w in rep["warnings"])
    assert any("Missing video media files" in w for w in rep["warnings"])


def test_verify_disc_extraction_flags_corrupt_media_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_cache_dir(tmp_path, monkeypatch)

    disc = make_fake_disc(
        tmp_path,
        label="VerifyCorruptMedia",
        layout="ps3_game",
        bank=1,
        song_ids=[1],
        include_chc=False,
        include_textures=True,
        include_covers=True,
        include_media=True,
    )

    # Break one file so it fails the MP4 sanity check.
    song_dir = disc.export_root / "1"
    (song_dir / "video.mp4").write_bytes(b"not an mp4")

    rep = ctl.verify_disc_extraction(disc.disc_root)
    assert rep["ok"] is False
    assert rep["counts"]["corrupt_video_files"] == 1
    assert any("Corrupt/unreadable video media files" in w for w in rep["warnings"])
    # Include a reason sample for debugging.
    assert rep.get("samples", {}).get("corrupt_video_samples")



def test_verify_disc_extraction_flags_missing_texture_pages(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_cache_dir(tmp_path, monkeypatch)

    disc = make_fake_disc(
        tmp_path,
        label="VerifyBad",
        layout="ps3_game",
        bank=1,
        song_ids=[1],
        include_chc=False,
        include_textures=False,
        include_covers=True,
    )

    rep = ctl.verify_disc_extraction(disc.disc_root)
    assert rep["ok"] is False
    assert rep["counts"]["missing_texture_pages"] >= 1
    assert any("Missing cover texture pages" in w for w in rep["warnings"])


def test_cleanup_extraction_artifacts_moves_to_trash(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_cache_dir(tmp_path, monkeypatch)

    disc = make_fake_disc(
        tmp_path,
        label="Cleanup",
        layout="ps3_game",
        bank=1,
        song_ids=[1],
        include_chc=False,
        include_textures=False,
        include_covers=False,
    )

    usrdir = disc.disc_root / "PS3_GAME" / "USRDIR"
    usrdir.mkdir(parents=True, exist_ok=True)
    pkd = usrdir / "PackXYZ.pkd"
    pkd.write_bytes(b"PKD")
    pkd_out = disc.disc_root / "PackXYZ.pkd_out"
    pkd_out.mkdir(parents=True, exist_ok=True)
    (pkd_out / "dummy.txt").write_text("x", encoding="utf-8")

    rep = ctl.cleanup_extraction_artifacts(
        disc.disc_root,
        include_pkd_out_dirs=True,
        include_pkd_files=True,
        delete_instead=False,
        trash_ts="TESTTS",
    )

    assert rep["trash_dir"]
    assert rep["moved_files"] >= 1
    assert rep["moved_dirs"] >= 1
    assert not pkd.exists()
    assert not pkd_out.exists()

    trash_dir = Path(str(rep["trash_dir"]))
    assert (trash_dir / disc.disc_root.name).exists()
