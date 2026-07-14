"""Hand-authored test for task #15's linker fix (system-settings-gs A0 debug
session): ``gsasm.linkiigs.link(objects, {'super': True, ...})`` builds a
PLAIN (non-ExpressLoad) single-segment load file whose OMF SEGNUM is always 1
(see ``_link._make_segment(out_name, out_load, out_org, out_kind, 1, ...)``
in ``linkiigs.link``). SUPER types 26+ mean "INTERSEG to segment (type-25)",
so a same-segment bank-byte relocation (``lda #^Label``, OMF (size=2,
shift=16)) in THIS single-segment path must be typed 25 + 1 = 26.

BUG (pre-fix): ``linkiigs.link``'s ``super=True`` branch reused
``expressload._scan_relocs``, whose ``_SUPER_TYPE`` table hardcodes the raw
type 27 for (size=2, shift=16) -- correct ONLY for an ExpressLoad'd
Tool/FST/driver file, where the main code segment is always OMF SEGNUM 2 (25
+ 2 = 27; see expressload.py's ``corrected_type = 25 + tgt_segnum``). Emitted
verbatim into a genuinely single-segment plain load file, SUPER type 27 tells
the GS/OS System Loader "relocate against segment 2", which does not exist
there -- the loader dies with error $1101.

CORROBORATION: work/rezloadcheck.py's golden Launcher.Load (LinkIIgs -x,
single segment, no ~ExpressLoad wrapper) carries SUPER type 26 -- never 27
-- for its (size=2, shift=16) class (see that harness's own local
``_scan_reloc_dictionary``, which has always used the correct type-26
mapping; ``linkiigs.link``'s shared ``super=True`` path was the one place
still carrying the bug, unexercised by any existing harness).

Run either as:
    python3 -m pytest tests/test_linkiigs_super_type26.py
    python3 tests/test_linkiigs_super_type26.py
"""
import os
import struct
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from gsasm import asm, omf, linkiigs               # noqa: E402

# One PROC: a plain (unflagged) high/low far-pointer style pair on Target --
# the (size=2, shift=16) bank-byte class that must fold into SUPER type 26
# (not 27) in a single-segment plain load file.
SOURCE = (
    'Single\tPROC\n'
    '\tlda\t#^Target\n'
    '\tlda\t#Target\n'
    '\trts\n'
    'Target\tanop\n'
    '\tENDP\n'
    '\tEND\n'
)


def _decode_tail(seg_bytes, dispdata):
    """Walk LCONST + reloc records of one OMF segment; return
    (code_len, {super_type: page_list_bytes})."""
    off = dispdata
    op = seg_bytes[off]
    assert op == 0xF2, f'expected LCONST, got 0x{op:02x}'
    n = struct.unpack_from('<I', seg_bytes, off + 1)[0]
    off += 5 + n

    supers = {}
    while True:
        op = seg_bytes[off]
        if op == 0x00:
            break
        if op == 0xF7:                      # SUPER
            total = struct.unpack_from('<I', seg_bytes, off + 1)[0]
            stype = seg_bytes[off + 5]
            supers[stype] = seg_bytes[off + 6:off + 5 + total]
            off += 5 + total
        else:
            raise AssertionError(f'unexpected opcode 0x{op:02x} at {off} '
                                 f'(expected only SUPER/END in this fixture)')
    return n, supers


def _page_offsets(page_list):
    offs, page = [], 0
    i = 0
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


def test_single_segment_plain_load_uses_super_type_26_not_27():
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, 'single.asm')
        with open(src, 'w') as f:
            f.write(SOURCE)
        a = asm.assemble(src, [d])
        assert not a.errors, a.errors
        obj = omf.emit(a)

    out = linkiigs.link([(obj, a)], {'super': True})

    h = omf.parse_header(out)
    assert h['SEGNUM'] == 1, 'plain merge=True output is always OMF segment 1'

    _code_len, supers = _decode_tail(out, h['DISPDATA'])

    # The critical assertion: type 26 present, type 27 absent.
    assert 27 not in supers, (
        'SUPER type 27 in a single-segment plain load file means '
        '"INTERSEG to segment 2", which does not exist here -- '
        'GS/OS System Loader error $1101')
    assert 26 in supers, 'the (size=2, shift=16) reloc must fold into SUPER type 26'

    # lda #^Target operand precedes lda #Target operand; both target the same
    # symbol, so type 26 (bank byte) and type 0 (16-bit addr) each get one
    # page-list entry.
    target = a.symbols['TARGET']
    assert 0 in supers
    offs26 = _page_offsets(supers[26])
    offs0 = _page_offsets(supers[0])
    assert len(offs26) == 1 and len(offs0) == 1
    # sanity: the two operand offsets are 3 bytes apart (lda #^ / lda # are
    # each 3-byte encodings: opcode + 2-byte immediate)
    assert offs0[0] - offs26[0] == 3
    assert offs26[0] == 1  # lda #^Target operand starts right after the opcode byte


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
