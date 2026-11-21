"""gslink multi-object (MPW LinkIIgs-style) CLI — gsasm/linkcli.py.

Corpus-free: synthetic two-source links exercise the three CLI shapes
(ungrouped merge, -lseg multiseg, -lseg:Dynamic with the auto-allocated
~JumpTable) plus the mode sniffer, and a strict-mode guard proves the
``jt_entries`` refactor in expressload.py kept the gate-proven callers'
missing-entry ValueError intact.

Run either as:
    python3 -m pytest tests/test_linkcli.py
    python3 tests/test_linkcli.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from gsasm import linkcli, omf                       # noqa: E402
from gsasm import expressload as E                   # noqa: E402


_MAIN_SRC = """\
Main\tPROC
\tEXPORT\tMain
\tIMPORT\tFarRtn
\tjsl\tFarRtn
\trts
\tENDP
\tEND
"""

_PREP_SRC = """\
FarRtn\tPROC
\tEXPORT\tFarRtn
\tlda\t#$0001
\trtl
\tENDP
\tEND
"""

_SUB_SRC = """\
Sub\tPROC
\tEXPORT\tSub
\trtl
\tENDP
\tEND
"""

_TOP_SRC = """\
Top\tPROC
\tEXPORT\tTop
\tIMPORT\tSub
\tjsl\tSub
\trts
\tENDP
\tEND
"""


def _write(d, name, text):
    p = os.path.join(d, name)
    with open(p, 'w') as fh:
        fh.write(text)
    return p


def test_wants_mpw_mode():
    f = linkcli.wants_mpw_mode
    assert not f(['x.obj'])
    assert not f(['x.obj', '-o', 'y'])
    assert not f(['-o', 'y', 'x.obj'])
    assert f(['a.obj', 'b.obj'])
    assert f(['-x', 'a.obj'])
    assert f(['-lseg', 'MAIN', 'a.obj', '-o', 'out'])
    assert f(['-lseg:Dynamic', 'P', 'a.obj', '-o', 'out'])


def test_ungrouped_merge():
    with tempfile.TemporaryDirectory() as d:
        top = _write(d, 'top.asm', _TOP_SRC)
        sub = _write(d, 'sub.asm', _SUB_SRC)
        spec = linkcli.parse([top, sub, '-o', os.path.join(d, 'out')])
        load = linkcli.build(spec)
    segs = list(omf.iter_segments(load, records=False))
    assert len(segs) == 1, [s['name'] for s in segs]
    # jsl Sub resolved across objects: 0x22 + Sub's absolute offset (top's
    # body is jsl(4) + rts(1) = 5 bytes, so Sub lands at 5).
    assert b'\x22\x05\x00\x00' in segs[0]['raw']


def test_grouped_dynamic_auto_jumptable():
    with tempfile.TemporaryDirectory() as d:
        main = _write(d, 'main.asm', _MAIN_SRC)
        prep = _write(d, 'prep.asm', _PREP_SRC)
        spec = linkcli.parse(['-lseg', 'MAIN', main,
                              '-lseg:Dynamic', 'PREP', prep,
                              '-o', os.path.join(d, 'out'),
                              '-t', '$BB', '-at', '$0001'])
        load = linkcli.build(spec)
    segs = list(omf.iter_segments(load, records=False))
    names = [s['name'] for s in segs]
    # Golden file layout: directory, non-dynamic block, ~JumpTable, dynamic.
    assert names == ['~ExpressLoad', 'MAIN', '~JumpTable', 'PREP'], names
    kinds = {s['name']: s['hdr']['KIND'] for s in segs}
    assert kinds['PREP'] & 0x8000, kinds
    assert kinds['~JumpTable'] & 0xFF == 0x02, kinds
    # One dynamic routine referenced once -> one auto-allocated entry for
    # (PREP's file segnum 4, routine offset 0).
    jt = next(s for s in segs if s['name'] == '~JumpTable')
    assert jt['hdr']['LENGTH'] == len(E.encode_jumptable([(4, 0)]))
    assert E.encode_jumptable([(4, 0)]) in jt['raw']


def test_dynamic_group_rejects_obj_inputs():
    with tempfile.TemporaryDirectory() as d:
        obj = os.path.join(d, 'x.obj')
        with open(obj, 'wb') as fh:
            fh.write(b'\x00')
        spec = linkcli.parse(['-lseg', 'MAIN', obj,
                              '-lseg:Dynamic', 'P', obj,
                              '-o', os.path.join(d, 'out')])
        try:
            linkcli.build(spec)
        except SystemExit as e:
            assert 'SOURCE files' in str(e)
        else:
            raise AssertionError('expected LinkCliError')


_TWO_PROCS = """\
KeepMe\tPROC
\tEXPORT\tKeepMe
\tlda\t#$0001
\trtl
\tENDP
DropMe\tPROC
\tEXPORT\tDropMe
\tlda\t#$0002
\trtl
\tENDP
\tEND
"""


def test_segment_selector():
    with tempfile.TemporaryDirectory() as d:
        src = _write(d, 'two.asm', _TWO_PROCS)
        out = os.path.join(d, 'out')
        # Select only KeepMe; DropMe's bytes must not appear.
        spec = linkcli.parse([f'{src}(KeepMe)', '-o', out])
        load = linkcli.build(spec)
        segs = list(omf.iter_segments(load, records=False))
        assert len(segs) == 1
        assert b'\xa9\x01\x00' in segs[0]['raw']        # lda #$0001
        assert b'\xa9\x02\x00' not in segs[0]['raw']    # DropMe excluded
        # Selector naming a missing segment errors clearly.
        spec = linkcli.parse([f'{src}(NoSuch)', '-o', out])
        try:
            linkcli.build(spec)
        except SystemExit as e:
            assert 'NoSuch' in str(e)
        else:
            raise AssertionError('expected error for unknown segment')


def test_strict_jt_entries_still_raises():
    """The jt_lookup refactor must keep strict mode: a caller-supplied
    jt_entries list with a missing key raises exactly as before."""
    from gsasm import asm as _asm, omf as _omf
    with tempfile.TemporaryDirectory() as d:
        main = _write(d, 'main.asm', _MAIN_SRC)
        prep = _write(d, 'prep.asm', _PREP_SRC)
        objs = []
        for p in (main, prep):
            a = _asm.assemble(p, [d])
            assert not a.errors, a.errors
            objs.append((_omf.emit(a), a))
    opts = {'multiseg': True, 'obj_group': [0, 1],
            'segnames': [b'MAIN', b'PREP'], 'segkinds': [0x0000, 0x8000],
            'jt_entries': []}
    try:
        E.expressload(objs, opts)
    except ValueError as e:
        assert 'has no entry' in str(e), e
    else:
        raise AssertionError('expected ValueError for missing jt entry')
    # And 'auto' succeeds on the same objects.
    opts['jt_entries'] = 'auto'
    load = E.expressload(objs, opts)
    names = [s['name'] for s in omf.iter_segments(load, records=False)]
    assert '~JumpTable' in names, names


if __name__ == '__main__':
    for nm, fn in sorted(globals().items()):
        if nm.startswith('test_') and callable(fn):
            fn()
            print(f'{nm}: PASS')
