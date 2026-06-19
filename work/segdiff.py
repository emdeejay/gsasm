#!/usr/bin/env python3
"""Per-segment record-level diff between gsasm's emitted .obj and the original.
Usage: python3 work/segdiff.py <module.asm> [segindex]
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from gsasm import asm, omf

ROOT = 'work/romsrc/GS_ROM'
INCS = ['work/includes'] + [d for d, _, _ in os.walk(ROOT)]


def split_segs(d):
    """Split a multi-segment OMF blob into (header, records) per segment."""
    segs = []
    i = 0
    while i < len(d):
        h = omf.parse_header(d[i:])
        seg = d[i:i + h['BYTECNT']]
        recs, _ = omf.parse_records(seg, h['DISPDATA'], h['NUMLEN'], h['LABLEN'])
        segs.append((h, recs, seg))
        if h['BYTECNT'] == 0:
            break
        i += h['BYTECNT']
    return segs


def fmt(rec):
    at, name, detail = rec
    if name in ('CONST', 'LCONST'):
        return f"{name}({len(detail)}) {bytes(detail).hex()}"
    return f"{name} {detail}"


def main():
    src = sys.argv[1]
    objf = src + '.obj' if os.path.exists(src + '.obj') else os.path.splitext(src)[0] + '.obj'
    a = asm.assemble(src, INCS)
    mine = omf.emit(a)
    orig = open(objf, 'rb').read()
    ms = split_segs(mine)
    os_ = split_segs(orig)
    print(f"mine {len(mine)}B {len(ms)}segs   orig {len(orig)}B {len(os_)}segs")
    only = int(sys.argv[2]) if len(sys.argv) > 2 else None
    for si in range(max(len(ms), len(os_))):
        if only is not None and si != only:
            continue
        mh, mr, mb = ms[si] if si < len(ms) else (None, [], b'')
        oh, orr, ob = os_[si] if si < len(os_) else (None, [], b'')
        same = (mb == ob)
        nm = (mh or oh)['SEGNAME'].decode('mac_roman', 'replace') if (mh or oh) else '?'
        if same and only is None:
            continue
        print(f"\n=== seg {si} {nm!r} {'IDENTICAL' if same else 'DIFF'} "
              f"mine {len(mb)}B/{len(mr)}rec  orig {len(ob)}B/{len(orr)}rec ===")
        if same:
            continue
        if mh and oh:
            for k in ('LENGTH', 'KIND', 'ORG', 'SEGNUM', 'LOADNAME', 'SEGNAME'):
                if mh[k] != oh[k]:
                    print(f"   HDR {k}: mine={mh[k]!r} orig={oh[k]!r}")
        for ri in range(max(len(mr), len(orr))):
            ra = mr[ri] if ri < len(mr) else None
            rb = orr[ri] if ri < len(orr) else None
            sa = fmt(ra) if ra else '-'
            sb = fmt(rb) if rb else '-'
            if sa != sb:
                print(f"   [{ri}] mine= {sa}")
                print(f"        orig= {sb}")


if __name__ == '__main__':
    main()
