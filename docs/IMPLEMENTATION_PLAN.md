# gsasm — Implementation Plan (execution of the Completion SOW)

> Companion to `docs/SOW_COMPLETION.md`. The SOW defines *what* Complete is and
> the phase outline; this is the concrete *how*, grounded in the evidence-based
> census (`docs/disk_census_2026-07-30.json`). Tier A+C, supervised-workflow
> autonomy. Draft 2026-07-30.

## 0. The shape of the remaining work

From the census (355 files, 7 disks, `oos:0` — authoritative rev2):

- **104 built** — already byte-exact; P2 wires them into per-disk manifests.
- **58 buildable** — the real reproduction work, and **~42 reuse a proven
  builder pattern** (see §3). Only ~16 are genuinely new (Disk-7 boot infra,
  AppleTalk setup DAs).
- **183 no-source substitute** + **8 Pascal/C non-target** — declared verbatim
  with cited evidence.
- **2 TECHNICAL_EXCEPTION** — `Tool.Setup` (Disks 1 & 2): source present, not
  byte-exact (case-B wall); P7 crack target.

Completion predicate (machine-checkable) — **NOT physical match alone** (a
no-builder run is trivially 100%; see SOW §2 + `diskcheck.py:13`): `gate.py`
green **and** the 5 builder-correctness metrics satisfied for all 7 disks —
`disk_inventory_classified` (`oos:0`), `disk_required_builders_wired`,
`disk_required_builders_exact`, `disk_substitutes_confirmed`, and
`disk_physical_exact` (secondary).

## 1. P0 — manifest model + metrics + census-validation + HFS (split into P0a–d)

> Revised per the Codex review (2026-07-30): physical match is **not** the
> completion gate; states must distinguish built from buildable; the census JSON
> must be validated against live enumeration first; HFS is more than a wrapper.

> **STATUS: P0a/P0b/P0c/P0d-1 DONE** — `work/diskmanifest.py` (fork-level states
> from the census, Disk-2 builders merged) + `work/manifestcheck.py` (live-vs-
> manifest validation across all 7 disks incl. HFS Disk 7 + the 5 metrics) +
> `work/hfs.py` reads the 2mg-wrapped Disk 7. Wired into `gate.py --full` with
> baselines: `inventory_classified 7/7`, `substitutes_confirmed 193/193`,
> `builders_wired 37/162`, `builders_exact 37/162`, `physical_exact 1/7`.
> `disk_logical_exact 39/39` unchanged (Disk-2 gate untouched — built alongside,
> not refactored). **P0d-2 (HFS overlay writer) deferred to P5** (per plan: the
> ProDOS track must not block on it; Disk 7 lands in P5).

**P0a — ProDOS manifest model + structured result.** Generalize `diskcheck`'s
implicit Disk-2 registry (`SOURCE_BUILDERS`/`REZ_BUILDERS`) into
`work/diskmanifest/` — one module per disk exposing **fork/payload-level** owners:

```python
def manifest(V) -> dict[ForkKey, Entry]
# Entry ∈ { BUILT(builder, evidence),
#           TODO_BUILDABLE(kind, source_path, evidence),   # source exists, no builder yet
#           SUBSTITUTE(reason, evidence),                  # incl. gold-fed rCDEVCode payloads
#           TECHNICAL_EXCEPTION(reason, evidence) }         # Tool.Setup; human-gated
# ForkKey = (path, 'data'|'rsrc'|'rCDEVCode'|...)  -- a file may hold several entries
```

`check()` reads `manifest(V)`, builds `BUILT` forks and overlays, carries every
other state's golden bytes verbatim, and returns a **structured result** (per
fork: state, wired?, logical-exact?, bytes). Disk 2 must stay 100% (regression
guard). **Do NOT seed `buildable` as `BUILT`** — that would invent placeholder
builders and weaken the gate; buildable forks seed as `TODO_BUILDABLE`.

**P0b — census validation (before any manifest generation).** Enumerate each
disk **live** (ProDOS via a2til, HFS via `work/hfs.py`); diff every live
path/fork against `docs/disk_census_2026-07-30.json`; **fail on missing / extra /
duplicate** records; merge the existing Disk-2 registry into the generated state.
(This is what caught the Disk-5 `/Fonts/Icons/Finder.Data` drop — it must be a
standing gate, not a one-off.)

**P0c — metrics (physical is secondary).** Add, fractional over the 7 disks:
`disk_inventory_classified` (`oos:0`), `disk_required_builders_wired`,
`disk_required_builders_exact` (each `BUILT` fork's **logical** bytes == golden
**before** overlay), `disk_substitutes_confirmed`, and `disk_physical_exact`
(secondary). A **new metric fails until its baseline is committed**. Tier A =
all five satisfied for all 7 disks (TECHNICAL_EXCEPTION allowed only human-gated).

**P0d — HFS, in stages (it is not a small wrapper).** `work/hfs.py` today is a
read-only data-fork extractor — no writer, resource-fork accessors, catalog
mutation, or allocation-bitmap API. So:
- **P0d-1** HFS read-only checker: prove path + **both fork** extraction for
  Disk 7's 12 files (incl. rsrc forks, date/version resources).
- **P0d-2** HFS overlay writer: catalog + allocation-bitmap-preserving rebuild,
  with a **selftest that round-trips the original bytes** (analogue of
  `diskcheck.selftest`).
ProDOS work (P0a–c) must **not block** on the HFS writer — Disk 7 lands in P5.

**P0 acceptance:** gate green; the 5 metrics wired with committed baselines;
Disk 2 still 100%; all 7 manifests generated + validated with `oos:0`;
`disk_required_builders_exact` reflects only genuinely-built forks (not golden
carry).

## 2. P2 — wire the 104 built forks

Mechanical. Most "built" files on Disks 1/3/4 are **the same artifact already
built for Disk 2** (census cmp-verified identical, e.g. Disk-1 `ProDOS`, `GS.OS`,
`Start.GS.OS`, `Error.Msg`, the FSTs and drivers, TS2/TS3, `Resource.Mgr`,
`Sys.Resources`, the CDEV forks). Wiring = register the existing builder under
the Disk-N path key. The Finder (Disk 3) reuses `findercheck`/`finderdatacheck`.

**Acceptance (per Codex #10 — not `oos:0`/physical, which are trivially true):**
per disk/fork, track **expected `BUILT` forks / builders wired / logical-exact /
built-bytes covered**. For a **duplicate artifact reused from Disk 2**, the
manifest must record that the target-disk copy was **independently byte-compared
to the already-gated source artifact** before the builder is reused (don't assume
"same name ⇒ same bytes"). `disk_required_builders_wired` and
`disk_required_builders_exact` must climb to match the expected-built count.

## 3. Build catalog — the 58 buildable files by pattern

| Type | N | Files | Proven pattern to reuse |
|------|--:|-------|--------------------------|
| **driver** | 17 | Modem, Parallel.Card, Printer, Epson, ImageWriter(.LQ), StyleWriter, Apple.Midi, Card6850.MIDI, A2.RAMCard *(Slinky)*, AppleTalk, ATP1.ATROM, ATP2.ATRAM, LaserWriter, IWEM, Boot.Driver, AppleCDSC | `drivercheck` DRIVERMAP (proves 12) — add entries + `-d` defines |
| **sound-rez** | 12 | Ahh, Doorbell, Droplet, Eastern, Frog, PipeOrgan, Quack, SimpleBeep, Sosumi, Swish, Trumpets, Whoosh | Rez pipeline (`rezbuildcheck`/`rezforkcheck`) |
| **toolset** | 5 | Tool025, Tool029, Tool032, Tool035, Tool038 | `toolcheck` TOOLMAP (proves 14) |
| **text-rez** | 5 | Read.Me ×2, Shortcuts, Whats.New, Apple II Script | Rez text/`rTextForScript` |
| **cdev-rez** | 3 | Printer, Slots, Time CDEVs | `cdevcheck` (proves 19; code payload extraction-fed) |
| **asm-other** | 10 | ControlPanel NDA, SetStart `Start` launchers ×2, Installer, QuickLogoff, VideoKeyboard, AppleIIVOC, ATInit, ATResponder, CloseView | asm assemble+link+expressload (per-file makefile recipe) |
| **boot/p8** | 6 | Basic.System, p8, `//e` + ProDOS16 Boot Blocks, ProDOS16 Image, IWEm *(Disk 7)* | `p8check`/`basiccheck` + NetBoot `Makefile` |
| **Tool.Setup** *(not counted in 58 — TECHNICAL_EXCEPTION ×2, Disks 1&2)* | — | Tool.Setup *(case-B wall)* | P7 CRACK → promote to BUILT if cracked, else stays the documented exception |

**~42 files (driver/sound/toolset/text/cdev) are "point the proven builder at N
more instances"** — the CRACK workflow is only expected for `asm-other`
stragglers, the Disk-7 boot infra, and `Tool.Setup`.

## 4. Per-phase execution (concrete)

Two completion tracks move separately (Codex #6): `disk_physical_exact`
(whole-image, can go 100% on golden carry) and the real
`disk_required_builders_exact` (only genuinely-built forks). **`Tool.Setup` (a
TECHNICAL_EXCEPTION on Disks 1 & 2) means those two disks are physical-complete
but not builder-exact-complete until P7** promotes it. `phys` = physical disks
at 100%; `builder` = disks fully builder-exact.

| Phase | Disks / batch | Steps | Acceptance (phys / builder) |
|-------|---------------|-------|------------|
| **P0** | infra | §1 P0a–d1 | ✅ **DONE** — 5 metrics wired+baselined; Disk 2 unchanged; `oos:0` all 7 (P0d-2 HFS writer → P5) |
| **P2** | 1,3,4 | wire 104 built forks (§2) | builders-wired/exact climb to expected-built |
| **P3** | 5 Fonts, 6 synthLAB | subs + `Tool035` + `Read.Me` | phys **3/7** (2,5,6); builder 3/7 |
| **P4a** | 3,4 drivers | 17 via drivercheck pattern | 17 drivers logical-exact |
| **P4b** | 4 sounds + 3,4 text/cdev | 12 sound-rez + 3 cdev-rez + 4 text-rez | those logical-exact |
| **P4c** | 3 toolsets + asm-other | Tool025/029/032/038 + 10 asm-other (CRACK as needed) | Disks 3,4 done; **Disk 1 phys&accounted but NOT builder-exact (Tool.Setup)** → phys **6/7**, builder **5/7** |
| **P5** | 7 Apple II Setup | HFS overlay (§1 P0d) + 6 boot/p8 + Apple II Script | phys **7/7**, builder **6/7** (Disks 1,2 still hold Tool.Setup) |
| **P7** | Tool.Setup ×2 | case-B CRACK → promote both to BUILT; **else human-gate the TECHNICAL_EXCEPTION** | builder **7/7**, OR Tier A stated as "phys 7/7 + fully accounted, Tool.Setup the one exception" |
| **P8** | — | **Tier A complete** (all 5 metrics); version bump + release | 5 metrics satisfied; gate green |
| **P9** | refactor | R10 cache, D1 `_common.py`, D5 asm internals | gate metrics **unchanged** (refactor discipline) |
| **P10** | refactor | D3 multiseg phase-split, D4 OMF classifier | metrics unchanged; **Tier A+C complete** |

(`disk_physical_exact` reaches 7/7 at P5; `disk_required_builders_exact` reaches
7/7 only at P7 when Tool.Setup is cracked — or Tier A is stated with Tool.Setup
as the one human-gated exception. Disk 1 cannot be called *builder-complete* in
P4c while Tool.Setup is unresolved.)

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

## 6. Guardrails & cadence (gate discipline differs by change type — Codex #8)

- **Expansion packets (P0–P7)** *add* coverage: reviewed metric **improvements
  are expected**; require **no regressions**; update `work/gate_baseline.json`
  in the same accepted packet; a **new metric fails until baselined**. `gate.py`
  is direction-aware, not stdout-pinned.
- **Refactor packets (P9/P10)**: metrics **unchanged**, no stdout/reporting drift
  (unless the packet explicitly targets reporting). An *improvement* there means
  behavior changed — stop.
- **Never `--bless` to make red green**; re-derive against gold.
- **New dialect ⇒ new corpus-free fixture** in the same commit.
- **Every `SUBSTITUTE`/`TECHNICAL_EXCEPTION` claim adversarially source-searched**
  across all trees before acceptance (the project's #1 historical error class).
- **Census-validation (P0b) runs as a standing gate** — live enumeration vs the
  manifest; fail on missing/extra/duplicate forks.
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

**P0b first, then P0a:** run the census-validation (live enumeration vs the rev2
JSON) as a standing check *before* generating anything — the JSON is now
corrected but validation must be the gate, not a one-off. Then scaffold
`work/diskmanifest/` from the validated census (each fork → `BUILT` /
`TODO_BUILDABLE` / `SUBSTITUTE` / `TECHNICAL_EXCEPTION`), merge the existing
Disk-2 registry, point `diskcheck.check` at the manifests, and confirm Disk 2
still 100% + the 5 metrics baseline. That makes `oos` and *builder-exactness*
measurable across all 7 disks and gives every later phase its real scoreboard.
