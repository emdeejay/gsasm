# gsasm rationalisation review

Read-only architecture review of the accreted complexity in `gsasm`, with a
prioritised, byte-exactness-gated refactoring plan. Nothing here has been applied
to `gsasm/*.py` or `work/*.py`; this document is the only artefact.

## Verified baseline (the SACROSANCT results, all green as of this review)

Run from the main checkout (`ref/` golden data is gitignored and lives there, not
in the worktree):

| Gate | Result |
|---|---|
| `work/buildrom.py` | ROM 03 **byte-identical: True** (261377 B gsasm-built, 99%) |
| `work/objcheck.py` | **36/61** OBJ byte-identical |
| `work/linkcheck.py` | **61 LINK_IDENTICAL** (24 provably-correct w/o byte-identical obj) |
| `work/toolcheck.py` | tools **90%** (DialogMgr/Scrap/ListMgr 100%, WindMgr/MenuMgr 99%, LineEdit 83%, FontMgr 81%, ControlMgr 54%) |
| `work/drivercheck.py` | drivers **38%** (Console.Driver 100%, UniDisk3.5 99%) |
| `work/fstcheck.py` | FSTs **40%** (Char.FST 100%, Pro.FST 99%, Pascal.FST 96%) |
| `work/probootcheck.py` | prodos **100% byte-exact** |
| `work/kernelcheck.py` | prodos 100%; Start.GS.OS/GS.OS/P8 partial |

Every plan step below is gated on the first three rows staying **exactly** at
`True / 36 / 61`, plus the corpus rows not regressing. Any step that cannot hold
that gate is listed under DON'T.

---

## 1. Debt inventory

### D1 — `omf.py` relocation-emit detectors: **genuine debt, and the headline**

The relocation-decision surface in `gsasm/omf.py` is a pile of pattern-detectors,
each deciding whether an operand/DC element is a literal, a relocation, a shift,
an expression, or a label-difference:

- `_linear_reloc` (147) — one reloc label, coefficient +1, + constant.
- `_mul_reloc_expr` (177) — one label in an ORG'd seg, coefficient N≠0,1: `(SEG+rel)*N+K`.
- `_diff_reloc` (217) — two defined labels, coefficients +1/−1, cross-segment: `A−B+K`.
- `_pc_rel_const` (281) — `label−*` where the base cancels → literal.
- `_expr_for` (311) — the dispatcher: prefixes/shifts, single `sym±const`, else falls to the above.
- `_reloc_elem` (680, nested in `emit_segment`) — the DC-table element gate that fans out to all of them.
- `needs_reloc` (asm.py 709), `_undef_external` (545), `_in_org_seg` (491), `_cross_seg_label` (535), `_branch_xseg` (501) — the boolean predicates each detector and `emit_segment` consult.

**Why it's debt, with evidence.** Every one of the four value-shaped detectors
independently reimplements *the same primitive*: perturb one symbol's value by a
known delta and re-evaluate the whole expression to recover **that symbol's
coefficient** in the expression. Grep proof (`omf.py`):

- `_linear_reloc`: `res2` bumps L by `0x100`; accepts iff `(V2 - V) == 0x100` (coeff +1). (168–172)
- `_mul_reloc_expr`: `_res(n, bump)`; `N = V1 - V` is literally the coefficient. (194–200)
- `_diff_reloc`: `bumped(0x100,0)` must equal `v+0x100` (coeff A = +1), `bumped(0,0x100)` must equal `v-0x100` (coeff B = −1). (246–260)
- `_pc_rel_const`: bumps PC and every same-seg label by `0x1000`; unchanged ⇒ base cancels ⇒ constant. (299–308)

So there is exactly one operation underneath — *"decompose an expression into
`Σ cᵢ·symᵢ + K` over its relocatable symbols by finite differencing"* — expressed
four times with four different acceptance predicates and four different emitters.
`_expr_for` then re-derives shift/prefix/paren handling on top. The detectors also
overlap and are order-sensitive: `_reloc_elem` must call `_pc_rel_const` **before**
`_linear_reloc` (comment at 682) or the PC-relative constant gets wrongly
relocated; `_expr_for` tries `_linear_reloc` then an inline undefined-external
path then `_diff_reloc` then `_mul_reloc_expr` in a specific sequence. This is the
classic "a detector per observed pattern on shared infrastructure" smell, and it
is the thing most likely to break when the next pattern (a two-label diff with a
shift, a coefficient-2 cross-object ref) appears.

**The cleaner form** (this is the headline move, see §4): compute the linear
decomposition **once** —

```
coeffs, K = linear_decompose(asm, text)     # {SYM: coeff}, residual constant
# via one finite-difference pass over the identifiers in `text`
```

Then a *single* emitter turns `coeffs`/`K`/shift into OMF ops by the rules the
detectors already encode, chosen by the shape of `coeffs` rather than by which
detector happened to match first:

- `coeffs == {}` → literal `K` (with `_in_org_seg` re-homing, unchanged).
- one reloc symbol, coeff +1 → `SEGNAME+off` / by-name / import (today's `_linear_reloc` + `_expr_for` core).
- one symbol, coeff N → `(SEG+rel)*N+K` (today's `_mul_reloc_expr`).
- two symbols, +1/−1, cross-seg → `A−B+K` (today's `_diff_reloc`).
- all coeffs on same-seg symbols **and** the `*`/PC term cancels → literal (today's `_pc_rel_const`).

The base-independence and coefficient checks *become* reading the `coeffs` map
instead of four bespoke re-evaluations. This **dissolves** `_linear_reloc`,
`_mul_reloc_expr`, `_diff_reloc`, and `_pc_rel_const` into one function + one
emitter, and it is a superset (it can emit a two-label diff *with* a shift, which
no current detector handles — that is the capability unlock, see §2/§4).

### D2 — `asm.py` symbol model: **genuine debt; proven to block a real case**

The scope model is a lattice of parallel dicts keyed by upper-cased name:
`symbols`/`symtype`/`symseg`/`seg_local`/`seg_equ`/`imports`/`entries`/`exports`
+ `seed`/`seed_type`/`seg_seed`/`at_defs`/`at_seg` (asm.py 191–224), consulted by
a precedence ladder in `sym_kind` (734) and mirrored in `resolve` (340),
`needs_reloc` (709), `is_reloc` (758). `_rseg` is `None` during the main assembly
pass and only set during `apply_fixups`/`emit_segment`, so several rules
("a label local to the current emit segment shadows…") silently no-op during
sizing and only fire at emit time — a documented footgun (`sym_kind` comment 738,
`needs_reloc` "only affects emit time; `_rseg` is None during pass-1").

**Why it's debt, with evidence.** The model stores **one kind and one value per
name globally**, so it structurally cannot represent "the same name is an imported
ADDRESS in reference X and a local EQU VALUE in reference Y." The `ctlPart` episode
is the proof: commit `048adb7` made an in-proc EQU that shadows an IMPORT keep the
import's global identity (WindMgr 99→100%); commit `d90f7e4` reverted it because
the identical rule regressed Pro.FST — `Max_call`/`max_sys` are computed EQUs that
ProDOS.FST both IMPORTs and defines and references as **immediates**, where the
local EQU must win, the *opposite* of `ctlPart`'s relocated address reference. The
revert message states it exactly: *"reference-context-dependent and not available
at define-label time."* `sym_kind(name)` takes only a name; it has no reference
context, so it cannot return 'import' for one use and 'equ' for another.

**The cleaner form.** Resolve **kind per reference-context**, not per symbol. The
minimal version keeps the stores but threads the *use* into the decision:
`sym_kind(name, as_addr: bool)` — an operand used as an address (`sta >ctlPart`,
a DC.L table entry, a branch/JSR target) prefers the import/label binding; an
operand used as an immediate value (`lda #Max_call`) prefers the local EQU. That
one extra bit distinguishes both cases the revert could not. The fuller version
(the `SCOPE_RESOLUTION.md` model, already written) makes **PROC/FUNC the unit of
label locality** so a per-PROC symbol table exists and cross-PROC same-name refs
are resolved *at assembly time* to a specific definition + `SEGNAME+offset`,
instead of punting a bare name to the linker. That is the deeper fix and it also
dissolves D3's multiply-defined-label problem (see §2).

### D3 — Three linkers + a duplicated fourth: **partly justified, partly latent-bug debt**

Four relocation resolvers exist, with **three different symbol-resolution models**:

1. `gsasm/link.py` — single-object, minimal `sym` dict (`_eval`, `_build_body`). ROM-proven via linkcheck (61/61).
2. `work/linkrom.py` — ROM banks; its OWN model: `msym`/`msloc`/`objsegbase`/`gtab['defs']` with `linkidx` precedence and a bespoke `resolve_name` order (segbase→msym→rommap→export→msloc→last-def-before-linkidx). Proven via buildrom (byte-exact).
3. `gsasm/linkiigs.py` — the general M2 linker; a THIRD model (`sym` + per-object `obj_globals`, first-def-wins with `len(objects)==1` gates for publicness).
4. `gsasm/expressload.py` — **reimplements linkiigs Pass-1 placement and Pass-2 symbol-table inline** rather than calling it.

**Justified parts.** `link.py` and `linkrom.py` are the *validated references*
(61/61 and byte-exact) — they must not be casually collapsed; the milestones doc's
own guardrail says so. `linkrom`'s `msym`/`msloc`/`objsegbase` machinery encodes
the multiply-defined-label + PROC-head-locality semantics that `linkiigs` does not
yet have, and `SCOPE_RESOLUTION.md` shows no single heuristic fits all cases — so
that logic is *earned complexity*, not gratuitous.

**The debt is expressload's duplication, and it is a live latent bug.** The two
placement loops are near-verbatim (linkiigs 161–176 vs expressload 410–422), and
the two symbol-table passes mirror each other — but they have **already diverged**:

- linkiigs gates segment-name publicness on object count: `if len(objects)==1: sym.setdefault(segname,…)` (linkiigs.py 224), with interior labels also gated public-only for multi-object (238–271).
- expressload does it **unconditionally**: `sym.setdefault(segname, seg_base)` for every object (expressload.py 440), with no publicness gate on interior labels (442–464).

For a single-object tool (every byte-exact ExpressLoad'd target today) the two
agree, which is why nothing is red. For a **multi-object** ExpressLoad'd tool they
would resolve segment names and interior labels differently — a divergence that
will surface exactly when the corpus pushes past single-object tools. This is the
"had to apply the `_defer_shifts` fix in BOTH" symptom the brief flagged: the fix
landed twice (linkiigs.py 332, expressload.py 501) because the placement/symbol
scaffolding was copied rather than shared.

### D4 — Harness special-casing: **mostly justified scaffolding; two items leak modelling gaps**

`work/*check.py` carry per-target data and compensation. Most is legitimate test
scaffolding — a harness must transcribe each component's makefile link order and
know its packaging:

- `TOOLMAP`/`DRIVERMAP`/`FSTMAP` source lists (toolcheck 65, etc.) — these *are* the MPW makefiles; correct to encode (README gotcha 6). Not debt.
- MenuMgr per-segment compare + `extern_srcs` PopUpProc@`0x030000` (toolcheck 72–76) — the tool genuinely is multi-segment with a bank segment; modelling it is correct.
- `de_express` / SUPER walking — inherent to comparing against ExpressLoad'd golden files.

Two items **leak a real gsasm gap into the harness** and should be treated as
markers, not permanent scaffolding:

- **kernelcheck `_build_header_content` / `_build_with_end_padding`** (kernelcheck 366–420) explicitly "compensates for the gsasm PROC ORG skip/noskip bug" by *hard-coding* the header gap (`SCM_HEADER_LENGTH - len(hdr_bytes)`) and the end pad from source EQUs. The comment says so outright. That is a modelling gap (`PROC ORG expr,noskip` sizing) papered over in the harness.
- **kernelcheck seg-length extern injection** (`_build_header_content` 383–406) injects `seg_N_end` absolute addresses as externs so `DC.W seg_N_end-seg_N_start` resolves. This is the cross-object label-difference case that `_diff_reloc` *already handles for cross-segment* — it doesn't fire here only because the two labels are in different *objects*, which the linker symbol table should provide. Once D1/D3 give a clean cross-object difference, this injection is deletable. `&sysdate` injection (kernelcheck 761) is legitimately external input (build date), not a gap — keep it.

---

## 2. Does the debt BLOCK the stuck levers? (the high-value question)

**Yes for three of the four named levers, and the same two refactors unblock them.**

### L1 — bank-byte `#^` for the *resolved* (non-ExpressLoad) kernel — BLOCKED by D3, cleanly fixable

Root cause found and confirmed by reading the code: `linkiigs.link` calls
`_defer_shifts(recs)` **unconditionally** in Pass-3 (linkiigs.py 332), including in
`merge=True` mode, and **discards** the collected relocs (`_srels` is unused —
grep confirms it is never read). `_defer_shifts` rewrites `#^Label`/`>>16` to store
the *un-shifted base-0 placeholder* on the premise that a SUPER type-27 reloc will
apply the shift at load time. That premise holds only in the ExpressLoad path
(where `expressload._scan_relocs` emits the SUPER record). In a **resolved merged**
link — which is exactly how the kernel is built (`kernelcheck` line 338:
`_lnk.link([(combined, None)], {'merge': True})`, then MakeBin/catenate, *no*
ExpressLoad) — nothing ever applies the deferred shift, so `#^Label` stores 0. That
is the stuck kernel bank-byte lever, and it is a *direct consequence* of applying
an ExpressLoad-only transform on the resolved path.

The resolved-path behaviour is already proven correct elsewhere: `linkrom.py`
(byte-exact ROM) does **not** call `_defer_shifts`; it evaluates the shift op
`0x07` directly in `eval_expr` (linkrom.py 223) and gets the right shifted value.
So the fix is to make `_defer_shifts` conditional on the output actually carrying
SUPER relocs: run it only for `merge=False`/ExpressLoad, and in `merge=True` let
`_build_body`/`_eval` resolve the shift (as link.py's `_eval` op 0x07 already
does, link.py 54–59). This unblocks L1 with **no** change to `omf.py` or the ROM
path. Gate: buildrom/objcheck/linkcheck unaffected (they don't use linkiigs);
kernel bank-byte `#^` should resolve; single-object ExpressLoad'd tools
(Char.FST/Scrap) must stay byte-exact.

### L2 — multiply-defined / cross-object ControlMgr (54%) — BLOCKED by D2/D3, needs the scope model

The first ControlMgr divergence is `DC.L WindDragRect-1` in CONTROLCALLTABLE baked
as `0xFFFFFFFF` (memory + `SCOPE_RESOLUTION.md`): `WindDragRect` is defined in
another *object*, undefined within ControlMgr.asm, so it resolves to 0 → `0-1` →
baked literal, instead of a by-name external reloc the linker fills. Plus 5
duplicate DefProc labels (`DO_DRAW`/`DO_TEST`/…×2). This is the *same* frontier as
the linkrom 14-byte tail documented in `SCOPE_RESOLUTION.md`: by-name references to
labels defined many times, where scope was discarded at assembly time. No linker
heuristic fits all cases (that doc proves first/last/nearest each break something).
The fix is D2's PROC-as-module scope model (resolve same-module cross-PROC refs at
assembly to a specific def; keep genuine externals by-name for the linker's
first-def-wins) + D3 giving `linkiigs` the `msym`/`msloc` distinction `linkrom`
already has. This is "cleanup that unlocks capability," not cosmetic.

### L3 — multi-object sizing drift (MenuMgr `BCS @counted` off-by-2) — NOT primarily a debt lever

The queued MenuMgr bug (`BCS @counted` stores disp 0x0c, should be 0x0e; memory
"grind/link found, unfixed") is a *sizing/width* drift: a 2-byte drift earlier in
the proc mis-places the `@counted` label, and the `@`-label resolution
(`resolve` 350–371, nearest-by-distance) then computes the branch off the drifted
position. The root is `m65816._width` (154) / the forward-DP sizing rule, not the
relocation detectors. D1 does **not** unblock it. It is genuine per-instruction
sizing work, ROM-shared and delicate (any `_width` change re-gates buildrom). List
it honestly as *not* dissolved by the headline refactor.

### L4 — import-vs-local `ctlPart` — BLOCKED by D2, the reference-context fix unblocks it

Exactly the D2 case; the reverted commit proves a per-*symbol* rule can't win both
`ctlPart` (import must win, address ref) and `Max_call` (local EQU must win,
immediate ref). The per-reference-context `sym_kind(name, as_addr)` split resolves
both. Small, targeted, ROM-gated.

**Summary:** the two refactors that pay for themselves in capability are the D1
expression-decomposition unification (dissolves 4 detectors, and its superset
power is what lets a diff-with-shift/coefficient-N-cross-object case be emitted at
all) and the D2 reference-context / PROC-scope model (unblocks L2 + L4 + deletes
D4's seg-length injection). L1 is unblocked by a *tiny* D3 correctness fix
(`_defer_shifts` conditionality) independent of the big refactors. L3 is separate
sizing work.

---

## 3. Prioritised plan

Ordering rationale: cheapest + safest + highest-unlock first; every step gates on
the sacrosanct three, and steps that touch ROM-shared code (`omf.py`, `asm.py`,
`m65816.py`) additionally require the corpus not to regress.

### P0 — Fix `_defer_shifts` conditionality (pure correctness; unblocks L1). **Do first.**
- **End state:** `_defer_shifts` runs only when the output emits SUPER relocs (segmented/ExpressLoad). In `merge=True`, the shift resolves via `_eval` op 0x07 (as link.py already does). `_srels` is either used or the dead assignment removed.
- **Why safe:** `omf.py` and the ROM path untouched; linkrom (the byte-exact resolved reference) already proves op-0x07 resolution is correct. Only `linkiigs.link` merge behaviour changes.
- **Gate:** buildrom True / 36 / 61 (unaffected — none use linkiigs); Char.FST + Scrap ExpressLoad'd output byte-identical (segmented path unchanged); kernel `#^Label` now resolves in the merged image.
- **Risk:** low. Only risk is a merged consumer that *relied* on the base-0 placeholder; none does (the resolved image is final).
- **Unlocks:** L1 (resolved-kernel bank byte).

### P1 — De-duplicate expressload onto linkiigs placement/symbol-table (removes latent divergence). 
- **End state:** `expressload()` Pass-1/Pass-2 call shared `linkiigs` helpers (extract `_place(objects, org)` and `_build_symtab(objects, placed, extern)` from `linkiigs.link`, call from both). expressload keeps only its SUPER/HET-specific Pass-3+.
- **Why safe:** the shared helpers are lifted verbatim from the linkiigs versions that already produce byte-exact tools; expressload's *current* behaviour is the *buggier* one (unconditional publicness), so converging on linkiigs is a strict improvement for the multi-object future while identical for today's single-object targets.
- **Gate:** all ExpressLoad'd byte-exact targets unchanged (Char.FST 100%, Scrap/DialogMgr/ListMgr full-file); toolcheck corpus ≥ 90%; ROM three unaffected.
- **Risk:** low–medium. The one behavioural question is whether expressload's *current* unconditional segment-name publicness is load-bearing for any passing single-object case — it is not (single-object gates collapse to the same result). Verify by asserting the pre/post SUPER dictionaries are identical for every currently-passing tool before deleting the copy.
- **Unlocks:** removes the "fix everything twice" tax; prerequisite for multi-object ExpressLoad progress.

### P2 — Reference-context `sym_kind` (unblocks L4 + ctlPart; small). 
- **End state:** `sym_kind(name, as_addr=None)` (or an explicit `use` enum). Emit sites in `omf.py` that already know whether an operand is an address (DC.L table, `sta >x`, JSR/branch target) vs an immediate (`lda #x`) pass that bit. Address-use prefers import/label binding; immediate-use prefers a local EQU. `define_label` stops trying to encode this globally (revert-safe: it keeps recording both, the *decision* moves to the reference).
- **Why safe:** it strictly *adds* information at the decision point that the reverted approach lacked; the revert failed precisely because the bit was missing at define time. It is scoped to `omf.py` emit + `asm.py sym_kind`; ORG'd/ROM operands are addresses today and stay addresses.
- **Gate:** the two golden cases must BOTH hold in one build — WindMgr 100% (was 99%, ctlPart) AND Pro.FST 99%+ no regression (Max_call); ROM three unchanged; full corpus ≥ current.
- **Risk:** medium (ROM-shared `asm.py`/`omf.py`). Mitigate by defaulting `as_addr=None` to today's behaviour and opting in only the two proven emit sites first.
- **Unlocks:** L4 (ctlPart) and the `Max_call` class simultaneously.

### P3 — Unify the four value-detectors into `linear_decompose` + one emitter (THE headline; dissolves D1). 
- **End state:** one `linear_decompose(asm, text) -> ({SYM: coeff}, K)` (the finite-difference primitive the four detectors share), and one `emit_reloc_expr(coeffs, K, shift, segname, …)` that chooses literal / `SEG+off` / by-name / import / `A−B` / `(SEG+rel)*N+K` by the *shape* of `coeffs`. `_linear_reloc`, `_mul_reloc_expr`, `_diff_reloc`, `_pc_rel_const` are deleted; `_expr_for` and `_reloc_elem` become thin callers. The ordering hazards (PC-const-before-linear) vanish because there is one classification.
- **Why safe:** it is a *refactor to a superset* — every current detector output is a special case of reading `coeffs`. Build it behind a comparison harness first: for every DC element / operand in the whole ROM + tool corpus, assert `emit_reloc_expr(linear_decompose(...))` emits **byte-identical OMF ops** to the current path, THEN delete the detectors. The ROM's 36/61 obj-identical set is a byte-level oracle for this equivalence.
- **Gate:** buildrom True / 36 / 61 **exactly**; linkcheck 61; toolcheck ≥ 90%; prodos 100%. The equivalence harness must be green before any detector is removed.
- **Risk:** medium (touches the most ROM-load-bearing file). Bounded by the equivalence oracle: if a single OMF op byte differs on any ROM/corpus element, stop.
- **Unlocks:** the capability the current detectors *cannot* express — a two-label difference *with* a shift, and coefficient-N cross-object refs — which is a prerequisite for the harder ControlMgr/kernel relocations. Also makes P2's address/immediate bit trivial to thread (one emitter, one place).

### P4 — PROC-as-module scope + linkiigs `msym`/`msloc` (unblocks L2; the big one). 
- **End state:** implement `SCOPE_RESOLUTION.md`'s model — PROC/FUNC delimits label locality; a cross-PROC same-module reference resolves at assembly to the in-scope definition and emits `SEGNAME+offset`; EXPORT→file-global, ENTRY→assembly-private, plain→module-local; genuine externals stay by-name for the linker (first-def-wins). Give `linkiigs` the `msym`(entry/export) vs `msloc`(plain-local) distinction `linkrom` already has, and ENTRY-visibility exclusion.
- **Why safe (and why LAST):** it is the deepest change to `asm.py` scope and the linker symbol table; it must ride on P3's clean emitter and P2's reference-context so the new resolutions have one place to be expressed. `SCOPE_RESOLUTION.md` already contains the rules *and* the counter-examples to over-fitting — prove each rule against its table, do not add heuristics.
- **Gate:** buildrom True / 36 / 61; linkrom bank diffs must not increase (ideally 14→fewer); ControlMgr should climb off 54%; every currently-100% tool stays 100%.
- **Risk:** high (scope is the most cross-cutting state). The memory's repeated warnings — naive @-rescoping regressed, blanket undefined→external regressed — apply. This is a multi-session effort, not a single fix.
- **Unlocks:** L2 (ControlMgr / multiply-defined), the linkrom 14-byte tail, and deletes D4's kernelcheck seg-length injection.

### P5 — Retire duplicate linkers onto `linkiigs` (pure cleanup; AFTER P4). 
- **End state:** per the milestones "Future: linker consolidation" — `gslink`/`link.py` calls `linkiigs.link(merge=True)`; `linkrom` expressed as `linkiigs.link(org=bank)` + BANKS ordering + `rommap` as extern, keeping only the ROM-specific multiply-defined scope logic P4 folds in.
- **Why safe:** only once `linkiigs` provably reproduces the ROM banks (needs P4's scope logic) and the tools/FSTs/kernel. Until then, collapsing risks the one byte-exact result for no new capability — the milestones guardrail.
- **Gate:** buildrom True / 36 / 61 at every sub-step; this is the definition of done.
- **Risk:** low IF sequenced after P4; catastrophic if attempted early (see DON'T).

**Pure cleanup vs capability-unlocking:**
- Pure cleanup: **P1** (de-dup), **P5** (linker retire), the *deletion* half of **P3**.
- Cleanup that unlocks capability: **P0** (→L1), **P2** (→L4), **P3**'s superset emitter (→harder relocs), **P4** (→L2 + delete D4 injection).
- Not a debt lever: **L3** (MenuMgr sizing) — separate `m65816._width` work.

---

## 4. The one headline move

**Unify the four `omf.py` value-detectors (`_linear_reloc`, `_mul_reloc_expr`,
`_diff_reloc`, `_pc_rel_const`) into a single `linear_decompose` primitive + one
`emit_reloc_expr`, behind a byte-identical equivalence oracle over the ROM+corpus
(P3).**

It is the headline because the four detectors are provably *the same finite-
difference-the-coefficients operation* wearing four coats (grep-verified: each
bumps a symbol by 0x100/0x1000 and reads back the coefficient), so the unification
is a mechanical refactor to a superset rather than a redesign — and the superset is
exactly what the stuck relocations need (a diff-with-shift, a coefficient-N cross-
object ref) which no current detector can emit. It also makes P2's per-reference
address/immediate bit a one-line thread (one emitter, one decision point) and gives
P4 a single clean place to express scope-resolved references. It dissolves the most
special-cased, most order-sensitive, most ROM-load-bearing surface in the codebase
while being the *safest* big move, because the ROM's 36/61 byte-identical objects
are a ready-made equivalence oracle: build the new path, assert it emits identical
OMF ops for every ROM+tool element, *then* delete the four detectors.

If only one thing is done this phase, do P0 first (trivial, unblocks the resolved
kernel bank byte) and then P3 (the structural headline).

---

## 5. Explicit DON'T list (tempting rationalisations that would risk byte-exactness)

- **DON'T collapse `link.py`/`linkrom.py` onto `linkiigs` before P4.** They are the
  ONLY byte-exact references (linkcheck 61/61, buildrom True). `linkrom`'s
  `msym`/`msloc`/`objsegbase`/`linkidx` model encodes multiply-defined-label
  semantics `linkiigs` lacks; `SCOPE_RESOLUTION.md` proves no single heuristic
  replaces it. Collapsing early trades the one byte-exact result for no capability
  (milestones guardrail).
- **DON'T re-apply the `ctlPart` EQU-over-import rule as a per-symbol rule** (the
  `048adb7`→`d90f7e4` loop). It is mathematically un-winnable per-symbol: `ctlPart`
  needs import-wins (address ref), `Max_call` needs local-EQU-wins (immediate ref),
  same name shape. Only the per-reference-context bit (P2) resolves both. Any
  define-time-only fix WILL regress one of them.
- **DON'T "simplify" `_defer_shifts` by making it always resolve the shift** (the
  naive inverse of P0). That would re-break the ExpressLoad'd tools (Char.FST 100%,
  the whole 99% tier) which *require* the deferred base-0 placeholder + SUPER
  type-27. The fix is *conditionality* (defer for segmented/ExpressLoad, resolve
  for merged), not removal.
- **DON'T unify the detectors by "just always emit an EXPR and let the linker
  compute it."** Memory + `SCOPE_RESOLUTION.md` note CONST-vs-EXPR and BEXPR-vs-
  LEXPR framing is link-equivalent but **not byte-identical**; the ROM's 36/61 obj
  set demands the *exact* record type/shape. The unification must reproduce today's
  literal-vs-reloc *and* record-type decisions byte-for-byte (that's what the P3
  oracle enforces), not relocate everything.
- **DON'T make `needs_reloc`/`_expr_for` treat all undefined idents as external at
  the current resolution.** Repeatedly regressed (memory: objcheck 9→1; "blanket
  undefined→external"). Most "undefined" names are gsasm resolution gaps, not
  externals. Fix the scope model (P4) first; then undefined→external is safe.
- **DON'T chase the MenuMgr `BCS @counted` / firmware `@`-label edges by naive
  rescoping.** Memory's most-repeated warning ("naive @-label rescoping",
  "HIGH REGRESSION RISK"). It is a `m65816._width` sizing drift (L3), not a scope
  or relocation bug — different subsystem.
- **DON'T delete the kernelcheck PROC-ORG gap/pad compensation until the
  `PROC ORG expr,noskip` sizing gap is actually fixed** in `asm.py`. It papers over
  a real gap; removing the harness compensation before the core fix regresses the
  kernel harness. It's a marker (D4), safe to keep until P4-era work closes it.
- **DON'T touch `m65816._width` (dp/abs/long sizing) as part of the relocation
  refactor.** It is orthogonal, ROM-shared, and the single most cascade-prone rule
  (one wrong width shifts every later label). Keep sizing work (L3) in its own
  gated change, never bundled with an `omf.py` relocation refactor.

---

## Appendix — key code locations (verified this review)

- Detectors: `gsasm/omf.py` `_linear_reloc`:147, `_mul_reloc_expr`:177, `_diff_reloc`:217, `_pc_rel_const`:281, `_expr_for`:311, `_reloc_elem`:680(in `emit_segment`:562), predicates `_in_org_seg`:491/`_branch_xseg`:501/`_cross_seg_label`:535/`_undef_external`:545/`_ctl_external`:553.
- Symbol model: `gsasm/asm.py` stores 191–224, `_symkey`:306, `resolve`:340, `define_label`:662, `needs_reloc`:709, `sym_kind`:734, `is_reloc`:758. Sizing: `gsasm/m65816.py` `_width`:154.
- Linkers: `gsasm/link.py` `_eval`:22/`_build_body`:84; `gsasm/linkiigs.py` `_defer_shifts`:80 (unconditional call:332, `_srels` unused), place:161–176, symtab:210–319; `gsasm/expressload.py` duplicated place:410–422 / symtab:433–484 (`sym.setdefault(segname)` unconditional:440), `_defer_shifts` call:501; `work/linkrom.py` `resolve_name`:171 / `eval_expr`:200 (shift op:223) / `place`:96.
- Harness gaps: `work/kernelcheck.py` `_build_header_content`:366 (seg-length extern inject:383–406), `_build_with_end_padding`:411 (PROC-ORG compensation).
- Evidence trail: ctlPart fix `048adb7`, revert `d90f7e4`; scope model `work/SCOPE_RESOLUTION.md`; roadmap `docs/GSOS_MILESTONES.md` "Future: linker consolidation".
