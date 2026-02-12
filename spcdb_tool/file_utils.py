from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Optional

_DEFAULT_CHUNK_SIZE = 1024 * 1024


def sha1_file(path: Path, *, chunk_size: int = _DEFAULT_CHUNK_SIZE) -> Optional[str]:
    """Return SHA1 hexdigest of a file, or None if missing/unreadable."""
    try:
        p = Path(path)
    except Exception:
        return None

    try:
        if not p.exists() or not p.is_file():
            return None
        h = hashlib.sha1()
        with p.open("rb") as f:
            for chunk in iter(lambda: f.read(int(chunk_size)), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None
