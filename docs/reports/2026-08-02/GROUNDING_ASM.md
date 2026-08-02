# Grounding gsasm's empirical assembler rules against MPW 3.0 Assembler Reference (1988)

Source: `ref/MPW_3.0_Assembler_Reference_1988.pdf`, extracted with
`pdftotext -layout` to
`/private/tmp/claude-501/-Users-mdj-src-gsasm/a5794041-df24-4aed-8c97-b8fdc88c5ec8/scratchpad/asm_ref.txt`
(paged copy `asm_ref_paged.txt`). Page numbers below are the **printed book
page numbers** (as in the manual's own running headers/TOC), not PDF physical
page indices. Key sections used:

- Ch. 2 "Coding Conventions" — "Scope of definitions" p.15-18, "Absolute and
  relocatable expressions" p.31-33.
- Ch. 4 "Assembler Directives" — PROC/ENDPROC p.62-63, RECORD/ENDR (data
  module) p.64, RECORD/ENDR (template) p.76-78, EQU/SET p.68-69,
  EXPORT/ENTRY p.85-86, IMPORT p.87, SEG p.92, CASE p.98, ALIGN p.100-101,
  ORG p.102.
- Ch. 1 "About the Assembler" — "Overview of the assembly process" p.6.
- Glossary p.311-316.

gsasm code referenced: `gsasm/asm.py` (`define_label`, `resolve`, `sym_kind`,
`assemble`, and the `_proc_equ_reuses_*` / `_masked_by_data_record` /
`_label_reuses_entry_elsewhere` / `_prior_modscope_dup` /
`_label_shadows_proc_head` helper predicates around lines 1240-1520),
`gsasm/linkiigs.py` (`_build_symtab` around line 264), and
`gsasm/expressload.py` (`_reloc_weight` around line 325).

---

## A. Module/label scoping ("module privacy")

**gsasm rule:** a module-interior label not declared ENTRY/EXPORT is
invisible outside its module; a by-name cross-module reference binds the
program-wide EXPORT.

**Verdict: DOCUMENTED.**

> "A definition is considered to have local scope if it occurs inside a code
> or data module. Local objects may be accessed only from within the module;
> you may use the object's identifier in different modules or outside the
> module without causing an identifier conflict." (p.15, "Scope of
> definitions")

> "Labels defined inside a code module are local to that module. The only
> way to make these labels accessible to other modules is to declare them as
> EXPORT or ENTRY inside the module." (p.63, PROC and ENDPROC)

> "Since EXPORT identifiers are global to the file in which they are
> declared, the Assembler treats references to such identifiers from
> modules other than the one that actually defines the identifier as
> imports of those identifiers." (p.17, "Imported and exported objects")

This last sentence is close to a verbatim statement of gsasm's "importers
bind the EXPORT" rule (`linkiigs.py` `_build_symtab`, comment: "every
IMPORTer must bind the export"). gsasm's implementation is code-side
(`asm.py` `define_label`'s `_label_reuses_entry_elsewhere`,
`_prior_modscope_dup`, `_masked_by_data_record`, `_label_shadows_proc_head`)
and link-side (`linkiigs.py` `_all_exports` / `_build_symtab`); both map
directly onto this paragraph plus the PROC/ENDPROC quote above.

---

## B. ENTRY semantics

**gsasm rule:** ENTRY makes a name reachable across modules of one assembly;
importers from elsewhere bind the EXPORT if one exists; a bulk ENTRY list
at file top only declares scope (doesn't define).

**Verdict: DOCUMENTED**, with one nuance PARTIAL (see below).

> "EXPORT makes them accessible in modules in all files linked with the
> file containing it; ENTRY makes them accessible only in modules within
> the same assembly." (p.85, EXPORT and ENTRY)

"Assembly" is precisely defined elsewhere as one source file → one object
file: "given an assembly-language source text file `Name.a`, the Assembler
will create an object code file `Name.a.o`" (p.7). So "same assembly" =
same source file/object file — exactly matching gsasm's per-object
`entries` vs. whole-link `exports` distinction in `linkiigs.py`.

> "An EXPORT directive mentioning an identifier previously listed in an
> ENTRY directive supersedes the ENTRY. An ENTRY directive mentioning an
> identifier previously listed in an EXPORT directive has no effect."
> (p.86, EXPORT and ENTRY rules list)

This documents EXPORT-beats-ENTRY, but for the *same name inside one file*
(one directive superseding another in the same source text). gsasm's rule
is broader: it applies EXPORT-beats-ENTRY **across objects at link time**
(name ENTRYed in object X, EXPORTed by object Y — importers everywhere bind
Y's EXPORT while X's own references still see its ENTRY). This
cross-object case is not addressed by the manual, which only discusses
ENTRY/EXPORT precedence within a single file. **Verdict for this specific
extension: PARTIAL** — the single-file directive-precedence rule is
documented and gsasm's cross-object generalization is a plausible but
unstated extrapolation from it (linkiigs.py comment cites the concrete
falsifying case: Finder `Misc.aii ENTRY GetFileInfo` vs `GSOS.aii EXPORT
GetFileInfo`).

> "You must place each EXPORT or ENTRY directive in your source text before
> defining any of the identifiers it affects." ... "You export identifiers
> occurring within a module by including an EXPORT or ENTRY directive
> inside the module, before they are defined." (p.86, EXPORT/ENTRY rules)

This documents that a bulk ENTRY/EXPORT list is a forward declaration, not
a definition — matching gsasm's split between `Asm._lbl` (defines) and the
`ENTRY name[,name]` handler (declares only) at `asm.py` ~line 2909
("`ENTRY name[,name]` only DECLARES entries; the labels are defined
[elsewhere]").

**What happens if a listed ENTRY name is never defined in that module?**
**Verdict: NOT DOCUMENTED.** The manual states the *placement* rule (before
definition) but is silent on the error/no-op behavior if the name is never
subsequently defined anywhere in the file. Searched "undefined" / "never
defined" / error-code sections — no hit. Stays empirical in gsasm.

---

## C. EQU semantics

**gsasm rule:** proc-interior EQU is module-local; an EQU reusing an
EXPORT/ENTRY/IMPORT/label name stays local and does not clobber the global
binding; `EXPORT name` + `name EQU N` = link-time constant, no relocation.

**Verdict: DOCUMENTED** for the core local/global search order and EQU
non-redefinability; **PARTIAL / NOT DOCUMENTED** for the specific masking
heuristics gsasm layers on top.

> "When the Assembler encounters a symbol in an effective address in a code
> module, it searches for its value first in the code module's local
> symbol table (if the symbol has been defined), then in the global symbol
> table." (p.69, EQU and SET)

This directly documents "local shadows global" search order, which is the
foundation of gsasm's `_proc_equ_reuses_global` / `_proc_equ_reuses_visible_equ`
/ `_proc_equ_reuses_import_winner` predicates (`asm.py` ~1248-1312): a
proc-scoped EQU is recorded in `seg_equ` (the local table) and does not
overwrite `self.symbols` (the global table) for a name that already denotes
a global label/import/export.

> "EQU assigns a permanent value; once an identifier has been used in an
> EQU directive it may not be redefined in another EQU directive within its
> scope, with the one exception that an EQU with the same value generates a
> warning." (p.68, EQU and SET)

This says redefinition of the *same* EQU identifier is illegal (except a
same-value re-EQU, which merely warns) — it does not describe what happens
when a **different kind** of object (label, IMPORT, EXPORT) already owns
the name and an interior EQU reuses it; that specific masking behavior
(kept in `seg_equ`, invisible outside the PROC) is gsasm's own empirical
resolution, not covered by the manual. **The exact-value-defers-to-warning
edge case matches nothing in gsasm** (gsasm's `defcount` bookkeeping
tracks redefinitions but does not special-case "same value ⇒ warning
instead of error" — worth a note but not a correctness bug since gsasm
does not currently emit MPW-style diagnostics at all).

> "Relocatable expressions are allowed only inside code modules and data
> modules." / "Equates defined outside modules or inside code modules may
> take any value." (p.68, EQU and SET)

`EXPORT name` + `name EQU N` → link-time constant, no relocation: **Verdict:
DOCUMENTED indirectly** via the absolute/relocatable-expression algebra
(see E below) — an EQU'd constant is by definition an *absolute* value
(not a code/data label), so any reference to it is never subject to
segment relocation. The manual doesn't spell out the OMF-record
consequence (GEQU vs. GLOBAL, no RELOC record) explicitly — that
link-format-level fact is documented instead in the *IIgs* linker/OMF
spec, not this MPW-68k manual. gsasm's `expressload.py` comment cites its
own diagnosis doc (`docs/SCSI_RELOC_DIAGNOSIS_2026-08-01.md`) rather than
this manual for that specific consequence — appropriately, since it's an
IIgs OMF-level fact, not an MPW-68k assembler-semantics fact. **Verdict:
NOT DOCUMENTED in this manual** (expected — wrong manual for OMF format
details; the *scope/absoluteness* half is documented, the *OMF-encoding*
half is out of scope for this document).

---

## D. Duplicate definitions (label/label, label/EQU, label/SET, proc name/interior label)

**Verdict: PARTIAL.** The manual states a strong global-uniqueness rule and
an EQU-specific non-redefinition rule, but does **not** document any of
gsasm's specific precedence/masking heuristics for local-vs-global name
collisions across module boundaries.

> "All identifiers assigned to global objects must be unique within the
> assembly." (p.15, "Scope of definitions")

> "Local definitions override global definitions." (p.15, "Scope of
> definitions")

These two bullets together are the *only* general duplicate-definition
statement in the manual: global names must be unique (implying a hard
conflict/error if two truly-global objects share a name), and a local
definition simply "overrides" (shadows) a global one of the same name
within its module — consistent with gsasm's masking approach in spirit.
But the manual gives no algorithm for what "override" means when the
*global* binding is itself ambiguous across objects at link time (gsasm's
`_masked_by_data_record`, `_label_reuses_entry_elsewhere`,
`_prior_modscope_dup`, `_label_shadows_proc_head`, and the SET-vs-label
`set_vs_label` predicate in `asm.py` ~1314-1499) — each of those is
derived from a specific golden-byte fixture (as the code comments say:
"Fixtures 036/039/042/044", "commit 5612d89") and is **NOT DOCUMENTED**;
it stays empirical/folklore, confirming the ARCHITECTURE_REVIEW finding.

EQU-vs-EQU redefinition is the one sub-case that **is** documented (see C
above): illegal, except same-value ⇒ warning. SET-vs-SET is also
documented: "SET assigns a temporary value; the same identifier may be
redefined with another SET directive" (p.68) — unconditionally allowed,
matching gsasm's `redefinable=True` path. Label-vs-label, label-vs-EQU,
label-vs-SET (gsasm's `set_vs_label`), and PROC-name-vs-interior-label
(`_label_shadows_proc_head`) collisions across *module* boundaries are not
addressed anywhere in the manual — searched "redefin", "already defined",
"duplicate identifier", "multiply defined", "name conflict" (the one
"name conflict" hit, p.69, is the unrelated forward-reference-to-global
warning case quoted under C).

---

## E. Expression relocatability algebra

**Verdict: DOCUMENTED** for the core absolute/relocatable term-cancellation
concept that grounds `_reloc_weight`'s weight-0 case; **PARTIAL** for the
generalization gsasm applies (arbitrary ADD/SUB chains, shift-riding, and
use outside the manual's stated EA/DC-only context).

> "When an identifier is used as a label, the Assembler assigns it a value.
> This value is absolute or relocatable... Code and data module identifiers
> and code or data labels are relocatable... Template identifiers and
> fields are absolute." (p.31, "Absolute and relocatable expressions")

> "An absolute expression may contain relocatable values, alone or in
> combination with absolute terms. All terms in such an expression must
> already have a value; there may be no forward references. If there are
> relocatable terms there must be exactly one pair of them, and the
> relocatable terms
> • may be used only in effective addresses of machine instructions and DC
>   or DCB directive statements
> • must access the same segment
> • must refer both to code or both to data
> • must consist of terms with opposite signs (+ and -)
> The pairing of relocatable terms of opposite sign is allowed in an
> absolute expression because the subexpression involving the difference
> between the relocatable terms cancels the effect of relocation, thus
> producing an absolute value." (p.32, "Absolute expressions")

> "A relocatable expression may contain relocatable values, alone or in
> combination with absolute terms, provided that it conforms to these
> rules:
> • There must be either one or three relocatable terms.
> • If there are three relocatable terms, two of them must be paired [i.e.
>   cancel as above].
> • Relocatable symbols may be combined only with the + and - operators."
> (p.33, "Relocatable expressions")

This is the crown citation the task asked for, and it grounds
`expressload._reloc_weight`'s central claim precisely: two relocatable
terms of opposite sign in the same segment "cancels the effect of
relocation" — exactly gsasm's weight==0 case (comment: "a same-segment
`End-Start` difference... needs NO relocation record"). ADD contributing
+1 and SUB contributing -1 per relocatable operand is the natural
op-list encoding of "opposite signs... cancel."

Where gsasm's `_reloc_weight` **goes beyond** the documented algebra
(PARTIAL, not a contradiction — a link-time OMF-expression classifier
necessarily operates on already-legal assembled expressions, not on
source-level legality):
- The manual restricts relocatable-term pairing to EA operands and
  DC/DCB statements specifically, and to exactly 1 or 3 total relocatable
  terms (with exactly one canceling pair). gsasm's `_reloc_weight` computes
  a generic running sum over an arbitrary ADD/SUB chain of any length and
  applies it to any OMF expression it is asked to classify, without
  checking segment/code-vs-data agreement (it trusts the input is already
  a legally-assembled expression, since MPW's assembler enforced that at
  source level).
  * Also: only relocatable terms combined with `+`/`-` are legal per the
    manual; `_reloc_weight`'s handling of any other operator returns
    `None` (falls back to conservative "assume needs reloc"), which is
    consistent with — but stricter/safer than — the manual's rule.
- Shift-riding (SHL/`>>` leaves the shifted value's weight unchanged) is
  **NOT DOCUMENTED** anywhere in this chapter; it is not one of the
  described relocatable-expression forms at all (the manual's relocatable
  algebra only covers `+`/`-`combinations). This is gsasm's own inference
  from OMF-record shapes (`>>N` shift-encoding), not from this manual.
- The EQU-as-constant short-circuit (`kinds.get(op[1]) == 'equ'` → weight
  contribution 0) is consistent with "template identifiers and fields are
  absolute" / EQU values being absolute (p.31), but the manual never
  discusses OMF relocation *records* at all (that's IIgs-linker territory,
  out of scope for this MPW-68k manual) — **NOT DOCUMENTED** for that
  specific consequence, same as noted under C.

---

## F. Pass model

**Verdict: PARTIAL / effectively CONTRADICTED on the "3 passes" framing** —
worth flagging as the most interesting finding after E.

> "The MPW Assembler processes your source text in two passes. The first
> pass reads the source text, defines and expands all macros, and defines
> all symbols. It determines the length of the object code and resolves
> forward references... As it starts to read each code or data module on
> its first pass, the Assembler creates an internal file in Macintosh
> memory containing a translation of your source text into postfix
> notation. At the end of each module, the Assembler performs its second
> pass, converting the postfix file into object code." (p.6, "Overview of
> the assembly process")

Glossary: "pass: One processing cycle of the Assembler." (p.314)

Two things to note:

1. The manual's "two passes" is **not** gsasm's model. MPW's pass 1 is a
   single whole-file sweep that defines all symbols/macros and produces a
   per-module postfix intermediate; pass 2 happens **per module**,
   immediately after that module's own pass-1 sweep, converting postfix to
   object bytes and then releasing memory before the next module starts.
   It is architecturally closer to "one global symbol-definition pass +
   N per-module code-generation passes" than to gsasm's "re-run the whole
   file N times, reseeding symbol values/kinds from the previous full run"
   (`asm.py` `assemble()`, `for _ in range(passes - 1): ... _run_once(...,
   seed=prev.symbols, ...)`). gsasm's model exists because it doesn't
   build a real postfix IR; it is a legitimate behavioral emulation
   strategy but the manual does not describe or motivate it — **NOT
   DOCUMENTED** as such.
2. gsasm's `passes=3` default and its rationale (`asm.py` docstring:
   "Three passes are needed for correct @-label forward-reference sizing
   when a PROC-local EQU... shares a name with a code label defined later
   in the same segment... The ROM corpus is fully converged at two passes,
   so the extra pass is a no-op") is **entirely empirical** — the manual
   states a fixed, unconditional two-pass model with no notion of
   "convergence" or needing extra passes for symbol-masking edge cases.
   Nothing in the manual suggests MPW's real assembler would need more
   than its stated two passes for any input (it doesn't have gsasm's
   reseed-from-previous-full-run architecture, so the question doesn't
   even arise for it) — **NOT DOCUMENTED**, and arguably the closest thing
   to a soft CONTRADICTION in this inventory: gsasm's whole pass strategy
   is a different algorithm solving the same forward-reference problem the
   manual's single deterministic two-pass design was built to avoid
   needing extra passes for.
3. "Is a symbol allowed to change value between passes?" — **NOT
   DOCUMENTED.** The manual's pass 1 is described as fully defining all
   symbols in one sweep (with pass 2 doing no symbol definition, only code
   generation), which implicitly suggests symbols are stable once pass 1
   for a module completes — but the manual never states a convergence
   guarantee or forbids multiple sweeps. gsasm's `assemble()` also performs
   no convergence check (confirmed by reading the code — it always runs
   exactly `passes` full sweeps unconditionally, matching the docstring's
   own framing "no convergence check").

---

## G. Segment/PROC naming

**Verdict: DOCUMENTED.**

> "If you write a name in the label field of a PROC directive, it becomes
> the identifier of the code module that begins there. The identifier is
> global to the assembly file. If you do not provide an identifier, you
> must define entry points inside the module by using ENTRY or EXPORT
> directives." (p.62, PROC and ENDPROC)

> "If you do not declare a code module as EXPORT, the Assembler declares it
> as ENTRY by default." (p.62-63, PROC and ENDPROC)

This documents gsasm's PROC-name handling precisely: `asm.py` ~3157
`private = 'EXPORT' not in up  # PROC without EXPORT is private` — i.e. a
PROC name defaults to ENTRY-only (module-global/assembly-visible, not
link-visible) unless EXPORT is given, matching "declares it as ENTRY by
default" exactly. And a PROC's own name **is** a global (module-identifier)
symbol per the manual — confirming `self.private = False # KIND 0x4000
(PROC without EXPORT)` encodes the ENTRY/EXPORT OMF distinction correctly
(private bit set = ENTRY-only/no GLOBAL-export record; unset = EXPORT).

> "All code modules up to the next SEG directive are grouped in the
> specified segment... Code modules grouped in the same segment do not have
> to be contiguous in the source file." / "SEG takes effect at the next
> PROC, FUNC, or MAIN directive. It remains in effect until the next SEG
> directive." (p.18 and p.92)

This documents CODE-module-vs-segment boundaries: a segment is a
*name grouping* of PROC/FUNC/MAIN modules, independent of module
boundaries — matching gsasm's `self.seg_loadname` comment ("PERSISTS
across PROCs until the next SEG (MPW semantics), not one-shot").

**Anonymous main module** (gsasm's `self.segs = [Segment(None, 'main',
None, 1)]`, the implicit segment holding statements before any PROC):
**Verdict: PARTIAL.** The manual documents that identifiers/statements can
exist "outside any module" with implicit CODE-scope defaults ("The default
designation for identifiers listed outside any module is CODE," p.85/p.87),
confirming such a region exists and behaves like an implicit module for
scope purposes, but it never names or formalizes it as gsasm's synthetic
"main" segment object — that internal representation choice is gsasm's own
and is **NOT DOCUMENTED** as such (expected; it's an implementation detail,
not user-facing assembler behavior).

---

## H. CASE ON/OFF semantics

**Verdict: DOCUMENTED.** This fully re-grounds the three citations to the
deleted `docs/design/CASE_ON.md`.

> "The operand ON, Y, or YES forces the Assembler to treat uppercase and
> lowercase letters as distinct. For example, the Assembler treats `abcd`
> and `Abcd` as two different identifiers... The operand OFF, N, or NO lets
> the Assembler treat uppercase and lowercase letters identically. For
> example, the Assembler treats `abcd` and `AbCd` as the same identifier.
> It is the preset condition." (p.98, CASE)

> "When CASE OFF is in effect, the Assembler generates exported and
> imported identifiers entirely in upper case... When CASE ON is in effect,
> the Assembler preserves the capitalization used in the source text."
> (p.98-99, CASE)

This is a verbatim match for gsasm's `_fold()` (`asm.py` ~664-670):
default (`case_sensitive = False`) folds every name through `str.upper()`
("generates... entirely in upper case"); `CASE ON` (the one file in the
corpus, `Loader.a`) keeps `case_sensitive = True` and preserves exact
spelling ("preserves the capitalization used in the source text"). The
code comment's claim that `Loader.a`'s `CASE ON` is "the only file in the
whole corpus that sets it" is a corpus-empirical fact (not something the
manual would state), but the *semantics* it implements are fully
documented at p.98.

One nuance also documented and worth noting for `case_equ_variants`
(exact-spelling EQU variants kept alongside the folded default, used for
Finder's `handle`/`Handle` DP-global collision): the manual's CASE OBJECT
mode is exactly this use case —

> "CASE OBJECT lets you preserve case distinctions in your object file
> while ignoring them in your source text. ... Case distinctions can
> create a problem when you are using large files of equates—for
> instance, the standard Macintosh equates." (p.99, CASE)

gsasm doesn't implement CASE OBJECT as a directive (the corpus apparently
never sets it), but `case_equ_variants` solves the identical practical
problem CASE OBJECT was designed for, by a different (fixture-driven,
opt-in) mechanism — **PARTIAL**: the *problem* is documented (exact quote
above even names "large files of equates" as the motivating case,
foreshadowing exactly the Finder DP.equ scenario gsasm's comment
describes), but gsasm's specific solution (`case_equ_variants` opt-in set)
is not CASE OBJECT and is not documented as such.

Also documented and correctly unimplemented-as-exempt in gsasm: "The CASE
directive has no effect on segment names. They are always case-sensitive"
(p.98, note) — worth checking gsasm's segment-name folding for a possible
gap (not verified in this pass; flagged for follow-up, not a finding
against the CASE rule itself).

---

## I. SET vs EQU redefinability; RECORD/ORG interactions

**Verdict: DOCUMENTED.**

SET vs EQU redefinability — see quotes under C/D above:
> "EQU assigns a permanent value; once an identifier has been used in an
> EQU directive it may not be redefined in another EQU directive within
> its scope... SET assigns a temporary value; the same identifier may be
> redefined with another SET directive." (p.68)

This is an unconditional, clean match to gsasm's `redefinable` flag
(`define_label(..., redefinable=False)`, SET call sites pass
`redefinable=True`).

**RECORD/ORG union-sizing, citation to p.102 — VERIFIED, exact match:**

> "If you use ORG with no operand, the Assembler sets the current location
> counter to the maximum positive or maximum negative location-counter
> value assigned to the module up to this point. The Assembler sets the
> current location counter to the maximum positive value for code modules
> and for incrementing templates and data modules. It sets the current
> location counter to the maximum negative value for decrementing
> templates and data modules." (p.102, ORG)

gsasm's code comment at `asm.py` ~554-561 quotes this almost verbatim
("MPW Asm Ref p.102: 'ORG with no operand sets the location counter to the
maximum ... value assigned to the module up to this point'") — **citation
confirmed accurate**, word-for-word aside from elision. The manual even
gives the exact worked example gsasm's comment alludes to: a `Region`
RECORD template with a `Top/Left/Bottom/Right` variant overlaid by
`topLeft/botRight` via an ORG-to-`Top` reset, followed by a bare `ORG`
that "sets the location counter to the highest value so far... Although
the mapping is exact, using ORG guarantees a correct final value for the
location counter... particularly useful... when a variant field does not
exactly map onto another variant" (p.102-103) — this is a textbook
description of union sizing via RECORD + bare ORG, exactly matching
gsasm's `_rec_hi_stack` high-water-mark mechanism (`asm.py` ~2877-2899,
comment: "a union: the high-water across the record's variant ORG
overlays").

RECORD/ENDR itself (data-module vs. template disambiguation by operand
shape) is also fully documented at p.76: "When used to define a data
module, RECORD has either no parameters or one of the terminal symbols
EXPORT or ENTRY as its first parameter. When used to define a template,
RECORD always has at least one parameter—the absolute expression offset,
the terminal symbol IMPORT, or the identifier origin enclosed in braces."
This grounds gsasm's `_is_data_seg` disambiguation logic (`asm.py`
~2668-2681) precisely — the code's own comment paraphrases this rule
closely.

---

## Free wins: manual-documented behavior our comments call "empirical/unexplained"

- The `@-label` scope-reset-on-any-non-@-label rule in `define_label`
  (`asm.py` ~1380-1387, comment "MPW Asm Ref, '@-labels': scope extends
  both directions to the nearest non-@ label") is **already correctly
  cited** — verified against p.17: "the scope of an @-label extends
  through the source text, in both directions, to the nearest label that
  doesn't begin with @." Exact match, already grounded, no action needed.
- IMPORT's own scope rules ("Imported identifiers local to a module must
  be listed in an IMPORT directive inside that module before they are
  mentioned in any other statement," p.87) directly document gsasm's
  treatment of module-scoped `IMPORT` as equivalent to a local definition
  for scope purposes — this generalizes and further grounds rule A/B and
  isn't currently cited anywhere in `asm.py`'s comments; worth a citation
  add near wherever `self.imports` scoping is implemented.
- CASE's segment-name exemption ("The CASE directive has no effect on
  segment names. They are always case-sensitive," p.98) is a small,
  concrete, currently-uncited rule worth spot-checking against gsasm's
  segment-name handling.

---

## Summary table

| Rule | Verdict | Citation |
|---|---|---|
| A. Module/label scoping ("module privacy") | DOCUMENTED | p.15 ("Local objects may be accessed only from within the module..."), p.63 ("Labels defined inside a code module are local..."), p.17 ("...treats references... as imports...") |
| B. ENTRY semantics | DOCUMENTED (core); PARTIAL (cross-object EXPORT-beats-ENTRY extension) | p.85 (EXPORT vs. ENTRY file-linked/assembly-only scope), p.7 ("assembly" = one file), p.86 (EXPORT supersedes ENTRY — same-file only); undefined-ENTRY-name behavior NOT DOCUMENTED |
| C. EQU semantics | DOCUMENTED (local/global search order, EQU non-redefinition); PARTIAL/NOT DOCUMENTED (specific masking heuristics; OMF-reloc consequence) | p.69 (local-then-global search), p.68 (EQU permanent, SET temporary) |
| D. Duplicate definitions | PARTIAL — general principle documented, specific precedence heuristics NOT DOCUMENTED | p.15 ("must be unique within the assembly"; "Local definitions override global definitions"), p.68 (EQU/SET rules) |
| E. Expression relocatability algebra | DOCUMENTED (core cancellation concept); PARTIAL (gsasm's generalized weight function goes beyond the manual's stated EA/DC-only, 1-or-3-term restriction; shift-riding NOT DOCUMENTED) | p.31-33 ("Absolute and relocatable expressions" / "Absolute expressions" / "Relocatable expressions") |
| F. Pass model | PARTIAL / effectively soft-CONTRADICTED on "3 passes" framing | p.6 ("Overview of the assembly process" — states a fixed two-pass, per-module-pass-2 architecture, not gsasm's whole-file-reseed N-pass model); convergence/passes=3 rationale NOT DOCUMENTED |
| G. Segment/PROC naming | DOCUMENTED (PROC name defaults to ENTRY, is module-global; SEG groups modules independent of boundaries); PARTIAL (anonymous main module as internal construct) | p.62-63 (PROC and ENDPROC), p.18 & p.92 (SEG) |
| H. CASE ON/OFF semantics | DOCUMENTED | p.98-99 (CASE: Specify treatment of lowercase letters) |
| I. SET vs EQU redefinability; RECORD/ORG | DOCUMENTED (both halves; p.102 citation verified word-for-word) | p.68 (EQU/SET), p.76 (RECORD data-module vs. template disambiguation), p.102-103 (ORG, worked Region-template union example) |

**Counts:** DOCUMENTED (fully or as the dominant verdict): A, G, H, I = 4.
PARTIAL (documented but narrower/broader, or mixed core+extension): B, C,
D, E, F = 5 (of these, F is flagged as the closest thing to a soft
CONTRADICTION). NOT DOCUMENTED (searched, no hit): none reached that
verdict as a *sole* verdict — every rule had at least a partial anchor in
the manual; the "NOT DOCUMENTED" findings above are all sub-clauses within
otherwise-PARTIAL/DOCUMENTED rules. CONTRADICTED (outright): none found —
the manual never states something gsasm's code actively does the opposite
of; the closest is F's soft contradiction (different pass architecture
entirely, not a same-architecture disagreement).
