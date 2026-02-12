"""Branding-only application helpers.

This module implements the "apply ICON0/PIC1 to an existing output disc" behavior
in a UI-agnostic way, so it can be tested without Qt widgets.

Notes:
- We validate the target folder by requiring a PS3_GAME directory.
- For non-PNG sources or when resizing is requested, we rely on PySide6's QImage
  (already required by the Qt GUI). If PySide6 is unavailable and conversion is
  required, we raise BrandingError with a clear message.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Tuple

import shutil


class BrandingError(RuntimeError):
    """Raised when branding-only apply cannot proceed."""


@dataclass(frozen=True)
class BrandingApplyResult:
    disc_dir: Path
    ps3_game_dir: Path
    wrote_icon: bool
    wrote_background: bool
    icon_dst: Optional[Path] = None
    background_dst: Optional[Path] = None


def _resolve_path(p: Path | str) -> Path:
    try:
        return Path(p).expanduser().resolve()
    except Exception:
        return Path(p)


def _validate_output_disc_dir(disc_dir: Path) -> Path:
    disc_dir = _resolve_path(disc_dir)
    ps3_game = disc_dir / "PS3_GAME"
    if not ps3_game.exists() or not ps3_game.is_dir():
        raise BrandingError(f"Not a PS3 disc output folder (missing PS3_GAME): {ps3_game}")
    return ps3_game


def _write_png_qt(
    src_path: Path,
    dst_path: Path,
    *,
    target_size: Optional[Tuple[int, int]],
    pad_mode: str,
) -> None:
    """Write src image as PNG to dst, optionally resizing to target_size.

    pad_mode: 'transparent' or 'black' (used when resizing with KeepAspectRatio).
    """
    try:
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QImage, QPainter, QColor
    except Exception as e:  # pragma: no cover
        raise BrandingError(
            "PySide6 is required to convert/resize branding images. "
            "Install PySide6 or use PNG sources with autoresize disabled."
        ) from e

    img = QImage(str(src_path))
    if img.isNull():
        raise BrandingError(f"Cannot load image: {src_path}")

    dst_path.parent.mkdir(parents=True, exist_ok=True)

    if target_size is None:
        # Convert to PNG (no resize)
        if not img.save(str(dst_path), "PNG"):
            raise BrandingError(f"Failed to write PNG: {dst_path}")
        return

    tw, th = int(target_size[0]), int(target_size[1])
    scaled = img.scaled(tw, th, Qt.KeepAspectRatio, Qt.SmoothTransformation)

    canvas = QImage(tw, th, QImage.Format_ARGB32)
    if str(pad_mode or "").lower() == "black":
        canvas.fill(QColor(0, 0, 0, 255))
    else:
        canvas.fill(Qt.transparent)

    p = QPainter(canvas)
    try:
        x = int((tw - scaled.width()) // 2)
        y = int((th - scaled.height()) // 2)
        p.drawImage(x, y, scaled)
    finally:
        p.end()

    if not canvas.save(str(dst_path), "PNG"):
        raise BrandingError(f"Failed to write PNG: {dst_path}")


def _write_branding_png(
    src_path: Path,
    dst_path: Path,
    *,
    target_size: Optional[Tuple[int, int]],
    pad_mode: str,
) -> None:
    """Write a branding image to dst_path as PNG.

    Fast-path: if no resize requested and src is a .png file, copy bytes directly.
    Otherwise, use Qt's QImage backend to convert/resize.
    """
    src_path = _resolve_path(src_path)
    dst_path = _resolve_path(dst_path)

    if target_size is None and src_path.suffix.lower() == ".png":
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src_path, dst_path)
        return

    _write_png_qt(src_path, dst_path, target_size=target_size, pad_mode=pad_mode)


def apply_branding_to_existing_output(
    disc_dir: Path | str,
    *,
    icon_src: Optional[Path | str] = None,
    background_src: Optional[Path | str] = None,
    autoresize: bool = True,
    logger: Optional[Callable[[str], None]] = None,
) -> BrandingApplyResult:
    """Apply ICON0.PNG / PIC1.PNG into an already-built output disc folder.

    Returns a BrandingApplyResult describing what was written.
    """
    disc_dir_p = _resolve_path(Path(disc_dir))
    ps3_game = _validate_output_disc_dir(disc_dir_p)

    wrote_icon = False
    wrote_bg = False
    icon_dst: Optional[Path] = None
    bg_dst: Optional[Path] = None

    def _log(msg: str) -> None:
        if callable(logger):
            try:
                logger(str(msg))
            except Exception:
                pass

    if not icon_src and not background_src:
        raise BrandingError("No branding sources set (icon/background). Choose at least one image first.")

    if icon_src:
        srcp = _resolve_path(Path(icon_src))
        if not srcp.exists() or not srcp.is_file():
            raise BrandingError(f"Icon file not found: {srcp}")
        icon_dst = ps3_game / "ICON0.PNG"
        ts = (320, 176) if autoresize else None
        _write_branding_png(srcp, icon_dst, target_size=ts, pad_mode="transparent")
        wrote_icon = True
        _log(f"[branding] Wrote ICON0.PNG ({'resized' if ts else 'as-is'}): {icon_dst}")

    if background_src:
        srcp = _resolve_path(Path(background_src))
        if not srcp.exists() or not srcp.is_file():
            raise BrandingError(f"Background file not found: {srcp}")
        bg_dst = ps3_game / "PIC1.PNG"
        ts = (1920, 1080) if autoresize else None
        _write_branding_png(srcp, bg_dst, target_size=ts, pad_mode="black")
        wrote_bg = True
        _log(f"[branding] Wrote PIC1.PNG ({'resized' if ts else 'as-is'}): {bg_dst}")

    return BrandingApplyResult(
        disc_dir=disc_dir_p,
        ps3_game_dir=ps3_game,
        wrote_icon=wrote_icon,
        wrote_background=wrote_bg,
        icon_dst=icon_dst,
        background_dst=bg_dst,
    )
