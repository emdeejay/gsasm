"""Regression guard for WITH lookup over qualified nested fields.

Run either as:
    python3 -m pytest tests/test_with_qualified_field.py
    python3 tests/test_with_qualified_field.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from gsasm import asm        # noqa: E402


SOURCE = (
    'Rect\tRECORD\t0\n'
    'top\tds.w\t1\n'
    'left\tds.w\t1\n'
    'bottom\tds.w\t1\n'
    'right\tds.w\t1\n'
    '\tENDR\n'
    'Cust\tRECORD\t0\n'
    'prefix\tds.b\t8\n'
    'ctlRect\tds\tRect\n'
    '\tENDR\n'
    'UseIt\tPROC\n'
    '\tWITH\tCust\n'
    '\tldy\t#ctlRect.top\n'
    '\tldy\t#Rect.top\n'
    '\tENDWITH\n'
    '\trts\n'
    '\tENDP\n'
    '\tEND\n'
)


def _assemble():
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, 'with-qualified.asm')
        with open(src, 'w') as fh:
            fh.write(SOURCE)
        a = asm.assemble(src, [tmp])
        assert not a.errors, a.errors
        return a


def test_with_prefixes_undefined_dotted_field_names():
    a = _assemble()
    seg = next(s for s in a.segs if (s.name or '').upper() == 'USEIT')
    code = b''.join(it[2] for it in seg.items if it[0] == 'code')
    assert code == bytes.fromhex('a0 08 00 a0 00 00 60')


if __name__ == '__main__':
    test_with_prefixes_undefined_dotted_field_names()
    print('ok')
