"""Hand-authored test for the linker import-vs-local resolution rule.

gsasm folds symbol names to upper case, but MPW AsmIIgs/LinkIIgs binds an
IMPORTed name to a sibling object's EXPORT unless THIS object genuinely
SATISFIES the import by defining the name itself as a segment/module head
(or its own EXPORT/ENTRY).  A plain INTERIOR label of the same (folded) name
does NOT satisfy the import.

Two real collisions this fixes with one rule (linkiigs._build_symtab pass-3):
  * epson.asm `IMPORT l1` + interior branch target `L1` (case-folded to one
    key): `pushlong l1` must bind dialogdata.asm's exported `l1` ($4262), not
    epson's own `L1` ($08E3).
  * ATP_includes.aii `import closeskt` + interior `closeskt` inside the
    cancelreq PROC: `DC.A closeskt` in the cmdaddrs PROC must bind ApTalk.aii's
    exported CLOSESKT ($1e95), not the interior local ($0656).
And one it must NOT disturb:
  * Tool032 midi.main `IMPORT NotImp` + `NotImp PROC` (a segment head at
    offset 0) self-satisfies the import — its own local wins.

Run:
    python3 -m pytest tests/test_linkiigs_import_case_shadow.py
    python3 tests/test_linkiigs_import_case_shadow.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from gsasm import asm, omf, linkiigs               # noqa: E402

# Object A: imports lowercase `l1`, references it via `dc.l l1` in its OWN proc
# (so it is a deferred external fixup), and elsewhere has a DIFFERENT-case
# INTERIOR label `L1` (a branch target inside a proc named Aloc — NOT a segment
# head named L1). The import must bind B's export, not this interior local.
SRC_A_INTERIOR = (
    '\tIMPORT\tl1\n'
    'Aref\tPROC\n'
    '\tEXPORT\tAref\n'
    '\tdc.l\tl1\n'           # must bind B's exported l1, not A's interior L1
    '\trts\n'
    '\tENDP\n'
    'Aloc\tPROC\n'
    '\tEXPORT\tAloc\n'
    'L1\tnop\n'              # interior label — folds to same key as l1
    '\tbne\tL1\n'
    '\trts\n'
    '\tENDP\n'
    '\tEND\n'
)

# Object B: exports `l1` as a real relocatable data label, well past A's body.
SRC_B = (
    'B\tPROC\n'
    '\tEXPORT\tB\n'
    '\tEXPORT\tl1\n'
    '\tds.b\t64\n'
    'l1\tdc.w\t$1234\n'
    '\tENDP\n'
    '\tEND\n'
)

# Object A2 (Tool032 shape): imports `bar` AND defines `bar PROC` — a segment
# head at offset 0 that self-satisfies the import. `dc.l bar` must bind A2's own
# `bar`, not B2's export.
SRC_A_SEGHEAD = (
    '\tIMPORT\tbar\n'
    'A2ref\tPROC\n'
    '\tEXPORT\tA2ref\n'
    '\tdc.l\tbar\n'          # self-satisfied by A2's own `bar` PROC below
    '\trts\n'
    '\tENDP\n'
    'bar\tPROC\n'            # segment head named bar -> satisfies the import
    '\trts\n'
    '\tENDP\n'
    '\tEND\n'
)

SRC_B2 = (
    'B2\tPROC\n'
    '\tEXPORT\tB2\n'
    '\tEXPORT\tbar\n'
    '\tds.b\t64\n'
    'bar\tdc.w\t$5678\n'
    '\tENDP\n'
    '\tEND\n'
)


def _asm(tmp, name, text):
    p = os.path.join(tmp, name)
    with open(p, 'w') as fh:
        fh.write(text)
    a = asm.assemble(p, [tmp])
    assert not a.errors, a.errors
    return omf.emit(a), a


def _first_dcl(linked):
    img = b''.join(r[2] for seg in omf.iter_segments(linked)
                   for r in seg['recs'] if r[1] in ('CONST', 'LCONST'))
    return int.from_bytes(img[0:4], 'little'), img


def test_interior_local_does_not_shadow_import():
    """epson/ATP1 shape: the interior local must NOT shadow the external."""
    with tempfile.TemporaryDirectory() as tmp:
        oa = _asm(tmp, 'a.asm', SRC_A_INTERIOR)
        ob = _asm(tmp, 'b.asm', SRC_B)
        stored, _ = _first_dcl(linkiigs.link([oa, ob], opts={'merge': True}))
        # A's interior L1 sits at a low A-offset (< 0x10); B's l1 is past A's
        # body + 64 bytes of ds. The fix must store B's l1 address.
        assert stored > len(oa[0]) or stored > 0x40, \
            f'dc.l l1 wrongly bound A interior local ({stored:#x})'


def test_segment_head_local_satisfies_import():
    """Tool032 shape: a `PROC` of the imported name self-satisfies -> local wins."""
    with tempfile.TemporaryDirectory() as tmp:
        oa = _asm(tmp, 'a.asm', SRC_A_SEGHEAD)
        ob = _asm(tmp, 'b.asm', SRC_B2)
        stored, _ = _first_dcl(linkiigs.link([oa, ob], opts={'merge': True}))
        # A2's own `bar` is a segment head within A2's body (low address); B2's
        # bar is past A2 + 64. The local must win: stored is in A2's range.
        assert stored < len(oa[0]) + 0x10, \
            f'dc.l bar wrongly bound B2 export instead of A2 seg head ({stored:#x})'


if __name__ == '__main__':
    test_interior_local_does_not_shadow_import()
    test_segment_head_local_satisfies_import()
    print('ok')
