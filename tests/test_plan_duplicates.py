from __future__ import annotations

from pathlib import Path

from spcdb_tool.layout import resolve_input
from spcdb_tool.plan import make_plan
from tests.conftest import make_export_root


def test_plan_classifies_identical_and_unresolved_duplicates(tmp_path: Path) -> None:
    base_melodies = {
        1: """
  <SENTENCE>
    <NOTE MidiNote=\"60\" Duration=\"100\" Lyric=\"a\" />
  </SENTENCE>
""",
        2: """
  <SENTENCE>
    <NOTE MidiNote=\"60\" Duration=\"100\" Lyric=\"a\" />
  </SENTENCE>
""",
    }
    donor_melodies = {
        # song 1 identical
        1: base_melodies[1],
        # song 2 different
        2: """
  <SENTENCE>
    <NOTE MidiNote=\"62\" Duration=\"100\" Lyric=\"a\" />
  </SENTENCE>
""",
    }

    base_export = make_export_root(tmp_path, label="base", song_ids=[1, 2], melodies=base_melodies)
    donor_export = make_export_root(tmp_path, label="donor", song_ids=[1, 2], melodies=donor_melodies)

    base_ri = resolve_input(str(base_export))
    donor_ri = resolve_input(str(donor_export))

    rep = make_plan(base_ri=base_ri, donor_ris=[donor_ri], target_version=1, collision_policy="fail")

    assert 1 in rep.identical_duplicates
    assert 2 in rep.unresolved_duplicates
