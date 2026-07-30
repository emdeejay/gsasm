# Changelog

All notable changes to **gsasm** are recorded here. The format is loosely based
on [Keep a Changelog](https://keepachangelog.com/); this project's version of
"notable" is: which shipping Apple IIgs / GS/OS artifacts now rebuild
**byte-exact** from source, plus toolchain/library changes.

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
