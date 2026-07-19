# Unify the omf.py reloc-value detectors onto one `linear_decompose`

Status: designed, not yet executed. This note is the validated design; the
migration itself is mechanical, gated at every step by the equivalence oracle.

## The finding (validated read-only over the whole ROM+corpus)

The four detectors in `gsasm/omf.py` —

| detector | shape it recognises | emits |
|---|---|---|
| `_linear_reloc` | 1 reloc label, coeff **+1**, + const | `(label, addend)` → `_expr_for` name path |
| `_mul_reloc_expr` | 1 label, coeff **N>1**, in ORG seg | `(SEG+rel)*N+K` ops |
| `_diff_reloc` | **2** labels, coeff **+1/−1**, cross-seg, non-ORG, both defined | `A−B[+K]` ops |
| `_pc_rel_const` | base **cancels** (`label−*`) | (bool) → force literal |

— are **one finite-difference primitive four times**: each re-extracts identifiers
with the same regex and bumps a symbol by `0x100` (or the PC via `asm.loc`) to
recover its coefficient. The differences are (a) the *shape* they accept and (b)
the *scoping* they layer on (segment/ORG/defined/cross-seg). Emit is byte-divergent
**by necessity** — the ROM requires each shape's exact OMF ops — so P3 unifies the
**detection**, not the emit (the "one emitter" is a dispatch-by-shape).

### The primitive
```
linear_decompose(asm, text) -> (terms, K, pc_coeff) | None
    terms     {name: coeff}  for each RELOCATABLE symbol (label/import/undef-external),
              coefficient by finite difference (resolve, then bump by 0x100)
    K         residual value (V = try_eval(text, asm.resolve, asm.loc))
    pc_coeff  coeff of the current PC `*` (bump asm.loc by 0x100)
Constants/equates fold into K (their value is fixed, not link-assigned).
```
Validated: reproduces `_mul_reloc_expr`'s classification **269/269 exactly**. The
apparent "mismatches" for the others were the read-only oracle's *check logic*
(it flagged constants and each detector's extra scoping), not the primitive —
confirmed by inspection (`0`, `1` are constants `_linear_reloc` correctly skips;
`PasCat−ProCat` is a 2-label diff `_diff_reloc` correctly skips on its cross-seg
scope test; `N*160+ScreenStart` is a base-independent constant).

## Empirical corpus (why the oracle is what it is)
Over buildrom + toolcheck + drivercheck + fstcheck: `_linear_reloc` and
`_pc_rel_const` are **ROM-heavy** (byte-exact-oracled, strongest safety);
`_mul_reloc_expr`/`_diff_reloc` fire **0× in the ROM** (only in the non-byte-exact
corpus). ~4,500 distinct expressions overall. So the oracle must be **exact
refactor-equivalence** (`new_ops == old_ops`) for *every* expression across *all*
harnesses, with the ROM's byte-identity + the objcheck set as the byte anchor.

## Migration plan (each step gated on `work/gate.py` AND the ops-oracle)
1. Add `linear_decompose` to `omf.py`.
2. **Ops-oracle harness** (`work/archive/p3_oracle.py`): instrument `_expr_for` to compute,
   for every call, the *would-be* new path alongside the old and assert byte-equal;
   run buildrom + all `*check.py`. Must be green before any detector is removed.
3. Rewrite each detector as a thin classifier over `linear_decompose`, keeping its
   **shape + scope** test and its **exact existing emit**:
   - `_mul_reloc_expr`: `terms` has 1 entry, coeff `N>1`, `_in_org_seg` → its ops.
   - `_diff_reloc`: `terms` has 2 entries `+1/−1`, both `symseg`-known, cross-seg,
     non-ORG'd, both defined → its ops.
   - `_pc_rel_const`: `'*' in text` and every segment's base coefficient cancels
     (net of same-seg term coeffs + `pc_coeff` is 0) → literal.
   - `_linear_reloc`: `terms` has 1 entry coeff `+1` → `(name, K − resolve(name))`.
4. Collapse the shared regex/finite-difference (now only in `linear_decompose`);
   `_reloc_elem` classifies once (dissolving the PC-const-before-linear ordering
   hazard). `_expr_for`'s single-symbol *name* path (by-name vs SEGNAME+offset,
   forward/backward via `ref_off`, data-seg, import, equate) is the single-term
   emitter — it stays, called from the coeff-+1 branch.

## DON'T (would risk the byte-exact ROM)
- **Do NOT merge the emit encodings.** Each shape's OMF ops are ROM-load-bearing;
  the win is one *decomposition*, dispatched to the existing encoders.
- **Do NOT migrate `_mul_reloc_expr`/`_diff_reloc` on the ROM oracle alone** — they
  don't fire there. Require `new_ops == old_ops` over fstcheck/drivercheck too.
- **Do NOT drop the scope tests** (cross-seg/ORG/defined). They are not derivable
  from coefficients; `PasCat−ProCat` shows a 2-label diff that must stay literal.
- Keep `pc_coeff` in the primitive — `label−*` base-cancellation is invisible to
  a symbol-only decomposition (the PC is not an identifier).

## Payoff
Removes four copies of the finite-difference + the ordering hazard, and the
primitive's **superset** (a difference *with* a shift; coefficient-N cross-object)
is exactly what the harder ControlMgr/kernel relocations need but the current
detectors cannot express.
