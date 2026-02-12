from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Iterable, Optional, Tuple, List


_SS_NS = "http://www.singstargame.com"


def _strip_ns(tag: str) -> str:
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _get_attr_ci(attrib: dict, name: str) -> object:
    """Case-insensitive attribute lookup.

    SingStar XML usually uses MidiNote/Duration/Lyric/Delay, but some dumps/tools
    may vary case. We treat attribute keys as ASCII-ish and match by lowercasing.
    """
    if not attrib:
        return None
    # Fast paths
    if name in attrib:
        return attrib.get(name)
    up = name.upper()
    lo = name.lower()
    if up in attrib:
        return attrib.get(up)
    if lo in attrib:
        return attrib.get(lo)

    # Fallback: scan keys once
    try:
        lowmap = {str(k).lower(): v for k, v in attrib.items()}
    except Exception:
        return None
    return lowmap.get(lo)


def _to_int_maybe(v: object) -> Optional[int]:
    if v is None:
        return None
    if isinstance(v, int):
        return int(v)
    try:
        s = str(v).strip()
        if not s:
            return None
        s = s.replace(",", "")
        # allow floats like "170.00" but treat as int-ish
        return int(round(float(s)))
    except Exception:
        return None


def _norm_lyric(s: object) -> str:
    # lower + collapse whitespace + normalize common punctuation
    txt = str(s or "").strip().lower()
    if not txt:
        return ""
    # translate a few unicode punctuation to ascii without embedding non-ascii literals
    # (use codepoints as ints to avoid accidental non-ascii in source)
    txt = txt.translate(
        {
            0x2010: ord("-"),  # hyphen
            0x2011: ord("-"),
            0x2012: ord("-"),
            0x2013: ord("-"),
            0x2014: ord("-"),
            0x2015: ord("-"),
            0x2212: ord("-"),  # minus
            0x2018: ord("'"),
            0x2019: ord("'"),
            0x201C: ord('"'),
            0x201D: ord('"'),
        }
    )
    # collapse whitespace
    txt = " ".join(txt.split())
    # normalize spaced hyphens (e.g. "Heart -" -> "heart-")
    txt = re.sub(r"\s*-\s*", "-", txt)
    return txt


def iter_melody_events(melody_xml: Path) -> Iterable[Tuple[int, int, int, str]]:
    """Yield (start_tick, duration_tick, midi_note, lyric_norm) from a SingStar melody_*.xml.

    We treat the melody as a linear stream of events. Inside each SENTENCE, we:
    - advance time by any child element's Delay attribute (LABEL/MARKER/etc)
    - for NOTE elements, emit an event and advance by Duration
    This ignores non-timing metadata such as ADRS, schema versions, whitespace, etc.
    """
    melody_xml = Path(melody_xml)
    if not melody_xml.exists() or not melody_xml.is_file():
        return

    cur = 0
    try:
        # Streaming parse: process each SENTENCE at end, then clear it to keep memory low.
        for ev, el in ET.iterparse(str(melody_xml), events=("end",)):
            if _strip_ns(str(el.tag)).upper() != "SENTENCE":
                continue

            # iterate direct children in order
            try:
                children = list(el)
            except Exception:
                children = []

            for ch in children:
                tag = _strip_ns(str(ch.tag)).upper()
                try:
                    delay = _to_int_maybe(_get_attr_ci(ch.attrib, "Delay"))
                except Exception:
                    delay = None

                # Delay on timeline elements advances the cursor.
                if delay is not None and tag != "NOTE":
                    cur += max(0, int(delay))
                    continue

                if tag == "NOTE":
                    # NOTE may also (rarely) have a Delay attribute; treat it as a gap before the note.
                    if delay is not None:
                        cur += max(0, int(delay))

                    midi = _to_int_maybe(_get_attr_ci(ch.attrib, "MidiNote"))
                    dur = _to_int_maybe(_get_attr_ci(ch.attrib, "Duration"))
                    lyr = _norm_lyric(_get_attr_ci(ch.attrib, "Lyric") or "")

                    if midi is None or dur is None:
                        continue

                    start = int(cur)
                    dur_i = max(0, int(dur))
                    yield (start, dur_i, int(midi), lyr)
                    cur += dur_i

            # free memory
            el.clear()
    except ET.ParseError:
        return
    except Exception:
        return


def melody_fingerprint_file(melody_xml: Path) -> Optional[str]:
    """Compute a semantic fingerprint for melody_*.xml based on note events.

    The fingerprint is stable against benign differences such as:
    - whitespace / attribute ordering
    - schema metadata (m2xVersion, audioVersion, etc.)
    - ADRS blocks and other non-note metadata

    Returns a SHA1 hex digest of a canonical event stream, or None if parsing fails / no notes.
    """
    events: List[Tuple[int, int, int, str]] = []
    for e in iter_melody_events(Path(melody_xml)):
        events.append(e)

    if not events:
        return None

    # normalize to remove leading constant offset
    base = int(events[0][0])
    h = hashlib.sha1()
    for (start, dur, midi, lyr) in events:
        # include rests (midi=0) since they affect timing.
        rel = int(start) - base
        line = f"{rel},{int(dur)},{int(midi)},{lyr}\n"
        h.update(line.encode("utf-8", errors="replace"))
    return h.hexdigest()


def melody_fingerprint_short(melody_xml: Path) -> Optional[str]:
    fp = melody_fingerprint_file(melody_xml)
    if not fp:
        return None
    return fp[:12]
