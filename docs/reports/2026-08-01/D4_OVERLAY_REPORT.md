# Disk 4 (SystemTools2) overlay wiring — the LAST disk — physical 7/7

## Status

**COMPLETE and committed by the supervisor** (commit `a58c1d6`, "Disk 4
RECONSTRUCTED — manifest_physical_exact 7/7, TIER-A PASS"), independently
re-verified by them: `47/47 logical`, `819264/819264 physical`, `rc=0`. The
gate baseline was updated by the supervisor and matches the prediction below
exactly. This report captures the work as I did it, for the record.

## Summary

Wired `DISK_BUILDER_REGISTRY['Disk 4 of 7 SystemTools2.2mg']` in
`work/diskcheck.py`, covering **47 of the census's 52 'built' forks**
(fork-granular count — see Census reconciliation below). Added the
`('diskcheck4', ...)` entry to `work/gate.py` FULL_CHECKS and `'Disk 4'` to
`work/manifestcheck.OVERLAID_DISKS`.

`python3 work/diskcheck.py --disk 'Disk 4 of 7 SystemTools2.2mg'` exits 0:
```
Disk 4 of 7 SystemTools2.2mg: SystemTools2  1600 blocks
  builders wired: 47  logical-exact: 47/47
  PHYSICAL image byte-match: 819264/819264 (100%)
```

5 forks are documented residuals, left OUT of the registry (not
force-wired) — see Residuals below.

## Census reconciliation (no edits made, none needed)

`docs/disk_census_2026-08-01.json`'s Disk 4 entry has a stale summary note
("built 14, buildable-asm 15, buildable-rez 15...") from an earlier revision;
the actual per-fork data is current. Scanning every file's `forks` dict for
`classification == 'built'` (not the file-level `classification`, which for
3 files lags behind — see below) gives **52** built forks, matching
`manifestcheck.py --tier-a`'s own count (`SystemTools2 ... BUILT=52/52
exact=52`).

Two known file/fork-level classification mismatches, both intentional (not
edited, per the task's "no census edits should be needed" directive):
- `/SystemTools2/System/Drivers/IWEM`: file-level `classification` is still
  `no-source-substitute` (the old verify-negative text), but its `data` fork
  sub-object was updated to `classification: built, proven_by: iwemcheck`
  after the 2026-08-01 IWEM crack (commit `5fc64fd`). The fork-level field is
  authoritative (same pattern this registry has always used: `fork` in the
  registry tuple is "the ACTUAL on-disk fork the builder targets ...
  independent of the census's file-granular label").
- `Desk.Accs/MediaControl`, `Desk.Accs/VideoMix`, `Teach`: file-level
  `classification` is `pascal-c-nontarget` (their DATA fork is a genuine
  Pascal/C wall, `no-source-substitute`), but each file's `rsrc` fork is
  independently `built` (rezforkcheck / teachcheck). Wired those 3 rsrc forks
  as targets exactly as the task specified.

52 = 49 (task's estimate) + these 3 pascal-c-nontarget rsrc forks — accounts
for the task's "~49" figure precisely.

## Probe-first methodology

Before touching `diskcheck.py`, I wrote a standalone probe
(`/private/tmp/.../scratchpad/d4_probe.py`) that built every one of the 52
candidate forks with its harness/generic-recipe callable and compared against
the actual on-disk Disk-4 fork (not the harnesses' own code-image gate, which
for several targets — drivers, FSTs — proves a narrower DE-ExpressLoad'd
surface than the whole-file overlay needs). Result: **47 PASS, 5 FAIL**. Only
passing builders were wired into the registry — the discipline this whole
First-Disks phase has followed since Disk 1.

## Registry table (path → builder source)

| Disk 4 path | fork | Builder source | Reuse? |
|---|---|---|---|
| `/SystemTools2/AppleTalk/Boot.Driver` | data | generic `_build_driver_fullfile('Boot.Driver')` (drivercheck DRIVERMAP, single-object) | new (thin factory call) |
| `/SystemTools2/System/Drivers/SCC.Manager` | data | `_build_driver_fullfile('SCC.Manager')` (single-object) | new |
| `/SystemTools2/System/Drivers/AppleTalk` | data | `_build_driver_fullfile('AppleTalk')` (2-object, PRINTER driver) | new |
| `/SystemTools2/System/Drivers/ATP2.ATRAM` | data | `_build_driver_fullfile('ATP2.ATRAM')` (18-object merge, byte-exact) | new |
| `/SystemTools2/System/Drivers/ATalk` | data | `_build_driver_fullfile('ATalk')` (4-object) | new |
| `/SystemTools2/System/Drivers/Media.Control/AppleCDSC` | data | `_build_driver_fullfile('AppleCDSC')` (single-object) | new |
| `/SystemTools2/System/System.Setup/AppleIIVOC` | data | `_build_driver_fullfile('AppleIIVOC')` (single-object) | new |
| `/SystemTools2/System/Drivers/IWEM` | data | new `_build_iwem_d4()` → `iwemcheck.build_iwem_disk4()` (BuildIWEm PostScript text-squeeze replay, cracked 2026-08-01) | new |
| `/SystemTools2/AppleTalk/QuickLogoff` | data | new `_build_quicklogoff()` → `expressloadcheck.build_quicklogoff()` | new (thin wrapper) |
| `/SystemTools2/System/Tools/Tool038` | data | new `_build_tool038()` → `expressloadcheck.build_tool038()` | new |
| `/SystemTools2/System/System.Setup/ATInit` | data | new `_build_atinit()` → `expressloadcheck.build_atinit()` | new |
| `/SystemTools2/System/System.Setup/ATResponder` | data | new `_build_atresponder()` → `expressloadcheck.build_atresponder()` | new |
| `/SystemTools2/AppleTalk/Start` | data | new `_build_net_start()` → `expressloadcheck.build_net_start()` (4-object AppleTalk net-boot Start) | new |
| `/SystemTools2/System/CDevs/{AppleShare,FolderPriv,MediaControl,Namer,NetPrinter,Network}` | rsrc | existing generic `_build_cdev(name)` factory (Disk 1/3 already use it) | reused factory |
| `/SystemTools2/System/Desk.Accs/MediaControl` | rsrc | new `_build_rezforkcheck('MediaControl')` factory → `rezforkcheck.build_rez_fork` | new factory |
| `/SystemTools2/System/Desk.Accs/VideoMix` | rsrc | `_build_rezforkcheck('VideoMix')` | reused factory |
| `/SystemTools2/System/Drivers/Media.Control/Pioneer2000` | data | new `_build_appdatacheck('Pioneer2000')` factory → `appdatacheck.build_app_data` | new factory |
| `/SystemTools2/System/Drivers/Media.Control/Pioneer4200` | data + rsrc (dual) | `_build_appdatacheck('Pioneer4200')` (plainload) + `_build_rezforkcheck('Pioneer4200')` | reused factories |
| `/SystemTools2/System/System.Setup/EasyAccess` | data | `_build_appdatacheck('EasyAccess')` | reused factory |
| `/SystemTools2/System/System.Setup/EasyMount` | data + rsrc (dual) | **reuse** Disk-2's `SOURCE_BUILDERS[.../EasyMount]` + `REZ_BUILDERS[.../EasyMount]` directly (cmp-anchored duplicate; confirmed against Disk 4's own on-disk forks, not merely asserted) | reused (Disk 2) |
| `/SystemTools2/System/Tools/Tool033` | data | existing generic `_build_tool_flat_fullfile('033')` (Disk 3's Tool026/029 pattern) | reused factory |
| `/SystemTools2/System/Sounds/{Ahh,Doorbell,Droplet,Eastern,PipeOrgan,Quack,SimpleBeep,Sosumi,Swish,Trumpets}` (10) | rsrc | new `_build_rezdatacheck(name)` factory → `rezdatacheck.build_rez_fork` | new factory |
| `/SystemTools2/System/Sounds/{Frog,Whoosh}` (2) | rsrc | `_build_rezforkcheck(name)` (rSoundSample template, not template-free `data`) | reused factory |
| `/SystemTools2/Teach` | rsrc | new `_build_teach_rsrc()` → `teachcheck.build_teach_fork()` | new |
| `/SystemTools2/{Read.Me,Shortcuts,Whats.New}` | data + rsrc (dual, 3×) | data: new `_build_text_source(relpath)` factory (verbatim tracked-source read, mirrors `textdatacheck.py`'s own comparison — no build step); rsrc: `_build_rezdatacheck(name)` | new factory + reused factory |

47 registry entries covering 47 forks (42 distinct paths; 5 dual-fork:
Pioneer4200, EasyMount, Read.Me, Shortcuts, Whats.New).

## Residuals: 5 forks left OUT (documented, not force-wired)

All 5 are variations of the SAME already-diagnosed family from Disk 1/3
(`SCSI_RELOC_DIAGNOSIS.md`, now formally written up in
`docs/SCSI_RELOC_DIAGNOSIS_2026-08-01.md` per the supervisor's follow-on
commit): `linkiigs._build_symtab` discards the assembler's GEQU-vs-GLOBAL
symbol-kind distinction, so the exported-EQU numeric-range heuristic
misclassifies some labels in multi-object ExpressLoad merges, producing a
spurious/missing SUPER reloc that only shows up in the wrapped full-file
surface (never in the DE-ExpressLoad'd code image the harnesses gate).

- **VideoKeyboard** (5-object merge): built 17498B vs gold 17516B (+18B).
  First byte (offset 0) already differs — the directory/reloc-dict size
  disagreement cascades through the whole file. Same family as Disk 1's
  SCSIHD.Driver (+8B) / Disk 3's 8 driver residuals.
- **ATP1.ATROM** (3-object merge): SAME length as gold (11080B) but 2 bytes
  differ at offset `0x144` — `0x0e56` (built) vs `0x0e95` (gold), inside a
  directory forward-pointer field. Confirms the bug is not simply
  length-correlated; smaller merges (2-4 objects) can still trigger it while
  larger ones (ATP2.ATRAM, 18 objects; ATalk, 4 objects) came out clean.
- **LaserWriter**: a genuinely *new* gap, not the reloc-weight class above.
  Its DRIVERMAP entry is a 2-load-segment jt_segments driver (MAIN 0x0000 +
  PREPFILE 0x8000, like Tool015/016/018).
  `drivercheck._link_jt_driver`/`toolcheck._link_jt_tool` only ever produce
  the CONCATENATED CODE IMAGE (36644B, what `de_express(gold)` compares) —
  there is no jt-aware FULL ExpressLoad-file packager (directory +
  per-segment reloc dicts + `~JumpTable`) anywhere in the codebase, so the
  39779B on-disk file could not be attempted at all.
- **CloseView**: same packaging gap as LaserWriter.
  `expressloadcheck.build_closeview_code()` is explicitly documented
  CODE-IMAGE-ONLY (2-lseg INIT+NDA, no wrapper modeled); built 33091B vs the
  35652B on-disk file.
- **AppleShare.FST**: the census's own notes flagged this exact file as the
  likely SCSI-class example, and the probe confirms it — a 25-object merge
  (24 modules + JudgeName, `fstcheck._build_appleshare`'s object list wrapped
  in `expressload()` instead of `linkiigs.link(merge=True)`). Built 19950B
  vs gold 19948B (+2B), first diff at `0x64`, inside the `~ExpressLoad`
  directory — same signature as the SCSI/printer-driver residuals.

All 5 stay on disk as their original untouched bytes; physical image match is
unaffected. Per the task's explicit instruction, the underlying `sym_kind`
library fix was **not** attempted here — that's the next packet (per the
supervisor's follow-on commit, the diagnosis is written up and the fix
approach is scoped but deliberately deferred: a naive flat-set fix regresses
TS2).

## Predicted vs actual

| Metric | Predicted | Actual |
|---|---|---|
| `disk4_logical_exact` | NEW `[47, 0]` (after the 5-residual probe, not the task's illustrative `~49`) | `[47, 0]` ✓ |
| `disk4_physical_exact` | NEW `[819264, 0]` | `[819264, 0]` ✓ |
| `manifest_physical_exact` | good 6 → 7, bad 1 → 0 | `[7, 0]` ✓ |
| everything else | unchanged | unchanged (confirmed by the `--full` run: every prior metric printed `(baseline good=X bad=Y)` matching exactly — objcheck 40/21, linkcheck 61/0, kernelcheck 59049/0, fstcheck 111584/0, drivercheck 310555/0, toolcheck 249342/0, iwemcheck 29185/0, textdatacheck 30520/0, bytecheck 97202/0 opcode + 62714/745 operand, cdevcheck 156917/0, findercheck 104790/0, teachcheck 7333/0, appdatacheck 44129/0, etc. — no unpredicted movement anywhere) |

`python3 work/diskcheck.py --disk 'Disk 4 of 7 SystemTools2.2mg'` exits 0
(47/47 logical, 819264/819264 physical, 100%). `python3 work/gate.py --full`
(run before the coordinator's stop instruction landed) showed only the
predicted movement; the supervisor independently re-ran and confirmed
`rc=0`, then updated `work/gate_baseline.json` and committed
(`a58c1d6`) — `git diff work/gate_baseline.json` shows no outstanding delta
now (already committed).

## `manifestcheck.py --tier-a` verdict (post-Disk-4, physical now 7/7)

```
=== 7-disk completion scoreboard (manifestcheck P0, fork-granular) ===
  Install              BUILT= 39/ 39 exact= 39 SUB= 64 TECH=0 [RECONSTRUCTED]
  System Disk          BUILT= 41/ 41 exact= 41 SUB= 18 TECH=0 [RECONSTRUCTED]
  SystemTools1         BUILT= 38/ 38 exact= 38 SUB= 52 TECH=0 [RECONSTRUCTED]
  SystemTools2         BUILT= 52/ 52 exact= 52 SUB= 37 TECH=0 [RECONSTRUCTED]
  Fonts                BUILT=  3/  3 exact=  3 SUB= 29 TECH=0 [RECONSTRUCTED]
  synthLAB             BUILT=  2/  2 exact=  2 SUB= 25 TECH=0 [RECONSTRUCTED]
  Apple II Setup       BUILT=  6/  6 exact=  6 SUB= 18 TECH=0 [RECONSTRUCTED]

  manifest_inventory_classified good=7 bad=0
  manifest_substitutes_confirmed good=243 bad=0
  manifest_substitutes_structured good=243 bad=0
  manifest_builders_wired 181/181
  manifest_builders_exact 181/181
  manifest_physical_exact good=7 bad=0
  manifest_technical_exceptions_accepted good=0 bad=0

=== Tier-A completion verdict ===
  [PASS] inventory 7/7
  [PASS] substitutes_confirmed bad=0
  [PASS] builders_wired bad=0
  [PASS] builders_exact bad=0
  [PASS] physical_exact good=7
  [PASS] technical exceptions all accepted
TIER-A PASS
```

(Pre-Disk-4 baseline for comparison, captured before this packet:
`manifest_physical_exact good=6 bad=1`, `SystemTools2 ... [builder-complete
(needs overlay)]`, `TIER-A FAIL` on `physical_exact good=6`. All 7 disks are
now `[RECONSTRUCTED]` — Tier A is fully closed at the physical-overlay
level; nothing further separates the project from Tier A on this axis.)

## Files touched (all under `work/`, none under `gsasm/`, no census edits)

- `work/diskcheck.py` — 13 new lazy-import wrapper/factory functions
  (`_build_rezforkcheck`, `_build_appdatacheck`, `_build_rezdatacheck`,
  `_build_teach_rsrc`, `_build_text_source`, `_build_iwem_d4`,
  `_build_quicklogoff`, `_build_tool038`, `_build_atinit`,
  `_build_atresponder`, `_build_net_start`, plus reuse of the existing
  `_build_driver_fullfile`/`_build_cdev`/`_build_tool_flat_fullfile`
  factories) and the Disk 4 registry entry (47 forks, 3 dual-fork lists).
- `work/gate.py` — new `diskcheck4` FULL_CHECKS entry.
- `work/manifestcheck.py` — `'Disk 4'` added to `OVERLAID_DISKS`.
- `work/gate_baseline.json` — updated and committed by the supervisor
  (`a58c1d6`); matches this packet's prediction exactly.

All of the above is already committed to `main` (`a58c1d6`, plus a
follow-on docs commit `90bc674` preserving the reloc diagnosis for the next
packet). No outstanding working-tree changes from this task.
