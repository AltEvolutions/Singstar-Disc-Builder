"""Qt GUI constants (internal).

This module exists to help split the large `qt_app.py` into smaller pieces
without changing behavior.
"""

# Persisted songs selection state (enabled/disabled) stored per-project.
SPCDB_QT_STATE_FILE = "spcdb_qt_song_selection.json"

# Persisted window geometry/state (Qt-only). Stored separately to avoid "poisoning"
# during frequent selection/filter state writes.
SPCDB_QT_WINDOW_STATE_FILE = "spcdb_qt_window_state.json"

# Special Source filter option: show songs from the currently selected discs in the Sources panel.
SONG_SOURCE_SELECTED_KEY = "__selected_discs__"
SONG_SOURCE_SELECTED_DISP = "Selected discs (from Sources panel)"
