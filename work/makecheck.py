#!/usr/bin/env python3
"""makecheck.py — sweep gsmake (gsasm/mpwmake.py) across EVERY MPW makefile
in the 6.0.1 source tree.

Three phases, each a scoreboard:

  parse     does gsasm.mpwmake.parse_makefile accept the file at all?
  classify  what does each makefile need?  Commands outside gsmake's
            dispatch (Pascal, CIIgs, TML Pascal... — the known toolchain
            wall), object-segment selectors, undefined shell variables.
  run       (--run) execute each EXECUTABLE-classified makefile's default
            target with gsmake in a THROWAWAY COPY of the whole tree
            (nothing under ref/ is ever written), one subprocess per
            makefile with a timeout, in parallel.

    python3 work/makecheck.py                 # parse + classify
    python3 work/makecheck.py --run           # ... and execute
    python3 work/makecheck.py --run -j 8 --timeout 300
    python3 work/makecheck.py --detail        # per-file classification

The run phase writes work/makecheck_results.json.
"""
import argparse
import concurrent.futures as _fut
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import ensure_repo_on_path          # noqa: E402
ensure_repo_on_path()

from gsasm import mpwmake as M                   # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TREE = os.path.join(REPO, 'ref/GSOS_6/IIGS.601.SRC')
INCLUDES = [os.path.join(REPO, 'work/includes')]

# Commands gsmake's run_line dispatches (conditionals handled in run_recipe).
SUPPORTED = {'asmiigs', 'linkiigs', 'link', 'reziigs', 'rez', 'makebiniigs',
             'overlayiigs', 'makelibiigs', 'make', 'catenate', 'echo',
             'directory', 'duplicate', 'duplicateiigs', 'dup', 'delete',
             'set', 'unset', 'export', 'unexport',
             'if', 'else', 'end'} | M._SKIP_CMDS

# Known non-gsasm compilers/tools: the documented toolchain wall.
FOREIGN_TOOLS = {'pascal', 'pascaliigs', 'ciigs', 'cc', 'c', 'tmlpascal',
                 'tmlpas', 'asm', 'lib', 'libiigs', 'makelib', 'duplicate2',
                 'compactor', 'rezde', 'derez', 'smartlink', 'intbasiciigs',
                 'makeout'}


def find_makefiles():
    out = []
    for root, dirs, files in os.walk(TREE):
        dirs[:] = [d for d in dirs if d != '__MACOSX']
        for f in sorted(files):
            fl = f.lower()
            if fl.startswith('._'):                 # AppleDouble sidecars
                continue
            if fl.endswith(('.makeout', '.list')):  # captured run output
                continue
            if fl == 'makefile' or fl.endswith('.make') \
                    or fl.startswith('make.'):
                out.append(os.path.join(root, f))
    return sorted(out)


def classify(path):
    """-> dict(status, detail) where status is one of
    parse-fail | foreign-tool | unknown-cmd | selectors | executable"""
    try:
        text = M.read_makefile(path)
        rules, assigns = M.parse_makefile(text)
    except SystemExit as e:
        return {'status': 'parse-fail', 'detail': str(e)}
    except Exception as e:                        # noqa: BLE001
        return {'status': 'parse-fail', 'detail': f'{type(e).__name__}: {e}'}
    cmds = set()
    generated = set()           # files a `MAKE t > file` line writes
    for r in rules:
        for line in r.recipe:
            toks = line.split()
            if not toks:
                continue
            c = toks[0].lower()
            if c.startswith('{') and c.endswith('}'):
                # A {var} command (e.g. "{PRN} file") — classify by the
                # variable's value when the makefile assigns it.
                v = assigns.get(c[1:-1].lower())
                c = v.split()[0].lower() if v and v.split() else c
            if ':' in c:        # a Mac path invocation — judge the leaf
                c = c.rstrip(':').rsplit(':', 1)[-1]
            if c == 'make':
                for i, t in enumerate(toks):
                    if t.startswith('>'):
                        name = (t.lstrip('>') or
                                (toks[i + 1] if i + 1 < len(toks) else ''))
                        generated.add(name.lower().rsplit(':', 1)[-1])
                continue        # MAKE itself is interpreted
            cmds.add(c)
    cmds -= generated           # running a generated cmds file is a no-op
    foreign = sorted(c for c in cmds if c in FOREIGN_TOOLS)
    unknown = sorted(c for c in cmds
                     if c not in SUPPORTED and c not in FOREIGN_TOOLS)
    if foreign:
        return {'status': 'foreign-tool', 'detail': ','.join(foreign),
                'n_rules': len(rules)}
    if unknown:
        return {'status': 'unknown-cmd', 'detail': ','.join(unknown),
                'n_rules': len(rules)}
    return {'status': 'executable', 'detail': '', 'n_rules': len(rules)}


def run_one(args):
    mf_rel, tmp_tree, timeout = args
    mf = os.path.join(tmp_tree, mf_rel)
    cmd = [sys.executable, '-m', 'gsasm.mpwmake',
           '-C', os.path.dirname(mf), '-f', os.path.basename(mf),
           '--always', '-q']
    # Apple's includes, plus the tree roots cross-directory includes
    # (':::ControlMgr:CtlCustomEqus.asm' etc.) search relative to.
    for inc in INCLUDES + [os.path.join(tmp_tree, 'GSToolbox'), tmp_tree]:
        cmd += ['-I', inc]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=timeout, cwd=REPO,
                           env=dict(os.environ, PYTHONPATH=REPO))
    except subprocess.TimeoutExpired:
        return mf_rel, 'timeout', ''
    if r.returncode == 0:
        return mf_rel, 'ok', ''
    err = (r.stderr.strip() or r.stdout.strip()).splitlines()
    return mf_rel, 'fail', err[-1][:200] if err else ''


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--run', action='store_true')
    ap.add_argument('--detail', action='store_true')
    ap.add_argument('-j', type=int, default=6)
    ap.add_argument('--timeout', type=int, default=600)
    ap.add_argument('--only', help='substring filter on makefile path')
    args = ap.parse_args()

    mfs = find_makefiles()
    if args.only:
        mfs = [m for m in mfs if args.only.lower() in m.lower()]
    print(f'{len(mfs)} makefiles')

    cls = {}
    for mf in mfs:
        cls[os.path.relpath(mf, TREE)] = classify(mf)

    from collections import Counter
    counts = Counter(v['status'] for v in cls.values())
    print('classification:', dict(counts))
    if args.detail:
        for k in sorted(cls):
            v = cls[k]
            if v['status'] != 'executable':
                print(f"  {v['status']:12s} {k}  [{v['detail'][:80]}]")

    if not args.run:
        return

    runnable = sorted(k for k, v in cls.items() if v['status'] == 'executable')
    print(f'--run: executing {len(runnable)} makefiles '
          f'(copy of tree, -j{args.j}, timeout {args.timeout}s)')
    tmp = tempfile.mkdtemp(prefix='makecheck-')
    tmp_tree = os.path.join(tmp, 'SRC')
    shutil.copytree(TREE, tmp_tree, symlinks=True)

    results = {}
    with _fut.ProcessPoolExecutor(max_workers=args.j) as ex:
        for mf_rel, status, err in ex.map(
                run_one, [(m, tmp_tree, args.timeout) for m in runnable]):
            results[mf_rel] = {'status': status, 'error': err}
            mark = {'ok': ' ', 'fail': 'F', 'timeout': 'T'}[status]
            print(f'  [{mark}] {mf_rel}' + (f'  {err}' if err else ''))

    rc = Counter(v['status'] for v in results.values())
    print('run results:', dict(rc))
    outpath = os.path.join(REPO, 'work', 'makecheck_results.json')
    with open(outpath, 'w') as fh:
        json.dump({'classification': cls, 'run': results}, fh, indent=1,
                  sort_keys=True)
    print(f'-> {outpath}')
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    main()
