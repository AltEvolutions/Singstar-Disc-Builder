from __future__ import annotations

from pathlib import Path


def write_melody_xml(path: Path, *, body: str) -> None:
    """Write a minimal SingStar melody_*.xml with provided inner body."""
    path.parent.mkdir(parents=True, exist_ok=True)
    xml = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<MELODY xmlns="http://www.singstargame.com">\n'
        f'{body}\n'
        '</MELODY>\n'
    )
    path.write_text(xml, encoding="utf-8")


def write_min_config(
    export_root: Path,
    *,
    product_code: str = "TEST",
    product_desc: str = "Test Disc",
    bank: int = 1,
    ref_prefix: str = "",
) -> None:
    """Write a minimal SingStar Export/config.xml with one VERSION.

    ref_prefix is prepended to referenced file paths inside config.xml. Some real
    discs store paths like "FileSystem/Export/songs_6_0.xml" even when we're
    inspecting a loose Export folder.
    """
    export_root.mkdir(parents=True, exist_ok=True)
    p = ref_prefix
    cfg = f'''<?xml version="1.0" encoding="utf-8"?>
<CONFIG xmlns="http://www.singstargame.com">
  <PRODUCT_CODE>{product_code}</PRODUCT_CODE>
  <PRODUCT_DESC>{product_desc}</PRODUCT_DESC>
  <VERSION version="{bank}">
    <SONGS>
      <SONG_LIST>{p}songs_{bank}_0.xml</SONG_LIST>
      <ACT_LIST>{p}acts_{bank}_0.xml</ACT_LIST>
    </SONGS>
    <SONG_LISTS><FILE>{p}songlists_{bank}.xml</FILE></SONG_LISTS>
    <MELODY_CACHE><FILE>{p}melodies_{bank}.chc</FILE></MELODY_CACHE>
  </VERSION>
  <COVERS><LIST>{p}covers.xml</LIST></COVERS>
</CONFIG>
'''
    (export_root / "config.xml").write_text(cfg, encoding="utf-8")

    # Optional but helps avoid confusion when reading fixtures:
    (export_root / "covers.xml").write_text('<COVERS xmlns="http://www.singstargame.com"></COVERS>\n', encoding="utf-8")
    (export_root / f"acts_{bank}_0.xml").write_text('<ACTS xmlns="http://www.singstargame.com"></ACTS>\n', encoding="utf-8")
    (export_root / f"songlists_{bank}.xml").write_text('<SONG_LISTS xmlns="http://www.singstargame.com"></SONG_LISTS>\n', encoding="utf-8")


def write_min_songs(export_root: Path, *, song_ids: list[int], bank: int = 1) -> None:
    export_root.mkdir(parents=True, exist_ok=True)
    inner = "\n".join([f'  <SONG ID="{int(sid)}" />' for sid in song_ids])
    songs = f'''<?xml version="1.0" encoding="utf-8"?>
<SONGS xmlns="http://www.singstargame.com">
{inner}
</SONGS>
'''
    (export_root / f"songs_{bank}_0.xml").write_text(songs, encoding="utf-8")


def make_export_root(tmp_path: Path, *, label: str, song_ids: list[int], melodies: dict[int, str], bank: int = 1) -> Path:
    """Create a tiny synthetic Export root that is just enough for planning/tests."""
    export_root = tmp_path / label
    write_min_config(export_root, product_code=label.upper(), product_desc=f"{label} disc", bank=bank)
    write_min_songs(export_root, song_ids=song_ids, bank=bank)
    for sid, body in melodies.items():
        write_melody_xml(export_root / str(int(sid)) / "melody_1.xml", body=body)
    return export_root
