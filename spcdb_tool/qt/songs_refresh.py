"""Songs refresh thread wiring (Qt).

This module exists to keep `main_window.py` smaller and to centralize the
fragile QThread/SongsWorker hookup logic in one place.

Behavior must remain identical to the legacy inline implementation.
"""

from __future__ import annotations

from typing import List, Tuple

from PySide6.QtCore import QThread, QTimer

from .workers import SongsWorker
from ..controller import CancelToken


def start_songs_refresh_thread(
    main_window: object,
    targets: List[Tuple[str, str, bool]],
    cancel_token: CancelToken,
) -> None:
    """Start the background song indexing worker.

    Args:
        main_window: The MainWindow instance (used for callbacks + state fields).
        targets: (label, disc_root, is_base) list.
        cancel_token: CancelToken for aborting the worker.

    Notes:
        - This function intentionally reaches into `main_window` attributes.
          It's an internal helper to avoid a massive MainWindow->helper argument surface.
        - It is critical that we preserve the exact locking/unlocking semantics and
          cleanup watchdog behavior.
    """

    # The main window provides these members; we keep lookups dynamic to avoid
    # circular imports / typing runtime costs.
    log = getattr(main_window, "_log")
    cleanup = getattr(main_window, "_cleanup_songs")
    on_done = getattr(main_window, "_on_songs_done")
    on_cancelled = getattr(main_window, "_on_songs_cancelled")
    on_error = getattr(main_window, "_on_songs_error")

    t = QThread()
    w = SongsWorker(targets, cancel_token)
    w.moveToThread(t)

    t.started.connect(w.run)
    w.log.connect(log)

    w.done.connect(on_done)
    w.cancelled.connect(on_cancelled)
    w.error.connect(on_error)

    # Robust finalize (v0.5.11a.3.1): always unlock when the worker finishes.
    # Using the cleanup helper avoids edge cases where startup queued signals are
    # delayed/dropped and the UI remains locked.
    def _finalize_songs() -> None:
        if getattr(main_window, "_songs_thread", None) is not t:
            return
        try:
            cleanup()
        except Exception as e:
            try:
                log(f"[songs] finalize cleanup failed: {e}")
            except Exception:
                pass

    w.finished.connect(_finalize_songs)
    t.finished.connect(_finalize_songs)

    # Watchdog: if the thread is no longer running but we didn't unlock, force cleanup.
    try:
        QTimer.singleShot(
            20000,
            lambda: (_finalize_songs() if (getattr(main_window, "_songs_thread", None) is t and (not t.isRunning())) else None),
        )
    except Exception:
        pass

    try:
        t.finished.connect(t.deleteLater)
        w.finished.connect(w.deleteLater)
    except Exception:
        pass

    setattr(main_window, "_songs_thread", t)
    setattr(main_window, "_songs_worker", w)
    t.start()
