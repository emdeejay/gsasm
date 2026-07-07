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

1. **Adopt §3** (unify into `linkiigs.link_placed`, retire linkrom + harness
   placement) — yes/no, and whether it must wait on D2 (symbol model).
2. **Ordering vs. D1/D2/D3** — D1 (omf detector unification) and D2 (symbol
   model) from RATIONALISE are still open; §3 (D3) may depend on D2. Sequence?
3. **Generality gate as CI** — encode the smell test: a pre-merge check that
   `gsasm/*.py` contains no source-symbol/address literals (grep-based, like the
   audit), so overfitting can't land silently.
4. **When to stop chasing bytes in the harness** — e.g. the last 36 Start.GS.OS
   bytes: fix via §3 (general) rather than more `_placed_symtab` special-cases.
