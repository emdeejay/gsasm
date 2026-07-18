"""A reached INCLUDE/APPEND that cannot be resolved must be a hard ERROR
(raised), not silently appended to a.errors and skipped.

BUG (SCSIHD.Driver residual, 2026-07-18): `INCLUDE 'SCSI Get Vol/Disk'` — a
legal HFS filename containing '/', extracted to disk as `SCSI Get Vol_Disk` —
did not resolve, so do_include appended "include not found" to a.errors and
CONTINUED, silently dropping ~1850 bytes of code that only SCSIHD's direct_acc
device type reached. No harness inspected a.errors, so the driver reported a
plausible-but-wrong 42% instead of failing. The '/'->'_' resolver fallback fixed
that specific include (see test/fixture 043); THIS test guards the general
policy that a genuinely-unresolvable include can never again pass quietly.

gsasm.asm.do_include now raises asm.IncludeNotFoundError. Every harness wraps
assemble() in try/except, so a dropped include surfaces as a loud check failure.

Run either as:
    python3 -m pytest tests/test_include_not_found.py
    python3 tests/test_include_not_found.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from gsasm import asm               # noqa: E402


def test_unresolvable_include_raises():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, 't.asm')
        with open(p, 'w') as f:
            f.write("t\tPROC\n"
                    "\tINCLUDE 'no_such_file'\n"   # line 2: the offending include
                    "\tENDP\n"
                    "\tEND\n")
        raised = None
        try:
            asm.assemble(p, [d])
        except asm.IncludeNotFoundError as e:
            raised = e
        assert raised is not None, 'expected IncludeNotFoundError, none raised'
        # carries the include's own file:line context and the spec
        assert ':2:' in str(raised), str(raised)
        assert 'no_such_file' in str(raised), str(raised)


def test_resolvable_include_assembles_clean():
    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(d, 'inc.asm'), 'w') as f:
            f.write("\tdc.b\t$42\n")
        p = os.path.join(d, 't.asm')
        with open(p, 'w') as f:
            f.write("t\tPROC\n\tINCLUDE 'inc.asm'\n\tENDP\n\tEND\n")
        a = asm.assemble(p, [d])          # must NOT raise
        assert not a.errors, a.errors


def test_hfs_slash_in_filename_still_resolves():
    # the SCSIHD class: source references 'Get/Vol', the file on disk is 'Get_Vol'
    # (HFS '/'-in-name extracted with '/'->'_'). The resolver fallback must find it
    # so this does NOT raise (complements fixture 043).
    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(d, 'Get_Vol'), 'w') as f:
            f.write("\tdc.b\t$99\n")
        p = os.path.join(d, 't.asm')
        with open(p, 'w') as f:
            f.write("t\tPROC\n\tINCLUDE 'Get/Vol'\n\tENDP\n\tEND\n")
        a = asm.assemble(p, [d])          # must NOT raise
        assert not a.errors, a.errors


if __name__ == '__main__':
    tests = [v for k, v in sorted(globals().items()) if k.startswith('test_')]
    passed = 0
    for t in tests:
        try:
            t()
            print(f'ok   {t.__name__}')
            passed += 1
        except AssertionError as e:
            print(f'FAIL {t.__name__}: {e}')
    print(f'{passed}/{len(tests)} passed')
    sys.exit(0 if passed == len(tests) else 1)
