# M8 — Byte-exact GS/OS 6.0.1 disk images (the capstone)

Extends gsasm from "byte-exact *files*" to "byte-exact *disk images*" — the
project's original north star ("byte-exact reproduction of the shipping GS/OS
System 6.0.1 **images**"). It is `buildrom.py` one level up: the ROM proved a
256K firmware image is reconstructable byte-identical (99% gsasm-built, the rest
substituted); M8 does the same for the shipping `.2mg` floppies.

## The target
`ref/GSOS_6/System601_disks/System 6.0.1/` — seven 800K `.2mg` floppies (2IMG
wrapper + 1600 ProDOS blocks) plus extras. Primary target: **Disk 2 — System
Disk** (the boot volume). Later: Install, SystemTools1/2, Fonts, etc.

## The strategy — the ROM pattern, at the disk level
A shipping disk is a ProDOS volume of files. Most of the System Disk is ASM we
build from clean-room source; the rest is Pascal/C, resource forks, and data.

- **Build** what we can (GS.OS, ProDOS, P8, Start.GS.OS, Error.Msg, the ToolNNN,
  toolsets TS2/TS3, Resource.Mgr, Tool.Setup, FSTs, drivers) with the gsasm
  toolchain, and **overlay** each file's bytes into its **original data blocks**.
- **Substitute** the rest (Pascal CDEVs, ControlPanel, resource forks — Rez is
  M7/out of scope — plus fonts/icons/`Finder.Data`) from the original image.
- Byte-compare the reconstruction to the shipping `.2mg`.

Headline result target: *a byte-identical System Disk, N% of its bytes built from
clean-room source* — exactly "ROM 99% gsasm-built, 100% byte-identical."

## Why overlay (not build-from-scratch)
Byte-exactness requires the **exact block layout** the original GS/OS installer
wrote. Reproducing that allocation order from an empty volume is the *stretch*
goal. The pragmatic, achievable path is **overlay**: keep the original's
directory, dates, bitmap, index blocks and block placement; write only each
built file's data into its **own original data blocks**. A byte-correct build
then leaves the image byte-identical; an incorrect one reveals exactly which of
its bytes differ — turning the structural grind into a precise, disk-driven
worklist.

## The ProDOS/2IMG layer — reuse a2til (do NOT re-implement)
`/Users/mdj/src/a2til` — a single-file, dependency-free ProDOS disk-image toolkit
(read/write `.po`/`.hdv`/`.2mg`/`.dsk`, seedling/sapling/tree + **extended/forked**
files, GS/OS mixed-case names, sparse files, 2IMG wrappers), cross-checked
byte-for-byte against cadius and real disks (it recreates *Total Replay*, 32 MB /
2480 files, byte-exact). `diskcheck.py` drives its `Volume`:
`scandir` (catalog), `_resolve_fork`/`_blocks_for` (a file's data-block list),
`_write_block` (the raw overlay).

## The harness — `work/diskcheck.py` (skeleton done, review-hardened)
Modeled on `buildrom.py`. Validated on the System Disk, and hardened per the
M8 second-chair review (`M8_SECOND_CHAIR_REPORT.md`):
- **Explicit manifest, not a type heuristic**: each path is owned `build` / `rez`
  (resource-forked → M7) / `substitute` / `out-of-scope`; an on-disk file absent
  from the manifest **fails the inventory**. Catalog: 50 files → **build 29, rez 9,
  substitute 11, oos 1**.
- **Fork-aware metrics** (three numbers, not one): data-fork 662,792 B,
  resource-fork 107,002 B; **BUILD data-fork 465,579 (70%)** source-buildable.
  (The earlier "81%" used the directory-entry EOF, which is the 512-byte extended
  key for forked files — a wrong denominator.)
- **Round-trip** (no builders): **byte-identical, 819264/819264** — a smoke test,
  NOT a rebuild proof.
- **Overlay is byte-clean AND asserts sparse-zero**: sparse logical blocks return
  block 0; the overlay skips them *and requires the built bytes there to be zero*
  (else a bad build could be masked — Pro.FST/GS.OS/Start have sparse blocks).
- **Builder contract** (`build_and_overlay`): `len == data-fork EOF`, logical
  compare `content == read_file` **before** overlay, then physical byte-identity;
  `--min-built N` gates built-byte coverage so it can't silently be zero.

Commands:
```
python3 work/diskcheck.py             # inventory + fork-aware metrics + round-trip
python3 work/diskcheck.py -v          # per-file manifest listing
python3 work/diskcheck.py --selftest  # prove overlay byte-cleanliness
python3 work/diskcheck.py --min-built N   # CI: fail below N built-bytes
```

## Scope: in-scope (build) vs substitute (System Disk)
| build (ours, ASM) | substitute |
|---|---|
| ProDOS · P8 · GS.OS · Start.GS.OS · GS.OS.Dev · Error.Msg · Resource.Mgr · Tool.Setup · TS2 · TS3 · Tool014–034 (13) · Char.FST · Pro.FST · AppleDisk3.5/5.25 · Console.Driver · CDev.Data | resource-forked files (`Start` loader fork, CDEVs, ControlPanel, EasyMount — need Rez), Pascal CDEVs, BASIC.System, fonts/icons/`Finder.Data`/Font.Lists |

Note: `Start` (the Loader) has an ASM data fork but a **resource fork** → whole-file
substitute until Rez (M7). A resource-forked file is substituted even when its
data fork is ours.

## Plan
- **Phase 1 — skeleton** ✅ (`diskcheck.py`: a2til catalog + byte-clean overlay +
  round-trip; 81% buildable quantified).
- **Phase 2 — wire per-file `SOURCE_BUILDERS`** (`path -> our toolchain -> exact
  disk-file bytes`). Each builder returns the FULL on-disk file (the ExpressLoad'd
  OMF / MakeBin output), not the de-ExpressLoad'd code image the `*check.py`
  harnesses compare. Order: start with the **already byte-exact** files (ProDOS,
  Error.Msg, the byte-exact ToolNNN, Char.FST via expressload) to prove end-to-end
  and set a real disk %; then let the disk drive the residual worklist — the
  System Disk is gated by a *short* known list: **AppleDisk3.5 (20%), AppleDisk5.25
  (70%)**, Char.FST's 3-byte SUPER page-offset, and a few tool tails.
- **Phase 3 — the other disks** (Install, SystemTools1/2 — the latter hosts the
  alien FSTs; Fonts is mostly data/substitute).
- **Stretch — build-from-scratch**: reproduce the installer's block allocation +
  catalog/bitmap/boot from an empty a2til volume, byte-identical.

## Validation discipline
`diskcheck.py`'s image byte-match is the gate, exactly like `buildrom.py`'s
byte-identity. Golden = the shipping `.2mg` (gitignored under `ref/`). Every
wired builder must keep the round-trip byte-identical for the files it covers, and
lift the source-built %. Never regress a file that already overlays clean.
