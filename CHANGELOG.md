# Changelog

All notable changes to **gsasm** are recorded here. The format is loosely based
on [Keep a Changelog](https://keepachangelog.com/); this project's version of
"notable" is: which shipping Apple IIgs / GS/OS artifacts now rebuild
**byte-exact** from source, plus toolchain/library changes.

## [Unreleased]

### Harness hygiene (0.6.0 slate item 3 — docs/ARCHITECTURE_REVIEW_2026-08-02.md)

- **The census system is named what it is.** `work/census_migrate.py` →
  `work/censusledger.py`: it was never a one-shot migration (its `OVERRIDES`
  dict was hand-edited six times in its first 36 hours), it is a
  hand-maintained fork-ownership **ledger** plus a **regenerator**. Its
  docstring now documents the actual write API — how to add an `OVERRIDES`
  entry, and that the only supported way to change the census is to change
  the ledger and re-run. The generated census moved from the date-stamped
  `docs/disk_census_2026-08-01.json` to the undated `docs/disk_census.json`;
  the dated files stay committed (the 2026-07-30 one is also the
  regenerator's frozen input, and the 2026-08-01 one is the record of what
  v0.5.0 claimed). No fork's classification changed: the regenerated census
  is byte-identical to the committed one apart from three renamed top-level
  provenance keys.
- **Registry↔census reconciliation is now a standing gate**, not a
  release-eve audit (`work/reconcilecheck.py`, gate metrics
  `ledger_census_regenerable` + `ledger_forks_reconciled`). It runs both
  directions — a builder wired for a fork the census does not call `built`,
  and a census-`built` fork with no builder on a RECONSTRUCTED disk — plus
  diskcheck's Disk-2 `MANIFEST` against the census, and re-proves the
  census is still exactly what the ledger regenerates (so a hand edit to
  `docs/disk_census.json` cannot sit undetected until the next
  regeneration silently reverts it). 181/181 fork claims reconcile today.
- **`manifestcheck.OVERLAID_DISKS` converged on the typed-proof pattern.**
  It was a hand-set literal of seven disk labels enforced only by a comment
  ("do not add a disk here without also adding its physical metric to
  gate.py"); it is now derived from `diskmanifest.overlay_proofs()` — one
  `OverlayProof` per registered, baselined `diskN_physical_exact` metric.
  The derived set is identical to the literal it replaced.

### Corrected (found by the new reconciliation)

- The **prose** fork counts in `README.md` and in the 0.5.0 entry below said
  **178** forks (System Disk 40, Fonts 1); the census, the builder registry
  and `manifest_builders_wired` all say **181** (System Disk 41, Fonts 3).
  The three forks are exactly the ones commit `6f00bf3` wired — Disk 2
  ControlPanel data, Disk 5 Read.Me data, Disk 5 Apple.Bowl rsrc — after
  those two prose passages were written. The machinery has been right since
  2026-08-02; the sentences were stale. Both passages are corrected above
  and in `README.md`. The error understated the work — 0.5.0 built three
  more forks than it claimed — and the v0.5.0 tag is left as published;
  only the prose is fixed. This was an **eighth ledger the architecture
  review did not count: the release prose**, and it is the one that had
  actually diverged.

## [0.5.0] — 2026-08-01

**Tier A: the complete System 6.0.1 seven-disk set reconstructs byte-exact.**
One day, one arc: an adversarial review of the completion machinery in the
morning; every one of its seven findings closed; every remaining wall cracked;
zero unbuilt files by night.

### Completion (the headline)

- **All seven disk images reconstruct physically byte-identical**
  (819,264/819,264 each): Disks 1–6 via the generalized ProDOS overlay,
  Disk 7 (HFS-in-2IMG) via a2til's new allocation-preserving HFS overlay
  engine (a2til issue #9, developed in tandem and merged upstream).
- **Every fork with producing source is wired and logical-exact** — 181
  registry entries across the set (Install 39, System Disk 41, SystemTools1
  38, SystemTools2 52, Fonts 3, synthLAB 2, Apple II Setup 6). Zero
  residuals: the census classifies no file as buildable-but-unbuilt.
  *(Corrected in 0.5.5: this entry as published said 178 / System Disk 40 /
  Fonts 1. The number was stale, not the work — 0.5.0 did ship all 181.)*
- **`work/manifestcheck.py --tier-a` passes** on all six machine-checked
  conditions (inventory 7/7, substitutes confirmed AND structured with
  dated search evidence, builders wired/exact with typed proofs, physical
  7/7, no unaccepted technical exceptions).

### Byte-exact reproduction (new since 0.4.0)

- **Tool.Setup** (19,232 B, Disks 1+2) — the last TECHNICAL_EXCEPTION;
  the "case-B wall" was stale, the residual was recipe drift.
- **IWEM** (29,185 B, Disk 4) — the ImageWriter-Emulator PostScript proc
  set, rebuilt by replaying the MPW `BuildIWEm` text-squeeze script.
- **Adv.Disk.Util** resource fork (8,037 B) — the census's final
  TODO_BUILDABLE.
- **The SCSI family** — SCSI.Manager, SCSIHD/CD/Scan/Tape drivers — plus
  **ImageWriter, ImageWriter.LQ, StyleWriter, Epson, ATP1.ATROM,
  AppleShare.FST, VideoKeyboard, CloseView, LaserWriter** full ExpressLoad
  files (previously only their de-ExpressLoad'd code images were proven).
- Four literal-text data forks (Read.Me/Shortcuts/Whats.New/Fonts Read.Me,
  30,520 B) gated 1:1 against their tracked sources.

### Toolchain (three linker discoveries, each corpus-free-guarded)

- **Exported-EQU symbol kinds** (`linkiigs.SymTab.kinds`): reloc
  suppression for link-time constants now uses the assembler's structural
  GEQU-vs-GLOBAL signal at per-object precedence, replacing a value-range
  proxy that misfired on small constants (spurious SUPER/cRELOC records).
- **Constant-shift resolution**: `#const>>16`-style shifts over exported
  EQUs resolve at link time in the ExpressLoad single path (the SCSI
  "badmin bug" that turned out never to exist).
- **MPW module scoping**: a plain interior label is module-local — a
  by-name reference binds the program-wide EXPORT even from a sibling
  module of the same object; ENTRYs, unexported names, and segment names
  are exempt (the TS2 private-wins shapes hold).
- `expressload()` gains `opts['segname']` (a load segment's name is
  byte-load-bearing: header + directory `entry_len`).

### Verification machinery (the adversarial-review response)

- Typed builder proofs (CallableProof/HarnessProof) replace label counts;
  fork-granular census with machine-regenerated migration; physical
  byte-match hard-gated per disk with enforced exit codes; technical-
  exception acceptance markers; dated structured substitute-search
  evidence (247 records re-searched); `--tier-a` completion command.
- HFS access (read + overlay write) moved upstream to a2til
  (`a2til.hfs.HfsVolume`); gsasm's vendored copy deleted.

## [0.4.0] — 2026-07-30

Coverage beyond the System Disk, an internals refactor, and a Python-floor bump.

### Byte-exact reproduction (new since 0.3.0)

- **`BASIC.System`** — the ProDOS 8 command interpreter (disk 38→39; the last
  out-of-scope file on the System Disk retired).
- **Toolbox toolsets: 14/14** (193,357 B) — NoteSeq (Tool026) and VideoMix
  (Tool033) close the corpus.
- **Control-Panel CDEVs/NDAs: 19/19** resource forks (156,917 B) — adds
  MediaControl and MIDI.
- **The Finder** — both forks byte-exact: the 52,395 B resource fork and the
  146,924 B data fork (the largest program in System 6.0.1, ExpressLoad'd with
  its relocation dictionaries). Ships twice byte-identical — as the Disk-3
  `Finder` and as the System-Disk boot program `Start`.
- **Installer** (17,895 B) and **Teach** (7,333 B) resource forks.
- **MountImageGS** NDA data fork (5,750 B), four A.U.G data forks (29,019 B:
  CDRemote / Pioneer2000 / EasyAccess / Pioneer4200), and five more resource
  forks (4,515 B: FindFile, Apple.Bowl, MediaControl & VideoMix NDAs,
  Pioneer4200).
- **Whole System Disk**: `diskcheck` logical-exact 39/39, physical image
  byte-match 819,264/819,264. (The one remaining full-file ExpressLoad residual
  is `Tool.Setup` — code image byte-exact, its relocation encoding blocked on
  the case-B converter wall; deliberately left unwired.)

### Changed

- **Refactor (R9):** `expressload()` decomposed into a thin dispatcher plus
  `_build_single_output_seg()` and `_build_multiseg_output()`. Zero-drift —
  verified gate-stdout and ROM byte-identical.
- **Python floor raised to 3.10** (`requires-python = ">=3.10"`); 3.9 reached
  end-of-life in Oct 2025.
- Documentation accuracy pass across README / RESULTS / GSOS_MILESTONES.

### Packaging

- Source distribution no longer bundles reference disk images or PDFs (`tmp/`,
  `Users/` excluded); only project source ships. The clean-room `TypesIIGS.r`
  Rez include continues to ship in the wheel, so `gsrez` works out of the box.

## [0.3.0] — 2026-07-19

- **The whole System 6.0.1 System Disk rebuilds byte-exact.** GS.OS SCM
  (38,805/38,805), P8 (17,128/17,128), the mapped tools, drivers, and FSTs, plus
  the Rez-compiled resource forks (Sys.Resources, EasyMount, all CDEVs). First
  release to ship the clean-room `TypesIIGS.r` include in the package.

## [0.2.0] — 2026-07-15

- Initial public release: clean-room Python reimplementation of the MPW IIgs
  cross-development toolchain (AsmIIgs / LinkIIgs / RezIIgs and the
  MakeBin/Overlay/ExpressLoad packagers), validated byte-for-byte against the
  IIgs ROM 03 and GS/OS 6.0.1 shipping binaries.

[0.4.0]: https://github.com/emdeejay/gsasm/releases/tag/v0.4.0
[0.3.0]: https://github.com/emdeejay/gsasm/releases/tag/v0.3.0
[0.2.0]: https://github.com/emdeejay/gsasm/releases/tag/v0.2.0
