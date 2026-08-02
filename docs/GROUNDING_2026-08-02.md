# Behavioral Grounding Survey — 2026-08-02

The architecture review's headline charge was that gsasm's semantic rules
are "folklore validated by golden bytes."  This survey tested that charge
against the reference material we actually hold: the MPW 3.0 Assembler
Reference, MPW 3.0 Reference Vol. 1 (both 68K-Mac manuals — neither
mentions the IIgs tools), and — the decisive source — **the GS/OS System
Loader v4.00 source inside our own golden tree** (`GS.OS/Loader/`), which
is the runtime *decoder* of everything our linker/packager emits and
therefore a specification by construction.  Full per-rule reports with
verbatim quotes: `docs/reports/2026-08-02/GROUNDING_{ASM,LINK}.md`.

## Verdict totals

| verdict | assembler rules | linker/OMF rules |
|---|---|---|
| DOCUMENTED | 4 (module scoping, PROC-name-as-ENTRY, CASE, ORG/union) | 6 (first-wins, OMF opcodes, record layouts, SUPER subtype formula, page-list codec, KIND bits incl. `BankRel_Segment EQU $0100`) |
| PARTIAL | 5 (ENTRY/EXPORT edge semantics, EQU rules, duplicate handling, reloc algebra, pass model) | 1 (HET fields exact; compaction formula unfound) |
| NOT DOCUMENTED | 0 outright (sub-clauses within PARTIALs) | 3 (unresolved→0, case-B flagged addends, BankRel consumption mechanics) |
| **CONTRADICTED** | **0** | **0** |

Zero contradictions.  The empirical method was finding real semantics, not
coincidences — but several of its findings were *rediscoveries* of things
the manuals state outright, which is the tax on not reading them first.

## Highlights

- **The module-privacy rule (2026-08-01's most invasive change) is verbatim
  manual text**: "Labels defined inside a code module are local to that
  module. The only way to make these labels accessible to other modules is
  to declare them as EXPORT or ENTRY inside the module." (Asm Ref p.63.)
- **`_reloc_weight`'s weight-0 core is documented algebra** (p.31–33:
  same-segment opposite-sign relocatable terms "cancel the effect of
  relocation, thus producing an absolute value"); the ADD/SUB-chain and
  shift-riding generalization remains gsasm's own, corpus-anchored.
- **The SUPER subtype formulas (13+segnum / 25+segnum), the page-list
  skip/count codec, every OMF opcode, and the KIND bit table are all
  confirmed by the Loader's own source** — including a literal
  `BankRel_Segment EQU $0100`, naming the bit the "BankRel rule" was
  reverse-engineered around.
- **First-definition-wins** is documented for the 68K MPW linker family
  (Vol. 1 p.291); the IIgs linker itself is undocumented in held refs, so
  this stays 68K-family evidence, honestly labeled.
- **The pass model is a documented divergence**: MPW is a fixed two-pass
  design with per-module postfix IR (Asm Ref p.6); gsasm's whole-file
  re-run-with-reseeding is architecturally different, corpus-equivalent,
  and now says so at `assemble()` (with the missing-convergence-check
  finding cross-referenced).

## What remains honestly empirical (keep labeled as such)

1. The duplicate-definition precedence predicates (`_masked_by_data_record`
   and kin) — the manual gives only "identifiers must be unique / local
   overrides global"; the fixture-derived algorithm is ours.
2. The case-B flagged-addend convention (`Label+$80000000`) — no reference
   mentions it; it is a LinkIIGS-binary-side encoding choice, proven only
   by the corpus and the source-sweep table in the old TODO §1.
3. The ~ExpressLoad HET **compaction** (`entry_len = 51 + len(SEGNAME)`)
   — struct fields confirmed against the Loader's declarations; the
   on-disk packing formula itself remains cross-validated-empirical (the
   decoder walks per-segment pointers and is compaction-agnostic).
4. Unresolved-symbol-stores-zero — observed (ATP1 gold), undocumented.
5. `_reloc_weight`'s generalization beyond the documented 1-or-3-term core.

## What changed in the tree

Citations embedded at the load-bearing sites (comment-only, fixtures+gate
green): `_build_symtab` module-privacy + first-wins, `_reloc_weight`,
`assemble()`'s pass-model note, the SUPER-formula and BankRel sites, and
all three dangling `docs/design/CASE_ON.md` references re-grounded to Asm
Ref p.98–99.  The 0.6.0 contract work (review slate item 2) should quote
these citations as its normative anchors and mark items 1–5 above with an
explicit EMPIRICAL tag — the distinction between "documented" and
"corpus-anchored" is now recorded per rule instead of being uniformly the
latter.
