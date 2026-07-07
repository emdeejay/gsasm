# Pro.FST residual — root causes + delegable work packages (2026-07-07)

Diagnosis of the remaining Pro.FST divergence after session 11's `temporg` +
`≈` fixes. **Repro/oracle: `python3 work/profst_diag.py`** — prints the diff
runs mapped to source, the OMF record we emit at each site, the symbol-table
view, and the reloc-set diff. All numbers below are its output.

## Current state

| metric | gold | ours | delta |
|---|---|---|---|
| file bytes (EOF) | 25581 | 25576 | −5 |
| code image | 22964 | 22964 | 14 diff bytes, 6 runs |
| SUPER type-0 | 2257 | 2252 | 5 gold-only offsets |
| SUPER type-1 / 27 | 2 / 20 | 2 / 20 | ✓ match |

The 14 code-diff bytes = **cluster A** (4 B, 2 sites) + **cluster B** (10 B,
5 sites). The −5 EOF and the 5 gold-only type-0 offsets are cluster B's
missing relocs. Fixing A+B flips Pro.FST logical-exact (diskcheck 9→10/26).

---

## Cluster B — EQU aliasing a relocatable label (10 B, 5 sites) → **WP1**

Sites `@0x452c/0x4548/0x454e/0x4573/0x457d` (seg NUM_SEQ_BLKS, base 0x451b):
`sta/cmp check_blk`, `sta/ora comp_temp` (ProDOS.FST:16138–16209).

Source (ProDOS.FST:16114–16115, inside `num_seq_blks PROC`):

    comp_temp   equ  and_mask         ;(same ZP location different name)
    check_blk   equ  entries_checked  ;(same ZP location different name)

`entries_checked` / `and_mask` are **`DC.W` data labels** (ProDOS.FST:1244,
1254) in segment `DATA` (a.segs[4], placed base **0x1bb**), offsets 0x414 /
0x402.

- **gold**: sites are relocated (SUPER type-0; the 5 gold-only offsets are
  exactly these sites). Site value = seg-relative address **0x5cf** = 0x1bb +
  0x414 ✓ (and 0x5bd = 0x1bb + 0x402 ✓).
- **ours**: gsasm snapshots the EQU as an absolute constant (symtype `'equ'`,
  value 0x414, symseg None) → `needs_reloc` False → **CONST literal 0x0414**,
  no reloc record.

**Root cause**: an EQU whose operand is a single relocatable label must
*inherit the label's relocatability* (it is an alias, not a constant). gsasm
treats every EQU as absolute.

**Fix sketch** (asm.py, keyed narrowly): at EQU definition time, if the
operand text is exactly one identifier (optionally `±const`) that resolves to
symtype `'label'` whose `symseg` segment is relocatable (`org is None and
temporg is None`), record it in a new map `a.equ_alias[NAME] = (target, addend)`.
Then:
- `needs_reloc`: a name in `equ_alias` → True (via its target).
- `omf._expr_for`: emit as if it were the target label (SEGNAME+offset /
  by-name, the existing label paths), +addend.
- Do **not** change `symtype` (stays `'equ'`) so dp/abs **sizing** is
  untouched (`sta check_blk` already sizes absolute-2 in both builds; only
  the value/reloc differs).

**Blast radius / risks** (why this is gated hard):
- `X equ IDENT` appears **1142×
  in 159 files** (dialog.asm 79, menumgr.asm 72 — ROM modules; SCSI equate
  files 100+). Most alias other *equates* → must stay absolute constants.
  Key strictly on RHS-resolves-to-relocatable-**label**.
- **DON'T** touch label-difference equates (`Max_call equ end_tbl-cmd_tbl`,
  `max_sys equ *-sys_tbl` — Pro.FST itself): those are constants. The
  d90f7e4 revert (ctlPart vs Max_call) is the scar: EQU-vs-import precedence
  must not change. See also 9b4247c (multiply-defined ctlPart).
- Forward-ref alias (EQU before the label is defined) resolves as undefined
  on pass 1 — decide behaviour on the converged pass only; here both RHS are
  backward so the simple case suffices.
- Edge: an alias to a dp-valued label (<0x100) would today size dp; gold
  might size absolute+reloc. Not exercised here; don't chase.

**Acceptance**: profst_diag cluster-B runs gone (14→4 diff bytes), SUPER
type-0 gold-only list empty, EOF delta 0 (25581). fstcheck Pro.FST
22950→22960/22964.

---

## Cluster A — qualified field ref into a no-operand DATA RECORD (4 B, 2 sites) → **WP2**

Sites `@0xec3/@0xec6` (seg SETUP_PARAMS, base 0xe9e), ProDOS.FST:3055–3056:

    stz  expand_record.expand_file
    stz  expand_record.expand_flag

`expand_record Record` (**no operand**, ProDOS.FST:1336) = a named **DATA
segment** (memory lever 20), placed base **0x083c**; interior labels
`expand_flag`=+0, `expand_file`=+2 → 0x083c / 0x083e = **exactly gold's site
values**. Both gold *and* ours emit a type-0 reloc at these sites (offsets in
both SUPER lists); only the stored seg-relative value differs:

- **gold**: 0x083e / 0x083c.
- **ours**: `EXPAND_RECORD.EXPAND_FILE` is **undefined** (val None) — gsasm
  defines qualified `RecName.field` keys only for *offset-template* records
  (cur_record path), not for no-operand DATA records. The undefined name goes
  out as `_undef_external` → LEXPR by name → linkiigs symtab has no such name
  → **0**.

(All other refs to these fields use `with expand_record` + bare `bit
expand_file` — the bare labels are defined, so only the 2 qualified refs
break.)

**Fix sketch** (asm.py): when defining an interior label inside a no-operand
DATA RECORD (`Segment.is_data` under RECORD..ENDR), *also* define the
qualified `RECNAME.LABEL` alias with the same value/symtype `'label'`/symseg
— mirroring the offset-template path. Then `needs_reloc` → LEXPR →
`_expr_for` cross-seg label path emits `EXPAND_RECORD`+offset, linkiigs
resolves 0x83c+2. Additive (new symbol keys only) — but **RomDataMgr in the
ROM uses data records** (ROMDataArea/TranslateTable), so the ROM trio must
gate it (a qualified-name collision would be the only regression vector).

**Acceptance**: profst_diag cluster-A run gone; with WP1 → Pro.FST code
image 0 diffs, **logical-exact 25581/25581, diskcheck 10/26**.

---

## WP3 (independent) — temporg comma-forms

`PROC temporg addr` (whitespace form) landed in 025f204. The **comma forms
are still unparsed** (`_proc` only splits on whitespace):

    Better_Bye  PROC  Export,TempOrg $1000      ; P8 QuitCode.aii
    MediaChk    PROC  ENTRY,TEMPORG HDChk_Org-2 ; AD3.5.main
    ZPCode      Proc  Export,TempORG $1000      ; NetBoot BootLog8/16
    (also NetBoot Patch.aii Quit, NuMustang ×2)

Fix in `_proc`: tokenize the operand on commas as well as whitespace before
the ORG/TEMPORG scan (keep `ORG expr,skip|noskip` working — that comma is
*inside* the org expression). P8's QuitCode is in the P8 disk build →
re-check `p8_driver` + kernelcheck P8 after.

**Acceptance**: kernelcheck P8 improves or holds; drivercheck AD3.5 holds
(±noise); ROM trio green.

---

## Gates (every WP, no exceptions)

    python3 work/buildrom.py      # byte-identical line present
    python3 work/objcheck.py      # 36/61
    python3 work/linkcheck.py     # 61 LINK_IDENTICAL
    python3 work/toolcheck.py     # CORPUS 102588/103138
    python3 work/fstcheck.py      # CORPUS ≥ 50214
    python3 work/drivercheck.py   # CORPUS ≥ 47827
    python3 work/kernelcheck.py   # TOTAL ≥ 51871
    python3 work/diskcheck.py     # logical-exact ≥ 9/26, PHYSICAL 100%
    python3 work/profst_diag.py   # the per-cluster oracle

Tools: `work/profst_diag.py` (this file's oracle), `work/reloc_diag.py`
(record-level gold-vs-ours for any disk file).
