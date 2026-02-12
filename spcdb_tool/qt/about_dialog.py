from __future__ import annotations

# About dialog (internal).
#
# Extracted from `spcdb_tool.qt.main_window.MainWindow._about()` as part of the
# incremental Qt refactor. Behavior is intended to be unchanged.
#
# This module is imported lazily via `MainWindow._about()`.

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


def show_about_dialog(parent: QWidget, app_version: str) -> None:
    dlg = QDialog(parent)
    dlg.setWindowTitle("About SingStar Disc Builder")

    # Branding assets live at spcdb_tool/branding/ (sibling of this qt/ folder).
    icon_path = Path(__file__).resolve().parents[1] / "branding" / "spcdb_icon.png"

    try:
        if icon_path.exists():
            dlg.setWindowIcon(QIcon(str(icon_path)))
    except Exception:
        pass

    v = QVBoxLayout(dlg)
    v.setContentsMargins(16, 16, 16, 16)
    v.setSpacing(12)

    # Header row: icon + app name/version
    header = QHBoxLayout()
    header.setSpacing(12)

    try:
        if icon_path.exists():
            pm = QPixmap(str(icon_path))
            if not pm.isNull():
                pm = pm.scaled(96, 96, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                ico = QLabel()
                ico.setPixmap(pm)
                ico.setAlignment(Qt.AlignTop | Qt.AlignLeft)
                header.addWidget(ico)
    except Exception:
        pass

    title_html = (
        "<div>"
        "<div style='font-size:18px; font-weight:700;'>SingStar Disc Builder</div>"
        f"<div style='font-size:14px;'>Version {app_version}</div>"
        "</div>"
    )
    title_lbl = QLabel(title_html)
    title_lbl.setTextFormat(Qt.RichText)
    title_lbl.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
    header.addWidget(title_lbl, 1)

    v.addLayout(header)

    body_html = (
        "<div>"
        "Build merged disc sets for PlayStation 3 from extracted SingStar discs you legally own.<br/>"
        "This tool does not include game content or songs.<br/><br/>"
        "<b>Trademark &amp; affiliation notice:</b><br/>"
        "SingStar is a trademark of Sony Computer Entertainment Europe.<br/>"
        "PlayStation and PS3 are trademarks or registered trademarks of Sony Interactive Entertainment Inc.<br/>"
        "This project is <b>unofficial</b> and is <b>not affiliated with, endorsed by, or sponsored by</b> "
        "Sony Interactive Entertainment or its affiliates.<br/>"
        "All other trademarks are the property of their respective owners.<br/><br/>"
        "<b>License:</b> GPL-3.0<br/><br/><b>Project:</b> AltEvolutions [<a href='https://bsky.app/profile/altevolutions.uk'>Bluesky</a> | <a href='https://github.com/AltEvolutions'>GitHub</a>]<br/><br/>"
        "<b>External dependency:</b> "
        "<a href='https://github.com/EdnessP/scee-london/'>SCEE London Studio PS3 PACKAGE tool</a>, created by Edness "
        "[<a href='https://bsky.app/profile/edness.bsky.social'>Bluesky</a> | "
        "<a href='https://github.com/EdnessP'>GitHub</a>] (not bundled)<br/><br/>"
        "This tool does not include or distribute SingStar/Sony game assets. Use extracted disc content you own."
        "</div>"
    )

    lbl = QLabel(body_html)
    try:
        lbl.setTextFormat(Qt.RichText)
        lbl.setTextInteractionFlags(Qt.TextBrowserInteraction)
        lbl.setOpenExternalLinks(True)
    except Exception:
        pass
    lbl.setWordWrap(True)
    v.addWidget(lbl)

    btns = QHBoxLayout()
    btns.addStretch(1)
    btn_close = QPushButton("Close")
    btn_close.clicked.connect(dlg.accept)
    btns.addWidget(btn_close)
    v.addLayout(btns)

    dlg.exec()
