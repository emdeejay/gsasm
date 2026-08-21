"""Corpus-free PIN for the single/multi-segment ExpressLoad reloc divergence.

The contract this guards is `docs/CONTRACT_EXPRESSLOAD_RELOC.md`; read §4 D1
and D3 before changing anything here.  In one sentence: the two output paths
answer *different questions* about a relocation site, and the mechanism that
makes each correct is fatal to the other.

  * `_build_single_output_seg` (Path A) emits ONE load segment, so its code
    image is final the moment it is built.  An EXPORT-EQU reference is a
    link-time constant, and the path suppresses its record AT SCAN TIME via the
    symbol KIND table (`_needs_reloc(ops, kinds)`), while resolving the site's
    `>>16` const shift separately, at body-build time, via `_defer_shifts`'
    `abs_syms`.
        Forcing artifact: the SCSI driver family's small `equ` constants
        (docs/SCSI_RELOC_DIAGNOSIS_2026-08-01.md, commit 9d82fba) and
        SCSI.Manager body 0xe5d, `dc.w work_vars_size>>16` (commit 4243c03).

  * `_build_multiseg_output` (Path B) emits N load segments and rewrites its
    code image WHILE classifying, so a dropped record and a finalised image
    byte are the same act.  It scans KIND-BLIND on purpose and drops the record
    LATE, in the `stype == 27` / `_group_of(target) is None` branch — which is
    also the ONLY place that bakes the deferred `#^AbsEqu` high word.
        Forbidding artifact: threading the same kind table into Path B's scan
        was tried first, in 9d82fba, and regressed TS2
        (/System.Disk/System/System.Setup/TS2) at body offset 0x88a: the record
        vanished, the bake never ran, and the image kept the unshifted low word.

Both regression shapes were reproduced by monkeypatch while writing the
contract, and both revert the pinned image word from `fe 00` to `ef 01`.  The
assertions below therefore fail BY NAME if either path's mechanism is removed
or if the two are collapsed into one.

What this does NOT pin: a SIMULTANEOUS collapse (kinds threaded into Path B's
scan AND `abs_syms` passed to Path B's `_defer_shifts`) leaves these bytes
correct, because for an ABSOLUTE equate the two mechanisms agree numerically.
That combination is a Path B targeting change and must be gated against
TS2/TS3, not against this test.

Run either as:
    python3 -m pytest tests/test_expressload_path_divergence.py
    python3 tests/test_expressload_path_divergence.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from gsasm import asm, omf, linkiigs                # noqa: E402
from gsasm import expressload as E                  # noqa: E402

# Object A exports an ABSOLUTE equate — outside any load segment's span, so
# multiseg's `_group_of` returns None for it (TS2's `UserDummyTable equ
# $FE01EF` shape) and single-seg's kind table calls it 'equ'.
SRC_A = (
    '\tEXPORT\tabs_thing\n'
    'abs_thing\tequ\t$FE01EF\n'
    'Aseg\tPROC\n'
    '\trts\n'
    '\tENDP\n'
    '\tEND\n'
)

# Object B references it twice: a bank-word `#^` immediate (OMF (2,16) ->
# SUPER type 27, the deferred-shift site) and a plain low-word `#` immediate
# (OMF (2,0) -> SUPER type 0).
SRC_B = (
    '\tIMPORT\tabs_thing\n'
    'Bseg\tPROC\n'
    '\tlda\t#^abs_thing\n'
    '\tlda\t#abs_thing\n'
    '\trts\n'
    '\tENDP\n'
    '\tEND\n'
)

# The bytes the loader must never be asked to patch: `a9 fe 00` is
# `lda #$00FE`, the RESOLVED high word of $FE01EF; `a9 ef 01` is
# `lda #$01EF`, the absolute's low word.  Together with the trailing `60`
# (rts) this is Bseg's whole image.
_BSEG_IMAGE = bytes.fromhex('a9fe00a9ef0160')
_UNRESOLVED_HIGH_WORD = bytes.fromhex('a9ef01')     # the D1/D3 regression shape


def _objects():
    out = []
    with tempfile.TemporaryDirectory() as tmp:
        for name, src in (('a.aii', SRC_A), ('b.aii', SRC_B)):
            p = os.path.join(tmp, name)
            with open(p, 'w') as fh:
                fh.write(src)
            a = asm.assemble(p, [tmp])
            assert not a.errors, (name, a.errors[:2])
            out.append((omf.emit(a), a))
    return out


def _placed_and_kinds(objects):
    """Reproduce expressload()'s shared prologue plus Path A's kind overlay."""
    placed, bases, pidx = linkiigs._place(objects, 0)
    sym, obj_globals = linkiigs._build_symtab(objects, placed, bases, pidx)
    sym_kinds = getattr(sym, 'kinds', {})
    body_kinds = []
    for placed_i in range(len(placed)):
        og = obj_globals[pidx[placed_i]]
        body_kinds.append(sym_kinds if not og
                          else {**sym_kinds, **getattr(og, 'kinds', {})})
    return placed, sym, body_kinds


def _segments(blob):
    return {seg['hdr']['SEGNAME']: seg for seg in omf.iter_segments(blob)}


def _image(seg):
    return b''.join(d for _at, nm, d in seg['recs'] if nm in ('CONST', 'LCONST'))


def _reloc_record_ops(seg):
    """OMF opcodes of every non-image record in *seg* (SUPER/RELOC/cRELOC/...)."""
    return [nm for _at, nm, _d in seg['recs']
            if nm not in ('CONST', 'LCONST', 'END')]


def test_scan_relocs_diverges_on_the_kind_table():
    """THE PIN: the two paths' scan calls must NOT agree.

    Path A passes `body_kinds`; Path B passes nothing.  If a future change
    makes `_scan_relocs` kind-aware unconditionally (or makes the kind table
    inert), these two calls collapse into one and the assertion below names the
    divergence that was lost.
    """
    objects = _objects()
    placed, _sym, body_kinds = _placed_and_kinds(objects)

    # Path B's call shape: kind-BLIND.  The absolute-equate sites survive the
    # scan (they are dropped later by `_group_of(...) is None`, which is also
    # where the image bake happens).
    blind = E._scan_relocs(placed)
    blind_offsets = sorted(o for lst in blind.values() for o in lst)
    assert blind_offsets, (
        'multiseg scan shape (no kind table) produced no reloc sites — the '
        'kind-blind half of the divergence is gone; see '
        'docs/CONTRACT_EXPRESSLOAD_RELOC.md D1')
    assert 27 in blind, (
        f'expected a SUPER type-27 (bank-word) site, got {sorted(blind)}')

    # Path A's call shape: kind-AWARE.  The same sites are suppressed here.
    body_len = sum(len(_bd) for _bd in
                   [linkiigs._omf._build_body(recs, {}, 0)
                    for _sn, recs, _b, _h, _a in placed]) or 0x10000
    aware = E._scan_relocs(placed, body_syms=[{} for _ in placed],
                           body_len=body_len, body_kinds=body_kinds)
    aware_offsets = sorted(o for lst in aware.values() for o in lst)
    assert not aware_offsets, (
        f'single-seg scan shape (kind table) still reports {aware_offsets} — '
        'the KIND suppression that closed the SCSI family is gone; see '
        'docs/CONTRACT_EXPRESSLOAD_RELOC.md D1')


def test_both_paths_bake_the_absolute_high_word():
    """Both paths must finalise the `#^AbsEqu` site to its resolved high word.

    Path A gets there via `_defer_shifts(recs, equ_names)` (const-shift
    resolution at body-build time, SCSI.Manager 0xe5d).  Path B gets there via
    the `stype == 27` / `_group_of is None` image bake (TS2).  A regression in
    EITHER mechanism leaves `a9 ef 01` — the unshifted low word — in the image.
    """
    single = _segments(E.expressload(_objects(), opts={}))
    multi = _segments(E.expressload(_objects(), opts={'multiseg': True}))

    assert b'main' in single, sorted(single)
    assert b'BSEG' in multi and b'ASEG' in multi, sorted(multi)

    single_img = _image(single[b'main'])
    multi_img = _image(multi[b'BSEG'])

    assert single_img.endswith(_BSEG_IMAGE), (
        f'single-segment image {single_img.hex()} does not end with the '
        f'baked {_BSEG_IMAGE.hex()}; if it contains '
        f'{_UNRESOLVED_HIGH_WORD.hex()} the const-shift resolution '
        "(_defer_shifts' equ_names) was lost — SCSI.Manager 0xe5d, "
        'docs/CONTRACT_EXPRESSLOAD_RELOC.md D3')
    assert multi_img == _BSEG_IMAGE, (
        f'multi-segment BSEG image {multi_img.hex()} != {_BSEG_IMAGE.hex()}; '
        f'if it contains {_UNRESOLVED_HIGH_WORD.hex()} the stype-27 '
        '_group_of-is-None bake was starved (almost certainly by kind-'
        'suppressing the site at scan level) — TS2 0x88a, '
        'docs/CONTRACT_EXPRESSLOAD_RELOC.md D1')


def test_neither_path_emits_a_record_for_the_absolute_sites():
    """An absolute equate reference gets NO relocation record, on either path.

    This is the property the two mechanisms agree on; D1/D3 are only about
    HOW each one reaches it.
    """
    single = _segments(E.expressload(_objects(), opts={}))
    multi = _segments(E.expressload(_objects(), opts={'multiseg': True}))
    for label, seg in (('single main', single[b'main']),
                       ('multiseg BSEG', multi[b'BSEG'])):
        recs = _reloc_record_ops(seg)
        assert not recs, (
            f'{label} emitted {recs} for absolute-equate references; gold '
            'emits none (TS2 UserDummyTable / MIDISynth XSHIFTOUT shape)')


def test_single_path_super_type_27_is_25_plus_segnum_2():
    """Path A's whole SUPER vocabulary is {0, 1, 27}, and 27 == 25 + 2.

    Grounded in the Loader's own dispatch (GS.OS/Loader/Relocation.a Do_SUPER:
    "n is 25-36 ... Segment Number = n-24 (type-25) ... Shift Count = -16"),
    and in `_make_output_seg(..., 2, ...)` — a single-segment ExpressLoad
    file's one load segment is always OMF SEGNUM 2.  If a future change makes
    Path A emit a `13+n`/`25+n` subtype for n != 2, it has grown a targeting
    rule it has no way to express (contract §2, §5 rule (b)).
    """
    assert set(E._SUPER_TYPE.values()) == {0, 1, 27}, E._SUPER_TYPE
    assert E._SUPER_TYPE[(2, 16)] == 25 + 2
    # A relocatable (non-equ) reference in a single-segment build must land in
    # exactly those subtypes.
    src = (
        'Cseg\tPROC\n'
        'here\tdc.w\t0\n'
        '\tlda\t#^here\n'
        '\tlda\t#here\n'
        '\tdc.l\there\n'
        '\trts\n'
        '\tENDP\n'
        '\tEND\n'
    )
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, 'c.aii')
        with open(p, 'w') as fh:
            fh.write(src)
        a = asm.assemble(p, [tmp])
        assert not a.errors, a.errors[:2]
    blob = E.expressload([(omf.emit(a), a)], opts={})
    types = set(_super_types_of(blob))
    assert types <= {0, 1, 27}, f'single path emitted SUPER types {sorted(types)}'
    assert 27 in types, f'expected the bank-word class, got {sorted(types)}'


def _super_types_of(blob):
    """SUPER subtypes present in every segment of a whole ExpressLoad file."""
    out = []
    off = 0
    while off < len(blob):
        bytecnt = int.from_bytes(blob[off:off + 4], 'little')
        if not bytecnt:
            break
        out.extend(E.parse_super(blob[off:off + bytecnt]))
        off += bytecnt
    return out


_TESTS = [(n, f) for n, f in sorted(globals().items())
          if n.startswith('test_') and callable(f)]

if __name__ == '__main__':
    failed = 0
    for name, fn in _TESTS:
        try:
            fn()
        except AssertionError as exc:
            print(f'FAIL {name}: {exc}')
            failed += 1
        else:
            print(f'pass {name}')
    print(f'{len(_TESTS) - failed}/{len(_TESTS)} passed')
    sys.exit(1 if failed else 0)
