<img width="200" height="200" alt="spcdb_icon" src="https://github.com/user-attachments/assets/95feae38-f66a-4e7c-a296-0dc97eaeea00" />

# SingStar PS3 Custom Disc Builder (SSPCDB)

**SSPCDB** builds a custom SingStar PS3 disc folder by selecting songs from a **Base** disc plus one or more **Source** discs.

- **Version:** 1.0.0
- **License:** GPL-3.0
- **Code + docs only:** this repo does **not** include any copyrighted game content.

## Quick start (Windows)

1. Install Python (**3.11+** recommended).
2. In the repo folder:

```bat
py -m venv .venv
.venv\Scripts\python.exe -m pip install -U pip
.venv\Scripts\python.exe -m pip install -r requirements.txt

REM If you're in PowerShell, use: .\run_gui.bat
run_gui.bat
```

> Tip: you can also run the GUI via `python -m spcdb_tool gui`.

## Documentation

- **User Guide (HTML, best local reading):** `docs/USER_GUIDE.html` (open in any web browser; includes a Dark/Light toggle)

## Important notes

- **Disc format:** SSPCDB expects **decrypted disc folders** (a folder containing `PS3_GAME/`). ISO images are **not supported directly** — extract/decrypt the ISO to a folder first. If you already have an extracted disc folder, you do **not** need the external extractor.
- **Real hardware requirement:** install **SingStar Update 6.00** on the PS3 before using a custom disc.
- **Recommended Base disc (tested):** SingStar **BCES00011**.
- **Avoid as Base:** SingStar MegaHits and SingStar: Ultimate Party (their latest official update is **v01.10**, not **v06.00**). They are fine as **Source** discs.

## External extractor (not bundled)

If you have packed discs (with `Pack*.pkd`), you can extract them using **Edness's “SCEE London Studio PS3 PACKAGE tool”** (external dependency; not bundled here).

Setup instructions are in the **User Guide** (see the “Extractor setup” section).

## Credits

- **Edness** (https://bsky.app/profile/edness.bsky.social) - SCEE London Studio PS3 PACKAGE tool (external extractor) (https://github.com/EdnessP/scee-london/)
- **AltEvolutions** - SSPCDB (https://bsky.app/profile/altevolutions.uk) / https://github.com/AltEvolutions

## Trademark & affiliation notice

SingStar and PlayStation are trademarks of their respective owners. This project is not affiliated with or endorsed by Sony.
