from __future__ import annotations

import base64
from pathlib import Path

import pytest

from spcdb_tool.branding_apply import BrandingError, apply_branding_to_existing_output


_TINY_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/wwAAgMBg4WmKQAAAABJRU5ErkJggg=="
)


def _write_tiny_png(p: Path) -> bytes:
    data = base64.b64decode(_TINY_PNG_B64)
    p.write_bytes(data)
    return data


def test_apply_branding_writes_icon_and_background(tmp_path: Path) -> None:
    # Target disc output folder
    disc_dir = tmp_path / "OUT_DISC"
    ps3_game = disc_dir / "PS3_GAME"
    ps3_game.mkdir(parents=True)

    icon_src = tmp_path / "icon.png"
    bg_src = tmp_path / "bg.png"
    icon_bytes = _write_tiny_png(icon_src)
    bg_bytes = _write_tiny_png(bg_src)

    res = apply_branding_to_existing_output(
        disc_dir,
        icon_src=icon_src,
        background_src=bg_src,
        autoresize=False,  # copy-fast-path for PNG
    )

    assert res.wrote_icon is True
    assert res.wrote_background is True

    icon_dst = ps3_game / "ICON0.PNG"
    bg_dst = ps3_game / "PIC1.PNG"
    assert icon_dst.exists()
    assert bg_dst.exists()
    assert icon_dst.read_bytes() == icon_bytes
    assert bg_dst.read_bytes() == bg_bytes


def test_apply_branding_requires_ps3_game(tmp_path: Path) -> None:
    disc_dir = tmp_path / "NOT_A_DISC"
    disc_dir.mkdir()

    icon_src = tmp_path / "icon.png"
    _write_tiny_png(icon_src)

    with pytest.raises(BrandingError):
        apply_branding_to_existing_output(
            disc_dir,
            icon_src=icon_src,
            background_src=None,
            autoresize=False,
        )
