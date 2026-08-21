# Contract: Symbol Precedence

*Written for the 0.5.5/0.6.0 slate, review item 2 (first half). The 2026-08-02
architecture review's finding #1 was that gsasm's symbol-binding semantics —
six composing rules at link time, four independent restatements of one
shadowing rule at assembly time — have a **composite truth table that "exists
nowhere but in the corpus itself"**, so the next contributor cannot derive
where their fix belongs without re-running the last author's experiment. This
document is that table. It is a reference for someone about to change the
linker or one of the four restatements, not an essay.*

**Every clause here was verified against the code, and every clause is
executable somewhere.** The pins live in
`tests/test_linkiigs_symtab_units.py` (link-time, 34 tests) and
`tests/test_symbol_precedence_agreement.py` (assembly-time, 18 tests). If you
change a clause, the failing test tells you which one.

**Provenance tags.** `[DOCUMENTED]` = verbatim in a held reference (MPW Asm
Ref / MPW 3.0 Ref Vol.1 / the GS/OS System Loader v4.00 source in our own
golden tree); `[EMPIRICAL]` = corpus-anchored only, gold-proven but with no
cited authority. Tags follow `docs/GROUNDING_2026-08-02.md` and the per-rule
reports under `docs/reports/2026-08-02/`.

---

## How to use this document

| You are about to… | Read |
|---|---|
| add a rule to `linkiigs._build_symtab` | Part I §1 (pass order), §4 (negative clauses), §5 (the routing checklist) |
| change `resolve` / `needs_reloc` / `sym_kind` / `omf._expr_for` | Part II §2 (the ladder), §3 (the invariants), §5 (checklist) |
| explain a wrong link-time address | Part I §3 (the composite table) |
| explain a wrong operand encoding or size | Part II §3–§4 |
| touch `SymTab` | Part I §6 |

---

# Part I — Link-time binding (`linkiigs._build_symtab`)

## I.1 The outer key is PASS ORDER, not object order

`_build_symtab` builds two things: the program-wide table `sym`, and one
per-object map `obj_globals[oi]` per input object. It fills them in **four
passes with four different precedence policies**:

| pass | what | iteration | policy on `sym` | policy on `obj_globals[oi]` |
|---|---|---|---|---|
| **(a)** | segment names | per object, link order | `setdefault`, **and only if** the link has ONE object **or** this segment hit the case-collision repair (R4) | `setdefault`, always |
| **(b)** | interior labels (`asm.symbols`/`asm.symseg`) | per object, link order | `setdefault`, **and only if** the link has ONE object **or** the label is public (EXPORT, or an ENTRY whose name nobody EXPORTs) | `setdefault`, **except** a module-private plain label, which is withheld (R5) |
| **(c)** | `GLOBAL` records | all objects, placed order | priv=1 (ENTRY) records are **skipped entirely**; otherwise `setdefault` for a single-object link and **OVERRIDE (last-wins)** for a multi-object link | `setdefault` when the owning object is a pre-concatenated **combo** (`asm is None`), **OVERRIDE** for a real object — priv=1 records included |
| **(c′)** | `GEQU` records | all objects, placed order | `setdefault`, kind `'equ'` | **never written** |
| **(d)** | caller `extern` | — | **OVERRIDE**, always last | **never written** |

Consequences, stated as clauses because each one has bitten:

* **P1.** "First-definition wins" `[DOCUMENTED — MPW 3.0 Ref Vol.1 p.291, 68K
  family; the IIgs linker itself is undocumented in held refs]` holds **within
  a pass**. A later pass with an OVERRIDE policy beats every earlier pass
  regardless of link order.
* **P2.** The single/multi-object split on `sym` is about the **number of
  objects in the link**, nothing else. The combo (`asm is None`) split is a
  **different** split and applies **only** to `obj_globals` — a combo's public
  GLOBALs still OVERRIDE in `sym` when the link has more than one object.
  (Pinned: `test_rule3_combo_per_object_map_uses_setdefault_for_globals`,
  which asserts the two tables disagree for the same record.)
* **P3.** Pass (c′) writes `sym` only. An exported EQU is therefore visible to
  the defining object **only through the global table**, so in pass 3 (below)
  *any* per-object entry of that name — from any pass — outranks it.
* **P4.** Pass (d) overrides `sym` but never `obj_globals`. An object that
  defines the name itself keeps its own value in pass 3: **`extern` does not
  beat an object's own definition inside that object's bodies**, only
  everywhere else. (`tests/test_linkiigs_symtab_units.py`'s
  `test_interaction_extern_overrides_every_earlier_rule` is a statement about
  `sym`.)

## I.2 The six rules, and where each one lives

| # | rule | implemented in | provenance |
|---|---|---|---|
| **R1** | first-wins (`_kind_setdefault`) | every pass except (c)-multi-object and (d) | `[DOCUMENTED]` 68K family, Vol.1 p.291 |
| **R2** | ENTRY-vs-EXPORT: an ENTRY is a PRIVATE entry point, so a name EXPORTed by *any* object in the link keeps a same-named ENTRY out of `sym` | pass (b) via the `_all_exports` set; pass (c) via the `priv` bit | `[PARTIAL]` — ENTRY/EXPORT are documented, this precedence is corpus-derived (Finder `GetFileInfo`) |
| **R3** | combo `setdefault`: a pre-concatenated object has no per-file scoping left, so a constituent's GLOBAL must not clobber another constituent's binding in the per-object map | pass (c), `objects[oi][1] is None` | `[EMPIRICAL]` — TS2 `TLBootInit` |
| **R4** | case-collision repair: when a folded interior label has clobbered a PUBLIC segment's own `asm.symbols` entry, pass (a) publishes the segment's authoritative placement base instead | pass (a), the `clobbered` predicate | `[EMPIRICAL]` — notesynth `UpDate` |
| **R5** | module privacy: a plain interior label is module-LOCAL; a by-name reference from a sibling module binds the program-wide EXPORT | pass (b), the `not (is_single_obj or … or lab not in _all_exports)` gate | `[DOCUMENTED]` — MPW Asm Ref p.63, verbatim |
| **R6** | symbol KINDs: `'equ'` = link-time constant (an EXPORTed EQU / a GEQU record), `'label'` = relocatable address; carried **on the value itself** (`linkiigs.Sym`, an `int` subclass with `.kind`), so kind and value are the same object and cannot be written at different insertion points or with different precedence | `_kind_setdefault` / `_kind_override`, which name the two pass policies | `[EMPIRICAL]` — `docs/SCSI_RELOC_DIAGNOSIS_2026-08-01.md` |

There is also a **rule already living outside the table** — see §I.5 before
you decide your change is #7:

| # | rule | implemented in |
|---|---|---|
| **L1** | per-object layering + import satisfaction: pass 3 resolves each segment against `sym.layered(obj_globals[oi])` (the kind-preserving `{**sym, **og}`, §I.6), then puts the *global* value back for a name this object IMPORTs, unless the object satisfies the import with a segment head / EXPORT / ENTRY (a plain interior label does not satisfy it) | `linkiigs.link()` pass 3 |

## I.3 The composite table (multi-object link, real objects)

Read a row as "a definition of this shape, in object *D*". `✗` = absent (so
the name resolves to whatever another pass put there, or is unresolved → 0
`[EMPIRICAL]`).

| definition shape in object D | `sym` | `obj_globals[D]` | what another object sees |
|---|---|---|---|
| public segment name, no case collision | ✗ | base | ✗ (a PROC name must not shadow a cross-object EXPORT) |
| public segment name, case-collided (R4) | placement base (pass a) | base | the R4 base — until pass (c) overrides it |
| private segment name (`KIND & 0x4000`) | ✗ | base | ✗ |
| EXPORTed interior label | address (pass b, re-asserted by its own GLOBAL in pass c) — but if another object EXPORTs the same name, pass (c)'s OVERRIDE means the **last placed** one wins | address | the last-placed EXPORT's address |
| ENTRY interior label, name EXPORTed nowhere | address | address | that address |
| ENTRY interior label, name EXPORTed elsewhere (R2) | the other object's EXPORT | **its own ENTRY** | the EXPORT |
| plain interior label, name EXPORTed nowhere | ✗ | address | ✗ |
| plain interior label, name EXPORTed elsewhere (R5) | the other object's EXPORT | **✗ (withheld)** | the EXPORT |
| EXPORTed EQU (emits GEQU) | value, kind `'equ'` | ✗ (P3) | the value |
| non-exported EQU | ✗ | ✗ | ✗ — it has no `symseg`, so pass (b) skips it entirely |
| combo constituent's GLOBAL, priv=0 | last constituent (override) | **first** constituent (R3) | the last constituent's |
| combo constituent's GLOBAL, priv=1 (ENTRY) | ✗ | address | ✗ |
| caller `extern` | value, kind `'label'` | unchanged (P4) | the extern |

For a **single-object** link every "only if" in §I.1 is satisfied, so passes
(a) and (b) publish *everything* into `sym`, pass (c) reverts to `setdefault`,
and R5 never engages (there is no sibling object whose EXPORT could win).

## I.4 Interactions — which rule wins when two apply

| # | interaction | winner | why | pinned by |
|---|---|---|---|---|
| **I1** | R4 (pass a) vs a same-named EXPORTed interior label of the same object (pass b) | R4's segment base | pass order: (a) before (b), both `setdefault` | `test_interaction_rule4_beats_rule1b_within_one_object` |
| **I2** | R4 (pass a) vs another object's public EXPORT GLOBAL (pass c) | the EXPORT, **in `sym`** | pass order + (c)'s multi-object OVERRIDE; the R4 repair survives in `obj_globals[D]`, which pass 3 layers back on top for D's own bodies | `test_interaction_export_global_pass_c_beats_rule4_in_the_global_table` |
| **I3** | R2 vs R5 | both apply, to different tables | an ENTRY is demoted from `sym` (R2) but is explicitly **exempt** from R5, so it stays its own object's binding | `test_interaction_rule2_exempts_the_entry_from_rule5_module_privacy` |
| **I4** | exported relocatable LABEL vs exported EQU, same name | the LABEL, in **either** link order | pass (b) publishes every exported label before pass (c′) looks at a single GEQU, and (c′) is a `setdefault`; surviving kind is `'label'` | `test_interaction_exported_label_beats_exported_equ_in_either_order` |
| **I5** | R5 vs R6 (the KIND, not the value) | R5 re-KINDs the reference | with D's own plain label withheld, D's own reloc classification reads the KIND attached to the *other* object's EXPORT — an EXPORT-EQU makes D's reference `'equ'` | `test_interaction_rule5_module_privacy_beats_rule6_equ_lookup_source` |
| **I6** | `extern` vs everything in `sym` | `extern`, and all kinds flatten to `'label'` | pass (d) is last and overrides; there is no GEQU behind an extern, so reloc suppression falls back to `_scan_relocs`'s value range | `test_interaction_extern_overrides_every_earlier_rule`, `test_rule6_caller_extern_is_always_kind_label` |
| **I7** | `extern` vs the defining object's own map (pass 3) | the object's own definition | P4 — `sym.layered(og)` puts `og` on top | (clause P4; `link()` pass 3) |

## I.5 Negative clauses — what does NOT happen

* **N1. R3 × R4 and R3 × R5 are structurally EXCLUSIVE.** Both the
  case-collision repair and module privacy require an `Asm` — R4 reads
  `asm.symseg`/`asm.segs`, R5 reads `asm.exports`/`asm.entries` and the
  `_all_exports` union, which only contributes for objects with an `Asm`. A
  combo object has `asm is None`. Therefore **a combo's segment names are
  never published into `sym`, no matter what collides with them**, and a
  combo's interior labels are never withheld for module privacy — a combo has
  no interior labels in the table at all, only its GLOBAL records. A rule that
  "fixes" a combo by reaching for `asm` is not a rule; it is a crash.
* **N2. Pass (c′) never writes a per-object map** (P3), so there is no
  "exported EQU wins inside its own object" case to reason about.
* **N3. Pass (a) and pass (b) never override.** Anything that must beat an
  earlier definition has to be routed to a pass whose policy is OVERRIDE, or
  to a later layer (L1). Adding an override inside (a) or (b) silently
  reverses first-wins for *every* symbol shape those passes touch.
* **N4. `_all_exports` is a union over the whole link**, not a per-object set.
  R2 and R5 both key off it, so a name becomes "exported" the moment *any*
  object exports it — including objects that no reference will ever reach.
* **N5. `{**a, **b}` yields a bare `dict`, so the merged table has no
  `.kinds` *attribute* — but it does still have the kinds**, because they
  ride on the values (`Sym`), not in a parallel table. Read them as
  `t[name].kind`, or merge with `SymTab.layered`, which returns a real
  `SymTab` (and so keeps `.kinds` and keeps refusing a kind-blank
  insertion). What is *gone* is the pre-0.5.5 failure mode this clause used
  to warn about: a merged table whose kinds were silently EMPTY.

## I.6 `SymTab`: kinds live ON the values

The binding tables ARE `{name: value}` mappings — every pass in §I.1 writes a
value under a name, and `omf._eval` reads it back as an integer. A symbol's
KIND is a property **of that binding**, so it lives on the value:
`linkiigs.Sym` is an `int` subclass carrying `.kind`, and `SymTab` is
`dict[str, Sym]`. Value consumers are unaffected (a `Sym` *is* an `int`);
kind consumers read `t[name].kind`, or `t.kinds` — a read-only
`{name: kind}` view **derived from the values on demand**, so it cannot
disagree with them.

The load-bearing property is **precedence parity**: whichever definition won
the value is the one the kind lookup reports. That is now structural rather
than a convention — the kind is the same object as the value, so it survives
`{**a, **b}`, `dict(t)`, `a | b`, a comprehension, and a `.get()` handed to
another table. A flat "known EQU names" set unioned across a multi-object
link does not have this property and mis-classifies collisions (TS2's 37 —
`docs/SCSI_RELOC_DIAGNOSIS_2026-08-01.md` §5).

`SymTab` is **loud about kind-blankness**, which is the defect this shape
exists to remove (before 0.5.5 the kind lived in a parallel `.kinds` sidecar
dict that every merge idiom above dropped, and `SymTab(existing_dict)` never
populated it at all — architecture review 2026-08-02, slate item 6):

* a value that is not a `Sym` is accepted **only** when it re-binds a name the
  table already holds, in which case it inherits that binding's kind. That is
  the location counter — `omf._build_body` and `expressload._scan_relocs` write
  `sym['__LOC__'] = seg_base + pos` straight into the table as they walk a body;
* everything else raises, including `SymTab(plain_mapping)`. Pass
  `kind=` to state the kind for a whole plain mapping;
* `.kinds` is read-only: a kind with no binding behind it is precisely the
  parity violation.

`link()` pass 3 builds its per-object layer with `sym.layered(og)` (L1),
which returns a `SymTab`. `gsasm/expressload.py` still hand-merges the two
`.kinds` views beside its `{**sym, **og}`; that is now redundant — both
routes read the same kinds off the same values — and it is correct either
way. Pinned by `test_symtab_dict_splat_merge_carries_the_kinds_on_the_values`
and `test_symtab_construction_from_a_plain_dict_demands_kinds`.

## I.7 The routing checklist for rule #7

Before adding a rule to `_build_symtab`, answer these in the commit message:

1. **Which pass?** State it as (a)/(b)/(c)/(c′)/(d) — or L1, if the rule is
   really about *layering* rather than *binding*, in which case it belongs in
   `link()` pass 3 next to the import-satisfaction rule and not in the table
   at all.
2. **Which table?** `sym`, `obj_globals`, or both — and with which policy in
   each. If your rule needs first-wins in one and last-wins in the other, say
   so explicitly; that combination already exists (R3) and is legitimate.
3. **Does it survive N1?** If it reads `asm`, it cannot fire for a combo
   object. Say what a combo does instead.
4. **Does it fire for a single-object link?** Every "only if" in §I.1 collapses
   there. A rule that is silent for single-object links must say so; a rule
   that is *not* silent changes every merged single-object load file.
5. **What happens in a later pass?** If a later OVERRIDE pass can reach the
   same name, your rule decides nothing in `sym` (I2). Check pass (c)-multi
   and pass (d).
6. **Which KIND does it write?** Kind and value ARE one object now
   (R6/§I.6), so the question is unavoidable: `Sym(val, kind)`, or
   `_kind_setdefault`/`_kind_override`, which take it as an argument. A bare
   `t[name] = val` re-binds an existing name and keeps ITS kind (the
   `__LOC__` counter); on a new name it raises. Precedence parity is the
   invariant.
7. **What is the negative clause?** State the shape your rule must *not*
   touch, and add it to §I.5 with a test.

---

# Part II — Assembly-time shadowing (the four restatements)

## II.1 The four, and the question each answers

| function | question | consumed by |
|---|---|---|
| `asm.resolve(name)` | **which** definition binds — the VALUE | everything; `evaluate()`, all emitters |
| `asm.sym_kind(name)` | **what** that definition is: `'label'` / `'equ'` / `'import'` / `None` | `asm.is_reloc()` → operand SIZING (direct-page vs absolute vs long); `omf._expr_for` and the OMF classifiers |
| `asm.needs_reloc(expr)` | does this reference need an OMF relocation **record** | `omf.py`'s emit paths — it is the **gate** that decides whether `_expr_for` is called at all |
| `omf._expr_for(asm, text, segname, …)` | **what the record says**: by-name, `SEGNAME`+offset, or a literal | the emitted `EXPR`/`LEXPR`/`RELEXPR` bodies |

Two helpers complete the set and must be counted as restatements when you
change anything here:

* `omf._undef_external(asm, name)` — the implicit-external rule, which
  `needs_reloc` does **not** implement (D1). Every `needs_reloc` call site in
  `omf.py` spells `or _undef_external(...)` beside it.
* `asm._with_active_field(u)` — the shared WITH lookup (row 5), deliberately
  factored so `resolve`, `needs_reloc` and `sym_kind` cannot drift on that one
  branch. It is the model for how the rest of this ladder *should* be shared.
* `asm._cur_seg()` — the shared **row 0** lookup, factored the same way for
  the same three callers (0.6.0; it closed X2, see §II.5).

Two lookups outside the ladder that look like row 0 but are **not** callers of
`_cur_seg()`, deliberately:

* `asm._equ_alias_of(operand)` asks its own version without `_rseg` — it runs
  at EQU *definition* time, where "current segment" can only mean the segment
  being assembled, and an emit cursor left over from a fixup would be the
  wrong scope.
* `omf._expr_for` reads `asm._rseg` raw (row 0 is `—` for it above): with no
  cursor there is no segment to encode `SEGNAME`+offset *against*, so the
  fallback would name a segment the record does not belong to.

## II.2 The precedence ladder

Highest first. The ✓/— columns say which restatement implements the branch.
`cur` = the current emit segment.

| # | branch | `resolve` | `sym_kind` | `needs_reloc` | `_expr_for` |
|---|---|---|---|---|---|
| 0 | current segment = `_rseg`, **falling back to the last segment when `_rseg is None` and emit is enabled** — `asm._cur_seg()`, one lookup, three callers | ✓ | ✓ | ✓ | — (uses `_rseg` raw) |
| 1 | `@`-label scope + nearest definition, segment-local | ✓ | via `_symkey` | via `_symkey` | via `_symkey` |
| 2 | `equ_alias` (an EQU that is a second name for a relocatable label) | — (returns the value) | — (kind stays `'equ'`) | ✓ **first branch of all** | ✓ (rewrites to the target, unless the current segment defines the bare name) |
| 3 | the enclosing `RECORD` template's own fields (`cur_record`) | ✓ | — | — | — |
| 4 | any local of `cur` (`seg_local` ∪ `seg_equ` ∪ `seg_seed` ∪ a `cur`-scoped `SET`) **beats** a WITH-active field | ✓ (`local_here`) | ✓ (ordered branches) | ✓ (ordered branches) | ✓ (`seg_local` only) |
| 5 | WITH-active record field (`_with_active_field`) — a template field is an absolute offset, an instance/data field is a relocatable label | ✓ | ✓ | ✓ | via `sym_kind` |
| 6 | `seg_local[cur]` / `seg_seed[cur]` → the local label | ✓ | ✓ `'label'` | ✓ True unless `cur` is ORG'd/temporg | ✓ same-segment encoding |
| 7 | `seg_equ[cur]` → the PROC-local equate | ✓ | ✓ `'equ'` | ✓ (never relocates) | via `sym_kind` |
| 8 | a `SET` scoped to `cur` (`setvar_seg`/`setvar_val`), even when label-masked out of `symbols` | ✓ | ✓ `'equ'` | ✓ | via `sym_kind` |
| 9 | exact-spelling file-scope EQU variant (`case_symbols`, opt-in `case_equ_variants`) | ✓ | ✓ `'equ'` | **—** (X1) | via `sym_kind` |
| 10 | `symbols[u]` — the file-wide binding, **last definition wins within one assembly** | ✓ | ✓ (with `_foreign_proc_equ_masks_label`) | ✓ | via `sym_kind` |
| 11 | declared `IMPORT` | ✓ (link mode) | ✓ `'import'` | ✓ | ✓ by name |
| 12 | prior pass's `seed` / `seed_type` | ✓ | ✓ | ✓ | via `sym_kind` |
| 13 | caller `extern` | ✓ (link mode) | — | — | — |
| 14 | undefined everywhere = implicit external | — | — | **—** (D1) | ✓ by name |

Note the **order difference at rows 5 and 9**: `resolve` gates the WITH lookup
on `local_here` (rows 6–8 only) and consults `case_symbols` *after* it, while
`sym_kind` checks `case_symbols` *before* the WITH field. A file that has both
an exact-spelling EQU variant and a WITH-active field of the same folded name
would bind them differently. No such source exists in the corpus, and the cell
could not be constructed for the test matrix without inventing one — recorded
here as a known unpinned corner.

## II.3 The two agreement invariants

These are what `tests/test_symbol_precedence_agreement.py` sweeps over a
generated matrix of (fixture × current segment × name) cells — where "current
segment" includes **no cursor at all** (`None` in `_MATRIX`), the state the
whole main assembly pass runs in and the only state in which row 0 is
observable:

> **INVARIANT A (kind ↔ emission).** `sym_kind(n) == 'equ'` ⟺ `_expr_for`
> emits a pure literal push, and that literal carries exactly `resolve(n)`.
>
> **INVARIANT B (relocatability ↔ emission).** `needs_reloc(n)` ⟺ `_expr_for`
> emits a symbolic reference (an OMF `0x83` label push — by name or
> `SEGNAME`+offset).

Invariant B matters because `needs_reloc` is the **gate**: when it says False
the emitter bakes literal bytes and never asks `_expr_for` anything. A cell
where B fails is a cell where one of the two is unreachable or is asked to
carry a constant inside a relocation record.

## II.4 Documented differences — cells where the four legitimately differ

| # | cell | what differs | why it is not a bug |
|---|---|---|---|
| **D1** | a symbol undefined everywhere | `needs_reloc` False, `_expr_for` by-name | the implicit-external rule lives in `omf._undef_external`, which every call site ORs in beside `needs_reloc`. `needs_reloc`'s own docstring used to claim it; the code never did |
| **D2** | a label in an ORG'd segment | `sym_kind` `'label'`, `needs_reloc` False, `_expr_for` still `SEGNAME`+offset | the value is already absolute, so no record is needed; the KIND still drives absolute SIZING. **`needs_reloc` is the gate, `_expr_for` is the encoder — never infer relocatability from what `_expr_for` would emit** |
| **D3** | a label in a TEMPORG segment | `sym_kind` `'label'`, `needs_reloc` False, `_expr_for` a baked literal | the code runs at `temporg` after being copied there; the linker must not re-place it |
| **D4** | `devName equ ParBlock+2` (`equ_alias`) | `sym_kind` `'equ'` but `needs_reloc` True and `_expr_for` emits the target label | an alias is a second NAME for a relocatable address. `needs_reloc` and `_expr_for` special-case `equ_alias` first; `asm.is_reloc()` re-checks it so sizing agrees. **This is the cell that proves kind alone is not a relocation decision** |
| **D5** | a declared `IMPORT` | `sym_kind` says `'import'`, not `'label'` | vocabulary only: `is_reloc`, `needs_reloc` and `_expr_for` all treat it as relocatable |

## II.5 Rows 0 and 9 — where `needs_reloc` restated the ladder short

Both had the same root cause: **`needs_reloc` restated the ladder without two
branches that `resolve` and `sym_kind` both have.** Neither moved a golden
byte, and only because of which phase each function is called from — which is
precisely the review's complaint that agreement was untested.

**X2 (row 0) is CLOSED as of 0.6.0; X1 (row 9) is still live and pinned.**

* **X1 — the exact-spelling EQU is invisible to `needs_reloc`** (ladder row 9).
  With `case_equ_variants={'HANDLE'}`, a file-scope `Handle equ $10` and a
  relocatable label `HANDLE`: `resolve('Handle')` → `$10`,
  `sym_kind('Handle')` → `'equ'`, `_expr_for` → literal `$10`, but
  `needs_reloc('Handle')` → **True**, because it folds every identifier
  through `_symkey` and sees only the label. The emitter asks `needs_reloc`
  first, so this shape emits an `EXPR` record whose contents are a constant:
  the resolved bytes are right, the object record stream is not. Unobservable
  in the corpus because the one build that opts into `case_equ_variants` has
  no relocatable label colliding with the variant.
  Pinned: `test_disagreement_case_exact_equ_is_invisible_to_needs_reloc`.
* **X2 — `needs_reloc` had no current-segment fallback** (ladder row 0).
  **CLOSED, 0.6.0.** `resolve` and `sym_kind` each spelled `if seg is None and
  self.emit_enabled and self.segs: seg = len(self.segs) - 1` inline;
  `needs_reloc` restated the row as a bare `seg = self._rseg` and lost it. With
  no emit cursor — which `sym_kind`'s own comment calls the normal state of the
  main assembly pass — `resolve`/`sym_kind` consulted the last segment's local
  tables and `needs_reloc` consulted none. On a `SET` masked by a same-named
  storage label (CloseView `v set h+2`): `resolve` → `4`, `sym_kind` → `'equ'`,
  `needs_reloc` → **True** (the masking label).

  The fix was **not** a fourth copy of those three lines. Row 0 now exists
  once, as `asm._cur_seg()`, and `resolve` / `sym_kind` / `needs_reloc` are its
  three callers — the `_with_active_field` shape (§II.6 point 4). Golden gate:
  **byte-identical, all 52 metrics, zero improvements.** The reason it moved
  nothing is call-site phase, not luck of shape: `needs_reloc` is reached only
  from `omf.py`'s emit paths, and every one of them runs under `_build_body`,
  which sets `asm._rseg` first — so the fallback never fires in a corpus build.
  Pinned: `test_agreement_row0_current_segment_fallback_is_shared_not_restated`,
  which overrides `_cur_seg` to prove all three read it rather than restate it,
  plus a whole no-cursor column across the swept matrix (`None` in `_MATRIX`).

Closing either is a **behaviour change**, not a refactor: give it its own
commit, predict the metric movement, run the gate, and update §II.2/§II.5 and
the pinning test (which carries an assertion message telling you so).

## II.6 The checklist for changing a restatement

1. **Which question are you changing?** Value (`resolve`), kind (`sym_kind`),
   record-or-not (`needs_reloc`), or record contents (`_expr_for`)? A fix
   applied to the wrong one produces right bytes for the wrong reason and
   breaks the invariants for every other cell.
2. **Which ladder row?** Add it to §II.2 with its ✓/— column — the empty cells
   in that table *are* the drift surface (row 9 is X1; row 0 was X2, closed).
3. **Do both invariants still hold?** Run
   `tests/test_symbol_precedence_agreement.py`. If your change makes a
   registered divergence disappear, the sweep fails loudly ("STALE REGISTER")
   — that is the register refusing to rot, not a broken test.
4. **Does the branch belong in a shared helper?** `_with_active_field` is the
   precedent: one lookup, three callers, no drift possible. **Default to yes.**
   The 0.6.0 X2 fix is the worked example: the obvious repair was to paste the
   three fallback lines into `needs_reloc`, which would have made a fourth
   restatement of row 0 and left the next author free to drift it again;
   `_cur_seg()` makes the row exist once instead. Share the LOOKUP, not the
   ANSWER — each caller still translates it into its own vocabulary (value /
   kind / record-or-not), which is why this is not the same thing as unifying
   the four functions.
5. **Does it change a KIND?** Then it changes SIZING through `is_reloc`, which
   changes instruction lengths, which moves every later address. Size the blast
   radius before the gate does it for you.
6. **Does the link-time table need the same rule?** Kinds cross the boundary:
   `sym_kind`'s `'equ'` and `linkiigs.Sym.kind`'s `'equ'` are the same word and feed
   the same reloc suppression. A change on one side without the other is how
   the TS2 0x88a regression shape happens.

---

## Appendix — where the pins are

| clause group | pinned by |
|---|---|
| Part I §1–§4 (passes, rules, interactions) | `tests/test_linkiigs_symtab_units.py` (34 tests: `test_ruleN_*`, `test_interaction_*`, `test_symtab_*`) |
| Part I §6 (`SymTab`, kinds on the values) | `test_symtab_dict_splat_merge_carries_the_kinds_on_the_values`, `test_symtab_construction_from_a_plain_dict_demands_kinds` |
| Part II §3 (both invariants, generated matrix) | `tests/test_symbol_precedence_agreement.py::test_matrix_invariant_{a,b}_*` |
| Part II §4 (D1–D5) | `test_difference_d1_*` … `test_difference_d4_*`, `test_cell_import_*` |
| Part II §5 (X1, still live) | `test_disagreement_case_exact_equ_is_invisible_to_needs_reloc` |
| Part II §5 (X2, closed) | `test_agreement_row0_current_segment_fallback_is_shared_not_restated`, plus the `None` (no-cursor) column of `_MATRIX` |
| the reloc-record walk that consumes all of this | `tests/test_omf_units.py`, `tests/test_expressload_*.py`, `tests/test_linkiigs_super_type26.py` |
