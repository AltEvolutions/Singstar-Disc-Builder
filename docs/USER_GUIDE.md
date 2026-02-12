# SSPCDB User Guide
> Prefer the HTML version when reading locally: open `docs/USER_GUIDE.html` in your browser (includes a Dark/Light toggle).

This guide covers the **typical GUI workflow** for building a custom SingStar PS3 disc folder from an extracted **Base** disc plus one or more **Source** discs.

> Reminder: this repository is **code + docs only**. Do not include or share copyrighted disc content.

## Requirements

- Python installed (Windows/Linux/macOS)
- Discs as **decrypted folders** (a folder containing `PS3_GAME/`). ISO images are **not supported directly** — extract/decrypt to a folder first.
- Packed/unextracted discs with `Pack*.pkd` are supported **via the external extractor** (configured in-app).
- For real hardware use: **SingStar Update 6.00** must be installed on the PS3 before using a custom disc.
  - Before launching SingStar, **check for updates** (or install Update 6.00 via PKG in your existing workflow).
  - On the **first boot**, large builds (e.g. **300+ songs**) may take a while: wait for the song icons to stop spinning, then you will reach the developer logos/intro video.
- For RPCS3 emulation:
  - The **first in-game load** (e.g. getting into the song list / initial content load) typically takes **~30–60 seconds** on larger song sets.
  - Occasionally RPCS3 may **crash during this first in-game load**; a successful run usually occurs after **up to 3 retries** (more retries can be needed in rare cases).
  - This is observed **RPCS3/emulation-side variability**, not necessarily an invalid build.


## Base disc guidance (important)

- **Recommended base disc (tested):** **SingStar [BCES00011]**.
- **Region seems to be irrelevant** for SSPCDB builds (any equivalent SingStar disc-region should work the same).
- **Avoid using these as the Base disc:** **SingStar MegaHits** and **SingStar: Ultimate Party** (and their regional equivalents). Their latest official update is **v01.10**, not **v06.00**. They **can still be used as Source discs**.
- Some later themed discs (example: **SingStar Frozen**) have a latest update **v01.03**, not **v06.00** — treat them as **Source-only** unless you personally validate them as a Base.
- **Disc order:** for typical use, **order doesn’t matter**. Pick your Base disc (template), then add any Source discs you want.

### SingStar titles known to offer Update 6.00

This list is based on the RPCS3 update catalog (Title IDs + latest patch version). If your disc isn’t listed here, the safest approach is: **use BCES00011 as Base** and treat unknown discs as **Source**.

- **SingStar** — BCES00011 / BCES00030 / BCES00031 / BCES00032 / BCES00051 / BCUS98151
- **SingStar ABBA** — BCES00381 / BCES00423 / BCUS98192
- **SingStar A Tutto Pop** — BCES00345
- **SingStar Afrikaanse Treffers** — BCES01083
- **SingStar Après-Ski Party 2** — BCES01024
- **SingStar Cantautori Italiani** — BCES01023
- **SingStar Chart Hits** — BCES00846
- **SingStar Dance** — BCES00894 / BCES01049 / BCUS98266
- **SingStar Fussballhits** — BCES00869
- **SingStar Grandes Exitos** — BCES01258
- **SingStar Guitar** — BCES00835 / BCES00979 / BCES00980 / BCES00981
- **SingStar Hits** — BCES00264
- **SingStar Hits 2** — BCES00346
- **SingStar Intro** — BCES00622
- **SingStar Kent** — BCES00852
- **SingStar Vol. 2** — BCES00185 / BCES00235 / BCES00233 / BCES00234 / BCUS98178
- **SingStar Vol. 3** — BCES00216 / BCES00265 / BCES00266 / BCES00267


## Concepts

> Note: SSPCDB works with **folder-based, decrypted disc dumps**. It does not open ISO images directly.

- **Base disc**: the disc you are building “on top of”. Branding defaults and many baseline files come from Base.
- **Source discs (donors)**: additional discs you can pull songs/assets from.
- **Packed vs extracted**:
  - **Extracted**: already has a `PS3_GAME/` folder on disk.
  - **Packed / unextracted**: contains `Pack*.pkd` archives that must be extracted to harvest `FileSystem/Export`.

## Workflow (GUI)

### 1) Add discs
1. Add your **Base** disc (extracted folder).
2. Add one or more **Source** discs.
   - If a Source is packed, you can extract it later (step 2).

Tip: use the Sources panel to select which discs are “active” for filtering and building.

### 2) Extract packed sources (external tool)
If any sources are packed/unextracted (and you have the external extractor configured):
1. Select the packed sources
2. Click **Extract Selected**
3. Wait for extraction to complete (you can cancel; cancelled builds are kept as `__CANCELLED*`)




### Extractor setup (external)

SSPCDB can work with **extracted** discs (already containing `PS3_GAME/`) and also with **packed/unextracted** sources (containing `Pack*.pkd`).

For packed sources, SSPCDB uses the external extractor:

- **Edness — SCEE London Studio PS3 PACKAGE tool**: https://github.com/EdnessP/scee-london/

**Setup (all platforms):**
1. Download/build the extractor from the repo above.
2. Put the resulting binary in `./extractor/` (recommended), or anywhere you like.
3. In SSPCDB, use **Browse…** next to the extractor path and select:
   - Windows: `scee_london.exe`
   - Linux/macOS: `scee_london`

**Linux/macOS permissions (common fixes):**
- `chmod +x scee_london`
- macOS (if blocked/quarantined): `xattr -d com.apple.quarantine scee_london`

Once set, select your packed discs and click **Extract Selected**.

### 3) Validate selected discs
Click **Validate Selected** to run non-destructive checks. This helps catch:
- Missing expected Export data
- Common folder casing issues
- Incomplete extraction

If validation warns/blocks, check the logs and the on-screen message, fix the disc folder, then re-validate.

### 4) Select songs
Use the Songs table to select what you want:
- Songs are grouped by **Preferred disc**
- Group headers can collapse/expand, and a group checkbox toggles all in the group
- Use the Source filter (and “Selected discs”) to focus on relevant donors

### 5) Resolve conflicts (when needed)
If the same Song ID exists in multiple sources with different content, use **Resolve Conflicts…** to choose the winning source.
Tools in the dialog include:
- Detect identical duplicates
- Auto-resolve identical
- Apply recommended

### 6) Build (full build)
1. Choose an output folder (empty is simplest).
2. Optional: enable **Allow overwrite existing output** if you want to rebuild into an existing output folder.
   - Recommended: keep **Keep backup of existing output** enabled so the prior build is preserved as `__BACKUP_*`.
   - Safety guardrail: overwrite is only allowed when the target folder looks like a previous SingStar disc/output (Export signature) and it is **not** one of your selected input folders (base/donors).
3. Click **Build Selected**

> Note: If your selection contains two entries with the same **Title + Artist** (different Song IDs),
> SingStar may suppress them in-game. SSPCDB will prompt you to choose which ID to keep (and will remember
> that choice for this project).

### 7) Update Existing… (fast incremental rebuild)
Use **Update Existing…** when you already built an output disc folder and you want to apply changes without a full rebuild (for example, add/remove discs, change your selection, or regenerate indexes).

High-level behavior:
- SSPCDB renames your chosen output folder to a timestamped backup (for example: `OUTPUT.__BACKUP_YYYYMMDD_HHMMSS`).
- It seeds the new output from that backup (using **hardlinks** when possible; otherwise copy), then applies only the differences.
- You’ll see a **pre-flight delta** summary (+added / -removed) before the update runs.

Notes:
- Updates are fastest when the output is on the **same drive/filesystem** (hardlinks).
- Update Existing still writes the normal sidecar reports next to the output folder (useful for verifying what changed).

### Which button should I use?
- **Build Selected**: first build, or when you want a clean rebuild into a new folder.
- **Update Existing…**: you already have an output folder and want the fastest “apply changes” workflow.
- **Apply to existing output…** (Branding-only): update ICON0/PIC1 only (no song/XML changes).

## Output files you should expect

After a successful build/update, SSPCDB writes the disc folder plus a few sidecar files next to it:

- `*_build_report.json`
- `*_build_report.txt`
- `*_transfer_notes.txt`
- `*_preflight_summary.txt`
- `*_expected_songs.csv`
- `*_built_songs.csv`
- `*_song_diff.csv`

These files are safe to share (they contain **no disc assets**) and are useful when debugging.

## Disc branding (XMB)

You can optionally override the disc’s XMB visuals:

- `PS3_GAME/ICON0.PNG` (tile icon) — auto-resized to **320×176**
- `PS3_GAME/PIC1.PNG` (background) — auto-resized to **1920×1080**

There are two workflows:
- Set overrides and **Build Selected** (applies during build)
- Use **Apply to existing output…** to update ICON0/PIC1 in an **already-built** output folder without rebuilding


## Recommended usage (single output disc)

SSPCDB is designed around a simple flow: **pick everything you want, then build one output disc folder**.

- Most users will select a Base disc plus all donor discs they own, then click **Build Selected** once.
- If you want to change the selection later (add/remove donors, adjust picks, regenerate indexes), prefer **Update Existing…** instead of rebuilding from scratch.

## Expected behaviour (real hardware and RPCS3)

- On real hardware, very large song sets can take longer on first load. Let the game finish loading (e.g., wait for song icons to stop spinning) before deciding something is wrong.
- In **RPCS3**, the first in-game load (entering the song list / initial content load) typically takes **~30–60 seconds** on larger song sets.
  - Occasionally RPCS3 may crash during this first in-game load; a successful run usually occurs after **up to 3 retries** (more retries can be needed in rare cases).
  - This is observed RPCS3/emulation-side variability, not necessarily an invalid build.

## Support bundle (for bug reports)

Export a support bundle (no copyrighted assets; paths are redacted by default):

- Qt GUI: **Help → Export support bundle...**
- CLI: `python -m spcdb_tool support-bundle --out spcdb_support.zip`



### Troubleshooting (common)

- **Extractor not set / Export folder not found:** set the extractor path (`scee_london` / `scee_london.exe`) and extract the disc.
- **First in-game load seems stuck (large builds):** on PS3, wait for song icons to stop spinning; on RPCS3, first load may take ~30–60s and may need a retry.
- **Update Existing is slow:** it’s fastest when output is on the same drive/filesystem (hardlinks). Different drives will copy instead.
