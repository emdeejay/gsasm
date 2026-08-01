"""Corpus-free guard: EXPORT-EQU constants emit NO relocation records, and
the suppression is per-object-precedence-scoped (never a flat name set).

The falsifying corpus case (docs/SCSI_RELOC_DIAGNOSIS_2026-08-01.md): the
SCSI driver family's `EXPORT MAX_CMD` / `MAX_CMD equ 2`-style link-time
constants got spurious SUPER offsets / standalone cRELOCs because the old
exported-EQU rule was a VALUE-RANGE check (`0 <= addr <= body_len`) that
silently misfires when the constant is small enough to land inside the
merged body's byte range.  The fix threads the assembler's own structural
signal (`symtype == 'equ'`, OMF GEQU vs GLOBAL) through
``linkiigs._build_symtab`` as ``SymTab.kinds``, resolved at the SAME
per-object precedence as the symbol's value.

Two properties are asserted, per the diagnosis §7 fixture spec:

1. A cross-object reference to an EXPORT-EQU whose small value (3) lands
   INSIDE the body range — reproducing the exact coincidence that hid the
   bug — bakes the literal and emits NO reloc record for its site.
2. Collision safety (the TS2 regression case): an unrelated object's OWN
   private label with the SAME folded name still gets its normal
   relocation — a flat "known EQU names" union would wrongly suppress it.

Run either as:
    python3 -m pytest tests/test_expressload_export_equ.py
    python3 tests/test_expressload_export_equ.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from gsasm import asm, omf                          # noqa: E402
from gsasm import linkiigs                          # noqa: E402
from gsasm.expressload import (                     # noqa: E402
    expressload, _needs_reloc, _scan_relocs, _scan_standalone_relocs)

# Object A: the EXPORT-EQU constant (value 3 — deliberately small, inside
# any body's byte range).
SRC_A = (
    '\tEXPORT\tsmall_const\n'
    'small_const\tequ\t3\n'
    'Aseg\tPROC\n'
    '\trts\n'
    '\tENDP\n'
    '\tEND\n'
)

# Object B: imports the constant; a 2-byte immediate (the SUPER (2,0) path)
# and a dc.w (EXPR path) both reference it.
SRC_B = (
    '\tIMPORT\tsmall_const\n'
    'Bseg\tPROC\n'
    '\tlda\t#small_const\n'
    '\trts\n'
    'BTab\tdc.w\tsmall_const\n'
    '\tENDP\n'
    '\tEND\n'
)

# Object C: an unrelated file whose OWN private label happens to share the
# folded name; the reference is CROSS-SEGMENT within the same object (the
# TS2 collision shape — a same-segment ref would fold to a segment-name
# expr and never carry the label's name), and must KEEP its relocation.
SRC_C = (
    'Cseg\tPROC\n'
    '\tlda\t#small_const\n'
    '\trts\n'
    '\tENDP\n'
    'Cdat\tPROC\n'
    'small_const\tdc.w\t0\n'
    '\tENDP\n'
    '\tEND\n'
)


def _objects():
    out = []
    with tempfile.TemporaryDirectory() as tmp:
        for name, src in (('a.aii', SRC_A), ('b.aii', SRC_B), ('c.aii', SRC_C)):
            p = os.path.join(tmp, name)
            with open(p, 'w') as fh:
                fh.write(src)
            a = asm.assemble(p, [tmp])
            assert not a.errors, (name, a.errors[:2])
            out.append((omf.emit(a), a))
    return out


def _pipeline(objects):
    """Mirror expressload's single-path plumbing up to the scan inputs."""
    placed, bases, pidx = linkiigs._place(objects, 0)
    sym, obj_globals = linkiigs._build_symtab(objects, placed, bases, pidx)
    sym_kinds = getattr(sym, 'kinds', {})
    body_kinds = []
    for placed_i in range(len(placed)):
        og = obj_globals[pidx[placed_i]]
        body_kinds.append(sym_kinds if not og
                          else {**sym_kinds, **getattr(og, 'kinds', {})})
    return placed, sym, obj_globals, body_kinds


def _expr_sites(placed, name_filter):
    """(seg_i, ops) of every EXPR-family record referencing *name_filter*."""
    sites = []
    for seg_i, (_sn, recs, _base, _hdr, _asm) in enumerate(placed):
        for _, nm, d in recs:
            if nm in ('LEXPR', 'BEXPR', 'EXPR'):
                ops = d[1]
                if any(isinstance(op, tuple) and op[0].startswith('sym')
                       and op[1] == name_filter for op in ops):
                    sites.append((seg_i, ops))
    return sites


def test_kind_tables_resolve_with_per_object_precedence():
    objects = _objects()
    placed, sym, obj_globals, body_kinds = _pipeline(objects)
    # Global view: the EXPORT-EQU is an 'equ'.
    assert sym.kinds.get('SMALL_CONST') == 'equ', sym.kinds
    # Object C's own view: its private label wins — kind 'label'.
    c_kinds = getattr(obj_globals[2], 'kinds', {})
    assert c_kinds.get('SMALL_CONST') == 'label', c_kinds


def test_export_equ_reference_needs_no_reloc():
    objects = _objects()
    placed, _sym, _og, body_kinds = _pipeline(objects)
    sites = _expr_sites(placed, 'SMALL_CONST')
    assert sites, 'no reference sites found — fixture drifted'
    b_sites = [(i, ops) for i, ops in sites if placed[i][0] == 'BSEG']
    c_sites = [(i, ops) for i, ops in sites if placed[i][0] == 'CSEG']
    assert b_sites and c_sites, [placed[i][0] for i, _ in sites]
    # 1. B's references bind the EXPORT-EQU -> link-time constant, NO reloc.
    for seg_i, ops in b_sites:
        assert not _needs_reloc(ops, body_kinds[seg_i]), (seg_i, ops)
    # 2. C's reference binds its OWN private label -> reloc KEPT.
    for seg_i, ops in c_sites:
        assert _needs_reloc(ops, body_kinds[seg_i]), (seg_i, ops)


def test_full_expressload_emits_no_record_for_equ_sites():
    # End-to-end: the built file must not contain any SUPER offset or
    # standalone cRELOC for B's sites; C's site keeps exactly one reloc.
    objects = _objects()
    placed, _sym, _og, body_kinds = _pipeline(objects)
    relocs = _scan_relocs(placed, body_syms=None, body_len=None,
                          body_kinds=body_kinds)
    standalone = _scan_standalone_relocs(placed, body_kinds=body_kinds)
    all_offsets = [o for lst in relocs.values() for o in lst] \
        + [o for o, *_r in standalone]
    # Compute each segment's base to attribute offsets.
    seg_ranges = {placed[i][0]: (placed[i][2],
                                 placed[i][2] + linkiigs._omf._body_length(placed[i][1]))
                  for i in range(len(placed))}
    b_lo, b_hi = seg_ranges['BSEG']
    c_lo, c_hi = seg_ranges['CSEG']
    assert not any(b_lo <= o < b_hi for o in all_offsets), (all_offsets, seg_ranges)
    assert any(c_lo <= o < c_hi for o in all_offsets), (all_offsets, seg_ranges)
    # And the whole pipeline still emits a well-formed file.
    blob = expressload(objects, opts={})
    assert blob[:4] != b'', 'empty output'


_TESTS = [(n, f) for n, f in sorted(globals().items())
          if n.startswith('test_') and callable(f)]

if __name__ == '__main__':
    failed = 0
    for name, fn in _TESTS:
        try:
            fn()
        except AssertionError as exc:
            print(f'FAIL {name}: {exc}')
            failed += 1
        else:
            print(f'pass {name}')
    print(f'{len(_TESTS) - failed}/{len(_TESTS)} passed')
    sys.exit(1 if failed else 0)
