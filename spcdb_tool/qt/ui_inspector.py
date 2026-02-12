"""Inspector + Preview helpers extracted from Qt MainWindow.

R26 refactor: behavior-preserving extraction of Inspector context rendering and
external-player Preview helpers.

All functions here are written to be called with the MainWindow instance as `self`.
"""

from __future__ import annotations

import os
import shutil
import xml.etree.ElementTree as ET

from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import Qt, QUrl, QProcess
from PySide6.QtGui import QDesktopServices

from ..controller import get_index_cache_status


# -------------------------
# Inspector
# -------------------------

def update_inspector_context(self) -> None:
    """Update the Inspector panel based on current selection.

    - If a Source row is selected: show source details.
    - Otherwise: show songs/selection summary.
    """
    try:
        selected_rows = sorted({i.row() for i in self.sources_table.selectedIndexes()})
    except Exception:
        selected_rows = []

    base_path = ""
    try:
        base_path = self.base_edit.text().strip()
    except Exception:
        base_path = ""

    try:
        any_sources = bool(base_path) or int(self.sources_table.rowCount() or 0) > 0
    except Exception:
        any_sources = bool(base_path)

    # Conflicts indicator is global; keep it updated regardless of which inspector page is showing.
    try:
        conflicts = getattr(self, '_song_conflicts', {}) or {}
        if hasattr(self, 'inspector_conflicts_lbl'):
            self.inspector_conflicts_lbl.setText(f"Conflicts: {int(len(conflicts))}")
        if hasattr(self, 'btn_resolve_conflicts'):
            self.btn_resolve_conflicts.setEnabled(bool(conflicts))
    except Exception:
        pass

    # Enable/disable source actions when nothing is configured.
    try:
        self.btn_validate.setEnabled(bool(any_sources))
    except Exception:
        pass
    try:
        self.btn_extract.setEnabled(bool(any_sources))
    except Exception:
        pass

    if selected_rows:
        r = int(selected_rows[0])
        try:
            label = (self.sources_table.item(r, 0).text() if self.sources_table.item(r, 0) else "").strip()
        except Exception:
            label = ""
        try:
            path = (self.sources_table.item(r, 2).text() if self.sources_table.item(r, 2) else "").strip()
        except Exception:
            path = ""
        try:
            state = (self.sources_table.item(r, 1).text() if self.sources_table.item(r, 1) else "").strip()
        except Exception:
            state = ""

        if not label and path:
            try:
                label = Path(path).name
            except Exception:
                label = "Source"

        try:
            self.inspector_title_lbl.setText("Source")
        except Exception:
            pass
        try:
            self.inspector_title_lbl.setVisible(True)
        except Exception:
            pass
        try:
            self.inspector_source_title_lbl.setText(f"Source: {label or '-'}")
        except Exception:
            pass
        try:
            self.inspector_source_path_lbl.setText(path or "-")
        except Exception:
            pass
        try:
            self.inspector_source_state_lbl.setText(state or "-")
        except Exception:
            pass

        cache_txt = "-"
        if path:
            try:
                st = get_index_cache_status(path)
                if not st.get("exists"):
                    cache_txt = "missing"
                else:
                    stale = bool(st.get("stale"))
                    sc = int(st.get("song_count") or 0)
                    cache_txt = f"{'stale (will rescan)' if stale else 'ok (matches)'} | songs {sc}"
            except Exception:
                cache_txt = "-"
        try:
            self.inspector_source_cache_lbl.setText(cache_txt)
        except Exception:
            pass

        hint_txt = ""
        try:
            sstate = str(state or "")
            if not sstate:
                hint_txt = ""
            elif "Extracted" in sstate:
                if "Verified" in sstate:
                    hint_txt = "Ready — you can Build Selected."
                else:
                    hint_txt = "Extracted export found. Run Validate Selected to verify files before building."
            elif "Partial" in sstate:
                hint_txt = (
                    "Partial extraction detected (Pack*.pkd_out present).\n"
                    "Use Extract Selected to finish extraction. If it keeps failing, use Tools → Cleanup PKD artifacts… then try again."
                )
            elif "Packed" in sstate:
                hint_txt = "Packed disc detected (.pkd files). Use Extract Selected to extract (requires the external extractor)."
            elif "Needs extract" in sstate:
                hint_txt = "Not extracted yet. Use Extract Selected."

            if "Errors" in sstate:
                hint_txt = (hint_txt + "\n\n" if hint_txt else "") + "Validation errors detected — run Validate Selected and Copy report to see what’s missing."
            elif "Warnings" in sstate:
                hint_txt = (hint_txt + "\n\n" if hint_txt else "") + "Validation warnings detected — check the report before building."
        except Exception:
            hint_txt = ""

        try:
            if hasattr(self, "inspector_source_hint_lbl"):
                self.inspector_source_hint_lbl.setText(hint_txt)
        except Exception:
            pass

        try:
            self.inspector_stack.setCurrentWidget(self._inspector_page_source)
        except Exception:
            pass
        return

    # Songs context
    try:
        self.inspector_title_lbl.setText("")
    except Exception:
        pass
    try:
        self.inspector_title_lbl.setVisible(False)
    except Exception:
        pass

    tot = 0
    vis = 0
    sel = 0
    try:
        tot = int(len(self._songs_all or []))
    except Exception:
        tot = 0
    try:
        vis = int(len(self._songs_visible_ids or []))
    except Exception:
        vis = 0
    try:
        sel = int(len(self._selected_song_ids or set()))
    except Exception:
        sel = 0
    try:
        # Title+Artist duplicate stats (in-game may suppress these)
        picked = int(sel)
        included = picked
        title_dupe_extra = 0
        try:
            import re as _re

            def _norm(s: str) -> str:
                return _re.sub(r"\s+", " ", (s or "").strip()).upper()

            counts: Dict[str, int] = {}
            for sid in (self._selected_song_ids or set()):
                try:
                    sid_i = int(sid)
                except Exception:
                    continue
                s = getattr(self, "_songs_by_id", {}).get(sid_i)
                title = str(getattr(s, "title", "") or "") if s is not None else ""
                artist = str(getattr(s, "artist", "") or "") if s is not None else ""
                k = f"{_norm(title)}||{_norm(artist)}"
                if not _norm(title) and not _norm(artist):
                    k = f"ID:{sid_i}"
                counts[k] = int(counts.get(k, 0)) + 1

            for k, n in (counts or {}).items():
                if k.startswith("ID:"):
                    continue
                if int(n) >= 2:
                    title_dupe_extra += max(0, int(n) - 1)

            included = max(0, picked - int(title_dupe_extra))
        except Exception:
            included = picked
            title_dupe_extra = 0

        conflicts_n = 0
        try:
            conflicts_n = int(len(getattr(self, "_song_conflicts", {}) or {}))
        except Exception:
            conflicts_n = 0

        id_dupes = int(getattr(self, "_dedupe_songs_with_dups", 0) or 0)

        songs_part = f"Songs: {tot}" + (f" ({vis} shown)" if vis != tot else "")
        included_part = f"Included: {included}"
        if title_dupe_extra > 0:
            included_part += f" ({picked} picked; {title_dupe_extra} duplicate title" + ("s" if title_dupe_extra != 1 else "") + ")"
        conflicts_part = f"Conflicts: {conflicts_n}"

        extra_parts: List[str] = []
        if id_dupes > 0:
            extra_parts.append(f"ID dupes: {id_dupes}")

        line = " | ".join([songs_part, included_part, conflicts_part] + extra_parts)
        self.inspector_songs_summary_lbl.setText(line)
        try:
            self.inspector_conflicts_lbl.setText(f"Conflicts: {conflicts_n}")
            self.btn_resolve_conflicts.setEnabled(bool(getattr(self, '_song_conflicts', None)))
        except Exception:
            pass
    except Exception:
        pass


    # Filter summary (best-effort)
    parts: List[str] = []
    try:
        s = self.song_search_edit.text().strip()
        if s:
            parts.append(f"Search: {s}")
    except Exception:
        pass
    try:
        src = self.song_source_combo.currentText().strip()
        if src and src != "All":
            parts.append(f"Source: {src}")
    except Exception:
        pass
    try:
        if bool(self.song_selected_only_chk.isChecked()):
            parts.append("Included only")
    except Exception:
        pass

    # Preset flags
    try:
        if bool(getattr(self, "_filter_conflicts_only", False)):
            parts.append("Conflicts only")
    except Exception:
        pass
    try:
        if bool(getattr(self, "_filter_duplicates_only", False)):
            parts.append("Duplicates only")
    except Exception:
        pass
    try:
        if bool(getattr(self, "_filter_overrides_only", False)):
            parts.append("Overrides only")
    except Exception:
        pass
    try:
        if bool(getattr(self, "_filter_disabled_only", False)):
            parts.append("Disabled only")
    except Exception:
        pass

    filt = " | ".join(parts) if parts else "Filters: none"
    try:
        self.inspector_songs_filter_lbl.setText(filt)
    except Exception:
        pass

    try:
        self.inspector_stack.setCurrentWidget(self._inspector_page_songs)
    except Exception:
        pass


# -------------------------
# Preview (external player)
# -------------------------


def pv_strip_ns(tag: str) -> str:
    try:
        if "}" in tag:
            return tag.split("}", 1)[1]
    except Exception:
        pass
    return str(tag or "")


def pv_int(v: object) -> Optional[int]:
    try:
        if v is None:
            return None
        if isinstance(v, int):
            return int(v)
        s = str(v).strip()
        if not s:
            return None
        return int(round(float(s.replace(",", ""))))
    except Exception:
        return None


def pv_resolution_beats(resolution: str) -> float:
    r = str(resolution or "").strip().lower()
    mapping = {
        "semibreve": 4.0,
        "minim": 2.0,
        "crotchet": 1.0,
        "quaver": 0.5,
        "semiquaver": 0.25,
        "demisemiquaver": 0.125,
        "hemidemisemiquaver": 0.0625,
    }
    return float(mapping.get(r, 0.125))


def pv_unit_seconds(self, melody_xml: Path) -> Optional[float]:
    try:
        tempo = None
        resolution = ""
        for _ev, el in ET.iterparse(str(melody_xml), events=("start",)):
            if pv_strip_ns(str(el.tag)).upper() == "MELODY":
                tempo = pv_int(el.attrib.get("Tempo") or el.attrib.get("TEMPO"))
                resolution = str(el.attrib.get("Resolution") or el.attrib.get("RESOLUTION") or "")
                break
        if not tempo or int(tempo) <= 0:
            return None
        beats = pv_resolution_beats(resolution)
        return (60.0 / float(tempo)) * beats
    except Exception:
        return None


def pv_extract_times(self, melody_xml: Path) -> Tuple[Dict[str, float], Optional[float]]:
    unit_s = pv_unit_seconds(self, melody_xml)
    if unit_s is None or unit_s <= 0:
        return {}, None

    cur_units = 0
    markers: Dict[str, float] = {}
    first_lyric: Optional[float] = None

    try:
        for _ev, el in ET.iterparse(str(melody_xml), events=("end",)):
            if pv_strip_ns(str(el.tag)).upper() != "SENTENCE":
                continue

            try:
                children = list(el)
            except Exception:
                children = []

            for ch in children:
                tag_u = pv_strip_ns(str(ch.tag)).upper()
                delay_u = pv_int(ch.attrib.get("Delay") or ch.attrib.get("DELAY"))

                if tag_u != "NOTE":
                    if delay_u is not None:
                        cur_units += max(0, int(delay_u))
                    if tag_u.startswith("MARKER"):
                        mtype = str(ch.attrib.get("Type") or ch.attrib.get("TYPE") or "").strip()
                        if mtype and mtype not in markers:
                            markers[mtype] = float(cur_units) * float(unit_s)
                    continue

                # NOTE
                if delay_u is not None:
                    cur_units += max(0, int(delay_u))

                note_start_sec = float(cur_units) * float(unit_s)

                # Nested markers (commonly MARKER_N)
                try:
                    for sub in list(ch):
                        sub_tag = pv_strip_ns(str(sub.tag)).upper()
                        if not sub_tag.startswith("MARKER"):
                            continue
                        mtype = str(sub.attrib.get("Type") or sub.attrib.get("TYPE") or "").strip()
                        if not mtype or mtype in markers:
                            continue
                        d = pv_int(sub.attrib.get("Delay") or sub.attrib.get("DELAY"))
                        if d is None:
                            markers[mtype] = note_start_sec
                        else:
                            # Nested marker Delay is usually milliseconds (tiny numbers like 28/40/80).
                            if 0 <= int(d) <= 100000:
                                markers[mtype] = note_start_sec + (float(d) / 1000.0)
                            else:
                                markers[mtype] = note_start_sec + (float(d) * float(unit_s))
                except Exception:
                    pass

                if first_lyric is None:
                    midi = pv_int(ch.attrib.get("MidiNote") or ch.attrib.get("MIDINOTE"))
                    lyr = str(ch.attrib.get("Lyric") or ch.attrib.get("LYRIC") or "").strip()
                    if midi is not None and int(midi) > 0 and lyr:
                        first_lyric = note_start_sec

                dur_u = pv_int(ch.attrib.get("Duration") or ch.attrib.get("DURATION"))
                if dur_u is not None:
                    cur_units += max(0, int(dur_u))

            el.clear()
    except Exception:
        pass

    return markers, first_lyric


def pv_fmt(sec: float) -> str:
    try:
        s = max(0.0, float(sec))
        mm = int(s // 60.0)
        ss = s - (mm * 60.0)
        return f"{mm:02d}:{ss:04.1f}"
    except Exception:
        return "00:00.0"


def pv_find_song_dir(self, export_root: Path, song_id: int) -> Optional[Path]:
    for p in [export_root / str(song_id), export_root / f"{song_id:04d}", export_root / f"{song_id:05d}"]:
        try:
            if p.exists() and p.is_dir():
                return p
        except Exception:
            pass
    return None


def pv_scan_media(self, song_dir: Path) -> Dict[str, str]:
    audio_exts = {".mp3", ".wav", ".ogg", ".at3", ".aac", ".m4a", ".ac3", ".flac", ".wma", ".aif", ".aiff", ".vag"}
    video_exts = {".mp4", ".m2v", ".mpg", ".mpeg", ".avi", ".mov", ".mkv", ".wmv", ".h264", ".264", ".vob"}
    best_audio = ("", 0, "")
    best_video = ("", 0, "")
    try:
        for root, _dirs, files in os.walk(str(song_dir)):
            for fn in files:
                p = Path(root) / fn
                try:
                    size = int(p.stat().st_size)
                except Exception:
                    size = 0
                ext = p.suffix.lower()
                if ext in audio_exts and size > best_audio[1]:
                    best_audio = (fn, size, str(p))
                if ext in video_exts and size > best_video[1]:
                    best_video = (fn, size, str(p))
    except Exception:
        pass
    return {"audio_path": str(best_audio[2]), "video_path": str(best_video[2])}


def pv_selected_song_id(self) -> Optional[int]:
    try:
        tbl = self.songs_table
    except Exception:
        return None

    try:
        rows = [int(ix.row()) for ix in tbl.selectionModel().selectedRows()]
    except Exception:
        rows = []
    if not rows:
        try:
            rows = [int(tbl.currentRow())]
        except Exception:
            rows = []

    for r in rows:
        try:
            if int(r) in (self._songs_header_rows or {}):
                continue
        except Exception:
            pass
        try:
            it = tbl.item(int(r), 0)
            if it is None:
                continue
            sid = int(it.data(Qt.UserRole) or 0)
            if sid > 0:
                return sid
        except Exception:
            pass

    return None


def pv_selected_label(self, song_id: int) -> str:
    try:
        ov = self._song_source_overrides or {}
        lab = str(ov.get(int(song_id)) or "").strip()
        if lab:
            return lab
    except Exception:
        pass

    try:
        for s in (self._songs_all or []):
            if int(getattr(s, "song_id", 0) or 0) == int(song_id):
                lab = str(getattr(s, "preferred_source", "") or "").strip()
                if lab:
                    return lab
                break
    except Exception:
        pass

    return "Base"


def pv_choose_window(
    self,
    melody_xml: Optional[Path],
    start_mode: str,
    clip_mode: str,
) -> Tuple[float, Optional[float], str, str]:
    """Pick a preview start/end window from melody_1.xml markers.

    Returns:
        (start_seconds, end_seconds_or_None, start_reason, end_reason)
    """
    if not melody_xml or not melody_xml.exists():
        return 0.0, None, "Start of song (no melody_1.xml)", ""

    start_mode = str(start_mode or "").strip()
    clip_mode = str(clip_mode or "").strip()

    cache = getattr(self, "_preview_time_cache", {})
    key = (str(melody_xml), start_mode, clip_mode)
    try:
        if key in cache:
            st, en, sr, er = cache[key]
            return float(st), (None if en is None else float(en)), str(sr), str(er)
    except Exception:
        pass

    markers, first_lyric = pv_extract_times(self, melody_xml)

    # --- start ---
    chosen = 0.0
    why = "Start of song"

    if start_mode == "MedleyNormalBegin":
        if "MedleyNormalBegin" in markers:
            chosen, why = float(markers["MedleyNormalBegin"]), "MedleyNormalBegin"
        elif "MedleyMicroBegin" in markers:
            chosen, why = float(markers["MedleyMicroBegin"]), "MedleyMicroBegin (fallback)"
        elif first_lyric is not None:
            chosen, why = float(first_lyric), "First lyric note (fallback)"
    elif start_mode == "MedleyMicroBegin":
        if "MedleyMicroBegin" in markers:
            chosen, why = float(markers["MedleyMicroBegin"]), "MedleyMicroBegin"
        elif "MedleyNormalBegin" in markers:
            chosen, why = float(markers["MedleyNormalBegin"]), "MedleyNormalBegin (fallback)"
        elif first_lyric is not None:
            chosen, why = float(first_lyric), "First lyric note (fallback)"
    elif start_mode == "First lyric note":
        if first_lyric is not None:
            chosen, why = float(first_lyric), "First lyric note"

    preroll = 0.75
    if chosen > 0.25:
        chosen = max(0.0, chosen - preroll)
        why = f"{why} - preroll {preroll:.2f}s"

    # --- end ---
    end_s: Optional[float] = None
    end_why = ""

    def _want_medley_segment() -> bool:
        return clip_mode in {"Auto", "Medley segment (Begin -> End)"}

    def _want_20s() -> bool:
        return clip_mode in {"Auto", "20 seconds"}

    if clip_mode == "Full track":
        end_s, end_why = None, ""
    elif _want_medley_segment() and start_mode in {"MedleyNormalBegin", "MedleyMicroBegin"}:
        end_key = "MedleyNormalEnd" if start_mode == "MedleyNormalBegin" else "MedleyMicroEnd"
        if end_key in markers:
            cand = float(markers[end_key])
            if cand > float(chosen) + 0.25:
                end_s, end_why = cand, end_key
            elif _want_20s():
                end_s, end_why = float(chosen) + 20.0, "20 seconds (end marker before start)"
        elif _want_20s():
            end_s, end_why = float(chosen) + 20.0, "20 seconds (no end marker)"
    elif clip_mode == "Medley segment (Begin -> End)":
        end_s, end_why = float(chosen) + 20.0, "20 seconds (not a medley start)"
    elif clip_mode == "20 seconds":
        end_s, end_why = float(chosen) + 20.0, "20 seconds"
    else:
        if clip_mode == "Auto":
            end_s, end_why = float(chosen) + 20.0, "20 seconds (auto)"
        else:
            end_s, end_why = None, ""

    try:
        cache[key] = (float(chosen), (None if end_s is None else float(end_s)), str(why), str(end_why))
        self._preview_time_cache = cache
    except Exception:
        pass

    return float(chosen), end_s, str(why), str(end_why)


def pv_choose_start(self, melody_xml: Optional[Path], mode: str) -> Tuple[float, str]:
    st, _en, sr, _er = pv_choose_window(self, melody_xml, mode, "Full track")
    return float(st), str(sr)


def update_preview_context(self) -> None:
    sid = pv_selected_song_id(self)
    try:
        self.btn_preview_stop.setEnabled(self._preview_proc.state() == QProcess.Running)
    except Exception:
        pass

    if not sid:
        try:
            self.preview_song_lbl.setText("Song: (select a song)")
            self.preview_status_lbl.setText("")
            self.btn_preview.setEnabled(False)
        except Exception:
            pass
        return

    label = pv_selected_label(self, int(sid))

    try:
        disp = str(label)
        try:
            disp = str(self._display_label_for_source(str(label)) or label)
        except Exception:
            pass

        title = ""
        artist = ""
        try:
            for s in (self._songs_all or []):
                if int(getattr(s, "song_id", 0) or 0) == int(sid):
                    title = str(getattr(s, "title", "") or "").strip()
                    artist = str(getattr(s, "artist", "") or "").strip()
                    break
        except Exception:
            pass

        if not title and not artist:
            try:
                tbl = self.songs_table
                rows = [int(ix.row()) for ix in tbl.selectionModel().selectedRows()]
                if not rows:
                    rows = [int(tbl.currentRow())]
                for r in rows:
                    try:
                        if int(r) in (self._songs_header_rows or {}):
                            continue
                    except Exception:
                        pass
                    try:
                        t_it = tbl.item(int(r), 1)
                        a_it = tbl.item(int(r), 2)
                        title = str(t_it.text() if t_it is not None else "").strip()
                        artist = str(a_it.text() if a_it is not None else "").strip()
                    except Exception:
                        pass
                    if title or artist:
                        break
            except Exception:
                pass

        if title and artist:
            song_name = f"{title} — {artist}"
        elif title:
            song_name = title
        elif artist:
            song_name = artist
        else:
            song_name = f"Song {sid}"

        self.preview_song_lbl.setText(f"Song: {song_name} [{disp}]")
    except Exception:
        pass

    export_root_s = ""
    try:
        export_root_s = str((self._export_roots_by_label or {}).get(str(label), "") or "").strip()
    except Exception:
        pass

    if not export_root_s:
        try:
            self.preview_status_lbl.setText("Not available: this source has no Export folder (extract first).")
            self.btn_preview.setEnabled(False)
        except Exception:
            pass
        return

    export_root = Path(export_root_s)
    song_dir = pv_find_song_dir(self, export_root, int(sid))
    if not song_dir:
        try:
            self.preview_status_lbl.setText("Not available: song folder missing in Export (extract first).")
            self.btn_preview.setEnabled(False)
        except Exception:
            pass
        return

    media = pv_scan_media(self, song_dir)
    media_path = str(media.get("video_path") or "")
    video_ok = bool(media_path)

    try:
        self.btn_preview.setEnabled(video_ok)
    except Exception:
        pass

    if not video_ok:
        try:
            self.preview_status_lbl.setText("Not available: MP4/video file not found for this song.")
        except Exception:
            pass
        return

    melody: Optional[Path] = None
    for nm in ["melody_1.xml", "MELODY_1.XML"]:
        p = song_dir / nm
        if p.exists():
            melody = p
            break

    try:
        start_mode = str(self.preview_start_combo.currentText() or "")
    except Exception:
        start_mode = "MedleyNormalBegin"

    try:
        clip_mode = str(self.preview_clip_combo.currentText() or "")
    except Exception:
        clip_mode = "Auto"

    start_s, end_s, start_why, end_why = pv_choose_window(self, melody, start_mode, clip_mode)

    _prog, _args, player_name = pv_player_cmd(self, media_path, float(start_s), end_s)

    try:
        lines = [f"Start: {start_why} @ {pv_fmt(start_s)}", f"Clip: {clip_mode}", f"Player: {player_name}"]
        if end_s is not None:
            lines.insert(1, f"End: {end_why or 'End'} @ {pv_fmt(end_s)}")
        else:
            lines.insert(1, "End: (full track)")
        self.preview_status_lbl.setText("\n".join(lines))
    except Exception:
        pass


def pv_player_cmd(self, media_path: str, start_s: float, end_s: Optional[float]) -> Tuple[str, List[str], str]:
    mpv = ""
    ffplay = ""
    try:
        mpv = str(shutil.which("mpv") or "")
    except Exception:
        pass
    try:
        ffplay = str(shutil.which("ffplay") or "")
    except Exception:
        pass

    st = max(0.0, float(start_s))
    dur: Optional[float] = None
    if end_s is not None:
        try:
            dur = max(0.0, float(end_s) - st)
            if dur <= 0.1:
                dur = None
        except Exception:
            dur = None

    if mpv:
        args: List[str] = [f"--start={st:.3f}"]
        if end_s is not None and dur is not None:
            args.append(f"--end={float(end_s):.3f}")
        args.append(str(media_path))
        return mpv, args, "mpv"

    if ffplay:
        args = ["-ss", f"{st:.3f}", "-autoexit", "-hide_banner", "-loglevel", "error"]
        if dur is not None:
            args.extend(["-t", f"{dur:.3f}"])
        args.append(str(media_path))
        return ffplay, args, "ffplay"

    return "", [], "default player"


def preview_start(self) -> None:
    sid = pv_selected_song_id(self)
    if not sid:
        return

    label = pv_selected_label(self, int(sid))

    export_root_s = ""
    try:
        export_root_s = str((self._export_roots_by_label or {}).get(str(label), "") or "").strip()
    except Exception:
        pass

    if not export_root_s:
        try:
            self.preview_status_lbl.setText("Preview unavailable: no Export folder for this source.")
        except Exception:
            pass
        return

    song_dir = pv_find_song_dir(self, Path(export_root_s), int(sid))
    if not song_dir:
        try:
            self.preview_status_lbl.setText("Preview unavailable: song folder missing in Export.")
        except Exception:
            pass
        return

    media = pv_scan_media(self, song_dir)
    media_path = str(media.get("video_path") or "")
    if not media_path:
        try:
            self.preview_status_lbl.setText("Preview unavailable: MP4/video file not found for this song.")
        except Exception:
            pass
        return

    melody: Optional[Path] = None
    for nm in ["melody_1.xml", "MELODY_1.XML"]:
        p = song_dir / nm
        if p.exists():
            melody = p
            break

    try:
        start_mode = str(self.preview_start_combo.currentText() or "")
    except Exception:
        start_mode = "MedleyNormalBegin"

    try:
        clip_mode = str(self.preview_clip_combo.currentText() or "")
    except Exception:
        clip_mode = "Auto"

    start_s, end_s, start_why, end_why = pv_choose_window(self, melody, start_mode, clip_mode)

    try:
        preview_stop(self)
    except Exception:
        pass

    prog, args, player_name = pv_player_cmd(self, media_path, float(start_s), end_s)
    if not prog:
        try:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(media_path)))
            msg = f"Opened in {player_name}. Seek to {pv_fmt(start_s)} ({start_why})."
            if end_s is not None:
                msg += f" Stop around {pv_fmt(end_s)} ({end_why or 'End'})."
            self.preview_status_lbl.setText(msg)
        except Exception:
            pass
        return

    try:
        self._preview_proc.setProgram(str(prog))
        self._preview_proc.setArguments([str(a) for a in (args or [])])
        self._preview_proc.start()
        msg = f"Launching {player_name} @ {pv_fmt(start_s)} ({start_why})"
        if end_s is not None:
            msg += f" -> {pv_fmt(end_s)} ({end_why or 'End'})"
        self.preview_status_lbl.setText(msg)
        self.btn_preview_stop.setEnabled(True)
    except Exception as e:
        try:
            self.preview_status_lbl.setText(f"Preview failed: {e}")
        except Exception:
            pass


def preview_stop(self) -> None:
    try:
        if self._preview_proc.state() == QProcess.NotRunning:
            return
    except Exception:
        return

    try:
        self._preview_proc.terminate()
    except Exception:
        pass

    try:
        if not self._preview_proc.waitForFinished(800):
            self._preview_proc.kill()
    except Exception:
        pass

    try:
        self.btn_preview_stop.setEnabled(False)
    except Exception:
        pass


def preview_on_finished(self) -> None:
    try:
        self.btn_preview_stop.setEnabled(False)
    except Exception:
        pass


def preview_on_error(self) -> None:
    try:
        self.btn_preview_stop.setEnabled(False)
    except Exception:
        pass
