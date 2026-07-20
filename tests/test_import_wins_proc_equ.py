"""Regression guard for Finder icons.aii's deltay/deltax collision.

``import_wins`` is a whole-link hint: when a proc-local EQU reuses a declared
IMPORT name that another object EXPORTs, the EQU stays local to its own PROC and
the import remains visible to later PROCs in the same source file.

Run either as:
    python3 -m pytest tests/test_import_wins_proc_equ.py
    python3 tests/test_import_wins_proc_equ.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from gsasm import asm, omf, linkiigs      # noqa: E402


SOURCE = (
    '\tIMPORT\tdeltay,deltax\n'
    'dragRects\tPROC\n'
    'deltay\tequ\t7\n'
    'deltax\tequ\tdeltay+2\n'
    '\tlda\tdeltay\n'
    '\tlda\tdeltax\n'
    '\trts\n'
    '\tENDP\n'
    'windClick\tPROC\n'
    '\tsta\tdeltay\n'
    '\tsta\tdeltax\n'
    '\trts\n'
    '\tENDP\n'
    '\tEND\n'
)


def _assemble(import_wins=None):
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, 'icons-shape.asm')
        with open(src, 'w') as fh:
            fh.write(SOURCE)
        a = asm.assemble(src, [tmp], import_wins=import_wins)
        assert not a.errors, a.errors
        return a, omf.emit(a)


def _segment_bytes(a, name):
    for seg in a.segs:
        if (seg.name or '').upper() == name.upper():
            out = bytearray()
            for it in seg.items:
                if it[0] == 'code':
                    out += it[2]
                elif it[0] == 'ds':
                    out += b'\x00' * it[1]
            return bytes(out)
    raise AssertionError(f'missing segment {name}')


def _linked_image(obj, a):
    linked = linkiigs.link(
        [(obj, a)],
        opts={'merge': True,
              'extern': {'DELTAY': 0x1234, 'DELTAX': 0x5678},
              'abs_extra': ['DELTAY', 'DELTAX']})
    return b''.join(r[2] for seg in omf.iter_segments(linked)
                    for r in seg['recs'] if r[1] in ('CONST', 'LCONST'))


def test_default_proc_equ_still_clobbers_plain_import():
    a, _obj = _assemble()
    assert _segment_bytes(a, 'windClick') == bytes.fromhex('85 07 85 09 60')


def test_import_wins_keeps_equ_local_but_later_proc_import_absolute():
    a, obj = _assemble(import_wins={'deltay', 'deltax'})

    assert _segment_bytes(a, 'dragRects') == bytes.fromhex('a5 07 a5 09 60')
    assert _segment_bytes(a, 'windClick') == bytes.fromhex(
        '8d ff ff 8d ff ff 60')
    assert _linked_image(obj, a) == bytes.fromhex(
        'a5 07 a5 09 60 8d 34 12 8d 78 56 60')


if __name__ == '__main__':
    test_default_proc_equ_still_clobbers_plain_import()
    test_import_wins_keeps_equ_local_but_later_proc_import_absolute()
    print('ok')
