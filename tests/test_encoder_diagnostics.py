"""End-to-end proof that m65816's EncodeError reaches an assembly CALLER.

WHY THIS FILE EXISTS: tests/test_m65816_units.py is deliberately corpus-free
and unit-level -- it calls `m65816.encode` directly and can only prove that
the encoder RAISES.  That is not the interesting half.  The lesson recorded
at the top of docs/TODO.md is that `assemble`/`link_driver` once ignored
`a.errors`, which is exactly how a silently dropped `INCLUDE` cost ~1,850
bytes of SCSIHD and went unnoticed for months.  An encoder diagnostic that
nobody can see is the same bug wearing a different hat.

So these tests run the real `asm.assemble()` on real (tiny) source and
assert the message lands in `a.errors`, file:line prefixed.  There is only
ONE channel and it already existed:

    m65816.encode  --raise-->  Asm._emit_instr's `except Exception as e:`
                   --------->  Asm._err  ---------->  Asm.errors
                                                 |
                                                 +->  __main__ prints to
                                                      stderr, exit 1

Run either as:
    python3 -m pytest tests/test_encoder_diagnostics.py
    python3 tests/test_encoder_diagnostics.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from gsasm import asm               # noqa: E402


def _assemble(body):
    """Assemble a one-PROC module and return the Asm object."""
    src = 'Single\tPROC\n' + body + '\tENDP\n\tEND\n'
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, 't.asm')
        with open(p, 'w') as f:
            f.write(src)
        return asm.assemble(p, [d])


def _encode_errors(a):
    return [e for e in a.errors if 'encode error' in e]


def _assert_reports(body, needle):
    a = _assemble(body)
    errs = _encode_errors(a)
    assert errs, f'{body!r}: no encode error reported; errors={a.errors}'
    assert any(needle in e for e in errs), \
        f'{body!r}: expected {needle!r} in {errs}'
    # the diagnostic must be located: "<file>:<line>: error: ..."
    head = errs[0].split(': error: ')[0]
    assert head.endswith(':2') or ':' in head, errs[0]
    return errs


# --------------------------------------------------------------------------
# defect 2: a bare '#' used to raise a bare IndexError out of encode()
# --------------------------------------------------------------------------

def test_bare_immediate_marker_is_a_located_error():
    errs = _assert_reports('\tlda\t#\n', 'immediate operand is empty')
    assert 't.asm:2: error: encode error lda' in errs[0], errs[0]


def test_empty_operand_is_a_located_error():
    _assert_reports('\tlda\n', 'LDA requires an operand')


def test_part_selector_with_no_expression_is_a_located_error():
    _assert_reports('\tlda\t#^\n', "part selector '^' has no expression")


# --------------------------------------------------------------------------
# defect 3: an operand that fits no addressing mode used to emit `00 00`
# --------------------------------------------------------------------------

def test_no_such_addressing_mode_is_a_located_error():
    _assert_reports('\tstz\t$10,y\n', 'STZ has no y-indexed addressing mode')
    _assert_reports('\tldx\t3,s\n', 'LDX has no stack-relative addressing mode')
    _assert_reports('\tldy\t$10,y\n', 'LDY has no y-indexed addressing mode')


def test_no_such_addressing_mode_no_longer_emits_two_zero_bytes():
    """The old behavior put a BRK-shaped `00 00` in the instruction stream."""
    a = _assemble('\tstz\t$10,y\n')
    for _at, ln, barr in a.emitted:
        if (ln.op or '').upper() == 'STZ':
            assert bytes(barr) != b'\x00\x00', 'silent BRK placeholder is back'
            break


# --------------------------------------------------------------------------
# defect 4: narrowing into a one-byte operand used to truncate silently
# --------------------------------------------------------------------------

def test_narrowed_to_dp_is_a_located_error():
    _assert_reports('\tstx\t$1234,y\n',
                    'needs 2 bytes but STX y-indexed has only a 1-byte form')


def test_the_bank_drop_that_asmiigs_itself_does_is_NOT_an_error():
    """The corpus's own shape must keep assembling, silently and exactly.

    `LDA QBase,y` with QBASE = $E11DD8 is `B9 1DD8` in MPW AsmIIgs's own
    listing (work/romsrc/GS_ROM/Serial/Serial.aii.lst:336 and :2624), and
    that listing ends "Assembly complete - no errors found."  414 sites
    across the gate corpus depend on this.
    """
    a = _assemble('\tlda\t$E11DD8,y\n')
    assert _encode_errors(a) == [], a.errors
    for _at, ln, barr in a.emitted:
        if (ln.op or '').upper() == 'LDA':
            assert bytes(barr) == b'\xb9\xd8\x1d', bytes(barr).hex()
            break
    else:
        raise AssertionError('no LDA emitted')


def test_a_forward_reference_is_not_accused_during_pass_one():
    """The multi-pass false-positive guard, end to end.

    `stx Later,y` names a direct-page equate defined further down the file.
    Pass 1 cannot resolve it, `_width` defaults to 2, and the dp,y form is
    narrower than that -- but the operand is only 1 byte wide in truth, so
    reporting there would be wrong.  No error must survive to `a.errors`.
    """
    a = _assemble('\tstx\tLater,y\n\trts\nLater\tequ\t$12\n')
    assert _encode_errors(a) == [], a.errors


# --------------------------------------------------------------------------
# defect 5: a block move used to invent bank 0 for an operand it could not
# account for
# --------------------------------------------------------------------------

def test_block_move_with_one_operand_is_a_located_error():
    _assert_reports('\tmvn\t$010000\n',
                    'MVN takes exactly two operands')


def test_block_move_with_an_unresolvable_bank_is_a_located_error():
    _assert_reports('\tmvn\t$010000,)\n', "cannot resolve bank of ')'")


def test_block_move_of_labels_still_assembles():
    """`mvn main,databank` -- 20 corpus uses -- must not be accused.

    The bank bytes are bank 0 placeholders that omf.py rewrites into
    `expr>>16` RELEXPR records; that is the whole reason `_deferred_bank`
    exists.
    """
    a = _assemble('main\tds.b\t4\n\tmvn\tmain,main\n')
    assert _encode_errors(a) == [], a.errors


def test_block_move_with_a_blank_after_the_comma_still_assembles():
    """GQuit.src:1068 `mvn 0, $E10000`; gold GQuit006800.asm:205 `54 E1 00`."""
    a = _assemble('\tmvn\t0, $E10000\n')
    assert _encode_errors(a) == [], a.errors
    for _at, ln, barr in a.emitted:
        if (ln.op or '').upper() == 'MVN':
            assert bytes(barr) == b'\x54\xe1\x00', bytes(barr).hex()
            break
    else:
        raise AssertionError('no MVN emitted')


# --------------------------------------------------------------------------
# the negative control: valid source produces NO encode errors
# --------------------------------------------------------------------------

def test_ordinary_instructions_report_nothing():
    a = _assemble('\tlda\t#$12\n\tsta\t$10\n\tldx\t$1234\n\trts\n')
    assert _encode_errors(a) == [], a.errors


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
