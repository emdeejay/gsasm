# Hostile architecture review: gsasm/asm.py, omf.py, expr.py, m65816.py

Scope: the assembler core as *software*, not as a byte-exactness oracle (that
part is proven and out of scope). I read `docs/REFACTORING.md` and
`docs/REFACTORING_DEEP_DIVE_2026-07-30.md` first; I do not re-litigate R6
(dispatch split) or R7 (define_label predicates) — both are landed and, on
inspection, landed honestly (see "What's actually fine" below). I also do
not re-argue Deep-Dive Opportunity 3 (omf.py classifier unification) as a
category — it's already correctly flagged as open — but I found evidence the
doc understated *how* unfinished it is, which changes its priority.

Every finding below is either something the two existing docs did not
identify, or a sharpening of one they identified but under-evidenced.

---

## 1. `Asm` is not merely "large" — it has no internal seams at all

`class Asm` (`gsasm/asm.py:456`) carries **85 distinct instance attributes**
assigned in `__init__` (lines 457-616) and **84 methods** total, spanning to
line 3593 — effectively the whole file is one class. Measured, not eyeballed:

```
85 attribute assignments in Asm.__init__
84 methods on Asm
```

These 85 attributes are not incidental bookkeeping — they are at least six
genuinely separate subsystems, flattened onto one `self`:

- macro-variable scoping: `globals`, `gkind`, `localstack`, `macro_at`,
  `macro_uid`, `local_ctx`
- the *live* symbol table: `symbols`, `symtype`, `symseg`, `equ_alias`,
  `defcount`, `case_symbols`, `case_symtype`
- the *prior-pass seed* symbol table (a parallel shadow of the above, for
  multi-pass convergence): `seed`, `seed_type`, `symseg_seed`, `seg_seed`,
  `at_seed`, `at_seg_seed`, `seg_names_seed`
- segment/record state: `segs`, `seg_local`, `seg_equ`, `seg_loadname`,
  `record_stack`, `cur_record`, `_record_dec`, `_record_data`,
  `record_sizes`, `record_ds_fields`, `field_bare`, `with_stack`
- link-mode state: `link_bases`, `extern`, `imports`, `seg_imports`,
  `import_wins`
- diagnostics/position: `errors`, `_cur_file`, `_cur_line`, `dirstack`

None of this is grouped into a sub-object (`self.symtab.symbols` /
`self.symtab.seed`, `self.macroenv.globals`, …). The REFACTORING_DEEP_DIVE
doc's "too central to split wholesale, prefer internal phase extraction" call
is the right near-term answer (a class split *would* be reckless given the
gate discipline — see §7), but it undersells the cost this shape already
imposes: **every one of the 84 methods can read or write any of the 6
subsystems with no compiler- or convention-enforced boundary.** A contributor
adding a 7th subsystem (say, a new per-segment attribute table) has no
signal for where it belongs relative to the existing 6 — the precedent is
"just add another `self.` field and thread it through `_run_once`'s seed
plumbing," which is exactly how it got to 85.

**Severity: informational/structural.** Not a bug source by itself, but it's
the soil the two much sharper findings below (§2, §3) grow out of: an object
this flat makes "the same precedence logic lives in three unconnected
methods" (§2) not just possible but the path of least resistance.

---

## 2. The collision-rule cluster: well-named symptoms, no stated cause — and it's triangulated, not centralized

### 2a. `define_label`'s predicates (R7) are honest, but non-compositional

`gsasm/asm.py:1223-1377` — the eight predicates R7 extracted
(`_proc_equ_reuses_global`, `_label_shadows_proc_head`,
`_proc_equ_reuses_import_winner`, `_proc_equ_reuses_visible_equ`,
`_masked_by_data_record`, `_label_reuses_entry_elsewhere`,
`_prior_modscope_dup`, `_masking_record_with_active`) are genuinely good
work: each has a one-paragraph docstring, a fixture citation, and a concrete
golden-source example. This is the *opposite* of vague — I want to say that
plainly before the criticism, because "extract and name the rule" is exactly
the right move and it was done well.

What's still missing is the layer *above* the predicates. `define_label`
(1378-1567) combines them as:

```python
if (not keep_prior and not foreign_entry_dup
        and not prior_modscope and not set_vs_label
        and not shadows_head):
    self.symbols[u] = value
    ...
```

— a flat conjunction of five independently-discovered negations, with a
comment at 1220 asserting "their short-circuiting... is load-bearing — do not
reorder" but no comment stating *why* this particular order is correct, i.e.
no scoping-precedence model a newcomer could use to predict a **ninth**
collision case. Each predicate answers "was this exact fixture's collision
already seen and named" — none of them, nor the ladder, states the general
rule MPW is actually implementing (something like: *interior definitions are
module-local unless promoted by ENTRY/EXPORT; among same-name candidates,
the most specific enclosing scope wins, in the order WITH-field > seg-local >
seg-equ > module-scope > global*). That rule is implicit in the sum of the
eight predicates but never written down. A contributor hitting a 9th
collision shape has no way to derive the right predicate from first
principles — they must find a tenth fixture, add a tenth predicate, and hope
the AND-ladder's order still doesn't matter for the new case. This is
**exactly the accretion pattern the task asked me to check for**, and R7
only fixed its *readability*, not its *predictive power*. That's a fair
trade for a corpus-discovery codebase (see §7), but it should be named as
what it is: a lookup table of fixed points, not a model.

**Fix scope, cheap:** a single comment block above the ladder stating the
inferred precedence order in prose, cross-referencing the predicates by name
in that order. Zero behavioral risk, pure documentation — should be done
regardless of anything else in this report.

### 2b. The SAME precedence logic is independently reimplemented in three methods

This is the sharper finding, and neither refactoring doc mentions it. The
"is `u` locally bound in the current segment" test — `seg_local` /
`seg_equ` / `seg_seed` / `setvar_seg`+`setvar_val` — is not one predicate
consulted from three call sites. It is **three separately-written,
independently-maintained code blocks** that happen to test the same four
conditions:

- `resolve()` (`gsasm/asm.py:759-762`), combined into one boolean:
  ```python
  local_here = seg is not None and (
      u in self.seg_local.get(seg, {}) or u in self.seg_equ.get(seg, {})
      or u in self.seg_seed.get(seg, {})
      or (self.setvar_seg.get(u) == seg and u in self.setvar_val))
  ```
- `needs_reloc()` (`gsasm/asm.py:1587-1600`), same four conditions but
  split into three sequential `if`/`continue` statements instead of one
  boolean, with a different consequence for `seg_equ` (skip vs. shadow).
- `sym_kind()` (`gsasm/asm.py:1728-1743`), a *third* restatement — visually
  closest to `needs_reloc`'s shape (three sequential `if`s) but returning
  `'label'`/`'equ'` instead of `bool`/`continue`.

`omf._expr_for` (`gsasm/omf.py:878`) then does a *fourth*, narrower
restatement (`local_here = asm._rseg is not None and nu in
asm.seg_local.get(asm._rseg, {})`) that only checks `seg_local`, not
`seg_equ`/`seg_seed`/`setvar_seg` — which may be intentional (it's checking
"is this specifically a code label," not "is this locally shadowed at all")
but nothing documents that the omission is deliberate rather than a
partial port.

**Concrete failure narrative:** MPW discovery is incremental — that's the
whole method of this codebase (see the fixture-cited predicates above).
The next discovered precedence rule (say, a new kind of segment-local
shadow) will be implemented by whoever's staring at whichever one of these
four sites the failing fixture routes through — most likely `resolve()`,
since that's the "main" symbol lookup. `needs_reloc()` and `sym_kind()` will
silently keep the old precedence. The result isn't a crash; it's a value
that resolves correctly but reloc-classifies or size-classifies wrong —
exactly the "silent wrong bytes" failure class this project's own
`test_branch_range.py` docstring calls "the worst failure class an
assembler has." There is no test today that would catch `resolve`,
`needs_reloc`, and `sym_kind` disagreeing about the same symbol — the golden
gate would eventually catch it (a byte would differ), but at the "which of
2,000 assembled objects broke" level of diagnosis, not "these three
functions disagree."

**Severity: HIGH.** This is my top-ranked finding — see §6.

---

## 3. Dialect quirks: individually well-documented, structurally undiscoverable — and one doc citation is already dangling

The ~50 discovered MPW AsmIIgs behaviors are not smeared as bare special
cases (I went in expecting worse). The actual pattern is: each quirk gets a
paragraph-plus comment at its point of use, citing the *source file* that
proved it (`SCSIHD.Driver`, `Pascal.FST`, `AppleShare Time.aii`, `GS.OS SCM`,
…) as the evidence anchor. That's a real, working discoverability mechanism
for "why does this line exist" — but there is no *index* — no
`docs/design/QUIRKS.md` or in-code catalog mapping quirk name -> location(s)
-> golden proof. `docs/design/` holds targeted docs for exactly three
subsystems (`expressload.md`, `linkiigs.md`, `P3_DECOMPOSE.md`,
`makebin.md`, `rez.md`) — none for the ~50 assembler-core quirks. A
contributor who needs to know "does gsasm already handle X" has exactly one
tool: `grep` for a plausible keyword and hope the comment uses it.

That gap is tolerable *until it silently rots*, and it already has once:

```
gsasm/asm.py:603:        # docs/design/CASE_ON.md.
gsasm/asm.py:669:        carried/compared/emitted as-is, never re-folded (docs/design/CASE_ON.md)."""
gsasm/linkiigs.py:54:    # would upper-case a case-sensitive Loader.a segname. (docs/design/CASE_ON.md)
```

`docs/design/CASE_ON.md` does not exist in the working tree. It was added in
commit `c61813a` ("CASE_ON.md — atomic blueprint for case-sensitive
symbols") and then deleted in `a3f274f` ("docs: consolidate outcomes into
RESULTS.md; prune session logs") — a docs-cleanup pass that removed the file
without grepping for its live in-code references. `_fold()` (`asm.py:664`)
is the single most load-bearing invariant in the symbol table (*"a name is
folded EXACTLY once... then carried/compared/emitted as-is, never
re-folded"*), and its own docstring points at a design doc that is gone.
This is a small, cheap-to-fix instance of exactly the "docstrings/docs that
narrate history and go stale" risk the task asked me to check for — and it's
a good canary: if a doc this central can go dangling silently, less central
ones certainly have too (I did not do a full repo-wide dangling-doc-link
sweep; that itself would be a good, cheap, zero-risk follow-up — a one-off
grep-for-`docs/design/\S+\.md`-and-check-existence script, not a refactor).

**Severity: LOW cost, but flagged because it's a canary, not because
CASE_ON.md itself matters much** (it's a single-file, single-directive
feature). Fix: either restore the file from `c61813a` (it's in git history)
or fold its content inline at the three citation sites and drop the dead
references.

---

## 4. `self.errors` is a flat string list; "is this fatal" is decided 14 times, once by substring match

`Asm._err()` (`gsasm/asm.py:618-619`) appends an unstructured f-string to
`self.errors`. There is no severity field, no error code, no
"byte-neutral vs. fatal" classification anywhere on the `Asm` object itself.
The task's framing (the SCSIHD lesson -> ONE fatal error class,
`IncludeNotFoundError`) is correct as far as it goes: `do_include` was
promoted from swallow-to-`errors` to a hard raise (`asm.py:1157-1169`), and
that fix is real and load-bearing (`tests/test_include_not_found.py` guards
it as a hard gate per `work/gate.py:257-266`).

But that fixed exactly one call site. Every *other* error class still lands
in the flat `self.errors` list, and whether a populated list is fatal is
re-decided independently by **14 separate `work/*.py` harnesses**
(`grep -rln '\.errors\b' work/*.py` -> 13 files + `gsasm/__main__.py`). Most
of them are disciplined (`if a.errors: raise RuntimeError(...)` — e.g.
`work/expressloadcheck.py:63-65`, `work/basiccheck.py:74-77`,
`work/mountimagecheck.py:41-43`, `gsasm/__main__.py:54-57`). One does it via
**bare substring matching** as its exemption mechanism:

```python
# work/installerdatacheck.py:77-78
real = [e for e in a.errors if 'branch out of range' not in e]
if real:
    raise RuntimeError(...)
```

This is fragile in the exact way the SCSIHD lesson warns against: it's a
`str.__contains__` check, not a check against a stable error *kind*. Any
future `_err()` call whose message happens to contain the substring
`"branch out of range"` — even for an unrelated reason — is silently
exempted here, with no signal to whoever wrote the new error that this one
consumer will swallow it. (I did not find such a collision today — the
current corpus is clean — but the mechanism itself is a landmine, not a
bug.) Nothing on `Asm` prevents this: there's no `Fixup.kind`-style tag on
error strings, so every consumer is stuck pattern-matching prose.

**This overlaps with, but is more specific than, REFACTORING.md's R2 item 3**
(which centralizes the `_IGNORE_OPS`/`_assemble()` filter pattern in
`kernelcheck.py` et al.) — R2 doesn't mention the `a.errors` fatality check
at all, and it's the same class of un-consolidated duplication, just on the
"is this a real error" axis instead of "which ops to ignore."

**Fix scope:** a library-level `Asm.fatal_errors(ignore=())` helper (or a
structured `(file, line, code, msg)` tuple instead of an f-string) that every
harness calls instead of hand-rolling the check — and `ignore=` takes an
explicit set of *error codes*, not substrings. This is squarely inside R2's
existing "harness helper pass" spirit; I'd fold it into that packet rather
than propose a new one.

---

## 5. `omf.py`'s "unification" is aspirational: 4 independent reimplementations of the same finite-difference probe

Deep-Dive Opportunity 3 correctly flags `_mul_reloc_expr`,
`_grouped_linear_reloc`, and `_extern_diff_expr` as "still duplicated or
specialized" relative to `linear_decompose`. What it doesn't say — and what
changes the priority — is that these functions don't merely duplicate
*structure*; they duplicate the exact same **numeric algorithm**
(evaluate at current values, bump one identifier by `0x100`, diff, divide by
`0x100` to recover a coefficient) as four separate hand-rolled closures:

```
gsasm/omf.py:358   linear_decompose:      V_pc = try_eval(text, base_res, pc_orig + 0x100)
gsasm/omf.py:371-4 linear_decompose:      def bumped_res(n, ...): return _val + 0x100 if ...
gsasm/omf.py:489   _grouped_linear_reloc: try_eval(text, asm.resolve, asm.loc + 0x100) != V
gsasm/omf.py:509-10 _grouped_linear_reloc: def bumped(n, ...): return _v + 0x100 if ...
gsasm/omf.py:568-9 _mul_reloc_expr:       def _res(n, bump=0): return (Lval+bump) if ...
gsasm/omf.py:740   _extern_diff_expr:     b = dict(base); b[e] = 0x100
```

`_diff_reloc` (590-661) and `_linear_reloc` (400-424) *do* correctly route
through `linear_decompose` as the deep-dive doc says. But `_mul_reloc_expr`,
`_grouped_linear_reloc`, and `_extern_diff_expr` — three of the five
classifiers `_expr_for` consults — bypass it entirely and reimplement the
probe from scratch, each with its own closure capturing slightly different
variables (`Lval`, `_val`, `base`/`vals`). So "Add an internal basis
evaluator... have `_mul_reloc_expr`/`_extern_diff_expr` call the same
decomposition primitive" (the deep-dive's own recommendation) is not a
polish pass on a mostly-unified system — it's still most of the work,
because the probe itself, not just its caller shape, needs extracting.

**Concrete failure narrative:** a new relocatable-expression shape is
discovered (this happens routinely — see the docstrings' constant citation
of newly-found golden idioms). Whoever fixes it picks whichever of the 5
classifiers structurally resembles the new case, patches *that one's* bump
logic, and — because there's no single probe function — has no reason to
check whether the other 4 need the same fix. `_expr_for` (759-973) is
already a 215-line policy hub dispatching across all 5; a bug that only
manifests when two classifiers disagree about the same expression is exactly
the shape of bug this system is hardest to catch by inspection.

**Severity: HIGH** — same class of risk as §2b (independently-maintained
copies of one algorithm), and it sits on the hottest path in the whole
emitter (every relocatable operand in every object file goes through
`_expr_for`).

---

## 6. Multi-pass convergence has no runtime check — it's an empirical claim, not an invariant

`assemble()` (`gsasm/asm.py:3542-3581`) runs a **hardcoded `passes=3`**
loop. Nothing compares pass N's output to pass N-1's to confirm a fixed
point was actually reached. The docstring is admirably honest about this:

> "Three passes are needed for correct @-label forward-reference sizing...
> The ROM corpus is fully converged at two passes, so the extra pass is a
> no-op for those files."

That's a claim about the *current corpus*, stated as fact, with no code
enforcing it. If a future source construct needs a 4th pass to converge
(plausible — the whole system exists because MPW's actual multi-pass
behavior keeps surfacing new edge cases), `assemble()` will silently return
an under-converged pass-3 result: not a crash, not an error, just
wrong-but-plausible bytes — precisely the failure class `_err()` /
`IncludeNotFoundError` / `test_branch_range.py` were all created to
eliminate for *other* failure modes. This one has no equivalent guard.

**Fix scope, cheap and additive:** after each `_run_once`, compare
`prev.symbols`/`prev.symseg`/`prev.at_defs` to the new pass's; if unchanged,
you've converged early (a legitimate perf win too, complementary to R10's
proposed cache) — if pass 3 still differs from pass 2, that's diagnostic
gold (today it's silently discarded). This is pure addition, zero risk to
existing output, and directly buys back the exact class of blind spot this
project has fixed twice already (SCSIHD, branch-range).

---

## 7. Testability: the assembler core has no direct unit tests; Rez, one directory over, does

`tests/` has hand-authored, corpus-free unit tests for `gsasm/rez/lexer.py`
(`test_rez_lexer.py`), `gsasm/rez/parser.py` (`test_rez_parser.py`), and
`gsasm/rez/gen.py` (`test_rez_gen.py`, 899 lines) — real unit tests, calling
`lexer.tokenize(...)` or the parser directly on small hand-written snippets
and asserting token/AST shape.

There is no `test_expr.py`, `test_omf.py`, or `test_m65816.py`. I checked —
none exist. Every one of `expr.py`'s `evaluate()`, `m65816.py`'s `encode()`,
and `omf.py`'s `_eval`/`linear_decompose`/`_diff_reloc`/etc. is a **pure
function** — no I/O, no mutable global state, trivially unit-testable in
isolation (`expr.py` in particular has zero side effects at all). None of
them are tested that way. All coverage of these functions is *indirect*,
through:

- `tests/run_fixtures.py` — assembles a whole `input.asm`, diffs the
  resulting OMF object against blessed `expected.obj` bytes.
- the golden corpus gate (`work/gate.py`) — assembles real Apple sources,
  diffs against captured ROM/GS.OS/tool bytes.

**What is the actual unit under test?** "The composition of `Asm` + `omf.emit`
over an entire file", never a single classifier function or a single
expression string. This has a real cost, not just a coverage-percentage
one: when a fixture or gate byte diverges, the failure surfaces as a wrong
byte at some offset in an LCONST/EXPR record — the contributor then has to
work *backward* through `_expr_for`'s 215-line dispatch to guess which of
the 5 classifiers (§5) or which of the 3 precedence restatements (§2b)
produced it. A `test_omf.py` with `assert omf._diff_reloc(fake_asm, "A-B") ==
expected_ops` would turn that into a 10-second, readable failure instead of
a `diff <(hexdump obj1) <(hexdump obj2)` archaeology session. The
`REFACTORING_DEEP_DIVE_2026-07-30.md`'s Opportunity 3 *does* recommend
"oracle tests that enumerate representative expressions and assert the
chosen OMF opcode sequence" — but frames it as a nice-to-have alongside a
refactor, not as the missing foundation that makes the refactor safe to do
at all. I'd invert that priority — see §8.

**Severity: MEDIUM** on its own (it's a gap, not a bug), but it's a
force-multiplier on §2b and §5: those findings are risky specifically
*because* there's no fast, targeted test that would catch the three
precedence copies (or the four probe copies) disagreeing.

---

## What's actually fine — redirecting flattery-shaped instincts to real targets

To be fair-hostile rather than just hostile:

- **`m65816.py` and `expr.py` are genuinely clean.** Table-driven opcode
  encoding, a small precedence-climbing parser, no God-object symptoms, one
  job each. The one quirk worth flagging (`m65816.py:261-285`, the `#^#N`
  double-immediate-marker note) is a *model* of how to document an unproven
  edge case: it states the exact mechanism, the corpus sweep that failed to
  find a counter-example, and explicitly says "do not change this fallback
  behavior without golden .lst evidence." More of the codebase should read
  like this comment.
- **R6/R7 were executed honestly.** `dispatch()` really was mechanically
  extracted (the `_dir_*` methods are verbatim moves, and the comment at
  `asm.py:2580-2584` says so and explains why the ladder stays sequential
  rather than becoming a dict). The predicates in §2a are well-cited, not
  just renamed magic. Don't undo either.
- **The SCSIHD fix (`IncludeNotFoundError`) is correctly load-bearing and
  correctly enforced** — it's a hard gate via `test_include_not_found.py`,
  and `gsasm/__main__.py:54-57` gates on it at the CLI level too. §4's
  finding is that the *general principle* wasn't generalized past this one
  site, not that this site is wrong.
- **The Do-Not-Touch registry (`REFACTORING.md` §5) is the right
  instrument** and I did not find anything in it that's actually just
  ordinary bad code wearing a "load-bearing" excuse — every zone I sampled
  (the `first_field`/`_EXPR_CONT_OPS` BLANKS-ON folding, the `_cond_leaf`
  ladder) had a specific fixture and a specific golden counter-example
  behind it. That's rarer than it sounds for a "don't touch this" list.

---

## Ranked findings (cost × likelihood a contributor trips it)

1. **§2b — triangulated precedence logic (resolve/needs_reloc/sym_kind).**
   Highest cost (silent wrong-byte classification on the hottest lookup
   path in the assembler) × highest likelihood (this is *exactly* the kind
   of incremental discovery this project does routinely — the next one
   WILL hit only one of the three sites).
2. **§5 — omf.py's 4 independent finite-difference probes.** Same failure
   shape as #1, same "next discovery only patches one copy" mechanism, on
   the equally hot relocation-classification path.
3. **§6 — no convergence check in `assemble()`.** Lower likelihood (only
   trips on a genuinely new multi-pass-sensitive construct), but the cost
   is a silent wrong ROM with zero diagnostic — the exact failure class
   this project has twice built dedicated hard gates to eliminate elsewhere.
4. **§7 — no unit tests for expr/omf/m65816.** Not a bug source itself, but
   it's why #1 and #2 are dangerous instead of merely ugly: there's no fast
   test that would catch them diverging before a byte-level gate does.
5. **§4 — error fatality decided by substring match in one harness.**
   Medium-low likelihood today (corpus is clean), but it's a `str in str`
   safety gate in a project that already learned this lesson once.
6. **§3 — dangling `CASE_ON.md` reference.** Low cost by itself; flagged as
   a canary for doc rot given how load-bearing this project's docs are.
7. **§1 / §2a — God-object shape, non-compositional predicate ladder.**
   Real, but *diffuse* cost (slows down every change a little) rather than
   a specific failure mode — hence lowest rank despite being the most
   visually obvious issue.

---

## The three refactors I'd actually stake time on

All three respect the project's own discipline: `run_fixtures.py` (62/62),
`work/gate.py` (byte-identical to baseline, not "improved"), and
`work/buildrom.py` after every step; one packet at a time; no drive-by
cleanup; Do-Not-Touch zones moved verbatim, never "simplified."

### Refactor A — Unify the seg-local/seg-equ/WITH precedence check (addresses §2b)

**Target:** `resolve()` (759-762), `needs_reloc()` (1587-1600), `sym_kind()`
(1728-1743), and `omf._expr_for`'s `local_here` (omf.py:878).

**Plan:**
1. Write a new method, e.g. `Asm._local_binding(self, u, seg)`, that
   reproduces `resolve()`'s `local_here` boolean *exactly*, verbatim
   short-circuit order, PLUS enough return detail (e.g. a tag telling the
   caller *which* of seg_local/seg_equ/seg_seed/setvar matched) that
   `needs_reloc` and `sym_kind` can derive their different consequences from
   one call instead of one reimplementation.
2. Migrate `sym_kind()` first (smallest, most mechanical — it already has
   the closest shape to what the shared method will look like). One commit,
   full gate + fixtures + buildrom.
3. Migrate `needs_reloc()` next. One commit, same verification.
4. Migrate `resolve()` last (riskiest — it's the hottest path). One commit,
   same verification.
5. Migrate `omf._expr_for`'s narrower `local_here` last, confirming with a
   comment whether its narrower scope (seg_local only) is intentional; if it
   is, the shared method should expose that as an explicit narrower query
   rather than `_expr_for` re-deriving it.
6. **Add the safety net *before* step 2, not after**: a new
   `tests/test_symbol_precedence.py` that runs a real corpus module (or a
   hand-written stand-in with a WITH-shadowed field, a seg_equ, and a
   seg_local collision all present) through `assemble()` and asserts
   `resolve`, `needs_reloc`, and `sym_kind` agree for every symbol touched —
   this is a new, permanent regression test, not a throwaway.

**De-risking:** each of the 4 migrations is independently gate-verified;
if any one shows a gate delta, that migration (not the whole packet) is
wrong and gets reverted in isolation. Est. 3-4 days.

### Refactor B — Extract the one finite-difference probe (addresses §5)

**Target:** `linear_decompose` (326-397, already correct),
`_grouped_linear_reloc` (468-529), `_mul_reloc_expr` (532-587),
`_extern_diff_expr` (703-756).

**Plan:**
1. **Before touching any classifier**, add the oracle test the Deep-Dive doc
   already recommends (Opportunity 3's "enumerate representative expressions,
   assert the chosen OMF opcode sequence") as a *pre-refactor* safety net,
   not a nice-to-have alongside it: one test file exercising each of the 5
   classifiers on the specific golden idioms their docstrings already cite
   by name (`my_f_info-tOpt.f_info`, `user_path+2-us_start+us_end`,
   `(common_int_ent<<8)+$5c`, `lst_rslt_scode+2-lst_rslt_ec`, …) with the
   exact expected opcode bytes.
2. Extract `_probe_coeff(asm, text, ident, base_val, base_res)` — the exact
   "evaluate, bump by 0x100, diff, divide" operation — as a standalone
   function callable from all four sites.
3. Migrate `_mul_reloc_expr` first (only one relocatable symbol, simplest
   case). Gate + fixtures + buildrom + the new oracle test.
4. Migrate `_extern_diff_expr`, then `_grouped_linear_reloc`. One commit
   each, same verification.
5. Leave `_expr_for`'s dispatch order and `_diff_reloc`/`_linear_reloc`
   untouched — they're already correct per Deep-Dive's own read.

**De-risking:** step 1 means every subsequent step has a fast, targeted
pass/fail *before* the corpus gate even runs — exactly the missing
foundation §7 identifies. Est. 3-4 days (1 of which is step 1, which pays
for itself even if B stops there).

### Refactor C — Direct unit tests for expr.py / m65816.py / omf.py classifiers (addresses §7)

**Target:** new `tests/test_expr.py`, `tests/test_m65816.py`,
`tests/test_omf_classifiers.py`, modeled exactly on the existing
`tests/test_rez_lexer.py` pattern (hand-authored snippets, zero corpus
dependency, `python3 -m pytest` or standalone `__main__` runnable).

**Plan:** this is purely additive — it touches zero shipping code, so the
gate/fixtures/buildrom discipline doesn't even apply in the usual sense
(nothing can regress that didn't already have a test). Prioritize the
Do-Not-Touch zones explicitly, since those are the behaviors most likely to
regress silently today:
- `expr.py`: MPW truncating division (`-32767/2`), the mac-roman
  `pea '"'` MSB case, each comparison/bitwise operator, `NOT` vs `~`.
- `m65816.py`: every addressing-mode selection path in `OPTABLE` at least
  once (dp/abs/long promotion, the crossbank JSR->JSL promotion, block-move
  bank byte extraction, the documented-unverified `#^#N` fallback pinned as
  a regression guard even though its *correctness* is unconfirmed — the
  test asserts gsasm's current behavior, which is exactly the point).
- `omf.py`: one test per classifier (`_linear_reloc`, `_grouped_linear_reloc`,
  `_mul_reloc_expr`, `_diff_reloc`, `_extern_diff_expr`, `_pc_rel_const`)
  against a small fake `Asm`-like stub (or the real `Asm` with two/three
  hand-defined labels) — this *is* Refactor B's step 1, generalized to the
  two classifiers B doesn't touch.

**De-risking:** none needed — this refactor cannot break the gate. The only
discipline required is not conflating it with A or B (write the tests
against *current* behavior, including current warts, so they document
what's true today rather than what should be true — a test that encodes an
opinion about correctness instead of current behavior would be worse than
no test, in this codebase's own stated philosophy).

**Sequencing note:** C's omf.py tests are a strict subset of B's step 1, so
if only one gets done, do B (which includes C's most valuable slice) —
listing them separately here because C's expr.py/m65816.py slices are
independently valuable and lower-risk than anything touching omf.py or
asm.py's live precedence logic.
