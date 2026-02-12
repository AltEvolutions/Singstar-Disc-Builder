# ruff: noqa
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QThread
from PySide6.QtWidgets import (
    QFileDialog,
    QMessageBox,
    QDialog,
    QVBoxLayout,
    QLabel,
    QProgressBar,
)

from .workers import CopyDiscWorker

if TYPE_CHECKING:
    from .main_window import MainWindow


def first_available_outdir(mw: "MainWindow", parent: Path, name: str) -> Path:
    """Return a non-existing child folder under parent, using name or name_#.

    This is used by the Copy Disc flow to avoid overwriting an existing destination.
    """
    self = mw  # keep body similarity to original method
    cand = parent / str(name)
    if not cand.exists():
        return cand
    i = 2
    while True:
        cand2 = parent / f"{name}_{i}"
        if not cand2.exists():
            return cand2
        i += 1


def start_copy_disc(mw: "MainWindow", disc_dir: Path) -> None:
    """Copy an extracted disc folder to a new destination (UI flow)."""
    self = mw  # keep body similarity to original method

    if self._any_op_running():
        self._log('[copy] Another operation is already running.')
        return
    try:
        disc_dir = Path(disc_dir).expanduser().resolve()
    except Exception:
        disc_dir = Path(disc_dir)

    if (not disc_dir.exists()) or (not disc_dir.is_dir()):
        QMessageBox.warning(self, 'Copy disc', f'Disc folder not found\n\n{disc_dir}')
        return

    dest_parent = QFileDialog.getExistingDirectory(self, "Copy disc to… (select destination parent folder)")
    if not dest_parent:
        return
    dest_parent_p = Path(dest_parent).expanduser().resolve()
    if dest_parent_p.exists() and (not dest_parent_p.is_dir()):
        self._show_critical_with_logs('Copy disc', f'Destination is not a folder\n\n{dest_parent_p}')
        return
    try:
        dest_parent_p.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        self._show_critical_with_logs('Copy disc', f'Cannot create destination folder\n\n{dest_parent_p}\n\n{e}')
        return

    dst_dir = first_available_outdir(self, dest_parent_p, disc_dir.name)

    # Simple progress dialog (indeterminate)
    dlg = QDialog(self)
    dlg.setWindowTitle("Copying disc…")
    v = QVBoxLayout(dlg)
    lbl = QLabel(f"Copying:\n{disc_dir}\n\nTo:\n{dst_dir}\n\nThis may take a while.")
    lbl.setWordWrap(True)
    v.addWidget(lbl)
    pb = QProgressBar()
    pb.setRange(0, 0)
    v.addWidget(pb)
    dlg.setModal(True)

    self._active_op = 'copy'
    self._set_op_running(True)

    t = QThread()
    w = CopyDiscWorker(src_dir=str(disc_dir), dst_dir=str(dst_dir))
    w.moveToThread(t)
    t.started.connect(w.run, Qt.QueuedConnection)
    w.log.connect(self._log)

    def _on_done(dst: str) -> None:
        self._log(f"[copy] Done: {dst}")
        try:
            dlg.accept()
        except Exception:
            pass
        QMessageBox.information(self, 'Copy disc', f'Copy complete\n\n{dst}')

    def _on_err(msg: str) -> None:
        self._log(f"[copy] ERROR: {msg}")
        try:
            dlg.reject()
        except Exception:
            pass
        self._show_critical_with_logs(
            'Copy disc failed',
            str(msg or 'Unknown error'),
            tip='Tip: Check the logs for details.',
        )

    w.done.connect(_on_done)
    w.error.connect(_on_err)

    def _finalize_copy() -> None:
        if self._copy_thread is not t:
            return
        try:
            t.quit()
        except Exception:
            pass
        self._copy_thread = None
        self._copy_worker = None
        self._active_op = None
        self._set_op_running(False)

    w.finished.connect(_finalize_copy)
    t.finished.connect(_finalize_copy)
    try:
        t.finished.connect(t.deleteLater)
        w.finished.connect(w.deleteLater)
    except Exception:
        pass

    self._copy_thread = t
    self._copy_worker = w
    t.start()

    try:
        dlg.exec()
    except Exception:
        pass
