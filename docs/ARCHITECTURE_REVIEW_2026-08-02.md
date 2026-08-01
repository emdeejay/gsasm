# Architecture Review — 2026-08-02

Commissioned by the author, the morning after Tier A, with the instruction
that it should sting.  Three independent hostile reviews (full texts with
file:line receipts in `docs/reports/2026-08-02/ARCH_CRIT_{ASM,LINK,WORK}.md`)
plus a synthesis section the reviewers could not write, because its subject
is the review's own supervisor.  The byte-exact results are not in question
anywhere in this document — the gate enforces those.  The question is what
this codebase costs to live in, and the answer is: more than its results
deserve.

## The verdict, in one paragraph

gsasm is a world-class *verification instrument* wearing the body of an
accreted lab notebook.  Its empirical discipline — golden bytes as the only
oracle, predicted-vs-actual movement, corpus-free guards for every dialect
discovery — is genuinely excellent and demonstrably self-correcting (it
caught its own supervisor twice in one night).  But the *knowledge* that
discipline has produced is stored in the wrong medium: semantic rules live
as code shaped like the order bugs were discovered in, duplicated wherever
they were needed next, with prose comments as the only contract.  The result
is a system where the bytes are certain and the *model* is folklore — four
restatements of one scoping rule, two reloc paths encoding different golden
semantics with no written statement of either, seven bookkeeping locations
for the single fact "this fork is built and wired."  Every one of those was
individually justified by a gate-green commit.  That is precisely how it
happened.

## The five findings that matter most (consolidated, cross-critic)

**1. One scoping rule, four unconnected implementations (ASM #1 + LINK #4).**
"Is this symbol locally shadowed here" is independently restated in
`asm.resolve()` (asm.py:759), `needs_reloc()` (:1587), `sym_kind()` (:1728),
and `omf._expr_for` (omf.py:878) — and its link-time sibling, symbol-binding
precedence, now comprises six rules in `_build_symtab` (first-wins,
ENTRY-vs-EXPORT, combo setdefault, case-collision repair, module privacy,
kinds) whose composite truth table exists nowhere but in the corpus itself.
Nothing tests that the four assembler restatements agree; nothing states
what rule #7 must and must not touch.  The 2026-08-01 module-privacy fix
worked *because its author had the whole corpus as an oracle*; the next
contributor won't know they've broken agreement until a golden byte moves —
if one happens to.

**2. The single/multiseg divergence is a bug factory with a production
record (LINK #3).**  The two ExpressLoad output paths encode *different*
golden reloc semantics: the single path suppresses via symbol kinds and
resolves const shifts; the multiseg path classifies absolutes via
`_group_of` and body-patches.  This is not a design — it is two piles of
empirically-forced behavior whose only contract is comments.  The receipts:
this week's kinds fix regressed TS2 at body level on its first application
because the divergence is *undocumented as a divergence*; the const-shift
gap existed because `_defer_shifts` is called three ways from two files;
and `_build_multiseg_output` is 752 lines that re-walk the same record
stream three times.  Every future reloc discovery must be manually routed
to the correct path by someone who remembers why.

**3. Stdout is a load-bearing API, and a third of its speakers don't
honor the contract (WORK #1).**  The gate's transport is regex-over-stdout
with a committed baseline — a design with a genuinely strong record — but
10 of 34 check scripts still never `sys.exit` nonzero on failure, so for
them the scrape is the *only* signal, and the parse guard catches absent
matches, not wrong-line matches after format drift.  The Packet-A hardening
(2026-08-01) fixed exactly the three scripts its review named and left the
sweep it *said* needed doing ("audit all ~20 scripts") undone.  Metric
semantics (frac/okbad/count) are per-entry conventions in a 222-line table
literal.  Runtime docs claim ~2 minutes; measured fast gate is 3:46.

**4. One fact, seven ledgers (WORK #2/#4 + synthesis).**  "This fork is
built from source and wired into its disk" is now recorded in: the census
fork classification, the census `proven_by`, `DISK_BUILDER_REGISTRY` (97
entries + 41 wrapper functions), diskcheck's Disk-2-only `MANIFEST`,
`manifestcheck.OVERLAID_DISKS` (hand-set, comment-enforced, one file away
from the typed-proof pattern that would validate it), gate's CHECKS table,
and the committed baseline values.  Some pairs are runtime-reconciled
(`_wired_builders`, the release-review audit that caught three strays);
most are not.  The census is "generated — never hand-edit," yet its
generator's `OVERRIDES` dict was hand-edited six times in its first
36 hours, each edit tied to a crack: `census_migrate.py` is not a
migration, it is a **ledger with a commit-shaped write API and a
misleading filename**, and pretending otherwise guarantees the day someone
edits the JSON directly and regeneration silently reverts them.

**5. The pure core is untested as units (ASM #3/#4 + LINK #8).**
`expr.py`, `m65816.py`, `omf.py`'s classifiers, `_build_symtab`,
`_scan_relocs`, `makebin` — pure functions with crisp inputs — have zero
direct unit tests; all coverage is whole-pipeline golden-byte diffing, so
every failure presents as "byte 0xe5d differs" and must be *diagnosed
backward through the entire pipeline* every time.  Tonight's cracks each
began with exactly that archaeology.  Meanwhile `assemble()`'s `passes=3`
has no convergence check: correctness is a docstring citation of corpus
behavior, not a runtime invariant.  The fixture suite is excellent at
pinning *discovered* behaviors; it is not a unit-test suite, and the
difference is billed on every diagnosis.

## The supervisor's own chapter (the part the critics couldn't write)

The freshest strata of these findings were laid down under my supervision
in the last 72 hours, gate-green at every step, which is rather the point:

- **`SymTab` as dict-with-attribute** was chosen explicitly to avoid
  touching six call sites ("zero caller breakage").  The tax arrived within
  hours: `{**a, **b}` silently drops `.kinds`, so the code hand-builds
  parallel kind dicts at every merge point, and `linkiigs.py:624` already
  contains the latent gap where a future kinds consumer will read an empty
  table.  Expedience chose the design; the workaround is now load-bearing.
- **The single/multiseg contract exists only as comments I wrote** after
  empirically regressing TS2 — I documented *that* the paths differ and
  *where*, but not the semantic model that would let someone derive the
  routing of the next fix without re-running my experiment.
- **The census "regenerable migration" fiction is mine to own**: I added
  six OVERRIDES edits in one day while the docstring continued to promise
  a one-shot migration, and I named the output file after a date that
  stopped being meaningful before it was 24 hours old.
- **The exit-code sweep** I declared necessary, then quietly scoped to
  three files.  The other ten are finding #3.
- Two prose overclaims ("every census-built fork wires", "COMPLETE") were
  caught only because the author asked a skeptical question.  The metrics
  never lied; my sentences did.  A system this good at catching machine
  drift deserves the same rigor applied to its narrator.

## What is genuinely good (kept short, because it's earned elsewhere)

The oracle discipline and its guardrails (predicted movement, corpus-free
fixtures, the bless interlock's *intent*, the Do-Not-Touch registry — every
zone fixture-backed on inspection).  `diskmanifest`'s typed proofs — the
one place a claim is validated against the machinery that enforces it; the
reviewers independently nominated it as the pattern the rest of the
ecosystem should converge on.  `expr.py` and `m65816.py`.  The a2til
boundary (filesystems live downstream, and the one-day HFS round-trip
proved the interface).  And the review record itself: this project writes
down its mistakes, including this document.

## The 0.6.0 slate (Tier C, reconciled with the critics' stakes)

Ordered so each step de-risks the next; all under the standing zero-drift
discipline (byte-identical gate stdout, or predicted metric movement):

1. **Foundations first — additive unit tests** for expr/m65816/omf
   classifiers, `_build_symtab`, `_scan_relocs` (ASM stake C, LINK stake 2
   precondition).  Zero gate risk; converts future archaeology into test
   failures with names.
2. **Write the two contracts as artifacts, then enforce them**: the
   symbol-precedence truth table (one doc + one cross-check test that the
   four assembler restatements and `_build_symtab` agree on a generated
   case matrix) and the single/multiseg reloc-semantics contract (ASM
   stake A, LINK stake 2).
3. **Harness hygiene sweep** (WORK stakes 1+3): universal nonzero-exit via
   a shared `_common.gate_result()`; one a2til discovery (fixing
   `drivercheck.py`'s no-override hardcode as its own commit); retire the
   "migration" framing — rename the census system to what it is (a ledger
   + regenerator) and make the registry↔census reconciliation a standing
   two-directional gate instead of a release-eve audit.
4. **R10 (the assembly cache)** — correctly scoped per WORK's assessment,
   *after* 1–3 so the cache lands on tested ground.
5. **D3's multiseg phase-split, upgraded by LINK's finding**: collapse the
   triple record-stream walk first (mechanical, shrinks the 752-line
   function), then split phases against the now-written contract.
6. `SymTab` redesign rides with 2 (whatever the contract says the binding
   tables *are*, encode kinds in that shape natively, not as a sidecar).

Items 1–3 are a realistic 0.6.0; 4–6 can trail into 0.7.0 without shame.
What should *not* happen is another feature era on top of the current
strata: the next Apple II reconstruction target (French disks? System 5?)
would multiply every ledger and both reloc paths.  Pay first.
