from __future__ import annotations

import os
import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from spcdb_tool import util


@dataclass
class _D:
    a: int
    p: Path


def test_numeric_dir_and_relpath_posix() -> None:
    assert util.is_probably_numeric_dir("123") is True
    assert util.is_probably_numeric_dir("001") is True
    assert util.is_probably_numeric_dir("12a") is False
    assert util.is_probably_numeric_dir("") is False

    assert util.relpath_posix("a\\b\\c") == "a/b/c"


def test_to_jsonable_and_dumps_pretty(tmp_path: Path) -> None:
    obj = {
        "x": _D(a=1, p=tmp_path / "file.txt"),
        "lst": [Path("/tmp"), {"k": (1, 2)}],
    }
    js = util.to_jsonable(obj)
    assert isinstance(js, dict)
    assert js["x"]["a"] == 1
    assert isinstance(js["x"]["p"], str)

    s = util.dumps_pretty(obj)
    back = json.loads(s)
    assert back["x"]["a"] == 1


def test_safe_listdir_missing(tmp_path: Path) -> None:
    missing = tmp_path / "does_not_exist"
    assert util.safe_listdir(missing) == []


def test_env_bool(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("X", raising=False)
    assert util.env_bool("X", default=True) is True
    assert util.env_bool("X", default=False) is False

    monkeypatch.setenv("X", "1")
    assert util.env_bool("X") is True
    monkeypatch.setenv("X", "true")
    assert util.env_bool("X") is True
    monkeypatch.setenv("X", "yes")
    assert util.env_bool("X") is True
    monkeypatch.setenv("X", "off")
    assert util.env_bool("X") is False


def test_find_app_root_prefers_markers(tmp_path: Path) -> None:
    root = tmp_path / "APPROOT"
    nested = root / "a" / "b" / "c"
    nested.mkdir(parents=True, exist_ok=True)
    (root / "README.md").write_text("hi\n", encoding="utf-8")

    assert util.find_app_root(nested) == root


def test_detect_default_extractor_exe_preferences(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Force util.find_app_root to our temp folder.
    monkeypatch.setattr(util, "find_app_root", lambda _start=None: tmp_path)

    ext_dir = util.ensure_default_extractor_dir()
    assert ext_dir == tmp_path / "extractor"

    # 1) exact match (platform-aware ordering)
    nm_primary = "scee_london.exe" if os.name == "nt" else "scee_london"
    nm_secondary = "scee_london" if os.name == "nt" else "scee_london.exe"

    p1 = ext_dir / nm_primary
    p1.write_bytes(b"x")
    assert util.detect_default_extractor_exe() == p1
    p1.unlink()

    p2 = ext_dir / nm_secondary
    p2.write_bytes(b"x")
    assert util.detect_default_extractor_exe() == p2
    p2.unlink()

    # 2) heuristic match
    exe2 = ext_dir / "my_scee_london_tool"
    exe2.write_bytes(b"x")
    assert util.detect_default_extractor_exe() == exe2

    exe2.unlink()

    # 3) single-exe fallback
    exe3 = ext_dir / "whatever.exe"
    exe3.write_bytes(b"x")
    assert util.detect_default_extractor_exe() == exe3
