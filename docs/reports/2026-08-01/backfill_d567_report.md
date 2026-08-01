# Backfill: Disk 5/6/7 "no-source-substitute" / "pascal-c-nontarget" records (2026-08-01)

Scope: every fork entry classified `no-source-substitute` or `pascal-c-nontarget` on Disk 5 (Fonts),
Disk 6 (synthLAB), Disk 7 (Apple II Setup) in `docs/disk_census_2026-08-01.json`.
**73/73 target records processed** (verified by exact set-diff against the census — 0 missing, 0 extra).

All three source trees were actually searched for every record (filename + targeted content):
1. `ref/GSOS_6/IIGS.601.SRC/` — grep -r / find -iname, plus full manual directory browse of every
   relevant subtree (A.U.G, GS.OS/NetBoot/Installer, GSToolbox/{FontMgr,MIDISynth,NoteSynth,NoteSeq,Midi},
   SD.ODDS.N.Ends/APW.Scripts).
2. `ref/ROM Source Code/` — this tree is small (231 files, 26 dirs) and was fully listed/browsed
   directly rather than grepped piecemeal; confirmed to contain only 65816/6502 ROM-resident engine
   asm (QuickDraw, GS/OS, toolbox, drivers) — no data files, no fonts, no synth content, no
   Installer/IWEm/Script sources anywhere in it.
3. `ref/gsrom3/system500.hfv` (MPW-GM disk image) — read via `work/hfs.py` (`HFS(...).files`,
   `.path()`, `.data()`), built a 4163-filename index, checked every target filename against it,
   and opened a handful of ambiguous hits to confirm/rule them out (see below).

## Families searched

**Disk 5 — Fonts (30 records)**
- 23 font data files (Courier/Helvetica/Times × point sizes): absent from all 3 trees. **Decisive
  find**: `ref/GSOS_6/IIGS.601.SRC/SD.ODDS.N.Ends/APW.Scripts/Build.Fonts` is the literal disk-assembly
  script for this disk and contains only `Duplicate` commands pulling every one of these 23 filenames
  from an external, not-checked-in tree (`:A2CE_Sources:System Disk 6.0:`). Same pattern already known
  for synthLAB's `Build.Synth`. Confirms genuine no-source binary data, not an incomplete search.
- 4× `Finder.Data`: zero hits across all 3 trees (Finder-runtime metadata, project-wide rule already
  applies).
- `/Fonts/Goodies/Apple.Bowl` data (pascal-c-nontarget): source (`Bowl.bas` + `IntBasicIIGS` Pascal
  compiler source) confirmed present in IIGS.601.SRC; confirmed the *compiled* IntBasicIIGS tool is
  absent from ROM Source and system500.hfv too, so even out-of-repo execution isn't possible. Scope
  wall confirmed, not a search gap.
- `/Fonts/Goodies/Read.Me` data — **CANDIDATE**, see below.
- `/Fonts/Icons/AppleBowl.Icon` data: archived copy already cited, byte-size match confirmed (466B),
  no build rule in `Apple.Bowl/Makefile`. Confirmed, not a gap.

**Disk 6 — synthLAB (25 records)**
- synthLAB app, `SL.Icons`, all 17 `Seq.and.Instr/*.{bnk,seq,wav}` files, `Reference` (data+rsrc): all
  absent from all 3 trees by filename. **Decisive find**: `Build.Synth` (same script family as
  `Build.Fonts`) contains an explicit `Duplicate` line naming every single one of these files,
  confirming they are externally-authored binaries duplicated verbatim into the disk image.
- One system500.hfv filename collision for "Reference" was individually opened and ruled out
  (`MPW-GM/MPW/MPButtons` — an unrelated MPW toolbar-button file).
- 3× `Finder.Data`, `/synthLAB/MIDI` data (0B structural): standard patterns confirmed.

**Disk 7 — Apple II Setup (18 records)**
Disk 7 context from the mission brief held up completely: every rsrc fork here is a genuine Mac-format
resource fork produced by *Mac* Rez, which `gsrez` (IIgs-format only) can never byte-match regardless
of source availability. For 5 of these (Basic.System, p8, Apple //e Boot Blocks, ProDOS16 Boot Blocks,
ProDOS16 Image rsrc forks) the census **already** cites the exact Mac `.r` source
(`GS.OS/NetBoot/Installer/{Basic,P8,Bullwinkle,BootBlocks,Image}.r`) — I confirmed each is present in
IIGS.601.SRC and absent from system500.hfv, and recorded the decision as "Mac Rez artifact, container
out of scope" per the mission's guidance rather than restating "no source anywhere."
- `/Apple II Script` rsrc: source `Apple2GSInstallerScript.r` already cited. New: its `#include`
  dependency `Types.r` **was found** in system500.hfv (`MPW-GM/Interfaces&Libraries/Interfaces/RIncludes/Types.r`);
  `InstallerTypes.r` remains absent from all 3 trees. Doesn't change the decision (container format is
  the hard blocker) but refines the evidence.
- `/IWEm` rsrc (312B): no producing source anywhere — checked the `IWEm.Src`-holding directory (no `.r`
  file at all), ruled out `SpoolerIWEM.r`'s one unrelated 2-byte resource, and checked the in-tree
  carried `IWEm` binary for an attached resource fork via `xattr`/`ls -la@` (none present).
- `/Installer` data+rsrc: confirmed this is Apple's Mac 68k Installer app (creator `bjbc`), distinct
  from the IIgs Installer already gated on Disk 1. No 68k Mac source in any tree; one system500.hfv
  near-miss ("Installer Engine") opened and ruled out as an unrelated later-era tool.
- `/Spooler—Read Me` data+rsrc: in-tree copy `NetBoot/SpoolerIWEM/SpoolerGÇöRead Me` independently
  byte-verified today (`wc -c` = 273, exact match to the golden data fork) — same mojibake-filename
  family that cracked IWEm earlier today, but here it only reconfirms already-correct evidence (no
  build step exists for this file even with a byte match, so it stays no-source-substitute, unlike the
  Read.Me case below which DOES have a Makefile rule).
- `/Desktop`, `/Finder.Data`, `/System Folder/Finder.Data` (6 records): standard Finder-runtime-DB
  pattern, confirmed absent from all 3 trees.

## CANDIDATE (1) — flagged for supervisor verification, decision NOT changed

**Disk 5 of 7 Fonts.2mg | /Fonts/Goodies/Read.Me | data fork**

`ref/GSOS_6/IIGS.601.SRC/A.U.G/Apple.Bowl/Read.Me.txt` is plain TeachText prose and is **exactly 3329
bytes** — an exact byte-count match to the golden data fork (3329B). `Apple.Bowl/Makefile`'s `Read.Me`
target is literally `Duplicate -d -y Read.Me.txt Read.Me`. The census's own v1 evidence already
flagged this ("byte-identical to the tracked source... but NO gate harness currently performs that
byte comparison — GAP; see B_REPORT.md"). I independently reconfirmed the byte-count match today but
did not diff content byte-for-byte against the live gold fork (no gate harness invoked — that's the
verification step this record calls for). Unlike `/Spooler—Read Me` (identical situation but genuinely
no build rule), this one has an actual Makefile `Duplicate` rule, so a wired byte-diff gate could
plausibly flip this record to `built` with no new tooling (the rsrc fork of the same file is already
gated this way via `rezdatacheck`).

**Suggested next step**: add/extend a check (rezdatacheck-style or a plain byte-diff) comparing
`A.U.G/Apple.Bowl/Read.Me.txt` against the Disk-5 gold `/Fonts/Goodies/Read.Me` data fork.
