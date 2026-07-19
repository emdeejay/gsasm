#!/usr/bin/env python3
"""tool034_diag.py — locate size/byte drift in Tool034 (TextEdit) vs gold.

Walks the built flat image against de_express(gold) with greedy resync:
at a mismatch, searches for the next 24-byte gold anchor within +/-64 bytes
of drift to classify the divergence as an insertion (built longer), deletion
(built shorter), or value-only patch.  Each drift point is attributed to the
owning object, nearest label, and assembled source line via the Asm records.

    python3 work/tool034_diag.py            # list every drift run
    python3 work/tool034_diag.py N          # show only first N drifts (default all)
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import ensure_repo_on_path
ensure_repo_on_path()
import toolcheck
from toolcheck import TOOLMAP, TB, INCS, golden, _lconst_image
from gsasm import asm, omf, linkiigs

ANCHOR = 24
WINDOW = 96


def build():
    subdir, spec = TOOLMAP['034']
    opts = spec['asm_opts']
    objs = []
    for r in spec['files']:
        a = asm.assemble(f'{TB}/{subdir}/{r}', INCS, **opts)
        objs.append((omf.emit(a), a, r))
    linked = linkiigs.link([(o, a) for o, a, _ in objs], opts={'merge': True})
    return _lconst_image(linked), objs


def object_bases(objs):
    """[(base, size, fname, Asm, [seg_bases])] in placed order."""
    out, cur = [], 0
    for _o, a, fname in objs:
        segs = [s for s in a.segs if s.items or s.name]
        seg_bases, base = [], cur
        for s in segs:
            seg_bases.append(cur)
            sz = 0
            for it in s.items:
                if it[0] == 'code':
                    sz += len(it[2])
                elif it[0] == 'ds' and isinstance(it[1], int):
                    sz += it[1]
            cur += sz
        out.append((base, cur - base, fname, a, seg_bases))
    return out


def attribute(off, bases):
    for base, size, fname, a, seg_bases in bases:
        if base <= off < base + size:
            best = None
            segs = [s for s in a.segs if s.items or s.name]
            for lab, v in a.symbols.items():
                si = a.symseg.get(lab)
                if si is None or not isinstance(v, int):
                    continue
                if si < 0 or si >= len(seg_bases):
                    continue
                addr = seg_bases[si] + v
                if addr <= off and (best is None or addr > best[1]):
                    best = (lab, addr)
            lab = f"{best[0]}+{off-best[1]:#x}" if best else '?'
            return f"{fname} {lab}"
    return '?'


def drifts(mine, g):
    """Yield (built_off, gold_off, kind, delta) for each divergence run."""
    i = j = 0
    while i < len(mine) and j < len(g):
        if mine[i] == g[j]:
            i += 1; j += 1
            continue
        anchor = g[j:j+ANCHOR]
        found = None
        if len(anchor) == ANCHOR:
            for d in range(0, WINDOW):
                for s in (d, -d):
                    k = i + s
                    if k >= 0 and mine[k:k+ANCHOR] == anchor:
                        found = s
                        break
                if found is not None:
                    break
        if found is None or found == 0:
            # value-only mismatch: skip past the differing run in lockstep
            yield i, j, 'value', 0
            while i < len(mine) and j < len(g) and mine[i] != g[j]:
                i += 1; j += 1
        elif found > 0:
            yield i, j, 'built-extra', found
            i += found
        else:
            yield i, j, 'built-missing', found
            j += -found
    if len(mine) - i != len(g) - j:
        yield i, j, 'tail', (len(mine) - i) - (len(g) - j)


def main():
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 10**9
    g = toolcheck.golden('034')
    mine, objs = build()
    print(f"built={len(mine)} gold={len(g)} delta={len(mine)-len(g)}")
    bases = object_bases(objs)
    for base, size, fname, _a, _sb in bases:
        print(f"  {base:#07x}..{base+size:#07x}  {fname}")
    n = 0
    for i, j, kind, delta in drifts(mine, g):
        n += 1
        if n > limit:
            print("...")
            break
        who = attribute(i, bases)
        print(f"[{n:3}] built@{i:#07x} gold@{j:#07x} {kind:13} {delta:+4d}  {who}")
        print(f"      built {mine[max(0,i-4):i+12].hex()}")
        print(f"      gold  {g[max(0,j-4):j+12].hex()}")
    print(f"{n} drift runs")


if __name__ == '__main__':
    main()
