"""Corpus-free guard for two ExpressLoad reloc-dictionary rules pinned by the
System 6.0.1 single-segment ExpressLoad files (E1: Start, QuickLogoff,
Tool038/MediaCtlTool).

1. NET-ZERO RELOCATION WEIGHT.  A same-segment label difference such as
   ``End - Start`` (both labels relocate by the same load bias, which cancels)
   is a link-time CONSTANT and must NOT get a load-time relocation record.
   ``_has_sym_ref`` alone was too coarse (it saw two symbols and emitted a
   SUPER reloc); Tool038's per-message length words ``EndMsg-Msg`` were the
   falsifying case (6 spurious SUPER type-0 relocs).  ``_reloc_weight`` /
   ``_needs_reloc`` model the expression's net segment-bias count: weight 0 =>
   no reloc, weight 1 => an ordinary reloc, unmodelled operator => stay
   conservative and keep the reloc.

2. NULL RELOC POINTER FOR A ZERO-RELOC SEGMENT.  The single-segment HET entry
   stores reloc_start = 0 when the segment has NO relocation dictionary (gold
   QuickLogoff), not code_start+length.  A reloc-bearing segment keeps
   code_start+length (every other single-segment tool, proven byte-exact).

Run either as:
    python3 -m pytest tests/test_expressload_reloc_weight.py
    python3 tests/test_expressload_reloc_weight.py
"""
import os
import struct
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from gsasm import asm, omf                              # noqa: E402
from gsasm.expressload import (                         # noqa: E402
    expressload, parse_super, _reloc_weight, _needs_reloc, _het_single_entry)


# --- expression op-lists (the shapes asm.py emits) -------------------------
_DIFF    = [('sym83', 'End'),    ('sym83', 'Start'), ('op', 2), 'end']  # A-B
_SINGLE  = [('sym83', 'Target'), 'end']                                 # A
_ADDEND  = [('sym83', 'Target'), ('lit', 2), ('op', 1), 'end']          # A+2
_SHIFTED = [('sym83', 'Target'), ('lit', 0xFFFFFFF0), ('op', 7), 'end']  # A>>16
_LITERAL = [('lit', 40), 'end']                                         # const
_UNKNOWN = [('sym83', 'A'), ('sym83', 'B'), ('op', 3), 'end']           # A*B


def test_reloc_weight_values():
    assert _reloc_weight(_DIFF) == 0           # same-seg difference cancels
    assert _reloc_weight(_SINGLE) == 1
    assert _reloc_weight(_ADDEND) == 1         # constant addend rides along
    assert _reloc_weight(_SHIFTED) == 1        # shift leaves value's weight
    assert _reloc_weight(_LITERAL) == 0
    assert _reloc_weight(_UNKNOWN) is None      # unmodelled operator -> None


def test_needs_reloc_predicate():
    assert not _needs_reloc(_DIFF)             # net-zero -> no reloc
    assert not _needs_reloc(_LITERAL)          # pure literal -> no reloc
    assert _needs_reloc(_SINGLE)
    assert _needs_reloc(_ADDEND)
    assert _needs_reloc(_SHIFTED)
    assert _needs_reloc(_UNKNOWN)              # conservative: still relocate


# One PROC: a same-segment difference word (must NOT relocate) followed by a
# real absolute reference (must relocate).
_SOURCE = (
    'Single\tPROC\n'
    'Start\tanop\n'
    '\tdc.w\tEnd-Start\n'   # offset 0-1: constant, NO reloc
    '\tlda\tTarget\n'       # offset 2 (opcode) + 3 (operand): needs reloc
    'Target\tanop\n'
    '\trts\n'
    'End\tanop\n'
    '\tENDP\n'
    '\tEND\n'
)


def test_same_segment_difference_not_relocated():
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, 't.aii')
        with open(src, 'w') as fh:
            fh.write(_SOURCE)
        a = asm.assemble(src, [tmp])
        assert not a.errors, a.errors[:2]
        img = expressload([(omf.emit(a), a)])
    seg = list(omf.iter_segments(img, records=False))[1]['raw']
    supers = parse_super(seg)
    # The ONLY relocation is the `lda Target` operand at offset 3; the
    # `dc.w End-Start` at offset 0 must be absent.
    assert supers.get(0) == [3], supers
    assert 0 not in supers.get(0, []), supers


def test_het_reloc_start_null_when_no_relocs():
    base = {'hdr': {'SEGNUM': 1, 'KIND': 0, 'DISPDATA': 59,
                    'DISPNAME': 44, 'ALIGN': 0},
            'body': b'\x00' * 100}
    no_reloc = _het_single_entry({**base, 'reloc_size': 0}, 152)
    assert struct.unpack_from('<I', no_reloc, 18)[0] == 0
    with_reloc = _het_single_entry({**base, 'reloc_size': 8}, 152)
    # code_start = 152 + 59 + 5 = 216; + length(100) = 316
    assert struct.unpack_from('<I', with_reloc, 18)[0] == 316


_TESTS = [(n, f) for n, f in sorted(globals().items())
          if n.startswith('test_') and callable(f)]

if __name__ == '__main__':
    failed = 0
    for name, fn in _TESTS:
        try:
            fn()
        except AssertionError as exc:
            failed += 1
            print(f'FAIL {name}: {exc}')
        else:
            print(f'ok   {name}')
    print(f'{len(_TESTS) - failed}/{len(_TESTS)} passed')
    sys.exit(1 if failed else 0)
