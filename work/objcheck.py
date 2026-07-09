#!/usr/bin/env python3
"""Validate the OMF emitter against original AsmIIgs .obj files.
Usage: python3 work/objcheck.py [module.asm]   (one module, shows record diff)
       python3 work/objcheck.py                  (whole corpus summary)
"""
import sys, os, glob
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from gsasm import asm, omf

ROOT = 'work/romsrc/GS_ROM'
INCS = ['work/includes'] + [d for d, _, _ in os.walk(ROOT)]


def src_for(objf):
    # Prefer the real source extensions (.asm/.aii) over the bare stem: for
    # `monitor.obj` the stem `monitor` matches a BINARY artifact `Monitor` on a
    # case-insensitive FS (assembling it crashes parse_line on binary bytes),
    # while the real source is `Monitor.aii`.  For the common `X.asm.obj` the
    # .asm/.aii candidates don't exist, so it still falls through to the stem.
    stem = objf[:-4]
    for cand in (stem + '.asm', stem + '.aii', stem):
        if os.path.exists(cand) and not cand.endswith('.obj'):
            return cand
    return None


def one(src, objf):
    a = asm.assemble(src, INCS)
    mine = omf.emit(a)
    orig = open(objf, 'rb').read()
    return mine, orig


def show(src):
    objf = src + '.obj'
    if not os.path.exists(objf):
        # maybe X.obj for X.aii
        objf = os.path.splitext(src)[0] + '.obj'
    mine, orig = one(src, objf)
    print(f"mine {len(mine)} orig {len(orig)}  {'IDENTICAL' if mine==orig else 'DIFF'}")
    rm, _ = omf.parse_records(mine, omf.parse_header(mine)['DISPDATA'])
    ro, _ = omf.parse_records(orig, omf.parse_header(orig)['DISPDATA'])
    for i in range(max(len(rm), len(ro))):
        a = rm[i] if i < len(rm) else None
        b = ro[i] if i < len(ro) else None
        ta = a[1] if a else '-'
        tb = b[1] if b else '-'
        mark = '' if ta == tb else '  <-'
        print(f"  mine={ta:8s} orig={tb:8s}{mark}")
        if i > 60:
            break


def summary():
    exact = total = 0
    for objf in sorted(glob.glob(ROOT + '/**/*.obj', recursive=True)):
        src = src_for(objf)
        if not src:
            continue
        total += 1
        try:
            mine, orig = one(src, objf)
            if mine == orig:
                exact += 1
        except Exception:
            pass
    print(f"OBJ byte-identical: {exact}/{total}")


if __name__ == '__main__':
    if len(sys.argv) > 1:
        show(sys.argv[1])
    else:
        summary()
