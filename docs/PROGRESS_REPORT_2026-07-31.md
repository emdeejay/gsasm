# gsasm — progress report, 2026-07-31

*Session arc: released 0.4.0 → hardened the completion SOW against two Codex
reviews → built the P0 completion scoreboard → mapped the whole opportunity
space breadth-first → sent a junior-dev crew to smash out the wins and the two
highest-leverage fix-clusters. Every number below is gate-verified against the
real shipping binaries.*

## TL;DR

- **v0.4.0 shipped** to PyPI (whole System Disk byte-exact + coverage beyond it).
- The remaining reproduction terrain is **mapped, not guessed**: an evidence-based
  census of all 7 disks (355 files, 0 unknown) + a breadth-first build sweep that
  clustered 46 failures into ~9 root causes.
- A **P0 scoreboard** now measures *builder-correctness*, not golden-carry — so
  "done" can't be faked.
- A **serialized, gate-gated junior-dev crew** landed **~31 new files byte-exact
  (~230 KB)** in one run, closing the two highest-leverage clusters — **with zero
  regressions and two honest residuals.**

## What landed this session (all gate-green)

| Metric | Before | After | What |
|---|--:|--:|---|
| `driver_bytes` | 94,948 | **143,374** | +8 drivers (7 sweep-proven + LaserWriter) → 20/20 |
| `tool_bytes` | 193,357 | **239,810** | +Tool025, Tool032, Tool035 → 17 tools |
| `rez_data_bytes_exact` | — | **107,839** | **new** — 14 template-free forks (10 Sounds + 4 TeachText docs) |
| `rezfork_bytes_exact` | 4,515 | **21,170** | +Frog, Whoosh (new `rSoundSample` template) |
| `expressload_sys601_bytes_exact` | — | **10,526** | **new** — Start, QuickLogoff, Tool038 |

**~31 files newly reproduced byte-exact**, and the whole commit stack
(`d81d3e5..bd5ebc9`) passes `gate.py --full` with every pre-existing metric
unchanged (`bad=0` throughout).

### The genuinely new engineering (not just plumbing)
- **Rez `data` statement** — `data <type>(<id>[,<attrs>]) { $"hex" }` end to end
  (parser → gen → emit), the verbatim-hex resource form. One feature, 14 files.
- **`rSoundSample` template** — derived from byte pairs, added to the clean-room
  `TypesIIGS.r`. Two more Sounds.
- **`objsel` selective link** — reproduces MPW's `object(SYM,…)` per-object
  dead-strip + `-lseg:Dynamic` segments (extends the proven TS2/TS3 `_part`
  mechanism). Tool032, Tool035, LaserWriter, ControlPanel — all byte-exact.
- **ExpressLoad wrapper details** — LOADNAME padding, null reloc pointer,
  net-zero same-segment label diffs. Start, QuickLogoff, Tool038.
- New corpus-free fixtures where new behavior landed (e.g. `test_rez_data_stmt`).

### A moment of taste worth calling out
The `wire-cdevs` stage was told to wire Printer/Slots/Time CDEVs. It found they
were **already** byte-exact and that the Disk-3 copies are byte-identical to the
already-gated Disk-2 copies — so wiring them would **double-count** for zero new
coverage. It **refused, and reported why.** That's the discipline this project
runs on: the metric must mean something.

## Honest residuals (2)
- **ATResponder** — code image byte-exact; the whole file is 8 bytes short of
  gold (an ExpressLoad wrapper detail). Small, tractable.
- **ATInit** — *not* an ExpressLoad file at all (134 B flat binary). Wrong
  builder class → a tiny dedicated builder or SUBSTITUTE.

## The map (breadth-first sweep) — what's left, and how hard

The sweep attempted a real build of all 58 buildable files. After this crew, the
remaining problems, ranked:

- **Long-tail assembler/linker drift (~8):** A1 same-length address drift
  (ATP1.ATROM 2B — cleanest, ATP2.ATRAM, StyleWriter), A2 operand-width (Epson,
  AppleCDSC), A3 IW/LQ 192-byte shared table, M1 macro-loop expansion (Tool029).
  Each a normal CRACK task with a fixture.
- **Localized (3):** CloseView, VideoKeyboard, AppleIIVOC — per-file diagnosis.
- **Wrong builder class → SUBSTITUTE / tiny builder (4):** IWEM (PostScript
  text-strip), ProDOS16 Image (MakeImage C tool), Apple II Script (Mac Rez),
  Installer (link lib).
- **Disk 7 (HFS net-boot):** boot blocks + ProDOS16 image, gated behind the HFS
  overlay writer (P0d-2 / P5).

## One caveat, stated plainly

The P0 **manifest scoreboard** (`manifest_builders_wired 37/162`) has **not**
moved yet, even though ~31 artifacts are now gate-proven. That's by design: the
scoreboard reads only `diskcheck`'s Disk-2 registry; the new artifacts are proven
by `drivercheck`/`toolcheck`/the Rez harnesses, not yet wired into the *per-disk
overlay*. Making the scoreboard reflect them (and thus climb toward 162) is the
mechanical **P2** follow-up — the builders exist and are proven; they just need
registering per disk.

## State
- 7 local commits ahead of Forgejo (`b3692f7..bd5ebc9`). **Not pushed — Forgejo
  was unreachable all session** (`forgejo.cornflower.au:443` timing out); GitHub
  mirror push stays disabled. Everything is committed and gate-green locally;
  `git push origin main` when the server is back.

## Recommended next moves
1. **P2 manifest wiring** — register the ~31 new (and the 104 census-`built`)
   artifacts per disk so the scoreboard climbs to reflect reality.
2. **Long-tail CRACK** — ATP1 and the IW/LQ table are the cleanest first cuts.
3. **Reclassify the 4 host-tool files** as SUBSTITUTE (source-search first).
4. **Disk 7** — the HFS overlay writer (P0d-2), then its boot infra.

---
*Filed from the terminal, as requested. The gate never lied to us once.*
