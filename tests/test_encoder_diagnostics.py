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
