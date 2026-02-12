from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from tests.conftest import write_melody_xml, write_min_config, write_min_songs


@dataclass(frozen=True)
class FakeDisc:
    """Paths for a tiny synthetic SingStar disc/export layout used in tests."""

    disc_root: Path
    export_root: Path
    layout: str  # "ps3_game" | "filesystem" | "export_only"

    @property
    def ps3_game(self) -> Path:
        return self.disc_root / "PS3_GAME"


def _write_min_covers(export_root: Path, *, song_ids: list[int], page: int = 0) -> None:
    """Write a minimal covers.xml containing TPAGE_BIT cover_<id> entries.

    The production code only relies on TPAGE_BIT NAME and TEXTURE fields.
    TEXTURE uses the logical page name (e.g. page_0) without an extension.
    """
    export_root.mkdir(parents=True, exist_ok=True)
    bits = "\n".join(
        [f'  <TPAGE_BIT NAME="cover_{int(sid)}" TEXTURE="page_{int(page)}" />' for sid in song_ids]
    )
    xml = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<COVERS xmlns="http://www.singstargame.com">\n'
        f'{bits}\n'
        '</COVERS>\n'
    )
    (export_root / "covers.xml").write_text(xml, encoding="utf-8")

def _write_fake_mp4(path: Path, *, kind: str = 'video') -> None:
    """Write a tiny MP4-like file for tests.

    This is NOT a playable MP4, but it includes common MP4 box markers
    (ftyp/moov/mdat) so our fast integrity checks treat it as valid.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    # Minimal MP4 box stubs: [size][type]...
    ftyp = (
        b'\x00\x00\x00\x18' + b'ftyp' + b'isom' + b'\x00\x00\x02\x00' + b'isomiso2'
    )
    moov = b'\x00\x00\x00\x08' + b'moov'
    mdat = b'\x00\x00\x00\x08' + b'mdat'
    payload = ftyp + moov + mdat
    # Add a small tail so size checks pass.
    payload += (b'X' * 2048)
    path.write_bytes(payload)



def make_fake_disc(
    tmp_path: Path,
    *,
    label: str = "FAKE_DISC",
    layout: str = "ps3_game",
    bank: int = 1,
    song_ids: Optional[Iterable[int]] = None,
    ref_prefix: str = "",
    include_chc: bool = True,
    include_textures: bool = False,
    include_covers: bool = False,
    include_media: bool = True,
) -> FakeDisc:
    """Create a mini disc-like folder tree that is just enough for tests.

    layout:
      - "ps3_game": <disc>/PS3_GAME/USRDIR/FileSystem/Export
      - "filesystem": <disc>/USRDIR/FileSystem/Export
      - "export_only": <folder>/ (loose Export root)

    Notes:
      - Textures pages are created as page_<n>.jpg (no zero-padding), because
        the build pipeline validates covers.xml against that filename format.
    """
    song_ids_list = list(song_ids) if song_ids is not None else [1, 2]

    disc_root = tmp_path / label
    if layout == "ps3_game":
        export_root = disc_root / "PS3_GAME" / "USRDIR" / "FileSystem" / "Export"
    elif layout == "filesystem":
        export_root = disc_root / "USRDIR" / "FileSystem" / "Export"
    elif layout == "export_only":
        export_root = disc_root
    else:
        raise ValueError(f"Unknown layout: {layout}")

    write_min_config(
        export_root,
        product_code=label[:10].upper(),
        product_desc=f"{label} disc",
        bank=bank,
        ref_prefix=ref_prefix,
    )
    write_min_songs(export_root, song_ids=song_ids_list, bank=bank)

    # Minimal melodies for CHC/inspect paths.
    bodies = [
        '<SENTENCE><NOTE MidiNote="60" Duration="100" Lyric="a" /></SENTENCE>',
        '<SENTENCE><NOTE MidiNote="62" Duration="100" Lyric="b" /></SENTENCE>',
        '<SENTENCE><NOTE MidiNote="64" Duration="100" Lyric="c" /></SENTENCE>',
    ]
    for idx, sid in enumerate(song_ids_list):
        body = bodies[idx % len(bodies)]
        write_melody_xml(export_root / str(int(sid)) / "melody_1.xml", body=body)

    # Minimal preview/video files for extraction/media verification tests.
    if include_media:
        for sid in song_ids_list:
            _write_fake_mp4(export_root / str(int(sid)) / 'video.mp4', kind='video')
            _write_fake_mp4(export_root / str(int(sid)) / 'preview.mp4', kind='preview')

    if include_covers:
        _write_min_covers(export_root, song_ids=song_ids_list, page=0)

    if include_chc:
        (export_root / f"melodies_{bank}.chc").write_bytes(b"CHC\x00\x01\x02\x03")

    if include_textures:
        tex = export_root / "textures"
        tex.mkdir(parents=True, exist_ok=True)
        # content doesn't matter for tests; only existence/name.
        (tex / "page_0.jpg").write_bytes(b"\xff\xd8\xff\xd9")

    return FakeDisc(disc_root=disc_root, export_root=export_root, layout=layout)
