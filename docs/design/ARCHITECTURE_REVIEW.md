# Architecture review — agenda & framing (2026-07-07)

Notes seeding a full architecture review, triggered by the question:

> *"Is each of these little fixes improving the linker as a general-purpose tool,
> or just getting really specifically good at this codebase?"*

This is the **agenda** — it sits on top of the two existing review artefacts and
does not replace them:
- `RATIONALISE.md` — the debt inventory (D1 omf detectors, D2 symbol model, D3
  the linkers) + a gated P0–P5 refactor plan. **Still the canonical debt doc.**
- `BESPOKERY_AUDIT.md` — the general-vs-bespoke audit (core clean; Tier-2 gap
  backlog). **Still the canonical generality audit.**
- `LINKOS.md` — the kernel-link scoping (the newest place the tension surfaced).

---

## 1. The central claim, and the one test that decides it

**Claim:** `gsasm/*.py` (asm, expr, m65816, omf, link, linkiigs, expressload,
makebin) is a **general** reimplementation of the MPW IIgs cross-toolchain —
no hardcoded symbol names, module addresses, or filenames. Codebase-specific
knowledge (module lists, `-lseg`/`-org` recipes, include paths, build defines)
lives **only** in `work/` harnesses, which is legitimate — it's build config,
the way a makefile is.

**The smell test** (apply to every change; this is the whole review in one line):

> A fix is *general* iff it is keyed on a **property** (a directive, an operator,
> a syntactic form, a structural relationship in the OMF/expr/instruction model).
> It is *overfitting* iff it is keyed on a **specific name, address, or file**.

Corollary: **finding** a bug via one file does not make the fix bespoke. `≈` was
found via ProDOS.FST but fires for any one's-complement; `temporg` was found via
boot_code but fires for any temporary-origin PROC. The byte-exact corpus is the
**oracle that proves generality**, not the thing being fit to — *provided* every
fix passes the smell test and the whole corpus stays green (no compensating
name-specific hacks). Watch for the failure mode: a change that only holds
because a second change elsewhere absorbs its regression.

---

## 2. Honest current verdict

- **Core (`gsasm/*.py`): general, and it holds.** Verified twice by
  `BESPOKERY_AUDIT.md` (grep + Explore passes: every module name / `$E1Dxxx`
  address in core is comment-only). This session added 8 core fixes (SEG
  persistence, IMPORT comma-split, temporg, `≈`, equ-alias-of-relocatable-label,
  data-record qualified field, linkiigs case-collision, expressload `>>8`
  cRELOC) — **all pass the smell test** (keyed on directive/operator/syntax/
  structure), all ROM-gated. See §4 for the worked classification.
- **Harnesses (`work/*.py`): bespoke by design — but leaking core logic.** This
  is the live issue. Two harnesses contain *linker/placement logic that belongs
  in the core*, not just build config:
  - `linkrom.py` — a full parallel ROM linker with its own symbol model.
  - `kernelcheck.py` — now (this session, WP-K1) a `_placed_symtab` +
    `_SCM_LSEG_RECIPE` that does placed multi-`-lseg` resolution by hand.

The distinction that matters: `_SCM_LSEG_RECIPE` (which loadname → which load
segment) is **fine** in the harness — it's the makefile. `_placed_symtab` (the
*algorithm* that places groups and resolves cross-group symbols) is **not** —
that is general linker behaviour that should live in `linkiigs`.

---

## 3. THE headline decision: linker unification (RATIONALISE D3, reinforced)

There are now **five** placement/symbol models in the tree:

| # | where | model | status |
|---|-------|-------|--------|
| 1 | `gsasm/link.py` | single-file reference | validated (linkcheck 61/61) — keep as reference |
| 2 | `work/linkrom.py` | ROM banks; `msym`/`msloc`/`objsegbase`/`linkidx` precedence | validated (buildrom byte-exact) — but a whole linker in the harness |
| 3 | `gsasm/linkiigs.py` | the "general" M2 linker; `sym`+`obj_globals`, placement via `_place` | the intended general home |
| 4 | `gsasm/expressload.py` | **re-implemented** linkiigs place+symtab inline (D3's flagged duplication; partly de-duped by P1 but diverged) | duplication debt |
| 5 | `work/kernelcheck.py` | **new** `_placed_symtab` + hand-built `_make_groups` | this session's leak |

RATIONALISE D3 already argued models 2 & 4 are debt. **WP-K1 added model 5.**
Every time the kernel/tools/ROM need "place segments at load addresses + build a
global symtab + resolve cross-object refs," a new copy appears in whichever
harness needs it, because `linkiigs` doesn't expose a *placed multi-`-lseg`
link* as a first-class operation.

**Recommended direction (the review's core proposal):** promote the
placed-multi-`-lseg` link + global symtab into `linkiigs` as one general
operation —
```
linkiigs.link_placed(objects, lsegs=[(name, [(@loadname|obj), ...], org?)],
                     defer_shifts=False|True) -> {segname: bytes}, symtab
```
The machinery is ~80% present (`_place` already jumps to ORGs and flows;
`_build_symtab` already builds a global table — improved this session). Doing
this would:
1. make `linkiigs` a genuine LinkIIgs (any link job, not just the tools' shape);
2. **retire `linkrom.py`** (ROM banks become one `link_placed` call with the bank
   recipe as config) — the audit's stated goal;
3. **retire kernelcheck `_make_groups`/`_placed_symtab`** (WP-K1 becomes config);
4. dissolve the expressload duplication (model 4) by construction;
5. let byte-exact Start.GS.OS/GS.OS *fall out as validation* instead of being
   chased byte-by-byte in the harness.

Open sub-questions for the reviewer:
- Does `link_placed` subsume linkrom's `msym`/`msloc`/`linkidx` precedence, or is
  that ROM-specific enough to stay? (D3 says linkrom's multiply-defined-label
  semantics are real and not yet in linkiigs — this couples to **D2**, the
  symbol model. Unifying the linkers may require the D2 PROC-as-module scope
  model first.)
- `defer_shifts` (ExpressLoad true / kernel false) is already an option — does it
  generalise cleanly across all five call sites?
- Placement assumes the `-lseg` group's header/PAD ORG structure (Layout A/B/C in
  kernelcheck). Is that a general OMF/MakeBin property or a GS.OS convention?

---

## 3a. The other half: read the recipes from the real build files (not hand-transcribed)

§3 makes the *engine* general. This makes the *driver* general — and it is the
higher-leverage of the two, because it attacks the largest remaining source of
bespokery and of *false* residuals.

**The finding.** Every codebase-specific recipe the harnesses hand-code already
exists, authoritatively, as a source build file:
- `GS.OS/MakeFiles/make.os` + `GS.OS/Scripts/linkOS` — the exact `linkiigs -apw
  -lseg scm_seg_0 … # becomes scm.bin`, `MakeBinIIGS scm.lnk`, and `catenate
  scm.bin.8..11 > Start.GS.OS`. (kernelcheck's `_SCM_LSEG_RECIPE`, `_make_groups`,
  Layout A/B/C, and catenation orders are hand-copies of this.)
- `ref/gsrom3/ROM 03/makeROM3.bat` — the ROM bank recipe (linkrom's `BANKS`).
- 194 component makefiles (`GSToolbox/*/makefile`, `FSTs/*/MakeFile`,
  `Drivers/*/*.make`) with literal `asmiigs … / LinkIIGS -x -t $BC -lseg:code:
  nospecial:static … / MakeBinIIgs …` — the object lists, `-lseg` groups **with
  attributes**, `-org`, `-t` filetype, `-i` includes, and `-d` defines that
  `toolcheck.TOOLMAP`/`FSTMAP`/`DRIVERMAP` transcribe (and repeatedly got wrong).

**Why it matters — evidence, not theory.** Hand-transcription has been a recurring
source of *false* residuals blamed on gsasm and later found to be wrong harness
lists (all in the session log): ControlMgr 54→96% (TOOLMAP missing
`CtlPatch`+`DummyDrag`), LineEdit 83→98% & FontMgr 81→99% (missing `common.asm`),
Scrap →100% (missing `common.asm`), multiple include-path bugs in fst/drivercheck.
A parser eliminates that entire class **by construction** — the list is complete
and correct because it *is* the shipping recipe.

**Proposal — a build-recipe reader** (`work/mpwmake.py`, a general interpreter):
parse an MPW makefile / link script into a normalized recipe —
```
Recipe(target, filetype, objects=[(src, asmflags, defines, includes)],
       lsegs=[(name, members=[obj|@loadname], attrs, org?)],
       makebin, catenate=[parts]) 
```
then have the harnesses **consume** it instead of hand-coding maps. This:
1. retires `TOOLMAP`/`FSTMAP`/`DRIVERMAP`/`BANKS`/`_SCM_LSEG_RECIPE` and much of
   `_make_groups` — the recipe becomes *read data*, the harness a general driver;
2. moves the codebase-specific knowledge back to where the smell test says it
   belongs — the Apple build files — leaving `work/` a genuine interpreter;
3. feeds §3's `link_placed` its `-lseg`/`-org`/attrs directly (engine + driver);
4. is a **cheap correctness win NOW, before any refactor**: parse the recipes and
   *diff them against the current hand-transcribed maps* — every discrepancy is
   either a transcription bug to fix (free residual) or a real gsasm gap to log.

**Honest limits (so the review scopes it right):**
- MPW Make has its own grammar (`ƒ` deps, `∂` continuation, `{Var}` expansion,
  `if/end`); and some builds are shell scripts (`linkOS`, `BuildEverything`) not
  makefiles. Both are bounded, but it's a real (small) parser + a build-env
  variable resolver ({Object}/{Common}/{WorkFolder}/…).
- A flag→API mapping layer is needed (`-lseg:…:static|dynamic`, `-org`, `-t`,
  `-x`, `-i`, `-d`; ignore `-unsafe`/`-wi`). Bounded and general.
- `reziigs` (Rez) targets are out of scope (M7); the code-image path doesn't need
  them — the reader just skips resource rules.
- **It does not replace core correctness.** A correct recipe still needs a correct
  assembler/linker: the remaining *code-image* gaps (sizing drift, `#^Label`,
  temporg-in-flow, the case-B reloc quirk, D1/D2/D3) are orthogonal. This retires
  *recipe* bespokery and *transcription-error* residuals, not assembler bugs.

**Probe result (data, `work/mpwmake_probe.py` — read-only, parses the makefiles
and diffs against the harness maps):**
- **Tools 8/8 EXACT** vs `TOOLMAP` — including ControlMgr & LineEdit once the make
  *dependency* line is used (their LinkIIGS *rule* is half-`#`-commented; the
  target's prerequisites are authoritative and match the shipping binary).
- **FSTs 6/7 EXACT**, **Drivers 7/12 EXACT** vs `FSTMAP`/`DRIVERMAP` — the SCSI
  four show identical 13-source lists (only my define-string format differs); the
  2 “no-match” are probe output-name quirks, not harness errors.
- **No remaining transcription errors found.** The current maps are faithful — the
  historical mistakes (ControlMgr `CtlPatch`/`DummyDrag`, LineEdit/FontMgr/Scrap
  `common.asm`) were already hand-corrected.

**So the win is *derivation*, not bug-fixing.** The maps are correct today but are
hand-maintained copies that were repeatedly wrong before; a reader makes them
*derived data*, killing the maintenance and the error class, and — the actual
point — turning "the harness knows this codebase" into "the harness reads this
codebase's build files."  Reader scope confirmed by the probe: use the make
*dependency* line as authoritative; `make.<component>` per FST/driver; first
real positional of `asmiigs` = the source. Remaining reader work is bounded and
now known: **{Variable} resolution** (defines like `DEBUGSYMBOLS`, and 2 output
names) and **quoted multi-word object names** (the SCSI drivers).

**Verdict:** §3a is complementary to §3 and arguably should come first (it's lower
risk — a reader is additive, gated by diffing against today's maps — and it
immediately converts a chunk of "harness knows this codebase" into "harness reads
this codebase's build files"). Together, §3 + §3a are the real answer to the
triggering question: point the toolchain at the Apple source **and its makefiles**,
get byte-exact output, with zero hand-copied recipe.

---

## 4. Worked example — classifying this session against the smell test

| change | keyed on | verdict |
|---|---|---|
| SEG loadname persists (WP-K0) | the `SEG` directive's scope semantics | GENERAL ✓ (Tier-2 #5) |
| IMPORT comma-split | `IMPORT a,b` syntax | GENERAL ✓ |
| temporg | the `temporg` directive | GENERAL ✓ (~15 files) |
| `≈` one's-complement | the operator glyph | GENERAL ✓ |
| equ-alias-of-relocatable-label (WP1) | "RHS is one relocatable label" (a property) | GENERAL ✓ (audited: 1142 sites, only real aliases fire) |
| data-record qualified field (WP2) | "label inside a no-operand DATA record" | GENERAL ✓ |
| linkiigs case-collision (Tool025) | case-folded name collides a public segment | GENERAL ✓ |
| expressload `>>8` cRELOC | OMF has no SUPER type for shift-8 | GENERAL ✓ |
| **kernelcheck `_placed_symtab` (WP-K1)** | the SCM's `-lseg` recipe + PAD-ORG layout | **HARNESS / leaning bespoke** ⚠ — the *recipe* is config, the *algorithm* should be in linkiigs (§3) |

Reading: the core is behaving. The one place the project drifted toward
"specifically good at this codebase" is exactly where a general capability
(placed multi-`-lseg` link) is missing from `linkiigs`, so the harness grew its
own. That's the signal to act on §3.

---

## 5. Current scorecard (moved a lot since RATIONALISE's baseline)

| gate | RATIONALISE baseline | now |
|---|---|---|
| buildrom / objcheck / linkcheck | True / 36 / 61 | **True / 36 / 61** (unchanged — sacrosanct) |
| toolcheck | 90% | **99%** (102588/103138) |
| drivercheck | 38% | **54%** (47827) |
| fstcheck | 40% | **53%** (50234) |
| kernelcheck | partial | **69%** (51905); Start.GS.OS 99.7% |
| M8 disk images | (not yet) | **10/26** byte-exact, physical image 100% |

The corpus rising while `buildrom/36/61` stays pinned is the evidence the core
fixes are general (a bespoke fix would eventually have to move an ROM byte).

---

## 6. What the review should decide

1. **Adopt §3a first** (the build-recipe reader) — likely the highest-leverage,
   lowest-risk move: it's additive, gated by diffing against today's maps,
   retires the transcription-error residual class, and dissolves TOOLMAP/FSTMAP/
   DRIVERMAP/BANKS/`_SCM_LSEG_RECIPE` bespokery. Do it before, or alongside, §3.
2. **Adopt §3** (unify into `linkiigs.link_placed`, retire linkrom + harness
   placement) — yes/no, and whether it must wait on D2 (symbol model). §3a feeds it.
3. **Ordering vs. D1/D2/D3** — D1 (omf detector unification) and D2 (symbol
   model) from RATIONALISE are still open; §3 (D3) may depend on D2. Sequence?
4. **Generality gate as CI** — encode the smell test: a pre-merge check that
   `gsasm/*.py` contains no source-symbol/address literals (grep-based, like the
   audit), so overfitting can't land silently.
5. **When to stop chasing bytes in the harness** — e.g. the last 36 Start.GS.OS
   bytes: fix via §3/§3a (general) rather than more `_placed_symtab` special-cases.
