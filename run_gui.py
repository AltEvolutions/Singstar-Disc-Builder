"""Cross-platform launcher for the GUI.

Usage:
  python run_gui.py [--qt|--tk] [--debug] [--qt-diag] [-- <extra args>]

Equivalent to:
  python -m spcdb_tool gui[-qt|-tk]
  python -m spcdb_tool qt-diag
"""

from __future__ import annotations

import os
import sys
from typing import List


def main(argv: List[str]) -> int:
    mode = "gui"
    lvl = "INFO"
    passthrough: List[str] = []

    it = iter(argv[1:])
    for a in it:
        al = a.lower()
        if al == "--qt":
            mode = "gui-qt"
        elif al == "--tk":
            mode = "gui-tk"
        elif al == "--qt-diag":
            mode = "qt-diag"
        elif al == "--debug":
            lvl = "DEBUG"
        elif al == "--":
            passthrough.extend(list(it))
            break
        else:
            passthrough.append(a)

    os.environ.setdefault("SPCDB_LOG_TO_CONSOLE", "1")
    os.environ.setdefault("SPCDB_LOG_LEVEL", lvl)
    os.environ.setdefault("PYTHONUNBUFFERED", "1")

    # Dispatch directly into the CLI (avoids fragile sys.argv hacks).
    from spcdb_tool.cli import main as cli_main

    sys.argv = ["spcdb_tool", mode, *passthrough]
    return int(cli_main())


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
