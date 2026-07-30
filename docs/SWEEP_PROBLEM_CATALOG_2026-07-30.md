# Breadth-first build sweep — problem catalog (2026-07-30)

Source: workflow `wf_475b7ce0-62e` (7 agents, one per builder-type) attempted a
real build of every one of the 58 buildable files, cmp'd against the golden fork
on-disk, and tagged each `exact` / `diff` / `error` / `blocked` with a failure
signature. This collates the failures by shared root cause. Raw per-file data:
the workflow journal + `docs/disk_census_2026-07-30.json`.

**Headline:** 12 immediate byte-exact wins; the ~46 failures collapse into ~9
root-cause clusters; **~5 shared fixes unblock ~28 files**.

## Immediate byte-exact wins (12 — wire straight in, no new work)

- **drivers (7):** A2.RAMCard (Slinky), Modem, Parallel.Card, Printer, AppleTalk
  (printer driver, distinct from GS.OS ATalk), Apple.Midi, Card6850.MIDI
- **CDEVs (3):** Printer, Slots, Time
- **toolset (1):** Tool025 (NoteSynth)
- **boot (1):** p8

## Problem clusters, ranked by leverage

| # | Root cause | N | Files | Fix character |
|---|-----------|--:|-------|---------------|
| **R1** | Rez parser lacks the `data <type>(<id>){ $"hex" }` statement (verbatim raw-hex resource) | 14 | 10 Sounds (Ahh…Whoosh minus Frog/Whoosh) + Read.Me, Shortcuts, Whats.New, Read.Me(D5) | one parser feature |
| **R2** | Rez `rSoundSample` template undefined in the bundled `TypesIIGS.r` | 2 | Frog, Whoosh | one template + gen support |
| **L1** | Selective / multi-segment link: MPW `obj(ENTRY,…)` module dead-strip + `-lseg:Dynamic` groups not modeled | ~4 | Tool032, Tool035, LaserWriter, ControlPanel | extends the proven TS2/TS3 `_part` filter-select mechanism |
| **E1** | ExpressLoad packaging differs though the code image is byte-exact (wrapper/header/reloc-dict) | 5 | ATInit, ATResponder, QuickLogoff, Start(D1 SetStart launcher), Tool038 | extends the proven E-series ExpressLoad reloc work |
| **A1** | Same-length absolute-address drift: a few cross-segment operands resolve to different addresses (link segment-order / base assignment) | 3 | ATP1.ATROM (2B — cleanest, one 24-bit table entry), ATP2.ATRAM (16B), StyleWriter (41B) | linker base-assignment |
| **A2** | ±1–2 byte length drift from operand-width / addressing-mode choice (DP vs abs, short vs long branch, dc.b) | 2 | Epson (+2), AppleCDSC (−1) | assembler width selection |
| **A3** | IW/LQ imaging driver 192 bytes short — a shared imaging data table (imagerdata dither/RGB) under-emitted | 2 | ImageWriter, ImageWriter.LQ | one data-emission bug (shared source) |
| **M1** | Macro loop directives (WHILE/SETA/ELSEIF) under-expand recursive DC.W decode tables | 1 | Tool029 (ACE) | macro-engine feature |
| **?** | Small localized code diffs — need per-file diagnosis | 3 | CloseView, VideoKeyboard, AppleIIVOC | individual |

## Wrong builder class → SUBSTITUTE or dedicated (tiny) builder (4)

- **IWEM** — golden is ASCII PostScript (`%!PS-Adobe-2.0 … BeginProcSet "IWEM"`,
  type `$04`), produced by `BuildIWEm` stripping comments/whitespace from
  `IWEm.Src`. Not an assembler/linker product. (A ~20-line text-strip builder, or
  SUBSTITUTE.)
- **ProDOS16 Image** (Disk 7) — 92,672 B emitted by the `MakeImage` C host tool
  wrapping components (fizzy/stub/p8/BootLog16/atrom/atram/ETBoot) in a
  proprietary net-boot container. Needs the C tool or a port. (SUBSTITUTE or P5.)
- **Apple II Script** (Disk 7) — Mac Installer Rez dialect (`#include "Types.r"`,
  `"InstallerTypes.r"` — templates absent). Not IIgs Rez. (SUBSTITUTE.)
- **Installer** (Disk 1) — missing link library + static relocs. Needs the
  Installer link lib wired (or SUBSTITUTE).

Note also **//e Boot Blocks** and **ProDOS16 Boot Blocks** (Disk 7): code
(Reloc+P8) is exact, but the net-boot multi-segment LinkIIGS+MakeBinIIGS
relocation/placement isn't modeled — same L1 theme, net-boot flavor. Land with
Disk 7 (P5, needs the HFS writer too).

## Recommended attack order (leverage-first)

1. **R1 + R2 — Rez `data` statement + `rSoundSample` template** → ~16 files in
   one session (the entire sound + text-rez batch). Cleanest, highest leverage.
2. **L1 + E1 — selective/multi-segment link + ExpressLoad packaging** → ~9 files,
   and both are *extensions of already-solved techniques* (TS2/TS3 `_part`;
   E-series reloc), not new research. The multi-segment theme recurs across
   drivers/tools/CDEVs/netboot — one high-value investment.
3. **A1 → A2 → A3 → M1 → localized** — the ~11-file long tail of individual
   linker/assembler drift bugs. ATP1 (one datum) and A3 (one shared table) are
   the cleanest first cuts; each is a normal CRACK task with a corpus-free
   fixture.
4. **Reclassify the 4 host-tool/wrong-class files** as `SUBSTITUTE` (or build the
   tiny text-strip / C-tool wrappers) after a source-search confirms no
   assembler/Rez path.

Wiring the 12 exact wins + the R1/R2/L1/E1 clusters (~37 files) would take
`builders_wired`/`exact` from 37 toward ~90 and land Disks 3 (SystemTools1) and
much of 4 (SystemTools2).
