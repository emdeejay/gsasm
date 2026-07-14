"""Hand-authored test for the ExpressLoad "case-B" flagged-relocation rule
(packet R9; see docs/TODO.md section 1 and docs/design/expressload.md).

CONFIRMED rule: a relocation whose target expression carries addend bits >= 24
(e.g. the ModalDialog filterProc/hook pointer conventions `+$80000000` /
`+$C0000000`) cannot be represented in a SUPER page list -- a page-list patch
only ever restores a clean, <=24-bit segment-relative offset. MPW's
ExpressLoad converter recognises this and emits a standalone RELOC (0xE2)
instead, whose relOffset is the FULL, un-shifted 32-bit value (flag bits
included) -- for BOTH halves of a far-pointer PEA pair (the high-word `pea
#^(Label+$80000000)` at shift=16 and the low-word `pea #Label+$80000000` at
shift=0 store the SAME flagged value, not the value shifted right 16), and
for an unpaired single shift-16 record (Tool027's `lda #^(Label+$80000000)`
style, no matching low-word pair).

This was proven against the golden System 6.0.1 corpus (work/reloc_survey.py):
all 9 flagged case-B records are exactly this pattern, mapped to source lines
in docs/TODO.md's table (Tool014/023/027, TS3). It is corpus-free here: an
ORIGINAL source (no Apple material) exercising the same PEA-pair / unpaired
shift-16 idioms, with expected bytes computed BY HAND (raw struct decoding of
the OMF RELOC/SUPER opcodes -- see GS.OS/Loader/ExpressLoad/ExpressLoad.src's
documented record layout), not by calling gsasm.expressload a second time for
the "expected" side.

Also proves the negative: an UNFLAGGED reference to the same kind of symbol
(no addend) still folds into SUPER as before -- the rule is selective, not a
blanket "never SUPER-ize size=2 shift=0/16" regression -- and that the
`dc.l routine-1` dispatch idiom (ADD literal 0xFFFFFFFF, i.e. two's-complement
-1 -- ubiquitous in every tool's jump table) is NOT misclassified as a case-B
flag merely because it evaluates to a large 32-bit value.

Run either as:
    python3 -m pytest tests/test_expressload_case_b.py
    python3 tests/test_expressload_case_b.py
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
# Fixture source: one PROC exercising, in order:
#   (1) a far-pointer PEA pair on FarTarget, flagged +$80000000 (shift=16 then
#       shift=0 -- the WindMgr/StdFile idiom)
#   (2) an UNPAIRED shift-16 reference on SoleTarget, flagged +$C0000000 (the
#       FontMgr idiom -- only the high half references the symbol)
#   (3) a normal (unflagged) high/low pair on NormalTarget -- must still fold
#       into SUPER type 27 / type 0, proving the rule is selective
#   (4) a `dc.l routine-1` dispatch-table style entry (ADD lit=$FFFFFFFF) on
#       NormalTarget -- must NOT be misread as a flagged addend merely
#       because -1 is a large unsigned 32-bit literal
# ---------------------------------------------------------------------------
SOURCE = (
    'CaseB\tPROC\n'
    '\tpea\t#^(FarTarget+$80000000)\n'
    '\tpea\t#FarTarget+$80000000\n'
    '\tpea\t#^(SoleTarget+$C0000000)\n'
    '\tlda\t#^NormalTarget\n'
    '\tlda\t#NormalTarget\n'
    '\tdc.l\tNormalTarget-1\n'
    '\trts\n'
    'FarTarget\tanop\n'
    'SoleTarget\tanop\n'
    'NormalTarget\tanop\n'
    '\tENDP\n'
    '\tEND\n'
)


# ---------------------------------------------------------------------------
# Minimal, self-contained OMF relocation-record walker (deliberately NOT
# gsasm.expressload.parse_super: that helper stops at the first unrecognised
# opcode and was never taught about a *leading* standalone RELOC/cRELOC run,
# so it cannot see past case-B's own output -- exactly why this test decodes
# the raw bytes directly instead of trusting the library's own helper).
# ---------------------------------------------------------------------------
def _split_segments(data):
    segs = []
    off = 0
    while off < len(data):
        h = omf.parse_header(data[off:])
        bc = h['BYTECNT']
        if bc == 0:
            break
        segs.append((h, data[off:off + bc]))
        off += bc
    return segs


def _decode_tail(seg_bytes, dispdata):
    """Walk LCONST + reloc records of one main segment; return
    (code_len, [('RELOC', size, shift, offset, rel), ...],
     {super_type: page_list_bytes})."""
    off = dispdata
    op = seg_bytes[off]
    assert op == 0xF2, f'expected LCONST, got 0x{op:02x}'
    n = struct.unpack_from('<I', seg_bytes, off + 1)[0]
    off += 5 + n

    standalone = []
    supers = {}
    while True:
        op = seg_bytes[off]
        if op == 0x00:
            break
        if op == 0xE2:                      # RELOC
            size, shift = seg_bytes[off + 1], seg_bytes[off + 2]
            offset = struct.unpack_from('<I', seg_bytes, off + 3)[0]
            rel = struct.unpack_from('<I', seg_bytes, off + 7)[0]
            standalone.append(('RELOC', size, shift, offset, rel))
            off += 11
        elif op == 0xF5:                    # cRELOC
            size, shift = seg_bytes[off + 1], seg_bytes[off + 2]
            offset = struct.unpack_from('<H', seg_bytes, off + 3)[0]
            rel = struct.unpack_from('<H', seg_bytes, off + 5)[0]
            standalone.append(('cRELOC', size, shift, offset, rel))
            off += 7
        elif op == 0xF7:                    # SUPER
            total = struct.unpack_from('<I', seg_bytes, off + 1)[0]
            stype = seg_bytes[off + 5]
            supers[stype] = seg_bytes[off + 6:off + 5 + total]
            off += 5 + total
        else:
            raise AssertionError(f'unexpected opcode 0x{op:02x} at {off}')
    return n, standalone, supers


def _shift_stored(positive_shift):
    """bitShiftCount is stored as a signed byte; a positive right-shift N is
    encoded as (-N) & 0xFF (0 -> 0, 16 -> 240)."""
    return (-positive_shift) & 0xFF


def test_case_b_far_pointer_pair_and_unpaired():
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, 'caseb.asm')
        with open(src, 'w') as f:
            f.write(SOURCE)
        a = asm.assemble(src, [d])
        assert not a.errors, a.errors
        obj = omf.emit(a)
        out = expressload([(obj, a)])

    segs = _split_segments(out)
    assert len(segs) == 2, f'expected [~ExpressLoad, main], got {len(segs)} segs'
    (dir_hdr, _dir_seg), (main_hdr, main_seg) = segs
    assert dir_hdr['SEGNAME'].rstrip(b'\x00 ') == b'~ExpressLoad'
    assert main_hdr['SEGNAME'].rstrip(b'\x00 ') == b'main'

    code_len, standalone, supers = _decode_tail(main_seg, main_hdr['DISPDATA'])

    # Code layout (16 bytes): three PEA(3B) + lda#^(3B) + lda#(3B) + dc.l(4B?)
    # -- dc.l is a 4-byte CONST, not a relocation site itself in the code
    # image byte count; recompute from the assembled symbol table instead of
    # hardcoding offsets, so the test does not silently drift if the encoding
    # of any instruction changes width.
    far = a.symbols['FARTARGET']
    sole = a.symbols['SOLETARGET']
    normal = a.symbols['NORMALTARGET']

    # -- 1. The far-pointer pair and the unpaired shift-16 record are BOTH
    #    standalone RELOC (0xE2), in ascending-offset order, each carrying the
    #    FULL flagged 32-bit value -- not the SUPER-page-list-eligible
    #    (size=2, shift=0/16) encoding a naive router would pick.
    assert len(standalone) == 3, standalone
    kinds = [s[0] for s in standalone]
    assert kinds == ['RELOC', 'RELOC', 'RELOC'], standalone
    offsets = [s[3] for s in standalone]
    assert offsets == sorted(offsets), 'standalone records must be offset-sorted'

    hi_far = next(s for s in standalone if s[3] == 1)     # pea #^(...) operand
    lo_far = next(s for s in standalone if s[3] == 4)     # pea #(...)   operand
    hi_sole = next(s for s in standalone if s[3] == 7)    # pea #^(...) operand

    assert hi_far == ('RELOC', 2, _shift_stored(16), 1, 0x80000000 | far)
    assert lo_far == ('RELOC', 2, _shift_stored(0), 4, 0x80000000 | far)
    assert hi_sole == ('RELOC', 2, _shift_stored(16), 7, 0xC0000000 | sole)
    # both halves of the pair carry the SAME (unshifted) flagged value
    assert hi_far[4] == lo_far[4]

    # -- 2. Neither FarTarget's nor SoleTarget's offsets leak into any SUPER
    #    page list (they were excluded from SUPER precisely because of the
    #    flag).
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

    all_super_offsets = set()
    for stype, pl in supers.items():
        all_super_offsets |= set(_page_offsets(pl))
    assert 1 not in all_super_offsets and 4 not in all_super_offsets
    assert 7 not in all_super_offsets

    # -- 3. NormalTarget's UNFLAGGED high/low pair still folds into SUPER
    #    type 27 / type 0 as before -- the rule is selective, not a blanket
    #    "size=2 shift=0/16 is never SUPER-eligible" regression.  Code layout:
    #    3 PEA (3B each, offsets 0/3/6) + lda#^Normal (3B @9, operand @10) +
    #    lda#Normal (3B @12, operand @13) + dc.l (4B @15) + rts (@19).
    assert 27 in supers and 0 in supers
    assert _page_offsets(supers[27]) == [10]    # lda #^NormalTarget operand
    assert _page_offsets(supers[0]) == [13]     # lda #NormalTarget operand

    # -- 4. The `dc.l NormalTarget-1` dispatch-table idiom (ADD lit=0xFFFFFFFF,
    #    the OMF encoding of "-1") is a (size=4, shift=0) SUPER-type-1 site.
    #    It must fold into SUPER as usual, NOT appear as a spurious standalone
    #    RELOC -- that would mean the ubiquitous "-1" idiom got misclassified
    #    as a flagged addend merely because it evaluates to a large unsigned
    #    32-bit value (the false positive _scan_case_b is built to avoid by
    #    restricting to (size, shift) in {(2, 0), (2, 16)}).
    assert 1 in supers
    assert _page_offsets(supers[1]) == [15]
    assert len(standalone) == 3   # no 4th (spurious) standalone record


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
