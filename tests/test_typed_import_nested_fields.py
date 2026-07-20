"""Regression guard for typed-import aliases through nested record fields.

Run either as:
    python3 -m pytest tests/test_typed_import_nested_fields.py
    python3 tests/test_typed_import_nested_fields.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from gsasm import asm, omf, linkiigs      # noqa: E402


SOURCE = (
    'Rect\tRECORD\t0\n'
    'top\tds.w\t1\n'
    'left\tds.w\t1\n'
    'bottom\tds.w\t1\n'
    'right\tds.w\t1\n'
    '\tENDR\n'
    'Param\tRECORD\t0\n'
    'pcount\tds.w\t1\n'
    'wPosition\tds\tRect\n'
    '\tENDR\n'
    '\tIMPORT\twin:Param\n'
    'UseIt\tPROC\n'
    '\tsta\twin.wPosition.top\n'
    '\tsta\twin.wPosition.bottom\n'
    '\trts\n'
    '\tENDP\n'
    '\tEND\n'
)


def _assemble():
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, 'nested.asm')
        with open(src, 'w') as fh:
            fh.write(SOURCE)
        a = asm.assemble(src, [tmp])
        assert not a.errors, a.errors
        return a, omf.emit(a)


def test_typed_import_aliases_nested_ds_fields():
    a, obj = _assemble()
    assert a.equ_alias['WIN.WPOSITION.TOP'] == ('WIN', 2)
    assert a.equ_alias['WIN.WPOSITION.BOTTOM'] == ('WIN', 6)

    linked = linkiigs.link(
        [(obj, a)],
        opts={'merge': True, 'extern': {'WIN': 0x00B5}, 'abs_extra': ['WIN']})
    img = b''.join(r[2] for seg in omf.iter_segments(linked)
                    for r in seg['recs'] if r[1] in ('CONST', 'LCONST'))
    assert img == bytes.fromhex('8d b7 00 8d bb 00 60')


if __name__ == '__main__':
    test_typed_import_aliases_nested_ds_fields()
    print('ok')
