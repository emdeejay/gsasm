# gsasm — Implementation Plan (execution of the Completion SOW)

> Companion to `docs/SOW_COMPLETION.md`. The SOW defines *what* Complete is and
> the phase outline; this is the concrete *how*, grounded in the evidence-based
> census (`docs/disk_census_2026-07-30.json`). Tier A+C, supervised-workflow
> autonomy. Draft 2026-07-30.

## 0. The shape of the remaining work

From the census (355 files, 7 disks, 0 unknown):

- **105 built** — already byte-exact; P2 wires them into per-disk manifests.
- **59 buildable** — the real reproduction work, and **~42 reuse a proven
  builder pattern** (see §3). Only ~17 are genuinely new (Disk-7 boot infra,
  AppleTalk setup, `Tool.Setup` case-B).
- **183 no-source substitute** + **8 Pascal/C non-target** — declared verbatim
  with cited reasons; compatible with 100% physical (Disk 2 already: 12 subs in
  a 100% image).

Completion predicate (machine-checkable): `gate.py` green **and**
`disk_physical_exact == 7/7` with `oos == 0` on every disk.

## 1. P0 — the manifest system + gate metric + HFS path

**1a. Per-disk manifest.** Generalize `diskcheck`'s implicit Disk-2 registry
(`SOURCE_BUILDERS`/`REZ_BUILDERS`, keyed by `/System.Disk/...`) into
`work/diskmanifest/` — one module per disk exposing

```python
def manifest(V) -> dict[str, Entry]   # Entry = BUILD(fn) | SUBSTITUTE(reason)
```

Seed each manifest **from the census JSON** (mechanical): `built`/`buildable` →
`BUILD(builder)`; `no-source-substitute`/`pascal-c-nontarget` →
`SUBSTITUTE(evidence)`. Every file gets an entry → `oos == 0` by construction.

**1b. `diskcheck.check(disk)`** already takes `disk_path` and overlays+matches;
change it to read `manifest(V)` for that disk instead of the global dicts. A
`SUBSTITUTE` entry means "carry the golden bytes verbatim" (exactly today's
Disk-2 behavior for its 12 subs). Disk 2 must stay 100% after the refactor
(regression guard).

**1c. Gate metric `disk_physical_exact`** — fractional over the 7 disks
(physical byte-match == 100%). Starts **1/7** (Disk 2). Add a companion
`disk_files_classified` (built+substitute == total, i.e. `oos:0`) so a disk can
report "fully accounted for" before it is "fully physical."

**1d. HFS overlay path (Disk 7).** Disk 7 is an HFS volume inside a ProDOS-order
2IMG (census A.2). `check()` uses the ProDOS `Volume`; add `check_hfs(disk)`
using `work/hfs.py` (read → rebuild the HFS B-tree/allocation → overlay built
forks → physical-match). This is the one new filesystem path.

**P0 acceptance:** gate green; `disk_physical_exact 1/7`; Disk 2 still 100%;
manifests generated for all 7 disks with 0 `oos`.

## 2. P2 — wire the 105 built files

Mechanical. Most "built" files on Disks 1/3/4 are **the same artifact already
built for Disk 2** (census cmp-verified identical, e.g. Disk-1 `ProDOS`, `GS.OS`,
`Start.GS.OS`, `Error.Msg`, the FSTs and drivers, TS2/TS3, `Resource.Mgr`,
`Sys.Resources`, the CDEV forks). Wiring = register the existing builder under
the Disk-N path key. The Finder (Disk 3) reuses `findercheck`/`finderdatacheck`.

**Acceptance:** each built file byte-matches on its disk; per-disk
`disk_files_classified` climbs; no new dialect work.

## 3. Build catalog — the 59 buildable files by pattern

| Type | N | Files | Proven pattern to reuse |
|------|--:|-------|--------------------------|
| **driver** | 17 | Modem, Parallel.Card, Printer, Epson, ImageWriter(.LQ), StyleWriter, Apple.Midi, Card6850.MIDI, A2.RAMCard *(Slinky)*, AppleTalk, ATP1.ATROM, ATP2.ATRAM, LaserWriter, IWEM, Boot.Driver, AppleCDSC | `drivercheck` DRIVERMAP (proves 12) — add entries + `-d` defines |
| **sound-rez** | 12 | Ahh, Doorbell, Droplet, Eastern, Frog, PipeOrgan, Quack, SimpleBeep, Sosumi, Swish, Trumpets, Whoosh | Rez pipeline (`rezbuildcheck`/`rezforkcheck`) |
| **toolset** | 5 | Tool025, Tool029, Tool032, Tool035, Tool038 | `toolcheck` TOOLMAP (proves 14) |
| **text-rez** | 5 | Read.Me ×2, Shortcuts, Whats.New, Apple II Script | Rez text/`rTextForScript` |
| **cdev-rez** | 3 | Printer, Slots, Time CDEVs | `cdevcheck` (proves 19; code payload extraction-fed) |
| **asm-other** | 10 | ControlPanel NDA, SetStart `Start` launchers ×2, Installer, QuickLogoff, VideoKeyboard, AppleIIVOC, ATInit, ATResponder, CloseView | asm assemble+link+expressload (per-file makefile recipe) |
| **boot/p8** | 6 | Basic.System, p8, `//e` + ProDOS16 Boot Blocks, ProDOS16 Image, IWEm *(Disk 7)* | `p8check`/`basiccheck` + NetBoot `Makefile` |
| **Tool.Setup** | 1 | Tool.Setup *(case-B wall)* | CRACK workflow (P7) |

**~42 files (driver/sound/toolset/text/cdev) are "point the proven builder at N
more instances"** — the CRACK workflow is only expected for `asm-other`
stragglers, the Disk-7 boot infra, and `Tool.Setup`.

## 4. Per-phase execution (concrete)

| Phase | Disks / batch | Steps | Acceptance |
|-------|---------------|-------|------------|
| **P0** | infra | §1a–d | gate green; `disk_physical_exact 1/7`; Disk 2 100% |
| **P2** | 1,3,4 | wire 105 built (§2) | per-disk `oos:0`-classified; built files match |
| **P3** | 5 Fonts, 6 synthLAB | subs + `Tool035` (toolset) + `Read.Me` (text) | `disk_physical_exact 3/7` |
| **P4a** | 3,4 drivers | 17 via drivercheck pattern | 17 drivers match |
| **P4b** | 4 sounds + 3,4 text/cdev | 12 sound-rez + 3 cdev-rez + 4 text-rez | those match |
| **P4c** | 3 toolsets + asm-other | Tool025/029/032/038 + the 10 asm-other (CRACK as needed) | Disks 1,3,4 100% → `5/7` |
| **P5** | 7 Apple II Setup | HFS overlay (§1d) + 6 boot/p8 + Apple II Script | Disk 7 100% → `6/7`… |
| **P7** | residual | `Tool.Setup` case-B CRACK; else document | `7/7` or documented exception |
| **P8** | — | **Tier A complete**; version bump + release (proven path) | `disk_physical_exact 7/7`, gate green |
| **P9** | refactor | R10 cache, D1 `_common.py`, D5 asm internals | gate byte-identical each |
| **P10** | refactor | D3 multiseg phase-split, D4 OMF classifier | **Tier A+C complete** |

(P8's `disk_physical_exact` reaches 7/7 across P3→P7; the fractions above assume
Disks 1/3/4 land together in P4c.)

## 5. The autonomous builder loop (per buildable file)

```
WIRE(f)   -> generate/register the builder from the census source_path + type
             (batch by §3 type: one pass wires all N of a type)
CHECK     -> diskcheck.check(disk) reports byte-match for f
if match  -> commit the batch
else      -> CRACK(f): decode-agents diff built-vs-gold -> synthesize the missing
             dialect/reloc/layout rule -> adversarial verify -> gate-guarded fix
             + corpus-free fixture; re-CHECK
```

Batches run as supervised workflows (one per §3 type). The orchestrator
gate-checks and commits per batch; substitute lists surface for human confirm at
each disk boundary.

## 6. Guardrails & cadence (every step)

- **Gate-stdout byte-identical to baseline** after any code change (a metric that
  *improves* means behavior changed — stop and understand).
- **Never `--bless` to make red green**; re-derive against gold.
- **New dialect ⇒ new corpus-free fixture** in the same commit.
- **Every substitute/non-target claim adversarially source-searched** before
  acceptance (the project's #1 historical error class).
- Commit per builder-type batch or per-disk milestone; push to Forgejo;
  GitHub/PyPI only at P8 release (human-gated).

## 7. Effort shape (supervised sessions, not human-days)

- **P0** — 1 focused session (infra; the HFS path is the only real unknown).
- **P2** — 1 session (mechanical wiring).
- **P3** — trivial (near-pure substitute disks).
- **P4** — the bulk, but batched: driver/sound/toolset/text/cdev batches are
  mostly mechanical; budget CRACK sessions only for asm-other stragglers.
- **P5** — Disk 7: 1–2 sessions (HFS overlay + boot infra is the novel work).
- **P7** — 1 CRACK session (`Tool.Setup`).
- **P9/P10** — per the refactor packets (R10 + D1/D3/D4/D5).

## 8. First action

**P0, step 1a:** scaffold `work/diskmanifest/` and generate all 7 manifests from
`docs/disk_census_2026-07-30.json` (every file → BUILD or SUBSTITUTE), then point
`diskcheck.check` at the manifest and confirm Disk 2 still 100%. That single step
makes `oos` measurable across all 7 disks and gives every later phase a scoreboard.
