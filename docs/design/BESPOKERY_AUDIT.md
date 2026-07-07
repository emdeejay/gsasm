# Bespokery audit (2026-07-06)

Audit of how issues have been addressed across the toolchain, checking the
project's central claim: `gsasm/*.py` is a **general** AsmIIgs/LinkIIgs
reimplementation (no hardcoded symbol names or module-specific addresses);
module-specific build config lives only in the `work/` harnesses.

**Method:** grep of `gsasm/*.py` for source-symbol / address / filename keying,
plus two read-only Explore passes over `work/*.py` and `work/diskbuilders/*.py`.

## Verdict: the core is clean ✅

No `gsasm/*.py` branch is keyed on a real source symbol; no module-specific bank
address is baked into logic; no filename special-casing. Every module/label name
and `$E1Dxxx`-style address in the core appears **only in explanatory comments**
(examples of a general rule). The one flagged hex, `omf.py:385 0x1000`, is a
base-cancellation probe constant, not an address. Claim holds.

Bespokery is correctly quarantined in the harnesses (by design — they transcribe
the original makefile recipes).

## Harness findings, by tier

### Tier 1 — stale, and now removable (DONE, commit f34284c)
- `kernelcheck.py` documented its flat-binary Layout A/B/C machinery as
  compensating for a *"`PROC ORG ,noskip` prevents ORG evaluation"* bug. **That
  bug is fixed** (ORG-flow, commit f2b89f0). The hardcoded `GQUIT_FLAT_SIZES`
  pads (`0x6800/0x8200/0x8400`) equalled the assembled `GLDR_OBJ_PSTN/PAD` etc.
  → replaced with `GQUIT_PADDED_GROUPS` reading `sel[0].org .. sel[-1].org`;
  rewrote the rationale (the gaps are MakeBin ORG-gap zero-fill that our
  concatenating `_code_image` omits — not a bug); removed dead `SCM_SEG_STARTS`.

### Tier 2 — genuine gsasm gaps papered in harnesses (real core work)
Ranked by how much harness bespokery a core fix would retire:
1. **`lda #^Label` bank-byte → `0x00`** in the fully-resolved (`defer_shifts=
   False`) kernel/link path. Named in *every* `*check` residual — highest
   fan-out. (linkiigs already defers it correctly for the ExpressLoad path.)
2. **linkiigs multi-object symbol scoping** — the "sizing/scoping drift" behind
   WindMgr/ControlMgr/SCSI/Tool019/Tool025. Fixing it would also retire
   `linkrom.py`'s hand-written duplicate-symbol precedence ladder (a parallel
   LinkIIgs living in the harness).
3. **`_reformat_omf_header`** (copy-pasted in `diskbuilders/kernel_os.py` +
   `kernel_setup.py`) — papers linkiigs emitting `SEGNAME=proc/LOADNAME=main`
   vs the shipping `SEGNAME=main/LOADNAME=0`. One linker-convention fix deletes
   both copies.
4. **sel.alt DS bug** — a forward-ref `*` in a `DS` expression isn't offset by
   the segment ORG (DS 4112 vs 5); papered by the `P8_SIZE = 17128` clip in
   `p8_driver.py` (only "works" because sel.alt is the last overlay).
5. **SEG `pending_loadname` is one-shot** (should persist until the next SEG) —
   the one real limitation `kernelcheck._make_groups` reconstructs by hand.
- Minor: `_IGNORE_OPS` silently drops unimplemented pseudo-ops; `aerror` drops
  real message bytes.

### Tier 3 — honest, documented, structural (not "hacks")
- `buildrom.py` substitutes captured artifacts for the FC/FD/FE toolbox banks
  (no native `-lseg/-org` bank placement), so `assert rom == real` is true by
  construction and "% gsasm-built" is a soft sub-metric. Real architectural gap,
  openly documented.
- `probootcheck.py`'s `if m==1666 and n==1668` hardcodes today's exact miss
  count (stops firing if gsasm improves by a byte). Minor fragility.

## Takeaway
Discipline is real: the reimplementation stays general, harnesses "report, don't
patch", and the biggest single item (Tier 1) was already stale thanks to
ORG-flow. Tier 2 is the concrete core-gap backlog; each item is ROM-gated work.
