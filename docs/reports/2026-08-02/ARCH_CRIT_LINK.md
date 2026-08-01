# Architecture Critique — Link/Package Layer (linkiigs.py, expressload.py, makebin.py)

Scope: `gsasm/linkiigs.py` (929 lines), `gsasm/expressload.py` (2316 lines),
`gsasm/makebin.py` (240 lines), and their tests, as of commit `b946e94`
(HEAD). Byte-exactness is not disputed — every claim below is about the code
as software: whether the next change (not this week's, the one after) is
findable, checkable in isolation, and hard to get subtly wrong.

`docs/REFACTORING_DEEP_DIVE_2026-07-30.md` (D3) correctly flags
`_build_multiseg_output` as the top decomposition target and correctly
declines to prescribe class rewrites. It **undercounts the risk**: it treats
the function as one big thing to split into named phases, but the harder
problem is that the phases *already know about each other's internal state*
(mutable `merged_arr`, per-group `grp_body_syms`, the `_group_of` closure) in
ways a mechanical "extract named phases" pass will not fix, and it does not
mention the opts-dict API surface, the single/multiseg semantic split, or the
`_build_symtab` precedence stack at all — all of which got *harder*, not
easier, in the three behaviors that landed this week (SymTab.kinds, the
const-shift `abs_syms` fix, and the module-privacy rule). Those three are
exactly the kind of change this architecture will keep inviting, and D3 has
no plan for them.

---

## Findings, ranked by (cost) × (trip likelihood)

### F1 — HIGH. `link()`/`expressload()` use two different opts key names for the identical parameter, and production code now monkey-patches a module function to route around it

**Receipts:**
- `gsasm/linkiigs.py:578-579` — `_place(objects, base_org, order=opts.get('seg_order'))`
- `gsasm/expressload.py:2291-2292` — `_linkiigs._place(objects, 0, order=opts.get('order'))`

Both call sites feed the exact same `_place()` parameter (`order:
list[tuple[obj_idx, seg_idx]]`). `linkiigs.link` reads it from
`opts['seg_order']`; `expressload.expressload` reads the same concept from
`opts['order']`. There is no shared constant, no alias, nothing that would
make a typo or a copy-paste of an opts dict from one call to the other fail
loudly instead of silently placing everything in default sequential order.

**This is not hypothetical — the codebase has already had to work around it
three times:**

- `work/toolcheck.py:473-474` builds `seg_order` and calls
  `linkiigs.link(objects, opts={'merge': True, 'seg_order': seg_order})`;
  four lines later `work/toolcheck.py:490-491` reuses the *same local
  variable* against `expressload(objects, opts={'order': seg_order})`. The
  docstring at `work/toolcheck.py:484` has to spell out the synonym by hand:
  `` `order` == linkiigs' `seg_order` ``.
- `work/diskcheck.py:545-558`, building an MSDOS.FST full-file ExpressLoad
  image, needs the placement order that `linkiigs.link_lib` computes
  internally for a `-lib` extraction (`gsasm/linkiigs.py:772-830`,
  variable `order` at line 772). `link_lib()` never returns that order — it
  only ever hands it to `link()` via `lopts['seg_order'] = order`
  (`linkiigs.py:829`) and discards it. So `diskcheck.py` **monkey-patches
  `linkiigs.link` itself**:
  ```python
  def _spy(objs, opts=None):
      captured['seg_order'] = (opts or {}).get('seg_order')
      return orig_link(objs, opts)
  linkiigs.link = _spy
  try:
      linkiigs.link_lib(objects[:1], objects[1:], opts={'merge': True})
  finally:
      linkiigs.link = orig_link
  return expressload(objects, opts={'order': captured['seg_order']})
  ```
  (`work/diskcheck.py:548-558`). That is a global-function swap, in a build
  harness, to extract a value that a well-formed API would simply return.
- `work/generality_check.py:72` maintains a separate list of "linkiigs opts
  keys" as documentation, because there is nowhere else in the code where the
  full opts vocabulary is declared.

**Failure narrative:** a future caller wires a new full-file builder, copies
the `opts={'seg_order': ...}` pattern from a nearby `linkiigs.link` call
because it's the one they can see, passes the same dict to `expressload()`,
and gets the default sequential placement instead of the intended dead-strip
/ library order. Nothing raises. The output differs from gold by however much
the wrong segment order changes; the failure surfaces as a diskcheck/gate
byte-mismatch with no clue that the opts key was the cause, because both
functions accept the dict and both run to completion.

**Verdict:** the *byte-exact result* the monkey-patch produces is fine — the
project's own standard would reject "equivalent" fixes here, and this isn't
one; the bytes are right. What's wrong is that a first-class linker
capability (`link_lib`'s extraction order) has no accessor, so a test harness
had to reach into the module's global namespace to get it out. That is a
software defect independent of any byte gate.

---

### F2 — HIGH. `_build_multiseg_output` (752 lines, `gsasm/expressload.py:1430-2181`) interleaves eight concerns with no phase boundary a reader can trust

Confirmed length via AST: `_build_multiseg_output` spans lines 1430–2181
inclusive = 752 lines, one function. (D3 measured 742 before this week's
additions; the kind-table exemption note at `expressload.py:1682-1691` and
the module-privacy `_fallback_sym` block at `1570-1601` are net-new growth in
the *same* function since the doc was written — the decomposition got
harder, not closer, in the interval D3 said was "no longer speculative.")

Concerns physically inside the one function body, in order of appearance:
1. Group formation from `opts['obj_group']` (1455-1469)
2. Per-group name/kind override resolution (1472-1473, repeated at
   2106-2113)
3. Group boundary table + the `_group_of` closure (1478-1504)
4. `~JumpTable` slot arithmetic — non-dynamic/dynamic boundary validation,
   `_final_segnum` closure (1523-1568)
5. The `_fallback_sym` combo-group workaround (1596-1601)
6. Per-group body construction with group-rebased symbols (`_adj`, `_adj_og`,
   1626-1673)
7. Case-A standalone / cross-group reclassification, including a **second,
   independent walk of every record in the group** to build `expr_at`
   (1737-1752) that duplicates the scan `_scan_standalone_relocs` and
   `_scan_relocs` already performed moments earlier, because the classifier
   needs the *pre-deferred, pre-adjusted* op-list back
8. Case-B (flagged-addend) reclassification (1804-1830)
9. Final SUPER-type renumbering with THREE separate branches for stype 1
   (dc.l / cross-group interseg), stype 27 (bank byte — including a **third**
   independent record walk at 1938-1990 to recover `sym_joint`, because
   neither `expr_at` nor `grp_body_syms` carries what this branch needs), and
   stype 0 (low word) (1839-2089)
10. HET-entry-metadata assembly and `~JumpTable` segment insertion
    (2102-2181)

**Trace one reloc's journey** (a cross-group `dc.l Target` reference into a
DYNAMIC group, jt_entries enabled — the ordinary Tool016/018 shape):

1. `_scan_relocs(group_placed)` classifies it as stype 1 by re-walking every
   record in the group (table: `group_relocs_raw`).
2. The offset is looked up in `expr_at` (table 2), a *second* from-scratch
   walk of the same records built earlier at line 1737, to recover `(size,
   ops, seg_i)` because the record tuple itself was discarded by step 1.
3. `ops` is evaluated against `grp_body_syms[seg_i]` (table 3), itself
   `{**_fallback_sym, **og_seg}` — `_fallback_sym` (table 4) is
   `{**merge-of-every-obj_globals, **sym}` (tables 5 = `obj_globals` list,
   6 = `sym`/SymTab).
4. The result is classified against `group_bases`/`group_ends` (tables 7, 8)
   via `_group_of`.
5. If the target is DYNAMIC, `(_final_segnum(tgt_group), off_in_tgt)` is
   looked up in `jt_index` (table 9), built from `jt_entries_opt` (table 10)
   — a list the caller derived with a *different* algorithm in
   `work/toolcheck.py`'s `_link_jt_tool`, not visible from this file at all.
6. The 3-byte field is patched directly into `merged_arr` (table 11, the
   group's own mutable byte buffer, already patched once by the case-A pass
   moments earlier).
7. The relocation offset lands in `final_relocs` (table 12), later merged
   with `standalone_group` (table 13) and sorted for emission.
8. The group's metadata is packed into `out_groups` (table 14) for
   `_build_het_lconst`, a *separate* ~300-line codec (`1011-1181`) with its
   own template/spill/segnum-conversion bookkeeping the reader must hold in
   mind to know whether anything above is even reachable in the file's final
   byte layout.

That is 12-14 distinct tables/closures a single relocation's value is a
function of, inside one function, with two of those tables existing purely
because an earlier pass in the *same function* threw away information a
later pass needed and had to re-derive it by re-walking the OMF record
stream. This is the real cost D3 didn't price in: it isn't 752 lines of
sequential phases, it's 752 lines where phase 7 quietly depends on phase 1's
raw input surviving past phase 1's own consumption of it.

**Where this is load-bearing, and where it isn't:** the record-shape
handling (LEXPR/BEXPR/EXPR/CONST/LCONST/DS/RELEXPR walking) is copied
almost verbatim in at least four places in this function (`expr_at`
construction at 1741-1752, the `sym_joint` walk at 1938-1990, plus
`_scan_relocs`/`_scan_standalone_relocs` themselves). None of that repetition
is byte-load-bearing — it is the SAME walk of the SAME record stream
computing different projections of it. A shared one-pass body-offset walker
that yields `(abs_off, size, ops, seg_i)` once, memoized per group, would
let `expr_at` and the `sym_joint` search collapse into dict lookups with zero
behavior change. That is a real, low-risk extraction the deep-dive's
suggested `_plan_output_groups` / `_build_group_image` split does not
capture because it's phase-oriented, not redundancy-oriented.

---

### F3 — HIGH. The single-path/multiseg asymmetry has no written contract; the "spec" is two divergent implementations plus scattered comments explaining where they diverge

`_build_single_output_seg` (`expressload.py:1262-1427`, 166 lines) and
`_build_multiseg_output` (1430-2181, 752 lines) both build ExpressLoad
output from the same `placed`/`sym`/`obj_globals` inputs, and they encode
**different rules for the same relocation classification problem** with no
shared statement of what the rule actually is:

- Single-path threads a `kinds` table into `_needs_reloc`/`_reloc_weight`
  (`expressload.py:1296-1315`, `_sym_kinds`/`body_kinds`) so an
  EXPORT-EQU reference contributes reloc-weight 0 and is suppressed at scan
  time.
- Multiseg path explicitly does **not** do this — `_scan_relocs(group_placed)`
  is called with no kind table (`expressload.py:1692`), and the reason is a
  comment, not a type or an assertion: *"Kind-suppressing the site at scan
  level starves that body patch and regresses TS2 at 0x88a exactly as the
  diagnosis's §5 collision analysis predicted"* (1682-1691). The actual
  mechanism that makes multiseg correct instead is `_group_of(target) is
  None` dropping the record **after** classification, in three separate
  branches (stype 1 at 1871-1875, stype 27 at 1992-2006, stype 0 at
  2062-2066) — three independent call sites that all have to remember to
  check for `None` correctly, versus one shared suppression rule on the
  single path.

The commit history proves this isn't a stable design choice being
documented after the fact — it's a scar from an actual regression. From
`git log -p 9d82fba`:

> "the first implementation regressed TS2 at 0x88a exactly as the
> diagnosis's §5 collision analysis predicted, and the gate caught it — now
> documented in place."

That is: the natural, uniform fix (thread `kinds` into both paths
identically) was tried, broke a gated golden byte-comparison, and the
resolution was to give the two paths **different, undocumented-except-in-a-
comment semantics** rather than find the invariant that makes both correct
under one rule. There is no `docs/design/` note stating "single-path
suppresses at scan time via kind; multi-path suppresses at classification
time via group membership; these are equivalent because X" — the equivalence
argument, if one exists, lives only in prose comments at two physically
separate locations in one 2300-line file. A reviewer (or an LLM) asked to
add an eighth relocation class has no artifact to check their reasoning
against except re-deriving why TS2 regressed the first time.

Same shape, second instance, THIS WEEK: `linkiigs._defer_shifts`'s
`abs_syms` parameter (`linkiigs.py:78-134`) is populated three different ways
across three call sites —
`linkiigs.link` (608-611, GEQU names ∪ caller `abs_extra`),
`_build_single_output_seg` (1311-1312, the per-object `kinds`-derived `equ_names`),
and `_build_multiseg_output` (1667, **no `abs_syms` argument at all** —
defaults to `frozenset()`, meaning const-shift resolution is silently
disabled on the multiseg path even though the docstring at `linkiigs.py:94-97`
explains why it should matter). Whether that's correct (because
`_group_of(None)` catches it downstream, per the comment at
`expressload.py:1995-2006`) or an oversight is *not verifiable by reading
`_defer_shifts`* — you have to already know the whole multiseg
classification story to know the omission is intentional.

**Verdict:** each individual divergence is defensible in isolation (the
comments are honest and specific, and the TS2 regression is real evidence
the naive unification is wrong). The problem is structural: there is no
single artifact — not a docstring, not a table, not a shared predicate
function — that states the semantics both paths must satisfy, so every new
relocation behavior has to be independently discovered to be different on
each path, at the cost of a broken gate, before it's safe to land. That cost
just paid out once (this week) and will pay out again the next time someone
adds a ninth relocation class.

---

### F4 — MEDIUM-HIGH. `_build_symtab`'s five-ish binding rules are real, correctly reasoned, and unformalized

`linkiigs._build_symtab` (`linkiigs.py:264-528`, 265 lines — up from D3's
234, again net growth since the doc) interleaves, per object, in link order:

1. **First-wins** for single-object links, segment names and interior labels
   (370, 439).
2. **ENTRY-vs-EXPORT** visibility: an ENTRY shadowed by a same-named EXPORT
   elsewhere stays private (`_all_exports`, 337-340, 423-425).
3. **Combo-object `setdefault`** vs **real-object override** for GLOBAL
   records, decided by `asm is None` (514-517) — a "combo" pre-concatenated
   blob keeps first-definition, a real per-file object overwrites.
4. **Module privacy**: a plain interior label whose folded name collides
   with another object's EXPORT is intra-object-only, "module-private;
   export wins" (453-458) — landed this week, per the memory brief.
5. **Case-collision repair**: a local label that case-folds onto a public
   segment name republishes the segment's placement base instead of the
   label's own value (354-373).
6. **Kind threading** (`'label'`/`'equ'`) riding through every one of the
   above at the *same* precedence point as the value (also this week).

Each rule has a real, cited, single-example falsifying case in a comment
(Finder GetFileInfo for #2, notesynth UpDate for #5, ATP1/epson for the
import-satisfies-locally rule inside `link()` itself at 640-650, TS2's
Patch2 for #3). That is good evidence discipline — nothing here reads as
guesswork. But the ordering **as a system** is nowhere stated as a system:
it exists only as "first do (a), then (b) [these two interleaved per
object], then after all objects do (c), then (d)" prose split across four
non-adjacent comment blocks, with the actual precedence enforced by
call-order in Python (`_kind_setdefault` vs `_kind_override`) rather than by
any explicit rank.

**Could you write the truth table?** Approximately — 6 boolean-ish axes
(single-object? public-seg? clobbered-by-collision? exported? entry-only?
combo-object?) times 2 outcomes (goes in `sym`? goes in `obj_globals[oi]`?)
is not small, and at least one cell (module-private label vs GLOBAL-record
combo-setdefault, when the SAME name arrives via both pass (b) and pass (c)
for a combo object) is resolved only by which one runs first in the
function body, not by an explainable rule. That's not necessarily wrong —
but nobody has written the table down, so "is this the seventh rule or does
it collapide with rule three" is a question only answerable by re-reading
265 lines of interleaved comments and re-deriving the ordering.

**Where rule #7 would go, and what it would break:** the natural next rule
(hypothetically: a WEAK import that should NOT satisfy-locally the way
`link()`'s 640-650 rule does) would have to be added to `link()`'s Pass 3
loop, which already reasons about `local_defs = exports | entries |
seg_names` (644-645) built from `_asm.imports`/`_asm.exports` — completely
separate machinery from `_build_symtab`'s own export/entry set
(`_all_exports`, 337). Those two sets are computed independently by two
different functions from the same underlying `Asm.exports`/`Asm.entries`,
and nothing enforces they stay consistent if one is extended without the
other. A rule #7 that only touched `_all_exports` would silently not apply
inside `link()`'s Pass 3, and vice versa — exactly the kind of gap that only
shows up as a gate regression on some future golden file, the same way the
TS2 kind regression did.

---

### F5 — MEDIUM. `SymTab(dict)` + `.kinds` sidecar is a workable but leaky design, and the code already shows the leak

`linkiigs.py:224-262`. `SymTab` subclasses `dict` and bolts on a parallel
`.kinds: dict[str,str]` attribute, kept in lockstep only through two
disciplined helper functions, `_kind_setdefault`/`_kind_override`
(251-261), that every writer *must* remember to call instead of plain
`d[k]=v` / `d.setdefault(k,v)`. Nothing enforces that discipline at the type
level — a future contributor extending `_build_symtab` (or writing a sixth
call site elsewhere) who does `sym[label] = value` directly produces a
value with no matching `.kinds` entry, and `kinds.get(name)` silently
returns `None` rather than raising, which downstream reads as "not an
equ" — i.e., the failure mode is silent misclassification, not a crash.
That's the worst kind of API-discipline requirement: unenforced, and its
violation looks like ordinary correct code.

The leak the class's own docstring half-acknowledges (`linkiigs.py:224-244`)
is dict-op erasure: `{**a, **b}` on two `SymTab`s produces a **plain
`dict`**, silently dropping `.kinds` — Python's dict-merge protocol has no
hook for subclass metadata. The code works around this by hand:

- `expressload.py:1301-1302`: `local_kinds = (_sym_kinds if not og else
  {**_sym_kinds, **getattr(og, 'kinds', {})})` — a second, parallel merge
  the caller must remember to perform every time it merges the symbol
  tables themselves, using `getattr(..., 'kinds', {})` defensively because
  `og` might be a plain `SymTab()` with an empty dict body but the code
  can't statically know that.
- `linkiigs.py:624` (`link()`'s Pass 3): `local_sym = {**sym, **og}` merges
  the *values* with no kinds counterpart at all — this call site doesn't
  need kinds today, but that's exactly the kind of omission that's
  invisible until something downstream needs `local_sym.kinds` and gets a
  plain dict with no such attribute, an `AttributeError` at a distance from
  where the merge happened.

**Honest alternative assessment:** a `NamedTuple`/dataclass-of-two-dicts
(`{'values': ..., 'kinds': ...}`) would make every merge site visibly do
two merges instead of accidentally doing one; a real `ChainMap`-based
design would avoid needing `{**a,**b}` at all (no merge, no erasure risk,
and `.kinds` could ride the same way) but would change the *iteration order
and mutation semantics* of every existing consumer of `sym` as a plain
dict, which is a bigger, riskier change than this layer's byte-exactness
discipline should accept casually. Given the project's "don't accept
byte-equivalent arguments" standard, dict-subclassing-with-parallel-attribute
is a defensible choice **for how it got here incrementally** (kinds was
added to an existing dict-typed API without changing every consumer's type
signature) — but it is accruing exactly the kind of manual-parallel-merge
debt that will make an eighth SymTab consumer wrong by default rather than
right by default.

---

### F6 — MEDIUM. `_defer_shifts` is a cross-module utility called with three different argument shapes and no shared vocabulary for what's being passed

`linkiigs._defer_shifts(recs, abs_syms=frozenset())` (`linkiigs.py:78-134`)
lives in `linkiigs.py` but is called from `expressload.py` twice
(1312, 1667) with different `abs_syms` derivations (see F3), and from
`linkiigs.link` itself (615) with a third derivation. The function's own
docstring is excellent and specific about *why* shifts defer — but "why"
lives in the callee; "which symbols count as `abs_syms` for THIS call site"
lives in three different comments at three different call sites in a
different file, with no enum, constant, or named predicate connecting them.
This is the same shape of problem as F3 (semantics fragmented across call
sites) at a smaller scale, worth fixing together with F3 rather than
separately.

---

### F7 — MEDIUM. `makebin.py` has zero dedicated unit tests and duplicates its own GEQU-resolution logic

- No file under `tests/` imports `gsasm.makebin` or `gsasm.makebin.*` at all
  (confirmed by search). `makebin`/`makebin_segments`/`overlay`/`catenate`
  are exercised only transitively, through full build harnesses
  (`work/kernelcheck.py`, `work/basiccheck.py`, `work/expressloadcheck.py`)
  that compare a whole kernel/tool image against gold. A regression in
  `makebin_segments`'s org-override logic (`makebin.py:147-198`) that
  happens to cancel out against some other harness behavior, or that only
  affects a code path none of the three harnesses currently exercise (e.g.
  an `orgs` override for a segment name that collides case-insensitively —
  `orgs = {k.upper(): v ...}` at `makebin.py:167`, with no test of what
  happens if two distinct segments fold to the same upper name), has no
  test that would catch it in isolation. This is the layer's smallest file
  and its thinnest test story.

- `_build_sym` (`makebin.py:79-115`) and the inline symbol-table-building
  block inside `makebin_segments` (`makebin.py:169-191`) are near-verbatim
  duplicates of the same two-pass GEQU-resolution logic (build `sym` by
  walking segments and accumulating `gequ_pending`, then resolve GEQUs in
  two passes for forward references). `makebin_segments` does not call
  `_build_sym` — it reimplements it inline with one difference (org comes
  from `orgs.get(...)` instead of sequential placement). This is exactly
  the kind of low-risk, purely-mechanical simplification D3's Opportunity 1
  pattern calls for elsewhere in the repo, just not noticed here because
  `makebin.py` is small enough to have escaped the "largest files" table
  that seeded D3's whole survey.

---

### F8 — LOW-MEDIUM (but structurally interesting). The fixture story for this layer is entirely golden-byte, end-to-end, through the public API — there is no isolated unit test of any internal phase

Every hand-authored test in `tests/test_linkiigs_*.py` and
`tests/test_expressload_*.py` (9 files, 1439 lines total) calls
`linkiigs.link`, `linkiigs.link_lib`, or `expressload.expressload` as a
black box and asserts on the final byte stream — computed either against a
hand-derived expected byte sequence (e.g. `test_expressload_case_b.py`'s
explicit struct-packed expectation, deliberately "not by calling
gsasm.expressload a second time for the expected side" per its own
docstring — genuinely good practice) or against golden Apple-original
artifacts via the `work/*check.py` harnesses. **No test calls
`_build_symtab`, `_scan_relocs`, `_group_of`, `_defer_shifts`,
`_reloc_weight`, or `_build_multiseg_output` directly.** That means:

- Every one of F2-F6's internal-boundary issues can only be *detected* by a
  full pipeline run producing wrong bytes somewhere downstream — never by a
  focused test that pins one function's contract. The TS2 regression this
  week was caught by the gate (`work/gate.py`, full-pipeline byte
  comparison), which is exactly correct as a *final* safety net, but it
  means the feedback loop for "did my change to `_reloc_weight` do what I
  think" is "assemble real object files, link a real multi-hundred-KB tool,
  diff it against a captured Apple binary" — minutes, not milliseconds, and
  the failure (a byte mismatch at some offset) doesn't localize to which of
  the 12+ tables in F2's trace produced the wrong value.
- This is a reasonable trade **for byte-exactness work specifically**
  (`docs/REFACTORING_DEEP_DIVE_2026-07-30.md`'s own stance: "the safest move
  is often to improve isolation and tests before changing shape" — Executive
  Summary item 1) — but it means every future internal refactor of this
  layer (including D3's own recommended `_plan_output_groups` extraction)
  will be validated *only* by the same slow, non-localizing full-pipeline
  gate, with no faster inner-loop check that the extraction preserved
  behavior before the 10-minute gate run confirms or denies it.

---

## The three refactors worth staking time on

Ranked by (cost saved) × (probability this class of bug recurs), given F1-F8
above.

### 1. Return `link_lib`'s placement order as a first-class value; unify the `order`/`seg_order` opts key

**Why first:** lowest implementation risk of the three (it's an API-surface
fix, not a semantics change — no relocation classification touched), and it
directly retires the monkey-patch in `work/diskcheck.py:545-558`, which is
the single ugliest thing this review found. It also removes the one
opts-key hazard (F1) that has already caused three separate hand-written
workarounds.

**Shape:**
- Add `order: list[tuple[int,int]]` to `link_lib`'s return — either as a
  second return value (`bytes, list[tuple[int,int]]`, requiring every
  caller update) or, lower-risk, expose it via a new `link_lib_order(roots,
  libs)` pure function that `link_lib` itself calls internally and that
  `diskcheck.py`/callers can call directly instead of spying on `link`.
  Prefer the second: zero signature change to `link_lib`, so it cannot
  regress any existing caller's return-unpacking.
- Pick ONE opts key name (`seg_order`, since it's the more precise name —
  "order" is used ambiguously elsewhere for HET/segment output order too)
  and accept the other as a deprecated alias inside `_place`'s own call
  sites for one release, with a comment pointing at the rename, OR do a
  single mechanical rename across `expressload.py`, `toolcheck.py`,
  `diskcheck.py` in one commit (5 call sites total, all found above).

**De-risking / zero-drift plan:**
1. Add `link_lib_order()` returning the same `order` list `link_lib`
   already computes internally at `linkiigs.py:772` (currently discarded
   after being handed to `link()`) — pure refactor, `link_lib` calls the new
   function and its own behavior is provably unchanged (it's the same list,
   same code path).
2. Replace `work/diskcheck.py:545-558`'s monkey-patch with a direct call to
   `link_lib_order(...)`. Capture `python3 work/diskcheck.py` stdout before
   and after; must be byte-identical (it's not a byte-producing path, it's
   the harness's own reporting, but "stdout unchanged" is cheap and catches
   accidental control-flow changes).
3. Rename `opts['order']` → `opts['seg_order']` in `expressload.py:2292` and
   every `work/` caller in the same commit; grep for the old key name after
   to confirm zero remaining references.
4. Full gate: `python3 work/gate.py` (must show zero metric movement —
   this refactor touches no relocation math) then `python3 work/gate.py
   --full` for `diskcheck`, then `python3 work/buildrom.py`.
5. Acceptance: gate baseline unchanged (not just "not worse" — this must be
   a strict no-op on bytes since nothing about placement math changed).

### 2. Write the `_build_symtab` precedence as data, not as ordered code with prose commentary

**Why second:** medium risk, high leverage — this doesn't touch bytes at
all if done as a *documentation-first* step, and it directly de-risks F3
and F4 together (the single/multiseg semantic split and the symtab
precedence stack are both instances of "the rule lives only in comments").

**Shape:**
- Before touching `_build_symtab`'s code, write the truth table F4 asks
  for as a real artifact: `docs/design/SYMTAB_PRECEDENCE.md`, one row per
  (single-object?, public-seg?, clobbered?, exported?, entry-only?,
  combo-object?) combination that actually occurs in the golden corpus
  today (not all 2^6 — only the reachable ones, which is probably 8-10
  rows given several axes are correlated), with the resulting `(sym[name],
  obj_globals[oi][name], kind)` outcome and a one-line citation of which
  golden file falsifies the alternative.
- Then, and only then, consider extracting each of the 6 numbered rules in
  F4 into a named predicate function (`_is_module_private(...)`,
  `_is_case_collision(...)`, etc.) that `_build_symtab` calls in the
  documented order — this is the "decompose into named phases" move D3
  recommends for `_build_multiseg_output`, applied to the *other*
  under-documented function of comparable importance that D3 didn't flag
  (234→265 lines and still the second-largest function in `linkiigs.py`).
- Do the SAME exercise for F3 (single vs multiseg relocation-suppression
  semantics): a short `docs/design/RELOC_SUPPRESSION.md` stating, as one
  sentence each, "single-path suppresses an EXPORT-EQU reference at
  scan-time via SymTab.kinds; multiseg suppresses the same case at
  classification-time via `_group_of(target) is None`; these differ because
  X" — with the TS2 falsifying case cited by both sentences so an eighth
  relocation-class author is not required to independently rediscover why
  the paths diverge.

**De-risking / zero-drift plan:**
1. Docs-only commit first — zero code change, zero risk, reviewable purely
   on "does this table match what `_build_symtab` actually does today"
   (spot-check 3-4 rows against the code by hand).
2. Extract predicate functions ONE at a time, each its own commit, each
   verified byte-identical to `git diff`-inspectable "the extracted
   function's body is a literal cut of the inline code, no logic changed."
   After each extraction: `python3 tests/test_linkiigs_import_case_shadow.py`,
   `tests/test_expressload_export_equ.py` (the two most on-point existing
   tests), then `python3 work/gate.py`.
3. Add the missing unit-test layer F8 identifies AS PART of this refactor,
   not after: once `_build_symtab` calls named predicates, write direct
   unit tests of 2-3 of those predicates against hand-built `Asm`-like
   fixtures (not full assemble-and-link), so the NEXT precedence change has
   a millisecond-scale check before the 10-minute gate run. This is the
   concrete payoff of F8's finding — it only becomes actionable once the
   monolith is decomposed enough to have something narrow to unit-test.
4. Full gate + `buildrom.py` after every commit in the sequence, not just
   at the end — this is a "many small graded commits" refactor precisely
   because each individual predicate extraction is small enough to bisect
   if the gate does move.

### 3. Collapse `_build_multiseg_output`'s three independent record-stream walks into one memoized walker

**Why third, and scoped narrower than D3's recommendation:** D3 recommends
extracting `_plan_output_groups`/`_plan_jump_table`/`_build_group_image`/
etc. as named phases. That's the right eventual shape, but F2 shows the
actual highest-value, lowest-risk piece of it is much smaller: the function
re-walks the same OMF record stream from scratch three times
(`_scan_relocs`/`_scan_standalone_relocs`'s internal walk, `expr_at`'s walk
at 1737-1752, and the `sym_joint` search's walk at 1938-1990) to recover
three different projections of the same data. Unifying those into one
pass is pure mechanical deduplication — it changes nothing about
placement, classification, or the single/multiseg semantic split (F3 stays
exactly as-is, deliberately, per "what not to change" in D3), so it is safe
to do BEFORE the larger named-phase extraction D3 recommends, and it makes
that later extraction easier (fewer implicit cross-phase dependencies to
carry into the new function boundaries).

**Shape:**
- Add one helper, `_walk_group_exprs(group_placed) -> dict[abs_off,
  (size, ops, seg_i)]`, computed once per group and threaded through to
  every place that currently re-derives it (`expr_at` becomes this dict
  directly; the `sym_joint` walk at 1938-1990 looks up `expr_at[abs_off]`
  instead of re-scanning).
- Leave `_scan_relocs`/`_scan_standalone_relocs`'s own internal walk alone
  for this first pass (they're called from BOTH single- and multi-seg
  paths with different kind-table arguments per F3 — unifying them with
  the new walker is a separate, riskier follow-on once #2's documented
  contract exists to check it against).

**De-risking / zero-drift plan:**
1. Add `_walk_group_exprs` as a pure function with the exact same walking
   logic already at `expressload.py:1741-1752`, cut-and-pasted (not
   rewritten) so a diff review can confirm it's byte-for-byte the same
   traversal.
2. Replace the `expr_at` construction (1737-1752) with a call to it —
   zero behavior change, `expr_at`'s consumers are unchanged.
3. Replace the `sym_joint` walk (1938-1990) with a lookup into the SAME
   dict instead of its own re-scan — this is the one place behavior COULD
   differ if the two walks weren't actually computing the same thing, which
   is exactly why this step needs its own isolated gate run.
4. After step 3 specifically: full `python3 work/gate.py --full` (not just
   the fast corpus) since the stype-27 bank-byte branch this touches is
   exercised by TS2/TS3/Tool016/Tool018 — the multi-object, multi-group,
   jt_enabled fixtures — which the fast gate corpus may not all cover.
   Confirm the baseline's `good`/`bad` counts are bit-for-bit unchanged, not
   just non-regressing, since this step's whole claim is "these two walks
   were redundant," and any metric movement (even improvement) falsifies
   that claim and means the walks were NOT interchangeable and the change
   must be reverted and re-examined rather than accepted.
5. `python3 work/buildrom.py` end to end as the final confirmation before
   calling this closed.

---

## What NOT to do

- Do not unify `_scan_relocs`'s kind-table behavior across single/multiseg
  paths as part of any of the above (F3's whole finding is that this was
  tried, broke TS2, and the fix was documented divergence, not code
  unification). Refactor #2 is explicitly about writing that divergence
  down, not erasing it.
- Do not replace `SymTab(dict)` with a `ChainMap` or dataclass mid-stream
  (F5) — it would touch every one of this layer's consumers' type
  assumptions at once, which is a much bigger blast radius than the
  documentation/predicate-extraction work above, for a design smell that is
  currently manageable (two disciplined helper functions) rather than
  actively causing failures.
- Do not attempt `_build_multiseg_output`'s full named-phase split (D3's
  recommendation) in one commit. Do refactor #3 first; it shrinks the
  function and removes the cross-phase data dependencies that make a full
  phase split risky today.
