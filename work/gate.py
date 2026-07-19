#!/usr/bin/env python3
"""Regression gate: run every byte-match check and fail if any metric regresses.

Each check emits a headline "good/total" (or "ok/bad") line.  We parse it into
(good, bad) where the invariant for a non-regression is:

    good  must NOT decrease   (fewer byte-exact matches = regression)
    bad   must NOT increase   (more mismatched bytes    = regression)

Baselines live in work/gate_baseline.json (committed).  Usage:

    python3 work/gate.py            # gate the fast corpus (exit 1 on regression)
    python3 work/gate.py --full     # also run diskcheck (slow; needs a2til)
    python3 work/gate.py --update   # rerun and rewrite the baseline

The gate is deliberately direction-aware, not total-pinned: a corpus that grows
(good up AND bad up) surfaces as a bad-count rise, i.e. "needs review" -> rerun
with --update once you've confirmed the new bytes are accounted for.
"""
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASELINE = os.path.join(ROOT, 'work', 'gate_baseline.json')

# Each check: (name, argv, [(metric, regex, kind), ...])
#   kind 'frac' -> regex groups are (good, total); bad = total - good
#   kind 'okbad'-> regex groups are (good, bad)
#   kind 'count'-> regex group is (good,);        bad = 0
CHECKS = [
    ('objcheck', ['objcheck.py'], [
        ('obj_identical', r'OBJ byte-identical:\s*(\d+)/(\d+)', 'frac')]),
    ('linkcheck', ['linkcheck.py'], [
        ('link_identical', r'(\d+)\s+LINK_IDENTICAL', 'count')]),
    ('kernelcheck', ['kernelcheck.py'], [
        ('kernel_bytes', r'TOTAL\s+(\d+)/(\d+)', 'frac')]),
    ('p8check', ['p8check.py'], [
        ('p8_bytes', r'P8 raw code-image match:\s*(\d+)/(\d+)', 'frac')]),
    ('fstcheck', ['fstcheck.py'], [
        ('fst_bytes', r'CORPUS raw code-image match:\s*(\d+)/(\d+)', 'frac')]),
    ('drivercheck', ['drivercheck.py'], [
        ('driver_bytes', r'CORPUS raw code-image match:\s*(\d+)/(\d+)', 'frac')]),
    ('toolcheck', ['toolcheck.py'], [
        ('tool_bytes', r'CORPUS raw code-image match:\s*(\d+)/(\d+)', 'frac')]),
    ('bytecheck', ['bytecheck.py'], [
        ('opcode_bytes', r'OPCODE bytes:\s*(\d+) ok / (\d+) bad', 'okbad'),
        ('operand_values', r'OPERAND values[^:]*:\s*(\d+) ok / (\d+) bad', 'okbad')]),
    # M7/R7 done-gate: the golden Sys.Resources resource fork, reproduced
    # byte-exact from source via BOTH the library pipeline and the `gsrez`
    # CLI (work/rezbuildcheck.py). The cheaper per-packet rez suites
    # (rezcheck/rezemitcheck/rezgencheck/rezloadcheck) are deliberately NOT
    # separately gated here: none of them print a "good/bad" pair that
    # actually dips on a missing (as opposed to merely mismatched) resource
    # (see rezgencheck.py's separate n_fail/n_missing counters), so folding
    # them into this table's regex-driven scheme would risk a metric that
    # silently stops catching a real regression; rezbuildcheck.py's single
    # end-to-end byte count has no such gap (any failure anywhere in the
    # pipeline collapses it to 0).
    ('rezbuildcheck', ['rezbuildcheck.py'], [
        ('rez_sysresources_bytes_exact',
         r'REZ_SYSRESOURCES_BYTES_EXACT\s+(\d+)', 'count')]),
    # R10/R11: EasyMount, both forks byte-exact (R11 closed the data fork's
    # two diagnosed residuals: asm.py's @-label macro-scoping bug and
    # expressload.py's per-object reloc-dictionary symbol table -- see
    # work/easymountcheck.py's docstring). Each regex anchors on its own PASS
    # line, so a regression on EITHER fork makes the parse fail loudly rather
    # than shrinking a number.
    ('easymountcheck', ['easymountcheck.py'], [
        ('rez_easymount_rsrc_bytes_exact',
         r'PASS EasyMount resource fork: built=(\d+)B', 'count'),
        ('rez_easymount_data_bytes_exact',
         r'PASS EasyMount data fork: built=(\d+)B', 'count')]),
]

FULL_CHECKS = [
    ('diskcheck', ['diskcheck.py'], [
        ('disk_logical_exact', r'logical-exact:\s*(\d+)/(\d+)', 'frac')]),
]


def run_unit_tests():
    """Run the standalone unit tests (tests/test_*.py) as a HARD gate.

    These assert BEHAVIORS the byte corpus and the expected-bytes fixture suite
    cannot capture — e.g. that do_include RAISES on an unresolvable include
    (test_include_not_found.py) and that an out-of-range branch is an ERROR
    (test_branch_range.py).  Without this, a regression reverting do_include to
    "append to a.errors and continue" would still pass the corpus + fixtures (the
    exact SCSIHD-class silent-drop this milestone closed).  pytest is not assumed
    present: each test file has a __main__ runner that exits non-zero on failure,
    so the returncode IS the gate.  Returns (ok, summary_line)."""
    import glob
    ok, lines = True, []
    for tf in sorted(glob.glob(os.path.join(ROOT, 'tests', 'test_*.py'))):
        proc = subprocess.run([sys.executable, tf], cwd=ROOT,
                              capture_output=True, text=True)
        out = proc.stdout + proc.stderr
        m = re.search(r'(\d+)/(\d+) passed', out)
        tag = m.group(0) if m else (
            out.strip().splitlines()[-1] if out.strip() else '(no output)')
        lines.append(f'{os.path.basename(tf)}: {tag}')
        if proc.returncode != 0:
            ok = False
            fails = [ln.strip() for ln in out.splitlines()
                     if ln.strip().startswith('FAIL')]
            lines[-1] += ''.join('\n      ' + f for f in fails)
    return ok, '\n  '.join(lines)


def run_fixture_suite():
    """Run the corpus-free fixture suite (tests/run_fixtures.py) as a HARD gate.

    The golden-corpus checks below are BLIND to any construct the ROM sources
    don't happen to contain — a change can broaden the assembler's behavior on
    unseen inputs and still leave every corpus byte identical (see
    docs/ADVERSARIAL_REVIEW_2026-07-17.md: a numeric-addend fold that silently
    widened `ds.b`/branch parsing passed the byte gate).  The fixtures are the
    guard for that blind spot, so the gate must enforce them, not just the corpus.
    Returns (ok, summary_line).  Needs no golden material."""
    rf = os.path.join(ROOT, 'tests', 'run_fixtures.py')
    proc = subprocess.run([sys.executable, rf], cwd=ROOT,
                          capture_output=True, text=True)
    out = proc.stdout + proc.stderr
    m = re.search(r'(\d+)/(\d+) fixtures pass', out)
    summary = m.group(0) if m else (out.strip().splitlines() or ['(no output)'])[-1]
    if proc.returncode != 0:
        fails = [ln.strip() for ln in out.splitlines() if ln.strip().startswith('FAIL')]
        summary += ''.join('\n    ' + f for f in fails)
    return proc.returncode == 0, summary


def run_check(name, argv, specs):
    """Run one check; return {metric: (good, bad)} or raise on parse failure."""
    proc = subprocess.run([sys.executable, os.path.join(ROOT, 'work', *argv)],
                          cwd=ROOT, capture_output=True, text=True)
    out = proc.stdout + proc.stderr
    metrics = {}
    for metric, rx, kind in specs:
        m = re.search(rx, out)
        if not m:
            raise RuntimeError(
                f'{name}: could not parse metric {metric!r} (regex {rx!r}).\n'
                f'--- tail of output ---\n' + '\n'.join(out.splitlines()[-15:]))
        if kind == 'frac':
            good, total = int(m.group(1)), int(m.group(2))
            metrics[metric] = (good, total - good)
        elif kind == 'okbad':
            metrics[metric] = (int(m.group(1)), int(m.group(2)))
        else:  # count
            metrics[metric] = (int(m.group(1)), 0)
    return metrics


def main():
    update = '--update' in sys.argv
    full = '--full' in sys.argv or update
    # --skip-fixtures: the run_fixtures --bless interlock calls gate.py to confirm
    # the CORPUS is green BEFORE it mints a new/changed fixture's expected bytes;
    # running the (not-yet-blessed) fixture suite there would deadlock, and the
    # bless step runs the suite itself anyway.
    skip_fixtures = '--skip-fixtures' in sys.argv
    checks = CHECKS + (FULL_CHECKS if full else [])

    if not skip_fixtures:
        print('running corpus-free fixtures ...', flush=True)
        fx_ok, fx_summary = run_fixture_suite()
        print(f'  {fx_summary}')
        if not fx_ok:
            print('\nFAIL: corpus-free fixture suite regressed '
                  '(a behavior changed on inputs the corpus does not exercise).')
            return 1

        print('running unit tests ...', flush=True)
        ut_ok, ut_summary = run_unit_tests()
        print(f'  {ut_summary}')
        if not ut_ok:
            print('\nFAIL: a standalone unit test regressed.')
            return 1

    baseline = {}
    if os.path.exists(BASELINE):
        with open(BASELINE) as f:
            baseline = json.load(f)

    current, regressions, improvements, missing = {}, [], [], []
    for name, argv, specs in checks:
        print(f'running {name} ...', flush=True)
        metrics = run_check(name, argv, specs)
        for metric, (good, bad) in metrics.items():
            current[metric] = [good, bad]
            base = baseline.get(metric)
            if base is None:
                missing.append(metric)
                print(f'  {metric:<20} good={good} bad={bad}   (NEW, no baseline)')
                continue
            bgood, bbad = base
            flag = ''
            if good < bgood or bad > bbad:
                regressions.append((metric, base, [good, bad]))
                flag = '  <<< REGRESSION'
            elif good > bgood or bad < bbad:
                improvements.append((metric, base, [good, bad]))
                flag = '  <<< improved'
            print(f'  {metric:<20} good={good} bad={bad}   '
                  f'(baseline good={bgood} bad={bbad}){flag}')

    if update:
        with open(BASELINE, 'w') as f:
            json.dump(current, f, indent=2, sort_keys=True)
            f.write('\n')
        print(f'\nbaseline written: {BASELINE} ({len(current)} metrics)')
        return 0

    print()
    if regressions:
        print(f'FAIL: {len(regressions)} regression(s)')
        for metric, base, cur in regressions:
            print(f'  {metric}: {base} -> {cur}')
        return 1
    if missing:
        print(f'FAIL: {len(missing)} metric(s) have no baseline; run --update')
        return 1
    if improvements:
        print(f'PASS with {len(improvements)} improvement(s) '
              f'(rerun with --update to lock in):')
        for metric, base, cur in improvements:
            print(f'  {metric}: {base} -> {cur}')
    else:
        print('PASS: all metrics at or above baseline')
    return 0


if __name__ == '__main__':
    sys.exit(main())
