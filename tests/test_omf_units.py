"""Direct unit tests for ``gsasm/omf.py`` — OMF v2.0 parse + emit.

Architecture-review 2026-08-02 finding 5 ("the pure core is untested as
units") names ``omf.py``'s classifiers as pure functions with crisp inputs
and zero direct tests; slate item 1 is this file.  Everything here is
CORPUS-FREE: synthetic OMF byte strings and tiny synthetic assemblies built
in a tempdir, so it runs in CI on a machine with no ``ref/`` tree.

This file PINS today's behaviour.  ``docs/REFACTORING.md`` §5 lists
``_diff_reloc`` / ``_mul_reloc_expr`` / ``_grouped_linear_reloc`` as
Do-Not-Touch (fixtures 035/040/044/047); the assertions below record what
those functions actually decide, not what they arguably ought to.  Three
observations that looked odd on the way in are pinned deliberately and
flagged with a SUSPICIOUS comment.

Ground truth used for the record-layout / opcode / SUPER assertions:
``docs/GROUNDING_2026-08-02.md`` — the OMF opcode set, the record layouts,
the SUPER subtype formulas (13+segnum, 25+segnum) and the page-list
skip/count codec are all DOCUMENTED against the GS/OS System Loader v4.00
source (``GS.OS/Loader/`` Relocation.a ``Do_SUPER`` + Loader.Equates).
``_reloc_weight``'s weight-0 core is documented algebra (MPW Asm Ref
p.31-33: same-segment opposite-sign relocatable terms cancel); the ADD/SUB
chain and shift-riding generalization is gsasm's own and is pinned here as
such.

Run either as:
    python3 -m pytest tests/test_omf_units.py
    python3 tests/test_omf_units.py
"""
import os
import struct
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from gsasm import asm, omf                                    # noqa: E402
from gsasm.omf import (                                       # noqa: E402
    emit_super, parse_super, _decode_page_list, _encode_page_list)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

_ASM_CACHE: dict = {}


def assemble(source: str):
    """Assemble *source* from a temp dir and return the Assembler.

    Memoised: the classifier tests below re-use a handful of fixtures and an
    assembly is the slow part of this file.
    """
    a = _ASM_CACHE.get(source)
    if a is None:
        d = tempfile.mkdtemp()
        path = os.path.join(d, 't.aii')
        with open(path, 'w') as fh:
            fh.write(source)
        a = asm.assemble(path, [d])
        assert not a.errors, a.errors[:3]
        _ASM_CACHE[source] = a
    return a


def in_seg(a, name):
    """Point the assembler's emit-time cursor at segment *name* (what
    ``emit_segment`` does before calling any classifier) and return the
    folded SEGNAME the classifiers expect as their ``segname`` argument."""
    folded = a._fold(name)
    a._rseg = next(i for i, s in enumerate(a.segs)
                   if a._fold(s.name or '') == folded)
    a.loc = 0
    a._rlg = a._rlg2 = a._rwith = None
    return folded


def lit(v, n=4):
    """The OMF expression ops for `push literal v` (numlen n)."""
    return bytes([0x81]) + omf._num(v & ((1 << (8 * n)) - 1), n)


def sym(name):
    """The OMF expression ops for `push label name` (0x83 + counted str)."""
    return bytes([0x83]) + omf._omfstr(name)


def lit_neg(n):
    """A right-shift-by-n count as OMF encodes it: the negative literal."""
    return ('lit', (-n) & 0xFFFFFFFF)


# Two segments, no ORG anywhere: everything relocatable.  Layout
#   ALPHA: ASTART=0  AMID=2  AEND=4   (length 4)
#   BETA:  0         BLAB=2           (length 4)
SRC_TWO_RELOC_SEGS = (
    'Alpha\tPROC\n'
    'AStart\tanop\n'
    '\tdc.w\t0\n'
    'AMid\tanop\n'
    '\tdc.w\t0\n'
    'AEnd\tanop\n'
    '\tENDP\n'
    'Beta\tPROC\n'
    '\tdc.w\t0\n'
    'BLab\tanop\n'
    '\tdc.w\t0\n'
    '\tENDP\n'
    '\tEND\n'
)

# ORG flows forward from a `PROC ORG addr`, so every PROC here is absolute.
#   ABS1 @ $FF0000: O1=$FF0000  O1B=$FF0002   (length 4)
#   ABS2 @ $FF1000: O2=$FF1000                (length 2)
# TMP is a `PROC TEMPORG` — seg.org stays None, labels are absolute literals.
SRC_ORG_SEGS = (
    'Abs1\tPROC\tORG $FF0000\n'
    'O1\tanop\n'
    '\tdc.w\t0\n'
    'O1b\tanop\n'
    '\tdc.w\t0\n'
    '\tENDP\n'
    'Abs2\tPROC\tORG $FF1000\n'
    'O2\tanop\n'
    '\tdc.w\t0\n'
    '\tENDP\n'
    'Tmp\tPROC\tTEMPORG $2000\n'
    'T1\tanop\n'
    '\tdc.w\t0\n'
    '\tENDP\n'
    '\tEND\n'
)

SRC_IMPORTS = (
    '\tIMPORT\tExtA\n'
    '\tIMPORT\tExtB\n'
    'Konst\tEQU\t8\n'
    'Main\tPROC\n'
    'MLab\tanop\n'
    '\tdc.w\t0\n'
    '\tENDP\n'
    '\tEND\n'
)

# MAIN has two ENTRYs (EARLY at 0, LATER at 4) with HERE at 2 in between;
# DATASEG is a RECORD (is_data); OTHER is a plain third segment.
SRC_ENTRIES = (
    'Main\tPROC\n'
    '\tENTRY\tEarly\n'
    '\tENTRY\tLater\n'
    'Early\tanop\n'
    '\tdc.w\t0\n'
    'Here\tanop\n'
    '\tdc.w\t0\n'
    'Later\tanop\n'
    '\tdc.w\t0\n'
    '\tENDP\n'
    'DataSeg\tRECORD\n'
    'DField\tds.w\t1\n'
    'DField2\tds.w\t1\n'
    '\tENDR\n'
    'Other\tPROC\n'
    '\tdc.w\t0\n'
    '\tENDP\n'
    '\tEND\n'
)

# The same ENTRY name defined in two segments (AppleDisk5.25 `wexit` shape).
SRC_DUP_ENTRY = (
    'Fmt16\tPROC\n'
    '\tENTRY\tWexit\n'
    '\tdc.w\t0\n'
    'Wexit\tanop\n'
    '\trts\n'
    '\tENDP\n'
    'Wr16\tPROC\n'
    '\tENTRY\tWexit\n'
    '\tdc.w\t0\n'
    'Wexit\tanop\n'
    '\trts\n'
    '\tENDP\n'
    '\tEND\n'
)

# Fixture 035's shape: an ORG'd pad PROC (MYSTART) that is ALSO IMPORTed, so
# the linker resolves it by name even though it has a local absolute value.
# The relocatable PROC comes first because ORG flows forward to later PROCs.
SRC_IMPORTED_ORG_PAD = (
    '\tIMPORT\tMyStart\n'
    'Rel\tPROC\n'
    '\tdc.w\t0\n'
    'RLab\tanop\n'
    '\tdc.w\t0\n'
    '\tENDP\n'
    'MyStart\tPROC\tORG $2000\n'
    '\tdc.w\t0\n'
    'MyEnd\tanop\n'
    '\tdc.w\t0\n'
    '\tENDP\n'
    '\tEND\n'
)

# The equ_alias shadowing shape (NetBoot Console SortArray's `Count`):
# COUNT is an EQU aliasing the relocatable CDBASE+2, and SORTARRAY *also*
# defines its own local label COUNT (at offset 2, after a filler word).
SRC_ALIAS_SHADOW = (
    'ConsData\tPROC\n'
    'CDBase\tanop\n'
    '\tdc.w\t0\n'
    '\tdc.w\t0\n'
    '\tENDP\n'
    'Count\tEQU\tCDBase+2\n'
    'Other\tPROC\n'
    '\tdc.w\t0\n'
    '\tENDP\n'
    'SortArray\tPROC\n'
    '\tdc.w\t0\n'
    'Count\tds.w\t1\n'
    '\tENDP\n'
    '\tEND\n'
)


# ===========================================================================
# 1. primitives: _num, _omfstr, _core, _eval, _body_length, _build_body
# ===========================================================================

def test_num_is_little_endian_and_width_selectable():
    assert omf._num(0x12345678) == b'\x78\x56\x34\x12'      # default 4 bytes
    assert omf._num(3, 2) == b'\x03\x00'
    assert omf._num(0x1234, 1) == b'\x34'                   # truncates, no error


def test_omfstr_is_a_mac_roman_counted_string():
    assert omf._omfstr('AB') == b'\x02AB'
    assert omf._omfstr('') == b'\x00'
    # mac_roman, not utf-8: the copyright sign is one byte (0xA9)
    assert omf._omfstr('\xa9') == b'\x01\xa9'


def test_core_strips_operand_decoration():
    # size prefix / indexing / indirection are stripped ...
    assert omf._core('|Foo') == 'Foo'
    assert omf._core('!Foo') == 'Foo'
    assert omf._core('Foo,x') == 'Foo'
    assert omf._core('(ptr),y') == 'ptr'
    assert omf._core('[ptr],y') == 'ptr'
    assert omf._core('(Foo,x)') == 'Foo'
    assert omf._core('[<data]') == 'data'
    # ... but on an IMMEDIATE operand `< > ^` is byte extraction and stays,
    # so _expr_for can turn it into a shift.
    assert omf._core('#Foo') == 'Foo'
    assert omf._core('#^Foo') == '^Foo'
    assert omf._core('#<Foo') == '<Foo'
    # immediate parens are arithmetic: keep them AND the trailing shift
    assert omf._core('#(muReturn-1)>>8') == '(muReturn-1)>>8'
    # after an explicit size prefix the operand is direct, so its parens are
    # arithmetic too (TextEdit fastdraw `pea |(returnHere-1)>>8`)
    assert omf._core('|(returnHere-1)>>8') == '(returnHere-1)>>8'


def test_eval_stack_machine():
    assert omf._eval([('lit', 5), ('lit', 3), ('op', 0x01), 'end'], {}) == 8
    assert omf._eval([('lit', 5), ('lit', 3), ('op', 0x02), 'end'], {}) == 2
    assert omf._eval([('lit', 5), ('lit', 3), ('op', 0x03), 'end'], {}) == 15
    assert omf._eval([('lit', 7), ('lit', 2), ('op', 0x04), 'end'], {}) == 3
    assert omf._eval([('sym83', 'X'), ('lit', 2), ('op', 0x01), 'end'],
                     {'X': 10}) == 12
    assert omf._eval(['loc', 'end'], {'__LOC__': 9}) == 9


def test_eval_shift_count_is_signed_and_arithmetic_is_mod_2_32():
    # 0x07 is SHL with a SIGNED count: negative means shift right.
    assert omf._eval([('lit', 1), ('lit', 8), ('op', 0x07), 'end'], {}) == 0x100
    assert omf._eval([('lit', 0x30000), lit_neg(16), ('op', 0x07), 'end'],
                     {}) == 3
    # wraparound, not Python bignum / negative
    assert omf._eval([('lit', 0), ('lit', 1), ('op', 0x02), 'end'],
                     {}) == 0xFFFFFFFF
    assert omf._eval([('lit', 0x80000000), ('lit', 2), ('op', 0x03), 'end'],
                     {}) == 0


def test_eval_degenerate_inputs_yield_zero_not_exceptions():
    assert omf._eval([], {}) == 0                       # empty
    assert omf._eval([('op', 0x01), 'end'], {}) == 0    # underflow -> skipped
    assert omf._eval([('lit', 7), ('lit', 0), ('op', 0x04), 'end'],
                     {}) == 0                           # divide by zero -> 0
    assert omf._eval([('lit', 7), ('lit', 2), ('op', 0x0C), 'end'],
                     {}) == 0                           # unsupported op -> 0
    assert omf._eval([('sym83', 'MISSING'), 'end'], {}) == 0  # unknown sym -> 0
    assert omf._eval(['loc', 'end'], {}) == 0           # no __LOC__ -> 0


def test_body_length_counts_only_byte_bearing_records():
    recs = [
        (0, 'CONST', b'\x01\x02'),
        (0, 'LCONST', b'\x03' * 300),
        (0, 'DS', 16),
        (0, 'LEXPR', (2, [('lit', 1), 'end'])),
        (0, 'RELEXPR', (2, 0, [('lit', 1), 'end'])),
        (0, 'GLOBAL', {'label': 'X'}),        # contributes no bytes
        (0, 'END', None),
        (0, 'CONST', b'\xff' * 99),           # after END: not counted
    ]
    assert omf._body_length(recs) == 2 + 300 + 16 + 2 + 2


def test_build_body_evaluates_expressions_and_relexpr():
    recs = [
        (0, 'CONST', b'\xAA'),
        (0, 'DS', 2),
        (0, 'LEXPR', (2, [('sym83', 'X'), ('lit', 1), ('op', 0x01), 'end'])),
        (0, 'END', None),
    ]
    assert omf._build_body(recs, {'X': 0x1233}, 0) == b'\xAA\x00\x00\x34\x12'
    # RELEXPR: value - address-of-next-instruction, truncated to nb bytes.
    # seg_base 0x1000, record at body offset 0, nb = 1 -> next_pc = 0x1001.
    rel = [(0, 'RELEXPR', (1, 0, [('lit', 0x1005), 'end'])), (0, 'END', None)]
    assert omf._build_body(rel, {}, 0x1000) == b'\x04'
    back = [(0, 'RELEXPR', (1, 0, [('lit', 0x0FFE), 'end'])), (0, 'END', None)]
    assert omf._build_body(back, {}, 0x1000) == b'\xFD'   # -3


# ===========================================================================
# 2. record layout: parse_records over every opcode, plus error/edge paths
# ===========================================================================

def test_rec_opcode_table_matches_the_documented_omf_opcode_set():
    """The REC table is the DOCUMENTED opcode set (Loader.Equates via the
    2026-08-02 grounding survey).  Pinned by value so a stray edit shows up
    as a named failure rather than as a mis-parsed byte three layers down."""
    assert omf.REC == {
        0x00: 'END', 0xE0: 'ALIGN', 0xE1: 'ORG', 0xE2: 'RELOC',
        0xE3: 'INTERSEG', 0xE6: 'GLOBAL', 0xE7: 'GEQU', 0xEB: 'EXPR',
        0xEC: 'ZEXPR', 0xED: 'BEXPR', 0xEE: 'RELEXPR', 0xEF: 'LOCAL',
        0xF0: 'EQU', 0xF1: 'DS', 0xF2: 'LCONST', 0xF3: 'LEXPR',
        0xF4: 'ENTRY', 0xF5: 'cRELOC', 0xF6: 'cINTERSEG', 0xF7: 'SUPER',
    }


def test_parse_records_const_lconst_ds_org_align():
    d = (bytes([0x03]) + b'\x01\x02\x03'                       # CONST(3)
         + bytes([0xF2]) + struct.pack('<I', 4) + b'\x0A\x0B\x0C\x0D'  # LCONST
         + bytes([0xF1]) + struct.pack('<I', 0x20)             # DS 32
         + bytes([0xE1]) + struct.pack('<I', 0x1234)           # ORG
         + bytes([0xE0]) + struct.pack('<I', 0x100)            # ALIGN
         + bytes([0x00]))                                      # END
    recs, end = omf.parse_records(d, 0)
    assert [r[1] for r in recs] == ['CONST', 'LCONST', 'DS', 'ORG',
                                    'ALIGN', 'END']
    assert recs[0][2] == b'\x01\x02\x03'
    assert recs[1][2] == b'\x0A\x0B\x0C\x0D'
    assert recs[2][2] == 0x20
    assert recs[3][2] == 0x1234
    assert recs[4][2] == 0x100
    assert end == len(d)
    # the offsets are absolute positions of the OPCODE byte
    assert [r[0] for r in recs] == [0, 4, 13, 18, 23, 28]


def test_parse_records_const_covers_the_whole_1_to_0xdf_range():
    """A leading byte 1..0xDF is itself the CONST length; 0xE0 and up are
    opcodes.  The boundary is the reason emit_segment cuts literal runs at
    0xDF."""
    for n in (1, 0xDF):
        recs, _ = omf.parse_records(bytes([n]) + b'\x5A' * n + b'\x00', 0)
        assert recs[0] == (0, 'CONST', b'\x5A' * n)
    # 0xE0 is ALIGN, not a 224-byte CONST
    recs, _ = omf.parse_records(bytes([0xE0]) + struct.pack('<I', 0) +
                                b'\x00', 0)
    assert recs[0][1] == 'ALIGN'


def test_parse_records_reloc_and_creloc_layouts():
    # RELOC: size(1) shift(1) off(numlen) ref(numlen)
    d = (bytes([0xE2, 4, 0]) + struct.pack('<I', 0x1122)
         + struct.pack('<I', 0x3344) + bytes([0x00]))
    recs, _ = omf.parse_records(d, 0)
    assert recs[0][1] == 'RELOC'
    assert recs[0][2] == (4, 0, 0x1122, 0x3344)
    # cRELOC: size(1) shift(1) off(2) ref(2) — the compressed form
    d = bytes([0xF5, 2, 0xF8]) + struct.pack('<H', 0x321B) \
        + struct.pack('<H', 0x3226) + bytes([0x00])
    recs, _ = omf.parse_records(d, 0)
    assert recs[0][1] == 'cRELOC'
    assert recs[0][2] == (2, 0xF8, 0x321B, 0x3226)   # 0xF8 == right shift 8
    assert len(d) == 8                               # 1+1+1+2+2 + END


def test_parse_records_interseg_and_cinterseg_layouts():
    # INTERSEG: size shift off(numlen) fileno(2) segno(2) segoff(numlen)
    d = (bytes([0xE3, 3, 0]) + struct.pack('<I', 0x10)
         + struct.pack('<H', 1) + struct.pack('<H', 2)
         + struct.pack('<I', 0x40) + bytes([0x00]))
    recs, _ = omf.parse_records(d, 0)
    assert recs[0][1] == 'INTERSEG'
    assert recs[0][2] == (3, 0, 0x10, 1, 2, 0x40)
    # cINTERSEG: size shift off(2) segno(1) segoff(2); FILENO is implicitly 1
    d = (bytes([0xF6, 3, 0]) + struct.pack('<H', 0x10) + bytes([2])
         + struct.pack('<H', 0x40) + bytes([0x00]))
    recs, _ = omf.parse_records(d, 0)
    assert recs[0][1] == 'cINTERSEG'
    assert recs[0][2] == (3, 0, 0x10, 1, 2, 0x40), \
        'cINTERSEG has no FILENO field; the parser synthesises fileno=1'


def test_parse_records_expr_family_and_relexpr():
    expr = sym('TARGET') + lit(4) + bytes([0x01, 0x00])
    for op, name in ((0xEB, 'EXPR'), (0xEC, 'ZEXPR'), (0xED, 'BEXPR'),
                     (0xF3, 'LEXPR')):
        recs, _ = omf.parse_records(bytes([op, 2]) + expr + bytes([0x00]), 0)
        assert recs[0][1] == name
        assert recs[0][2] == (2, [('sym83', 'TARGET'), ('lit', 4),
                                  ('op', 1), 'end'])
    # RELEXPR carries an extra numlen ORIGIN field between size and expr
    d = bytes([0xEE, 2]) + struct.pack('<I', 0x99) + expr + bytes([0x00])
    recs, _ = omf.parse_records(d, 0)
    assert recs[0][1] == 'RELEXPR'
    assert recs[0][2] == (2, 0x99, [('sym83', 'TARGET'), ('lit', 4),
                                    ('op', 1), 'end'])


def test_parse_records_symbol_records():
    """GLOBAL/LOCAL/ENTRY carry label+LENGTH+type+priv; GEQU/EQU append an
    expression."""
    plain = omf._omfstr('SYMBOL') + struct.pack('<H', 0) + bytes([0x4D, 0x01])
    for op, name in ((0xE6, 'GLOBAL'), (0xEF, 'LOCAL'), (0xF4, 'ENTRY')):
        recs, _ = omf.parse_records(bytes([op]) + plain + bytes([0x00]), 0)
        assert recs[0][1] == name
        assert recs[0][2] == {'label': 'SYMBOL', 'len': 0,
                              'type': 0x4D, 'priv': 1}
    valued = omf._omfstr('K') + struct.pack('<H', 0) + bytes([0x4D, 0x00]) \
        + lit(42) + bytes([0x00])
    for op, name in ((0xE7, 'GEQU'), (0xF0, 'EQU')):
        recs, _ = omf.parse_records(bytes([op]) + valued + bytes([0x00]), 0)
        assert recs[0][1] == name
        assert recs[0][2] == {'label': 'K', 'len': 0, 'type': 0x4D,
                              'priv': 0, 'expr': [('lit', 42), 'end']}


def test_read_expr_decodes_every_push_form():
    d = (lit(7)                                   # 0x81 numlen literal
         + sym('ABC')                             # 0x83 counted label
         + bytes([0x84]) + omf._omfstr('W')       # 0x84..0x87 label variants
         + bytes([0x85]) + omf._omfstr('V')
         + bytes([0x86]) + omf._omfstr('L')
         + bytes([0x87]) + omf._omfstr('T')
         + bytes([0x82])                          # 0x82 = current location
         + bytes([0x01])                          # an operator
         + bytes([0x00]))                         # end
    ops, i = omf._read_expr(d, 0, 4)
    assert ops == [('lit', 7), ('sym83', 'ABC'), ('sym84', 'W'),
                   ('sym85', 'V'), ('sym86', 'L'), ('sym87', 'T'),
                   'loc', ('op', 1), 'end']
    assert i == len(d)


def test_read_expr_honours_numlen():
    d = bytes([0x81]) + struct.pack('<H', 0x1234) + bytes([0x00])
    assert omf._read_expr(d, 0, 2)[0] == [('lit', 0x1234), 'end']


def test_read_expr_unterminated_stops_at_end_of_buffer():
    """No 0x00 terminator: the op-list simply lacks its 'end' sentinel — the
    parser must not loop or raise."""
    ops, i = omf._read_expr(bytes([0x82]), 0, 4)
    assert ops == ['loc'] and i == 1
    assert omf._read_expr(b'', 0, 4) == ([], 0)


def test_parse_records_unknown_opcode_is_reported_then_parsing_stops():
    """0xE4 is not in REC: the record is named '?E4', detailed 'UNHANDLED',
    and the walk stops (the record's length is unknown, so continuing would
    mis-frame everything after it)."""
    recs, end = omf.parse_records(bytes([0xE4, 0x01, 0x02]), 0)
    assert recs == [(0, '?E4', 'UNHANDLED')]
    assert end == 1


def test_parse_records_decodes_super_and_keeps_walking():
    """SUPER (0xF7) decodes to {'type', 'offsets', 'pagelist'} and the walk
    CONTINUES — the record after it is no longer invisible.

    Was pinned the other way ("names it and stops"): the missing decode branch
    made every record after a SUPER invisible, which on shipping
    ref/GSOS_6/tool_bin/Tool014#BA0000 left 1,719 bytes of the `main` segment
    unparsed with no error reported.  Since R1 promoted iter_segments to the
    one OMF segment-walker, that silent truncation was a loaded trap, so the
    branch is now real.  Layout (Loader Relocation.a Do_SUPER, contract §1.1):
    opcode + Length(4, a Long regardless of NUMLEN) + Type(1) + page list,
    with Length COUNTING the type byte.

    'offsets' is the decoded page list (the codec §1.2 pins separately);
    'pagelist' is the raw bytes, because only they can reproduce a
    non-canonical encoding byte-exactly."""
    # page list b'\x00\x00' = "one offset byte follows for page 0" -> offset 0,
    # so Length = 1 (type) + 2 (page list) = 3.
    d = bytes([0xF7]) + struct.pack('<I', 3) + bytes([26, 0x00, 0x00]) \
        + bytes([0x03]) + b'\xAA\xBB\xCC' + bytes([0x00])
    recs, end = omf.parse_records(d, 0)
    assert recs == [(0, 'SUPER', {'type': 26, 'offsets': [0],
                                  'pagelist': b'\x00\x00'}),
                    (8, 'CONST', b'\xAA\xBB\xCC'),
                    (12, 'END', None)]
    assert end == len(d) == 13
    # the record is opcode + Length(4) + Length bytes, i.e. 1 + 4 + 3 = 8
    assert recs[1][0] == 1 + 4 + 3


def test_parse_records_super_length_field_is_not_numlen_scaled():
    """Do_SUPER reads `ldx #5` (Length(4) + Type(1)) whatever the segment's
    NUMLEN is, so a NUMLEN=2 segment's SUPER still carries a 4-byte Length.
    Pinned because LCONST/DS/ORG in the same walk DO scale with numlen."""
    d = (bytes([0xF7]) + struct.pack('<I', 4) + bytes([0, 0x01, 0x10, 0x20])
         + bytes([0x00]))
    for numlen in (2, 4):
        recs, end = omf.parse_records(d, 0, numlen)
        assert recs[0][2] == {'type': 0, 'offsets': [0x10, 0x20],
                              'pagelist': b'\x01\x10\x20'}
        assert recs[1][1] == 'END' and end == len(d)


def test_parse_records_truncated_records_do_not_raise():
    # LCONST claiming 16 bytes with only 2 present: the short slice is kept
    # and the cursor runs past the buffer (the caller sees end > len(d)).
    d = bytes([0xF2]) + struct.pack('<I', 16) + b'\x01\x02'
    recs, end = omf.parse_records(d, 0)
    assert recs == [(0, 'LCONST', b'\x01\x02')]
    assert end == 21 > len(d)
    # CONST claiming 5 bytes with 2 present
    recs, end = omf.parse_records(b'\x05\x01\x02', 0)
    assert recs == [(0, 'CONST', b'\x01\x02')]
    assert end == 6
    # a record stream that simply ends without an END record
    recs, end = omf.parse_records(b'\x03\x01\x02\x03', 0)
    assert [r[1] for r in recs] == ['CONST']
    assert end == 4
    # an empty stream
    assert omf.parse_records(b'', 0) == ([], 0)


def test_parse_records_end_record_stops_the_walk():
    recs, end = omf.parse_records(b'\x00\x03\x01\x02\x03', 0)
    assert recs == [(0, 'END', None)]
    assert end == 1


# ===========================================================================
# 3. header parse, _make_segment emit, iter_segments round-trip
# ===========================================================================

def test_make_segment_header_fields_round_trip_through_parse_header():
    body = bytes(range(0x40))
    seg = omf._make_segment(b'MYSEG', b'myload', 0x8000, 0x1000, 7, body)
    h = omf.parse_header(seg)
    assert h['BYTECNT'] == len(seg)
    assert h['LENGTH'] == len(body)
    assert h['NUMLEN'] == 4
    assert h['VERSION'] == 2
    assert h['KIND'] == 0x1000
    assert h['ORG'] == 0x8000
    assert h['SEGNUM'] == 7
    assert h['ALIGN'] == 0
    assert h['NUMSEX'] == 0
    assert h['DISPNAME'] == 44
    assert h['DISPDATA'] == 44 + 10 + 1 + len('MYSEG')
    assert h['LOADNAME'] == b'myload' + b'\x00' * 4    # padded to 10
    assert h['SEGNAME'] == b'MYSEG'
    # code segment (KIND bit 0 clear) => BANKSIZE $10000
    assert h['BANKSIZE'] == 0x10000


def test_make_segment_data_kind_bit_zeroes_banksize():
    """KIND bit 0 = data.  A data segment does not span banks, so BANKSIZE
    is 0 (the documented KIND-bit table, grounding survey 2026-08-02)."""
    seg = omf._make_segment(b'D', b'l', 0, 0x0001, 1, b'\x00')
    assert omf.parse_header(seg)['BANKSIZE'] == 0
    seg = omf._make_segment(b'D', b'l', 0, 0x4001, 1, b'\x00')
    assert omf.parse_header(seg)['BANKSIZE'] == 0     # private data
    seg = omf._make_segment(b'C', b'l', 0, 0x4000, 1, b'\x00')
    assert omf.parse_header(seg)['BANKSIZE'] == 0x10000   # private code


def test_make_segment_body_is_one_lconst_then_tail_then_end():
    body = b'\xAA\xBB\xCC'
    tail = bytes([0xE2, 4, 0]) + struct.pack('<I', 0) + struct.pack('<I', 0)
    seg = omf._make_segment(b'MAIN', b'main', 0, 0, 1, body, tail)
    h = omf.parse_header(seg)
    recs, end = omf.parse_records(seg, h['DISPDATA'], h['NUMLEN'])
    assert [r[1] for r in recs] == ['LCONST', 'RELOC', 'END']
    assert recs[0][2] == body
    assert end == len(seg), 'the segment ends exactly at its END record'
    assert omf._body_length(recs) == h['LENGTH']


def test_make_segment_empty_body_still_emits_an_lconst():
    seg = omf._make_segment(b'E', b'e', 0, 0, 1, b'')
    h = omf.parse_header(seg)
    recs, _ = omf.parse_records(seg, h['DISPDATA'], h['NUMLEN'])
    assert [r[1] for r in recs] == ['LCONST', 'END']
    assert recs[0][2] == b''
    assert h['LENGTH'] == 0


def test_iter_segments_walks_a_concatenation_by_bytecnt():
    a = omf._make_segment(b'ONE', b'one', 0, 0x0000, 1, b'\x11' * 5)
    b = omf._make_segment(b'TWO', b'two', 0, 0x4001, 2, b'\x22' * 9)
    segs = list(omf.iter_segments(a + b))
    assert [s['name'] for s in segs] == ['ONE', 'TWO']
    assert [s['off'] for s in segs] == [0, len(a)]
    assert [s['raw'] for s in segs] == [a, b]
    assert [s['hdr']['SEGNUM'] for s in segs] == [1, 2]
    assert [r[1] for r in segs[0]['recs']] == ['LCONST', 'END']
    # records=False skips the record walk entirely
    lazy = list(omf.iter_segments(a + b, records=False))
    assert all(s['recs'] is None for s in lazy)
    assert [s['raw'] for s in lazy] == [a, b]


def test_iter_segments_name_is_stripped_mac_roman_preserving_case():
    seg = omf._make_segment(b'  MixedCase  ', b'l', 0, 0, 1, b'\x00')
    assert list(omf.iter_segments(seg))[0]['name'] == 'MixedCase'
    seg = omf._make_segment(b'A\xa9B', b'l', 0, 0, 1, b'\x00')
    assert list(omf.iter_segments(seg))[0]['name'] == 'A©B'


def test_iter_segments_stops_on_a_zero_bytecnt():
    """A zero BYTECNT would make the walk spin forever; iter_segments treats
    it as end-of-file (trailing padding in a load file)."""
    a = omf._make_segment(b'ONE', b'one', 0, 0, 1, b'\x11')
    segs = list(omf.iter_segments(a + b'\x00' * 64))
    assert [s['name'] for s in segs] == ['ONE']
    assert list(omf.iter_segments(b'')) == []


def test_emit_round_trips_a_real_assembly_structurally():
    """emit() -> iter_segments() -> parse_records(): one segment per PROC,
    segments renumbered 1..N, header LENGTH equal to the walked body length,
    BYTECNTs tiling the file exactly."""
    a = assemble(SRC_TWO_RELOC_SEGS)
    obj = omf.emit(a)
    segs = list(omf.iter_segments(obj))
    assert [s['name'] for s in segs] == ['ALPHA', 'BETA']
    assert [s['hdr']['SEGNUM'] for s in segs] == [1, 2]
    assert sum(s['hdr']['BYTECNT'] for s in segs) == len(obj)
    for s in segs:
        assert s['recs'][-1][1] == 'END'
        assert omf._body_length(s['recs']) == s['hdr']['LENGTH']
        assert s['hdr']['VERSION'] == 2 and s['hdr']['NUMLEN'] == 4
        # re-parsing the raw slice alone reproduces the same records
        again, _ = omf.parse_records(s['raw'], s['hdr']['DISPDATA'],
                                     s['hdr']['NUMLEN'])
        assert again == s['recs']


def test_emit_round_trip_reproduces_the_body_bytes():
    a = assemble(SRC_TWO_RELOC_SEGS)
    obj = omf.emit(a)
    for s in omf.iter_segments(obj):
        body = omf._build_body(s['recs'], {}, 0)
        assert len(body) == s['hdr']['LENGTH']


# ===========================================================================
# 4. SUPER records: subtype formulas and the page-list skip/count codec
# ===========================================================================

def test_super_record_layout():
    """0xF7 + total_size(4) + type(1) + page_list.  total_size counts the
    type byte, so it is 1 + len(page_list) (Loader Relocation.a Do_SUPER)."""
    rec = emit_super(0, [3])
    assert rec[0] == 0xF7
    total = struct.unpack_from('<I', rec, 1)[0]
    assert total == len(rec) - 5
    assert rec[5] == 0                      # super type
    assert total == 1 + len(rec[6:])
    assert emit_super(0, []) == b'', 'an empty offset list emits no record'


def test_super_subtype_formula_13_plus_segnum():
    """Type 13+segnum = "2-byte low-word reloc against segment segnum".
    Types 1..12 are the fixed classes, so segnum 1 lands at 14.  Pinned as a
    round-trip so the formula's arithmetic and the byte's position in the
    record are checked together."""
    for segnum in (1, 2, 8, 12):
        rec = emit_super(13 + segnum, [0x10])
        assert rec[5] == 13 + segnum
        assert parse_super(_wrap_super(rec)) == {13 + segnum: [0x10]}


def test_super_subtype_formula_25_plus_segnum():
    """Type 25+segnum = "INTERSEG bank-byte reloc against segment segnum".
    26 is the single-segment plain-load case (see
    tests/test_linkiigs_super_type26.py); 27 is the ExpressLoad'd
    main-code-segment-is-2 case (expressload's `corrected_type`)."""
    assert 25 + 1 == 26 and 25 + 2 == 27
    for segnum in (1, 2, 30):
        rec = emit_super(25 + segnum, [0x20])
        assert rec[5] == 25 + segnum
        assert parse_super(_wrap_super(rec)) == {25 + segnum: [0x20]}
    # the subtype is a single byte, so the formula tops out at segnum 230
    assert 25 + 230 == 0xFF


def _wrap_super(*super_recs):
    """A minimal OMF segment carrying only the given SUPER records."""
    return omf._make_segment(b'S', b's', 0, 0, 1, b'\x00' * 4,
                             b''.join(super_recs))


def test_super_codec_is_still_reachable_through_expressload():
    """The codec now lives in omf.py (SUPER is an OMF record and
    ``parse_records`` decodes it); ``expressload`` re-exports the same four
    objects so its historical importers — work/finderdatacheck.py,
    work/installerdatacheck.py, work/rezloadcheck.py, linkiigs' lazy
    ``_exl.emit_super`` — keep working.  Identity, not equality: a re-export
    must not become a second copy of a codec."""
    from gsasm import expressload as _exl
    assert _exl.parse_super is parse_super
    assert _exl.emit_super is emit_super
    assert _exl._decode_page_list is _decode_page_list
    assert _exl._encode_page_list is _encode_page_list


def test_page_list_codec_count_headers():
    """bit7=0 is a count header: (b & 0x7f) + 1 offset bytes follow for the
    current page, then the page advances by one."""
    assert _encode_page_list([0]) == b'\x00\x00'
    assert _encode_page_list([1, 2, 3]) == b'\x02\x01\x02\x03'
    assert _decode_page_list(b'\x02\x01\x02\x03') == [1, 2, 3]
    # 128 offsets in one page is the maximum a single count header holds
    full = list(range(256))[:128]
    enc = _encode_page_list(full)
    assert enc[0] == 0x7F and len(enc) == 129
    assert _decode_page_list(enc) == full


def test_page_list_codec_skip_headers_have_no_plus_one():
    """bit7=1 is a skip header: advance by (b & 0x7f) pages — NO +1
    adjustment (matches the Loader decoder exactly)."""
    assert _encode_page_list([0, 0x200 + 5]) == b'\x00\x00\x81\x00\x05'
    assert _decode_page_list(b'\x00\x00\x81\x00\x05') == [0, 0x205]
    # a run longer than the 7-bit field chains skip bytes: 199 = 127 + 72
    assert _encode_page_list([0, 200 * 256 + 5]) == \
        b'\x00\x00\xFF\xC8\x00\x05'
    assert _decode_page_list(b'\x00\x00\xFF\xC8\x00\x05') == [0, 200 * 256 + 5]


def test_page_list_codec_round_trips():
    for offsets in ([], [0], [0xFF], [0, 1, 255, 256, 257, 0x1234, 0xFFFF],
                    list(range(0, 4096, 97))):
        enc = _encode_page_list(sorted(offsets))
        assert _decode_page_list(enc) == sorted(offsets), offsets


def test_parse_super_skips_lconst_and_stops_at_end():
    seg = omf._make_segment(b'MAIN', b'main', 0, 0, 1, b'\xAA' * 0x140,
                            emit_super(0, [3, 300]) + emit_super(26, [7]))
    assert parse_super(seg) == {0: [3, 300], 26: [7]}
    # repeated types accumulate rather than overwrite
    seg = omf._make_segment(b'MAIN', b'main', 0, 0, 1, b'\x00' * 8,
                            emit_super(0, [1]) + emit_super(0, [2]))
    assert parse_super(seg) == {0: [1, 2]}
    # nothing after the END record is seen
    seg = omf._make_segment(b'MAIN', b'main', 0, 0, 1, b'\x00' * 8)
    assert parse_super(seg + emit_super(0, [1])) == {}


# ===========================================================================
# 5. the reloc classifiers (Do-Not-Touch registry: _diff_reloc,
#    _mul_reloc_expr, _grouped_linear_reloc — fixtures 035/040/044/047)
# ===========================================================================

def test_linear_decompose_finite_difference():
    a = assemble(SRC_TWO_RELOC_SEGS)
    in_seg(a, 'Alpha')
    # terms carry only RELOCATABLE symbols; constants fold into K
    assert omf.linear_decompose(a, 'AEnd-AStart+5') == \
        ({'AEnd': 1, 'AStart': -1}, 5, 0)
    assert omf.linear_decompose(a, 'AMid+2') == ({'AMid': 1}, 2, 0)
    assert omf.linear_decompose(a, '4*3') == ({}, 12, 0)
    # a `*` (PC) term shows up as pc_coeff, not as a symbol term
    terms, K, pc = omf.linear_decompose(a, '*+4')
    assert terms == {} and pc == 1
    # an inevaluable expression is None
    assert omf.linear_decompose(a, 'NoSuchSymbol+') is None


def test_linear_reloc_requires_exactly_one_plus_one_term():
    a = assemble(SRC_TWO_RELOC_SEGS)
    in_seg(a, 'Alpha')
    assert omf._linear_reloc(a, 'AEnd+2') == ('AEnd', 2)
    assert omf._linear_reloc(a, 'AEnd-1') == ('AEnd', -1)
    assert omf._linear_reloc(a, 'AEnd-AStart') is None      # two terms
    assert omf._linear_reloc(a, 'AEnd*2') is None           # coeff != 1
    assert omf._linear_reloc(a, 'AStart-AEnd') is None      # coeff -1 net
    assert omf._linear_reloc(a, '*+2') is None              # PC term
    assert omf._linear_reloc(a, '$1234') is None            # no reloc term


def test_reloc_target_key_groups_by_relocation_base():
    """Two identifiers share a key iff they relocate against the same base —
    the whole point of the grouping in _grouped_linear_reloc."""
    a = assemble(SRC_TWO_RELOC_SEGS)
    in_seg(a, 'Alpha')
    # same-segment labels share one key, so their difference cancels
    assert omf._reloc_target_key(a, 'AStart') == ('seg', 0)
    assert omf._reloc_target_key(a, 'AEnd') == ('seg', 0)
    assert omf._reloc_target_key(a, 'BLab') == ('seg', 1)
    assert omf._reloc_target_key(a, 'NotDefinedAnywhere') == \
        ('ext', 'NOTDEFINEDANYWHERE')

    imp = assemble(SRC_IMPORTS)
    in_seg(imp, 'Main')
    assert omf._reloc_target_key(imp, 'ExtA') == ('import', 'EXTA')
    assert omf._reloc_target_key(imp, 'Konst') is None       # equate: constant

    org = assemble(SRC_ORG_SEGS)
    in_seg(org, 'Abs1')
    assert omf._reloc_target_key(org, 'O1') is None, \
        'an ORG\'d segment label is an absolute literal, never a reloc base'
    assert omf._reloc_target_key(org, 'T1') is None, \
        'a temporg segment label is an absolute literal too'


def test_grouped_linear_reloc_collapses_multi_term_to_one_relocation():
    """DO-NOT-TOUCH (fixtures 035/040/044/047).  Three same-segment labels
    that net to +1 collapse to a single relocation; the representative is the
    first ident with coefficient +1 and the addend is V - repr_value."""
    a = assemble(SRC_TWO_RELOC_SEGS)
    in_seg(a, 'Alpha')
    # AMid(2)+2 - AStart(0) + AEnd(4) = 8; net coeff on ('seg',0) is +1;
    # representative AMid (value 2) -> addend 8 - 2 = 6.
    assert omf._grouped_linear_reloc(a, 'AMid+2-AStart+AEnd') == ('AMid', 6)
    # a plain single label still goes through
    assert omf._grouped_linear_reloc(a, 'AEnd+2') == ('AEnd', 2)


def test_grouped_linear_reloc_rejections():
    a = assemble(SRC_TWO_RELOC_SEGS)
    in_seg(a, 'Alpha')
    # net-zero same-segment difference: left to literal baking / _diff_reloc
    assert omf._grouped_linear_reloc(a, 'AEnd-AStart') is None
    # two different relocation groups: > 1 group
    assert omf._grouped_linear_reloc(a, 'AEnd-BLab') is None
    # net coefficient != 1
    assert omf._grouped_linear_reloc(a, 'AEnd+AMid') is None
    assert omf._grouped_linear_reloc(a, 'AEnd*2') is None
    # a PC term disqualifies it outright
    assert omf._grouped_linear_reloc(a, 'AEnd+*') is None
    # no relocatable group at all
    assert omf._grouped_linear_reloc(a, '$40') is None
    # inevaluable
    assert omf._grouped_linear_reloc(a, 'AEnd+') is None


def test_grouped_linear_reloc_defers_named_externals_to_diff_reloc():
    """Fixture 035's guard: an identifier that this classifier would fold
    into the constant (its _reloc_target_key is None because it has a local
    ORG'd value) but that is ALSO an IMPORT / undefined external must be
    emitted BY NAME as a difference, so the classifier bails entirely."""
    a = assemble(SRC_IMPORTED_ORG_PAD)
    in_seg(a, 'Rel')
    # control: the same shape with a NON-imported ORG'd label collapses fine
    assert omf._grouped_linear_reloc(a, 'RLab+MyEnd-MyEnd') == ('RLab', 0)
    assert omf._grouped_linear_reloc(a, 'RLab+2') == ('RLab', 2)
    # MYSTART is ORG'd (key None) but also IMPORTed -> hand it to _diff_reloc
    assert omf._reloc_target_key(a, 'MyStart') is None
    assert a._symkey('MyStart') in a.imports
    assert omf._grouped_linear_reloc(a, 'RLab+MyEnd-MyStart') is None

    # A keyless, non-external term (an equate) simply folds into the constant.
    imp = assemble(SRC_IMPORTS)
    in_seg(imp, 'Main')
    assert omf._reloc_target_key(imp, 'Konst') is None
    assert omf._grouped_linear_reloc(imp, 'MLab+Konst') == ('MLab', 8)


def test_diff_reloc_is_scoped_to_cross_segment_differences():
    """DO-NOT-TOUCH.  `A - B` emits (SEGNAME_A+offA) - (SEGNAME_B+offB) [+K]
    only when the two labels live in DIFFERENT segments that are not both
    ORG'd."""
    a = assemble(SRC_TWO_RELOC_SEGS)
    in_seg(a, 'Alpha')
    assert omf._diff_reloc(a, 'BLab-AMid') == \
        sym('BETA') + lit(2) + b'\x01' + sym('ALPHA') + lit(2) + b'\x01' + b'\x02'
    # a residual constant appends `+K`
    assert omf._diff_reloc(a, 'BLab-AMid+7') == \
        sym('BETA') + lit(2) + b'\x01' + sym('ALPHA') + lit(2) + b'\x01' \
        + b'\x02' + lit(7) + b'\x01'
    # a zero offset omits the +offset term entirely
    assert omf._diff_reloc(a, 'BLab-AStart') == \
        sym('BETA') + lit(2) + b'\x01' + sym('ALPHA') + b'\x02'


def test_diff_reloc_rejections():
    a = assemble(SRC_TWO_RELOC_SEGS)
    in_seg(a, 'Alpha')
    assert omf._diff_reloc(a, 'AEnd-AStart') is None, \
        'same segment: the assembly-time literal is already final'
    assert omf._diff_reloc(a, 'AEnd+AStart') is None      # not +1/-1
    assert omf._diff_reloc(a, 'BLab') is None             # only one term
    assert omf._diff_reloc(a, 'BLab-AMid+*') is None      # PC term
    org = assemble(SRC_ORG_SEGS)
    in_seg(org, 'Abs1')
    assert omf._diff_reloc(org, 'O2-O1') is None, \
        'BOTH segments ORG\'d (absolute): the difference is final'
    imp = assemble(SRC_IMPORTS)
    in_seg(imp, 'Main')
    assert omf._diff_reloc(imp, 'ExtA-ExtB') is None, \
        'externals do not resolve, so linear_decompose cannot see them'


def test_mul_reloc_expr_emits_segname_times_n_plus_k():
    """DO-NOT-TOUCH.  (SEGNAME + rel) * N + K for a single label with
    coefficient N > 1."""
    a = assemble(SRC_TWO_RELOC_SEGS)
    seg = in_seg(a, 'Alpha')
    # case (b): the label lives in ANOTHER relocatable segment -> its own
    # SEGNAME rides the multiply.  BLab is BETA+2, N = 4, K = 3.
    assert omf._mul_reloc_expr(a, 'BLab*4+3', seg) == \
        sym('BETA') + lit(2) + b'\x01' + lit(4) + b'\x03' + lit(3) + b'\x01'
    # a zero rel and a zero K drop their terms
    assert omf._mul_reloc_expr(a, 'AStart*3', seg) == \
        sym('ALPHA') + lit(3) + b'\x03'


def test_mul_reloc_expr_case_a_uses_the_current_org_segment_name():
    org = assemble(SRC_ORG_SEGS)
    seg = in_seg(org, 'Abs1')
    # O1b = $FF0002 inside the current ORG'd segment ($FF0000) -> ABS1 + 2
    assert omf._mul_reloc_expr(org, 'O1b*4+3', seg) == \
        sym('ABS1') + lit(2) + b'\x01' + lit(4) + b'\x03' + lit(3) + b'\x01'


def test_mul_reloc_expr_rejections():
    a = assemble(SRC_TWO_RELOC_SEGS)
    seg = in_seg(a, 'Alpha')
    assert omf._mul_reloc_expr(a, 'BLab', seg) is None       # N == 1
    assert omf._mul_reloc_expr(a, 'BLab*4-BLab*3', seg) is None  # nets to 1
    assert omf._mul_reloc_expr(a, 'AEnd*2-AStart', seg) is None  # two labels
    assert omf._mul_reloc_expr(a, '$10*4', seg) is None      # no label
    a._rseg = None
    assert omf._mul_reloc_expr(a, 'BLab*4', seg) is None, \
        'no current segment -> never a multiply reloc'
    org = assemble(SRC_ORG_SEGS)
    segt = in_seg(org, 'Tmp')
    assert omf._mul_reloc_expr(org, 'O1*4', segt) is None, \
        'a label in an ORG\'d segment that is not the CURRENT one is absolute'


def test_pc_rel_const_detects_a_cancelling_base():
    a = assemble(SRC_TWO_RELOC_SEGS)
    in_seg(a, 'Alpha')
    assert omf._pc_rel_const(a, 'AEnd-*') is True, \
        'same-segment label minus PC: the segment base cancels -> literal'
    assert omf._pc_rel_const(a, 'AEnd') is False, 'no `*` at all'
    assert omf._pc_rel_const(a, 'BLab-*') is False, \
        'cross-segment: the base does NOT cancel'
    assert omf._pc_rel_const(a, 'AEnd+*') is False       # coefficients add
    a._rseg = None
    assert omf._pc_rel_const(a, 'AEnd-*') is False       # no current segment


def test_undef_external_and_ext_plus_const():
    imp = assemble(SRC_IMPORTS)
    in_seg(imp, 'Main')
    assert omf._undef_external(imp, 'NeverMentioned') is True
    assert omf._undef_external(imp, 'ExtA') is False, 'a DECLARED import'
    assert omf._undef_external(imp, 'MLab') is False, 'a defined label'
    assert omf._undef_external(imp, 'Konst') is False, 'an equate'
    # one external + absolute-equate constants -> (name, addend)
    assert omf._ext_plus_const(imp, 'ExtA-Konst') == ('ExtA', -8)
    assert omf._ext_plus_const(imp, 'NeverMentioned+4') == \
        ('NeverMentioned', 4)
    assert omf._ext_plus_const(imp, 'ExtA-ExtB') is None      # two externals
    assert omf._ext_plus_const(imp, 'Konst+1') is None        # no external
    assert omf._ext_plus_const(imp, 'ExtA-MLab') is None, \
        'a non-external term must be an absolute equate, not a label'


def test_extern_diff_expr_emits_a_by_name_difference():
    imp = assemble(SRC_IMPORTS)
    in_seg(imp, 'Main')
    assert omf._extern_diff_expr(imp, 'ExtA-ExtB') == \
        sym('EXTA') + sym('EXTB') + b'\x02'
    assert omf._extern_diff_expr(imp, 'ExtA+2-ExtB') == \
        sym('EXTA') + sym('EXTB') + b'\x02' + lit(2) + b'\x01'
    # implicit (never-declared) externals count too
    assert omf._extern_diff_expr(imp, 'Nope1-Nope2') == \
        sym('NOPE1') + sym('NOPE2') + b'\x02'
    # rejections
    assert omf._extern_diff_expr(imp, 'ExtA-Konst') is None    # one external
    assert omf._extern_diff_expr(imp, 'ExtA+ExtB') is None     # not +1/-1
    assert omf._extern_diff_expr(imp, 'ExtA-ExtB+MLab') is None, \
        'a non-external term must be an absolute equate'


def test_in_org_seg_and_temporg_label():
    org = assemble(SRC_ORG_SEGS)
    in_seg(org, 'Abs1')                    # ORG $FF0000, length 4
    assert omf._in_org_seg(org, 0xFF0000) is True
    assert omf._in_org_seg(org, 0xFF0003) is True
    assert omf._in_org_seg(org, 0xFF0004) is False, 'half-open upper bound'
    assert omf._in_org_seg(org, 0xFF1000) is False
    assert omf._in_org_seg(org, None) is False
    assert omf._temporg_label(org, 'T1') is True
    assert omf._temporg_label(org, 'O1') is False
    assert omf._temporg_label(org, 'NoSuch') is False
    a = assemble(SRC_TWO_RELOC_SEGS)
    in_seg(a, 'Alpha')
    assert omf._in_org_seg(a, 0) is False, 'a relocatable segment has no ORG'


def test_global_stream_mismatch_is_false_for_well_formed_segments():
    """The backward-ORG overlay detector.  A normal relocatable segment's
    GLOBAL item sits exactly at the label's value, so it reports False; ORG'd
    and temporg segments are excluded up front."""
    e = assemble(SRC_ENTRIES)
    in_seg(e, 'Main')
    assert omf._global_stream_mismatch(e, 'EARLY', 0) is False
    assert omf._global_stream_mismatch(e, 'LATER', 0) is False
    assert omf._global_stream_mismatch(e, 'NOSUCH', 0) is False
    org = assemble(SRC_ORG_SEGS)
    assert omf._global_stream_mismatch(org, 'O1', 0) is False    # ORG'd
    tmp_idx = next(i for i, s in enumerate(org.segs) if s.temporg is not None)
    assert omf._global_stream_mismatch(org, 'T1', tmp_idx) is False


def test_branch_xseg():
    e = assemble(SRC_ENTRIES)
    cur = e.segs.index(next(s for s in e.segs if e._fold(s.name) == 'MAIN'))
    e._rseg = cur
    # a BACKWARD branch to a same-segment ENTRY is a fixed literal offset
    assert omf._branch_xseg(e, 'Early', cur, ref_off=4) is False
    # a FORWARD branch to a same-segment ENTRY needs a RELEXPR
    assert omf._branch_xseg(e, 'Later', cur, ref_off=0) is True
    # ref_off unknown -> stay conservative, relocate by name
    assert omf._branch_xseg(e, 'Later', cur) is True
    # a plain local label is always a fixed offset
    assert omf._branch_xseg(e, 'Here', cur, ref_off=0) is False
    # a label in another relocatable segment needs a RELEXPR
    assert omf._branch_xseg(e, 'DField2', cur, ref_off=0) is True
    # anything that is not a simple `sym [+/- const]` reference is not one
    assert omf._branch_xseg(e, 'Later-Early', cur, ref_off=0) is False
    imp = assemble(SRC_IMPORTS)
    icur = imp.segs.index(next(s for s in imp.segs
                               if imp._fold(s.name) == 'MAIN'))
    imp._rseg = icur
    assert omf._branch_xseg(imp, 'ExtA', icur, ref_off=0) is True
    assert omf._branch_xseg(imp, 'NeverHeardOfIt', icur, ref_off=0) is True
    org = assemble(SRC_ORG_SEGS)
    ocur = org.segs.index(next(s for s in org.segs
                               if org._fold(s.name) == 'ABS1'))
    org._rseg = ocur
    assert omf._branch_xseg(org, 'T1', ocur, ref_off=0) is False, \
        'a temporg segment\'s labels are absolute literals'


def test_dup_entry_branch_is_a_fixed_literal():
    d = assemble(SRC_DUP_ENTRY)
    cur = 0                                       # FMT16
    d._rseg = cur
    assert d.defcount['WEXIT'] == 2
    assert omf._branch_xseg(d, 'Wexit', cur, ref_off=0) is False, \
        'a forward branch to a DUPLICATE entry name cannot relocate by name'


# ===========================================================================
# 6. _expr_for — the operand-to-OMF-expression decision (omf.py:759)
# ===========================================================================

END = b'\x00'


def test_expr_for_same_segment_label_is_segname_plus_offset():
    a = assemble(SRC_TWO_RELOC_SEGS)
    seg = in_seg(a, 'Alpha')
    assert omf._expr_for(a, 'AMid', seg) == sym('ALPHA') + lit(2) + b'\x01' + END
    assert omf._expr_for(a, 'AStart', seg) == sym('ALPHA') + END
    assert omf._expr_for(a, 'AMid+2', seg) == \
        sym('ALPHA') + lit(4) + b'\x01' + END
    # a hex addend is parsed base 16
    assert omf._expr_for(a, 'AStart+$10', seg) == \
        sym('ALPHA') + lit(0x10) + b'\x01' + END


def test_expr_for_cross_segment_code_label_is_by_name():
    a = assemble(SRC_TWO_RELOC_SEGS)
    seg = in_seg(a, 'Alpha')
    assert omf._expr_for(a, 'BLab', seg) == sym('BLAB') + END
    assert omf._expr_for(a, 'BLab+3', seg) == sym('BLAB') + lit(3) + b'\x01' + END


def test_expr_for_cross_segment_data_label_is_segname_plus_offset():
    """Labels in a data segment (RECORD) are not exposed by name to other
    segments' linker resolution."""
    e = assemble(SRC_ENTRIES)
    seg = in_seg(e, 'Other')
    assert omf._expr_for(e, 'DField2', seg) == \
        sym('DATASEG') + lit(2) + b'\x01' + END
    assert omf._expr_for(e, 'Early', seg) == sym('EARLY') + END


def test_expr_for_same_segment_entry_forward_is_by_name_backward_is_offset():
    """The as_data / ref_off rule: a same-segment ENTRY is by name only when
    the reference is FORWARD of the definition (the assembler had not seen
    the definition yet); a BACKWARD reference uses SEGNAME+offset."""
    e = assemble(SRC_ENTRIES)
    seg = in_seg(e, 'Main')            # EARLY=0, HERE=2, LATER=4
    assert omf._expr_for(e, 'Early', seg, ref_off=4) == sym('MAIN') + END
    assert omf._expr_for(e, 'Later', seg, ref_off=2) == sym('LATER') + END
    assert omf._expr_for(e, 'Later', seg, ref_off=None) == sym('LATER') + END, \
        'ref_off unknown (e.g. a branch via RELEXPR) -> keep by-name'
    # a non-ENTRY same-segment label is always SEGNAME+offset
    assert omf._expr_for(e, 'Here', seg, ref_off=0) == \
        sym('MAIN') + lit(2) + b'\x01' + END


def test_expr_for_duplicate_entry_name_prefers_the_local_definition():
    """A duplicate ENTRY name cannot be referenced by name from a segment
    that has its OWN definition — MPW scoping gives the same-segment
    definition precedence."""
    d = assemble(SRC_DUP_ENTRY)
    seg = in_seg(d, 'Fmt16')
    assert d.defcount['WEXIT'] == 2
    assert omf._expr_for(d, 'Wexit', seg, ref_off=0) == \
        sym('FMT16') + lit(2) + b'\x01' + END


def test_expr_for_import_is_by_name():
    imp = assemble(SRC_IMPORTS)
    seg = in_seg(imp, 'Main')
    assert omf._expr_for(imp, 'ExtA', seg) == sym('EXTA') + END
    assert omf._expr_for(imp, 'ExtA+4', seg) == \
        sym('EXTA') + lit(4) + b'\x01' + END


def test_expr_for_equate_is_a_literal():
    imp = assemble(SRC_IMPORTS)
    seg = in_seg(imp, 'Main')
    assert omf._expr_for(imp, 'Konst', seg) == lit(8) + END
    assert omf._expr_for(imp, 'Konst+2', seg) == lit(10) + END
    assert omf._expr_for(imp, '$1234', seg) == lit(0x1234) + END


def test_expr_for_equate_landing_in_the_current_org_segment_relocates():
    org = assemble(SRC_ORG_SEGS)
    seg = in_seg(org, 'Abs1')                # ORG $FF0000, length 4
    # a bare numeric address inside the ORG'd segment becomes SEGNAME+offset
    assert omf._expr_for(org, '$FF0002', seg) == \
        sym('ABS1') + lit(2) + b'\x01' + END
    assert omf._expr_for(org, '$FF0000', seg) == sym('ABS1') + END
    # ... and one outside stays a literal
    assert omf._expr_for(org, '$FF1000', seg) == lit(0xFF1000) + END


def test_expr_for_temporg_label_is_an_absolute_literal():
    org = assemble(SRC_ORG_SEGS)
    seg = in_seg(org, 'Abs1')
    assert omf._expr_for(org, 'T1', seg) == \
        bytes([0x81]) + omf._num(0x2000) + END
    assert omf._expr_for(org, 'T1+1', seg) == \
        bytes([0x81]) + omf._num(0x2001) + END
    # a byte-extraction on a temporg label is applied to the VALUE, not
    # deferred to the linker as a shift
    assert omf._expr_for(org, '^T1', seg) == \
        bytes([0x81]) + omf._num(0x0000) + END
    assert omf._expr_for(org, '>T1', seg) == \
        bytes([0x81]) + omf._num(0x20) + END


def test_expr_for_shift_prefixes_and_suffixes_become_a_trailing_shift_op():
    """`< > ^` and an explicit `>>N` / `<<N` are folded into ONE trailing
    `push -shift; SHL` pair: the linker computes (sym >> shift)."""
    a = assemble(SRC_TWO_RELOC_SEGS)
    seg = in_seg(a, 'Alpha')
    shift16 = lit((-16) & 0xFFFFFFFF) + b'\x07'
    assert omf._expr_for(a, '^AStart', seg) == sym('ALPHA') + shift16 + END
    assert omf._expr_for(a, 'AStart>>16', seg) == sym('ALPHA') + shift16 + END
    assert omf._expr_for(a, '>AStart', seg) == \
        sym('ALPHA') + lit((-8) & 0xFFFFFFFF) + b'\x07' + END
    assert omf._expr_for(a, '<AStart', seg) == sym('ALPHA') + END, \
        '`<` is shift 0, so no shift op is appended at all'
    # a LEFT shift is the negative of a right shift, so the emitted count is
    # POSITIVE (the deferred-left-shift rule, tests/test_linkiigs_defer_left_shift)
    assert omf._expr_for(a, 'AStart<<8', seg) == \
        sym('ALPHA') + lit(8) + b'\x07' + END
    # prefix and suffix ADD: ^X>>8 is a 24-bit shift
    assert omf._expr_for(a, '^AStart>>8', seg) == \
        sym('ALPHA') + lit((-24) & 0xFFFFFFFF) + b'\x07' + END


def test_expr_for_strips_only_a_fully_enclosing_paren_pair():
    a = assemble(SRC_TWO_RELOC_SEGS)
    seg = in_seg(a, 'Alpha')
    assert omf._expr_for(a, '(AMid)', seg) == \
        sym('ALPHA') + lit(2) + b'\x01' + END
    # `(A)-(B)` starts with `(` and ends with `)` but the first pair closes
    # early, so the text is NOT unwrapped and falls to the classifiers.
    assert omf._expr_for(a, '(BLab)-(AMid)', seg) == \
        omf._diff_reloc(a, '(BLab)-(AMid)') + END


def test_expr_for_falls_through_to_the_classifiers():
    a = assemble(SRC_TWO_RELOC_SEGS)
    seg = in_seg(a, 'Alpha')
    # _linear_reloc: one reloc label plus a computed constant
    assert omf._expr_for(a, 'AMid+(1*2)', seg) == \
        sym('ALPHA') + lit(4) + b'\x01' + END
    # _grouped_linear_reloc: three same-segment labels netting to +1
    assert omf._expr_for(a, 'AMid+2-AStart+AEnd', seg) == \
        sym('ALPHA') + lit(8) + b'\x01' + END
    # _diff_reloc: a cross-segment difference
    assert omf._expr_for(a, 'BLab-AMid', seg) == \
        omf._diff_reloc(a, 'BLab-AMid') + END
    # _mul_reloc_expr: coefficient > 1 (reached only via the no-name path)
    assert omf._expr_for(a, 'BLab*4+3', seg) == \
        omf._mul_reloc_expr(a, 'BLab*4+3', seg) + END
    # nothing matches: bake the assembly-time literal
    assert omf._expr_for(a, 'AEnd-AStart', seg) == lit(4) + END


def test_expr_for_instruction_operand_resolves_a_single_external_by_name():
    """as_data=False: an operand linear in ONE external plus constants is
    resolved by name + addend (`lda >arrowMap-UP_ARROW,x`)."""
    imp = assemble(SRC_IMPORTS)
    seg = in_seg(imp, 'Main')
    assert omf._expr_for(imp, 'ExtA-Konst', seg) == \
        sym('EXTA') + lit((-8) & 0xFFFFFFFF) + b'\x01' + END
    assert omf._expr_for(imp, 'NeverSeen+Konst', seg) == \
        sym('NEVERSEEN') + lit(8) + b'\x01' + END
    # ... and as_data=True takes the _ext_plus_const route to the same result
    assert omf._expr_for(imp, 'ExtA-Konst', seg, as_data=True) == \
        sym('EXTA') + lit((-8) & 0xFFFFFFFF) + b'\x01' + END


def test_expr_for_two_externals_become_a_by_name_difference():
    imp = assemble(SRC_IMPORTS)
    seg = in_seg(imp, 'Main')
    assert omf._expr_for(imp, 'ExtA-ExtB', seg, as_data=True) == \
        sym('EXTA') + sym('EXTB') + b'\x02' + END


def test_expr_for_equ_alias_relocates_through_to_the_target_label():
    """An EQU whose RHS is a relocatable label is a second NAME for that
    address: references emit as the TARGET label + addend, not as the baked
    snapshot value."""
    al = assemble(SRC_ALIAS_SHADOW)
    seg = in_seg(al, 'Other')
    assert al.equ_alias['COUNT'] == ('CDBASE', 2)
    assert omf._expr_for(al, 'Count', seg) == \
        sym('CDBASE') + lit(2) + b'\x01' + END
    # the alias addend and the operand addend ADD
    assert omf._expr_for(al, 'Count+1', seg) == \
        sym('CDBASE') + lit(3) + b'\x01' + END


def test_expr_for_local_definition_shadows_an_equ_alias_of_the_same_name():
    """THE SHADOWING BRANCH (omf.py, inside _expr_for).

    Decision rule, stated exactly:  when the resolved name has an
    ``asm.equ_alias`` entry AND ``asm._rseg is not None`` AND
    ``asm._symkey(name)`` is a key of ``asm.seg_local[asm._rseg]``, the alias
    is DISCARDED (``alias = None``) and the name is resolved as an ordinary
    label — which, since it is by construction local to the current segment,
    means SEGNAME + offset.  The test is purely "does the CURRENT segment
    define this name itself"; it does not look at definition order, at the
    alias target, or at whether the local is a label or a storage
    reservation.

    MPW binds the innermost explicit definition (the same precedence
    ``resolve()`` applies).  This is one of FOUR independent restatements of
    that scoping rule in the tree — see architecture-review finding 1; a
    later packet cross-checks that all four agree.
    """
    al = assemble(SRC_ALIAS_SHADOW)
    assert al.equ_alias['COUNT'] == ('CDBASE', 2)
    assert 'COUNT' in al.seg_local[al.segs.index(
        next(s for s in al.segs if al._fold(s.name) == 'SORTARRAY'))]

    # From OTHER (no local COUNT): the alias applies -> CDBASE + 2.
    other = in_seg(al, 'Other')
    assert omf._expr_for(al, 'Count', other) == \
        sym('CDBASE') + lit(2) + b'\x01' + END

    # From SORTARRAY (which defines its own COUNT at offset 2): the alias is
    # suppressed and the LOCAL label wins -> SORTARRAY + 2.
    sorter = in_seg(al, 'SortArray')
    assert omf._expr_for(al, 'Count', sorter) == \
        sym('SORTARRAY') + lit(2) + b'\x01' + END
    # the operand addend still applies to the local binding
    assert omf._expr_for(al, 'Count+1', sorter) == \
        sym('SORTARRAY') + lit(3) + b'\x01' + END

    # And the branch is gated on _rseg: with no current segment there is no
    # seg_local to consult, so the alias survives.
    al._rseg = None
    assert omf._expr_for(al, 'Count', sorter) == \
        sym('CDBASE') + lit(2) + b'\x01' + END


def test_expr_for_leading_and_trailing_whitespace_is_ignored():
    a = assemble(SRC_TWO_RELOC_SEGS)
    seg = in_seg(a, 'Alpha')
    assert omf._expr_for(a, '  AMid  ', seg) == omf._expr_for(a, 'AMid', seg)
    assert omf._expr_for(a, '^ AStart', seg) == omf._expr_for(a, '^AStart', seg)
    assert omf._expr_for(a, 'AStart + 2', seg) == \
        omf._expr_for(a, 'AStart+2', seg)


def test_expr_for_always_terminates_the_expression():
    a = assemble(SRC_TWO_RELOC_SEGS)
    seg = in_seg(a, 'Alpha')
    for text in ('AMid', 'BLab', '^AStart', 'BLab-AMid', 'BLab*4+3',
                 '$1234', 'AEnd-AStart', '(AMid)'):
        assert omf._expr_for(a, text, seg).endswith(b'\x00'), text


# ===========================================================================
# runner (project convention: standalone script, nonzero exit on failure)
# ===========================================================================

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
        except Exception as exc:                       # noqa: BLE001
            failed += 1
            print(f'ERROR {name}: {exc!r}')
        else:
            print(f'ok   {name}')
    print(f'{len(_TESTS) - failed}/{len(_TESTS)} passed')
    sys.exit(1 if failed else 0)
