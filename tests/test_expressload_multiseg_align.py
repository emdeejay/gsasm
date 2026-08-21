"""Corpus-free PIN for contract divergence D9 — ALIGN gap filling on the
MULTI-SEGMENT ExpressLoad path (`docs/CONTRACT_EXPRESSLOAD_RELOC.md` D9).

`linkiigs._place` rounds a segment's placed base up to its header ALIGN
(`PROC align N`).  Both output paths then resolve each segment's body at that
ROUNDED base — Path B via `adj_seg_base = seg_base - group_base` — so the
merge that concatenates a group's bodies must reinstate the rounding gap or
the image's byte offsets stop agreeing with the addresses its own EXPRs (and
its own relocation records) were resolved against.

Path A always did this: it merges with `linkiigs._merge_bodies`, which
zero-fills exactly those gaps.  Path B merged with a bare `b''.join` until
0.6.0.  Nothing in the golden corpus exercised it — no multi-segment group
has an aligned second-or-later segment, measured across a full `--full` gate
— so the divergence was [UNFORCED] and latent, not wrong bytes.

The shape below is the smallest thing that trips it: one object with two
PROCs, the second `align 16` after a 3-byte first, referenced by a `dc.w` in
its own segment.  Before the fix the group image was 6 bytes
(`11 22 33 aa 10 00`) while `here` stored `$0010` and the SUPER record named
offset 17 — both past the end of a 6-byte image.  After it the image is 19
bytes with 13 zero fill, `here` really is at offset 16, and the record lands
inside the image.

Run either as:
    python3 -m pytest tests/test_expressload_multiseg_align.py
    python3 tests/test_expressload_multiseg_align.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from gsasm import asm, omf, linkiigs                # noqa: E402
from gsasm import expressload as E                  # noqa: E402

# Object A: a 3-byte segment followed by an `align 16` segment whose own
# `dc.w here` names a label in the aligned segment.  Both segments land in
# output GROUP 0 (multiseg groups per input OBJECT by default).
SRC_A = (
    'First\tPROC\n'
    '\tdc.b\t$11,$22,$33\n'
    '\tENDP\n'
    'Second\tPROC\talign 16\n'
    'here\tdc.b\t$aa\n'
    '\tdc.w\there\n'
    '\tENDP\n'
    '\tEND\n'
)
# A second object, because multiseg output needs more than one.
SRC_B = 'Other\tPROC\n\trts\n\tENDP\n\tEND\n'

_ALIGN = 16
_FIRST_LEN = 3                       # dc.b $11,$22,$33
_HERE_OFF = _ALIGN                   # where `here` MUST live in the image
_EXPECTED = (bytes.fromhex('112233')
             + bytes(_ALIGN - _FIRST_LEN)
             + bytes.fromhex('aa1000'))


def _objects():
    out = []
    with tempfile.TemporaryDirectory() as tmp:
        for name, src in (('a.aii', SRC_A), ('b.aii', SRC_B)):
            path = os.path.join(tmp, name)
            with open(path, 'w') as fh:
                fh.write(src)
            a = asm.assemble(path, [tmp])
            assert not a.errors, (name, a.errors[:2])
            out.append((omf.emit(a), a))
    return out


def _segments(blob):
    return {seg['hdr']['SEGNAME']: seg for seg in omf.iter_segments(blob)}


def _image(seg):
    return b''.join(d for _at, nm, d in seg['recs'] if nm in ('CONST', 'LCONST'))


def test_place_really_rounds_the_second_segment_up():
    """Precondition: without the rounding there is nothing to fill."""
    placed, _bases, _pidx = linkiigs._place(_objects(), 0)
    bases = {hdr['SEGNAME']: base for _n, _recs, base, hdr, _asm in placed}
    assert bases[b'FIRST'] == 0, bases
    assert bases[b'SECOND'] == _ALIGN, (
        f'_place did not round SECOND up to {_ALIGN}: {bases} — the `PROC '
        'align N` rounding this test exists to follow is gone')


def test_multiseg_group_image_reinstates_the_align_gap():
    """D9: the group image must zero-fill the ALIGN rounding gap.

    Path A has always done this (`linkiigs._merge_bodies`); Path B used a
    bare `b''.join(group_bodies)` while still resolving each body at the
    ROUNDED base.
    """
    multi = _segments(E.expressload(_objects(), opts={'multiseg': True}))
    assert b'FIRST' in multi, sorted(multi)
    img = _image(multi[b'FIRST'])
    assert img == _EXPECTED, (
        f'multiseg group image {img.hex()} != {_EXPECTED.hex()}; a '
        f'{len(img)}-byte image means the ALIGN gap was not filled — the '
        'bodies were resolved at the rounded base but concatenated without '
        'it (docs/CONTRACT_EXPRESSLOAD_RELOC.md D9)')
    assert img[_HERE_OFF] == 0xAA, (
        f'`here` is stored as {_HERE_OFF:#x} but image[{_HERE_OFF:#x}] is '
        f'{img[_HERE_OFF]:#04x}, not the 0xaa byte it labels')


def test_multiseg_align_gap_matches_the_single_path():
    """The same two segments merged single-segment agree byte-for-byte.

    Path A's `_merge_bodies` is the reference; D9 was only ever about Path B
    not calling it.  (Single-segment output places both objects at joint
    bases, so compare only the aligned prefix this test is about.)
    """
    single = _segments(E.expressload(_objects(), opts={}))
    img = _image(single[b'main'])
    assert img.startswith(_EXPECTED), (
        f'single-segment image {img.hex()} does not start with '
        f'{_EXPECTED.hex()} — the reference merge itself changed')


def test_multiseg_reloc_offsets_land_inside_the_image():
    """Every relocation record must name an offset inside its own image.

    This is the failure the gap-fill prevents: the SUPER page list is built
    from group-relative offsets derived from the ROUNDED joint bases, so an
    unfilled gap puts the record past the end of the image the loader will
    patch.
    """
    multi = _segments(E.expressload(_objects(), opts={'multiseg': True}))
    seg = multi[b'FIRST']
    img_len = len(_image(seg))
    offsets = [o for lst in E.parse_super(seg['raw']).values() for o in lst]
    assert offsets, 'expected at least one SUPER-covered site in FIRST'
    for off in offsets:
        assert off < img_len, (
            f'SUPER record names offset {off:#x} in a {img_len:#x}-byte '
            'image — the ALIGN gap is missing (contract D9)')


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
