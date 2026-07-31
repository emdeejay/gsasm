"""Hand-authored test for the linker import-vs-case-folded-local fix.

gsasm folds symbol names to upper case, but MPW AsmIIgs/LinkIIgs is
case-SENSITIVE.  epson.asm declares `IMPORT l1` and also has a private code
label `L1` (a branch target).  Under gsasm's fold both become the one key
`L1`, so a `pushlong l1` (an external sym83 fixup) resolved to epson's own
local `L1` (0x08E3) instead of dialogdata.asm's exported `l1` (0x4262) — an
8-byte drift (delta 0x397F, dialogdata's placed base).

Fix: asm.py records each import's exact spelling and flags a fold in
`_import_case_shadow` when a local label's exact spelling DIFFERS from a
same-fold import (a distinct symbol under case-sensitive linking).
linkiigs._build_symtab then binds the external EXPORT (in the global `sym`)
for such a flagged fold, instead of letting the local shadow it — but only
when `sym` genuinely holds a DIFFERENT value, so a SAME-case self-satisfying
import (Tool032 `IMPORT NotImp` + `NotImp PROC`) keeps its own local.

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

# Object A: imports lowercase `l1`, has a DIFFERENT-case local `L1` (a branch
# target), and references the import via `dc.l l1` (an external fixup).
SRC_A = (
    '\tIMPORT\tl1\n'
    'Aref\tPROC\n'           # the external reference lives in its OWN proc, so at
    '\tEXPORT\tAref\n'       # assembly time `dc.l l1` is a deferred external fixup
    '\tdc.l\tl1\n'           # (the local L1 below is out of this proc's scope) —
    '\trts\n'               # it must bind B's exported l1, not A's local L1.
    '\tENDP\n'
    'Aloc\tPROC\n'
    '\tEXPORT\tAloc\n'
    'L1\tnop\n'              # local branch target — folds to the same key as l1
    '\tbne\tL1\n'
    '\trts\n'
    '\tENDP\n'
    '\tEND\n'
)

# Object B: exports `l1` as a real relocatable data label.
SRC_B = (
    'B\tPROC\n'
    '\tEXPORT\tB\n'
    '\tEXPORT\tl1\n'
    '\tds.b\t32\n'
    'l1\tdc.w\t$1234\n'
    '\tENDP\n'
    '\tEND\n'
)

# Same-case self-satisfying import (the Tool032 NotImp guard): must NOT flag.
SRC_SELF = (
    'M\tPROC\n'
    '\tEXPORT\tM\n'
    '\tIMPORT\tNotImp\n'
    '\tdc.l\tNotImp\n'
    '\tENDP\n'
    'NotImp\tPROC\n'
    '\trts\n'
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


def test_case_shadow_flagged_positive():
    with tempfile.TemporaryDirectory() as tmp:
        _, a = _asm(tmp, 'a.asm', SRC_A)
        assert 'L1' in a._import_case_shadow, a._import_case_shadow


def test_same_case_import_not_flagged():
    with tempfile.TemporaryDirectory() as tmp:
        _, a = _asm(tmp, 'm.asm', SRC_SELF)
        assert a._fold('NotImp') not in a._import_case_shadow


def test_link_binds_external_export_not_local():
    with tempfile.TemporaryDirectory() as tmp:
        oa = _asm(tmp, 'a.asm', SRC_A)
        ob = _asm(tmp, 'b.asm', SRC_B)
        linked = linkiigs.link([oa, ob], opts={'merge': True})
        img = b''.join(r[2] for seg in omf.iter_segments(linked)
                       for r in seg['recs'] if r[1] in ('CONST', 'LCONST'))
        # A's `dc.l l1` is the first 4 bytes of the merged image. A is placed at
        # base 0; A's own body is 1(nop after dc.l is at 4)+... . B follows A, so
        # B's `l1` (at B-offset 32) sits at an address >= len(A body). A's local
        # `L1` is at A-offset 5. The fix must store B's l1 address, not 0x000005.
        stored = int.from_bytes(img[0:4], 'little')
        assert stored != 0x000005, 'dc.l l1 wrongly bound A local L1 (0x05)'
        assert stored >= len(oa[0]) or stored > 0x20, f'stored {stored:#x}'


if __name__ == '__main__':
    test_case_shadow_flagged_positive()
    test_same_case_import_not_flagged()
    test_link_binds_external_export_not_local()
    print('ok')
