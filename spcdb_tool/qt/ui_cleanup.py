# ruff: noqa
from __future__ import annotations

"""Qt Cleanup tool handlers (internal).

This module contains the heavy-lifting bodies for Cleanup operations:
- Cleanup triggered from Extract flows (cleanup artifacts in selected disc folders)
- Tools → Cleanup PKD artifacts… (scan + preview + optional trash-empty + cleanup)

MainWindow keeps thin wrapper methods that delegate here, to keep `main_window.py`
smaller while preserving behavior.
"""

from pathlib import Path
from typing import List, Optional, Tuple

from PySide6.QtCore import Qt, QThread
from PySide6.QtWidgets import QFileDialog, QMessageBox, QDialog, QVBoxLayout, QLabel, QLineEdit, QHBoxLayout, QPushButton

from ..controller import CancelToken
from .workers import CleanupWorker, ScanWorker, ArtifactsPreviewWorker
def start_cleanup_targets(mw, disc_roots: List[str], *, include_pkd_files: bool) -> None:
    if mw._any_op_running():
        mw._log("[cleanup] Another operation is already running.")
        return

    targets = [str(x) for x in (disc_roots or []) if str(x or "").strip()]
    if not targets:
        QMessageBox.information(mw, "Cleanup", "No discs to clean up.")
        return

    mw._active_op = "cleanup"
    mw._cancel_token = CancelToken()
    mw._set_op_running(True)

    mw._log(f"[cleanup] Starting ({len(targets)} disc(s))...")
    for p in targets:
        mw._log(f"[cleanup] - {p}")

    t = QThread()
    w = CleanupWorker(targets, include_pkd_files=bool(include_pkd_files), delete_instead=False, cancel_token=mw._cancel_token)
    w.moveToThread(t)

    t.started.connect(w.run, Qt.QueuedConnection)
    w.log.connect(mw._log)

    w.done.connect(mw._on_cleanup_done)
    w.cancelled.connect(mw._on_cleanup_cancelled)
    w.error.connect(mw._on_cleanup_error)

    def _finalize_cleanup() -> None:
        if mw._cleanup_thread is not t:
            return
        try:
            t.quit()
        except Exception:
            pass
        if str(mw._active_op or "") != "cleanup":
            return
        mw._cleanup_thread = None
        mw._cleanup_worker = None
        mw._cancel_token = None
        mw._set_op_running(False)
        mw._active_op = None

    w.finished.connect(_finalize_cleanup)
    t.finished.connect(_finalize_cleanup)
    try:
        t.finished.connect(t.deleteLater)
        w.finished.connect(w.deleteLater)
    except Exception:
        pass

    mw._cleanup_thread = t
    mw._cleanup_worker = w
    t.start()


def cleanup_cleanup(mw) -> None:
    try:
        if mw._cleanup_thread is not None:
            mw._cleanup_thread.quit()
            if QThread.currentThread() is not mw._cleanup_thread:
                mw._cleanup_thread.wait(1500)
    except Exception:
        pass
    mw._cleanup_thread = None
    mw._cleanup_worker = None
    mw._cancel_token = None
    mw._set_op_running(False)
    mw._active_op = None


def on_cleanup_tool_done(mw, results: object) -> None:
    n = 0
    moved_dirs = 0
    moved_files = 0
    deleted_dirs = 0
    deleted_files = 0
    trash_dirs: list[str] = []

    rl: list = []
    trash_emptied: dict = {}
    try:
        if isinstance(results, dict):
            trash_emptied = dict((results or {}).get('trash_emptied') or {})
            rl = list((results or {}).get('results') or [])
        else:
            rl = list(results or [])
        n = len(rl)
        for r in rl:
            res = (r or {}).get("result") or {}
            try:
                moved_dirs += int(res.get("moved_dirs") or 0)
            except Exception:
                pass
            try:
                moved_files += int(res.get("moved_files") or 0)
            except Exception:
                pass
            try:
                deleted_dirs += int(res.get("deleted_dirs") or 0)
            except Exception:
                pass
            try:
                deleted_files += int(res.get("deleted_files") or 0)
            except Exception:
                pass
            try:
                td = res.get("trash_dir", None)
                if td:
                    trash_dirs.append(str(td))
            except Exception:
                pass
    except Exception:
        rl = []

    uniq_trash = []
    try:
        uniq_trash = list(dict.fromkeys([x for x in trash_dirs if x]))
    except Exception:
        uniq_trash = []

    mw._log(
        f"[cleanup] Done. Discs={n} | moved dirs={moved_dirs} files={moved_files} | deleted dirs={deleted_dirs} files={deleted_files}"
    )
    try:
        mw._refresh_source_states()
    except Exception:
        pass
    mw._cleanup_cleanup()

    # Show a completion dialog with an "Open trash folder" option (when in MOVE mode).
    try:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtWidgets import (
            QComboBox,
            QDialog,
            QDialogButtonBox,
            QHBoxLayout,
            QLabel,
            QPushButton,
            QVBoxLayout,
        )

        dlg = QDialog(mw)
        dlg.setWindowTitle("Cleanup complete")
        lay = QVBoxLayout(dlg)

        msg = (
            f"Discs processed: {n}\n\n"
            f"Moved folders: {moved_dirs}\n"
            f"Moved files: {moved_files}\n"
        )
        if deleted_dirs or deleted_files:
            msg += (
                f"\nDeleted folders: {deleted_dirs}\n"
                f"Deleted files: {deleted_files}\n"
                "\nNOTE: Deleted items cannot be restored."
            )

        # Optional: trash empty stats (applies when the user selected "Empty trash").
        try:
            te = int((trash_emptied or {}).get("deleted_entries", 0) or 0)
        except Exception:
            te = 0
        if te > 0:
            try:
                tf = int((trash_emptied or {}).get("deleted_files", 0) or 0)
            except Exception:
                tf = 0
            try:
                td = int((trash_emptied or {}).get("deleted_dirs", 0) or 0)
            except Exception:
                td = 0
            tp = str((trash_emptied or {}).get("trash_dir", "") or "").strip()
            msg += (
                f"\n\nTrash emptied (before cleanup): entries={te} files={tf} dirs={td}\n"
                + (f"Trash folder: {tp}\n" if tp else "")
                + "NOTE: Emptying trash is permanent."
            )

        lbl = QLabel(msg)
        lbl.setWordWrap(True)
        lay.addWidget(lbl)

        if uniq_trash:
            lay.addWidget(QLabel("Trash folder:"))
            row = QHBoxLayout()
            cb = QComboBox(dlg)
            for p in uniq_trash:
                cb.addItem(str(p))
            btn_open = QPushButton("Open folder", dlg)

            def _open_selected() -> None:
                try:
                    p = str(cb.currentText() or "").strip()
                    if p:
                        QDesktopServices.openUrl(QUrl.fromLocalFile(p))
                except Exception:
                    pass

            try:
                btn_open.clicked.connect(_open_selected)
            except Exception:
                pass

            row.addWidget(cb, 1)
            row.addWidget(btn_open)
            lay.addLayout(row)

        btns = QDialogButtonBox(QDialogButtonBox.Close)
        btns.rejected.connect(dlg.reject)
        btns.accepted.connect(dlg.accept)
        lay.addWidget(btns)

        dlg.exec()
    except Exception:
        pass

    # If an extract requested a song refresh after cleanup, do it now.
    try:
        pending = list(getattr(mw, '_pending_auto_refresh_roots', []) or [])
    except Exception:
        pending = []
    try:
        mw._pending_auto_refresh_roots = []
    except Exception:
        pass
    if pending:
        try:
            mw._auto_refresh_songs_for_roots(pending)
        except Exception:
            pass


def on_cleanup_tool_cancelled(mw) -> None:
    mw._log("[cleanup] Cancelled.")
    mw._cleanup_cleanup()


def on_cleanup_tool_error(mw, msg: str) -> None:
    mw._log(f"[cleanup] ERROR: {msg}")
    mw._show_critical_with_logs("Cleanup failed", str(msg or "Unknown error"), tip="Tip: Check the logs. Any moved files should be in _spcdb_trash inside your discs folder.")
    mw._cleanup_cleanup()


def confirm_permanent_delete_cleanup(mw, *, disc_count: int, mode_txt: str) -> bool:
    # Returns True only if the user explicitly confirms irreversible deletion.
    try:
        dlg = QDialog(mw)
        dlg.setWindowTitle("Confirm permanent delete")
        v = QVBoxLayout()
        dlg.setLayout(v)
        lbl = QLabel(
            f"You are about to PERMANENTLY DELETE PKD artifacts for {disc_count} disc folder(s).\n\n"
            f"Mode: {mode_txt}\n\n"
            "This cannot be undone.\n\n"
            "Type DELETE to enable the Delete button."
        )
        try:
            lbl.setWordWrap(True)
        except Exception:
            pass
        v.addWidget(lbl)
        edit = QLineEdit()
        try:
            edit.setPlaceholderText("Type DELETE")
        except Exception:
            pass
        v.addWidget(edit)

        h = QHBoxLayout()
        btn_cancel = QPushButton("Cancel")
        btn_ok = QPushButton("Delete permanently")
        try:
            btn_ok.setEnabled(False)
        except Exception:
            pass

        def _sync_btn(_t: str) -> None:
            try:
                btn_ok.setEnabled((_t or '').strip().upper() == 'DELETE')
            except Exception:
                pass

        try:
            edit.textChanged.connect(_sync_btn)
        except Exception:
            pass
        try:
            btn_cancel.clicked.connect(dlg.reject)
            btn_ok.clicked.connect(dlg.accept)
        except Exception:
            pass

        h.addWidget(btn_cancel)
        try:
            h.addStretch(1)
        except Exception:
            pass
        h.addWidget(btn_ok)
        v.addLayout(h)

        try:
            edit.setFocus()
        except Exception:
            pass

        r = dlg.exec()
        if r != QDialog.Accepted:
            return False

        # Final yes/no, just in case.
        try:
            msg = (
                f"Really permanently delete PKD artifacts for {disc_count} disc folder(s)?\n\n"
                "This cannot be undone."
            )
            rr = QMessageBox.question(
                mw,
                "Final confirm",
                msg,
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            return rr == QMessageBox.Yes
        except Exception:
            return True
    except Exception:
        return False


def cleanup_pkd_artifacts_action(mw) -> None:
    """Tools → Cleanup PKD artifacts… (destructive).

    Moves pkd_out dirs (and optionally Pack*.pkd files) into _spcdb_trash folders under each detected disc root. You can optionally enable PERMANENT DELETE at the final confirmation step.
    """
    if mw._any_op_running():
        mw._log("[cleanup] Another operation is already running.")
        return

    root_dir = QFileDialog.getExistingDirectory(mw, "Cleanup PKD artifacts (choose a folder to scan)")
    if not root_dir:
        return

    # Obvious destructive warning
    # NOTE: We avoid QMessageBox custom ActionRole buttons here because we've seen
    # native Qt crashes (Qt6Core.dll) on some Windows setups when choosing the
    # "pkd_out + pkd" option. A small QDialog with radio buttons is much safer.
    include_pkd_files = False
    try:
        from PySide6.QtWidgets import QRadioButton, QDialogButtonBox, QCheckBox

        dlg = QDialog(mw)
        dlg.setWindowTitle("Cleanup PKD artifacts (destructive)")
        lay = QVBoxLayout(dlg)

        intro = QLabel(
            "This will MOVE packed-disc extraction leftovers out of your disc folders.\n"
            "This includes Pack*.pkd_out folders and Pack*.pkd files.\n\n"
            "Artifacts will be moved into:\n"
            "  <discs_folder>/_spcdb_trash/<timestamp>/<disc_folder>/\n\n"
            "This changes your disc folders, but it does NOT permanently delete files.\n"
            "You can restore by moving items back out of _spcdb_trash.\n\n"
            "Choose what to cleanup:"
        )
        intro.setWordWrap(True)
        lay.addWidget(intro)

        rb_pkd_out = QRadioButton("Cleanup pkd_out only (recommended)")
        rb_both = QRadioButton("Cleanup Pack*.pkd_out folders + Pack*.pkd files (also removes original PKDs)")
        rb_pkd_out.setChecked(True)
        lay.addWidget(rb_pkd_out)
        lay.addWidget(rb_both)

        tip = QLabel("Tip: If you want to re-extract later, keep the .pkd files.")
        tip.setWordWrap(True)
        lay.addWidget(tip)

        # Optional: empty existing _spcdb_trash before cleanup (permanent delete).
        # We show this option up-front; actual trash folders will be derived from detected disc roots later.
        cb_empty_trash = None
        try:
            cb_empty_trash = QCheckBox("Empty existing _spcdb_trash before cleanup (permanent delete)")
            lay.addWidget(cb_empty_trash)

            trash_base = Path(str(root_dir)) / "_spcdb_trash"
            entries = 0
            if trash_base.exists() and trash_base.is_dir():
                try:
                    entries = sum(1 for _ in trash_base.iterdir())
                except Exception:
                    entries = 0
                lbl_trash = QLabel(f"Trash folder (under selected folder): {trash_base}\nEntries: {entries}")
            else:
                lbl_trash = QLabel(
                    f"No _spcdb_trash found under the selected folder ({root_dir}).\n"
                    "If your disc folders live in a subfolder, we will also look for _spcdb_trash alongside each detected disc root."
                )
            lbl_trash.setWordWrap(True)
            lay.addWidget(lbl_trash)

            hint = QLabel("Note: Emptying trash is permanent and will require typing DELETE in the final confirmation.")
            hint.setWordWrap(True)
            lay.addWidget(hint)
        except Exception:
            cb_empty_trash = None

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        lay.addWidget(btns)

        if dlg.exec() != QDialog.Accepted:
            return
        include_pkd_files = bool(rb_both.isChecked())

        empty_trash_first = False
        try:
            empty_trash_first = bool(cb_empty_trash.isChecked()) if cb_empty_trash is not None else False
        except Exception:
            empty_trash_first = False
    except Exception:
        # If dialog fails, default to the safer option.
        include_pkd_files = False
        empty_trash_first = False

    mw._active_op = "cleanup_scan"
    mw._cancel_token = CancelToken()
    mw._set_op_running(True)

    mw._log(f"[cleanup] Scanning for disc folders under: {root_dir}")

    mw._cleanup_scan_thread = QThread()
    mw._cleanup_scan_worker = ScanWorker(str(root_dir), max_depth=6, cancel_token=mw._cancel_token)
    mw._cleanup_scan_worker.moveToThread(mw._cleanup_scan_thread)

    mw._cleanup_scan_thread.started.connect(mw._cleanup_scan_worker.run, Qt.QueuedConnection)
    mw._cleanup_scan_worker.log.connect(mw._log)

    # When scan completes, start cleanup
    mw._cleanup_scan_root_dir = str(root_dir)
    mw._cleanup_scan_include_pkd_files = bool(include_pkd_files)
    mw._cleanup_scan_empty_trash_first = bool(empty_trash_first)
    mw._cleanup_scan_worker.done.connect(mw._on_cleanup_scan_done_worker, Qt.QueuedConnection)
    mw._cleanup_scan_worker.cancelled.connect(mw._on_cleanup_scan_cancelled, Qt.QueuedConnection)
    mw._cleanup_scan_worker.error.connect(mw._on_cleanup_scan_error, Qt.QueuedConnection)

    try:
        mw._cleanup_scan_thread.finished.connect(mw._cleanup_scan_thread.deleteLater)
        mw._cleanup_scan_worker.finished.connect(mw._cleanup_scan_worker.deleteLater)
    except Exception:
        pass

    mw._cleanup_scan_thread.start()


def cleanup_cleanup_scan(mw) -> None:
    """Stop and clear the background scan thread used by Tools → Cleanup PKD artifacts."""
    try:
        t = getattr(mw, "_cleanup_scan_thread", None)
        if t is not None:
            try:
                t.quit()
            except Exception:
                pass
            try:
                if QThread.currentThread() is not t:
                    t.wait(1500)
            except Exception:
                pass
    except Exception:
        pass
    try:
        mw._cleanup_scan_thread = None
        mw._cleanup_scan_worker = None
        mw._cleanup_scan_root_dir = None
        mw._cleanup_scan_include_pkd_files = None
        mw._cleanup_scan_empty_trash_first = None
    except Exception:
        pass


def cleanup_cleanup_preview(mw) -> None:
    """Stop and clear the background preview thread used by Tools → Cleanup PKD artifacts."""
    # IMPORTANT: On some Qt/PySide6 setups, calling close() on a QProgressDialog can
    # emit its canceled signal. If that canceled handler cancels our token, the actual
    # cleanup run can immediately abort as 'Cancelled'. We therefore disconnect/block
    # signals before closing.
    try:
        dlg = getattr(mw, "_cleanup_preview_progress", None)
        if dlg is not None:
            try:
                dlg.canceled.disconnect(mw._on_cleanup_preview_progress_cancelled)
            except Exception:
                pass
            try:
                dlg.blockSignals(True)
            except Exception:
                pass
            try:
                dlg.close()
            except Exception:
                pass
            try:
                dlg.blockSignals(False)
            except Exception:
                pass
    except Exception:
        pass
    try:
        t = getattr(mw, "_cleanup_preview_thread", None)
        if t is not None:
            try:
                t.quit()
            except Exception:
                pass
            try:
                if QThread.currentThread() is not t:
                    t.wait(1500)
            except Exception:
                pass
    except Exception:
        pass
    try:
        mw._cleanup_preview_thread = None
        mw._cleanup_preview_worker = None
        mw._cleanup_preview_progress = None
        mw._cleanup_preview_paths = None
        mw._cleanup_preview_include_pkd_files = None
        mw._cleanup_preview_mode_txt = None
    except Exception:
        pass


def on_cleanup_preview_progress_cancelled(mw) -> None:
    try:
        mw._log("[cleanup] Preview cancelled by user.")
    except Exception:
        pass
    # Cancel ONLY the preview token. The real cleanup run uses its own token.
    try:
        tok = getattr(mw, "_cleanup_preview_cancel_token", None)
        if tok is not None:
            tok.cancel()
    except Exception:
        pass


def start_cleanup_preview(mw, paths: list[str], *, mode_txt: str, include_pkd_files: bool) -> None:
    """Compute a per-disc preview (counts + sample paths), then show a final confirm dialog."""
    try:
        tok = getattr(mw, "_cancel_token", None)
        if tok is None:
            tok = CancelToken()
            mw._cancel_token = tok
    except Exception:
        tok = CancelToken()
        mw._cancel_token = tok

    # Non-blocking “busy” dialog with a Cancel button.
    try:
        from PySide6.QtWidgets import QProgressDialog

        pd = QProgressDialog("Scanning for PKD artifacts…", "Cancel", 0, 0, mw)
        pd.setWindowTitle("Cleanup PKD artifacts")
        pd.setWindowModality(Qt.ApplicationModal)
        try:
            pd.canceled.connect(mw._on_cleanup_preview_progress_cancelled)
        except Exception:
            pass
        try:
            pd.show()
        except Exception:
            pass
        mw._cleanup_preview_progress = pd
    except Exception:
        mw._cleanup_preview_progress = None

    mw._log(f"[cleanup] Preparing preview for {len(paths)} disc folder(s)…")

    mw._cleanup_preview_thread = QThread()
    preview_tok = CancelToken()
    try:
        mw._cleanup_preview_cancel_token = preview_tok
    except Exception:
        pass

    mw._cleanup_preview_worker = ArtifactsPreviewWorker(list(paths), cancel_token=preview_tok)
    mw._cleanup_preview_worker.moveToThread(mw._cleanup_preview_thread)

    mw._cleanup_preview_thread.started.connect(mw._cleanup_preview_worker.run, Qt.QueuedConnection)
    mw._cleanup_preview_worker.log.connect(mw._log)
    mw._cleanup_preview_worker.done.connect(mw._on_cleanup_preview_done, Qt.QueuedConnection)
    mw._cleanup_preview_worker.cancelled.connect(mw._on_cleanup_preview_cancelled, Qt.QueuedConnection)
    mw._cleanup_preview_worker.error.connect(mw._on_cleanup_preview_error, Qt.QueuedConnection)

    try:
        mw._cleanup_preview_thread.finished.connect(mw._cleanup_preview_thread.deleteLater)
        mw._cleanup_preview_worker.finished.connect(mw._cleanup_preview_worker.deleteLater)
    except Exception:
        pass

    # Persist args for preview dialog
    try:
        mw._cleanup_preview_paths = list(paths)
        mw._cleanup_preview_include_pkd_files = bool(include_pkd_files)
        mw._cleanup_preview_mode_txt = str(mode_txt)
    except Exception:
        pass

    mw._cleanup_preview_thread.start()


def show_cleanup_preview_confirm_dialog(
    mw,
    preview_rows: list[dict],
    *,
    include_pkd_files: bool,
    mode_txt: str,
    trash_root_dir: Optional[str] = None,
    empty_trash_first: bool = False,
) -> tuple[bool, bool, bool]:
    """Return (proceed, delete_instead, empty_trash_first)."""
    try:
        from PySide6.QtWidgets import (
            QCheckBox,
            QDialog,
            QDialogButtonBox,
            QGroupBox,
            QHBoxLayout,
            QLabel,
            QLineEdit,
            QPlainTextEdit,
            QRadioButton,
            QTableWidget,
            QTableWidgetItem,
            QVBoxLayout,
        )
    except Exception:
        return (False, False, False)

    dlg = QDialog(mw)
    dlg.setWindowTitle("Cleanup PKD artifacts (preview)")
    lay = QVBoxLayout(dlg)

    total_discs = int(len(preview_rows))
    total_pkd_out = 0
    total_pkd = 0
    try:
        for r in preview_rows:
            total_pkd_out += int(len(r.get("pkd_out_dirs") or []))
            total_pkd += int(len(r.get("pkd_files") or []))
    except Exception:
        pass

    intro = QLabel(
        "Review what will be cleaned up, then confirm.\n\n"
        f"Disc folders: {total_discs}\n"
        f"Mode: {mode_txt}\n"
        f"Found: pkd_out={total_pkd_out}, pkd={total_pkd}\n\n"
        "Default action: MOVE artifacts into <discs_folder>/_spcdb_trash/<timestamp>/<disc_folder>/ (restorable)."
    )
    intro.setWordWrap(True)
    lay.addWidget(intro)

    table = QTableWidget(dlg)
    table.setColumnCount(3)
    table.setHorizontalHeaderLabels(["Disc", "pkd_out", "pkd"])  # pkd column is informational unless enabled
    table.setRowCount(total_discs)
    try:
        table.verticalHeader().setVisible(False)
    except Exception:
        pass
    try:
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setSelectionMode(QTableWidget.SingleSelection)
    except Exception:
        pass

    for i, r in enumerate(preview_rows):
        disc_root = str(r.get("disc_root") or "")
        name = Path(disc_root).name if disc_root else "(unknown)"
        pkd_out_n = int(len(r.get("pkd_out_dirs") or []))
        pkd_n = int(len(r.get("pkd_files") or []))

        it0 = QTableWidgetItem(name)
        try:
            it0.setToolTip(disc_root)
        except Exception:
            pass
        table.setItem(i, 0, it0)
        table.setItem(i, 1, QTableWidgetItem(str(pkd_out_n)))
        table.setItem(i, 2, QTableWidgetItem(str(pkd_n)))
        try:
            for c in (1, 2):
                table.item(i, c).setTextAlignment(Qt.AlignCenter)
        except Exception:
            pass

    try:
        table.resizeColumnsToContents()
    except Exception:
        pass
    lay.addWidget(table)

    details = QPlainTextEdit(dlg)
    details.setReadOnly(True)
    details.setPlaceholderText("Select a disc row to preview paths…")
    try:
        details.setMinimumHeight(140)
    except Exception:
        pass
    lay.addWidget(details)

    def _render_row(idx: int) -> None:
        try:
            r = preview_rows[int(idx)]
        except Exception:
            details.setPlainText("")
            return

        disc_root = str(r.get("disc_root") or "")
        pkd_out_dirs = list(r.get("pkd_out_dirs") or [])
        pkd_files = list(r.get("pkd_files") or [])

        lines: list[str] = []
        lines.append(f"Disc: {disc_root}")
        lines.append(f"pkd_out: {len(pkd_out_dirs)}")
        lines.append(f"pkd files: {len(pkd_files)}")
        lines.append("")

        # Keep the preview short to avoid UI spam.
        max_list = 30
        if pkd_out_dirs:
            lines.append("pkd_out folders:")
            for p in pkd_out_dirs[:max_list]:
                lines.append(f"  {p}")
            if len(pkd_out_dirs) > max_list:
                lines.append(f"  …and {len(pkd_out_dirs) - max_list} more")
            lines.append("")

        if pkd_files:
            lines.append("pkd files:")
            for p in pkd_files[:max_list]:
                lines.append(f"  {p}")
            if len(pkd_files) > max_list:
                lines.append(f"  …and {len(pkd_files) - max_list} more")

        if not include_pkd_files:
            lines.append("")
            lines.append("NOTE: pkd files will NOT be removed in the selected mode.")

        details.setPlainText("\n".join(lines))

    try:
        table.selectionModel().currentRowChanged.connect(lambda cur, _prev: _render_row(int(cur.row())))
    except Exception:
        pass
    try:
        if total_discs > 0:
            table.selectRow(0)
            _render_row(0)
    except Exception:
        pass

    # Action choice
    gb = QGroupBox("Action", dlg)
    gb_lay = QVBoxLayout(gb)
    rb_move = QRadioButton("Move to _spcdb_trash (recommended)")
    rb_delete = QRadioButton("Permanent delete (irreversible)")
    rb_move.setChecked(True)
    gb_lay.addWidget(rb_move)
    gb_lay.addWidget(rb_delete)
    lay.addWidget(gb)

    # Trash option (optional): empty existing trash before cleanup (permanent delete).
    # Trash lives alongside disc folders:
    #   <discs_folder>/_spcdb_trash/<timestamp>/<disc_folder>/
    # We derive candidate trash folders from the detected disc roots.
    trash_bases: list[Path] = []
    try:
        for r in preview_rows:
            disc_root_s = str((r or {}).get("disc_root") or "")
            if not disc_root_s:
                continue
            disc_root_p = Path(disc_root_s)
            trash_bases.append(disc_root_p.parent / "_spcdb_trash")
    except Exception:
        trash_bases = []

    # Fall back to an explicit root_dir if provided.
    try:
        if not trash_bases:
            tr = str(trash_root_dir or "").strip()
            if tr:
                trash_bases = [Path(tr) / "_spcdb_trash"]
    except Exception:
        pass

    uniq_trash_bases: list[Path] = []
    try:
        seen = set()
        for p in trash_bases:
            ps = str(p)
            if ps in seen:
                continue
            seen.add(ps)
            uniq_trash_bases.append(p)
    except Exception:
        uniq_trash_bases = list(trash_bases)

    existing_trash_bases: list[Path] = []
    try:
        existing_trash_bases = [p for p in uniq_trash_bases if p.exists() and p.is_dir()]
    except Exception:
        existing_trash_bases = []

    trash_entries = 0
    try:
        for p in existing_trash_bases:
            try:
                trash_entries += sum(1 for _ in p.iterdir())
            except Exception:
                pass
    except Exception:
        trash_entries = 0

    gb_trash = QGroupBox("Trash", dlg)
    gb_trash_lay = QVBoxLayout(gb_trash)
    cb_empty_trash = QCheckBox("Empty existing _spcdb_trash before cleanup (permanent delete)")
    gb_trash_lay.addWidget(cb_empty_trash)

    lbl_trash = QLabel("")
    lbl_trash.setWordWrap(True)
    try:
        if not uniq_trash_bases and not existing_trash_bases:
            lbl_trash.setText("Trash folder: (unknown)")
            cb_empty_trash.setEnabled(False)
        else:
            base_list = existing_trash_bases or uniq_trash_bases
            first = base_list[0]
            extra = max(0, len(base_list) - 1)
            extra_txt = f" (+{extra} more)" if extra > 0 else ""
            found_txt = "" if existing_trash_bases else " (not found)"
            lbl_trash.setText(f"Trash folder: {first}{extra_txt}{found_txt}\nEntries: {trash_entries}")
            if trash_entries <= 0:
                cb_empty_trash.setEnabled(False)
    except Exception:
        pass

    # Apply initial check state only if the option is available.
    try:
        if cb_empty_trash.isEnabled():
            cb_empty_trash.setChecked(bool(empty_trash_first))
    except Exception:
        pass

    gb_trash_lay.addWidget(lbl_trash)
    lay.addWidget(gb_trash)
    confirm_row = QHBoxLayout()
    confirm_lbl = QLabel("Type DELETE to enable permanent delete / empty trash:")
    confirm_edit = QLineEdit(dlg)
    confirm_edit.setPlaceholderText("DELETE")
    confirm_row.addWidget(confirm_lbl)
    confirm_row.addWidget(confirm_edit)
    lay.addLayout(confirm_row)

    btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    try:
        btns.button(QDialogButtonBox.Ok).setText("Start cleanup")
    except Exception:
        pass
    lay.addWidget(btns)

    def _update_ok_enabled() -> None:
        ok_btn = btns.button(QDialogButtonBox.Ok)
        if ok_btn is None:
            return
        require_delete = bool(rb_delete.isChecked())
        try:
            require_delete = require_delete or bool(cb_empty_trash.isChecked())
        except Exception:
            pass
        if not require_delete:
            ok_btn.setEnabled(True)
            return
        ok_btn.setEnabled(confirm_edit.text().strip() == "DELETE")

    try:
        rb_move.toggled.connect(_update_ok_enabled)
        rb_delete.toggled.connect(_update_ok_enabled)
        try:
            cb_empty_trash.toggled.connect(_update_ok_enabled)
        except Exception:
            pass
        confirm_edit.textChanged.connect(lambda _t: _update_ok_enabled())
    except Exception:
        pass
    _update_ok_enabled()

    btns.accepted.connect(dlg.accept)
    btns.rejected.connect(dlg.reject)

    if dlg.exec() != QDialog.Accepted:
        return (False, False, False)

    delete_instead = bool(rb_delete.isChecked())

    empty_trash_first = False
    try:
        empty_trash_first = bool(cb_empty_trash.isChecked())
    except Exception:
        empty_trash_first = False

    if (delete_instead or empty_trash_first) and (confirm_edit.text().strip() != "DELETE"):
        return (False, False, False)
    return (True, delete_instead, empty_trash_first)


def on_cleanup_preview_done(mw, preview_obj: object) -> None:

    try:
        preview_rows = list(preview_obj or [])
    except Exception:
        preview_rows = []

    # Capture args before tearing down preview state.
    try:
        include_pkd_files = bool(getattr(mw, "_cleanup_preview_include_pkd_files", False))
    except Exception:
        include_pkd_files = False
    try:
        mode_txt = str(getattr(mw, "_cleanup_preview_mode_txt", "") or "")
    except Exception:
        mode_txt = ""

    # Stop preview worker
    try:
        mw._cleanup_cleanup_preview()
    except Exception:
        pass

    # If nothing found at all, exit early.
    total_found = 0
    try:
        for r in preview_rows:
            total_found += int(len((r or {}).get("pkd_out_dirs") or []))
            total_found += int(len((r or {}).get("pkd_files") or []))
    except Exception:
        total_found = 0

    want_empty_trash = False
    try:
        want_empty_trash = bool(getattr(mw, "_cleanup_preview_empty_trash_first", False))
    except Exception:
        want_empty_trash = False

    if total_found == 0 and not want_empty_trash:
        try:
            QMessageBox.information(mw, "Cleanup", "No PKD artifacts were found for the detected disc folders.")
        except Exception:
            pass
        mw._active_op = None
        mw._cancel_token = None
        mw._set_op_running(False)
        return

    if total_found == 0 and want_empty_trash:
        try:
            mw._log("[cleanup] No PKD artifacts found; proceeding because empty trash was requested.")
        except Exception:
            pass

    proceed, delete_instead, empty_trash_first = mw._show_cleanup_preview_confirm_dialog(
        preview_rows,
        include_pkd_files=include_pkd_files,
        mode_txt=mode_txt or ("pkd_out only" if not include_pkd_files else "pkd_out + pkd files"),
        trash_root_dir=str(getattr(mw, "_cleanup_preview_root_dir", "") or "") or None,
        empty_trash_first=bool(getattr(mw, "_cleanup_preview_empty_trash_first", False)),
    )
    if not proceed:
        mw._log("[cleanup] Cancelled by user.")
        mw._active_op = None
        mw._cancel_token = None
        mw._set_op_running(False)
        return

    # Extract disc roots in a stable order.
    try:
        paths = [str((r or {}).get("disc_root") or "") for r in preview_rows]
        paths = [p for p in paths if p]
        paths = list(dict.fromkeys(paths))
    except Exception:
        paths = list(getattr(mw, "_cleanup_preview_paths", []) or [])

    if not paths:
        if bool(empty_trash_first):
            # Allow trash-only cleanup when no disc roots were detected.
            paths = []
        else:
            mw._log("[cleanup] No disc roots available for cleanup.")
            mw._active_op = None
            mw._cancel_token = None
            mw._set_op_running(False)
            return

    mw._active_op = "cleanup"
    try:
        if paths:
            mw._log(
                f"[cleanup] Starting cleanup on {len(paths)} disc folder(s)… (mode={'DELETE' if delete_instead else 'MOVE'})"
            )
        else:
            mw._log(
                f"[cleanup] Starting cleanup… (trash only) (mode={'DELETE' if delete_instead else 'MOVE'})"
            )
    except Exception:
        pass

    # Ensure a fresh cancel token for the actual cleanup phase.
    # This prevents any preview-dialog cancellation edge cases from aborting cleanup immediately.
    try:
        mw._cancel_token = CancelToken()
    except Exception:
        mw._cancel_token = CancelToken()

# Run cleanup in background
    mw._cleanup_thread = QThread()
    mw._cleanup_worker = CleanupWorker(
        paths,
        include_pkd_files=include_pkd_files,
        delete_instead=delete_instead,
        cancel_token=mw._cancel_token,
        trash_root_dir=str(getattr(mw, "_cleanup_preview_root_dir", "") or "") or None,
        empty_trash_first=bool(empty_trash_first),
        skip_artifacts_cleanup=bool(total_found == 0),
    )
    mw._cleanup_worker.moveToThread(mw._cleanup_thread)

    mw._cleanup_thread.started.connect(mw._cleanup_worker.run, Qt.QueuedConnection)
    mw._cleanup_worker.log.connect(mw._log)
    mw._cleanup_worker.done.connect(mw._on_cleanup_tool_done, Qt.QueuedConnection)
    mw._cleanup_worker.cancelled.connect(mw._on_cleanup_tool_cancelled, Qt.QueuedConnection)
    mw._cleanup_worker.error.connect(mw._on_cleanup_tool_error, Qt.QueuedConnection)

    try:
        mw._cleanup_thread.finished.connect(mw._cleanup_thread.deleteLater)
        mw._cleanup_worker.finished.connect(mw._cleanup_worker.deleteLater)
    except Exception:
        pass

    mw._cleanup_thread.start()


def on_cleanup_preview_cancelled(mw) -> None:
    mw._log("[cleanup] Preview cancelled.")
    try:
        mw._cleanup_cleanup_preview()
    except Exception:
        pass
    mw._active_op = None
    mw._cancel_token = None
    mw._set_op_running(False)


def on_cleanup_preview_error(mw, msg: str) -> None:
    mw._log(f"[cleanup] Preview ERROR: {msg}")
    try:
        QMessageBox.warning(mw, "Cleanup preview failed", f"Cleanup preview failed:\n\n{msg}")
    except Exception:
        pass
    try:
        mw._cleanup_cleanup_preview()
    except Exception:
        pass
    mw._active_op = None
    mw._cancel_token = None
    mw._set_op_running(False)
    try:
        mw._cleanup_scan_thread = None
        mw._cleanup_scan_worker = None
        mw._cleanup_scan_root_dir = None
        mw._cleanup_scan_include_pkd_files = None
    except Exception:
        pass


def on_cleanup_scan_done_worker(mw, found: list[str]) -> None:
    """Bridge ScanWorker.done → _on_cleanup_scan_done without lambdas/partials.

    Using a direct QObject slot is more stable on Windows/PySide6 than
    connecting a queued signal to a Python lambda.
    """
    try:
        root_dir = str(getattr(mw, "_cleanup_scan_root_dir", "") or "")
    except Exception:
        root_dir = ""
    try:
        include_pkd_files = bool(getattr(mw, "_cleanup_scan_include_pkd_files", False))
    except Exception:
        include_pkd_files = False
    try:
        empty_trash_first = bool(getattr(mw, "_cleanup_scan_empty_trash_first", False))
    except Exception:
        empty_trash_first = False
    mw._on_cleanup_scan_done(found, root_dir=root_dir, include_pkd_files=include_pkd_files, empty_trash_first=empty_trash_first)


def on_cleanup_scan_cancelled(mw) -> None:
    mw._log("[cleanup] Scan cancelled.")
    try:
        mw._cleanup_cleanup_scan()
    except Exception:
        pass
    mw._active_op = None
    mw._cancel_token = None
    mw._set_op_running(False)


def on_cleanup_scan_error(mw, msg: str) -> None:
    mw._log(f"[cleanup] Scan ERROR: {msg}")
    try:
        QMessageBox.warning(mw, "Cleanup scan failed", f"Cleanup scan failed:\n\n{msg}")
    except Exception:
        pass
    try:
        mw._cleanup_cleanup_scan()
    except Exception:
        pass
    mw._active_op = None
    mw._cancel_token = None
    mw._set_op_running(False)


def on_cleanup_scan_done(mw, found_paths: object, *, root_dir: str, include_pkd_files: bool, empty_trash_first: bool) -> None:
    # Stop scan thread (avoid leaks / stuck state)
    try:
        mw._cleanup_cleanup_scan()
    except Exception:
        pass

    # Normalize targets (disc roots)
    try:
        paths = [str(p) for p in (found_paths or []) if str(p)]
    except Exception:
        paths = []

    # If scan finds nothing but the selected folder itself looks like a disc, include it.
    if not paths:
        try:
            cand = Path(str(root_dir)).expanduser()
            if (cand / "PS3_GAME" / "USRDIR").is_dir():
                paths = [str(cand)]
        except Exception:
            pass

    # Deduplicate
    try:
        paths = list(dict.fromkeys(paths))
    except Exception:
        paths = list(paths)

    if not paths:
        mw._log("[cleanup] No disc folders found under selected root.")
        try:
            QMessageBox.information(mw, "Cleanup", "No disc folders were detected under the selected folder.")
        except Exception:
            pass
        mw._active_op = None
        mw._set_op_running(False)
        return

    # Preview first (counts + sample paths), then ask for final confirmation.
    mode_txt = "pkd_out only" if not include_pkd_files else "pkd_out + pkd files"
    try:
        mw._active_op = "cleanup_preview"
    except Exception:
        pass
    try:
        mw._cleanup_preview_mode_txt = str(mode_txt)
    except Exception:
        pass
    try:
        mw._cleanup_preview_paths = list(paths)
    except Exception:
        mw._cleanup_preview_paths = []
    try:
        mw._cleanup_preview_include_pkd_files = bool(include_pkd_files)
    except Exception:
        mw._cleanup_preview_include_pkd_files = False

    # Persist scan options for the preview/confirm stage.
    try:
        mw._cleanup_preview_root_dir = str(root_dir or "")
    except Exception:
        mw._cleanup_preview_root_dir = str(root_dir or "")
    try:
        mw._cleanup_preview_empty_trash_first = bool(empty_trash_first)
    except Exception:
        mw._cleanup_preview_empty_trash_first = bool(empty_trash_first)
    mw._start_cleanup_preview(paths, mode_txt=mode_txt, include_pkd_files=include_pkd_files)
    return


def on_cleanup_done(mw, results: object) -> None:
    # Summarize results
    moved_dirs = 0
    moved_files = 0
    deleted_dirs = 0
    deleted_files = 0
    trash_dirs = []
    trash_emptied: dict = {}
    rl = results
    try:
        if isinstance(results, dict):
            trash_emptied = dict((results or {}).get("trash_emptied") or {})
            rl = (results or {}).get("results") or []
    except Exception:
        rl = results
    try:
        for r in (rl or []) or []:
            res = (r or {}).get("result", {}) if isinstance(r, dict) else {}
            try:
                moved_dirs += int(res.get("moved_dirs", 0) or 0)
            except Exception:
                pass
            try:
                moved_files += int(res.get("moved_files", 0) or 0)
            except Exception:
                pass
            try:
                deleted_dirs += int(res.get("deleted_dirs", 0) or 0)
            except Exception:
                pass
            try:
                deleted_files += int(res.get("deleted_files", 0) or 0)
            except Exception:
                pass
            td = res.get("trash_dir", None)
            if td:
                trash_dirs.append(str(td))
    except Exception:
        pass

    mw._log(f"[cleanup] Done. moved_dirs={moved_dirs} moved_files={moved_files} deleted_dirs={deleted_dirs} deleted_files={deleted_files}")
    try:
        detail = ""
        if trash_dirs:
            # Show at most 3 unique trash dirs
            uniq = list(dict.fromkeys(trash_dirs))
            detail = "\n\nTrash folder(s):\n" + "\n".join(uniq[:3])
            if len(uniq) > 3:
                detail += f"\n…and {len(uniq) - 3} more"
        QMessageBox.information(
            mw,
            "Cleanup complete",
            (
                f"Cleanup complete.\n\n"
                f"Moved folders: {moved_dirs}\n"
                f"Moved files: {moved_files}\n"
                + (f"Deleted folders: {deleted_dirs}\nDeleted files: {deleted_files}\n\nNOTE: Deleted items cannot be restored." if (deleted_dirs or deleted_files) else "")
                + detail
            ),
        )
    except Exception:
        pass

    # Ensure threads/state are fully cleared (prevents “stuck busy” / hangs)
    try:
        mw._cleanup_cleanup()
    except Exception:
        mw._active_op = None
        mw._set_op_running(False)

    # Refresh source states in case packed/extracted states changed
    try:
        mw._refresh_source_states()
    except Exception:
        pass
    # Best-effort: refresh songs view
    try:
        mw._start_refresh_songs(auto=True)
    except Exception:
        pass


def on_cleanup_cancelled(mw) -> None:
    mw._log("[cleanup] Cancelled.")
    try:
        mw._cleanup_cleanup()
    except Exception:
        mw._active_op = None
        mw._set_op_running(False)


def on_cleanup_error(mw, msg: str) -> None:
    mw._log(f"[cleanup] ERROR: {msg}")
    try:
        QMessageBox.warning(mw, "Cleanup failed", f"Cleanup failed:\n\n{msg}")
    except Exception:
        pass
    try:
        mw._cleanup_cleanup()
    except Exception:
        mw._active_op = None
        mw._set_op_running(False)
