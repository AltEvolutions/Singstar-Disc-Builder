from __future__ import annotations

import json
import os
import shutil
import re
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, cast


NUMERIC_DIR_RE = re.compile(r"^\d+$")


def is_probably_numeric_dir(name: str) -> bool:
    return bool(NUMERIC_DIR_RE.match(name))


def to_jsonable(obj: Any) -> Any:
    if is_dataclass(obj):
        return {k: to_jsonable(v) for k, v in asdict(cast(Any, obj)).items()}
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, dict):
        return {str(k): to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(x) for x in obj]
    return obj


def dumps_pretty(obj: Any) -> str:
    return json.dumps(to_jsonable(obj), indent=2, sort_keys=True, ensure_ascii=False)


def relpath_posix(path: str) -> str:
    # normalize to forward-slash for matching config.xml style
    return path.replace("\\", "/")


def safe_listdir(p: Path) -> list[Path]:
    try:
        return list(p.iterdir())
    except FileNotFoundError:
        return []
    except PermissionError:
        return []


def env_bool(name: str, default: bool = False) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "y", "on"}



def find_app_root(start: Path | None = None) -> Path:
    """Best-effort app root finder.

    Prefers a folder that contains run_gui.bat or README.md (portable zip use-case),
    otherwise falls back to the current working directory.
    """
    try:
        cur = (start or Path(__file__).resolve().parent)
        cur = cur if isinstance(cur, Path) else Path(str(cur))
        for _ in range(8):
            if (cur / "run_gui.bat").is_file() or (cur / "README.md").is_file():
                return cur
            if cur.parent == cur:
                break
            cur = cur.parent
    except Exception:
        pass
    try:
        return Path.cwd()
    except Exception:
        return Path(__file__).resolve().parent


def default_extractor_dir() -> Path:
    """Return the recommended extractor folder: <app_root>/extractor."""
    try:
        root = find_app_root(Path(__file__).resolve().parent)
    except Exception:
        root = Path.cwd()
    return root / "extractor"


def ensure_default_extractor_dir() -> Path:
    """Create the default extractor folder if it does not exist."""
    p = default_extractor_dir()
    try:
        p.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return p


def detect_default_extractor_exe() -> Path | None:
    """Detect a likely extractor executable inside the default extractor folder.

    We do NOT bundle the extractor; this only helps users who already placed it
    into ./extractor.

    Preference order:
      1) exact match: scee_london(.exe)
      2) heuristic match: filename contains "scee" and/or "london" (platform-aware)
      3) single-candidate fallback
      4) PATH lookup (shutil.which)

    Note: On Linux/macOS, the extractor is typically named `scee_london` (no suffix).
    """

    def _path_lookup() -> Path | None:
        # Prefer the platform-typical name first.
        names = ["scee_london.exe", "scee_london"] if os.name == "nt" else ["scee_london", "scee_london.exe"]
        for nm in names:
            try:
                hit = shutil.which(nm)
            except Exception:
                hit = None
            if hit:
                try:
                    pp = Path(hit)
                except Exception:
                    continue
                if pp.exists() and pp.is_file():
                    return pp
        return None

    try:
        d = ensure_default_extractor_dir()
    except Exception:
        d = None

    if d is None or (not d.exists()) or (not d.is_dir()):
        return _path_lookup()

    try:
        entries = [pp for pp in safe_listdir(d) if pp.is_file() and (not pp.name.startswith('.'))]
    except Exception:
        entries = []

    if not entries:
        return _path_lookup()

    # 1) exact match (platform-aware ordering)
    exact = ["scee_london.exe", "scee_london"] if os.name == "nt" else ["scee_london", "scee_london.exe"]
    for nm in exact:
        for pp in entries:
            try:
                if pp.name.lower() == nm:
                    return pp
            except Exception:
                continue

    # helper: filter out obvious non-binaries
    bad_suffix = {".txt", ".md", ".rtf", ".pdf", ".json", ".yml", ".yaml", ".ini", ".cfg"}

    def is_exec(pp: Path) -> bool:
        try:
            return os.access(str(pp), os.X_OK)
        except Exception:
            return False

    # 2) heuristic match
    if os.name == "nt":
        # On Windows, accept both .exe and suffixless tools (some users rename the extractor without an extension).
        candidates = [pp for pp in entries if (pp.suffix.lower() == ".exe" or pp.suffix == "")]
    else:
        candidates = [pp for pp in entries if pp.suffix.lower() not in bad_suffix]

    def rank(pp: Path) -> tuple[int, int, int, int]:
        n = pp.name.lower()
        both = 0 if ("scee" in n and "london" in n) else 1
        one = 0 if ("scee" in n or "london" in n) else 1
        exec_penalty = 0
        if os.name != "nt":
            exec_penalty = 0 if is_exec(pp) else 1
        return (both, one, exec_penalty, len(n))

    try:
        cand2 = [pp for pp in candidates if ("scee" in pp.name.lower() or "london" in pp.name.lower())]
        cand2.sort(key=rank)
        if cand2:
            return cand2[0]
    except Exception:
        pass

    # 3) single-candidate fallback
    try:
        if os.name == "nt":
            win_bins = [pp for pp in entries if (pp.suffix.lower() == ".exe" or pp.suffix == "")]
            if len(win_bins) == 1:
                n = win_bins[0].name.lower()
                # Avoid auto-selecting placeholder dotfiles (e.g. .gitkeep) or unrelated suffixless files.
                if win_bins[0].suffix.lower() == ".exe" or ("scee" in n or "london" in n):
                    return win_bins[0]
        else:
            execs = [pp for pp in candidates if is_exec(pp)]
            if len(execs) == 1:
                return execs[0]
            if len(candidates) == 1:
                return candidates[0]
    except Exception:
        pass

    # 4) PATH lookup
    return _path_lookup()
