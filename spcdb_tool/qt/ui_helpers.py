# ruff: noqa
from __future__ import annotations

"""Qt small helper utilities (internal).

Extracted from `spcdb_tool/qt/main_window.py` as part of the incremental Qt refactor.
Behavior is intended to be unchanged.

Imported lazily via `MainWindow`.
"""

from pathlib import Path

from .constants import SPCDB_QT_STATE_FILE, SPCDB_QT_WINDOW_STATE_FILE


def fmt_duration(secs: float) -> str:
    try:
        s = int(max(0, round(float(secs))))
    except Exception:
        s = 0
    h = s // 3600
    m = (s % 3600) // 60
    ss = s % 60
    if h > 0:
        return f"{h:02d}:{m:02d}:{ss:02d}"
    return f"{m:02d}:{ss:02d}"


def open_logs_folder() -> None:
    """Open the logs folder in the OS file explorer (best-effort)."""
    try:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
    except Exception:
        return

    try:
        # Get the current logs dir from the main logging module.
        from ..app_logging import current_logs_dir  # type: ignore

        p = current_logs_dir()
        if p is None:
            return
        pth = Path(p)
        try:
            pth.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

        ok = QDesktopServices.openUrl(QUrl.fromLocalFile(str(pth)))
        if not ok:
            # Fallback for Windows shells that don't like QDesktopServices.
            try:
                import os
                os.startfile(str(pth))  # type: ignore[attr-defined]
            except Exception:
                pass
    except Exception:
        # Best-effort only.
        pass


def show_msg_with_logs(
    parent,
    open_logs_cb,
    title: str,
    text: str,
    *,
    icon: str = 'critical',
    tip: str | None = None,
    details: str | None = None,
) -> None:
    # Show a message box with an 'Open logs folder' button.
    try:
        from PySide6.QtWidgets import QMessageBox
    except Exception:
        return

    msg = str(text or '').strip() or 'Unknown error'
    if tip:
        msg = msg + "\n\n" + str(tip).strip()

    dlg = QMessageBox(parent)
    try:
        if str(icon or '').lower().strip() == 'warning':
            dlg.setIcon(QMessageBox.Warning)
        else:
            dlg.setIcon(QMessageBox.Critical)
    except Exception:
        pass
    dlg.setWindowTitle(str(title or 'Message'))
    try:
        dlg.setText(msg)
    except Exception:
        pass
    if details:
        try:
            dlg.setDetailedText(str(details))
        except Exception:
            pass

    btn_logs = dlg.addButton('Open logs folder', QMessageBox.ActionRole)
    dlg.addButton(QMessageBox.Ok)

    try:
        dlg.exec()
    except Exception:
        return

    try:
        if dlg.clickedButton() == btn_logs:
            try:
                open_logs_cb()
            except Exception:
                pass
    except Exception:
        pass


def show_critical_with_logs(parent, open_logs_cb, title: str, text: str, *, tip: str | None = None, details: str | None = None) -> None:
    show_msg_with_logs(parent, open_logs_cb, title, text, icon='critical', tip=tip, details=details)


def show_warning_with_logs(parent, open_logs_cb, title: str, text: str, *, tip: str | None = None, details: str | None = None) -> None:
    show_msg_with_logs(parent, open_logs_cb, title, text, icon='warning', tip=tip, details=details)


def browse_base(win) -> None:
    try:
        from PySide6.QtWidgets import QFileDialog
    except Exception:
        return

    self = win
    d = QFileDialog.getExistingDirectory(self, 'Select Base disc folder')
    if d:
        self.base_edit.setText(str(d))
        self._log(f"Base set: {d}")


def browse_output(win) -> None:
    try:
        from PySide6.QtWidgets import QFileDialog
    except Exception:
        return

    self = win
    d = QFileDialog.getExistingDirectory(self, 'Select Output location (parent folder)')
    if d:
        self.output_edit.setText(str(d))
        self._log(f"Output location set: {d}")


def browse_extractor(win) -> None:
    try:
        from PySide6.QtWidgets import QFileDialog
    except Exception:
        return

    try:
        from ..util import default_extractor_dir
    except Exception:
        default_extractor_dir = None

    self = win

    start_dir = ''
    try:
        cur = self.extractor_edit.text().strip()
        if cur:
            cp = Path(cur)
            if cp.exists():
                start_dir = str(cp.parent)
        if not start_dir and callable(default_extractor_dir):
            start_dir = str(default_extractor_dir())
    except Exception:
        start_dir = ''

    f, _ = QFileDialog.getOpenFileName(
        self,
        'Select SCEE extractor executable',
        start_dir,
        filter='Executable (*.exe);;All Files (*)',
    )
    if f:
        self.extractor_edit.setText(str(f))
        self._log(f"Extractor set: {f}")


def qt_state_path() -> Path:
    # Store alongside the tool (portable)
    return Path(__file__).resolve().parent / SPCDB_QT_STATE_FILE


def qt_window_state_path() -> Path:
    # Store alongside the tool (portable)
    return Path(__file__).resolve().parent / SPCDB_QT_WINDOW_STATE_FILE


def show_status_message(win: object, msg: str, timeout_ms: int = 6000) -> None:
    """Best-effort status bar hint.

    Qt will show QAction/WIDGET status tips automatically on hover, but
    for important completion events we also push a short transient message.
    """

    try:
        sb = win.statusBar() if hasattr(win, 'statusBar') else None
        if sb is not None:
            sb.showMessage(str(msg or '').strip(), int(timeout_ms))
    except Exception:
        pass

