from __future__ import annotations

from pathlib import Path

import pytest

from spcdb_tool.inspect import inspect_export
from spcdb_tool.layout import resolve_input
from tests.fixtures.fake_disc import make_fake_disc


def test_resolve_input_finds_export_from_disc_root_and_ps3_game(tmp_path: Path) -> None:
    disc = make_fake_disc(tmp_path, label="DiscResolve", layout="ps3_game", include_textures=False)

    ri = resolve_input(str(disc.disc_root))
    assert ri.kind == "disc_folder"
    assert ri.export_root.resolve() == disc.export_root.resolve()
    assert any("No textures folder found" in w for w in ri.warnings)

    # Users often point the app at PS3_GAME directly; we should still resolve.
    ri2 = resolve_input(str(disc.ps3_game))
    assert ri2.kind == "disc_folder"
    assert ri2.export_root.resolve() == disc.export_root.resolve()


def test_resolve_input_finds_loose_export_root(tmp_path: Path) -> None:
    disc = make_fake_disc(tmp_path, label="ExportOnly", layout="export_only", include_textures=False)
    ri = resolve_input(str(disc.export_root))
    assert ri.kind == "export_folder"
    assert ri.export_root.resolve() == disc.export_root.resolve()


def test_inspect_export_resolves_filesystem_export_refs(tmp_path: Path) -> None:
    # Some real config.xml files use FileSystem/Export/... paths for referenced files.
    disc = make_fake_disc(
        tmp_path,
        label="InspectRefs",
        layout="ps3_game",
        ref_prefix="FileSystem/Export/",
        include_textures=False,
        include_chc=True,
    )

    warnings: list[str] = []
    report = inspect_export(disc.export_root, kind="disc_folder", input_path=str(disc.disc_root), warnings=warnings)

    assert report.product_code is not None
    assert report.max_version_in_config == 1
    assert report.counts["numeric_song_folders"] >= 1

    # These refs come from config.xml as-is; existence should still be true.
    assert report.existence["all"].get("FileSystem/Export/songs_1_0.xml") is True
    assert report.existence["all"].get("FileSystem/Export/acts_1_0.xml") is True
    assert report.existence["all"].get("FileSystem/Export/songlists_1.xml") is True
    assert report.existence["all"].get("FileSystem/Export/melodies_1.chc") is True


def test_resolve_input_missing_export_raises(tmp_path: Path) -> None:
    p = tmp_path / "EmptyFolder"
    p.mkdir(parents=True, exist_ok=True)
    with pytest.raises(FileNotFoundError):
        resolve_input(str(p))
