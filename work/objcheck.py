#!/usr/bin/env python3
"""Validate the OMF emitter against original AsmIIgs .obj files.
Usage: python3 work/objcheck.py [module.asm]   (one module, shows record diff)
       python3 work/objcheck.py                  (whole corpus summary)
"""
import sys, os, glob
from _common import (
    cached_assemble_emit,
    ensure_repo_on_path,
    gate_result,
    romsrc_incs,
    romsrc_root,
)
ensure_repo_on_path()
from gsasm import omf

ROOT = romsrc_root()
INCS = romsrc_incs(ROOT)


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
    # R10: the emitted OMF is all this harness ever wanted from the Asm, so it
    # goes through the opt-in assembly cache (inert unless GSASM_CACHE=1).
    mine, _errors = cached_assemble_emit(src, INCS)
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
    # 21 accepted: those objects are NOT byte-identical but ARE link-identical
    # (cosmetic OMF encoding choices the linker collapses -- linkcheck.py proves
    # it, docs/REFACTORING.md 0).  A 22nd is a regression.
    return gate_result(obj_identical=(total - exact, 21))


if __name__ == '__main__':
    if len(sys.argv) > 1:
        show(sys.argv[1])
    else:
        sys.exit(summary())
