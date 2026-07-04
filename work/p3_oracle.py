#!/usr/bin/env python3
"""p3_oracle.py — Equivalence oracle for the P3 decompose refactor.

For every _expr_for call across buildrom + toolcheck + drivercheck + fstcheck,
computes both the CURRENT path (original detectors) and the WOULD-BE NEW path
(classifiers over linear_decompose) and asserts the emitted OMF op-bytes are
byte-identical.

Must be 100% green against UNCHANGED code first (proving the oracle faithfully
captures the current behavior). Then as each detector is migrated, re-run to
verify equivalence holds.

Usage:
    python3 work/p3_oracle.py [--verbose] [harness ...]
    # harness: buildrom, toolcheck, drivercheck, fstcheck (default: all)

Output:
    Per-harness agree/mismatch counts and sample mismatches.
    Exit 0 if 0 mismatches, 1 otherwise.
"""
import sys, os, types, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gsasm import omf as _omf
from gsasm.omf import (
    _num, _omfstr, _in_org_seg, _undef_external, _diff_reloc, _mul_reloc_expr,
    _linear_reloc, _pc_rel_const, linear_decompose,
)

# ---------------------------------------------------------------------------
# "New path" dispatcher: classifies via linear_decompose and dispatches to
# the same existing emit encoders.  This is what the post-migration _expr_for
# will look like from the detectors' perspective.
#
# Scope: only the parts of _expr_for that use the four detectors:
#   1. _pc_rel_const  (in _reloc_elem in the DC branch)
#   2. _linear_reloc  (called from the name=None fallback in _expr_for body)
#   3. _diff_reloc    (in the name=None else branch)
#   4. _mul_reloc_expr (in the name=None/diff=None fallback)
#
# The oracle patches _expr_for at the module level and intercepts the result;
# it also patches the _reloc_elem inner function by intercepting the
# _pc_rel_const + _linear_reloc + _diff_reloc calls within _reloc_elem.
# ---------------------------------------------------------------------------

def _new_linear_reloc(asm, text):
    """Reimplementation of _linear_reloc via linear_decompose."""
    dec = linear_decompose(asm, text)
    if dec is None:
        return None
    terms, K, pc_coeff = dec
    # exactly one relocatable symbol, coefficient +1, no PC term
    if len(terms) != 1 or pc_coeff != 0:
        return None
    name, coeff = next(iter(terms.items()))
    if coeff != 1:
        return None
    # addend = K - 0  (K already accounts for the symbol value)
    # _linear_reloc returns (L, V - Lval) = (L, K + coeff*Lval - Lval) = (L, K)
    # since coeff=1: addend = K
    return (name, K)


def _new_pc_rel_const(asm, text):
    """Reimplementation of _pc_rel_const via linear_decompose."""
    if '*' not in text:
        return False
    seg = asm._rseg
    if seg is None:
        return False
    dec = linear_decompose(asm, text)
    if dec is None:
        return False
    terms, K, pc_coeff = dec
    # The base cancels if: for every same-seg symbol s with coeff c_s,
    # and pc with coeff c_pc:  sum(c_s) + c_pc == 0
    # (all same-seg terms, including PC, are shifted together by the base).
    # pc_coeff is the PC's normalised coefficient.
    # Same-seg label coefficients: those whose symseg == seg
    same_seg_coeff_sum = pc_coeff
    for name, coeff in terms.items():
        nu = asm._symkey(name)
        if asm.symseg.get(nu) == seg:
            same_seg_coeff_sum += coeff
    return same_seg_coeff_sum == 0


def _new_mul_reloc_expr(asm, text, segname):
    """Reimplementation of _mul_reloc_expr via linear_decompose."""
    if asm._rseg is None:
        return None
    dec = linear_decompose(asm, text)
    if dec is None:
        return None
    terms, K, pc_coeff = dec
    # exactly one relocatable symbol, coefficient > 1, in ORG seg
    if len(terms) != 1 or pc_coeff != 0:
        return None
    name, coeff = next(iter(terms.items()))
    if coeff <= 1:
        return None
    # must be a label (not import), and in the current ORG segment
    if asm.sym_kind(name) not in ('label', 'equ'):
        return None
    Lval = (asm.resolve(name) or 0) & 0xFFFFFF
    if not _in_org_seg(asm, Lval):
        return None
    N = coeff
    # K from linear_decompose is V - N*Lval, so the OMF K is the same
    seg_org = asm.segs[asm._rseg].org or 0
    rel = Lval - seg_org
    ops = bytearray()
    ops += bytes([0x83]) + _omfstr(segname)
    if rel:
        ops += bytes([0x81]) + _num(rel & 0xFFFFFFFF) + bytes([0x01])
    ops += bytes([0x81]) + _num(N & 0xFFFFFFFF) + bytes([0x03])
    K_m = K & 0xFFFFFFFF
    if K_m:
        ops += bytes([0x81]) + _num(K_m) + bytes([0x01])
    return bytes(ops)


def _new_diff_reloc(asm, text):
    """Reimplementation of _diff_reloc via linear_decompose."""
    dec = linear_decompose(asm, text)
    if dec is None:
        return None
    terms, K, pc_coeff = dec
    # exactly 2 relocatable symbols with coefficients +1/-1
    if len(terms) != 2 or pc_coeff != 0:
        return None
    items = list(terms.items())
    # find A (coeff +1) and B (coeff -1)
    plus_ones = [(n, c) for n, c in items if c == 1]
    minus_ones = [(n, c) for n, c in items if c == -1]
    if len(plus_ones) != 1 or len(minus_ones) != 1:
        return None
    A = plus_ones[0][0]
    B = minus_ones[0][0]
    # Scope tests (same as original _diff_reloc): both must be labels with known symseg,
    # in different segments, neither ORG'd, both defined.
    if asm.sym_kind(A) != 'label' or asm.sym_kind(B) != 'label':
        return None
    sa = asm.symseg.get(asm._symkey(A))
    sb = asm.symseg.get(asm._symkey(B))
    if sa is None or sb is None:
        return None
    if sa == sb:
        return None
    if (asm.segs[sa].org or 0) or (asm.segs[sb].org or 0):
        return None
    av = asm.resolve(A)
    bv = asm.resolve(B)
    if av is None or bv is None:
        return None

    def locops(name):
        nu = asm._symkey(name)
        seg = asm.segs[asm.symseg[nu]]
        off = ((asm.resolve(nu) or 0) & 0xFFFFFF) - (seg.org or 0)
        o = bytes([0x83]) + _omfstr((seg.name or '').upper())
        if off:
            o += bytes([0x81]) + _num(off & 0xFFFFFFFF) + bytes([0x01])
        return o

    # K from linear_decompose: V - (+1)*av - (-1)*bv = V - av + bv
    # Original _diff_reloc: K = (v - (av&0xFFFFFF - bv&0xFFFFFF)) & 0xFFFFFFFF
    # which is (V - av + bv) & 0xFFFFFFFF — matches linear_decompose's K (mod 2^32).
    K_m = K & 0xFFFFFFFF
    ops = bytearray()
    ops += locops(A)
    ops += locops(B)
    ops += bytes([0x02])  # SUB: A - B
    if K_m:
        ops += bytes([0x81]) + _num(K_m) + bytes([0x01])
    return bytes(ops)


# ---------------------------------------------------------------------------
# Oracle instrumentation
# ---------------------------------------------------------------------------

_stats = {}  # harness_name -> {'agree': 0, 'mismatch': 0, 'samples': []}

_verbose = '--verbose' in sys.argv

_original_expr_for = _omf._expr_for
_original_linear_reloc = _omf._linear_reloc
_original_pc_rel_const = _omf._pc_rel_const
_original_diff_reloc = _omf._diff_reloc
_original_mul_reloc_expr = _omf._mul_reloc_expr

_current_harness = ['?']


def _oracle_linear_reloc(asm, text):
    """Oracle wrapper for _linear_reloc: compares old vs new."""
    old = _original_linear_reloc(asm, text)
    new = _new_linear_reloc(asm, text)
    _check_decomposed('_linear_reloc', asm, text, old, new)
    return old  # always return original for safety


def _oracle_pc_rel_const(asm, text):
    """Oracle wrapper for _pc_rel_const: compares old vs new."""
    old = _original_pc_rel_const(asm, text)
    new = _new_pc_rel_const(asm, text)
    _check_bool('_pc_rel_const', asm, text, old, new)
    return old


def _oracle_diff_reloc(asm, text):
    """Oracle wrapper for _diff_reloc: compares old vs new."""
    old = _original_diff_reloc(asm, text)
    new = _new_diff_reloc(asm, text)
    _check_opbytes('_diff_reloc', asm, text, old, new)
    return old


def _oracle_mul_reloc_expr(asm, text, segname):
    """Oracle wrapper for _mul_reloc_expr: compares old vs new."""
    old = _original_mul_reloc_expr(asm, text, segname)
    new = _new_mul_reloc_expr(asm, text, segname)
    _check_opbytes('_mul_reloc_expr', asm, text, old, new)
    return old


def _check_bool(detector, asm, text, old, new):
    h = _current_harness[0]
    if h not in _stats:
        _stats[h] = {'agree': 0, 'mismatch': 0, 'samples': []}
    if old == new:
        _stats[h]['agree'] += 1
    else:
        _stats[h]['mismatch'] += 1
        if len(_stats[h]['samples']) < 10:
            _stats[h]['samples'].append(
                f"  {detector}  old={old!r}  new={new!r}  text={text!r}")
        if _verbose:
            print(f"MISMATCH {detector}: old={old!r} new={new!r} text={text!r}")


def _check_decomposed(detector, asm, text, old, new):
    """For _linear_reloc: old=(name,addend)|None, new=(name,addend)|None.
    Equivalence = both None, or both non-None and same (name.upper(), addend)."""
    h = _current_harness[0]
    if h not in _stats:
        _stats[h] = {'agree': 0, 'mismatch': 0, 'samples': []}
    if old is None and new is None:
        _stats[h]['agree'] += 1
        return
    if old is not None and new is not None:
        # Compare case-insensitively for name, exact for addend
        if old[0].upper() == new[0].upper() and old[1] == new[1]:
            _stats[h]['agree'] += 1
            return
    _stats[h]['mismatch'] += 1
    if len(_stats[h]['samples']) < 10:
        _stats[h]['samples'].append(
            f"  {detector}  old={old!r}  new={new!r}  text={text!r}")
    if _verbose:
        print(f"MISMATCH {detector}: old={old!r} new={new!r} text={text!r}")


def _check_opbytes(detector, asm, text, old, new):
    """For _diff_reloc / _mul_reloc_expr: both return bytes|None."""
    h = _current_harness[0]
    if h not in _stats:
        _stats[h] = {'agree': 0, 'mismatch': 0, 'samples': []}
    if old == new:
        _stats[h]['agree'] += 1
    else:
        _stats[h]['mismatch'] += 1
        if len(_stats[h]['samples']) < 10:
            _stats[h]['samples'].append(
                f"  {detector}  old={old!r}  new={new!r}  text={text!r}")
        if _verbose:
            print(f"MISMATCH {detector}: old={old!r} new={new!r} text={text!r}")


def install_oracle():
    """Monkeypatch the detectors in the omf module with oracle wrappers."""
    _omf._linear_reloc = _oracle_linear_reloc
    _omf._pc_rel_const = _oracle_pc_rel_const
    _omf._diff_reloc = _oracle_diff_reloc
    _omf._mul_reloc_expr = _oracle_mul_reloc_expr


def uninstall_oracle():
    """Restore original detectors."""
    _omf._linear_reloc = _original_linear_reloc
    _omf._pc_rel_const = _original_pc_rel_const
    _omf._diff_reloc = _original_diff_reloc
    _omf._mul_reloc_expr = _original_mul_reloc_expr


# ---------------------------------------------------------------------------
# Harness runners
# ---------------------------------------------------------------------------


def _run_harness(harness_name, script_path):
    """Load and run a harness script's main() within this process so oracle patches are active."""
    _current_harness[0] = harness_name
    print(f'--- {harness_name} ---', flush=True)
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        f'_{harness_name}_oracle', os.path.abspath(script_path))
    mod = importlib.util.module_from_spec(spec)
    saved_argv = sys.argv[:]
    sys.argv = [script_path]  # no sub-args so main() runs in full-scan mode
    try:
        spec.loader.exec_module(mod)
        # exec_module runs module-level code; now call main() explicitly
        if hasattr(mod, 'main'):
            mod.main()
    except SystemExit:
        pass
    except Exception as e:
        print(f"  {harness_name} error: {e}")
        if _verbose:
            traceback.print_exc()
    finally:
        sys.argv = saved_argv


def _run_buildrom_import():
    _run_harness('buildrom', 'work/buildrom.py')


def _run_toolcheck_import():
    _run_harness('toolcheck', 'work/toolcheck.py')


def _run_drivercheck_import():
    _run_harness('drivercheck', 'work/drivercheck.py')


def _run_fstcheck_import():
    _run_harness('fstcheck', 'work/fstcheck.py')


def _run_kernelcheck_import():
    _run_harness('kernelcheck', 'work/kernelcheck.py')


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    args = [a for a in sys.argv[1:] if not a.startswith('-')]
    run_all = not args

    harnesses_to_run = []
    if run_all or 'buildrom' in args:
        harnesses_to_run.append(('buildrom', _run_buildrom_import))
    if run_all or 'toolcheck' in args:
        harnesses_to_run.append(('toolcheck', _run_toolcheck_import))
    if run_all or 'drivercheck' in args:
        harnesses_to_run.append(('drivercheck', _run_drivercheck_import))
    if run_all or 'fstcheck' in args:
        harnesses_to_run.append(('fstcheck', _run_fstcheck_import))
    if run_all or 'kernelcheck' in args:
        harnesses_to_run.append(('kernelcheck', _run_kernelcheck_import))

    install_oracle()
    try:
        for name, runner in harnesses_to_run:
            try:
                runner()
            except Exception as e:
                print(f"ERROR running {name}: {e}")
                if _verbose:
                    traceback.print_exc()
    finally:
        uninstall_oracle()

    # Print summary
    print()
    print('=== Oracle summary ===')
    total_agree = 0
    total_mismatch = 0
    for h, s in sorted(_stats.items()):
        agree = s['agree']
        mm = s['mismatch']
        total_agree += agree
        total_mismatch += mm
        status = 'OK' if mm == 0 else 'FAIL'
        print(f"  {h:20s}: agree={agree:6d}  mismatch={mm:4d}  [{status}]")
        for sample in s['samples']:
            print(sample)

    print()
    print(f"  TOTAL: agree={total_agree}  mismatch={total_mismatch}")
    if total_mismatch == 0:
        print('  => 0 mismatches across ALL harnesses: ORACLE GREEN')
    else:
        print(f'  => {total_mismatch} mismatches: ORACLE RED')

    return 1 if total_mismatch > 0 else 0


if __name__ == '__main__':
    sys.exit(main())
