"""Corpus-free guard for the single-segment ExpressLoad reloc scan's
absolute-target drop (First-Disks phase — Tool035/synthLAB, Disk 6).

A relocatable expression whose TARGET resolves to an absolute address OUTSIDE
the merged load segment gets NO relocation record: gold emits none for a site
that binds to an exported absolute EQU (MIDISynth's ``XSHIFTOUT equ $E01E8C`` /
``XSHIFTSTAY equ $E01E84``, reached by cursor.asm's ``jsl xShiftOut`` — the two
spurious SUPER type-1 records that made Tool035 4 bytes long before this).

``gsasm/expressload.py::_scan_relocs`` mirrors the multi-segment path's
``_group_of(target) is None`` rule, but ONLY when the single-segment caller
supplies the symbol table + merged length — the multi-seg caller passes
neither, so its behavior is unchanged (asserted below).

Run either as:
    python3 -m pytest tests/test_expressload_absolute_target.py
    python3 tests/test_expressload_absolute_target.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from gsasm import expressload as E                  # noqa: E402

# One placed segment with two size-3 (jsl) relocations:
#   offset 0 -> LOCAL, an in-segment label (addr 0x100)   -> SUPER type 1
#   offset 6 -> XABS,  an absolute EQU (0xE01E8C, off-seg) -> DROPPED
_RECS = [
    ('', 'LEXPR', (3, [('sym', 'LOCAL'), 'end'])),
    ('', 'LCONST', b'\x00\x00\x00'),
    ('', 'LEXPR', (3, [('sym', 'XABS'), 'end'])),
    ('', 'END', None),
]
_PLACED = [('main', _RECS, 0, {}, None)]
_SYMS = [{'LOCAL': 0x100, 'XABS': 0xE01E8C}]
_BODY_LEN = 0x8000                                   # LOCAL in range, XABS out


def test_single_seg_drops_absolute_target():
    relocs = E._scan_relocs(_PLACED, E._ALL_SUPER_CLASSES, _SYMS, _BODY_LEN)
    # (3, 0) -> SUPER type 1; only the in-segment LOCAL site survives.
    assert relocs == {1: [0]}, relocs


def test_multiseg_path_unchanged():
    # No symbol table -> no drop: BOTH sites ride the SUPER record, exactly as
    # before (the multi-seg caller relies on its own _group_of gate instead).
    relocs = E._scan_relocs(_PLACED)
    assert relocs == {1: [0, 6]}, relocs


def test_segment_end_label_kept():
    # The upper bound is INCLUSIVE: a label at exactly body_len is the
    # segment-end marker, a valid relocatable target — NOT dropped.  (A
    # half-open bound wrongly dropped unflagged end-of-segment references,
    # regressing the case-B corpus test.)  XABS ($E01E8C) is far beyond and
    # still drops.
    syms = [{'LOCAL': _BODY_LEN, 'XABS': 0xE01E8C}]
    relocs = E._scan_relocs(_PLACED, E._ALL_SUPER_CLASSES, syms, _BODY_LEN)
    assert relocs == {1: [0]}, relocs


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
