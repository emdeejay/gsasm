"""Corpus-free guard for expressload's `super_classes` option (MountImageGS
golden discovery, docs/REZ_TYPES_PLAN.md Finder-era sweeps).

The archived 30-Apr-93 LinkIIGS integrated ExpressLoad encoder folds ONLY
the (2, 0) low-word class into SUPER records: size-4 relocs and (2,16)
bank-byte relocs are standalone $F5 cRELOCs whose relOffset is the full
UNSHIFTED target.  The default (System Disk toolchain) supers every
`_SUPER_TYPE` class — pinned by the byte-exact EasyMount/tool/driver/FST
corpus, and re-checked here so the option can never leak into the default.

Run either as:
    python3 -m pytest tests/test_expressload_super_classes.py
    python3 tests/test_expressload_super_classes.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from gsasm import asm, omf                          # noqa: E402
from gsasm.expressload import (                     # noqa: E402
    expressload, SUPER_CLASSES_APR93, _ALL_SUPER_CLASSES)

# One PROC with a bank-byte ref, a low-word ref, and a size-4 pointer.
SOURCE = (
    'Single\tPROC\n'
    '\tlda\t#^Target\n'
    '\tlda\t#Target\n'
    '\trts\n'
    'Ptr\tdc.l\tTarget\n'
    'Target\tanop\n'
    '\tENDP\n'
    '\tEND\n'
)


def _build(opts):
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, 't.aii')
        with open(src, 'w') as fh:
            fh.write(SOURCE)
        a = asm.assemble(src, [tmp])
        assert not a.errors, a.errors[:2]
        return expressload([(omf.emit(a), a)], opts=opts)


def _record_kinds(data):
    """Crude scan: classify $F5 (size, shift-byte) and $F7 (super type)
    records anywhere in the image."""
    kinds = set()
    i, n = 0, len(data)
    while i < n - 7:
        if data[i] == 0xF5 and data[i + 1] in (1, 2, 3, 4):
            kinds.add(('F5', data[i + 1], data[i + 2]))
            i += 7
            continue
        if data[i] == 0xF7:
            total = int.from_bytes(data[i + 1:i + 5], 'little')
            if 0 < total < n and data[i + 5] < 64:
                kinds.add(('F7', data[i + 5]))
                i += 5 + total
                continue
        i += 1
    return kinds


def test_apr93_classes_standalone_all_but_low_word():
    kinds = _record_kinds(_build({'super_classes': SUPER_CLASSES_APR93}))
    assert ('F5', 4, 0) in kinds, kinds            # dc.l -> standalone
    assert ('F5', 2, 0xF0) in kinds, kinds         # bank byte -> standalone
    assert ('F7', 27) not in kinds and ('F7', 1) not in kinds, kinds


def test_default_supers_every_class():
    kinds = _record_kinds(_build(None))
    assert ('F5', 4, 0) not in kinds, kinds
    assert ('F5', 2, 0xF0) not in kinds, kinds


def test_multiseg_rejects_a_restricted_class_set():
    """Contract D8: the multi-segment path REFUSES `super_classes`.

    It cannot honour it: narrowing the set moves a `(size, shift)` class out
    of phase 7 (`_classify_super_relocs`) and into phase 5
    (`_emit_case_a_records`), and only phase 7's `stype == 27` /
    `_group_of is None` arm bakes the deferred `#^Const` high word (§3.1
    mutation 4).  Silently ignoring the caller's request — the pre-0.6.0
    behaviour — is the one option that is definitely wrong.
    """
    objs = _multiseg_objects()
    try:
        expressload(objs, opts={'multiseg': True,
                                'super_classes': SUPER_CLASSES_APR93})
    except ValueError as exc:
        assert 'super_classes' in str(exc), exc
        assert 'multi-segment' in str(exc), exc
    else:
        raise AssertionError(
            "multiseg build accepted opts['super_classes'] — it is either "
            'silently ignored again (contract D8) or newly honoured, and a '
            'newly honoured one needs a golden artifact behind it')

    # The full set is a no-op, not an error: it is what the path already does.
    assert expressload(objs, opts={'multiseg': True,
                                   'super_classes': _ALL_SUPER_CLASSES}) == \
        expressload(objs, opts={'multiseg': True})


def _multiseg_objects():
    """Two separately-assembled objects — the shape `multiseg` needs."""
    srcs = (
        ('m1.aii', 'One\tPROC\tEXPORT\n\trts\n\tENDP\n\tEND\n'),
        ('m2.aii', 'Two\tPROC\n\tlda\t#^One\n\tjsl\tOne\n\trts\n'
                   '\tENDP\n\tEND\n'),
    )
    out = []
    with tempfile.TemporaryDirectory() as tmp:
        for name, src in srcs:
            p = os.path.join(tmp, name)
            with open(p, 'w') as fh:
                fh.write(src)
            a = asm.assemble(p, [tmp])
            assert not a.errors, (name, a.errors[:2])
            out.append((omf.emit(a), a))
    return out


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
