#!/usr/bin/env python3
"""Corpus-free fixture suite for the gsasm toolchain.

Each directory under tests/fixtures/ holds one original assembly source
exercising one discovered AsmIIgs/OMF behavior, plus the expected output
bytes. Unlike the gates in work/, this suite needs NO copyrighted reference
material: the inputs are original and the expected bytes are gsasm's own
output, blessed at a moment the full golden-corpus gate passed.

Check (default):   python3 tests/run_fixtures.py [name-substring ...]
Bless:             python3 tests/run_fixtures.py --bless [name-substring ...]

--bless first runs work/gate.py and refuses to mint new expected bytes unless
the gate passes — that interlock is what ties fixture truth back to the
golden corpus. --no-gate skips the interlock (for machines without ref/;
use only for fixtures whose behavior you have verified by hand).

Fixture directory layout:
    input.asm       original source (required)
    fixture.json    optional: {"note": ..., "defines": {...},
                    "sysdate": ..., "systime": ..., "link": true}
    expected.obj    blessed OMF object bytes (authoritative comparison)
    expected.dump   human-readable dump of expected.obj (derived, for review)
    expected.out    blessed link.link() output, when "link": true
    expected.out.dump
"""
import argparse
import difflib
import json
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXDIR = os.path.join(REPO, 'tests', 'fixtures')
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, 'tests'))

from gsasm import asm, omf, link  # noqa: E402
import omfdump  # noqa: E402


def build(fixdir):
    """Assemble (and optionally link) a fixture; return {name: bytes} outputs."""
    cfgfile = os.path.join(fixdir, 'fixture.json')
    cfg = {}
    if os.path.exists(cfgfile):
        with open(cfgfile) as fh:
            cfg = json.load(fh)
    src = os.path.join(fixdir, 'input.asm')
    a = asm.assemble(src, [fixdir],
                     defines=cfg.get('defines'),
                     sysdate=cfg.get('sysdate'),
                     systime=cfg.get('systime'))
    if a.errors:
        raise AssertionError('assembly errors:\n  ' + '\n  '.join(a.errors[:10]))
    outs = {'expected.obj': omf.emit(a)}
    if cfg.get('link'):
        outs['expected.out'] = link.link(outs['expected.obj'])
    return outs


def check(fixdir):
    """Return a list of failure messages (empty = pass)."""
    fails = []
    try:
        outs = build(fixdir)
    except Exception as exc:
        return [f'build failed: {exc}']
    for name, got in outs.items():
        expfile = os.path.join(fixdir, name)
        if not os.path.exists(expfile):
            fails.append(f'{name}: missing expected file (run --bless)')
            continue
        with open(expfile, 'rb') as fh:
            want = fh.read()
        if got != want:
            diff = difflib.unified_diff(
                omfdump.dump(want).splitlines(keepends=True),
                omfdump.dump(got).splitlines(keepends=True),
                fromfile=f'{name} (expected)', tofile=f'{name} (actual)')
            fails.append(f'{name}: {len(want)} -> {len(got)} bytes\n'
                         + ''.join(diff))
    return fails


def bless(fixdir):
    outs = build(fixdir)
    for name, got in outs.items():
        with open(os.path.join(fixdir, name), 'wb') as fh:
            fh.write(got)
        dumpname = 'expected.dump' if name == 'expected.obj' else name + '.dump'
        with open(os.path.join(fixdir, dumpname), 'w') as fh:
            fh.write(omfdump.dump(got))
    return sorted(outs)


def run_gate():
    # --skip-fixtures: gate.py runs THIS suite as its own hard gate; calling it
    # from the bless interlock (before the new fixture's bytes exist) would
    # deadlock, and we run the suite ourselves right after.
    print('bless interlock: running work/gate.py (requires golden refs) ...')
    r = subprocess.run(
        [sys.executable, os.path.join(REPO, 'work', 'gate.py'), '--skip-fixtures'],
        cwd=REPO)
    return r.returncode == 0


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('names', nargs='*',
                   help='only fixtures whose directory name contains any of these')
    p.add_argument('--bless', action='store_true',
                   help='regenerate expected outputs (gate-interlocked)')
    p.add_argument('--no-gate', action='store_true',
                   help='skip the work/gate.py interlock when blessing')
    args = p.parse_args()

    fixtures = sorted(d for d in os.listdir(FIXDIR)
                      if os.path.isdir(os.path.join(FIXDIR, d)))
    if args.names:
        fixtures = [f for f in fixtures if any(n in f for n in args.names)]
    if not fixtures:
        print('no fixtures matched', file=sys.stderr)
        return 1

    if args.bless:
        if args.no_gate:
            print('WARNING: blessing WITHOUT the golden-corpus gate. Only do this\n'
                  'for fixtures whose expected bytes you have verified by hand.')
        elif not run_gate():
            print('ABORT: work/gate.py did not pass; refusing to bless.\n'
                  'Fixture truth may only be minted while the golden corpus '
                  'validates the toolchain.', file=sys.stderr)
            return 1

    failed = []
    for f in fixtures:
        fixdir = os.path.join(FIXDIR, f)
        if args.bless:
            written = bless(fixdir)
            print(f'  BLESS {f}: wrote {", ".join(written)}')
        else:
            fails = check(fixdir)
            if fails:
                failed.append(f)
                print(f'  FAIL  {f}')
                for msg in fails:
                    print('        ' + msg.replace('\n', '\n        '))
            else:
                print(f'  ok    {f}')

    if args.bless:
        print(f'blessed {len(fixtures)} fixture(s)')
        return 0
    print(f'{len(fixtures) - len(failed)}/{len(fixtures)} fixtures pass')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
