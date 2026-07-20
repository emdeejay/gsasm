"""Corpus-free guards for three gsasm/expressload.py behaviors added for the
Finder DATA-fork build (docs/EXPRESSLOAD_FINDER_PLAN.md B.0/B.1/B.1a/B.3):

1. Injection opts (``opts['seg_images']`` / ``opts['reloc_dicts']``) are
   INERT when unset — the tool-safety contract (plan item 9): every existing
   caller that never passes these keys (i.e. every tool/driver/FST build)
   must see byte-identical output whether the keys are simply absent or
   present-but-``None``.
2. ``opts['loadfile_name']`` threads the load file's own name into the
   ``~ExpressLoad`` directory segment's LOADNAME field, header[44:54],
   space-padded to 10 bytes (plan item 7).  Absent — the field stays
   ``b'\\x00' * 10``.
3. ``_scan_case_b``'s size-4 (shift-0) discriminator: a ``dc.l`` target only
   becomes a standalone case-B RELOC when its value is a genuine
   0x80000000/0xC0000000-family flag (bit 31 set, bits 24-29 clear) — NOT
   the ``Label-1``/``Label-2`` dispatch-table idiom, which (when the target
   resolves near address 0) evaluates to 0xFFFFFFFF/0xFFFFFFFE — bit 31 set
   too, but with bits 24-29 also all set, so it must stay an ordinary
   SUPER-eligible reloc (plan item, INFO's off=0xb3 case, B.1a).

No golden/disk material is read anywhere in this file — every fixture is an
ORIGINAL, hand-authored source assembled in a tempdir, matching the style of
tests/test_expressload_super_classes.py and tests/test_expressload_case_b.py.

Run either as:
    python3 -m pytest tests/test_expressload_finder.py
    python3 tests/test_expressload_finder.py
"""
import os
import struct
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from gsasm import asm, omf                     # noqa: E402
from gsasm.expressload import expressload      # noqa: E402


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _assemble(src, fname):
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, fname)
        with open(path, 'w') as fh:
            fh.write(src)
        a = asm.assemble(path, [d])
        assert not a.errors, a.errors
        return omf.emit(a), a


def _find_segment(out, name):
    """Return the raw bytes of the OMF segment named *name* in *out* (an
    ExpressLoad file produced by ``expressload()``), or raise."""
    for seg in omf.iter_segments(out, records=False):
        if seg['hdr']['SEGNAME'].rstrip(b'\x00 ') == name:
            return seg['hdr'], seg['raw']
    raise AssertionError(f'no {name!r} segment in output; segments = '
                          f'{[s["hdr"]["SEGNAME"] for s in omf.iter_segments(out, records=False)]}')


def _decode_main_records(raw, dispdata):
    """Walk the LCONST + reloc-record stream of one main/output load
    segment; return (standalone_records, {super_type: page_list_bytes}).
    Each standalone record is ('RELOC'|'cRELOC', size, shift, offset, rel).
    Deliberately independent of gsasm.expressload.parse_super — see
    tests/test_expressload_case_b.py's identical helper for why."""
    off = dispdata
    op = raw[off]
    assert op == 0xF2, f'expected LCONST, got 0x{op:02x}'
    n = struct.unpack_from('<I', raw, off + 1)[0]
    off += 5 + n

    standalone = []
    supers = {}
    while True:
        op = raw[off]
        if op == 0x00:
            break
        if op == 0xE2:                      # RELOC
            size, shift = raw[off + 1], raw[off + 2]
            offset = struct.unpack_from('<I', raw, off + 3)[0]
            rel = struct.unpack_from('<I', raw, off + 7)[0]
            standalone.append(('RELOC', size, shift, offset, rel))
            off += 11
        elif op == 0xF5:                    # cRELOC
            size, shift = raw[off + 1], raw[off + 2]
            offset = struct.unpack_from('<H', raw, off + 3)[0]
            rel = struct.unpack_from('<H', raw, off + 5)[0]
            standalone.append(('cRELOC', size, shift, offset, rel))
            off += 7
        elif op == 0xF7:                    # SUPER
            total = struct.unpack_from('<I', raw, off + 1)[0]
            stype = raw[off + 5]
            supers[stype] = raw[off + 6:off + 5 + total]
            off += 5 + total
        else:
            raise AssertionError(f'unexpected opcode 0x{op:02x} at {off}')
    return standalone, supers


# ---------------------------------------------------------------------------
# 1. Injection opts (seg_images / reloc_dicts) are inert when unset
# ---------------------------------------------------------------------------
# Two SEPARATE tiny objects (own PROC/segment each), built with
# multiseg=True + segnames/segkinds so expressload() takes the multi-segment
# output path where the injection branch lives (single-segment builds never
# consult seg_images/reloc_dicts at all).

_SEG_A_SRC = (
    'SegA\tPROC\n'
    '\tlda\t#Target1\n'
    '\trts\n'
    'Target1\tanop\n'
    '\tENDP\n'
    '\tEND\n'
)
_SEG_B_SRC = (
    'SegB\tPROC\n'
    '\tlda\t#Target2\n'
    '\trts\n'
    'Target2\tanop\n'
    '\tENDP\n'
    '\tEND\n'
)


def _build_two_object_multiseg(extra_opts=None):
    o1, a1 = _assemble(_SEG_A_SRC, 'a.aii')
    o2, a2 = _assemble(_SEG_B_SRC, 'b.aii')
    objects = [(o1, a1), (o2, a2)]
    opts = {'multiseg': True, 'segnames': [b'SEG1', b'SEG2'], 'segkinds': [0, 0]}
    if extra_opts:
        opts.update(extra_opts)
    return expressload(objects, opts=opts)


def test_injection_opts_absent_vs_explicit_none_byte_identical():
    out_absent = _build_two_object_multiseg()
    out_none = _build_two_object_multiseg(
        {'seg_images': None, 'reloc_dicts': None})
    # If a future change swapped `opts.get('reloc_dicts')` for a bare
    # `'reloc_dicts' in opts` membership test (or otherwise let a
    # present-but-None key take a different code path than an absent key),
    # this would fail -- it is exactly the tool-safety contract these two
    # keys exist to preserve.
    assert out_absent == out_none
    assert len(out_absent) > 0


def test_injection_opts_actually_change_output_when_supplied():
    """Non-vacuity check for the test above: prove seg_images/reloc_dicts
    are NOT simply dead parameters (which would make byte-identity above
    trivially true regardless of the opt-gating logic). Inject a real,
    deliberately-different image for SEG1 and confirm the output moves."""
    out_default = _build_two_object_multiseg()
    out_injected = _build_two_object_multiseg({
        'seg_images': {b'SEG1': b'\xEA\xEA\xEA\xEA'},
        'reloc_dicts': {b'SEG1': b'\x00'},   # no relocs, just the END byte
    })
    assert out_injected != out_default
    _, seg1_default = _find_segment(out_default, b'SEG1')
    _, seg1_injected = _find_segment(out_injected, b'SEG1')
    assert seg1_injected != seg1_default
    # SEG2 (not named in either injection dict) must be untouched.
    _, seg2_default = _find_segment(out_default, b'SEG2')
    _, seg2_injected = _find_segment(out_injected, b'SEG2')
    assert seg2_default == seg2_injected


# ---------------------------------------------------------------------------
# 2. opts['loadfile_name'] -> ~ExpressLoad directory LOADNAME (header[44:54])
# ---------------------------------------------------------------------------

_SOLO_SRC = (
    'Solo\tPROC\n'
    '\tlda\t#Target\n'
    '\trts\n'
    'Target\tanop\n'
    '\tENDP\n'
    '\tEND\n'
)


def test_loadname_threaded_and_absent_stays_zeroed():
    obj, a = _assemble(_SOLO_SRC, 'solo.aii')
    objects = [(obj, a)]

    out_with = expressload(objects, opts={'loadfile_name': 'Finder'})
    out_without = expressload(objects, opts={})

    hdr_with, raw_with = _find_segment(out_with, b'~ExpressLoad')
    hdr_without, raw_without = _find_segment(out_without, b'~ExpressLoad')
    assert hdr_with['KIND'] == 0x8001
    assert hdr_without['KIND'] == 0x8001

    header_with = raw_with[:hdr_with['DISPDATA']]
    header_without = raw_without[:hdr_without['DISPDATA']]

    # -- non-vacuity: the two headers must actually differ, and specifically
    # only in the LOADNAME field -- proving the assertions below discriminate
    # a reverted (opt ignored) implementation from the real one.
    assert header_with != header_without
    assert header_with[:44] == header_without[:44]        # fixed header unchanged
    assert header_with[54:] == header_without[54:]         # SEGNAME field unchanged

    assert header_with[44:54] == b'Finder    '             # 6 chars + 4 spaces
    assert header_without[44:54] == b'\x00' * 10


# ---------------------------------------------------------------------------
# 3. _scan_case_b size-4 discriminator: flagged addend vs Label-N dispatch idiom
# ---------------------------------------------------------------------------
# Target is placed at offset 0 of its own PROC (the very first thing in the
# segment), so its resolved value is 0 -- which makes `Target-2` evaluate to
# -2 mod 2**32 == 0xFFFFFFFE: bit 31 set (like a real flag) but bits 24-29
# ALSO all set (0x3F000000 mask nonzero), the exact pattern the size-4 guard
# must reject.  `Target+$80000000` evaluates to the clean flag family
# (0x80000000 | 0, bits 24-29 clear) and must become a standalone RELOC.

_CASE_B4_SRC = (
    'CaseB4\tPROC\n'
    'Target\tanop\n'
    '\tdc.l\tTarget+$80000000\n'
    '\tdc.l\tTarget-2\n'
    '\trts\n'
    '\tENDP\n'
    '\tEND\n'
)


def test_case_b_size4_flag_standalone_vs_dispatch_idiom_stays_reloc():
    obj, a = _assemble(_CASE_B4_SRC, 'caseb4.aii')
    assert a.symbols['TARGET'] == 0, a.symbols['TARGET']   # fixture precondition

    out = expressload([(obj, a)])
    main_hdr, main_raw = _find_segment(out, b'main')
    standalone, supers = _decode_main_records(main_raw, main_hdr['DISPDATA'])

    # -- 1. `Target+$80000000` (offset 0, the first dc.l): a standalone
    # RELOC (0xE2) carrying the FULL flagged 32-bit value, not folded into a
    # SUPER page list.
    assert len(standalone) == 1, standalone
    kind, size, shift, offset, rel = standalone[0]
    assert (kind, size, shift, offset) == ('RELOC', 4, 0, 0), standalone
    assert rel == 0x80000000, hex(rel)

    # -- 2. `Target-2` (offset 4, the second dc.l) must NOT appear as a
    # second standalone record -- a reverted/loosened discriminator (e.g.
    # accepting any val > 0xFFFFFF, or dropping the `& 0x3F000000 == 0`
    # check) would misclassify 0xFFFFFFFE as a flagged addend too and emit a
    # spurious second RELOC here, which this length check catches.
    assert offset != 4
    offsets_only = [s[3] for s in standalone]
    assert 4 not in offsets_only, standalone

    # -- 3. Instead `Target-2` stays an ordinary SUPER-type-1 (size=4/3,
    # shift=0) page-list site at offset 4 -- proving the rule is selective
    # (rejects the dispatch idiom) rather than accidentally dropping the
    # site's relocation altogether.
    assert 1 in supers, supers

    def _page_offsets(page_list):
        offs, page, i = [], 0, 0
        while i < len(page_list):
            b = page_list[i]; i += 1
            if b & 0x80:
                page += b & 0x7f
            else:
                cnt = (b & 0x7f) + 1
                for _ in range(cnt):
                    offs.append(page * 256 + page_list[i]); i += 1
                page += 1
        return offs

    assert _page_offsets(supers[1]) == [4], supers[1].hex()


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
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f'ERROR {name}: {exc!r}')
        else:
            print(f'ok   {name}')
    print(f'{len(_TESTS) - failed}/{len(_TESTS)} passed')
    sys.exit(1 if failed else 0)
