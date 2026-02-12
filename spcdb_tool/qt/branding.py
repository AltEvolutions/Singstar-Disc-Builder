# ruff: noqa
from __future__ import annotations

"""Disc Branding helpers (Qt path only).

Extracted from `spcdb_tool.qt.main_window.MainWindow` as part of the incremental Qt refactor.
Behavior is intended to be unchanged.

This module is imported lazily via the Qt UI path.
"""

from pathlib import Path
from typing import Any, Optional, Tuple

from ..controller import _load_settings, _save_settings


def disc_branding_base_asset_path(win: Any, fname_upper: str) -> Optional[Path]:
    """Return Base-disc PS3_GAME asset (ICON0.PNG / PIC1.PNG), or None.

    Used for previews when no custom override is set.
    """
    base_edit = getattr(win, "base_edit", None)
    base_s = ""
    try:
        if base_edit is not None:
            base_s = str(base_edit.text() or "").strip()
    except Exception:
        base_s = ""

    if not base_s:
        return None

    try:
        p = Path(base_s).expanduser().resolve()
    except Exception:
        p = Path(base_s)

    # Normalize to disc root if the user points at PS3_GAME or inside it.
    disc_root = p
    try:
        if disc_root.name.upper() == "PS3_GAME" and disc_root.parent.exists():
            disc_root = disc_root.parent
        else:
            for parent in [disc_root] + list(disc_root.parents):
                if parent.name.upper() == "PS3_GAME":
                    disc_root = parent.parent
                    break
    except Exception:
        pass

    ps3_game = disc_root / "PS3_GAME"
    try:
        if not ps3_game.is_dir():
            return None
    except Exception:
        return None

    target_u = str(fname_upper or "").strip().upper()
    if not target_u:
        return None
    try:
        for ch in ps3_game.iterdir():
            try:
                if ch.is_file() and ch.name.upper() == target_u:
                    return ch
            except Exception:
                continue
    except Exception:
        return None
    return None


def update_disc_branding_ui(win: Any) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QPixmap

    icon_edit = getattr(win, "disc_icon_path_edit", None)
    bg_edit = getattr(win, "disc_bg_path_edit", None)

    icon_s = ""
    bg_s = ""
    try:
        if icon_edit is not None:
            icon_s = str(icon_edit.text() or "").strip()
    except Exception:
        icon_s = ""
    try:
        if bg_edit is not None:
            bg_s = str(bg_edit.text() or "").strip()
    except Exception:
        bg_s = ""

    # Clear buttons are only relevant when a custom override is set.
    try:
        getattr(win, "btn_disc_icon_clear").setEnabled(bool(icon_s))
    except Exception:
        pass
    try:
        getattr(win, "btn_disc_bg_clear").setEnabled(bool(bg_s))
    except Exception:
        pass

    # -------- Icon (ICON0.PNG) effective preview --------
    icon_eff: Optional[Path] = None
    icon_src_txt = "None"
    icon_missing = False
    if icon_s:
        try:
            p = Path(icon_s).expanduser().resolve()
        except Exception:
            p = Path(icon_s)
        if p.exists():
            icon_eff = p
            icon_src_txt = "Custom"
        else:
            icon_missing = True
            icon_src_txt = "Custom (missing)"
    else:
        icon_eff = disc_branding_base_asset_path(win, "ICON0.PNG")
        if icon_eff is not None and icon_eff.exists():
            icon_src_txt = "Base (default)"

    try:
        lbl = getattr(win, "disc_icon_source_lbl", None)
        if lbl is not None:
            lbl.setText(f"Source: {icon_src_txt}")
    except Exception:
        pass

    try:
        preview = getattr(win, "disc_icon_preview_lbl", None)
        if preview is not None:
            if icon_missing:
                preview.setPixmap(QPixmap())
                preview.setText("Missing file")
            elif icon_eff is not None and icon_eff.exists():
                px = QPixmap(str(icon_eff))
                if not px.isNull():
                    preview.setPixmap(
                        px.scaled(
                            preview.size(),
                            Qt.KeepAspectRatio,
                            Qt.SmoothTransformation,
                        )
                    )
                    preview.setText("")
                else:
                    preview.setPixmap(QPixmap())
                    preview.setText("Invalid image")
            else:
                preview.setPixmap(QPixmap())
                preview.setText("No icon")
    except Exception:
        pass

    # -------- Background (PIC1.PNG) effective preview --------
    bg_eff: Optional[Path] = None
    bg_src_txt = "None"
    bg_missing = False
    if bg_s:
        try:
            p = Path(bg_s).expanduser().resolve()
        except Exception:
            p = Path(bg_s)
        if p.exists():
            bg_eff = p
            bg_src_txt = "Custom"
        else:
            bg_missing = True
            bg_src_txt = "Custom (missing)"
    else:
        bg_eff = disc_branding_base_asset_path(win, "PIC1.PNG")
        if bg_eff is not None and bg_eff.exists():
            bg_src_txt = "Base (default)"

    try:
        lbl = getattr(win, "disc_bg_source_lbl", None)
        if lbl is not None:
            lbl.setText(f"Source: {bg_src_txt}")
    except Exception:
        pass

    try:
        preview = getattr(win, "disc_bg_preview_lbl", None)
        if preview is not None:
            if bg_missing:
                preview.setPixmap(QPixmap())
                preview.setText("Missing file")
            elif bg_eff is not None and bg_eff.exists():
                px = QPixmap(str(bg_eff))
                if not px.isNull():
                    preview.setPixmap(
                        px.scaled(
                            preview.size(),
                            Qt.KeepAspectRatio,
                            Qt.SmoothTransformation,
                        )
                    )
                    preview.setText("")
                else:
                    preview.setPixmap(QPixmap())
                    preview.setText("Invalid image")
            else:
                preview.setPixmap(QPixmap())
                preview.setText("No background")
    except Exception:
        pass


def save_disc_branding_settings(win: Any) -> None:
    """Persist Disc Branding controls without touching other settings keys."""
    try:
        icon_edit = getattr(win, "disc_icon_path_edit", None)
        bg_edit = getattr(win, "disc_bg_path_edit", None)
        chk_autoresize = getattr(win, "chk_disc_branding_autoresize", None)
        chk_apply = getattr(win, "chk_disc_branding_apply", None)

        icon_s = str(icon_edit.text().strip()) if icon_edit is not None else ""
        bg_s = str(bg_edit.text().strip()) if bg_edit is not None else ""
        autoresize = bool(chk_autoresize.isChecked()) if chk_autoresize is not None else True
        apply_on_build = bool(chk_apply.isChecked()) if chk_apply is not None else True

        s = _load_settings() or {}
        s.update(
            {
                "disc_branding_icon_path": icon_s,
                "disc_branding_pic1_path": bg_s,
                "disc_branding_autoresize": autoresize,
                "disc_branding_apply_on_build": apply_on_build,
            }
        )
        _save_settings(s)
    except Exception:
        pass


def write_branding_png(
    src_path: Path,
    dst_path: Path,
    *,
    target_size: Optional[Tuple[int, int]],
    pad_mode: str,
) -> None:
    """Write src image as PNG to dst, optionally resizing to target_size.

    pad_mode: 'transparent' or 'black' (used when resizing with KeepAspectRatio).
    """
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage, QPainter, QColor

    img = QImage(str(src_path))
    if img.isNull():
        raise RuntimeError(f"Cannot load image: {src_path}")

    if target_size is None:
        # Just convert to PNG (no resize)
        if not img.save(str(dst_path), "PNG"):
            raise RuntimeError(f"Failed to write PNG: {dst_path}")
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
        raise RuntimeError(f"Failed to write PNG: {dst_path}")


def apply_disc_branding_to_output(win: Any, disc_dir: Path) -> None:
    """Apply ICON0.PNG / PIC1.PNG overrides into the built output disc folder."""
    try:
        if not bool(getattr(win, "chk_disc_branding_apply").isChecked()):
            return
    except Exception:
        return

    try:
        icon_src = str(getattr(win, "disc_icon_path_edit").text() or "").strip()
    except Exception:
        icon_src = ""
    try:
        bg_src = str(getattr(win, "disc_bg_path_edit").text() or "").strip()
    except Exception:
        bg_src = ""

    if (not icon_src) and (not bg_src):
        return

    try:
        disc_dir = Path(disc_dir).expanduser().resolve()
    except Exception:
        disc_dir = Path(disc_dir)

    ps3_game = disc_dir / "PS3_GAME"
    if not ps3_game.exists():
        try:
            win._log(f"[branding] PS3_GAME folder not found in output: {ps3_game}")
        except Exception:
            pass
        return

    try:
        autoresize = bool(getattr(win, "chk_disc_branding_autoresize").isChecked())
    except Exception:
        autoresize = True

    # Icon (ICON0.PNG)
    if icon_src:
        try:
            srcp = Path(icon_src).expanduser().resolve()
            if not srcp.exists():
                raise RuntimeError(f"Icon file not found: {srcp}")
            dstp = ps3_game / "ICON0.PNG"
            ts = (320, 176) if autoresize else None
            write_branding_png(srcp, dstp, target_size=ts, pad_mode="transparent")
            try:
                win._log(f"[branding] Wrote ICON0.PNG ({'resized' if ts else 'as-is'}): {dstp}")
            except Exception:
                pass
        except Exception as e:
            try:
                win._log(f"[branding] Icon apply failed: {e}")
            except Exception:
                pass

    # Background (PIC1.PNG)
    if bg_src:
        try:
            srcp = Path(bg_src).expanduser().resolve()
            if not srcp.exists():
                raise RuntimeError(f"Background file not found: {srcp}")
            dstp = ps3_game / "PIC1.PNG"
            ts = (1920, 1080) if autoresize else None
            write_branding_png(srcp, dstp, target_size=ts, pad_mode="black")
            try:
                win._log(f"[branding] Wrote PIC1.PNG ({'resized' if ts else 'as-is'}): {dstp}")
            except Exception:
                pass
        except Exception as e:
            try:
                win._log(f"[branding] Background apply failed: {e}")
            except Exception:
                pass
