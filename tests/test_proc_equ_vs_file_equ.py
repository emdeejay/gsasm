"""Regression guard for proc-local stack EQUs reusing file-scope EQUs.

Run either as:
    python3 -m pytest tests/test_proc_equ_vs_file_equ.py
    python3 tests/test_proc_equ_vs_file_equ.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from gsasm import asm        # noqa: E402


SOURCE = (
    'handle\tequ\t$CA\n'
    'ptr\tequ\thandle+4\n'
    'Handle\tequ\t4\n'
    'Ptr\tequ\t4\n'
    'Frame\tPROC\n'
    'Handle\tequ\t4\n'
    'Ptr\tequ\tHandle+2\n'
    '\tlda\t<Handle\n'
    '\tlda\t<Ptr\n'
    '\trts\n'
    '\tENDP\n'
    'UseDP\tPROC\n'
    '\tlda\t<handle\n'
    '\tlda\t<ptr\n'
    '\trts\n'
    '\tENDP\n'
    '\tEND\n'
)


def _assemble():
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, 'proc-file-equ.asm')
        with open(src, 'w') as fh:
            fh.write(SOURCE)
        a = asm.assemble(src, [tmp], case_equ_variants={'HANDLE', 'PTR'})
        assert not a.errors, a.errors
        return a


def _segment_bytes(a, name):
    seg = next(s for s in a.segs if (s.name or '').upper() == name.upper())
    return b''.join(it[2] for it in seg.items if it[0] == 'code')


def test_proc_equ_does_not_clobber_file_scope_equ():
    a = _assemble()
    assert _segment_bytes(a, 'Frame') == bytes.fromhex('a5 04 a5 06 60')
    assert _segment_bytes(a, 'UseDP') == bytes.fromhex('a5 ca a5 ce 60')


if __name__ == '__main__':
    test_proc_equ_does_not_clobber_file_scope_equ()
    print('ok')
