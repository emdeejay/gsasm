# Second-chair critique of the architecture review (2026-07-07)

Independent review of `ARCHITECTURE_REVIEW.md` (+ its dependencies `RATIONALISE.md`,
`BESPOKERY_AUDIT.md`, `LINKOS.md`) and `work/mpwmake_probe.py`. Read-only; the goal
is to disagree where disagreement is warranted, not to validate. Precedent:
`M8_SECOND_CHAIR_REPORT.md`.

**Baseline re-verified (sacrosanct, all green):**
- `work/buildrom.py` → "verified byte-identical to the real ROM" (261377 B gsasm-built, 99%).
- `work/objcheck.py` → `OBJ byte-identical: 36/61`.
- `work/linkcheck.py` → 61 LINK_IDENTICAL.
- `work/mpwmake_probe.py` → Tools **8/8**, FSTs **6/7**, Drivers **7/12** EXACT. Primary's numbers reproduce exactly.

---

## TL;DR ranking (most to least important)

1. **§3 is materially bigger than the primary implies, but for a *different* reason than
   RATIONALISE names.** Retiring `linkrom` into a `link_placed` needs symbol-model work
   FIRST — and the specific coupling is `entry_seg`-based re-routing of multiply-defined
   names, which `linkiigs` has no representation for at all. This is real, and the primary's
   "~80% present, machinery exists" framing undersells it. **AMEND §3.**
2. **A load-bearing factual error propagates from RATIONALISE into the review: the
   expressload "duplication" (model 4) is STALE.** expressload no longer re-implements
   place+symtab; it calls `_linkiigs._place`/`_build_symtab` and has *zero* copies of the
   symtab logic. The cited divergence (unconditional `setdefault(segname)` at
   expressload.py:440; "the fix landed twice") describes deleted code. The review keeps
   listing it as live debt and as a current symptom. **Correct the record.**
3. **The disk-image residual class is misdiagnosed as something §3/§3a fixes.** 13 of 16
   disk residuals are `len < EOF` (missing *trailing* bytes), not content divergence — and
   at least one (Tool014 WindMgr) has a **100%-exact code image yet is still 20 bytes short
   on disk**. The gap is the ExpressLoad *file structure* (HET / reloc tail / EOF), which is
   orthogonal to placement (§3) and to recipe-reading (§3a). Byte-exact disk output will NOT
   "fall out" of either. **This is the cheapest lever and neither §3 nor §3a touches it.**
4. **§3a (makefile reader) is speculative infrastructure for a solved problem.** The probe
   found ZERO current transcription errors; the maps are correct and stable. A lighter option
   — keep the maps, add the probe as a CI drift-check — captures ~all the value at a fraction
   of the cost. **DISAGREE with "adopt §3a first"; AMEND to "adopt the probe as CI, defer the
   parser."**
5. **The smell test is good but has a real false-negative class: self-inflicted bugs.** The
   Tool025 case-collision fix (a8707cb) is keyed on a genuine "property," yet the property
   only exists because *gsasm folds symbol case* — it repairs damage gsasm itself causes and
   that MPW may never exhibit. That passes the smell test and every gate while being, arguably,
   a workaround for our own modelling choice. **AMEND the test with a "is the property a proxy
   for a gsasm-internal artifact?" clause.**
6. **Sequencing: keep grinding, defer both refactors.** The honest cheapest path to more
   byte-exact output is the ExpressLoad-tail fix (finding 3) + the three named content diffs
   (Start.GS.OS @0x1475, Tool019 @0x95c, P8 @0xc9), none of which is a refactor.

---

## Per-recommendation verdicts

### §3 — unify placed multi-`-lseg` link into `linkiigs.link_placed`, retire `linkrom` + harness placement — **AMEND (bigger than sold; sequence after a scoped symbol-model step)**

**Where the primary is right.** The *diagnosis* is sound: there really are multiple placement
models, and `kernelcheck._placed_symtab` (work/kernelcheck.py:333-368) genuinely mixes a
*general algorithm* (base-ORG + accumulated-offset placement, lines 357-368) with *config*
(`_SCM_LSEG_RECIPE`, lines 373-379). The algorithm half does belong in `linkiigs`; the recipe
is legitimately harness config. `linkiigs._place` (linkiigs.py:125-168) already does ORG-jump +
flow, and `_build_symtab` (171-362) already builds a global placed table. So a `link_placed`
that takes `(objects, lsegs, org)` and returns `{segname: bytes}, symtab` is a coherent target.

**Where the primary undersells it — the coupling is real and specific.** The open sub-question
"does `link_placed` subsume linkrom's `msym`/`msloc`/`linkidx` precedence?" is answered **no,
not with today's symbol model**, and the blocker is narrower and harder than "multiply-defined
labels" in the abstract:

- `linkrom.resolve_name` (work/linkrom.py:171-197) is a **6-level precedence ladder**:
  segbase → `msym` (this module's ENTRY/EXPORT) → rommap → `objsegbase` (same-object PROC head)
  → global EXPORT (max linkidx) → `msloc` (module plain-local) → last-def-at/before-linkidx.
- The load-bearing part `linkiigs` cannot express is **`entry_seg`-based re-routing**
  (work/linkrom.py:136-141):
  ```python
  es = a.entry_seg.get(nm, '')
  route = kind
  if (kind != 'local' and es and (aseg.name or '').upper() != es.upper()):
      route = 'local'
  (msloc if route == 'local' else msym).setdefault(nm, base + v)
  ```
  When a name is defined multiple times *inside one module* (e.g. WDefProc's two `setLong`),
  only the segment that *owns the ENTRY/EXPORT directive* is published to the symbol table a
  by-name ref resolves against; the other definitions are downgraded to plain-local. `linkiigs`
  has no `entry_seg` in its symbol path (it lives in `gsasm.asm.Asm` and is consumed only by
  `omf.py:708` at emit time). `_build_symtab` uses first-wins `setdefault` for `obj_globals`
  (linkiigs.py:310), so it picks the *first* `setLong`, not the directive-owner. Re-partitioning
  the ROM into per-file objects does **not** help, because this is *intra*-assembly disambiguation.
- Second concrete mismatch: `linkrom` deliberately makes a module's plain-local **yield** to an
  external EXPORT (the `atp`/`closeskt` case, documented at work/linkrom.py:176-178 — `msloc` is
  checked *after* global exports). `linkiigs` Pass-3 does the **opposite**: `local_sym = {**sym,
  **obj_globals[oi]}` (linkiigs.py:426) lets the object's own locals *override* the global table.
  For single-object links this is invisible; for the ROM's multi-module banks it inverts.

So the primary's "L2 blocked by D2/D3" and "unifying may require the D2 model first" hedges in
`RATIONALISE §2/§3` are, on the code, **not hedges — they are the answer**. §3 as "retire
linkrom" is a **P4-sized** (RATIONALISE's own "the big one," high risk, multi-session) change,
not the ~80%-done refactor the headline framing suggests. The ROM's 36/61 objcheck gate is
unforgiving here: the ROM banks are the *only* place the multi-module precedence bites, and
they must stay byte-exact.

**Honest caveat that helps the primary.** `linkiigs`'s multi-object path *is* exercised today
(WindMgr = 7 objects → 100%, ControlMgr = 8 objects → but only 96%, 26 code bytes short). So
`link_placed` for the *kernel* (`kernelcheck` currently feeds `_build_scm_segments` a single
combined object — work/kernelcheck.py:391 `_lnk.link([(combined, None)], ...)`) is a smaller
step than retiring `linkrom`: the kernel does not need `entry_seg` re-routing today (its
`_placed_symtab` is a flat home-segment→base map, not a multiply-defined resolver). **Split §3
into §3-kernel (tractable now, no D2) and §3-ROM (needs D2, defer).** The review conflates them.

**Verdict: AMEND.** Adopt the *diagnosis* and the *kernel* half (promote the placed base+offset
algorithm out of `kernelcheck`). Do **not** promise "retire `linkrom`" without first doing the
`entry_seg`/plain-local scope work — that is D2, and it is the largest item in the whole plan.

### §3a — build-recipe reader (`work/mpwmake.py`) — **DISAGREE with "adopt first"; AMEND to CI drift-check, defer the parser**

**The strongest honest case against building it (steelman).** §3a is infrastructure for a
problem the primary's own probe proves is *already solved*: "**No remaining transcription
errors found. The current maps are faithful.**" (ARCHITECTURE_REVIEW.md:182-183). The historical
wins it cites (ControlMgr `CtlPatch`/`DummyDrag`, LineEdit/FontMgr/Scrap `common.asm`) were all
*already hand-corrected*. So the maps are correct today and change ~never (the source makefiles
are frozen 1990s artifacts). Against that near-zero ongoing cost, an MPW-Make interpreter carries
real, unavoidable cost the primary lists but then discounts:
- `ƒ`/`∂` grammar, `{Variable}` expansion, `if/end`, quoted multi-word names;
- a build-env variable resolver (`{Object}`/`{Common}`/`{WorkFolder}`/…);
- shell scripts that are *not* makefiles at all (`linkOS`, `BuildEverything`);
- a flag→API mapping layer (`-lseg:…:static|dynamic`, `-org`, `-t`, `-x`, `-i`, `-d`);
- the "dependency-line-is-authoritative-when-the-rule-is-`#`-commented" reconciliation
  (ControlMgr/LineEdit) — a *judgement call the probe hard-codes*, not a derivable fact.

That last point is the crux: the probe's own method (`parse_targets` uses the `ƒ` dependency
line and *overrides* the `-o` link line, work/mpwmake_probe.py:180-181) encodes a **human
decision** that the commented-out LinkIIGS rule is stale and the prerequisites are truth. A
"derived, no-hand-maintenance" reader that silently trusts a half-commented rule would produce
the *wrong* list for exactly ControlMgr/LineEdit — the two tools the primary leans on. The
maintenance doesn't vanish; it moves into the reader's heuristics and gets harder to see.

**The probe already found the two things a reader would need to special-case anyway**
(`{Variable}` resolution for `DEBUGSYMBOLS` + 2 output names; quoted SCSI names). Those are the
*only* deltas across 8 tools + 7 FSTs + 12 drivers. The value of turning ~26 correct static
maps into derived data is genuinely small; the risk (a parser bug silently mis-lists a component
and a *real* gsasm gap gets masked as "matches the derived recipe") is not.

**The lighter option captures ~all the value.** Keep the maps; wire `mpwmake_probe.py` into CI
as a drift-check (fail if any map diverges from the makefile *except* the known
`DEBUGSYMBOLS`/quoting deltas). That kills the *error class* (a future hand-edit that drifts
from the shipping recipe is caught) without building or trusting an MPW-Make interpreter. It is
strictly additive, ~1 day, and it is what item #4 in the review's own §6 ("generality gate as
CI") is already reaching for.

**Verdict: DISAGREE with "§3a first."** The probe is the deliverable; the parser is speculative.
The review's ranking (§6.1 "adopt §3a first — highest-leverage, lowest-risk") inverts the
cost/benefit: it is low *risk* only in the "additive" sense, but it is low *value* because the
maps are already correct, and the "kills the maintenance" benefit is overstated (the reader
inherits the maintenance as heuristics).

### The smell test — **AGREE it is the right axis; AMEND for a real false-negative class**

The test ("keyed on a **property** = general; on a **name/address/file** = overfit") is a good
first filter, and the corpus-as-oracle discipline is real (buildrom/36/61 pinned while the
corpus rises is genuine evidence). The classification table (§4) is mostly fair, and the
best-disciplined fix I audited — equ-alias-of-relocatable-label (c1526c4) — is a model of the
method: keyed on "RHS is exactly one label in a non-ORG'd segment," audited across **1142
`X equ IDENT` sites / 159 files**, only real aliases fire (sound.aii 3, dialog/menumgr 0), and
the DON'Ts (label-difference, `*`-relative, import precedence) are explicitly excluded. That is
generality earned, not asserted.

**But the test has a false-negative class the review does not name: a property that is a proxy
for a gsasm-internal artifact.** Concrete example — **Tool025 case-collision (a8707cb),
linkiigs.py:253-264.** The fix is keyed on a property ("the folded name's home segment is not
the segment it names") and passes every gate. Yet that property *only exists because gsasm folds
symbol case* (the commit says so: "gsasm folds symbol case, so notesynth's local label `UpDate`
… clobbered the exported `update` segment"). MPW's assembler may preserve case and never produce
this collision at all. So this is not a reimplementation of an MPW behaviour — it is a repair of
damage gsasm's *own* case-folding inflicts, dressed as a general linker rule. It is defensible
(it makes the corpus green and is narrowly gated), but by the review's own axis it is closer to
"specifically good at working around this codebase's interaction with *our* case-folding" than
to "general LinkIIgs behaviour." A byte-exact gate cannot catch this because the golden file was
produced by a toolchain that never had the collision.

**Amendment:** add a third question to the test — *"Is the property a proxy for a gsasm-internal
representational choice (case-folding, one-symbol-per-name storage, `_rseg`-None-at-pass-1) rather
than a property of the MPW input?"* If yes, the fix is a **compensation**, not a generalization,
and should be logged as debt against the underlying choice (here: case-insensitive symbol
storage) even when green. This is exactly the D2 story RATIONALISE tells for `ctlPart`/`Max_call`,
generalized: the corpus can prove a fix is *sufficient*, never that it is *the right model*.

**Overfitting risk from byte-exact validation — yes, one concrete axis.** The SEG-persistence fix
(48b7cef) is correct MPW semantics and I have no quarrel with it, but note its *validation* was
"zero regression across the corpus" — and the corpus has *no bare `SEG`* (the commit admits "a
bare SEG (none in the corpus)"). So the `seg_loadname = None` revert branch (asm.py:1561) is
**completely unvalidated**; it is asserted-correct, not proven. That is the overfitting shape to
watch: not the fired path (corpus-proven) but the *unfired* branch added alongside it.

### Sequencing / opportunity cost — **DISAGREE with the refactor-first framing; keep grinding**

The review's §6 leads with "adopt §3a first, then §3." The residual evidence says neither is the
cheapest next byte. Disk images are 10/26; the 16 near-misses break down as:

- **13 files: `len < EOF`** (missing trailing bytes) — Tool014/15/16/18/23/27/34, TS2/TS3,
  GS.OS(+238)/GS.OS.Dev(+143)/AppleDisk3.5(+647)/5.25(+258). diskcheck fails these at the
  *length* check (work/diskcheck.py:181-182) **before** comparing content.
- **3 files: content diff** — Start.GS.OS @0x1475 (the `#^Label`/CONST bank-word, LINKOS WP-K3),
  Tool019 @0x95c, P8 @0xc9.

The decisive datum: **Tool014 WindMgr's code image is 100% exact (toolcheck 28046/28046) yet its
disk file is 20 bytes short** (`len 29998 != EOF 30018`). So the dominant residual class is the
**ExpressLoad file wrapper** (HET, reloc tail, or the on-disk EOF/pad convention) — *not* code
correctness, *not* placement (§3), *not* recipe (§3a). A single fix to the ExpressLoad tail/EOF
sizing plausibly flips a *cluster* of these (every ExpressLoad'd tool that is otherwise exact),
for far less than either refactor. The primary's claim (§3.5, §6.5) that byte-exact
Start.GS.OS/GS.OS/tools "fall out as validation" of the refactors is **not supported** by this
breakdown: the residuals are elsewhere.

**What I would do first, in order:**
1. **Root-cause the ExpressLoad `len < EOF` gap** on a code-100% tool (Tool014, 20 B) where code
   is not a confounder. Isolate whether it is HET size, reloc-record count, or a trailing-pad/EOF
   convention. Highest fan-out (13 files), cheapest, no refactor. *(Verify the fix keeps the code
   image 100% and does not perturb the 36/61 ROM gate — it shouldn't; ROM path is not ExpressLoad.)*
2. **The three content diffs** — Start.GS.OS @0x1475 is the known WP-K3 bank-word; a targeted
   `_defer_shifts`-conditionality fix (RATIONALISE P0, correctly scoped: *defer for
   segmented/ExpressLoad, resolve for merged*) is small and independently useful.
3. **Only then** the §3-kernel algorithm lift (promote base+offset placement out of
   `kernelcheck`), gated as LINKOS.md specifies.
4. **Defer §3-ROM (retire linkrom) and the D2 refactor** until a lever actually needs them —
   ControlMgr's remaining 26 bytes is the honest trigger, and even that is a *code-image* gap the
   disk harness cannot see yet (its disk residual is the wrapper, not the 26 bytes).

The refactors are worth doing *eventually* for code health, but "cheapest path to more byte-exact
output" is grinding the ExpressLoad tail + three diffs, not either big move.

---

## Factual errors / oversells to correct

1. **STALE (the important one): expressload "model 4 duplication" no longer exists.**
   ARCHITECTURE_REVIEW.md:75 and the D3 table list expressload as "**re-implemented** linkiigs
   place+symtab inline." It does not: `gsasm/expressload.py:751` calls `_linkiigs._place`, `:759`
   calls `_linkiigs._build_symtab`, and a grep for the symtab-building predicates
   (`setdefault(lab` / `is_public` / `len(objects) == 1`) in expressload returns **0**. RATIONALISE
   D3 (lines 145-156) cites specific diverged lines — "expressload does it **unconditionally**:
   `sym.setdefault(segname, seg_base)` … (expressload.py 440)" and "the fix landed twice
   (linkiigs.py 332, expressload.py 501)". **None of that code is present.** The current
   `_defer_shifts` sites in expressload (770/904/958) are the *multi-segment SUPER-type-2* path
   doing its own reloc *classification* — legitimately EL-specific, not duplicated placement. P1
   was evidently completed; the review carries a pre-P1 snapshot forward as live debt and as a
   *current* symptom ("this is the 'had to apply `_defer_shifts` in BOTH' symptom the brief
   flagged"). Correct the D3 entry and drop "model 4" from the "five models" count → it is four.

2. **Oversell: "the machinery is ~80% present" for §3 (ARCHITECTURE_REVIEW.md:91).** True for
   *placement/flow*; false for *symbol resolution* on the ROM path. The `entry_seg` re-routing and
   inverted plain-local precedence (above) are not "20% polish" — they are the multiply-defined
   scope model (D2/P4), the plan's own highest-risk item. The 80% figure applies to the easy
   (kernel) half and hides the hard (ROM) half.

3. **Oversell: byte-exact disk output "falls out as validation" of §3/§3a** (ARCHITECTURE_REVIEW.md
   lines 99-100, 250-251). The residual data contradicts this: 13/16 disk misses are ExpressLoad
   file-length gaps unrelated to placement or recipe; a 100%-code tool is still 20 B short. Neither
   refactor addresses the dominant class.

4. **Minor: "five placement/symbol models" (§3 table).** After (1), it is four (link.py, linkrom,
   linkiigs, kernelcheck `_placed_symtab`). expressload is a *consumer* of linkiigs's two, not a
   fifth model.

5. **Minor but worth stating: BESPOKERY_AUDIT.md Tier-2 #1 vs LINKOS.md.** The audit lists
   "`lda #^Label` bank-byte → 0x00 in the resolved kernel path" as the highest-fan-out Tier-2 gap;
   LINKOS.md WP-K3 and the disk residual (Start.GS.OS @0x1475) confirm it is *one 2-byte site*, not
   high fan-out in the *disk* output. The two docs use "fan-out" differently (source occurrences vs
   output bytes); reconcile so the backlog isn't double-counted. RATIONALISE P0 is the right-sized
   fix and is *independent* of the big refactors — it should be pulled ahead of §3/§3a, not folded
   into them.

---

## Bottom line

The primary's *generality thesis* and its audit discipline hold up — the core is clean and the
smell test is the right axis (with the proxy-for-internal-artifact amendment). But three of the
review's headline moves are mis-weighted:

- **§3** is the plan's *biggest* item (needs the D2 scope model to retire `linkrom`), not a mostly-
  done refactor; split off the tractable kernel half and defer the ROM half.
- **§3a** is speculative infrastructure for a problem the probe proves is solved; ship the probe as
  a CI drift-check and defer the parser.
- **The cheapest byte-exact wins are neither refactor** — they are the ExpressLoad file-tail gap
  (13 files, one root cause, code already exact) and three named content diffs. Keep grinding;
  defer the refactors until a lever demands them.

And correct the record: the expressload duplication the review treats as live debt was already
paid down (P1). Reviewing a pre-P1 snapshot is how a "five models / fix-everything-twice"
narrative outlives the code that motivated it.
