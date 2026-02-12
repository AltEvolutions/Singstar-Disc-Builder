# ruff: noqa
from __future__ import annotations

"""Qt menus and actions (internal).

Extracted from `spcdb_tool/qt/main_window.py` as part of the incremental Qt refactor.
Behavior is intended to be unchanged.

Keep this module **side-effect free**: it must not create a QApplication or windows at import time.
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction


def build_main_menus(win) -> None:
    """Build the main menu bar and wire actions for the given MainWindow.

    Parameters
    ----------
    win:
        The MainWindow instance (owner of callbacks).
    """
    menu = win.menuBar()

    # ---- File ----
    m_file = menu.addMenu("File")

    try:
        m_file.setToolTipsVisible(True)
    except Exception:
        pass

    act_save = QAction("Save", win)
    try:
        act_save.setToolTip("Save current settings to disk.")
        act_save.setStatusTip("Save current settings to disk.")
    except Exception:
        pass

    try:
        act_save.triggered.connect(win._save_from_ui)
    except Exception:
        pass
    m_file.addAction(act_save)

    act_exit = QAction("Exit", win)
    try:
        act_exit.setToolTip("Quit SingStar Disc Builder.")
        act_exit.setStatusTip("Quit SingStar Disc Builder.")
    except Exception:
        pass

    try:
        act_exit.triggered.connect(win.close)
    except Exception:
        pass
    m_file.addAction(act_exit)

    # ---- Tools ----
    m_tools = menu.addMenu("Tools")

    try:
        m_tools.setToolTipsVisible(True)
    except Exception:
        pass

    act_clear_cache = QAction("Clear index cache", win)
    try:
        act_clear_cache.setToolTip("Delete saved song index caches (forces re-scan on next Refresh Songs).")
        act_clear_cache.setStatusTip("Delete saved song index caches (forces re-scan on next Refresh Songs).")
    except Exception:
        pass

    try:
        act_clear_cache.triggered.connect(win._clear_index_cache_action)
    except Exception:
        pass
    m_tools.addAction(act_clear_cache)

    act_reset_ui = QAction("Reset UI state…", win)
    try:
        act_reset_ui.setToolTip("Reset saved UI settings (filters, column widths, window layout).")
        act_reset_ui.setStatusTip("Reset saved UI settings (filters, column widths, window layout).")
    except Exception:
        pass

    try:
        act_reset_ui.triggered.connect(win._reset_ui_state_action)
    except Exception:
        pass
    m_tools.addAction(act_reset_ui)

    act_reset_layout = QAction("Reset layout to defaults", win)
    try:
        act_reset_layout.setToolTip("Reset splitter/sidebar layout back to defaults.")
        act_reset_layout.setStatusTip("Reset splitter/sidebar layout back to defaults.")
    except Exception:
        pass

    try:
        act_reset_layout.triggered.connect(win._reset_layout_action)
    except Exception:
        pass
    m_tools.addAction(act_reset_layout)

    act_reset_columns = QAction("Reset columns to defaults", win)
    try:
        act_reset_columns.setToolTip("Reset column widths/visibility for Sources and Songs tables.")
        act_reset_columns.setStatusTip("Reset column widths/visibility for Sources and Songs tables.")
    except Exception:
        pass

    try:
        act_reset_columns.triggered.connect(win._reset_columns_action)
    except Exception:
        pass
    m_tools.addAction(act_reset_columns)

    act_cleanup_pkd = QAction("Cleanup PKD artifacts…", win)
    try:
        act_cleanup_pkd.setToolTip(
            "Clean up temporary packed-disc extraction files created during extraction.\n"
            "This includes Pack*.pkd_out folders and Pack*.pkd files.\n"
            "Files are moved to a safe trash folder unless you choose permanent delete."
        )
        act_cleanup_pkd.setStatusTip("Clean up temporary extraction files (Pack*.pkd_out folders / Pack*.pkd files).")
    except Exception:
        pass

    try:
        act_cleanup_pkd.triggered.connect(win._cleanup_pkd_artifacts_action)
    except Exception:
        pass
    m_tools.addAction(act_cleanup_pkd)

    # ---- View ----
    m_view = menu.addMenu("View")

    try:
        m_view.setToolTipsVisible(True)
    except Exception:
        pass

    act_toggle_left_sidebar = QAction("Left sidebar", win)
    try:
        act_toggle_left_sidebar.setToolTip("Show/hide the Sources + Paths panel.")
        act_toggle_left_sidebar.setStatusTip("Show/hide the Sources + Paths panel.")
    except Exception:
        pass

    try:
        act_toggle_left_sidebar.setCheckable(True)
        act_toggle_left_sidebar.setChecked(True)
        act_toggle_left_sidebar.setShortcut("F8")
        act_toggle_left_sidebar.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
    except Exception:
        pass
    try:
        act_toggle_left_sidebar.triggered.connect(win._toggle_left_sidebar)
    except Exception:
        pass
    try:
        win._act_toggle_left_sidebar = act_toggle_left_sidebar
    except Exception:
        pass
    m_view.addAction(act_toggle_left_sidebar)

    act_toggle_right_sidebar = QAction("Right sidebar", win)
    try:
        act_toggle_right_sidebar.setToolTip("Show/hide the Inspector + Quick Actions panel.")
        act_toggle_right_sidebar.setStatusTip("Show/hide the Inspector + Quick Actions panel.")
    except Exception:
        pass

    try:
        act_toggle_right_sidebar.setCheckable(True)
        act_toggle_right_sidebar.setChecked(True)
        act_toggle_right_sidebar.setShortcut("F9")
        act_toggle_right_sidebar.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
    except Exception:
        pass
    try:
        act_toggle_right_sidebar.triggered.connect(win._toggle_right_sidebar)
    except Exception:
        pass
    try:
        win._act_toggle_right_sidebar = act_toggle_right_sidebar
    except Exception:
        pass
    m_view.addAction(act_toggle_right_sidebar)

    # ---- Help ----
    m_help = menu.addMenu("Help")

    try:
        m_help.setToolTipsVisible(True)
    except Exception:
        pass

    act_about = QAction("About", win)
    try:
        act_about.setToolTip("About SingStar Disc Builder (version, credits).")
        act_about.setStatusTip("About SingStar Disc Builder (version, credits).")
    except Exception:
        pass

    try:
        act_about.triggered.connect(win._about)
    except Exception:
        pass
    m_help.addAction(act_about)

    act_license = QAction("License (GPLv3)", win)
    try:
        act_license.setToolTip("Open the GPLv3 license text.")
        act_license.setStatusTip("Open the GPLv3 license text.")
    except Exception:
        pass

    try:
        act_license.triggered.connect(win._open_license)
    except Exception:
        pass
    m_help.addAction(act_license)

    act_third = QAction("Third-party notices", win)
    try:
        act_third.setToolTip("Open third-party dependency notices.")
        act_third.setStatusTip("Open third-party dependency notices.")
    except Exception:
        pass

    try:
        act_third.triggered.connect(win._open_third_party_notices)
    except Exception:
        pass
    m_help.addAction(act_third)

    act_bundle = QAction("Export support bundle...", win)
    try:
        act_bundle.setToolTip(
            "Create a zip with logs + config for debugging.\n"
            "Does not include disc content."
        )
        act_bundle.setStatusTip("Export a zip with logs + config for debugging (no disc content).")
    except Exception:
        pass

    try:
        act_bundle.triggered.connect(win._export_support_bundle_action)
    except Exception:
        pass
    m_help.addAction(act_bundle)
