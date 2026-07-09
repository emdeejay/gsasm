# CASE ON — case-sensitive symbols (GS.OS Loader last mile)

Blueprint for a **fresh session** to execute atomically.  Do NOT attempt this
incrementally — it was tried and oscillated (28→109→88→182→2378 diff on the
Loader) because case-consistency is a whole-model property, not a per-site one.

## Why
`Loader.a` line 1 sets `CASE ON` — the **only** file in the entire corpus that
does (0 ROM/tool/FST/driver sources use it; verified). Under CASE ON, MPW keeps
symbols case-SENSITIVE, so it distinguishes:
- `find_Segment` (ExpressLoad.a) ≠ `Find_Segment` (Segments.a)
- `load_segment` (ExpressLoad.a) ≠ `Load_Segment` (Segments.a)
- `set_mark` (ExpressLoad.a) ≠ `Save_Mark` (Files.a)

gsasm uppercase-folds all symbol names, so each pair collides and a reference
binds to the wrong duplicate segment. This is the **entire** remaining Loader
residual (the last 28B; work/loader_placed.py is at 99% = 16562/16590 without it).

## The model — ONE rule, applied everywhere at once
Add `Asm.case_sensitive` (default False), set by the `CASE ON`/`OFF` directive,
and one method:

    def _fold(self, name):
        return name if self.case_sensitive else name.upper()

**Invariant (this is what makes it converge):** a symbol name is folded EXACTLY
ONCE — at the moment it first enters a table or the OMF bytes — and is then
carried/compared/emitted **as-is**, never re-folded. `_fold ≡ str.upper` for every
non-CASE-ON module, so the whole change is byte-neutral for the ROM/tool/FST/
driver corpus BY CONSTRUCTION (gate proves it). The oscillation last time was
caused by MIXING: some sites folded, some read as-is, so names got double-folded
or mismatched. Pick the invariant and apply it to ALL sites below in one commit.

## Every site (from the reverted attempt — this list is complete)
asm.py:
- `_symkey`: the plain return + the two @-key builds → `_fold`.
- `define_label`: `last_global`, the `cur_record.field` qualified key, the
  data-record `SEGNAME.label` alias → `_fold`. (main key already via `_symkey`.)
- `_proc`: the segment name `name = (ln.label or '').upper()` → `_fold`.
- data-`RECORD` open: the segment `name` → `_fold`.
- ENTRY / EXPORT / IMPORT / WITH operand names + `.add()` into
  `entries`/`exports`/`imports` → `_fold` (CRITICAL — else both cases land as one
  entry and `is_public` matches both).
- `_note_entry_seg` (the stored segname), `_maybe_global` (`u`) → `_fold`.
- record helpers: `record_sizes` key (ENDR), `_ds_size` key, `_explode_record_
  fields` prefix (and iterate `sname` as-is — keys are already folded) → `_fold`.
- `resolve`: the `extern.get(name.upper())` lookup → `_fold`.
- Add the `CASE` directive handler: `case_sensitive = operand=='ON'`.

omf.py (all have `asm`):
- `_expr_for`: the same-seg compare `asm.segs[..].name.upper() == segname`, and
  the by-name emits `_omfstr(name.upper())` / `_omfstr(other_seg.name.upper())`
  → `asm._fold(...)`. (`nu`/`segname` are already folded.)
- `emit_segment`: `segname = (seg.name or 'main').upper()`, `_nm` → `asm._fold`.
- `_diff_reloc.locops`: `_omfstr(seg.name.upper())` → `asm._fold`.
- compare callbacks `bumped_res`, `_res0`, `_mul_reloc_expr._res`,
  `_branch_xseg` (`m.group(1).upper()`) → `asm._fold`.
- LEAVE `u = (ln.op or '').upper()` (op code, not a symbol).

linkiigs.py:
- `_decode_segname`: drop the `.upper()` — read the SEGNAME **as-is** (omf writes
  it folded; linkiigs only ever parses gsasm-emitted objects, so bytes are
  authoritative). This is the "read as-is" half of the invariant.
- `_build_symtab`: the interior-label `lab.upper()` (×2), the GLOBAL/GEQU
  `d['label'].upper()` (×2) → **as-is** (already folded at source). The
  `clobbered` compare `_asm.segs[home].name.upper()` → `_asm._fold(...)`.
- (segnames in `placed` come from `_decode_segname` = as-is now.)

harness: `work/loader_placed.py` line ~109 — pass `sd['segname']` **as-is** (NOT
`.upper()`), matching the read-as-is invariant.

## Execute + gate
- Work in a **worktree off current main** (mind the stale-base gotcha in the
  handoff — verify `git merge-base` is recent, else rebase).
- Make ALL the edits above in ONE pass, then run once:
  - `python3 work/loader_placed.py` → expect ~4B residual (the DC.W import-diff),
    i.e. the 3 case-collisions gone.
  - Gate the corpus (must be byte-identical — `_fold≡upper` guarantees it):
    buildrom True · objcheck 36/61 · linkcheck 61 · toolcheck 102588 ·
    fstcheck 50234 · drivercheck 47827 · kernelcheck 60184 · diskcheck 11/26.
- Then: SCM DC.W LEXPR (~1731B — categorise first, likely a bounded class like
  RECORD-sizeof / typed-DS were) → integrate `loader_placed` into
  `kernel_os._build_gsos` → **diskcheck 12/26** (the flip).

The ~4B DC.W import-difference (`DC.W zloader_end-zloader_start`) is separate: omf
bakes a CONST `ffff` instead of an EXPR record — `_linear_reloc` bails on undef
imports, `_diff_reloc` needs both defined. Emit an EXPR for an import±const diff.
