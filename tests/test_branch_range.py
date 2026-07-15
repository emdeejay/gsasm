"""Hand-authored test for task #24: an out-of-range short/long branch must be
a hard assembly ERROR, not a silently wrapped wrong target.

BUG (found while assembling the system-settings-gs app, see that repo's
docs/HARNESS.md "A23 harness notes"): a short branch (BCC/BCS/BEQ/BNE/BMI/
BPL/BVC/BVS/BRA, plus the aliases BLT/BGE/BLE/BGT) whose true displacement
falls outside -128..127 got its offset silently WRAPPED modulo 256 into a
WRONG target -- no error, no warning. Real AsmIIgs errors on this; silent
wrong code is the worst failure class an assembler has. BRL/PER (16-bit
relative) have the same class of bug for -32768..32767.

ROOT CAUSE: gsasm/m65816.py's `encode()` always defers a rel8/rel16 operand
to a `Fixup` -- `_emit()` only calls `evaluate()` for kind in ('val', 'byte'),
so the `kind == 'rel8'`/`'rel16'` arithmetic inside `_emit` never actually
runs against a resolved value; it is dead code kept only for documentation
(see the comment added there). The real, and only, place the branch target is
resolved to a concrete displacement is `Asm.apply_fixups` (final assembly
pass) and `Asm.relink` (LINK pass, cross-module) in gsasm/asm.py -- both
compute `rel = val - (pc + 2 or 3)` and previously masked it mod 256/65536
with no range check. The fix adds the check in both places (`Asm.
_branch_range_err`), reporting through the normal `self._err` file:line
channel using the branch instruction's OWN source location (captured at
`emit_line` time, since `apply_fixups`/`relink` run long after `_cur_file`/
`_cur_line` have moved on).

Multi-pass note: `apply_fixups` skips the check entirely when the target is
still unresolved (`v is None`, e.g. a forward reference in an early
convergence pass) -- only a truly out-of-range FINAL displacement is an
error, so a pass-1/2 placeholder never false-positives.

Run either as:
    python3 -m pytest tests/test_branch_range.py
    python3 tests/test_branch_range.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from gsasm import asm               # noqa: E402


def _assemble(src):
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, 't.asm')
        with open(p, 'w') as f:
            f.write(src)
        return asm.assemble(p, [d])


def _has_range_error(a):
    return [e for e in a.errors if 'branch out of range' in e]


def test_bra_forward_over_range_errors():
    # bra is 2 bytes; ds.b 128 puts Far exactly 130 bytes after the branch,
    # i.e. displacement +128 -- one past the +127 ceiling.
    src = ('Single\tPROC\n'
           '\tbra\tFar\n'
           '\tds.b\t128\n'
           'Far\tanop\n'
           '\trts\n'
           '\tENDP\n'
           '\tEND\n')
    a = _assemble(src)
    errs = _has_range_error(a)
    assert errs, f'expected a branch-range error, got: {a.errors}'
    assert '+128' in errs[0] and '-128..127' in errs[0]


def test_bra_forward_at_127_is_fine():
    # ds.b 127 -> Far is displacement +127 exactly: the legal ceiling.
    src = ('Single\tPROC\n'
           '\tbra\tFar\n'
           '\tds.b\t127\n'
           'Far\tanop\n'
           '\trts\n'
           '\tENDP\n'
           '\tEND\n')
    a = _assemble(src)
    assert not a.errors, a.errors


def test_bcc_backward_over_range_errors():
    # a backward branch one step past -128
    src = ('Single\tPROC\n'
           'Near\tanop\n'
           '\tds.b\t127\n'
           '\tbcc\tNear\n'
           '\trts\n'
           '\tENDP\n'
           '\tEND\n')
    a = _assemble(src)
    errs = _has_range_error(a)
    assert errs, f'expected a branch-range error, got: {a.errors}'
    assert '-129' in errs[0]


def test_bcc_backward_at_neg128_is_fine():
    src = ('Single\tPROC\n'
           'Near\tanop\n'
           '\tds.b\t126\n'
           '\tbcc\tNear\n'
           '\trts\n'
           '\tENDP\n'
           '\tEND\n')
    a = _assemble(src)
    assert not a.errors, a.errors


def test_error_carries_the_branch_instructions_own_file_line():
    src = ('Single\tPROC\n'
           '\tbra\tFar\n'          # line 2: the offending branch
           '\tds.b\t200\n'
           'Far\tanop\n'
           '\trts\n'
           '\tENDP\n'
           '\tEND\n')
    a = _assemble(src)
    errs = _has_range_error(a)
    assert errs, a.errors
    assert ':2: error:' in errs[0], errs[0]


def test_brl_forward_over_range_errors():
    # brl is 3 bytes; ds.b 40000 makes the displacement far exceed +32767.
    src = ('Single\tPROC\n'
           '\tbrl\tFar\n'
           '\tds.b\t40000\n'
           'Far\tanop\n'
           '\trts\n'
           '\tENDP\n'
           '\tEND\n')
    a = _assemble(src)
    errs = _has_range_error(a)
    assert errs, f'expected a branch-range error, got: {a.errors}'
    assert '+40000' in errs[0] and '-32768..32767' in errs[0]


def test_brl_in_range_is_fine():
    src = ('Single\tPROC\n'
           '\tbrl\tFar\n'
           '\tds.b\t100\n'
           'Far\tanop\n'
           '\trts\n'
           '\tENDP\n'
           '\tEND\n')
    a = _assemble(src)
    assert not a.errors, a.errors


def test_out_of_range_branch_still_emits_a_byte_the_same_as_before():
    # The fix only ADDS a diagnostic; it must not change the (buggy-but-
    # deterministic) wrapped byte gsasm has always produced, since other
    # passes/tools may still consume the object bytes even though __main__
    # now aborts the build on a.errors.
    src = ('Single\tPROC\n'
           '\tbra\tFar\n'
           '\tds.b\t128\n'
           'Far\tanop\n'
           '\trts\n'
           '\tENDP\n'
           '\tEND\n')
    a = _assemble(src)
    assert _has_range_error(a)
    bra_bytes = None
    for _at, ln, barr in a.emitted:
        if (ln.op or '').upper() == 'BRA':
            bra_bytes = bytes(barr)
            break
    assert bra_bytes is not None
    # opcode 0x80, operand (128) & 0xFF == 0x80
    assert bra_bytes == b'\x80\x80', bra_bytes.hex()


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
