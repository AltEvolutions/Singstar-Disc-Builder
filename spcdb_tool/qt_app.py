from __future__ import annotations

"""Experimental PySide6 (Qt) GUI shell.

Block D / v0.5.10b:
- Minimal UI that can load/save settings
- Manage Base/Sources paths
- Provide a live log panel

Core actions (Validate/Extract/Build) are added in v0.5.10c.

This module is imported lazily from the CLI subcommand `gui-qt`.
"""

import json
import logging
import os
import shutil
import subprocess
import time
import re
import xml.etree.ElementTree as ET

from pathlib import Path
from typing import Dict, List, Optional, Tuple, Set

from .controller import (
    BuildBlockedError,
    CancelToken,
    CancelledError,
    DiscIndex,
    _index_cache_path_for_input,
    SongAgg,
    SongOccur,
    compute_song_id_conflicts,
    _load_settings,
    _save_settings,
    build_song_catalog,
    extract_disc_pkds,
    verify_disc_extraction,
    cleanup_extraction_artifacts,
    _find_extraction_artifacts,
    index_disc,
    run_build_subset,
    validate_discs,
    get_index_cache_status,
    clear_index_cache,
)

from . import __version__ as APP_VERSION
from .util import ensure_default_extractor_dir, default_extractor_dir, detect_default_extractor_exe
from .app_logging import logs_dir as _app_logs_dir

_FILELOG = logging.getLogger("spcdb_tool.gui")

from .qt.utils import _scan_for_disc_inputs
from .qt.constants import SPCDB_QT_STATE_FILE, SONG_SOURCE_SELECTED_KEY, SONG_SOURCE_SELECTED_DISP


def _show_missing_pyside6_dialog(extra: str | None = None) -> None:
    """Show a user-friendly Qt launch failure message.

    We prefer a Tk messagebox so it appears even if launched via pythonw.
    """
    msg = """Qt GUI could not be launched.

This usually means PySide6 (Qt) is missing or broken in this Python environment.

Try reinstalling:
  pip install --upgrade --force-reinstall pyside6

Then launch the Qt GUI with:
  python -m spcdb_tool gui-qt

(or run_gui.bat --qt)
"""
    if extra:
        msg = msg + "\nDetails:\n  " + str(extra).strip() + "\n"
    try:
        import tkinter as tk
        from tkinter import messagebox

        r = tk.Tk()
        r.withdraw()
        messagebox.showerror("Qt GUI could not be launched", msg)
        r.destroy()
    except Exception:
        print(msg)


def run_qt_gui() -> int:
    """Launch the experimental Qt GUI.

    If PySide6 is missing, shows a friendly message and returns.
    """
    # --- boot trace (auto) ---
    from .qt.bootstrap import (
        start_qt_boot_trace,
        install_killtimer_message_suppression,
        show_splash,
        show_main_window_smart,
    )

    qt_boot = start_qt_boot_trace()
    qt_boot('run_qt_gui: entered')
    # --- end boot trace ---

    try:
        from PySide6.QtCore import Qt, QObject, QThread, Signal, Slot, QTimer, QEvent, QUrl, QProcess
        from PySide6.QtGui import QAction, QIcon, QPixmap, QDesktopServices, QCursor
        from PySide6.QtWidgets import (
            QApplication,
            QAbstractItemView,
            QCheckBox,
            QComboBox,
            QDialog,
            QListWidget,
            QListWidgetItem,
            QFileDialog,
            QFormLayout,
            QGridLayout,
            QGroupBox,
            QHBoxLayout,
            QLabel,
            QLineEdit,
            QMainWindow,
            QMessageBox,
            QMenu,
            QProgressBar,
            QStyle,
            QStyleOptionViewItem,
            QStyleOption,
            QStyledItemDelegate,
            QProxyStyle,
            QSplashScreen,
            QPushButton,
            QToolButton,
            QTableWidget,
            QTableWidgetItem,
            QSplitter,
            QStackedWidget,
            QTextEdit,
            QFrame,
            QScrollArea,
            QSizePolicy,
            QVBoxLayout,
            QWidget,
        )
    except Exception as e:
        # If Qt bindings fail to import, emit a clear message to BOTH log + console.
        try:
            _FILELOG.exception("[gui-qt] PySide6/Qt import failed: %s", e)
        except Exception:
            pass
        try:
            print(f"[gui-qt] PySide6/Qt import failed: {e}")
        except Exception:
            pass
        _show_missing_pyside6_dialog(extra=str(e))
        raise


    # Suppress a benign Qt warning that can appear on startup:
    #   QObject::killTimer: Timers cannot be stopped from another thread
    # This does not affect correctness, but it confuses users by printing on boot.
    try:
        from PySide6.QtCore import qInstallMessageHandler

        install_killtimer_message_suppression(qInstallMessageHandler, qt_boot)
    except Exception:
        pass


    # Create the QApplication (must happen before any widgets).
    app = QApplication.instance() or QApplication([])
    qt_boot('QApplication created')

    icon_path = Path(__file__).resolve().parent / "branding" / "spcdb_icon.png"

    # App icon
    try:
        if icon_path.exists():
            app.setWindowIcon(QIcon(str(icon_path)))
    except Exception:
        pass

    # Splash screen (show logo briefly on boot)
    splash = show_splash(
        app=app,
        Qt=Qt,
        QSplashScreen=QSplashScreen,
        QPixmap=QPixmap,
        icon_path=icon_path,
    )

    from .qt.main_window import MainWindow




    win = MainWindow()
    qt_boot('MainWindow constructed')
    try:
        if icon_path.exists():
            win.setWindowIcon(QIcon(str(icon_path)))
    except Exception:
        pass
    show_main_window_smart(app=app, win=win, QCursor=QCursor)
    qt_boot('MainWindow shown')

    # Keep splash visible for a moment even after main window appears.
    try:
        if splash is not None:
            QTimer.singleShot(2500, lambda: splash.finish(win))
    except Exception:
        pass


    # Surface the per-run log file path in the UI (if file logging is enabled).
    try:
        from .app_logging import current_log_path
        lp = current_log_path()
        if lp:
            win._log(f"[log] Verbose log: {lp}")
    except Exception:
        pass
    rc = int(app.exec())
    qt_boot(f'app.exec exited rc={rc}')
    return rc
