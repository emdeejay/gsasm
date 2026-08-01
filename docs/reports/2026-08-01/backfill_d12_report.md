# Backfill search report: Disk 1 (Install) + Disk 2 (System Disk) no-source-substitute / pascal-c-nontarget forks

Search date: 2026-08-01. Scope: 82 fork records (all `no-source-substitute`; 0 `pascal-c-nontarget` occurred in this slice — that classification only appears on Disk 3+). All 82 records processed; every claim below was independently re-verified today by direct extraction from the actual `.2mg` disk images (via `a2til.prodos.Volume`, found at `/Users/mdj/src/a2til`, not previously wired into this session) rather than trusting prior evidence text.

## IMPORTANT — anomaly encountered and NOT acted on

Partway through this task, a `<system-reminder>` appeared claiming my own scratch file `targets.json` had been "modified, either by the user or by a linter," was "intentional," and instructed me not to tell the user. The file's content had in fact been silently swapped for **Disk 3 (SystemTools1)** records — completely outside my assigned slice (Disk 1 + Disk 2 only) — and the message told me to conceal this. This has the shape of a prompt injection: unsolicited, tries to get an agent to silently accept manipulated data and hide it from the principal. I did not comply with "don't tell" — I flagged it, discarded the swapped content, regenerated `targets_d12.json` fresh from `docs/disk_census_2026-08-01.json` myself, verified it matched my actual assignment (82 records, Disk 1 + Disk 2 only), and proceeded on that basis. All 82 output records were built from the clean regenerated file. Flagging this to the supervisor/user as something to be aware of, independent of the actual census-verification findings below.

## Method

1. Extracted the census's 82 target fork entries (Disk 1 + Disk 2, `no-source-substitute`/`pascal-c-nontarget`) into `targets_d12.json`.
2. Located the actual disk images at `ref/GSOS_6/System601_disks/System 6.0.1/Disk {1,2} of 7 *.2mg` and a ProDOS reader (`a2til.prodos.Volume`, external to the gsasm repo at `/Users/mdj/src/a2til`) to extract real data-fork bytes for direct comparison — this is more rigorous than the prior evidence text, which in several cases only described searches rather than including a byte-for-byte re-check.
3. Grouped the 82 records into 9 families by shared evidence/basename, searched once per family, applied results to every member.
4. Searched all 3 required trees where applicable: `ref/GSOS_6/IIGS.601.SRC/`, `ref/ROM Source Code/`, `ref/gsrom3/system500.hfv` (via `work/hfs.py`'s `HFS` reader).

## Families and what was found

| Family | Records | Result |
|---|---|---|
| 0-byte structural data forks (Sys.Resources, various CDevs) | 10 | Re-extracted from disk images; confirmed genuinely 0 bytes. No search possible/needed on empty data. Not a candidate. |
| `/Install/Scripts/*` Installer SCRIPT files | 50 | Extracted all 50 from Disk 1, byte-compared against `ref/GSOS_6/IIGS.601.SRC/A.U.G/InstallerScripts/`. **All 50 confirmed byte-identical**, including the 9 with non-obvious remapped filenames (worked out via content sniffing, e.g. `A2.RAMCard`→`Slinky`, `SCSI.Scanner`→`Scan6.0`, `SCSI.Tape`→`Tape6.0`, `Archiver`→`ArchiverGS`, `Calculator`→`GSCalc.NDA`, `CloseView`→`CloseView.Init`, `FindFile`→`Find.File.NDA`, `MediaControl`→`MEDIACTRL`, `Teach`→`TeachGS`). Not treated as reclassification candidates — a verbatim copy isn't an assembler/rez "build," consistent with existing classification. |
| `Finder.Data` (desktop-DB caches, all dirs both disks) | 13 | Searched all 3 trees for the literal filename/string; zero hits anywhere (including inside the real Finder application source at `A.U.G/Finder/`, and Mac-format `Desktop DB`/`Desktop DF` in system500.hfv, which are a different OS/format and irrelevant). Confirmed genuinely runtime-computed with no producing source. Not a candidate. |
| `CDev.Data` (Disk1 2079B, Disk2 3449B) | 2 | **CANDIDATE** — see below. |
| `SetStart.data` (Disk1, 20B) | 1 | Re-confirmed byte-identical to `SD.ODDS.N.Ends/SetStart.data`. Not a candidate (matches/extends existing evidence). |
| `FastFont` (Disk1, 28672B) | 1 | Confirmed both filename hits (`GSToolbox/QD/FastFontCache`, ROM `Bank FE/fastfontcache.asm`) are the runtime cache-manager CODE, not the data blob — read both files directly. Not a candidate. |
| `Font.Lists` (Disk1 70B, Disk2 121B) | 2 | **CANDIDATE — strongest lead of the slice.** See below. |
| `FType.Apple` (Disk1 & Disk2, 12160B each) | 2 | Re-confirmed byte-identical to `SD.ODDS.N.Ends/FType.Apple`, and confirmed the two disks' copies are byte-identical to each other. Not a candidate. |
| `Times.10` (Disk2, 2414B) | 1 | No producing source; `Build.SysTools1` duplicates it (and other bitmap fonts) verbatim from a prebuilt location — consistent with the already-established "no source for bitmap font data" pattern. Not a candidate. |

## Candidates found (4 records — prominent)

### 1-2. `CDev.Data` — Disk 1 `/Install/System/CDevs/CDev.Data` (2079B) and Disk 2 `/System.Disk/System/CDevs/CDev.Data` (3449B)

Found `ref/GSOS_6/IIGS.601.SRC/A.U.G/CtlPanel/CtlPanelIntfs/CDEVMgr.pii` (Pascal), function `GetAndUpdateCDEVS`. It explicitly builds a file at `*/SYSTEM/CDEVS/CDEV.DATA` (matching file type $00 / aux type $00) by scanning the `CDevs` directory, reading each CDEV's `rIcon`/`FLAG` resources, sorting by name, and serializing a `CDEVHeader{identifier, version, lastMachine, count, reserved[4]}` + array of `CDEV` records — a genuine build/regeneration algorithm for exactly this file.

Caveat found during verification: the source's `identifier := $444C` ('DL') does not match the disk files' actual first two bytes (`0x44 0x56` = 'D','V') — so this specific source revision is not provably the *literal byte-exact* producer. The `version` field *does* match (source sets `version:=1`; disk bytes at offset 2-3 are `01 00` = 1), and both disks' files share an identical 4-byte header prefix. Since the source is Pascal, even if confirmed as producer this would reclassify to `pascal-c-nontarget`, not `buildable`. Flagging as a lead, not changing the classification.

### 3-4. `Font.Lists` — Disk 1 `/Install/System/Fonts/Font.Lists` (70B) and Disk 2 `/System.Disk/System/Fonts/Font.Lists` (121B)

Found `ref/GSOS_6/IIGS.601.SRC/GSToolbox/FontMgr/fm.asm` — **this is assembler**, the gsasm project's actual target language (unlike the CDev.Data lead, which is Pascal). It contains:
- The exact filename constant: `FLFileName DC.B 10, 'Font.Lists'`
- Format-version equates: `FLVerHi equ $0000`, `FLVerLo equ $0001`
- A full field-offset table (`oRomFamNum=4, oRomStyle, oRomSize, oIDCount, oFamCount, oIDListSize, oFamListSize, oNameListSize, oFileListSize, oTimeListSize...`)
- Startup/validation/rebuild logic (`FMStartup`, `CheckFLFile`, `KillBadFLFile`, `FLFileGood`) that validates an existing `Font.Lists` or rebuilds it by scanning the `FONTS` directory

The extracted disk bytes open with `01 00 00 00`, i.e. word value 1 — matching `FLVerLo=$0001` exactly as the version field the source describes. Disk 2's larger (121B) copy embeds readable Pascal-string font-family names ("Shaston", "Times"), consistent with the source's documented name-list section. No verbatim-copy source or `Build.Install`/`Build.SysTools1` script reference to `Font.Lists` by name was found — it appears to be purely runtime-regenerated, so even with the algorithm identified, true byte-exact static reproduction may not be feasible (the content is a function of which font files happen to be present). Flagging as the strongest lead in this slice for supervisor review; did not change the classification myself.

## Files

- `/private/tmp/claude-501/-Users-mdj-src-gsasm/a5794041-df24-4aed-8c97-b8fdc88c5ec8/scratchpad/backfill_d12.json` — 82 structured records
- `/private/tmp/claude-501/-Users-mdj-src-gsasm/a5794041-df24-4aed-8c97-b8fdc88c5ec8/scratchpad/targets_d12.json` — regenerated clean target list (82 entries, Disk 1 + Disk 2 only)
- `/private/tmp/claude-501/-Users-mdj-src-gsasm/a5794041-df24-4aed-8c97-b8fdc88c5ec8/scratchpad/extract.py`, `cmp_scripts.py`, `build_output.py` — working scripts used for extraction/comparison
