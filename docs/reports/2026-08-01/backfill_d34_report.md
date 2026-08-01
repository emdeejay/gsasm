# Backfill: Disk 3 (SystemTools1) + Disk 4 (SystemTools2) "no-source-substitute" / "pascal-c-nontarget" re-search

Date: 2026-08-01
Scope: all 92 fork entries on Disk 3 of 7 SystemTools1.2mg and Disk 4 of 7 SystemTools2.2mg classified
`no-source-substitute` or `pascal-c-nontarget` in `docs/disk_census_2026-08-01.json` (IWEM already excluded —
already flipped to `built` earlier today). 1:1 verified against the extracted target list — 92/92 records
covered, no drops, no duplicates.

## Trees searched (per the project's 3-tree rule)

1. `ref/GSOS_6/IIGS.601.SRC/` — grep/find, case-insensitive
2. `ref/ROM Source Code/` — `find -iname`
3. `ref/gsrom3/system500.hfv` — `work/hfs.py` `HFS(path).files` filename scan (case-insensitive substring)

Where a filename hit needed byte-level confirmation, I extracted the real fork from the gold disk image via
`/Users/mdj/src/a2til` (`a2til.prodos.Volume(...).read_file(path, fork=...)`) and diffed it directly — not
just trusting prior census prose.

## Families searched (9 families cover all 92 records)

| Family | Records | Trees hit | Outcome |
|---|---|---|---|
| Finder.Data (runtime desktop DB) | 21 | 1,2,3 | Confirmed correct — no source anywhere |
| CDevs `data` fork (structural 0B) | 14 | 1 (+ live extraction) | Confirmed correct — 0-byte fork, rsrc already built |
| Sounds `data` fork (structural 0B) | 12 | 1 (+ live extraction) | Confirmed correct — 0-byte fork, rsrc already built |
| Pascal-wall Desk.Accs/apps (FindFile, Calculator, MediaControl-DA, VideoMix, Teach, Adv.Disk.Util) | 6 | 1,2,3 | Confirmed correct — Pascal source found, no asm/rez alt anywhere |
| **TeachText docs (Read.Me, Shortcuts, Whats.New)** | **3** | 1 (+ live byte-diff) | **CANDIDATE — byte-exact match verified, not actually missing** |
| Archiver (data+rsrc) | 2 | 1,2,3 | Confirmed correct — no source, only an Installer script naming the prebuilt app |
| CLOCK.PATCH | 1 | 1,2,3 | Confirmed correct — tokenized Applesoft BASIC, no de-tokenized/asm alt |
| AppleTalk/Display.0 | 1 | 1,2,3 | Confirmed correct — opaque prebuilt binary, patched not built |
| Fonts (32 bitmap font files) | 32 | 1,2,3 | Confirmed correct — no producing source, only copy scripts |
| **Total** | **92** | | **3 candidates** |

## Commands actually run

- `find ref/GSOS_6/IIGS.601.SRC -iname '*<pattern>*'` for each family basename (Finder.Data, Archiver, ADU,
  CLOCK.PATCH, Teach, FindFileDA, GSCalc, MediaCtlNDA, PokeyNDA/VideoMix, font family names).
- `grep -ril '<basename>' ref/GSOS_6/IIGS.601.SRC --include='*.asm' --include='*.aii' --include='*.a'` — looking
  for an asm alternative alongside every known Pascal source.
- `find "ref/ROM Source Code" -iname '*<pattern>*'` for the same basenames.
- `python3 -c "... HFS('ref/gsrom3/system500.hfv') ..."` — filename substring scan against every `(parID,name)`
  key for the same basenames (courier/geneva/helvetica/shaston/times/venice/font; findfile/gscalc/calculator;
  mediactl/pokey/videomix; archiv; teach; clock; display/aristotle; adu; finder.data/finder).
- `python3 work/cdevcheck.py` — live run, confirms 19/19 CDEV resource forks byte-exact
  (`CDEV_RSRC_BYTES_EXACT 156917/156917`), including all 14 target CDevs on D3/D4.
- `a2til.prodos.Volume(path).read_file(fork_path, fork='data')` spot-checks: confirmed 0-byte data forks for
  DirectConnect, Keyboard, AppleShare (CDevs) and Ahh, Sosumi (Sounds) directly against the gold disk images
  (not just census numbers).
- `a2til.prodos.Volume(...).read_file('/SystemTools2/Read.Me', fork='data')` (and Shortcuts, Whats.New)
  byte-compared against `ref/GSOS_6/IIGS.601.SRC/ToolBoxMisc/ReadMeFiles/{Read.Me,Shortcuts,Whats.New}.text` —
  **all three: exact match** (same length, `data == src`).

## CANDIDATES (3) — prominent

All three are the **data forks of `/SystemTools2/Read.Me`, `/SystemTools2/Shortcuts`, `/SystemTools2/Whats.New`**
on Disk 4. The census evidence already *named* `ToolBoxMisc/ReadMeFiles/{Read.Me,Shortcuts,Whats.New}.text` as
the likely source and said the data fork "is the literal TeachText text, byte-identical to the tracked source
... but NO gate harness currently performs that byte comparison — carried verbatim pending a wired check (GAP;
see B_REPORT.md)". I ran that exact comparison myself against the real gold disk image:

```
Read.Me     gold_len=2150  src_len=2150  match=True
Shortcuts   gold_len=19939 src_len=19939 match=True
Whats.New   gold_len=5102  src_len=5102  match=True
```

The rsrc fork for all three is already `built` via `work/rezdatacheck.py` from the corresponding `.r` file in
the same `ToolBoxMisc/ReadMeFiles/` directory. This is not a "no source" situation at all — it's a missing
harness. A supervisor should either flip these three `data` forks to `built` (once a small comparison gate is
wired, e.g. into `rezdatacheck.py` or a new `textcheck.py`) or otherwise formally close the GAP noted in
`B_REPORT.md`. Per the mission rules I have NOT changed the classification myself — only recorded the verified
finding with `"candidate": true`.

## Notable non-candidate findings worth a supervisor's attention (taxonomy, not missing-search)

- `/SystemTools1/System/Desk.Accs/FindFile` `data` fork is labeled `no-source-substitute`, but its own evidence
  field already documents Pascal source (`FindFileDA.p`) and even says the file-level `pascal-c-nontarget`
  label "undercounted" the fork-level one. This is a pre-existing labeling inconsistency in the census (not a
  missing search), confirmed but not changed here.
- Same fork-vs-file-level inconsistency exists for `/SystemTools1/Adv.Disk.Util`, `/SystemTools2/System/Desk.Accs/MediaControl`,
  `/SystemTools2/System/Desk.Accs/VideoMix`, and `/SystemTools2/Teach` — all have Pascal source already
  documented but a `data`-fork label of `no-source-substitute` rather than `pascal-c-nontarget`. Re-search
  confirms no asm/rez substitute exists in any of the 3 trees for any of them, so the *substance* is correct
  either way, only the enum bucket differs.

## Surprising / worth flagging separately (not a candidate, but interesting)

- `A.U.G/CtlPanel/SoundCDEV/Sounds/` contains **more** `.r` sound sources than the 12 shipped
  System Sounds — also `Clavichord.r`, `Chirp.r`, `Whip.r`, `Guitar.r`, `Lore.r` — presumably alternate/unused
  sound sets from other System 6.0.1 configurations. Not relevant to this disk's census (none of those 5 ship on
  D3/D4), noted only in case another disk's census references them.
- `SD.ODDS.N.Ends/APW.Scripts/Build.Fonts` explicitly proves the font bitmaps are copied ("Duplicate") from an
  external `{Source}Fonts:...` folder rather than compiled — good direct confirmation for the whole 32-file Fonts
  family, not just an absence-of-evidence inference.
