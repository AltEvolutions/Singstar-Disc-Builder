from __future__ import annotations

from pathlib import Path

from spcdb_tool.layout import resolve_input
from spcdb_tool.subset import _compute_copy_root_and_rel_export, _delete_unselected_song_folders
from tests.conftest import write_min_config


def test_subset_compute_copy_root_prefers_disc_root_when_ps3_game_present(tmp_path: Path) -> None:
    disc_root = tmp_path / "DISCROOT"
    export_root = disc_root / "PS3_GAME" / "USRDIR" / "FileSystem" / "Export"
    write_min_config(export_root, product_code="TEST", product_desc="Test Disc", bank=1)

    ri = resolve_input(str(disc_root))
    copy_root, rel_export = _compute_copy_root_and_rel_export(ri)

    assert copy_root.resolve() == disc_root.resolve()
    assert rel_export.as_posix().endswith("PS3_GAME/USRDIR/FileSystem/Export")


def test_subset_compute_copy_root_when_user_selected_ps3_game(tmp_path: Path) -> None:
    disc_root = tmp_path / "DISCROOT"
    export_root = disc_root / "PS3_GAME" / "USRDIR" / "FileSystem" / "Export"
    write_min_config(export_root, product_code="TEST", product_desc="Test Disc", bank=1)

    ri = resolve_input(str(disc_root / "PS3_GAME"))
    copy_root, rel_export = _compute_copy_root_and_rel_export(ri)

    assert copy_root.resolve() == disc_root.resolve()
    assert rel_export.as_posix().endswith("PS3_GAME/USRDIR/FileSystem/Export")


def test_subset_delete_unselected_song_folders(tmp_path: Path) -> None:
    export_root = tmp_path / "Export"
    export_root.mkdir(parents=True, exist_ok=True)
    for name in ["1", "2", "3", "ABC", "004"]:
        (export_root / name).mkdir(parents=True, exist_ok=True)

    _delete_unselected_song_folders(export_root, keep_song_ids={2, 4})

    assert (export_root / "2").exists()
    assert (export_root / "004").exists()  # 004 -> int 4 should be kept
    assert (export_root / "ABC").exists()  # non-numeric should be untouched
    assert not (export_root / "1").exists()
    assert not (export_root / "3").exists()
