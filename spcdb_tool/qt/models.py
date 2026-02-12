"""Qt GUI models/types (internal).

This module exists to help split the large `qt_app.py` into smaller pieces.
"""

from dataclasses import dataclass


@dataclass
class _SourceRow:
    """Simple Sources-table row model.

    NOTE: Currently unused, but kept for future incremental refactors.
    """

    label: str
    path: str
