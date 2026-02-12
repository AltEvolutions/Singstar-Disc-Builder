from __future__ import annotations

import time
from pathlib import Path

import pytest

import spcdb_tool.controller as ctl
from spcdb_tool.controller import DiscIndex

from tests.fixtures.fake_disc import make_fake_disc


def _patch_cache_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect the persistent index cache into a temp folder for tests."""
    cache_dir = tmp_path / "_index_cache"
    monkeypatch.setattr(ctl, "_index_cache_dir", lambda: cache_dir)
    return cache_dir


def test_index_cache_roundtrip_and_status(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_cache_dir(tmp_path, monkeypatch)

    disc = make_fake_disc(tmp_path, label="DISC1", include_chc=False)
    idx = DiscIndex(
        input_path=str(disc.disc_root),
        export_root=str(disc.export_root),
        product_code="DISC1",
        product_desc="DISC1 disc",
        max_bank=1,
        chosen_bank=1,
        songs_xml=str(disc.export_root / "songs_1_0.xml"),
        acts_xml=str(disc.export_root / "acts_1_0.xml"),
        song_count=2,
        warnings=[],
    )
    songs = {1: ("Song 1", "Artist 1"), 2: ("Song 2", "Artist 2")}

    ctl._write_index_cache(idx, songs=songs)

    idx2, songs2, stale, reason = ctl._load_index_cache(str(disc.disc_root))
    assert stale is False
    assert reason == "ok"
    assert idx2 is not None
    assert idx2.export_root == idx.export_root
    assert idx2.chosen_bank == 1
    assert songs2 == songs

    st = ctl.get_index_cache_status(str(disc.disc_root))
    assert st["exists"] is True
    assert st["stale"] is False
    assert st["has_songs"] is True
    assert st["song_count"] == 2


def test_index_cache_detects_stale_signature(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_cache_dir(tmp_path, monkeypatch)

    disc = make_fake_disc(tmp_path, label="DISC2", include_chc=False)
    idx = DiscIndex(
        input_path=str(disc.disc_root),
        export_root=str(disc.export_root),
        product_code="DISC2",
        product_desc="DISC2 disc",
        max_bank=1,
        chosen_bank=1,
        songs_xml=str(disc.export_root / "songs_1_0.xml"),
        acts_xml=str(disc.export_root / "acts_1_0.xml"),
        song_count=2,
        warnings=[],
    )

    ctl._write_index_cache(idx, songs=None)

    # Change a signature-tracked file (size change guarantees a diff).
    cfg = disc.export_root / "config.xml"
    cfg.write_text(cfg.read_text(encoding="utf-8") + "\n<!-- changed -->\n", encoding="utf-8")
    time.sleep(0.01)

    idx2, songs2, stale, reason = ctl._load_index_cache(str(disc.disc_root))
    assert idx2 is None
    assert songs2 is None
    assert stale is True
    assert "signature" in reason

    st = ctl.get_index_cache_status(str(disc.disc_root))
    assert st["exists"] is True
    assert st["stale"] is True


def test_clear_index_cache_removes_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cache_dir = _patch_cache_dir(tmp_path, monkeypatch)

    disc = make_fake_disc(tmp_path, label="DISC3", include_chc=False)
    idx = DiscIndex(
        input_path=str(disc.disc_root),
        export_root=str(disc.export_root),
        product_code="DISC3",
        product_desc="DISC3 disc",
        max_bank=1,
        chosen_bank=1,
        songs_xml=str(disc.export_root / "songs_1_0.xml"),
        acts_xml=str(disc.export_root / "acts_1_0.xml"),
        song_count=2,
        warnings=[],
    )

    ctl._write_index_cache(idx)
    assert list(cache_dir.glob("*.json"))

    ok, _msg = ctl.clear_index_cache()
    assert ok is True
    assert not list(cache_dir.glob("*.json"))


def test_locate_ps3_usrdir_under_wrapper(tmp_path: Path) -> None:
    wrapper = tmp_path / "WRAPPER"
    wrapper.mkdir(parents=True, exist_ok=True)

    disc = make_fake_disc(wrapper, label="INNER_DISC", layout="ps3_game")
    found = ctl._locate_ps3_usrdir_under(wrapper)
    assert found is not None
    assert found == disc.ps3_game / "USRDIR"


def test_covers_mapping_and_texture_page_exists(tmp_path: Path) -> None:
    disc = make_fake_disc(tmp_path, include_covers=True, include_textures=True)

    mapping = ctl._covers_song_to_page(disc.export_root)
    assert mapping[1] == 0
    assert mapping[2] == 0

    tex = disc.export_root / "textures"
    assert ctl._texture_page_exists(tex, 0) is True
    assert ctl._texture_page_exists(tex, 1) is False


def test_sanitize_console_line_removes_ansi_and_control_chars() -> None:
    s = "\x1b[31mRed\x1b[0m\x00\tOK �\n"
    out = ctl.sanitize_console_line(s)
    assert "Red" in out
    assert "\x1b" not in out
    assert "\x00" not in out
    assert "\t" in out
    assert "�" not in out


def test_decode_bytes_uses_candidates_then_fallback() -> None:
    assert ctl._decode_bytes("hello".encode("utf-8"), ["utf-8"]) == "hello"
    # Invalid UTF-8 should fall back (and never raise).
    out = ctl._decode_bytes(b"\xff\xfe\xfa", ["utf-8"])
    assert isinstance(out, str)
    assert out
