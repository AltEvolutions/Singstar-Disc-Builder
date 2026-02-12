# ruff: noqa
from __future__ import annotations

"""Qt Support bundle export helpers (internal).

Extracted from `spcdb_tool/qt/main_window.py` as part of the incremental Qt refactor.
Behavior is intended to be unchanged.

Imported lazily via `MainWindow`.
"""

from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtWidgets import QFileDialog, QMessageBox

from ..controller import export_support_bundle

if TYPE_CHECKING:
    from .main_window import MainWindow


def export_support_bundle_action(win: "MainWindow") -> None:
    """Export a privacy-safe support bundle zip for troubleshooting."""
    # Keep the original variable name used in main_window to minimize risk.
    self = win

    msg = (
        "<b>Support bundle will include:</b><br>"
        "• Recent logs<br>"
        "• Settings (sanitized - no extractor path)<br>"
        "• Disc states (labels + state)<br>"
        "• Cache info (counts only)<br>"
        "• System summary<br><br>"
        "<b>Will NOT include:</b><br>"
        "• Disc assets / copyrighted content<br>"
    )

    try:
        r = QMessageBox.question(
            self,
            "Export Support Bundle",
            msg + "<br><b>Redact file paths?</b> (Recommended)",
            QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
            QMessageBox.Yes,
        )
    except Exception:
        r = QMessageBox.Yes

    if r == QMessageBox.Cancel:
        return
    redact = (r == QMessageBox.Yes)

    try:
        default_name = f"spcdb_support_{datetime.now():%Y%m%d}.zip"
    except Exception:
        default_name = "spcdb_support.zip"

    try:
        start_dir = str(Path.home() / default_name)
    except Exception:
        start_dir = default_name

    try:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Support Bundle",
            start_dir,
            "ZIP files (*.zip)",
        )
    except Exception:
        path = ""

    path = str(path or "").strip()
    if not path:
        return
    if not path.lower().endswith(".zip"):
        path = path + ".zip"

    # Collect current disc states from the Sources table (best-effort).
    disc_states: list[dict] = []
    try:
        rows = int(self.sources_table.rowCount() or 0)
    except Exception:
        rows = 0

    for row in range(rows):
        try:
            label = (self.sources_table.item(row, 0).text() if self.sources_table.item(row, 0) else "").strip()
        except Exception:
            label = ""
        try:
            state = (self.sources_table.item(row, 1).text() if self.sources_table.item(row, 1) else "").strip()
        except Exception:
            state = ""
        try:
            pth = (self.sources_table.item(row, 2).text() if self.sources_table.item(row, 2) else "").strip()
        except Exception:
            pth = ""

        if not pth:
            continue
        if not label:
            try:
                label = Path(pth).name
            except Exception:
                label = "Source"
        disc_states.append({"label": label, "state": state or "unknown", "path": pth})

    try:
        res = export_support_bundle(Path(path), disc_states=disc_states, redact_paths=bool(redact))
    except Exception as e:
        try:
            QMessageBox.warning(self, "Export failed", f"Could not create support bundle:\n\n{e}")
        except Exception:
            pass
        return

    try:
        QMessageBox.information(
            self,
            "Bundle exported",
            f"Support bundle saved:\n{res.get('bundle_path')}\n\n"
            f"Size: {float(res.get('size_mb') or 0.0):.2f} MB\n"
            f"Paths redacted: {bool(res.get('redact_paths'))}",
        )
    except Exception:
        pass
