from __future__ import annotations

from pathlib import Path

import pytest

from spcdb_tool.subset import _rename_dir_with_retries


def test_rename_dir_with_retries_permissionerror_then_ok(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    src = tmp_path / "SRC_DIR"
    dst = tmp_path / "DST_DIR"
    src.mkdir()

    real_rename = Path.rename
    calls = {"n": 0}

    def _flaky_rename(self: Path, target: Path) -> Path:
        if self == src and Path(target) == dst and calls["n"] == 0:
            calls["n"] += 1
            raise PermissionError("Access is denied")
        return real_rename(self, target)

    monkeypatch.setattr(Path, "rename", _flaky_rename)

    _rename_dir_with_retries(src, dst, max_attempts=3, sleep_s=0.0)

    assert dst.is_dir()
    assert not src.exists()
