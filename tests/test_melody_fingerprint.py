from __future__ import annotations

from pathlib import Path

from spcdb_tool.melody_fingerprint import melody_fingerprint_file
from tests.conftest import write_melody_xml


def test_fingerprint_stable_against_whitespace_and_attribute_order(tmp_path: Path) -> None:
    p1 = tmp_path / "a.xml"
    p2 = tmp_path / "b.xml"

    write_melody_xml(
        p1,
        body="""
  <SENTENCE>
    <NOTE MidiNote=\"60\" Duration=\"100\" Lyric=\"Hello\" />
    <NOTE MidiNote=\"62\" Duration=\"100\" Lyric=\"world\" />
  </SENTENCE>
""",
    )

    # Same events, different ordering + lowercase attrs + extra whitespace.
    write_melody_xml(
        p2,
        body="""
  <SENTENCE>

    <NOTE lyric=\"hello\" duration=\"100\" midinote=\"60\" />
    <NOTE  DURATION=\"100\"   MIDINOTE=\"62\"   LYRIC=\"WORLD\"/>

  </SENTENCE>
""",
    )

    assert melody_fingerprint_file(p1) == melody_fingerprint_file(p2)


def test_fingerprint_marker_delay_equivalent_to_note_delay(tmp_path: Path) -> None:
    a = tmp_path / "marker.xml"
    b = tmp_path / "note.xml"

    # 50-tick gap represented by a marker element.
    write_melody_xml(
        a,
        body="""
  <SENTENCE>
    <LABEL Delay=\"50\" />
    <NOTE MidiNote=\"60\" Duration=\"100\" Lyric=\"a\" />
  </SENTENCE>
""",
    )

    # Same 50-tick gap represented as NOTE Delay.
    write_melody_xml(
        b,
        body="""
  <SENTENCE>
    <NOTE Delay=\"50\" MidiNote=\"60\" Duration=\"100\" Lyric=\"a\" />
  </SENTENCE>
""",
    )

    assert melody_fingerprint_file(a) == melody_fingerprint_file(b)


def test_lyric_normalization_unicode_punctuation(tmp_path: Path) -> None:
    a = tmp_path / "unicode.xml"
    b = tmp_path / "ascii.xml"

    # Use escape codes so we don't depend on editor unicode behavior.
    lyric_unicode = "don\u2019t-stop\u2014now"
    lyric_ascii = "don't-stop-now"

    write_melody_xml(
        a,
        body=f"""
  <SENTENCE>
    <NOTE MidiNote=\"60\" Duration=\"100\" Lyric=\"{lyric_unicode}\" />
  </SENTENCE>
""",
    )
    write_melody_xml(
        b,
        body=f"""
  <SENTENCE>
    <NOTE MidiNote=\"60\" Duration=\"100\" Lyric=\"{lyric_ascii}\" />
  </SENTENCE>
""",
    )

    assert melody_fingerprint_file(a) == melody_fingerprint_file(b)


def test_numbers_as_floats_are_handled(tmp_path: Path) -> None:
    a = tmp_path / "ints.xml"
    b = tmp_path / "floats.xml"

    write_melody_xml(
        a,
        body="""
  <SENTENCE>
    <NOTE MidiNote=\"60\" Duration=\"100\" Lyric=\"a\" />
    <NOTE MidiNote=\"62\" Duration=\"50\" Lyric=\"b\" />
  </SENTENCE>
""",
    )
    write_melody_xml(
        b,
        body="""
  <SENTENCE>
    <NOTE MidiNote=\"60.0\" Duration=\"100.0\" Lyric=\"a\" />
    <NOTE MidiNote=\"62.0\" Duration=\"50.0\" Lyric=\"b\" />
  </SENTENCE>
""",
    )

    assert melody_fingerprint_file(a) == melody_fingerprint_file(b)
