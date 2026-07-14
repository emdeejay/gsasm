"""Hand-authored unit tests for gsasm/rez/gen.py (work packet R5).

These are original snippets (NOT derived from Apple sources) each pinning
one generation rule discovered while byte-diffing the real corpus against
`work/rezcheck.py`'s golden `Sys.Resources` fork (`work/rezgencheck.py` runs
that corpus check itself; this file only ever needs small hand-computed
snippets, following the style of tests/test_rez_parser.py).

Run either as:
    python3 -m pytest tests/test_rez_gen.py
    python3 tests/test_rez_gen.py
"""
import os
import struct
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from gsasm.rez import parser, gen, emit  # noqa: E402


def _parse(data, name='t.r', predefined=None):
    if isinstance(data, str):
        data = data.encode('latin-1')
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, name)
        with open(path, 'wb') as f:
            f.write(data)
        return parser.parse(path, predefined=predefined)


def _gen(data, name='t.r', predefined=None):
    return gen.generate(_parse(data, name, predefined))


def _one_resource_data(data, name='t.r', predefined=None):
    """Parse+generate `data`, assert exactly one 'resource' entry, and
    return its bytes."""
    entries = _gen(data, name, predefined)
    res = [e for e in entries if e.kind == 'resource']
    assert len(res) == 1, [e.kind for e in entries]
    return res[0].data


def _expect_gen_error(src, name='t.r', predefined=None):
    """Parse+generate `src` and assert it raises `gen.GenError`, returning
    the error message (adversarial-review regression tests: robustness
    findings that must fail closed with a `GenError`, not silently produce
    wrong bytes or leak a raw Python exception)."""
    try:
        _gen(src, name, predefined)
    except gen.GenError as exc:
        return str(exc)
    raise AssertionError(f'expected GenError, none raised for: {src!r}')


# --------------------------------------------------------------------------
# Integer widths + endianness: byte/integer/longint are little-endian.
# --------------------------------------------------------------------------
def test_integer_widths_are_little_endian():
    src = (
        b'type 1 { byte; integer; longint; };\r'
        b'resource 1 (1) { $12, $1234, $12345678 };\r'
    )
    data = _one_resource_data(src)
    assert data == b'\x12' + struct.pack('<H', 0x1234) + struct.pack('<I', 0x12345678)
    assert data == bytes([0x12, 0x34, 0x12, 0x78, 0x56, 0x34, 0x12])


def test_negative_longint_two_complement_little_endian():
    src = (
        b'type 1 { longint infront=-1, behind=0; };\r'
        b'resource 1 (1) { infront };\r'
    )
    data = _one_resource_data(src)
    assert data == b'\xff\xff\xff\xff'


# --------------------------------------------------------------------------
# pstring: 1-byte length prefix + raw bytes (no terminator).
# --------------------------------------------------------------------------
def test_pstring_length_prefix():
    src = (
        b'type 1 { pstring; };\r'
        b'resource 1 (1) { "Standard" };\r'
    )
    data = _one_resource_data(src)
    assert data == bytes([len(b'Standard')]) + b'Standard'


# --------------------------------------------------------------------------
# hex string: raw passthrough, no length prefix, no terminator; the
# field's own `[size-expr]` bracket is never evaluated -- the literal's
# own byte length is authoritative (see gen.py module docstring).
# --------------------------------------------------------------------------
def test_hex_string_passthrough_ignores_size_bracket():
    src = (
        b'type 1 { integer h; hex string [99]; };\r'   # bogus bracket size
        b'resource 1 (1) { 2, $"DEADBEEF" };\r'
    )
    data = _one_resource_data(src)
    assert data == struct.pack('<H', 2) + bytes.fromhex('DEADBEEF')


# --------------------------------------------------------------------------
# `string` field: raw bytes, no prefix/terminator; escape decoding:
# \0xHH -> one byte, \n -> one byte 0x0D (Mac CR, NOT 0x0A).
# --------------------------------------------------------------------------
def test_string_escapes_hex_byte_and_mac_cr():
    src = (
        b'type 1 { string; };\r'
        b'resource 1 (1) { "AB\\0x00CD\\n\\0x0dEF" };\r'
    )
    data = _one_resource_data(src)
    assert data == b'AB\x00CD\x0d\x0dEF'


# --------------------------------------------------------------------------
# `\$HH` escape (hex byte via a dollar sign, not `0x`): golden-diffed
# against EasyMount's Cancel/Connect rControlTemplate KeyEquiv char pairs
# (`{"\$1B","\$1B",...}` / `{"\$0D","\$0D",...}`), whose golden bytes are
# single ESC (0x1B) / CR (0x0D) bytes, not the 4 literal characters a bare
# backslash-drop fallback would produce.
# --------------------------------------------------------------------------
def test_string_escape_dollar_hex_byte():
    src = (
        b'type 1 { char; char; };\r'
        b'resource 1 (1) { "\\$1B", "\\$0d" };\r'   # case-insensitive hex digits
    )
    data = _one_resource_data(src)
    assert data == b'\x1b\x0d'


# --------------------------------------------------------------------------
# fill (byte|word|long)[N]: N zero-valued units, no resource value consumed.
# --------------------------------------------------------------------------
def test_fill_units():
    src = (
        b'type 1 { integer; fill long[2]; fill byte[3]; integer; };\r'
        b'resource 1 (1) { $0001, $0002 };\r'
    )
    data = _one_resource_data(src)
    assert data == (struct.pack('<H', 1) + b'\x00' * 8 + b'\x00' * 3
                     + struct.pack('<H', 2))


def test_fill_default_count_is_one_unit():
    src = (
        b'type 1 { fill word; integer; };\r'
        b'resource 1 (1) { $0007 };\r'
    )
    data = _one_resource_data(src)
    assert data == b'\x00\x00' + struct.pack('<H', 7)


# --------------------------------------------------------------------------
# array with $$Countof: unbounded array consumes a brace-enclosed group,
# iterating its one field per remaining value; a later `integer =
# $$Countof(name)` default reads back how many iterations ran.
# --------------------------------------------------------------------------
def test_array_countof():
    src = (
        b'type 1 {\r'
        b'  integer = $$Countof(Items);\r'
        b'  array Items { integer; };\r'
        b'};\r'
        b'resource 1 (1) { { 10, 20, 30 } };\r'
    )
    data = _one_resource_data(src)
    assert data == (struct.pack('<H', 3) + struct.pack('<H', 10)
                     + struct.pack('<H', 20) + struct.pack('<H', 30))


def test_array_bounded_and_named_group_reused_by_optionalcount():
    # A forward reference: the count field precedes the array it counts,
    # mirroring rControlTemplate's "integer = 3+$$optionalCount(Fields);"
    # appearing before its own `switch`. Requires the two-pass generation
    # scheme (see gen.py module docstring).
    src = (
        b'type 1 {\r'
        b'  integer = 100+$$Countof(Pair);\r'
        b'  array Pair [2] { integer; };\r'
        b'};\r'
        b'resource 1 (1) { { 1, 2 } };\r'
    )
    data = _one_resource_data(src)
    assert data == (struct.pack('<H', 102) + struct.pack('<H', 1)
                     + struct.pack('<H', 2))


# --------------------------------------------------------------------------
# optional field: partial consumption -- fewer values than declared fields
# means the remaining fields are OMITTED (not zero-filled), and
# $$optionalCount reads back the number of values actually consumed.
# Mirrors rControlTemplate's editLineControl (6 template fields, 5 values
# supplied in the corpus) discovery.
# --------------------------------------------------------------------------
def test_optional_partial_fill_and_optionalcount():
    src = (
        b'type 1 {\r'
        b'  integer = 3+$$optionalCount(Fields);\r'
        b'  optional Fields { integer; integer; integer; };\r'
        b'};\r'
        b'resource 1 (1) { { 10, 20 } };\r'
    )
    data = _one_resource_data(src)
    # pCount = 3+2 = 5, then only the 2 supplied values, third field omitted.
    assert data == (struct.pack('<H', 5) + struct.pack('<H', 10)
                     + struct.pack('<H', 20))


def test_optional_partial_fill_stops_at_nested_array_field():
    # Same partial-fill doctrine as test_optional_partial_fill_and_
    # optionalcount above, but the field the resource runs out of values
    # AT is itself a nested ArrayField, not a plain TypedField -- mirrors
    # EasyMount's CTLTMP_00000008 (iconButtonControl's `optional Fields`,
    # 7 plain fields then the unnamed `KeyEquiv` array macro), which
    # supplies only 7 values and golden-diffs to a resource with KeyEquiv
    # entirely omitted (not zero-filled).
    src = (
        b'type 1 {\r'
        b'  optional Fields {\r'
        b'    integer;\r'
        b'    integer;\r'
        b'    array [1] { integer; integer; };\r'   # "KeyEquiv"-shaped
        b'  };\r'
        b'};\r'
        b'resource 1 (1) { { 10, 20 } };\r'   # only 2 of the 2+2 values
    )
    data = _one_resource_data(src)
    assert data == struct.pack('<H', 10) + struct.pack('<H', 20)


def test_optional_absent_yields_zero_count():
    src = (
        b'type 1 {\r'
        b'  integer = $$optionalCount(Fields);\r'
        b'  optional Fields { integer; };\r'
        b'};\r'
        b'resource 1 (1) { };\r'
    )
    data = _one_resource_data(src)
    assert data == struct.pack('<H', 0)


# --------------------------------------------------------------------------
# switch: case selected by name (case-insensitive), key field always uses
# its own template default (never consumes a resource value).
# --------------------------------------------------------------------------
def test_switch_case_selection_and_key_default():
    src = (
        b'type 1 {\r'
        b'  switch {\r'
        b'    case Foo:\r'
        b'      key integer = 1;\r'
        b'      integer;\r'
        b'    case Bar:\r'
        b'      key integer = 2;\r'
        b'      longint;\r'
        b'  };\r'
        b'};\r'
        b'resource 1 (1) { bar { 0x11223344 } };\r'   # lowercase "bar"
    )
    data = _one_resource_data(src)
    assert data == struct.pack('<H', 2) + struct.pack('<I', 0x11223344)


# --------------------------------------------------------------------------
# bitstring: MSB-first packing within a byte (first-declared field is the
# high bits) -- mirrors rVersion's ReverseBytes nibble evidence directly.
# --------------------------------------------------------------------------
def test_bitstring_msb_first_packing():
    src = (
        b'type 1 { bitstring[4]; bitstring[4]; };\r'
        b'resource 1 (1) { 0x0, 0x1 };\r'   # high nibble 0, low nibble 1
    )
    data = _one_resource_data(src)
    assert data == b'\x01'


def test_bitstring_named_values():
    src = (
        b'type 1 { bitstring[4] a=0xA; bitstring[4] b=0x3; };\r'
        b'resource 1 (1) { a, b };\r'
    )
    data = _one_resource_data(src)
    assert data == b'\xa3'


# --------------------------------------------------------------------------
# ReverseBytes: pack the group normally, then reverse the whole buffer's
# byte order. Directly mirrors rVersion(1)'s golden evidence:
# {6,0,1,release,$00} -> forward bytes 06 01 A0 00 -> reversed 00 A0 01 06.
# --------------------------------------------------------------------------
def test_reversebytes_group():
    src = (
        b'type 1 {\r'
        b'  ReverseBytes {\r'
        b'    hex byte;\r'
        b'    hex bitstring[4];\r'
        b'    hex bitstring[4];\r'
        b'    hex byte development=0x20, release=0xA0;\r'
        b'    hex byte;\r'
        b'  };\r'
        b'};\r'
        b'resource 1 (1) { { 6, 0, 1, release, $00 } };\r'
    )
    data = _one_resource_data(src)
    assert data == bytes.fromhex('00A00106')


# --------------------------------------------------------------------------
# char: exactly 1 byte; an empty string produces a single 0x00 byte
# (mirrors rMenuItem's `char;` fields, always given "" in the corpus).
# --------------------------------------------------------------------------
def test_char_field_empty_string_is_nul():
    src = (
        b'type 1 { char; char; };\r'
        b'resource 1 (1) { "", "" };\r'
    )
    data = _one_resource_data(src)
    assert data == b'\x00\x00'


def test_char_field_nonempty_takes_first_byte():
    src = (
        b'type 1 { char; };\r'
        b'resource 1 (1) { "Q" };\r'
    )
    data = _one_resource_data(src)
    assert data == b'Q'


# --------------------------------------------------------------------------
# rect/point: 4/2 little-endian 16-bit components.
# --------------------------------------------------------------------------
def test_rect_and_point():
    src = (
        b'type 1 { rect; point; };\r'
        b'resource 1 (1) { {1,2,3,4}, {5,6} };\r'
    )
    data = _one_resource_data(src)
    assert data == b''.join(struct.pack('<H', v) for v in (1, 2, 3, 4, 5, 6))


# --------------------------------------------------------------------------
# $$Word backward reference: reads back a PREVIOUSLY WRITTEN field's value.
# --------------------------------------------------------------------------
def test_dollar_word_backward_reference():
    src = (
        b'type 1 {\r'
        b'  n:\r'
        b'    integer;\r'
        b'  hex string [$$Word(n)];\r'   # size bracket ignored for
        b'};\r'                          # generation, but must still parse
        b'resource 1 (1) { 3, $"AABBCC" };\r'
    )
    data = _one_resource_data(src)
    assert data == struct.pack('<H', 3) + bytes.fromhex('AABBCC')


# --------------------------------------------------------------------------
# Forward bare-label reference (bit OFFSET, not value) inside a `default`
# expression -- directly mirrors rIcon's "(Mask-Image)/8 - 6" pattern,
# needing the two-pass generation scheme.
# --------------------------------------------------------------------------
def test_forward_label_offset_reference_in_default():
    src = (
        b'type 1 {\r'
        b'a:\r'
        b'  integer = (b-a)/8 - 2;\r'   # a: at offset 0; b: after this field
        b'  hex string [1];\r'          # 2 bytes (this field itself, ignored
        b'                            \r'   # for width purposes) + N image bytes
        b'b:\r'
        b'  byte;\r'
        b'};\r'
        # (b-a) in BITS = 8*(2 [this integer field] + len(image bytes))
        # /8 - 2 = len(image bytes) = 3 for a 3-byte hex string.
        b'resource 1 (1) { $"AABBCC", 0xFF };\r'
    )
    data = _one_resource_data(src)
    # computed size field == 3, then the 3 literal bytes, then the trailing byte.
    assert data == struct.pack('<H', 3) + bytes.fromhex('AABBCC') + b'\xff'


# --------------------------------------------------------------------------
# Attribute word: keyword bits OR together; a bare numeric attribute
# passes through unchanged; default (no attrs) is 0.
# --------------------------------------------------------------------------
def test_attribute_word_keywords_combine():
    src = (
        b'type 1 { byte; };\r'
        b'resource 1 (1, locked, fixed, preload, nospecialmemory) { 0 };\r'
    )
    entries = _gen(src)
    res = [e for e in entries if e.kind == 'resource'][0]
    assert res.attr == 0xC048


def test_attribute_word_bare_numeric_passthrough():
    src = (
        b'type 1 { byte; };\r'
        b'resource 1 (1, $8000) { 0 };\r'
    )
    entries = _gen(src)
    res = [e for e in entries if e.kind == 'resource'][0]
    assert res.attr == 0x8000


def test_attribute_word_default_zero():
    src = (
        b'type 1 { byte; };\r'
        b'resource 1 (1) { 0 };\r'
    )
    entries = _gen(src)
    res = [e for e in entries if e.kind == 'resource'][0]
    assert res.attr == 0


def test_convert_attribute_on_read_statement():
    src = (
        b'type 1 { byte; };\r'
        b'read 1 (2, Convert, locked) "some.file";\r'
    )
    entries = _gen(src)
    reads = [e for e in entries if e.kind == 'read']
    assert len(reads) == 1
    assert reads[0].attr == 0x8800
    assert reads[0].data is None   # R6's job, not R5's


# --------------------------------------------------------------------------
# rResName synthesis: built from "name" strings, in source order, appended
# as the LAST entry (mirrors the golden fork's data-order placement).
# --------------------------------------------------------------------------
def test_resname_synthesis_order_and_layout():
    src = (
        b'type 1 { byte; };\r'
        b'resource 1 (100, "First") { 0xAA };\r'
        b'resource 1 (200) { 0xBB };\r'   # unnamed: excluded from rResName
        b'resource 1 (300, "Second") { 0xCC };\r'
    )
    entries = _gen(src)
    assert [e.kind for e in entries] == ['resource', 'resource', 'resource', 'resname']
    resname = entries[-1]
    assert resname.rtype == gen.RESNAME_TYPE == 0x8014
    assert resname.rid == gen.RESNAME_ID == 0x00018001
    assert resname.attr == 0
    expected = (
        struct.pack('<H', gen.RESNAME_FORMAT)
        + struct.pack('<I', 2)
        + struct.pack('<I', 100) + bytes([5]) + b'First'
        + struct.pack('<I', 300) + bytes([6]) + b'Second'
    )
    assert resname.data == expected


def test_no_named_resources_means_no_resname_entry():
    src = (
        b'type 1 { byte; };\r'
        b'resource 1 (1) { 0 };\r'
    )
    entries = _gen(src)
    assert all(e.kind != 'resname' for e in entries)


# --------------------------------------------------------------------------
# to_emit_tuples(): read entries need externally supplied data; resource/
# resname entries pass through untouched; ordering preserved.
# --------------------------------------------------------------------------
def test_to_emit_tuples_resolves_read_entries():
    src = (
        b'type 1 { byte; };\r'
        b'resource 1 (1) { 0xAA };\r'
        b'read 1 (2) "x.file";\r'
    )
    entries = _gen(src)
    try:
        gen.to_emit_tuples(entries)
        raised = False
    except gen.GenError:
        raised = True
    assert raised, 'expected GenError for a missing read payload'

    tuples = gen.to_emit_tuples(entries, {(1, 2): b'\x99\x99'})
    assert tuples == [(1, 1, 0, b'\xaa'), (1, 2, 0, b'\x99\x99')]


# --------------------------------------------------------------------------
# Type redeclaration: the LAST `type` declaration for a given typeid wins
# (mirrors rCursor/rMyCursor both templating $8027).
# --------------------------------------------------------------------------
def test_type_redeclaration_last_wins():
    src = (
        b'type 1 { integer; };\r'
        b'type 1 { longint; };\r'
        b'resource 1 (1) { 0x11223344 };\r'
    )
    data = _one_resource_data(src)
    assert data == struct.pack('<I', 0x11223344)


# --------------------------------------------------------------------------
# The `RezIIGS` predefined macro: needed so `#if RezIIGS == 1` guards fire
# (real RezIIgs predefines this; our lexer/parser need it passed in
# explicitly -- see lexer.py's `_Preprocessor.__init__` docstring). Mirrors
# rControlList's/rMenu's null-longint array terminator.
# --------------------------------------------------------------------------
def test_rezIIGS_predefined_macro_gates_terminator():
    src = (
        b'type 1 {\r'
        b'  array { integer; };\r'
        b'  #if RezIIGS == 1\r'
        b'    integer = 0;\r'
        b'  #endif\r'
        b'};\r'
        b'resource 1 (1) { { 7 } };\r'
    )
    without = _one_resource_data(src)
    assert without == struct.pack('<H', 7)   # no terminator: guard inactive

    with_flag = _one_resource_data(src, predefined={'RezIIGS': 1})
    assert with_flag == struct.pack('<H', 7) + struct.pack('<H', 0)


# --------------------------------------------------------------------------
# $$ArrayIndex / Subscript: best-effort, NOT golden-verified (see gen.py
# module docstring) -- this only pins internal self-consistency.
# --------------------------------------------------------------------------
def test_array_index_and_subscript_speculative():
    src = (
        b'type 1 {\r'
        b'  array Items [2] {\r'
        b'    start:\r'
        b'      integer;\r'
        b'    integer = (start[$$ArrayIndex(Items)])/8;\r'
        b'  };\r'
        b'};\r'
        b'resource 1 (1) { { 111, 222 } };\r'
    )
    data = _one_resource_data(src)
    # iteration 0: start@0 -> integer field stores 0/8=0
    # iteration 1: start@4 (bytes) -> 32/8=4
    assert data == (struct.pack('<H', 111) + struct.pack('<H', 0)
                     + struct.pack('<H', 222) + struct.pack('<H', 4))


# ==========================================================================
# Adversarial-review regressions (docs/REZ_REVIEW_2026-07-14.md)
# ==========================================================================

# --------------------------------------------------------------------------
# HIGH: missing mandatory values must raise GenError, not silently shrink
# the resource. Partial fill is now legal ONLY inside an `optional` group's
# own field list (see the existing test_optional_partial_fill_* tests
# above, which still pass unchanged); every other field list -- the
# top-level resource body, a bounded array's per-iteration list, a switch
# case, a bare/named group -- is mandatory.
# --------------------------------------------------------------------------
def test_top_level_missing_mandatory_value_raises():
    src = (
        b'type 1 { integer; integer; };\r'
        b'resource 1 (1) { 7 };\r'
    )
    msg = _expect_gen_error(src)
    assert 'ran out of resource values' in msg


def test_bounded_array_drops_excess_values_raises():
    # Previously silently dropped the trailing `3` instead of raising.
    src = (
        b'type 1 { array [2] { integer; }; integer; };\r'
        b'resource 1 (1) { { 1, 2, 3 }, 9 };\r'
    )
    msg = _expect_gen_error(src)
    assert 'unconsumed value' in msg


def test_switch_case_missing_value_raises():
    src = (
        b'type 1 { switch { case Foo: integer; integer; }; };\r'
        b'resource 1 (1) { foo { 1 } };\r'
    )
    msg = _expect_gen_error(src)
    assert 'ran out of resource values' in msg


def test_bare_group_missing_value_raises():
    src = (
        b'type 1 { ReverseBytes { hex byte; hex byte; }; };\r'
        b'resource 1 (1) { { 1 } };\r'
    )
    msg = _expect_gen_error(src)
    assert 'ran out of resource values' in msg


def test_bare_group_excess_values_raises():
    src = (
        b'type 1 { ReverseBytes { hex byte; }; };\r'
        b'resource 1 (1) { { 1, 2 } };\r'
    )
    msg = _expect_gen_error(src)
    assert 'unconsumed value' in msg


# --------------------------------------------------------------------------
# MEDIUM: $$Word/$$Byte/$$Long label lookup must be case-insensitive, like
# every other label reference this module resolves.
# --------------------------------------------------------------------------
def test_dollar_word_label_lookup_case_insensitive():
    src = (
        b'type 1 {\r'
        b'  Height: integer;\r'
        b'  integer = $$Word(Height);\r'
        b'};\r'
        b'resource 1 (1) { 7 };\r'
    )
    data = _one_resource_data(src)
    assert data == struct.pack('<H', 7) + struct.pack('<H', 7)


# --------------------------------------------------------------------------
# MEDIUM/LOW: named-value (C-enum-style) resolution must be case-
# insensitive too, same identifier model as label references.
# --------------------------------------------------------------------------
def test_named_value_lookup_case_insensitive():
    src = (
        b'type 1 { integer release=1; };\r'
        b'resource 1 (1) { Release };\r'
    )
    data = _one_resource_data(src)
    assert data == struct.pack('<H', 1)


# --------------------------------------------------------------------------
# MEDIUM/LOW: nonnumeric (literal-identifier) resource type IDs must raise
# a GenError with source location -- not ride through to emit.emit_fork()
# and crash with a raw TypeError on `& 0xFFFF`.
# --------------------------------------------------------------------------
def test_nonnumeric_resource_type_raises():
    src = (
        b'type Foo { byte; };\r'
        b'resource Foo (1) { 7 };\r'
    )
    msg = _expect_gen_error(src)
    assert 'Foo' in msg and 'numeric' in msg


# --------------------------------------------------------------------------
# MEDIUM/LOW: out-of-range resource type/id must raise, not be silently
# truncated by the emitter's `& 0xFFFF` / `& 0xFFFFFFFF` masking.
# --------------------------------------------------------------------------
def test_resource_type_out_of_range_raises():
    src = (
        b'type $10000 { byte; };\r'
        b'resource $10000 (1) { 7 };\r'
    )
    msg = _expect_gen_error(src)
    assert 'out of range' in msg


def test_resource_id_out_of_range_raises():
    src = (
        b'type 1 { byte; };\r'
        b'resource 1 ($100000000) { 7 };\r'
    )
    msg = _expect_gen_error(src)
    assert 'out of range' in msg


def test_emit_fork_rejects_out_of_range_type_directly():
    """`emit.emit_fork()` itself validates, independent of `gen.generate()`
    -- defense in depth for any other/direct caller of the library."""
    try:
        emit.emit_fork([(0x10000, 1, 0, b'\x00')], {})
    except ValueError as exc:
        assert 'out of range' in str(exc)
    else:
        raise AssertionError('expected ValueError, none raised')

    try:
        emit.emit_fork([(1, 0x100000000, 0, b'\x00')], {})
    except ValueError as exc:
        assert 'out of range' in str(exc)
    else:
        raise AssertionError('expected ValueError, none raised')


# --------------------------------------------------------------------------
# MEDIUM/LOW: duplicate final (type, id) resource keys must raise, listing
# both source locations -- including a collision with the synthesized
# rResName entry.
# --------------------------------------------------------------------------
def test_duplicate_resource_key_raises():
    src = (
        b'type 1 { byte; };\r'
        b'resource 1 (1) { 1 };\r'
        b'resource 1 (1) { 2 };\r'
    )
    msg = _expect_gen_error(src)
    assert 'duplicate resource key' in msg


def test_duplicate_resource_key_collides_with_resname_raises():
    src = (
        b'type 1 { pstring; };\r'
        b'type $8014 { byte; };\r'
        b'resource 1 (100, "Alpha") { "x" };\r'
        b'resource $8014 ($00018001) { 9 };\r'
    )
    msg = _expect_gen_error(src)
    assert 'duplicate resource key' in msg


# --------------------------------------------------------------------------
# MEDIUM/LOW: expression domain errors (zero-division, negative bitstring
# width, negative array bound/fill count) must raise GenError with a
# source location, not a raw ZeroDivisionError/ValueError.
# --------------------------------------------------------------------------
def test_division_by_zero_raises():
    src = (
        b'type 1 { integer = 1/0; };\r'
        b'resource 1 (1) { };\r'
    )
    msg = _expect_gen_error(src)
    assert 'division by zero' in msg


def test_negative_bitstring_width_raises():
    src = (
        b'type 1 { bitstring[-1]; };\r'
        b'resource 1 (1) { 3 };\r'
    )
    msg = _expect_gen_error(src)
    assert 'negative bitstring width' in msg


def test_negative_array_bound_raises():
    src = (
        b'type 1 { array [-1] { integer; }; };\r'
        b'resource 1 (1) { { 1, 2 } };\r'
    )
    msg = _expect_gen_error(src)
    assert 'negative array bound' in msg


def test_negative_fill_count_raises():
    src = (
        b'type 1 { fill word[-1]; };\r'
        b'resource 1 (1) { };\r'
    )
    msg = _expect_gen_error(src)
    assert 'negative fill count' in msg


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
