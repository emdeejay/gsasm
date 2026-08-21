"""Direct unit tests for gsasm/makebin.py — the MakeBinIIgs / OverlayIIgs models.

`makebin.py` had no direct coverage: it was exercised only by whole-disk golden
diffing (P8, the drivers, the FSTs), so a mistake in segment placement or in
the deferred-GEQU pass showed up as "byte 0x1a3 of ProDOS differs" rather than
as a failing unit.  These tests drive the module with OMF segments we build
here, byte by byte, so a failure names the semantic that broke.

CORPUS-FREE: every input is synthesised by `_segment()` below — no ref/, no
tmp/, no Apple material.  The synthetic OMF is deliberately hand-encoded rather
than produced by gsasm+linkiigs, so that these tests fail for makebin's reasons
only.

Where makebin's behaviour is surprising (a patch past the end of the host
GROWS it; segment bases come from the declared header LENGTH while the output
comes from the actual body bytes; only TWO GEQU resolution passes run, so a
three-deep forward chain resolves wrong) the test says "PINNED (surprising)"
and asserts what the code does TODAY.  That is the point: these are tripwires,
not endorsements.

Run either as:
    python3 -m pytest tests/test_makebin_units.py
    python3 tests/test_makebin_units.py
"""
import os
import struct
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from gsasm import makebin  # noqa: E402


# --------------------------------------------------------------------------
# Synthetic OMF construction.
#
# Every record builder returns (raw_bytes, body_bytes_contributed) so that
# _segment() can compute the header LENGTH the way a real assembler would —
# and so a test can deliberately declare a WRONG length (see the LENGTH
# divergence test).
# --------------------------------------------------------------------------
def _p4(v):
    return struct.pack('<I', v & 0xFFFFFFFF)


def _p2(v):
    return struct.pack('<H', v & 0xFFFF)


def const(data):
    """CONST: opcode is the literal byte count (1..0xDF)."""
    assert 1 <= len(data) <= 0xDF
    return (bytes([len(data)]) + data, len(data))


def lconst(data):
    """LCONST (0xF2): NUMLEN count + literal bytes."""
    return (b'\xf2' + _p4(len(data)) + data, len(data))


def ds(n):
    """DS (0xF1): n bytes of zero fill."""
    return (b'\xf1' + _p4(n), n)


# OMF expression atoms (see omf._read_expr / omf._eval).
def e_lit(v):
    return b'\x81' + _p4(v)


def e_sym(name):
    b = name.encode('mac_roman')
    return b'\x83' + bytes([len(b)]) + b


E_LOC = b'\x82'          # current location counter
E_ADD = b'\x01'
E_SUB = b'\x02'
E_MUL = b'\x03'
E_END = b'\x00'


def expr_rec(size, *parts):
    """EXPR (0xEB): `size` bytes patched from the expression's value."""
    return (b'\xeb' + bytes([size]) + b''.join(parts) + E_END, size)


def relexpr_rec(size, origin, *parts):
    """RELEXPR (0xEE): PC-relative, `size` bytes."""
    return (b'\xee' + bytes([size]) + _p4(origin) + b''.join(parts) + E_END,
            size)


def _sym_rec(op, name, expr_parts=()):
    b = name.encode('mac_roman')
    return (bytes([op]) + bytes([len(b)]) + b + _p2(0) + bytes([0, 0])
            + b''.join(expr_parts) + (E_END if expr_parts else b''), 0)


def glob(name):
    """GLOBAL (0xE6): defines `name` at the current body offset."""
    return _sym_rec(0xE6, name)


def gequ(name, *expr_parts):
    """GEQU (0xE7): defines `name` as an expression (resolved after placement)."""
    return _sym_rec(0xE7, name, expr_parts)


def _segment(name, recs, org=0, segnum=1, kind=0x00, length=None):
    """Assemble one complete OMF v2.0 segment from *recs*.

    LENGTH defaults to the true sum of the records' body contributions; pass
    `length=` to declare something else on purpose.
    """
    body = b''.join(r[0] for r in recs)
    true_len = sum(r[1] for r in recs)
    sname = bytes([len(name)]) + name.encode('mac_roman')
    hdr = bytearray(44)
    hdr[8:12] = _p4(true_len if length is None else length)   # LENGTH
    hdr[13] = 0                                               # LABLEN
    hdr[14] = 4                                               # NUMLEN
    hdr[15] = 2                                               # VERSION
    hdr[16:20] = _p4(0x10000)                                 # BANKSIZE
    hdr[20:22] = _p2(kind)
    hdr[24:28] = _p4(org)
    hdr[34:36] = _p2(segnum)
    hdr[40:42] = _p2(44)                                      # DISPNAME
    hdr[42:44] = _p2(44 + 10 + len(sname))                    # DISPDATA
    seg = bytearray(hdr) + b'\x00' * 10 + sname + body + b'\x00'   # + END
    seg[0:4] = _p4(len(seg))                                  # BYTECNT
    return bytes(seg)


def test_the_fixture_builder_produces_parsable_omf():
    """Guard the guard: if _segment() drifts, every other test here is noise."""
    from gsasm import omf
    seg = _segment('MAIN', [lconst(b'\x01\x02'), ds(3), glob('LAB')], org=0x800)
    parsed = list(omf.iter_segments(seg))
    assert len(parsed) == 1
    assert parsed[0]['name'] == 'MAIN'
    assert parsed[0]['hdr']['LENGTH'] == 5      # 2 literal + 3 reserved
    assert parsed[0]['hdr']['ORG'] == 0x800
    assert [r[1] for r in parsed[0]['recs']] == ['LCONST', 'DS', 'GLOBAL',
                                                 'END']
    assert parsed[0]['hdr']['BYTECNT'] == len(seg)


# --------------------------------------------------------------------------
# makebin: flattening
# --------------------------------------------------------------------------
def test_empty_input_yields_empty_output():
    assert makebin.makebin(b'', 0x2000) == b''


def test_single_lconst_segment_is_copied_verbatim():
    # The linked-load-file case: one LCONST, nothing to resolve.
    seg = _segment('MAIN', [lconst(bytes(range(16)))])
    assert makebin.makebin(seg, 0x2000) == bytes(range(16))


def test_const_lconst_and_ds_all_contribute_body_bytes():
    seg = _segment('MAIN', [const(b'\xaa'), lconst(b'\xbb\xcc'), ds(3),
                            const(b'\xdd')])
    assert makebin.makebin(seg, 0) == b'\xaa\xbb\xcc\x00\x00\x00\xdd'


def test_ds_is_zero_fill_not_a_hole():
    assert makebin.makebin(_segment('M', [ds(5)]), 0x300) == b'\x00' * 5


def test_segment_name_resolves_to_its_placement_address():
    seg = _segment('MAIN', [expr_rec(2, e_sym('MAIN'))])
    assert makebin.makebin(seg, 0x2000) == b'\x00\x20'          # little-endian


def test_global_labels_take_org_plus_body_offset():
    seg = _segment('MAIN', [lconst(b'\x00\x00\x00'), glob('HERE'),
                            expr_rec(2, e_sym('HERE'))])
    # HERE sits 3 bytes into the segment, which is based at $1000.
    assert makebin.makebin(seg, 0x1000) == b'\x00\x00\x00\x03\x10'


def test_segments_are_placed_sequentially_and_see_each_others_symbols():
    one = _segment('ONE', [lconst(b'\xaa\xbb'), glob('TARGET'),
                           lconst(b'\xcc')], segnum=1)
    two = _segment('TWO', [expr_rec(2, e_sym('TARGET')),
                           expr_rec(2, e_sym('ONE')),
                           expr_rec(2, e_sym('TWO'))], segnum=2)
    out = makebin.makebin(one + two, 0x1000)
    # ONE at $1000 (3 bytes) -> TARGET at $1002, TWO based at $1003.
    assert out == b'\xaa\xbb\xcc' + b'\x02\x10' + b'\x00\x10' + b'\x03\x10'


def test_expression_arithmetic_is_evaluated_at_flatten_time():
    seg = _segment('MAIN', [expr_rec(2, e_sym('MAIN'), e_lit(0x10), E_ADD),
                            expr_rec(2, e_sym('MAIN'), e_lit(0x10), E_SUB),
                            expr_rec(1, e_lit(3), e_lit(4), E_MUL)])
    assert makebin.makebin(seg, 0x2000) == b'\x10\x20' + b'\xf0\x1f' + b'\x0c'


def test_expression_value_is_stored_little_endian_and_truncated_to_size():
    seg = _segment('MAIN', [expr_rec(1, e_lit(0x1234)),
                            expr_rec(2, e_lit(0x1234)),
                            expr_rec(3, e_lit(0xAABBCC))])
    assert makebin.makebin(seg, 0) == b'\x34' + b'\x34\x12' + b'\xcc\xbb\xaa'


def test_loc_operand_tracks_the_current_body_offset():
    seg = _segment('MAIN', [expr_rec(2, E_LOC), lconst(b'\x00' * 4),
                            expr_rec(2, E_LOC)])
    # __LOC__ is seg_base + bytes emitted so far: $2000, then $2006.
    assert makebin.makebin(seg, 0x2000) == b'\x00\x20' + b'\x00' * 4 + \
        b'\x06\x20'


def test_relexpr_is_relative_to_the_end_of_the_field():
    # 0x4C (JMP) then a 2-byte displacement to $2010 stored at offset 1:
    # next_pc = base+1+2 = $2003, so the displacement is $000D.
    seg = _segment('MAIN', [lconst(b'\x4c'), relexpr_rec(2, 0, e_lit(0x2010))])
    assert makebin.makebin(seg, 0x2000) == b'\x4c\x0d\x00'


def test_relexpr_wraps_to_the_field_width_for_backward_targets():
    seg = _segment('MAIN', [lconst(b'\x10'), relexpr_rec(1, 0, e_sym('MAIN'))])
    # target base, next_pc = base+2 -> -2 in one byte.
    assert makebin.makebin(seg, 0x800) == b'\x10\xfe'


def test_unknown_symbols_evaluate_to_zero_rather_than_failing():
    # PINNED: omf._eval answers 0 for an unbound name; makebin has no
    # "undefined symbol" diagnostic of its own.
    seg = _segment('MAIN', [expr_rec(2, e_sym('NOSUCHTHING'))])
    assert makebin.makebin(seg, 0x2000) == b'\x00\x00'


def test_symbols_are_folded_to_upper_case():
    # _parse_segs upper-cases SEGNAME and _build_sym upper-cases GLOBAL/GEQU
    # labels; an expression naming the lower-case spelling misses and reads 0.
    seg = _segment('main', [expr_rec(2, e_sym('main')),
                            expr_rec(2, e_sym('MAIN'))])
    assert makebin.makebin(seg, 0x1234) == b'\x00\x00' + b'\x34\x12'


# --------------------------------------------------------------------------
# makebin: the deferred-GEQU pass
# --------------------------------------------------------------------------
def test_gequ_is_deferred_so_it_can_name_a_later_segment():
    one = _segment('ONE', [gequ('AFTER', e_sym('TWO'), e_lit(4), E_ADD),
                           expr_rec(2, e_sym('AFTER'))], segnum=1)
    two = _segment('TWO', [lconst(b'\xff')], segnum=2)
    # ONE is 2 bytes at $1000, so TWO is at $1002 and AFTER == $1006 —
    # a value the single forward walk could not have known.
    assert makebin.makebin(one + two, 0x1000) == b'\x06\x10\xff'


def test_a_one_deep_forward_gequ_chain_resolves():
    seg = _segment('G', [gequ('A', e_sym('B'), e_lit(1), E_ADD),
                         gequ('B', e_lit(5)),
                         expr_rec(2, e_sym('A'))])
    assert makebin.makebin(seg, 0) == b'\x06\x00'        # A == B+1 == 6


def test_a_three_deep_forward_gequ_chain_resolves():
    # FIXED: exactly two resolution passes used to run, so C = B+1 saw only
    # the first-pass placeholder for B and came out 2.  Resolution now iterates
    # to a fixed point, so A=5, B=A+1, C=B+1 declared in reverse order give the
    # true 5/6/7.
    seg = _segment('G', [gequ('C', e_sym('B'), e_lit(1), E_ADD),
                         gequ('B', e_sym('A'), e_lit(1), E_ADD),
                         gequ('A', e_lit(5)),
                         expr_rec(2, e_sym('C')),
                         expr_rec(2, e_sym('B')),
                         expr_rec(2, e_sym('A'))])
    assert makebin.makebin(seg, 0) == b'\x07\x00' + b'\x06\x00' + b'\x05\x00'


def test_a_deep_forward_gequ_chain_resolves_at_any_depth():
    # The bound is len(pending)+1 sweeps, so the worst case (every link
    # declared in reverse order) must still settle exactly, not "deep enough".
    n = 12
    recs = [gequ(f'S{i}', e_sym(f'S{i+1}'), e_lit(1), E_ADD)
            for i in range(n)]
    recs.append(gequ(f'S{n}', e_lit(0)))
    recs.append(expr_rec(2, e_sym('S0')))
    assert makebin.makebin(_segment('G', recs), 0) == bytes([n, 0])


def test_a_gequ_reference_cycle_raises_instead_of_shipping_an_iterate():
    # A = B+1, B = A+1 has no fixed point.  The old two-pass code answered
    # with whatever the second pass happened to hold; a value nobody can
    # justify is worse than a stop.
    seg = _segment('G', [gequ('A', e_sym('B'), e_lit(1), E_ADD),
                         gequ('B', e_sym('A'), e_lit(1), E_ADD),
                         expr_rec(2, e_sym('A'))])
    try:
        makebin.makebin(seg, 0)
    except ValueError as exc:
        assert 'did not converge' in str(exc)
        assert 'A' in str(exc) and 'B' in str(exc)
    else:
        raise AssertionError('a GEQU cycle must raise, not resolve')


def test_makebin_segments_also_resolves_gequ_chains_to_a_fixed_point():
    # The same fixed-point resolver serves both entry points.
    obj = _segment('ALPHA', [gequ('C', e_sym('B'), e_lit(1), E_ADD),
                             gequ('B', e_sym('A'), e_lit(1), E_ADD),
                             gequ('A', e_lit(5)),
                             expr_rec(2, e_sym('C'))], org=0x2000)
    assert makebin.makebin_segments(obj)['ALPHA'] == b'\x07\x00'


def test_gequ_overrides_a_colliding_global_after_the_seed_pass():
    # PINNED: the seed pass is setdefault (the GLOBAL wins), every sweep after
    # it assigns unconditionally (the GEQU wins).  The value stored is the
    # GEQU's.  Unchanged by the fixed-point rewrite, deliberately.
    seg = _segment('G', [lconst(b'\x00\x00'), glob('DUP'),
                         gequ('DUP', e_lit(0x77)),
                         expr_rec(2, e_sym('DUP'))])
    assert makebin.makebin(seg, 0x400) == b'\x00\x00\x77\x00'


# --------------------------------------------------------------------------
# makebin: placement uses the DECLARED length
# --------------------------------------------------------------------------
def test_placement_uses_the_header_length_while_output_uses_real_bytes():
    # PINNED (surprising): `base += seg['length']` trusts the OMF header, but
    # the returned image is the concatenation of the ACTUAL bodies.  A segment
    # whose declared LENGTH exceeds its emitted bytes (RESSPC-style tail) makes
    # the next segment's ADDRESSES advance by 8 while the IMAGE advances by 2.
    one = _segment('ONE', [lconst(b'\x11\x22')], length=8, segnum=1)
    two = _segment('TWO', [expr_rec(2, e_sym('TWO'))], segnum=2)
    out = makebin.makebin(one + two, 0x100)
    assert out == b'\x11\x22' + b'\x08\x01'     # TWO based at $0108
    assert len(out) == 4                        # ...but only 4 bytes long


# --------------------------------------------------------------------------
# makebin_segments: one symbol table, several origins
# --------------------------------------------------------------------------
def test_makebin_segments_empty_input():
    assert makebin.makebin_segments(b'') == {}


def test_makebin_segments_keys_and_order_follow_the_object():
    obj = (_segment('ALPHA', [lconst(b'\x01')], org=0x2000, segnum=1)
           + _segment('BETA', [lconst(b'\x02')], org=0xBF00, segnum=2))
    out = makebin.makebin_segments(obj)
    assert list(out) == ['ALPHA', 'BETA']
    assert out == {'ALPHA': b'\x01', 'BETA': b'\x02'}


def test_makebin_segments_bases_each_segment_at_its_header_org():
    obj = (_segment('ALPHA', [expr_rec(2, e_sym('ALPHA'))], org=0x2000,
                    segnum=1)
           + _segment('BETA', [expr_rec(2, e_sym('BETA'))], org=0xBF00,
                      segnum=2))
    out = makebin.makebin_segments(obj)
    # NOT sequential placement (that is plain makebin's rule): each segment
    # sits at its own ORG, as with `linkiigs -lseg NAME -org $X`.
    assert out['ALPHA'] == b'\x00\x20'
    assert out['BETA'] == b'\x00\xbf'


def test_makebin_segments_shares_one_symbol_table_across_segments():
    # The P8 shape: PROCONE at $2000 and PROCTWO at $BF00 calling each other.
    obj = (_segment('ALPHA', [expr_rec(2, e_sym('BETA'))], org=0x2000,
                    segnum=1)
           + _segment('BETA', [expr_rec(2, e_sym('ALPHA'))], org=0xBF00,
                      segnum=2))
    out = makebin.makebin_segments(obj)
    assert out['ALPHA'] == b'\x00\xbf'          # sees BETA's linked address
    assert out['BETA'] == b'\x00\x20'


def test_makebin_segments_org_override_is_case_insensitive():
    obj = (_segment('ALPHA', [expr_rec(2, e_sym('BETA'))], org=0x2000,
                    segnum=1)
           + _segment('BETA', [expr_rec(2, e_sym('BETA'))], org=0xBF00,
                      segnum=2))
    out = makebin.makebin_segments(obj, {'beta': 0x0300})
    assert out['ALPHA'] == b'\x00\x03'
    assert out['BETA'] == b'\x00\x03'
    # an override for a name no segment carries is simply ignored
    assert makebin.makebin_segments(obj, {'GAMMA': 1})['BETA'] == b'\x00\xbf'


def test_makebin_segments_resolves_cross_segment_globals_and_gequs():
    obj = (_segment('ALPHA', [lconst(b'\x00\x00'), glob('MID'),
                              expr_rec(2, e_sym('LATE'))], org=0x2000,
                    segnum=1)
           + _segment('BETA', [gequ('LATE', e_sym('MID'), e_lit(2), E_ADD),
                               expr_rec(2, e_sym('MID'))], org=0xBF00,
                      segnum=2))
    out = makebin.makebin_segments(obj)
    assert out['ALPHA'] == b'\x00\x00' + b'\x04\x20'    # LATE == MID+2
    assert out['BETA'] == b'\x02\x20'                   # MID == $2002


# --------------------------------------------------------------------------
# overlay / catenate / stamp
# --------------------------------------------------------------------------
def test_overlay_lays_a_patch_at_a_fixed_offset():
    assert makebin.overlay(b'\x00' * 4, [(b'\xaa\xbb', 1)]) == \
        b'\x00\xaa\xbb\x00'


def test_overlay_with_no_patches_returns_the_host():
    assert makebin.overlay(b'\x01\x02', []) == b'\x01\x02'


def test_overlay_applies_patches_in_order_so_the_last_one_wins():
    out = makebin.overlay(b'\x00' * 4, [(b'\x11\x11', 0), (b'\x22', 1)])
    assert out == b'\x11\x22\x00\x00'


def test_overlay_does_not_mutate_the_host_bytes():
    host = b'\x00' * 4
    makebin.overlay(host, [(b'\xff', 0)])
    assert host == b'\x00' * 4


def test_overlay_past_the_end_GROWS_the_host():
    # CONTRACT (was "PINNED (surprising)"): growth is the OverlayIIgs model,
    # not a slice-assignment accident — make.p8 overlays twelve drivers onto a
    # 6367-byte ProdosBIN and depends on the destination extending.  The old
    # "The host length is unchanged" docstring was the drifted half.
    assert makebin.overlay(b'\x00' * 4, [(b'\xaa\xbb', 3)]) == \
        b'\x00\x00\x00\xaa\xbb'


def test_overlay_wholly_past_the_end_ZERO_FILLS_THE_GAP():
    # FIXED: offset 5 into a 2-byte host used to land at offset 2 (bytearray
    # slice assignment clamps) — silently the wrong address.  OverlayIIgs
    # extends the destination, so the gap is zeros and the patch lands at 5.
    assert makebin.overlay(b'\x00\x00', [(b'\xaa', 5)]) == \
        b'\x00\x00\x00\x00\x00\xaa'


def test_overlay_gap_fill_then_a_later_patch_into_the_gap():
    # The P8 shape in miniature: a far patch extends the image, a later one
    # writes into the zeros it created.
    out = makebin.overlay(b'\x11', [(b'\xaa', 4), (b'\xbb\xcc', 1)])
    assert out == b'\x11\xbb\xcc\x00\xaa'


def test_overlay_exactly_at_the_end_appends_without_a_gap():
    assert makebin.overlay(b'\x11\x22', [(b'\x33', 2)]) == b'\x11\x22\x33'


def test_catenate_joins_in_order():
    assert makebin.catenate([]) == b''
    assert makebin.catenate([b'a', b'', b'bc']) == b'abc'
    assert makebin.catenate([b'\x01' * 3, b'\x02' * 2]) == \
        b'\x01\x01\x01\x02\x02'


def test_stamp_writes_the_sidecar_and_leaves_the_file_alone():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, 'ProDOS')
        with open(path, 'wb') as fh:
            fh.write(b'\xde\xad\xbe\xef')
        makebin.stamp(path, 0xFF, 0x2000)
        with open(path + '.filetype') as fh:
            assert fh.read() == 'type=0xff aux=0x00002000\n'
        with open(path, 'rb') as fh:
            assert fh.read() == b'\xde\xad\xbe\xef'


def test_stamp_field_widths_are_fixed():
    # SYS/OS/TOL filetypes are two hex digits, auxtype eight — the sidecar
    # format is zero-padded to those widths.
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, 'x')
        makebin.stamp(path, 0xB0, 0)
        with open(path + '.filetype') as fh:
            assert fh.read() == 'type=0xb0 aux=0x00000000\n'
        makebin.stamp(path, 0x0F, 0xABCDEF01)
        with open(path + '.filetype') as fh:
            assert fh.read() == 'type=0x0f aux=0xabcdef01\n'


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
