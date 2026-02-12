from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest

import spcdb_tool.controller as ctl

from tests.fixtures.fake_disc import make_fake_disc


def _patch_cache_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect the persistent index cache into a temp folder for tests."""
    cache_dir = tmp_path / "_index_cache"
    monkeypatch.setattr(ctl, "_index_cache_dir", lambda: cache_dir)
    return cache_dir


def test_index_disc_uses_persistent_cache_when_valid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_cache_dir(tmp_path, monkeypatch)

    disc = make_fake_disc(tmp_path, label="CACHE_DISC", include_chc=False, song_ids=[1])

    idx1 = ctl.index_disc(str(disc.disc_root))
    st1 = ctl.get_index_cache_status(str(disc.disc_root))
    assert st1["exists"] is True
    assert st1["stale"] is False

    def _boom(*_a: Any, **_kw: Any) -> Any:
        raise AssertionError("resolve_input should not be called when cache is valid")

    # If the cache is valid, index_disc should return before resolving input paths.
    monkeypatch.setattr(ctl, "resolve_input", _boom)

    idx2 = ctl.index_disc(str(disc.disc_root))
    assert idx2.export_root == idx1.export_root
    assert idx2.chosen_bank == idx1.chosen_bank
    assert idx2.songs_xml == idx1.songs_xml
    assert idx2.acts_xml == idx1.acts_xml


def test_index_disc_reindexes_when_cache_stale(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_cache_dir(tmp_path, monkeypatch)

    disc = make_fake_disc(tmp_path, label="STALE_DISC", include_chc=False, song_ids=[1])

    _idx1 = ctl.index_disc(str(disc.disc_root))

    # Change a signature-tracked file (size change guarantees a diff).
    songs_xml = disc.export_root / "songs_1_0.xml"
    songs_xml.write_text(songs_xml.read_text(encoding="utf-8") + "\n" + ("X" * 2000), encoding="utf-8")
    time.sleep(0.01)

    called = {"n": 0}
    orig = ctl.resolve_input

    def _wrap(p: str) -> Any:
        called["n"] += 1
        return orig(p)

    monkeypatch.setattr(ctl, "resolve_input", _wrap)

    _idx2 = ctl.index_disc(str(disc.disc_root))
    assert called["n"] >= 1

    st = ctl.get_index_cache_status(str(disc.disc_root))
    assert st["exists"] is True
    assert st["stale"] is False
