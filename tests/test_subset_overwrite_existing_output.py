from __future__ import annotations

from pathlib import Path

import pytest

from spcdb_tool.layout import resolve_input
from spcdb_tool.merge import MergeError
from spcdb_tool.subset import SubsetOptions, build_subset
from tests.fixtures.fake_disc import make_fake_disc


def test_build_subset_overwrite_existing_output_keeps_backup(tmp_path: Path) -> None:
    # Base disc provides song 1.
    base = make_fake_disc(
        tmp_path,
        label="BaseDisc",
        layout="ps3_game",
        song_ids=[1],
        include_textures=True,
        include_covers=True,
        include_chc=True,
    )

    # Donor export provides song 2.
    donor = make_fake_disc(
        tmp_path,
        label="DonorDisc",
        layout="export_only",
        song_ids=[2],
        include_textures=True,
        include_covers=True,
        include_chc=True,
    )

    base_ri = resolve_input(str(base.disc_root))
    donor_ri = resolve_input(str(donor.export_root))

    # Existing output should look like a real SSPCDB output disc folder (guardrail).
    existing = make_fake_disc(
        tmp_path,
        label="OUT_DISC",
        layout="ps3_game",
        song_ids=[99],
        include_textures=True,
        include_covers=True,
        include_chc=True,
    )

    out_dir = existing.disc_root
    (out_dir / "dummy_existing.txt").write_text("hello", encoding="utf-8")

    opts = SubsetOptions(target_version=6, mode="update-required")

    build_subset(
        base_ri,
        source_ris=[("Donor", donor_ri)],
        out_dir=out_dir,
        selected_song_ids={1, 2},
        opts=opts,
        allow_overwrite=True,
        keep_backup=True,
    )

    # New output exists.
    assert out_dir.is_dir()

    # Backup exists and contains our old marker.
    backups = sorted(tmp_path.glob("OUT_DISC.__BACKUP_*"))
    assert backups, "Expected a timestamped backup folder to be created"
    assert (backups[0] / "dummy_existing.txt").exists()


def test_build_subset_overwrite_requires_flag(tmp_path: Path) -> None:
    base = make_fake_disc(
        tmp_path,
        label="BaseDisc2",
        layout="ps3_game",
        song_ids=[1],
        include_textures=True,
        include_covers=True,
        include_chc=True,
    )
    base_ri = resolve_input(str(base.disc_root))

    out_dir = tmp_path / "OUT_EXISTS"
    out_dir.mkdir(parents=True, exist_ok=True)

    opts = SubsetOptions(target_version=6, mode="update-required")

    with pytest.raises(MergeError):
        build_subset(
            base_ri,
            source_ris=[],
            out_dir=out_dir,
            selected_song_ids={1},
            opts=opts,
        )


def test_build_subset_overwrite_refuses_non_spcdb_folder_even_with_flag(tmp_path: Path) -> None:
    base = make_fake_disc(
        tmp_path,
        label="BaseDisc3",
        layout="ps3_game",
        song_ids=[1],
        include_textures=True,
        include_covers=True,
        include_chc=True,
    )
    base_ri = resolve_input(str(base.disc_root))

    # Not an Export/disc layout; should be refused.
    out_dir = tmp_path / "NOT_A_DISC"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "notes.txt").write_text("oops", encoding="utf-8")

    opts = SubsetOptions(target_version=6, mode="update-required")

    with pytest.raises(MergeError):
        build_subset(
            base_ri,
            source_ris=[],
            out_dir=out_dir,
            selected_song_ids={1},
            opts=opts,
            allow_overwrite=True,
            keep_backup=True,
        )


def test_build_subset_overwrite_refuses_when_out_matches_base_input(tmp_path: Path) -> None:
    # If the user accidentally selects the base disc folder as output, it is a valid layout
    # but should be refused (guardrail).
    base = make_fake_disc(
        tmp_path,
        label="BaseDisc4",
        layout="ps3_game",
        song_ids=[1],
        include_textures=True,
        include_covers=True,
        include_chc=True,
    )
    base_ri = resolve_input(str(base.disc_root))

    opts = SubsetOptions(target_version=6, mode="update-required")

    with pytest.raises(MergeError):
        build_subset(
            base_ri,
            source_ris=[],
            out_dir=base.disc_root,
            selected_song_ids={1},
            opts=opts,
            allow_overwrite=True,
            keep_backup=True,
        )
