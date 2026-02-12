from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

import spcdb_tool.controller as ctl

from tests.fixtures.fake_disc import make_fake_disc


def test_strip_ns_and_sha1_path(tmp_path: Path) -> None:
    assert ctl._strip_ns("{ns}TAG") == "TAG"
    assert ctl._strip_ns("TAG") == "TAG"

    f = tmp_path / "x.txt"
    f.write_bytes(b"abc")
    got = ctl._sha1_path(f)
    assert got == hashlib.sha1(b"abc").hexdigest()


def test_settings_load_save_roundtrip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings_p = tmp_path / "settings.json"
    monkeypatch.setattr(ctl, "_settings_path", lambda: settings_p)

    # Missing file -> {}
    assert ctl._load_settings() == {}

    ctl._save_settings({"b": 2, "a": 1})
    loaded = ctl._load_settings()
    assert loaded == {"a": 1, "b": 2} or loaded == {"b": 2, "a": 1}

    # Corrupt JSON -> {}
    settings_p.write_text("{not json", encoding="utf-8")
    assert ctl._load_settings() == {}


def test_parse_config_and_best_bank_files(tmp_path: Path) -> None:
    disc = make_fake_disc(tmp_path, label="CFG", bank=1, include_chc=False)
    product_code, product_desc, versions = ctl._parse_config(disc.export_root)

    assert product_code is not None
    assert product_desc is not None
    assert versions == [1]

    # Add a higher bank and ensure best-bank selection works.
    (disc.export_root / "songs_2_0.xml").write_text(
        (disc.export_root / "songs_1_0.xml").read_text(encoding="utf-8"), encoding="utf-8"
    )
    (disc.export_root / "acts_2_0.xml").write_text('<ACTS xmlns="http://www.singstargame.com"></ACTS>\n', encoding="utf-8")

    bank, songs_p, acts_p = ctl._best_bank_files(disc.export_root, preferred_bank=99)
    assert bank == 2
    assert songs_p is not None and songs_p.name == "songs_2_0.xml"
    assert acts_p is not None and acts_p.name == "acts_2_0.xml"

    # Preferred bank exists -> prefer it.
    bank2, songs_p2, acts_p2 = ctl._best_bank_files(disc.export_root, preferred_bank=1)
    assert bank2 == 1
    assert songs_p2 is not None and songs_p2.name == "songs_1_0.xml"
    assert acts_p2 is not None and acts_p2.name == "acts_1_0.xml"


def test_extract_song_ids_count_and_minimal_export_scan(tmp_path: Path) -> None:
    disc = make_fake_disc(tmp_path, label="SCAN", include_chc=True, include_textures=True)

    assert ctl._extract_song_ids_count(disc.export_root / "songs_1_0.xml") == 2

    scan = ctl._minimal_export_scan(disc.export_root)
    assert scan["numeric_song_folders"] == 2
    assert scan["songs_xml_files"] == 1
    assert scan["banks_from_songs_xml"] == 1
    assert scan["melodies_chc_files"] == 1
    assert scan["texture_pages"] >= 1


def test_bundle_redaction_and_log_copy_capped(tmp_path: Path) -> None:
    tok1 = ctl._bundle_redact_token("C:/secret/path")
    tok2 = ctl._bundle_redact_token("C:/secret/path")
    tok3 = ctl._bundle_redact_token("D:/other")
    assert tok1 == tok2
    assert tok1 != tok3
    assert tok1.startswith("<path_") and tok1.endswith(">")

    settings = {
        "extractor_exe_path": "C:/extractor/scee_london.exe",
        "base_path": "C:/users/dan/discs",
        "nested": {"output_path": "D:/out", "keep": 1},
        "paths": ["X:/a", "Y:/b"],
    }
    s2 = ctl._sanitize_settings_for_bundle(settings, redact_paths=True)
    assert "extractor_exe_path" not in s2
    assert isinstance(s2["base_path"], str) and s2["base_path"].startswith("<path_")
    assert isinstance(s2["nested"]["output_path"], str) and s2["nested"]["output_path"].startswith("<path_")
    assert s2["nested"]["keep"] == 1

    # _copy_log_file_capped: full copy
    src = tmp_path / "a.log"
    src.write_bytes(b"hello\n")
    dst = tmp_path / "b.log"
    note = ctl._copy_log_file_capped(src, dst, max_log_bytes=1024)
    assert note == "full"
    assert dst.read_bytes() == src.read_bytes()

    # large log tail copy
    big = tmp_path / "big.log"
    big.write_bytes(b"x" * 500)
    tail = tmp_path / "tail.log"
    note2 = ctl._copy_log_file_capped(big, tail, max_log_bytes=50)
    assert note2.startswith("tail(")
    assert tail.stat().st_size <= 50
