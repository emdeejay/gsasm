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

Three properties are asserted (diagnosis §7 fixture spec + the 2026-08-01
module-privacy rule the ATP1.ATROM/Epson golds forced):

1. A cross-object reference to an EXPORT-EQU whose small value (3) lands
   INSIDE the body range — reproducing the exact coincidence that hid the
   bug — bakes the literal and emits NO reloc record for its site.
2. A plain INTERIOR label sharing the export's folded name is module-LOCAL
   (MPW scoping): the by-name ref binds the EXPORT — no reloc (ATP1.ATROM's
   CMDADDRS CloseSkt, gold-proven 0x1E95 over the private 0x656).
3. A SEGMENT/PROC name sharing the name stays object-locally visible
   (pass (a)): its own object's refs keep their reloc (the TS2
   DUMMYTABLE/TLBootInit shape, gold-proven) — the collision-safety line.

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

# Object C: an unrelated file whose OWN private INTERIOR label shares the
# folded name, referenced cross-module within the same object.  MPW module
# scoping makes a plain interior label module-LOCAL, so the by-name ref
# binds the program-wide EXPORT — here object A's EQU constant, hence NO
# reloc (the ATP1.ATROM CloseSkt rule, gold-proven: CMDADDRS binds
# ApTalk.aii's exported CloseSkt, not ATP_includes' private label).
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

# Object D: a PROC (segment) NAMED like the export.  Segment names are
# seeded by _build_symtab pass (a) and stay object-private-but-visible —
# D's own reference keeps binding its own PROC (the TS2 DUMMYTABLE /
# TLBootInit shape, gold-proven) and therefore KEEPS its relocation.
SRC_D = (
    'Dseg\tPROC\n'
    '\tlda\t#small_const\n'
    '\trts\n'
    '\tENDP\n'
    'small_const\tPROC\n'
    '\tdc.w\t0\n'
    '\tENDP\n'
    '\tEND\n'
)


def _objects():
    out = []
    with tempfile.TemporaryDirectory() as tmp:
        for name, src in (('a.aii', SRC_A), ('b.aii', SRC_B),
                          ('c.aii', SRC_C), ('d.aii', SRC_D)):
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
    # Object C's plain interior label is module-private (MPW): it is
    # EXCLUDED from C's per-object table, so the name resolves via the
    # global sym to A's export — kind 'equ'.
    assert 'SMALL_CONST' not in obj_globals[2], dict(obj_globals[2])
    # Object D's PROC name IS in its per-object table (pass (a) segment
    # seeding) — kind 'label', so D's own refs keep their reloc.
    d_kinds = getattr(obj_globals[3], 'kinds', {})
    assert d_kinds.get('SMALL_CONST') == 'label', d_kinds


def test_export_equ_reference_needs_no_reloc():
    objects = _objects()
    placed, _sym, _og, body_kinds = _pipeline(objects)
    sites = _expr_sites(placed, 'SMALL_CONST')
    assert sites, 'no reference sites found — fixture drifted'
    b_sites = [(i, ops) for i, ops in sites if placed[i][0] == 'BSEG']
    c_sites = [(i, ops) for i, ops in sites if placed[i][0] == 'CSEG']
    d_sites = [(i, ops) for i, ops in sites if placed[i][0] == 'DSEG']
    assert b_sites and c_sites and d_sites, [placed[i][0] for i, _ in sites]
    # 1. B's references bind the EXPORT-EQU -> link-time constant, NO reloc.
    for seg_i, ops in b_sites:
        assert not _needs_reloc(ops, body_kinds[seg_i]), (seg_i, ops)
    # 2. C's plain INTERIOR label is module-local (MPW): the by-name ref
    #    binds A's exported EQU -> also NO reloc (ATP1.ATROM CloseSkt rule).
    for seg_i, ops in c_sites:
        assert not _needs_reloc(ops, body_kinds[seg_i]), (seg_i, ops)
    # 3. D's SEGMENT name stays visible object-locally (pass (a)): its own
    #    ref binds its own PROC -> reloc KEPT (TS2 DUMMYTABLE shape).
    for seg_i, ops in d_sites:
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
    d_lo, d_hi = seg_ranges['DSEG']
    assert not any(b_lo <= o < b_hi for o in all_offsets), (all_offsets, seg_ranges)
    assert not any(c_lo <= o < c_hi for o in all_offsets), (all_offsets, seg_ranges)
    assert any(d_lo <= o < d_hi for o in all_offsets), (all_offsets, seg_ranges)
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
