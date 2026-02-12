# ruff: noqa
from __future__ import annotations

"""Qt operation handlers (internal).

This module contains the heavy-lifting bodies for Validate / Extract / Build / Cancel
actions. MainWindow keeps small wrapper methods that delegate here, to keep
`main_window.py` smaller while preserving behavior.
"""

from pathlib import Path
from typing import Dict, List, Optional, Set
import hashlib
import re
import html


from PySide6.QtCore import Qt, QThread, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QCommandLinkButton,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QStyle,
    QToolButton,
    QVBoxLayout,
)


from ..controller import CancelToken
from .workers import ValidateWorker, ExtractWorker, BuildWorker
from .ui_helpers import show_status_message




def _norm_display_key(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip()).upper()


def _song_display_key(title: str, artist: str) -> str:
    return f"{_norm_display_key(title)}||{_norm_display_key(artist)}"


def _display_duplicate_stats(mw, song_ids: Set[int]) -> Dict[str, object]:
    """Return display-level duplicate stats for the given song ids.

    Display key is normalized Title+Artist. This matches the in-game duplicate suppression risk.
    """
    ids_in = sorted(set(int(x) for x in (song_ids or set())))
    groups: Dict[str, List[int]] = {}
    key_to_disp: Dict[str, tuple[str, str]] = {}

    for sid in ids_in:
        s = getattr(mw, "_songs_by_id", {}).get(int(sid))
        if s is None:
            continue
        title = str(getattr(s, "title", "") or "")
        artist = str(getattr(s, "artist", "") or "")
        k = _song_display_key(title, artist)
        if not k.strip():
            continue
        groups.setdefault(k, []).append(int(sid))
        key_to_disp.setdefault(k, (title, artist))

    dup_groups = {k: v for (k, v) in groups.items() if len(v) >= 2}

    # Compact structured list (safe to persist into UI state/logs)
    dups_list: List[Dict[str, object]] = []
    for k, ids in sorted(dup_groups.items(), key=lambda kv: (len(kv[1]), kv[0])):
        title, artist = key_to_disp.get(k, ("", ""))
        dups_list.append(
            {
                "key": str(k),
                "title": str(title),
                "artist": str(artist),
                "ids": sorted(int(x) for x in (ids or [])),
            }
        )

    return {
        "selected": int(len(ids_in)),
        "unique": int(len(groups)),
        "dup_groups": int(len(dup_groups)),
        "dups": dups_list,
    }


def _sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _song_folder_meta_hash(song_dir: Path) -> str:
    # Hash of relative paths + sizes (fast first pass).
    h = hashlib.sha256()
    files: list[Path] = []
    try:
        files = [fp for fp in song_dir.rglob("*") if fp.is_file()]
    except Exception:
        files = []
    for fp in sorted(files, key=lambda x: x.as_posix()):
        try:
            rel = fp.relative_to(song_dir).as_posix()
        except Exception:
            rel = fp.name
        try:
            size = int(fp.stat().st_size)
        except Exception:
            size = -1
        h.update(rel.encode("utf-8", "replace"))
        h.update(b"\0")
        h.update(str(size).encode("ascii", "replace"))
        h.update(b"\0")
    return h.hexdigest()


def _song_folder_full_hash(song_dir: Path) -> str:
    # Full content hash of all files under Export/<song_id>/ (byte-identical check).
    h = hashlib.sha256()
    files: list[Path] = []
    try:
        files = [fp for fp in song_dir.rglob("*") if fp.is_file()]
    except Exception:
        files = []
    for fp in sorted(files, key=lambda x: x.as_posix()):
        try:
            rel = fp.relative_to(song_dir).as_posix()
        except Exception:
            rel = fp.name
        try:
            size = int(fp.stat().st_size)
        except Exception:
            size = -1
        h.update(rel.encode("utf-8", "replace"))
        h.update(b"\0")
        h.update(str(size).encode("ascii", "replace"))
        h.update(b"\0")
        try:
            h.update(_sha256_file(fp).encode("ascii"))
        except Exception:
            # Treat unreadable file as unique.
            h.update(b"__READ_FAIL__")
        h.update(b"\0")
    return h.hexdigest()


def _compare_song_folders(a: Path, b: Path) -> tuple[Optional[bool], str]:
    if not a.exists() or not a.is_dir():
        return None, f"Missing song folder: {a}"
    if not b.exists() or not b.is_dir():
        return None, f"Missing song folder: {b}"
    try:
        a_meta = _song_folder_meta_hash(a)
        b_meta = _song_folder_meta_hash(b)
    except Exception as e:
        return None, f"Compare failed (meta): {e}"
    if a_meta != b_meta:
        return False, "Different file list and/or sizes"
    try:
        a_full = _song_folder_full_hash(a)
        b_full = _song_folder_full_hash(b)
    except Exception as e:
        return None, f"Compare failed (hash): {e}"
    if a_full == b_full:
        return True, "Byte-identical"
    return False, "Same file list/sizes, but content differs"


_VIDEO_EXTS = {
    '.m2v', '.mp4', '.m4v', '.mov', '.avi', '.wmv', '.mpg', '.mpeg', '.vob', '.m2ts', '.ts', '.h264', '.avc',
    '.usm', '.pss', '.bik', '.webm',
}

_AUDIO_EXTS = {
    '.at3', '.wav', '.mp3', '.aac', '.m4a', '.ogg', '.flac', '.wma', '.ac3', '.dts',
}


def _human_bytes(n: int) -> str:
    try:
        n = int(n)
    except Exception:
        return str(n)
    sign = '-' if n < 0 else ''
    n = abs(n)
    units = ['B', 'KB', 'MB', 'GB', 'TB']
    v = float(n)
    i = 0
    while v >= 1024.0 and i < len(units) - 1:
        v /= 1024.0
        i += 1
    if i == 0:
        return f"{sign}{int(v)} {units[i]}"
    return f"{sign}{v:.1f} {units[i]}"


def _song_dir_stats(song_dir: Path) -> Dict[str, object]:
    """Fast-ish stats to help choose between duplicate SongIDs."""
    d: Dict[str, object] = {
        'exists': False,
        'folder': str(song_dir) if str(song_dir) else '',
        'files': 0,
        'bytes': 0,
        'video_bytes': 0,
        'audio_bytes': 0,
        'melody1': False,
        'largest': [],
    }
    if not song_dir or not song_dir.exists() or not song_dir.is_dir():
        return d

    d['exists'] = True
    files = []
    try:
        files = [fp for fp in song_dir.rglob('*') if fp.is_file()]
    except Exception:
        files = []

    total_files = 0
    total_bytes = 0
    video_bytes = 0
    audio_bytes = 0
    melody1 = False
    largest = []

    for fp in files:
        total_files += 1
        name_l = fp.name.lower()
        if name_l in {'melody_1.xml', 'melody_1'}:
            melody1 = True
        try:
            size = int(fp.stat().st_size)
        except Exception:
            size = 0
        total_bytes += size
        ext = fp.suffix.lower()
        if ext in _VIDEO_EXTS or 'video' in name_l:
            video_bytes += size
        if ext in _AUDIO_EXTS or 'audio' in name_l:
            audio_bytes += size
        try:
            rel = fp.relative_to(song_dir).as_posix()
        except Exception:
            rel = fp.name
        largest.append((size, rel))

    largest = sorted(largest, key=lambda t: (-int(t[0]), t[1]))[:3]

    d['files'] = int(total_files)
    d['bytes'] = int(total_bytes)
    d['video_bytes'] = int(video_bytes)
    d['audio_bytes'] = int(audio_bytes)
    d['melody1'] = bool(melody1)
    d['largest'] = list(largest)
    return d


def _song_dir_listing(song_dir: Path) -> Dict[str, int]:
    out: Dict[str, int] = {}
    if not song_dir or not song_dir.exists() or not song_dir.is_dir():
        return out
    try:
        files = [fp for fp in song_dir.rglob('*') if fp.is_file()]
    except Exception:
        files = []
    for fp in files:
        try:
            rel = fp.relative_to(song_dir).as_posix()
        except Exception:
            rel = fp.name
        try:
            out[str(rel)] = int(fp.stat().st_size)
        except Exception:
            out[str(rel)] = -1
    return out


def _song_dir_diff(a: Path, b: Path) -> Dict[str, object]:
    la = _song_dir_listing(a)
    lb = _song_dir_listing(b)
    sa = set(la.keys())
    sb = set(lb.keys())

    only_a = sorted(sa - sb)
    only_b = sorted(sb - sa)
    common = sorted(sa & sb)
    size_diff = [k for k in common if int(la.get(k, -2)) != int(lb.get(k, -2))]

    bytes_a = sum(int(v) for v in la.values() if isinstance(v, int) and v >= 0)
    bytes_b = sum(int(v) for v in lb.values() if isinstance(v, int) and v >= 0)

    # Sample items for display
    def _sample(xs, n=8):
        return xs[:n] + ([f"... (+{len(xs)-n} more)"] if len(xs) > n else [])

    return {
        'only_a': only_a,
        'only_b': only_b,
        'size_diff': size_diff,
        'bytes_a': int(bytes_a),
        'bytes_b': int(bytes_b),
        'delta': int(bytes_a - bytes_b),
        'sample_only_a': _sample(only_a),
        'sample_only_b': _sample(only_b),
        'sample_size_diff': _sample(size_diff),
    }


def _autofix_display_duplicates_interactive(
    mw,
    selected_song_ids: Set[int],
    preferred_source_by_song_id: Dict[int, str],
) -> tuple[Set[int], Dict[int, str], list[str]]:
    """Detect Title+Artist duplicates among the selected songs and ask which to keep.

    Returns updated (selected_song_ids, preferred_source_by_song_id, log_lines).
    """
    selected_song_ids = set(int(x) for x in (selected_song_ids or set()))
    preferred_source_by_song_id = dict((int(k), str(v)) for (k, v) in (preferred_source_by_song_id or {}).items())

    groups: Dict[str, list[int]] = {}
    key_to_disp: Dict[str, tuple[str, str]] = {}
    for sid in sorted(selected_song_ids):
        s = mw._songs_by_id.get(int(sid))
        if s is None:
            continue
        title = str(getattr(s, "title", "") or "")
        artist = str(getattr(s, "artist", "") or "")
        k = _song_display_key(title, artist)
        if not k.strip():
            continue
        groups.setdefault(k, []).append(int(sid))
        key_to_disp.setdefault(k, (title, artist))

    dup_groups = {k: v for (k, v) in groups.items() if len(v) >= 2}
    if not dup_groups:
        return selected_song_ids, preferred_source_by_song_id, []

    overrides: Dict[str, int] = dict(getattr(mw, "_display_dup_keep_overrides", {}) or {})
    export_roots: Dict[str, str] = dict(getattr(mw, "_export_roots_by_label", {}) or {})

    log_lines: list[str] = []
    for k, ids in sorted(dup_groups.items(), key=lambda kv: (len(kv[1]), kv[0])):
        ids = sorted(set(int(x) for x in (ids or [])))
        if len(ids) < 2:
            continue

        title, artist = key_to_disp.get(k, ("", ""))
        disp_name = (f"{title} — {artist}" if title or artist else k)

        kept = overrides.get(k)
        if kept is not None and int(kept) in ids:
            drop = [x for x in ids if int(x) != int(kept)]
            for d in drop:
                selected_song_ids.discard(int(d))
                preferred_source_by_song_id.pop(int(d), None)
            if drop:
                log_lines.append(f"[build] Autofix: display-duplicate -> keep {int(kept)}, skip {drop} ({disp_name})")
            continue

        # Interactive choice
        # Build per-ID info (chosen source + song folder path)
        info = []
        for sid in ids:
            src = str(preferred_source_by_song_id.get(int(sid), "Base") or "Base")
            exp = str(export_roots.get(src, "") or "").strip()
            song_dir = (Path(exp) / str(int(sid))) if exp else Path("")
            info.append((int(sid), src, song_dir))
        ident_txt = "Unknown"
        ident_ok: Optional[bool] = None
        diff: Optional[Dict[str, object]] = None

        # Collect quick stats so the dialog can actually help the user choose.
        stats = []
        for sid, src, song_dir in info:
            try:
                stats.append(_song_dir_stats(Path(song_dir) if song_dir else Path("")))
            except Exception:
                stats.append(_song_dir_stats(Path("")))

        if len(info) == 2:
            a_sid, a_src, a_dir = info[0]
            b_sid, b_src, b_dir = info[1]
            ident_ok, ident_txt = _compare_song_folders(a_dir, b_dir)
            try:
                diff = _song_dir_diff(a_dir, b_dir)
            except Exception:
                diff = None

        # Conservative recommendation (only when it's clearly better).
        reco_id: Optional[int] = None
        reco_reason = ""
        if len(info) == 2:
            (a_sid, a_src, _a_dir) = info[0]
            (b_sid, b_src, _b_dir) = info[1]
            a_st = stats[0] if len(stats) > 0 else {}
            b_st = stats[1] if len(stats) > 1 else {}

            def _b(x) -> bool:
                return bool(x)

            # If byte-identical duplicates, prefer Base when present.
            if ident_ok is True and (a_src == "Base" or b_src == "Base"):
                reco_id = int(a_sid) if a_src == "Base" else int(b_sid)
                reco_reason = "byte-identical duplicates; keep Base"
            else:
                a_exists = _b(a_st.get('exists'))
                b_exists = _b(b_st.get('exists'))
                if a_exists and not b_exists:
                    reco_id = int(a_sid)
                    reco_reason = "only one has a song folder"
                elif b_exists and not a_exists:
                    reco_id = int(b_sid)
                    reco_reason = "only one has a song folder"
                else:
                    a_mel = _b(a_st.get('melody1'))
                    b_mel = _b(b_st.get('melody1'))
                    if a_mel != b_mel:
                        reco_id = int(a_sid) if a_mel else int(b_sid)
                        reco_reason = "only one has melody_1.xml"
                    else:
                        a_vid = int(a_st.get('video_bytes') or 0)
                        b_vid = int(b_st.get('video_bytes') or 0)
                        if (a_vid > 0) != (b_vid > 0):
                            reco_id = int(a_sid) if a_vid > 0 else int(b_sid)
                            reco_reason = "only one has video assets"
                        else:
                            a_aud = int(a_st.get('audio_bytes') or 0)
                            b_aud = int(b_st.get('audio_bytes') or 0)
                            if (a_aud > 0) != (b_aud > 0):
                                reco_id = int(a_sid) if a_aud > 0 else int(b_sid)
                                reco_reason = "only one has audio assets"
                            else:
                                a_files = int(a_st.get('files') or 0)
                                b_files = int(b_st.get('files') or 0)
                                a_bytes = int(a_st.get('bytes') or 0)
                                b_bytes = int(b_st.get('bytes') or 0)

                                # Recommend only if the difference is very obvious.
                                if a_files and b_files and a_files >= int(b_files * 1.4) and a_bytes >= int(b_bytes * 1.2):
                                    reco_id = int(a_sid)
                                    reco_reason = "more files and larger total size"
                                elif a_files and b_files and b_files >= int(a_files * 1.4) and b_bytes >= int(a_bytes * 1.2):
                                    reco_id = int(b_sid)
                                    reco_reason = "more files and larger total size"
                                elif a_bytes and b_bytes and a_bytes >= int(b_bytes * 1.8):
                                    reco_id = int(a_sid)
                                    reco_reason = "much larger total size"
                                elif a_bytes and b_bytes and b_bytes >= int(a_bytes * 1.8):
                                    reco_id = int(b_sid)
                                    reco_reason = "much larger total size"

        # Build rich, decision-oriented dialog text.
        esc = lambda s: html.escape(str(s or ''))

        # Differences summary (for main dialog).
        diff_summary = ''
        if ident_ok is True:
            diff_summary = f"<b>Compare:</b> {esc(ident_txt)}"
        elif ident_ok is False:
            if diff is not None:
                oa = int(len(diff.get('only_a') or []))
                ob = int(len(diff.get('only_b') or []))
                sd = int(len(diff.get('size_diff') or []))
                delta = int(diff.get('delta') or 0)
                diff_summary = (
                    f"<b>Differences:</b> {oa} only-in A, {ob} only-in B, {sd} size-different"
                    f" &nbsp;•&nbsp; size Δ {esc(_human_bytes(delta))}"
                )
            else:
                diff_summary = f"<b>Differences:</b> NOT identical ({esc(ident_txt)})"
        else:
            diff_summary = f"<b>Compare:</b> {esc(ident_txt)}"

        # Build the option table.
        rows = []
        for i, (sid, src, _song_dir) in enumerate(info[:4]):
            st = stats[i] if i < len(stats) else {}
            opt = chr(ord('A') + i)
            if reco_id is not None and int(sid) == int(reco_id):
                opt = f"{opt} (recommended)"
            files_txt = 'MISSING' if not bool(st.get('exists')) else str(int(st.get('files') or 0))
            bytes_txt = 'MISSING' if not bool(st.get('exists')) else _human_bytes(int(st.get('bytes') or 0))
            mel_txt = 'Yes' if bool(st.get('melody1')) else 'No'
            vid_b = int(st.get('video_bytes') or 0)
            aud_b = int(st.get('audio_bytes') or 0)
            vid_txt = '—' if vid_b <= 0 else _human_bytes(vid_b)
            aud_txt = '—' if aud_b <= 0 else _human_bytes(aud_b)

            rows.append(
                '<tr>'
                f'<td>{esc(opt)}</td>'
                f'<td>{esc(src)}</td>'
                f'<td>{esc(sid)}</td>'
                f'<td>{esc(files_txt)}</td>'
                f'<td>{esc(bytes_txt)}</td>'
                f'<td>{esc(mel_txt)}</td>'
                f'<td>{esc(vid_txt)}</td>'
                f'<td>{esc(aud_txt)}</td>'
                '</tr>'
            )

        table_html = (
            "<table border='1' cellspacing='0' cellpadding='4'>"
            "<tr><th>Option</th><th>Source</th><th>ID</th><th>Files</th><th>Total</th><th>Melody</th><th>Video</th><th>Audio</th></tr>"
            + ''.join(rows)
            + "</table>"
        )

        reco_line = ''
        if reco_id is not None:
            try:
                reco_src = next(src for (sid, src, _d) in info if int(sid) == int(reco_id))
            except Exception:
                reco_src = ''
            why = f" — {esc(reco_reason)}" if reco_reason else ''
            reco_line = f"<br><br><b>Recommended:</b> Keep ID {esc(reco_id)} ({esc(reco_src)}){why}"
        else:
            reco_line = (
                "<br><br><b>Tip:</b> If you're unsure, pick the version with more complete assets (video/audio present)."
            )

        msg_html = (
            "<b>Two selected songs share the same Title+Artist.</b><br>"
            "SingStar can hide duplicates, so only one should be kept on the output disc."
            f"<br><br><b>Title/Artist:</b> {esc(disp_name)}"
            + reco_line
            + f"<br><br>{table_html}"
            + (f"<br><br>{diff_summary}" if diff_summary else '')
            + "<br><br><i>This choice will be remembered for this project.</i>"
        )

        dlg = QMessageBox(mw)
        dlg.setIcon(QMessageBox.Warning if (ident_ok is False) else QMessageBox.Information)
        dlg.setWindowTitle("Duplicate song detected")
        try:
            dlg.setTextFormat(Qt.RichText)
        except Exception:
            pass
        dlg.setText(msg_html)

        # Put the noisy paths + file-diff listing behind the built-in 'Show Details…' expander.
        details_lines = []
        details_lines.append(f"Title/Artist: {disp_name}")
        details_lines.append('')
        for i, (sid, src, song_dir) in enumerate(info[:4]):
            st = stats[i] if i < len(stats) else {}
            opt = chr(ord('A') + i)
            details_lines.append(f"Option {opt}: ID {int(sid)} ({src})")
            loc = str(song_dir) if str(song_dir) else '(unknown folder)'
            details_lines.append(f"  Folder: {loc}")
            if not bool(st.get('exists')):
                details_lines.append('  Status: MISSING')
            else:
                details_lines.append(f"  Files: {int(st.get('files') or 0)}")
                details_lines.append(f"  Total: {_human_bytes(int(st.get('bytes') or 0))}")
                details_lines.append(f"  Melody_1.xml: {'yes' if bool(st.get('melody1')) else 'no'}")
                details_lines.append(f"  Video bytes: {_human_bytes(int(st.get('video_bytes') or 0))}")
                details_lines.append(f"  Audio bytes: {_human_bytes(int(st.get('audio_bytes') or 0))}")
                try:
                    largest = list(st.get('largest') or [])
                except Exception:
                    largest = []
                if largest:
                    details_lines.append('  Largest files:')
                    for sz, rel in largest:
                        details_lines.append(f"    - {rel} ({_human_bytes(int(sz) if sz is not None else 0)})")
            details_lines.append('')

        if diff is not None:
            details_lines.append('Differences between Option A and B:')
            try:
                details_lines.append(f"  Only in A: {len(diff.get('only_a') or [])}")
                for x in (diff.get('sample_only_a') or []):
                    details_lines.append(f"    - {x}")
                details_lines.append(f"  Only in B: {len(diff.get('only_b') or [])}")
                for x in (diff.get('sample_only_b') or []):
                    details_lines.append(f"    - {x}")
                details_lines.append(f"  Size-different files: {len(diff.get('size_diff') or [])}")
                for x in (diff.get('sample_size_diff') or []):
                    details_lines.append(f"    - {x}")
                details_lines.append(f"  Size delta (A - B): {_human_bytes(int(diff.get('delta') or 0))}")
            except Exception:
                pass

        try:
            dlg.setDetailedText('\n'.join(details_lines))
        except Exception:
            pass

        # Buttons
        btns = []
        for sid, src, _song_dir in info[:4]:
            if reco_id is not None and int(sid) == int(reco_id):
                cap = f"Keep recommended: ID {sid} ({src})"
            else:
                cap = f"Keep ID {sid} ({src})"
            btns.append(dlg.addButton(cap, QMessageBox.AcceptRole))
        btn_cancel = dlg.addButton("Cancel build", QMessageBox.RejectRole)

        try:
            dlg.exec()
        except Exception:
            return selected_song_ids, preferred_source_by_song_id, log_lines

        clicked = dlg.clickedButton()
        if clicked == btn_cancel:
            raise RuntimeError("Build cancelled (duplicate selection unresolved).")

        chosen_id = None
        for i, b in enumerate(btns):
            if clicked == b:
                chosen_id = int(info[i][0])
                break
        if chosen_id is None:
            raise RuntimeError("Build cancelled (no duplicate choice made).")

        # Persist override (so next build is non-interactive)
        try:
            overrides[str(k)] = int(chosen_id)
            mw._display_dup_keep_overrides = dict(overrides)
            mw._save_qt_state(force=True)
        except Exception:
            pass

        drop = [x for x in ids if int(x) != int(chosen_id)]
        for d in drop:
            selected_song_ids.discard(int(d))
            preferred_source_by_song_id.pop(int(d), None)
        if drop:
            log_lines.append(f"[build] Autofix: display-duplicate -> keep {int(chosen_id)}, skip {drop} ({disp_name})")

    return selected_song_ids, preferred_source_by_song_id, log_lines


def collect_validate_targets(mw) -> List[tuple[str, str]]:
    """Collect disc roots to validate.

    v0.9a4c: "Validate Selected" now strictly uses the selected rows in the
    Sources table. Base is only included if the Base row is selected.
    """
    targets: List[tuple[str, str]] = []

    # Determine selected rows (row-based)
    try:
        selected_rows = sorted({i.row() for i in mw.sources_table.selectedIndexes()})
    except Exception:
        selected_rows = []

    # For the "Selected" buttons we require an explicit selection.
    if not selected_rows:
        return targets

    # Include Base only if the Base row is selected.
    if any(mw._is_base_row(r) for r in selected_rows):
        base_path = mw.base_edit.text().strip()
        if base_path:
            targets.append(("Base", base_path))

    for r in selected_rows:
        if mw._is_base_row(r):
            continue
        try:
            if bool(mw.sources_table.isRowHidden(int(r))):
                continue
        except Exception:
            pass

        label = (mw.sources_table.item(r, 0).text() if mw.sources_table.item(r, 0) else "").strip()
        path = (mw.sources_table.item(r, 2).text() if mw.sources_table.item(r, 2) else "").strip()
        if not path:
            continue
        if not label:
            label = Path(path).name
        targets.append((label, path))

    return targets

def start_validate(mw) -> None:
    if mw._any_op_running():
        mw._log("[validate] Already running.")
        return

    targets = mw._collect_validate_targets()
    if not targets:
        QMessageBox.information(
            mw,
            "Validate",
            "No sources selected.\n\nSelect one or more discs in Sources, then click Validate Selected.",
        )
        return

    mw._last_validate_report_text = ""
    mw._validate_badge_by_path: Dict[str, str] = {}
    mw._active_op = "validate"
    mw._cancel_token = CancelToken()
    mw._set_op_running(True)

    mw._log(f"[validate] Starting ({len(targets)} target(s))...")
    for lbl, pth in targets:
        mw._log(f"[validate] - {lbl}: {pth}")

    t = QThread()
    w = ValidateWorker(targets, mw._cancel_token)
    w.moveToThread(t)

    t.started.connect(w.run, Qt.QueuedConnection)
    w.log.connect(mw._log)

    w.done.connect(mw._on_validate_done)
    w.cancelled.connect(mw._on_validate_cancelled)
    w.error.connect(mw._on_validate_error)
    # Robust finalize (v0.5.11a.3.1): always unlock when the worker finishes.
    def _finalize_validate() -> None:
        if mw._validate_thread is not t:
            return
        try:
            mw._cleanup_validate()
        except Exception as e:
            try:
                mw._log(f"[validate] finalize cleanup failed: {e}")
            except Exception:
                pass

    w.finished.connect(_finalize_validate)
    t.finished.connect(_finalize_validate)
    try:
        QTimer.singleShot(20000, lambda: (_finalize_validate() if (mw._validate_thread is t and (not t.isRunning())) else None))
    except Exception:
        pass
    try:
        t.finished.connect(t.deleteLater)
        w.finished.connect(w.deleteLater)
    except Exception:
        pass

    mw._validate_thread = t
    mw._validate_worker = w
    t.start()

def cancel_active(mw) -> None:
    if mw._cancel_token is not None:
        mw._log("[cancel] Cancel requested.")
        try:
            op = str(mw._active_op or "")
            if op:
                mw._set_progress_ui(phase="Cancelling", detail=f"Cancelling {op}...", indeterminate=True)
            else:
                mw._set_progress_ui(phase="Cancelling", detail="Cancelling...", indeterminate=True)
        except Exception:
            pass
        try:
            mw._cancel_token.cancel()
        except Exception:
            pass

def cleanup_validate(mw) -> None:
    # Called after validate completes/cancels/errors; stop thread loop and unlock UI.
    try:
        if mw._validate_thread is not None:
            mw._validate_thread.quit()
            if QThread.currentThread() is not mw._validate_thread:
                mw._validate_thread.wait(1500)
    except Exception:
        pass
    mw._validate_thread = None
    mw._validate_worker = None
    mw._cancel_token = None
    mw._set_op_running(False)
    mw._active_op = None

def write_validate_report_file(mw, report_text: str) -> str:
    out_path = mw.output_edit.text().strip()
    if not out_path:
        raise RuntimeError("Output location is empty. Set Output to write validate_report.txt.")
    od = Path(out_path).expanduser().resolve()
    od.mkdir(parents=True, exist_ok=True)
    rp = od / "validate_report.txt"
    rp.write_text(str(report_text or ""), encoding="utf-8")
    return str(rp)

def on_validate_done(mw, report_text: str, results: object) -> None:
    # Store report for clipboard
    mw._last_validate_report_text = str(report_text or "")

    # Summarise
    fail = 0
    warn = 0
    ok = 0
    try:
        for r in list(results or []):
            sev = str((r or {}).get("severity", "") or "").upper()
            if sev == "FAIL":
                fail += 1
            elif sev == "WARN":
                warn += 1
            else:
                ok += 1
    except Exception:
        pass

    mw._log(f"[validate] Done. OK={ok} WARN={warn} FAIL={fail}")

    try:
        show_status_message(mw, f"Validate complete: OK={ok} WARN={warn} FAIL={fail}.", 8000)
    except Exception:
        pass

    # Update state badges for Sources
    try:
        for r in list(results or []):
            try:
                pth = str((r or {}).get("input_path", "") or "").strip()
                if not pth:
                    continue
                sev = str((r or {}).get("severity", "") or "").upper()
                if sev == "FAIL":
                    badge = "X"
                elif sev == "WARN":
                    badge = "W"
                else:
                    badge = "V"
                mw._disc_validation_badge[mw._norm_key(pth)] = badge
            except Exception:
                continue
    except Exception:
        pass

    mw._refresh_source_states()

    if mw._last_validate_report_text.strip():
        mw.btn_copy_report.setEnabled(True)

    # Optional report file
    if bool(mw.chk_validate_write_report.isChecked()):
        try:
            rp = mw._write_validate_report_file(mw._last_validate_report_text)
            mw._log(f"[validate] Wrote validate_report.txt: {rp}")
        except Exception as e:
            mw._log(f"[validate] Could not write validate_report.txt: {e}")

    mw._cleanup_validate()

def on_validate_cancelled(mw) -> None:
    mw._log("[validate] Cancelled.")
    try:
        show_status_message(mw, 'Validate cancelled.', 5000)
    except Exception:
        pass
    mw._cleanup_validate()

def on_validate_error(mw, msg: str) -> None:
    mw._log(f"[validate] ERROR: {msg}")
    try:
        show_status_message(mw, 'Validate failed. See logs for details.', 8000)
    except Exception:
        pass
    mw._show_critical_with_logs("Validate failed", str(msg or "Unknown error"), tip="Tip: Click \"Open logs folder\" for details. If you need to share this, use Help > Export support bundle...")
    mw._cleanup_validate()

def copy_validate_report(mw) -> None:
    txt = str(getattr(mw, "_last_validate_report_text", "") or "")
    if not txt.strip():
        mw._log("[validate] No report to copy.")
        return
    try:
        QApplication.clipboard().setText(txt)
        mw._log("[validate] Report copied to clipboard.")
    except Exception as e:
        mw._log(f"[validate] Could not copy report: {e}")


# ---- Songs (v0.5.10c5) ----

def collect_extract_targets(mw) -> List[tuple[str, str]]:
    """Collect disc roots to extract.

    v0.9a4c: "Extract Selected" now strictly uses the selected rows in the
    Sources table. Base is only included if the Base row is selected.
    """
    targets: List[tuple[str, str]] = []

    # Determine selected rows (row-based)
    try:
        selected_rows = sorted({i.row() for i in mw.sources_table.selectedIndexes()})
    except Exception:
        selected_rows = []

    # For the "Selected" buttons we require an explicit selection.
    if not selected_rows:
        return targets

    # Include Base only if the Base row is selected.
    if any(mw._is_base_row(r) for r in selected_rows):
        base_path = mw.base_edit.text().strip()
        if base_path:
            targets.append(("Base", base_path))

    for r in selected_rows:
        if mw._is_base_row(r):
            continue
        try:
            if bool(mw.sources_table.isRowHidden(int(r))):
                continue
        except Exception:
            pass

        label = (mw.sources_table.item(r, 0).text() if mw.sources_table.item(r, 0) else "").strip()
        path = (mw.sources_table.item(r, 2).text() if mw.sources_table.item(r, 2) else "").strip()
        if not path:
            continue
        if not label:
            label = Path(path).name
        targets.append((label, path))

    return targets

def collect_packed_extract_targets(mw) -> List[tuple[str, str]]:
    targets: List[tuple[str, str]] = []

    base_path = mw.base_edit.text().strip()
    if base_path:
        try:
            st = mw._compute_disc_state(str(base_path))
        except Exception:
            st = ""
        if (("Packed" in str(st)) or ("Partial" in str(st)) or ("Needs extract" in str(st))) and ("Extracted" not in str(st)):
            targets.append(("Base", base_path))

    for r in range(mw.sources_table.rowCount()):
        if mw._is_base_row(r):
            continue
        label = (mw.sources_table.item(r, 0).text() if mw.sources_table.item(r, 0) else "").strip()
        path = (mw.sources_table.item(r, 2).text() if mw.sources_table.item(r, 2) else "").strip()
        if not path:
            continue
        if not label:
            label = Path(path).name
        try:
            st = mw._compute_disc_state(str(path))
        except Exception:
            st = ""
        if (("Packed" in str(st)) or ("Partial" in str(st)) or ("Needs extract" in str(st))) and ("Extracted" not in str(st)):
            targets.append((label, path))

    return targets

def start_extract_targets(mw, targets: List[tuple[str, str]]) -> None:
    if mw._any_op_running():
        mw._log("[extract] Another operation is already running.")
        return

    extractor_exe = mw.extractor_edit.text().strip()
    if not extractor_exe:
        QMessageBox.warning(mw, "Extract", "Extractor is not set.\n\nSet the SCEE extractor binary (scee_london / scee_london.exe) first.")
        return

    targets = list(targets or [])
    if not targets:
        QMessageBox.warning(mw, "Extract", "Nothing to extract.\n\nSet Base and/or add at least one Source.")
        return


    try:
        mw._extract_post_cleanup_mode = None
    except Exception:
        pass

    # If any selected targets are packed/unextracted, confirm unpack + optional post-verify cleanup.
    packed_targets: list[tuple[str, str]] = []
    try:
        for lbl, pth in targets:
            try:
                st = mw._compute_disc_state(str(pth))
            except Exception:
                st = ""
            if (("Packed" in str(st)) or ("Partial" in str(st)) or ("Needs extract" in str(st))) and ("Extracted" not in str(st)):
                packed_targets.append((str(lbl), str(pth)))
    except Exception:
        packed_targets = []

    if packed_targets:
        dlg = QMessageBox(mw)
        dlg.setIcon(QMessageBox.Question)
        dlg.setWindowTitle("Extract packed disc(s)?")
        try:
            names = [str(x[0] or '') for x in packed_targets if str(x[0] or '').strip()]
        except Exception:
            names = []
        if not names:
            names = [f"{len(packed_targets)} disc(s)"]
        preview = ", ".join(names[:4])
        if len(names) > 4:
            preview = preview + f" (+{len(names)-4} more)"
        dlg.setText(
            "One or more selected sources are packed (unextracted).\n\n"
            f"Extract now: {preview}\n\n"
            "After extraction completes, you can optionally clean up:\n"
            "  • Pack*.pkd_out folders (recommended)\n"
            "  • Pack*.pkd files (optional)\n\n"
            "Cleanup is destructive: files are MOVED into _spcdb_trash after verification passes."
        )

        btn_cancel = dlg.addButton("Cancel", QMessageBox.RejectRole)
        btn_unpack = dlg.addButton("Extract / Unpack", QMessageBox.AcceptRole)
        btn_pkd_out = dlg.addButton("Unpack + cleanup pkd_out", QMessageBox.ActionRole)
        btn_both = dlg.addButton("Unpack + cleanup pkd_out + pkd", QMessageBox.ActionRole)

        dlg.exec()

        clicked = dlg.clickedButton()
        if clicked is btn_cancel:
            return
        if clicked is btn_unpack:
            mw._extract_post_cleanup_mode = "skip"
        elif clicked is btn_pkd_out:
            mw._extract_post_cleanup_mode = "pkd_out"
        elif clicked is btn_both:
            mw._extract_post_cleanup_mode = "both"
        else:
            mw._extract_post_cleanup_mode = "skip"

    mw._active_op = "extract"
    mw._cancel_token = CancelToken()
    mw._set_op_running(True)

    mw._log(f"[extract] Starting ({len(targets)} disc(s))...")
    for lbl, pth in targets:
        mw._log(f"[extract] - {lbl}: {pth}")

    t = QThread()
    w = ExtractWorker(extractor_exe, targets, mw._cancel_token)
    w.moveToThread(t)

    t.started.connect(w.run, Qt.QueuedConnection)
    w.log.connect(mw._log)

    w.done.connect(mw._on_extract_done)
    w.cancelled.connect(mw._on_extract_cancelled)
    w.error.connect(mw._on_extract_error)

    def _finalize_extract() -> None:
        if mw._extract_thread is not t:
            return
        try:
            t.quit()
        except Exception:
            pass
        if str(mw._active_op or "") != "extract":
            return
        mw._extract_thread = None
        mw._extract_worker = None
        mw._cancel_token = None
        mw._set_op_running(False)
        mw._active_op = None

    w.finished.connect(_finalize_extract)
    t.finished.connect(_finalize_extract)
    try:
        t.finished.connect(t.deleteLater)
        w.finished.connect(w.deleteLater)
    except Exception:
        pass

    mw._extract_thread = t
    mw._extract_worker = w
    t.start()

def start_extract_packed_only(mw) -> None:
    targets = mw._collect_packed_extract_targets()
    if not targets:
        QMessageBox.information(mw, "Extract", "No packed (unextracted) discs to extract.")
        return
    mw._start_extract_targets(targets)

def start_extract(mw) -> None:
    targets = mw._collect_extract_targets()
    if not targets:
        QMessageBox.information(
            mw,
            "Extract",
            "No sources selected.\n\nSelect one or more discs in Sources, then click Extract Selected.",
        )
        return
    mw._start_extract_targets(targets)

def cleanup_extract(mw) -> None:
    try:
        if mw._extract_thread is not None:
            mw._extract_thread.quit()
            if QThread.currentThread() is not mw._extract_thread:
                mw._extract_thread.wait(1500)
    except Exception:
        pass
    mw._extract_thread = None
    mw._extract_worker = None
    mw._cancel_token = None
    mw._set_op_running(False)
    mw._active_op = None
    try:
        mw._extract_post_cleanup_mode = None
    except Exception:
        pass

def on_extract_done(mw, results: object) -> None:
    results_list = []
    try:
        results_list = list(results or [])
    except Exception:
        results_list = []

    extracted_n = int(len(results_list))
    verified_ok = 0
    verified_fail = 0
    cleanup_candidates: list[str] = []

    for r in results_list:
        try:
            disc_root = str((r or {}).get("disc_root", "") or "").strip()
        except Exception:
            disc_root = ""
        if not disc_root:
            continue

        v = {}
        try:
            v = (r or {}).get("verify") or {}
        except Exception:
            v = {}

        ok = bool((v or {}).get("ok"))
        try:
            mw._disc_extraction_verified[mw._norm_key(disc_root)] = bool(ok)
        except Exception:
            pass

        if ok:
            verified_ok += 1
        else:
            verified_fail += 1

        try:
            arts = (v or {}).get("artifacts") or {}
            pkd_out_dirs = list(arts.get("pkd_out_dirs", []) or [])
            pkd_files = list(arts.get("pkd_files", []) or [])
        except Exception:
            pkd_out_dirs = []
            pkd_files = []

        if ok and (pkd_out_dirs or pkd_files):
            cleanup_candidates.append(disc_root)

    refresh_roots: List[str] = []
    try:
        seen = set()
        for r in results_list:
            try:
                dr = str((r or {}).get("disc_root", "") or "").strip()
            except Exception:
                dr = ""
            if not dr:
                continue
            try:
                st = mw._compute_disc_state(str(dr))
            except Exception:
                st = ""
            if "Extracted" not in str(st):
                continue
            k = mw._norm_key(str(dr))
            if k in seen:
                continue
            seen.add(k)
            refresh_roots.append(str(dr))
    except Exception:
        refresh_roots = []

    mw._log(f"[extract] Done. Extracted={extracted_n} | Verified OK={verified_ok} FAIL={verified_fail}")

    try:
        show_status_message(mw, f"Extract complete: {extracted_n} discs. Verified OK={verified_ok} FAIL={verified_fail}.", 8000)
    except Exception:
        pass

    try:
        mw._refresh_source_states()
    except Exception:
        pass
    mw._cleanup_extract()


    # If user already chose a cleanup mode up-front, apply it automatically (no second popup).
    mode = None
    try:
        mode = str(mw._extract_post_cleanup_mode or "").strip() or None
    except Exception:
        mode = None

    if mode in ("skip", "pkd_out", "both"):
        try:
            mw._extract_post_cleanup_mode = None
        except Exception:
            pass
        # If cleanup is requested, defer the song refresh until cleanup completes (ops cannot overlap).
        if cleanup_candidates and (mode in ("pkd_out", "both")):
            try:
                mw._pending_auto_refresh_roots = list(refresh_roots or [])
            except Exception:
                pass
            if mode == "pkd_out":
                mw._start_cleanup_targets(cleanup_candidates, include_pkd_files=False)
            elif mode == "both":
                mw._start_cleanup_targets(cleanup_candidates, include_pkd_files=True)
            return
        # Otherwise refresh now (best-effort).
        try:
            mw._auto_refresh_songs_for_roots(list(refresh_roots or []))
        except Exception:
            pass
        return

    # Offer cleanup only if verification passed (destructive move into _spcdb_trash).
    if cleanup_candidates:
        dlg = QMessageBox(mw)
        dlg.setIcon(QMessageBox.Warning)
        dlg.setWindowTitle("Cleanup extraction artifacts?")
        dlg.setText(
            "Extraction verified.\n\n"
            "You can now clean up legacy extraction artifacts:\n"
            "  • Pack*.pkd_out folders (default)\n"
            "  • Pack*.pkd files (optional)\n\n"
            "This is destructive: files are MOVED out of the disc folder into _spcdb_trash."
        )

        btn_skip = dlg.addButton("Skip", QMessageBox.RejectRole)
        btn_pkd_out = dlg.addButton("Cleanup pkd_out only", QMessageBox.AcceptRole)
        btn_both = dlg.addButton("Cleanup pkd_out + pkd files", QMessageBox.ActionRole)

        try:
            dlg.setInformativeText(
                "Only discs that passed verification are eligible for cleanup.\n"
                "If you later need to restore anything, look inside:\n"
                "<discs_folder>/_spcdb_trash/<timestamp>/<disc_folder>/"
            )
        except Exception:
            pass

        dlg.exec()

        clicked = dlg.clickedButton()
        if clicked is btn_pkd_out:
            try:
                mw._pending_auto_refresh_roots = list(refresh_roots or [])
            except Exception:
                pass
            mw._start_cleanup_targets(cleanup_candidates, include_pkd_files=False)
            return
        elif clicked is btn_both:
            try:
                mw._pending_auto_refresh_roots = list(refresh_roots or [])
            except Exception:
                pass
            mw._start_cleanup_targets(cleanup_candidates, include_pkd_files=True)
            return
        else:
            # Skip cleanup: refresh songs now (best-effort).
            try:
                mw._auto_refresh_songs_for_roots(list(refresh_roots or []))
            except Exception:
                pass

    else:
        # No cleanup eligible: refresh songs now (best-effort).
        try:
            mw._auto_refresh_songs_for_roots(list(refresh_roots or []))
        except Exception:
            pass

def on_extract_cancelled(mw) -> None:
    mw._log("[extract] Cancelled.")
    try:
        show_status_message(mw, 'Extract cancelled.', 5000)
    except Exception:
        pass
    mw._cleanup_extract()

def on_extract_error(mw, msg: str) -> None:
    mw._log(f"[extract] ERROR: {msg}")
    try:
        show_status_message(mw, 'Extract failed. See logs for details.', 8000)
    except Exception:
        pass
    mw._show_critical_with_logs("Extract failed", str(msg or "Unknown error"), tip="Tip: Confirm the extractor executable path is set, then check the logs.")
    mw._cleanup_extract()



# ---- Build action (v0.5.10c5) ----

def start_build(mw) -> None:
    if mw._any_op_running():
        mw._log('[build] Another operation is already running.')
        return

    try:
        mw._build_mode = 'build'
        mw._last_update_delta = None
    except Exception:
        pass

    base_path = mw.base_edit.text().strip()
    if not base_path:
        QMessageBox.warning(mw, 'Build', 'Base path is empty. Set Base first.')
        return

    out_path = mw.output_edit.text().strip()
    if not out_path:
        QMessageBox.warning(mw, 'Build', 'Output location is empty. Set Output first.')
        return
    out_parent = Path(out_path).expanduser().resolve()
    if out_parent.exists() and (not out_parent.is_dir()):
        mw._show_critical_with_logs('Build', f'Output location is not a folder\n\n{out_parent}')
        return
    try:
        out_parent.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        mw._show_critical_with_logs('Build', f'Cannot create output location\n\n{out_parent}\n\n{e}')
        return

    # Need song catalog (Qt parity with Tk: Build selection is song-based)
    if not mw._songs_all or not mw._songs_by_id:
        QMessageBox.warning(
            mw,
            'Update Existing',
            'Song catalog not loaded yet.\n\nClick "Refresh Songs" first (or wait for the auto-refresh to finish).',
        )
        return

    src_label_paths = mw._collect_build_sources()
    # Refuse to "update" in-place on one of the Source discs (foot-gun).
    try:
        out_abs = Path(str(out_dir)).expanduser().resolve()
        for lbl, sp in (src_label_paths or []):
            try:
                sp_abs = Path(str(sp)).expanduser().resolve()
                if sp_abs == out_abs:
                    QMessageBox.warning(
                        mw,
                        "Update Existing",
                        "The selected folder matches one of your Sources.\n\n"
                        "Choose the built output disc folder (the one you are updating), not a Source disc folder.",
                    )
                    return
            except Exception:
                continue
    except Exception:
        pass

    available_labels = {'Base'} | {str(lbl) for (lbl, _p) in (src_label_paths or [])}

    raw_selected = set(int(x) for x in (mw._selected_song_ids or set()))
    if not raw_selected:
        QMessageBox.warning(
            mw,
            'Build',
            'No songs selected.\n\nTick songs in the Songs table, or use "Select All (visible)".',
        )
        return

    selected_song_ids: Set[int] = set()
    preferred_source_by_song_id: Dict[int, str] = {}
    missing: List[int] = []

    for sid in sorted(raw_selected):
        s = mw._songs_by_id.get(int(sid))
        if s is None:
            continue
        try:
            sources = [str(x) for x in (getattr(s, 'sources', ()) or ())]
        except Exception:
            sources = []

        sources_avail = [lab for lab in sources if lab in available_labels]
        if not sources_avail:
            missing.append(int(sid))
            continue

        if 'Base' in sources_avail:
            chosen = 'Base'
        else:
            pref = str(getattr(s, 'preferred_source', '') or '')
            if pref and pref in sources_avail:
                chosen = pref
            else:
                chosen = str(sources_avail[0])

        selected_song_ids.add(int(sid))
        preferred_source_by_song_id[int(sid)] = str(chosen)

    if not selected_song_ids:
        QMessageBox.warning(
            mw,
            'Build',
            'None of the selected songs are available in the currently selected Base/Sources.',
        )
        return

    if missing:
        mw._log(f'[build] NOTE: {len(missing)} selected song(s) not found in current discs; they will be skipped.')

    
    # Snapshot build-eligible selection before any autofix (for summary + reproducibility)
    try:
        mw._last_build_ids_before_autofix = set(int(x) for x in (selected_song_ids or set()))
    except Exception:
        pass

    # Pre-build selection stats (Selected / Unique / Duplicate groups)
    try:
        st_before = _display_duplicate_stats(mw, selected_song_ids)
        sel_n = int(st_before.get("selected", 0) or 0)
        uniq_n = int(st_before.get("unique", 0) or 0)
        dup_g = int(st_before.get("dup_groups", 0) or 0)
        try:
            mw._log(
                f"[build] Selection: {sel_n} selected / {uniq_n} unique (Title+Artist) / {dup_g} duplicate group(s)"
            )
        except Exception:
            pass
        try:
            show_status_message(mw, f"Selection: {sel_n} selected • {uniq_n} unique • {dup_g} dup group(s)", 9000)
        except Exception:
            pass

        # Stash for end-of-build summary dialog
        try:
            mw._last_build_dup_summary = {
                "selected_before": sel_n,
                "unique_before": uniq_n,
                "dup_groups": dup_g,
                "dups": list(st_before.get("dups", []) or []),
                "dropped_ids": [],
                "kept_ids": [],
                "selected_after": sel_n,
                "dropped": 0,
            }
        except Exception:
            pass
    except Exception:
        pass

    # Autofix: display duplicates (same Title+Artist with different Song IDs)
    # -> asks which to keep, then removes the others from this build.
    try:
        selected_song_ids, preferred_source_by_song_id, fix_logs = _autofix_display_duplicates_interactive(
            mw, selected_song_ids, preferred_source_by_song_id
        )
        for ln in (fix_logs or []):
            try:
                mw._log(str(ln))
            except Exception:
                pass
    except Exception as e:
        # User cancelled or something went wrong; do not start the build.
        try:
            mw._log(f"[build] Cancelled: {e}")
        except Exception:
            pass
        return

    # Update duplicate summary after autofix (for Build Complete dialog)
    try:
        before = dict(getattr(mw, "_last_build_dup_summary", {}) or {})
        snap_before = set(int(x) for x in (getattr(mw, "_last_build_ids_before_autofix", set()) or set()))
        if not snap_before:
            snap_before = set(int(x) for x in (selected_song_ids or set()))
        after_ids = set(int(x) for x in (selected_song_ids or set()))
        removed = sorted(int(x) for x in (snap_before - after_ids))
        dropped_n = int(len(removed))

        before["selected_after"] = int(len(after_ids))
        before["dropped"] = int(dropped_n)
        before["dropped_ids"] = removed

        # Keep only kept IDs that were part of a dup group (prebuild)
        try:
            dup_ids = set()
            for g in (before.get("dups", []) or []):
                for sid in (g.get("ids", []) or []):
                    dup_ids.add(int(sid))
            before["kept_ids"] = sorted(int(x) for x in (after_ids & dup_ids))
        except Exception:
            before["kept_ids"] = []

        mw._last_build_dup_summary = dict(before)

        if dropped_n > 0:
            try:
                mw._log(
                    f"[build] Duplicates resolved: dropped {dropped_n} duplicate song id(s): "
                    f"{removed[:12]}{' ...' if len(removed) > 12 else ''}"
                )
            except Exception:
                pass
    except Exception:
        pass

    # Output location semantics (v0.8d): user chooses a parent folder; we create a new auto-named subfolder inside it.
    out_name = mw._suggest_output_name(len(selected_song_ids))
    out_dir = mw._first_available_outdir(out_parent, out_name)
    mw._log(f'[build] Output: {out_dir}')

    needed_donors = {v for v in preferred_source_by_song_id.values() if v != 'Base'}
    # If preflight validation is enabled, ensure Copy report reflects THIS run, not a previous one.
    if bool(mw.chk_preflight.isChecked()):
        mw._last_validate_report_text = ""
        mw._validate_badge_by_path = {}
        try:
            mw.btn_copy_report.setEnabled(False)
        except Exception:
            pass

    mw._active_op = 'build'
    mw._cancel_token = CancelToken()
    mw._set_op_running(True)

    mw._log('[build] Starting...')
    mw._log(f'[build] Base: {base_path}')
    mw._log(f'[build] Songs: {len(selected_song_ids)} selected')

    if src_label_paths:
        mw._log(f'[build] Sources: {len(src_label_paths)} (needed donors: {len(needed_donors)})')
        for lbl, pth in src_label_paths:
            mw._log(f'[build] - {lbl}: {pth}')
    else:
        mw._log('[build] No Sources selected; building from Base only.')

    # Map song_id -> all source labels where it exists (for build_report.json dedupe stats)
    try:
        song_sources_by_id = {int(sid): tuple(getattr(mw._songs_by_id.get(int(sid)), 'sources', ()) or ()) for sid in selected_song_ids}
    except Exception:
        song_sources_by_id = {}

    # Capture an expected song list (ID + title/artist + chosen source) so builds can emit a diff
    # without needing any post-hoc scripting.
    try:
        expected_song_rows = []
        for sid in sorted(selected_song_ids):
            s = mw._songs_by_id.get(int(sid))
            if s is None:
                continue
            expected_song_rows.append({
                'song_id': int(sid),
                'title': str(getattr(s, 'title', '') or ''),
                'artist': str(getattr(s, 'artist', '') or ''),
                'chosen_source': str(preferred_source_by_song_id.get(int(sid), 'Base') or 'Base'),
                'available_sources': [str(x) for x in (getattr(s, 'sources', ()) or ())],
            })
    except Exception:
        expected_song_rows = []


    t = QThread()
    w = BuildWorker(
        base_path=base_path,
        src_label_paths=src_label_paths,
        out_dir=str(out_dir),
        allow_overwrite_output=bool(getattr(mw, 'chk_allow_overwrite', None).isChecked() if getattr(mw, 'chk_allow_overwrite', None) is not None else False),
        keep_backup_of_existing_output=bool(getattr(mw, 'chk_keep_backup', None).isChecked() if getattr(mw, 'chk_keep_backup', None) is not None else True),
        selected_song_ids=set(int(x) for x in selected_song_ids),
        needed_donors=set(str(x) for x in needed_donors),
        preferred_source_by_song_id=dict((int(k), str(v)) for (k, v) in preferred_source_by_song_id.items()),
        song_sources_by_id=song_sources_by_id,
        expected_song_rows=list(expected_song_rows or []),
        preflight_validate=bool(mw.chk_preflight.isChecked()),
        block_on_errors=bool(mw.chk_block_build.isChecked()),
        cancel_token=mw._cancel_token,
    )
    w.moveToThread(t)

    t.started.connect(w.run, Qt.QueuedConnection)
    w.log.connect(mw._log)
    w.preflight_report.connect(mw._on_preflight_report)

    w.done.connect(mw._on_build_done)
    w.cancelled.connect(mw._on_build_cancelled)
    w.blocked.connect(mw._on_build_blocked)
    w.error.connect(mw._on_build_error)
    def _finalize_build() -> None:
        if mw._build_thread is not t:
            return
        try:
            t.quit()
        except Exception:
            pass
        if str(mw._active_op or '') != 'build':
            return
        try:
            # Ensure we don't keep stale per-build summary around.
            mw._last_build_dup_summary = None
            mw._last_build_ids_before_autofix = set()
        except Exception:
            pass
        mw._build_thread = None
        mw._build_worker = None
        mw._cancel_token = None
        mw._set_op_running(False)
        mw._active_op = None

    w.finished.connect(_finalize_build)
    t.finished.connect(_finalize_build)
    try:
        t.finished.connect(t.deleteLater)
        w.finished.connect(w.deleteLater)
    except Exception:
        pass

    mw._build_thread = t
    mw._build_worker = w
    t.start()

def start_update_existing(mw) -> None:
    """Update an already-built output disc folder in-place.

    This uses the Build engine in overwrite mode with:
      - keep_backup_of_existing_output=True
      - fast_update_existing_output=True

    The old output folder is moved to a backup, then the new output is built.
    Fast update seeds the build from the backup (using hardlinks where possible),
    so adding a few songs or updating branding is much faster than a full rebuild.
    """
    if mw._any_op_running():
        mw._log('[update] Another operation is already running.')
        return

    base_path = mw.base_edit.text().strip()
    if not base_path:
        QMessageBox.warning(mw, 'Update Existing', 'Base path is empty. Set Base first.')
        return

    # Need song catalog (Qt parity with Tk: Build selection is song-based)
    if not mw._songs_all or not mw._songs_by_id:
        QMessageBox.warning(
            mw,
            'Update Existing',
            'Song catalog not loaded yet.\n\nClick "Refresh Songs" first (or wait for the auto-refresh to finish).',
        )
        return

    try:
        mw._build_mode = 'update'
        mw._last_update_delta = None
    except Exception:
        pass

    # Pick the existing output disc folder.
    try:
        from PySide6.QtWidgets import QFileDialog  # type: ignore
    except Exception:
        QFileDialog = None  # type: ignore

    start_dir = ''
    try:
        start_dir = mw.output_edit.text().strip()
    except Exception:
        start_dir = ''
    if not start_dir:
        start_dir = base_path

    chosen_dir = ''
    try:
        if QFileDialog is not None:
            chosen_dir = QFileDialog.getExistingDirectory(
                mw,
                'Update existing output disc… (choose folder containing PS3_GAME)',
                str(start_dir or ''),
            )
    except Exception:
        chosen_dir = ''

    if not chosen_dir:
        return

    chosen_p = Path(str(chosen_dir)).expanduser().resolve()

    # Accept either the disc root or PS3_GAME folder.
    if chosen_p.name.upper() == 'PS3_GAME':
        disc_root = chosen_p.parent
    else:
        disc_root = chosen_p

    if not (disc_root / 'PS3_GAME').exists():
        # If they picked a parent folder, try one level down by common patterns.
        QMessageBox.warning(
            mw,
            'Update Existing',
            'That folder does not look like a disc root.\n\nChoose the disc folder that contains "PS3_GAME" (or choose the PS3_GAME folder itself).',
        )
        return

    # Reject obvious wrong picks (backup/temp folders) to avoid updating the wrong directory.
    try:
        dn = str(disc_root.name or '')
        if ('.__BACKUP_' in dn) or ('._BUILDING_tmp' in dn) or ('.__CANCELLED' in dn) or ('.__OVERWRITTEN_' in dn):
            QMessageBox.warning(
                mw,
                'Update Existing',
                'That looks like a temporary/backup build folder.\n\nChoose the main output disc folder (the one you normally copy to your PS3), not a backup/temp folder.',
            )
            return
    except Exception:
        pass

    # Additional sanity: chosen folder should look like a prior SSPCDB output (Export signature).
    try:
        from ..subset import _looks_like_spcdb_output_folder  # type: ignore
        ok, reason = _looks_like_spcdb_output_folder(disc_root)
        if not ok:
            QMessageBox.warning(
                mw,
                'Update Existing',
                f'That folder does not look like an SSPCDB output disc folder.\n\nReason: {reason}\n\nChoose the disc folder that contains PS3_GAME and a valid Export folder (songs/config).',
            )
            return
    except Exception:
        pass


    out_dir = disc_root
    try:
        base_root = Path(str(base_path)).expanduser().resolve()
        if base_root == out_dir:
            QMessageBox.warning(
                mw,
                'Update Existing',
                'The selected folder is the same as Base.\n\n'
                'Do not update in-place on the Base disc folder. Choose the built output disc folder instead.',
            )
            return
    except Exception:
        pass

    src_label_paths = mw._collect_build_sources()
    available_labels = {'Base'} | {str(lbl) for (lbl, _p) in (src_label_paths or [])}

    raw_selected = set(int(x) for x in (mw._selected_song_ids or set()))
    if not raw_selected:
        QMessageBox.warning(
            mw,
            'Update Existing',
            'No songs selected.\n\nTick songs in the Songs table, or use "Select All (visible)".',
        )
        return

    selected_song_ids: Set[int] = set()
    preferred_source_by_song_id: Dict[int, str] = {}
    missing: List[int] = []

    for sid in sorted(raw_selected):
        s = mw._songs_by_id.get(int(sid))
        if s is None:
            continue
        try:
            sources = [str(x) for x in (getattr(s, 'sources', ()) or ())]
        except Exception:
            sources = []

        sources_avail = [lab for lab in sources if lab in available_labels]
        if not sources_avail:
            missing.append(int(sid))
            continue

        if 'Base' in sources_avail:
            chosen = 'Base'
        else:
            pref = str(getattr(s, 'preferred_source', '') or '')
            if pref and pref in sources_avail:
                chosen = pref
            else:
                chosen = str(sources_avail[0])

        selected_song_ids.add(int(sid))
        preferred_source_by_song_id[int(sid)] = str(chosen)

    if not selected_song_ids:
        QMessageBox.warning(
            mw,
            'Update Existing',
            'None of the selected songs are available in the currently selected Base/Sources.',
        )
        return

    if missing:
        mw._log(f'[update] NOTE: {len(missing)} selected song(s) not found in current discs; they will be skipped.')

    # Snapshot build-eligible selection before any autofix (for summary + reproducibility)
    try:
        mw._last_build_ids_before_autofix = set(int(x) for x in (selected_song_ids or set()))
    except Exception:
        pass

    # Pre-build selection stats (Selected / Unique / Duplicate groups)
    try:
        st_before = _display_duplicate_stats(mw, selected_song_ids)
        sel_n = int(st_before.get("selected", 0) or 0)
        uniq_n = int(st_before.get("unique", 0) or 0)
        dup_g = int(st_before.get("dup_groups", 0) or 0)
        try:
            mw._log(
                f"[update] Selection: {sel_n} selected / {uniq_n} unique (Title+Artist) / {dup_g} duplicate group(s)"
            )
        except Exception:
            pass
        try:
            show_status_message(mw, f"Selection: {sel_n} selected • {uniq_n} unique • {dup_g} dup group(s)", 9000)
        except Exception:
            pass

        # Stash for end-of-build summary dialog
        try:
            mw._last_build_dup_summary = {
                "selected_before": sel_n,
                "unique_before": uniq_n,
                "dup_groups": dup_g,
                "dups": list(st_before.get("dups", []) or []),
                "dropped_ids": [],
                "kept_ids": [],
                "selected_after": sel_n,
                "dropped": 0,
            }
        except Exception:
            pass
    except Exception:
        pass

    # Autofix: display duplicates (same Title+Artist with different Song IDs)
    # -> asks which to keep, then removes the others from this build.
    try:
        selected_song_ids, preferred_source_by_song_id, fix_logs = _autofix_display_duplicates_interactive(
            mw, selected_song_ids, preferred_source_by_song_id
        )
        for ln in (fix_logs or []):
            try:
                mw._log(str(ln))
            except Exception:
                pass
    except Exception as e:
        # User cancelled or something went wrong; do not start the update.
        try:
            mw._log(f"[update] Cancelled: {e}")
        except Exception:
            pass
        return

    # Update duplicate summary after autofix (for Build Complete dialog)
    try:
        before = dict(getattr(mw, "_last_build_dup_summary", {}) or {})
        snap_before = set(int(x) for x in (getattr(mw, "_last_build_ids_before_autofix", set()) or set()))
        if not snap_before:
            snap_before = set(int(x) for x in (selected_song_ids or set()))
        after_ids = set(int(x) for x in (selected_song_ids or set()))
        removed = sorted(int(x) for x in (snap_before - after_ids))
        dropped_n = int(len(removed))

        before["selected_after"] = int(len(after_ids))
        before["dropped"] = int(dropped_n)
        before["dropped_ids"] = removed

        # Keep only kept IDs that were part of a dup group (prebuild)
        try:
            dup_ids = set()
            for g in (before.get("dups", []) or []):
                for sid in (g.get("ids", []) or []):
                    dup_ids.add(int(sid))
            before["kept_ids"] = sorted(int(x) for x in (after_ids & dup_ids))
        except Exception:
            before["kept_ids"] = []

        mw._last_build_dup_summary = dict(before)

        if dropped_n > 0:
            try:
                mw._log(
                    f"[update] Duplicates resolved: dropped {dropped_n} duplicate song id(s): "
                    f"{removed[:12]}{' ...' if len(removed) > 12 else ''}"
                )
            except Exception:
                pass
    except Exception:
        pass

    # Pre-flight delta summary (existing output vs selection) + confirmation.
    existing_ids: Set[int] = set()
    try:
        from ..subset import _find_export_root_from_disc_root  # type: ignore
        exp_root = _find_export_root_from_disc_root(out_dir)
        for p in exp_root.iterdir():
            try:
                if p.is_dir() and str(p.name).isdigit():
                    existing_ids.add(int(p.name))
            except Exception:
                continue
    except Exception:
        existing_ids = set()

    try:
        sel_ids = set(int(x) for x in (selected_song_ids or set()))
        added_n = int(len(sel_ids - existing_ids))
        removed_n = int(len(existing_ids - sel_ids))
        try:
            mw._last_update_delta = {
                'existing': int(len(existing_ids)),
                'selected': int(len(sel_ids)),
                'added': int(added_n),
                'removed': int(removed_n),
            }
        except Exception:
            pass

        msg_lines = [
            f"Output folder:\n  {out_dir}",
            "",
            f"Current output songs: {len(existing_ids)}",
            f"Included songs: {len(sel_ids)}",
            f"Delta: +{added_n} added, -{removed_n} removed",
            "",
            "A backup folder will be created next to it (Option B).",
            "Branding will be regenerated from current Disc Branding settings.",
            "",
            "Continue?",
        ]
        res = QMessageBox.question(
            mw,
            'Update Existing',
            "\n".join(msg_lines),
            QMessageBox.Ok | QMessageBox.Cancel,
            QMessageBox.Ok,
        )
        if res != QMessageBox.Ok:
            return
    except Exception:
        # If the summary dialog fails for any reason, proceed (best-effort).
        pass


    # Force overwrite + backup in update mode.
    allow_overwrite_output = True
    keep_backup_of_existing_output = True
    fast_update_existing_output = True

    needed_donors = {v for v in preferred_source_by_song_id.values() if v != 'Base'}

    # If preflight validation is enabled, ensure Copy report reflects THIS run, not a previous one.
    if bool(mw.chk_preflight.isChecked()):
        mw._last_validate_report_text = ""
        mw._validate_badge_by_path = {}
        try:
            mw.btn_copy_report.setEnabled(False)
        except Exception:
            pass

    mw._active_op = 'build'
    mw._cancel_token = CancelToken()
    mw._set_op_running(True)

    mw._log('[update] Starting...')
    mw._log(f'[update] Base: {base_path}')
    mw._log(f'[update] Output (in-place): {out_dir}')
    mw._log(f'[update] Songs: {len(selected_song_ids)} selected')

    if src_label_paths:
        mw._log(f'[update] Sources: {len(src_label_paths)} (needed donors: {len(needed_donors)})')
        for lbl, pth in src_label_paths:
            mw._log(f'[update] - {lbl}: {pth}')
    else:
        mw._log('[update] No Sources selected; building from Base only.')

    # Map song_id -> all source labels where it exists (for build_report.json dedupe stats)
    try:
        song_sources_by_id = {int(sid): tuple(getattr(mw._songs_by_id.get(int(sid)), 'sources', ()) or ()) for sid in selected_song_ids}
    except Exception:
        song_sources_by_id = {}

    # Capture an expected song list (ID + title/artist + chosen source) so builds can emit a diff.
    try:
        expected_song_rows = []
        for sid in sorted(selected_song_ids):
            s = mw._songs_by_id.get(int(sid))
            if s is None:
                continue
            expected_song_rows.append({
                'song_id': int(sid),
                'title': str(getattr(s, 'title', '') or ''),
                'artist': str(getattr(s, 'artist', '') or ''),
                'chosen_source': str(preferred_source_by_song_id.get(int(sid), 'Base') or 'Base'),
                'available_sources': [str(x) for x in (getattr(s, 'sources', ()) or ())],
            })
    except Exception:
        expected_song_rows = []

    t = QThread()
    w = BuildWorker(
        base_path=base_path,
        src_label_paths=src_label_paths,
        out_dir=str(out_dir),
        allow_overwrite_output=bool(allow_overwrite_output),
        keep_backup_of_existing_output=bool(keep_backup_of_existing_output),
        fast_update_existing_output=bool(fast_update_existing_output),
        selected_song_ids=set(int(x) for x in selected_song_ids),
        needed_donors=set(str(x) for x in needed_donors),
        preferred_source_by_song_id=dict((int(k), str(v)) for (k, v) in preferred_source_by_song_id.items()),
        song_sources_by_id=song_sources_by_id,
        expected_song_rows=list(expected_song_rows or []),
        preflight_validate=bool(mw.chk_preflight.isChecked()),
        block_on_errors=bool(mw.chk_block_build.isChecked()),
        cancel_token=mw._cancel_token,
    )
    w.moveToThread(t)

    t.started.connect(w.run, Qt.QueuedConnection)
    w.log.connect(mw._log)
    w.preflight_report.connect(mw._on_preflight_report)

    w.done.connect(mw._on_build_done)
    w.cancelled.connect(mw._on_build_cancelled)
    w.blocked.connect(mw._on_build_blocked)
    w.error.connect(mw._on_build_error)

    def _finalize_build() -> None:
        if mw._build_thread is not t:
            return
        try:
            t.quit()
        except Exception:
            pass
        if str(mw._active_op or '') != 'build':
            return
        try:
            mw._last_build_dup_summary = None
            mw._last_build_ids_before_autofix = set()
        except Exception:
            pass
        mw._build_thread = None
        mw._build_worker = None
        mw._cancel_token = None
        mw._set_op_running(False)
        mw._active_op = None

    w.finished.connect(_finalize_build)
    t.finished.connect(_finalize_build)
    try:
        t.finished.connect(t.deleteLater)
        w.finished.connect(w.deleteLater)
    except Exception:
        pass

    mw._build_thread = t
    mw._build_worker = w
    try:
        t.start()
    except Exception as e:
        mw._log(f"[update] ERROR: {e}")
        mw._cleanup_build()
        return

def cleanup_build(mw) -> None:
    try:
        if mw._build_thread is not None:
            mw._build_thread.quit()
            if QThread.currentThread() is not mw._build_thread:
                mw._build_thread.wait(1500)
    except Exception:
        pass
    try:
        mw._last_build_dup_summary = None
        mw._last_build_ids_before_autofix = set()
    except Exception:
        pass


    try:
        mw._build_mode = None
        mw._last_update_delta = None
    except Exception:
        pass
    mw._build_thread = None
    mw._build_worker = None
    mw._cancel_token = None
    mw._set_op_running(False)
    mw._active_op = None

def on_preflight_report(mw, report_text: str) -> None:
    rt = str(report_text or '')
    if not rt.strip():
        return
    mw._last_validate_report_text = rt
    mw.btn_copy_report.setEnabled(True)

    if bool(mw.chk_validate_write_report.isChecked()):
        try:
            rp = mw._write_validate_report_file(rt)
            mw._log(f'[preflight] Wrote validate_report.txt: {rp}')
        except Exception as e:
            mw._log(f'[preflight] Could not write validate_report.txt: {e}')


class BuildCompleteDialog(QDialog):
    """Build-complete summary dialog (clean, link-style artifacts)."""

    def __init__(
        self,
        mw,
        disc_dir: Path,
        output_parent: Path,
        artifacts: List[tuple[str, Path]],
        on_copy_disc,
    ) -> None:
        super().__init__(mw)
        self._mw = mw
        self._disc_dir = Path(disc_dir)
        self._output_parent = Path(output_parent)
        self._artifacts = list(artifacts or [])
        self._on_copy_disc = on_copy_disc

        try:
            self._build_mode = str(getattr(mw, "_build_mode", "") or "").strip().lower()
        except Exception:
            self._build_mode = "build"

        if self._build_mode == "update":
            win_title = "Update complete"
        else:
            win_title = "Build complete"

        self.setWindowTitle(str(win_title))
        try:
            self.setModal(True)
        except Exception:
            pass

        outer = QVBoxLayout(self)
        try:
            outer.setContentsMargins(16, 16, 16, 16)
            outer.setSpacing(10)
        except Exception:
            pass

        header = QHBoxLayout()
        try:
            header.setSpacing(12)
        except Exception:
            pass

        icon_lbl = QLabel(self)
        try:
            icon = self.style().standardIcon(QStyle.SP_MessageBoxInformation)
            icon_lbl.setPixmap(icon.pixmap(32, 32))
        except Exception:
            pass

        header.addWidget(icon_lbl, 0, Qt.AlignTop)

        title_box = QVBoxLayout()
        title = QLabel(str(win_title), self)
        try:
            title.setStyleSheet("font-size: 16px; font-weight: 600;")
        except Exception:
            pass
        title_box.addWidget(title)

        sub = QLabel(str(self._disc_dir.name), self)
        try:
            sub.setStyleSheet("color: #666;")
        except Exception:
            pass
        title_box.addWidget(sub)
        title_box.addStretch(1)

        header.addLayout(title_box, 1)
        outer.addLayout(header)

        path_row = QHBoxLayout()
        try:
            path_row.setSpacing(8)
        except Exception:
            pass

        path_lbl = QLabel("Disc folder:", self)
        try:
            path_lbl.setMinimumWidth(86)
        except Exception:
            pass

        self._path_edit = QLineEdit(self)
        self._path_edit.setReadOnly(True)
        self._path_edit.setText(str(self._disc_dir))
        try:
            self._path_edit.setCursorPosition(0)
            self._path_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        except Exception:
            pass

        btn_copy_path = QPushButton("Copy path", self)
        try:
            btn_copy_path.clicked.connect(self._copy_path)
        except Exception:
            pass

        path_row.addWidget(path_lbl)
        path_row.addWidget(self._path_edit, 1)
        path_row.addWidget(btn_copy_path)
        outer.addLayout(path_row)

        # Minimal next step (keep it short and actionable)
        next_steps = QLabel("Next steps: Copy the disc folder to your PS3 / loader location (uncompressed).", self)
        next_steps.setWordWrap(True)
        outer.addWidget(next_steps)

        # --- Summary counts (Option B: compact) ---
        self._notes_path = self._find_artifact_path("Transfer notes")
        self._diff_path = self._find_artifact_path("Song diff")
        self._expected_csv = self._find_artifact_path("Expected songs")
        self._built_csv = self._find_artifact_path("Built songs")
        self._preflight_path = self._find_artifact_path("Preflight summary")

        expected_n = self._count_csv_rows(self._expected_csv)
        built_n = self._count_csv_rows(self._built_csv)
        diff_n = self._count_csv_rows(self._diff_path)
        warn_n = self._count_warnings(self._preflight_path)

        summary_box = QFrame(self)
        grid = QGridLayout(summary_box)
        try:
            grid.setContentsMargins(0, 0, 0, 0)
            grid.setHorizontalSpacing(18)
            grid.setVerticalSpacing(2)
        except Exception:
            pass

        def _fmt(n: Optional[int]) -> str:
            return (str(int(n)) if isinstance(n, int) else "—")

        lab1 = QLabel("Songs expected:", self)
        val1 = QLabel(_fmt(expected_n), self)
        lab2 = QLabel("Songs built:", self)
        val2 = QLabel(_fmt(built_n), self)
        lab3 = QLabel("Diff:", self)
        val3 = QLabel(_fmt(diff_n), self)
        lab4 = QLabel("Warnings:", self)
        val4 = QLabel(_fmt(warn_n), self)

        try:
            for l in (lab1, lab2, lab3, lab4):
                l.setStyleSheet("color: #666;")
            for v in (val1, val2, val3, val4):
                v.setStyleSheet("font-weight: 600;")
        except Exception:
            pass

        grid.addWidget(lab1, 0, 0)
        grid.addWidget(val1, 0, 1)
        grid.addWidget(lab2, 1, 0)
        grid.addWidget(val2, 1, 1)
        grid.addWidget(lab3, 0, 2)
        grid.addWidget(val3, 0, 3)
        grid.addWidget(lab4, 1, 2)
        grid.addWidget(val4, 1, 3)

        # Update Existing: show a compact delta line (+added / -removed) if available.
        try:
            if str(getattr(self, "_build_mode", "") or "").strip().lower() == "update":
                ud = dict(getattr(self._mw, "_last_update_delta", {}) or {})
                add_n = int(ud.get("added", 0) or 0)
                rem_n = int(ud.get("removed", 0) or 0)
                lab_u = QLabel("Delta:", self)
                val_u = QLabel(f"+{add_n} added / -{rem_n} removed", self)
                try:
                    lab_u.setStyleSheet("color: #666;")
                    val_u.setStyleSheet("font-weight: 600;")
                except Exception:
                    pass
                grid.addWidget(lab_u, 2, 0)
                grid.addWidget(val_u, 2, 1, 1, 3)
        except Exception:
            pass

        outer.addWidget(summary_box)

        # --- Duplicate handling summary (Title+Artist) ---
        try:
            dsum = dict(getattr(mw, "_last_build_dup_summary", {}) or {})
        except Exception:
            dsum = {}
        try:
            dup_groups = int(dsum.get("dup_groups", 0) or 0)
        except Exception:
            dup_groups = 0

        if dup_groups > 0:
            try:
                sel_b = int(dsum.get("selected_before", 0) or 0)
                uniq_b = int(dsum.get("unique_before", 0) or 0)
                dropped_n = int(dsum.get("dropped", 0) or 0)
                dropped_ids = [int(x) for x in (dsum.get("dropped_ids", []) or [])]
            except Exception:
                sel_b, uniq_b, dropped_n, dropped_ids = 0, 0, 0, []

            dup_box = QFrame(self)
            dup_grid = QGridLayout(dup_box)
            try:
                dup_grid.setContentsMargins(0, 6, 0, 0)
                dup_grid.setHorizontalSpacing(18)
                dup_grid.setVerticalSpacing(2)
            except Exception:
                pass

            lab_a = QLabel("Selection:", self)
            val_a = QLabel(f"{sel_b} selected / {uniq_b} unique", self)
            lab_b = QLabel("Duplicates:", self)
            val_b = QLabel(f"{dup_groups} group(s), dropped {dropped_n} id(s)", self)

            try:
                lab_a.setStyleSheet("color: #666;")
                lab_b.setStyleSheet("color: #666;")
                val_a.setStyleSheet("font-weight: 600;")
                val_b.setStyleSheet("font-weight: 600;")
            except Exception:
                pass

            dup_grid.addWidget(lab_a, 0, 0)
            dup_grid.addWidget(val_a, 0, 1)
            dup_grid.addWidget(lab_b, 0, 2)
            dup_grid.addWidget(val_b, 0, 3)

            if dropped_ids:
                try:
                    shown = ", ".join(str(int(x)) for x in dropped_ids[:10])
                    if len(dropped_ids) > 10:
                        shown += ", ..."
                    lab_c = QLabel("Dropped IDs:", self)
                    val_c = QLabel(shown, self)
                    try:
                        lab_c.setStyleSheet("color: #666;")
                        val_c.setStyleSheet("font-weight: 600;")
                    except Exception:
                        pass
                    dup_grid.addWidget(lab_c, 1, 0)
                    dup_grid.addWidget(val_c, 1, 1, 1, 3)
                except Exception:
                    pass

            outer.addWidget(dup_box)

        # Small link-style control for extra artifacts
        more_row = QHBoxLayout()
        more = QToolButton(self)
        more.setText("More artifacts...")
        more.setAutoRaise(True)
        more.setPopupMode(QToolButton.InstantPopup)
        more.setMenu(self._build_open_menu(more))
        more_row.addWidget(more)
        more_row.addStretch(1)
        outer.addLayout(more_row)

        # --- Primary actions (Option B) ---
        bottom = QHBoxLayout()
        try:
            bottom.setSpacing(8)
        except Exception:
            pass

        btn_open_disc = QPushButton("Open disc folder", self)
        btn_open_disc.clicked.connect(lambda checked=False: self._open_path(self._disc_dir))
        bottom.addWidget(btn_open_disc)

        btn_open_diff = QPushButton("Open Song Diff", self)
        try:
            btn_open_diff.setEnabled(bool(self._diff_path and self._diff_path.exists()))
        except Exception:
            pass
        btn_open_diff.clicked.connect(self._open_song_diff)
        bottom.addWidget(btn_open_diff)

        btn_copy_notes = QPushButton("Copy transfer notes", self)
        try:
            btn_copy_notes.setEnabled(bool(self._notes_path and self._notes_path.exists()))
        except Exception:
            pass
        btn_copy_notes.clicked.connect(self._copy_transfer_notes)
        bottom.addWidget(btn_copy_notes)

        bottom.addStretch(1)

        box = QDialogButtonBox(QDialogButtonBox.Ok, self)
        box.accepted.connect(self.accept)
        bottom.addWidget(box)

        outer.addLayout(bottom)


    def _make_separator(self) -> QFrame:
        line = QFrame(self)
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        return line

    def _find_artifact_path(self, key: str) -> Optional[Path]:
        try:
            needle = str(key or "").strip().lower()
        except Exception:
            needle = ""
        if not needle:
            return None
        for label, path in (self._artifacts or []):
            try:
                if needle in str(label).lower():
                    return Path(path)
            except Exception:
                continue
        return None

    def _count_csv_rows(self, path: Optional[Path]) -> Optional[int]:
        try:
            if not path or not Path(path).exists():
                return None
            p = Path(path)
            # Only treat *.csv as a row-based report; anything else returns None.
            if p.suffix.lower() != ".csv":
                return None
            import csv as _csv  # local import (keeps module deps light)

            with p.open("r", encoding="utf-8", errors="ignore", newline="") as f:
                reader = _csv.DictReader(f)
                n = 0
                for _ in reader:
                    n += 1
            return int(n)
        except Exception:
            return None

    def _count_warnings(self, preflight_path: Optional[Path]) -> Optional[int]:
        try:
            if not preflight_path or not Path(preflight_path).exists():
                return 0
            txt = Path(preflight_path).read_text(encoding="utf-8", errors="ignore")
            import re as _re
            m = _re.search(r"\bWarnings\s*:\s*(\d+)\b", txt, flags=_re.IGNORECASE)
            if m:
                try:
                    return int(m.group(1))
                except Exception:
                    pass
            # Fallback: count warning-like lines.
            lines = [ln for ln in txt.splitlines() if ln.strip()]
            warnish = 0
            for ln in lines:
                ll = ln.lower()
                if "warning" in ll or "[warn" in ll:
                    warnish += 1
            return int(warnish)
        except Exception:
            return 0

    def _open_song_diff(self) -> None:
        try:
            if self._diff_path and Path(self._diff_path).exists():
                self._open_path(Path(self._diff_path))
                return
        except Exception:
            pass
        # Fallback: open output folder
        try:
            self._open_path(self._output_parent)
        except Exception:
            pass

    def _copy_transfer_notes(self) -> None:
        try:
            if not self._notes_path or not Path(self._notes_path).exists():
                return
            payload = Path(self._notes_path).read_text(encoding="utf-8", errors="ignore")
            QApplication.clipboard().setText(payload)
            try:
                show_status_message(self._mw, "Transfer notes copied to clipboard.", 5000)
            except Exception:
                pass
        except Exception:
            pass

    def _copy_path(self) -> None:
        try:
            QApplication.clipboard().setText(str(self._disc_dir))
            try:
                self._path_edit.selectAll()
            except Exception:
                pass
        except Exception:
            pass

    def _open_path(self, path: Path) -> None:
        try:
            if not path:
                return
            p = Path(path)
            if not p.exists():
                return
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(p)))
        except Exception as e:
            try:
                self._mw._log(f"[build] Open failed: {e}")
            except Exception:
                pass

    def _build_open_menu(self, parent_btn: QToolButton) -> QMenu:
        menu = QMenu(parent_btn)
        act_disc = menu.addAction("Disc folder")
        act_parent = menu.addAction("Output folder")
        menu.addSeparator()

        acts: List[tuple[object, Path]] = []
        for label, path in self._artifacts:
            p = Path(path)
            act = menu.addAction(str(label))
            act.setEnabled(p.exists())
            acts.append((act, p))

        act_disc.triggered.connect(lambda checked=False: self._open_path(self._disc_dir))
        act_parent.triggered.connect(lambda checked=False: self._open_path(self._output_parent))

        for act, p in acts:
            act.triggered.connect(lambda checked=False, pp=p: self._open_path(pp))

        return menu

    def _copy_disc_to(self) -> None:
        try:
            if callable(self._on_copy_disc):
                self._on_copy_disc(self._disc_dir)
        except Exception as e:
            try:
                self._mw._log(f"[build] Copy disc failed: {e}")
            except Exception:
                pass
        self.accept()

    def _build_details_text(self) -> str:
        lines: List[str] = []
        lines.append("Next steps:")
        lines.append("  • Copy the entire disc folder to your PS3 / loader location (uncompressed folder).")
        lines.append("  • Reports are written next to the disc folder in the output parent folder.")
        lines.append("")

        try:
            dsum = dict(getattr(self._mw, "_last_build_dup_summary", {}) or {})
            dup_groups = int(dsum.get("dup_groups", 0) or 0)
        except Exception:
            dup_groups = 0

        if dup_groups > 0:
            try:
                sel_b = int(dsum.get("selected_before", 0) or 0)
                uniq_b = int(dsum.get("unique_before", 0) or 0)
                dropped_n = int(dsum.get("dropped", 0) or 0)
                dropped_ids = [int(x) for x in (dsum.get("dropped_ids", []) or [])]
            except Exception:
                sel_b, uniq_b, dropped_n, dropped_ids = 0, 0, 0, []

            lines.append("Duplicates (Title+Artist):")
            lines.append(f"  • Selection: {sel_b} selected / {uniq_b} unique")
            lines.append(f"  • Resolved: {dup_groups} group(s), dropped {dropped_n} id(s)")
            if dropped_ids:
                shown = ", ".join(str(int(x)) for x in dropped_ids[:14])
                if len(dropped_ids) > 14:
                    shown += ", ..."
                lines.append(f"  • Dropped IDs: {shown}")
            lines.append("")

        lines.append(f"Output parent:\n  {self._output_parent}")
        lines.append("")
        lines.append("Artifacts:")
        for label, path in self._artifacts:
            lines.append(f"  {label}:\n    {path}")
        return "\n".join(lines)


def on_build_done(mw, out_dir: str) -> None:
    try:
        mode = str(getattr(mw, "_build_mode", "build") or "build").strip().lower()
    except Exception:
        mode = "build"

    tag = "update" if mode == "update" else "build"
    label = "Update" if tag == "update" else "Build"

    mw._log(f'[{tag}] Done: {out_dir}')
    try:
        show_status_message(mw, f"{label} complete: {Path(str(out_dir or '')).name}", 10000)
    except Exception:
        pass
    disc_dir = Path(str(out_dir or '')).expanduser().resolve()
    parent = disc_dir.parent
    notes = parent / f"{disc_dir.name or 'disc'}_transfer_notes.txt"
    preflight = parent / f"{disc_dir.name or 'disc'}_preflight_summary.txt"
    report = parent / f"{disc_dir.name or 'disc'}_build_report.json"
    report_txt = parent / f"{disc_dir.name or 'disc'}_build_report.txt"
    report_best = report_txt if report_txt.exists() else report

    # Disc Branding (XMB): optional ICON0.PNG / PIC1.PNG overrides into the built output.
    try:
        mw._apply_disc_branding_to_output(disc_dir)
    except Exception as e:
        mw._log(f"[branding] Apply failed: {e}")


    expected_csv = parent / f"{disc_dir.name or 'disc'}_expected_songs.csv"
    built_csv = parent / f"{disc_dir.name or 'disc'}_built_songs.csv"
    diff_csv = parent / f"{disc_dir.name or 'disc'}_song_diff.csv"

    artifacts: List[tuple[str, Path]] = [
        ("Preflight summary", preflight),
        ("Transfer notes", notes),
        ("Build report (text)", report_txt),
        ("Build report (json)", report),
        ("Expected songs", expected_csv),
        ("Built songs", built_csv),
        ("Song diff", diff_csv),
    ]

    try:
        dlg = BuildCompleteDialog(
            mw,
            disc_dir=disc_dir,
            output_parent=parent,
            artifacts=artifacts,
            on_copy_disc=mw._start_copy_disc,
        )
        dlg.exec()
    except Exception:
        mw._cleanup_build()
        return

    mw._cleanup_build()

def on_build_cancelled(mw) -> None:
    mw._log('[build] Cancelled.')
    try:
        show_status_message(mw, 'Build cancelled.', 5000)
    except Exception:
        pass
    mw._cleanup_build()

def on_build_blocked(mw, msg: str) -> None:
    mw._log(f'[build] BLOCKED: {msg}')
    try:
        show_status_message(mw, 'Build blocked. Resolve validation errors.', 8000)
    except Exception:
        pass
    mw._show_critical_with_logs('Build blocked', str(msg or 'Build blocked'), tip="Tip: Resolve validation errors first (or disable 'Block Build when Validate has Errors').")
    mw._cleanup_build()

def on_build_error(mw, msg: str) -> None:
    mw._log(f'[build] ERROR: {msg}')
    try:
        show_status_message(mw, 'Build failed. See logs for details.', 8000)
    except Exception:
        pass
    mw._show_critical_with_logs('Build failed', str(msg or 'Unknown error'), tip='Tip: Check the logs. You can export a support bundle from Help if you need to share this.')
    mw._cleanup_build()
