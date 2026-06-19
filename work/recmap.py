#!/usr/bin/env python3
"""Map differing OMF records back to source lines by image-byte offset.
Usage: python3 work/recmap.py <module> <segidx>
"""
import sys, os
sys.path.insert(0, '.')
from gsasm import asm, omf
from work.segdiff import split_segs

ROOT = 'work/romsrc/GS_ROM'
INCS = ['work/includes'] + [d for d, _, _ in os.walk(ROOT)]


def rec_imglen(name, detail):
    if name in ('CONST', 'LCONST'):
        return len(detail)
    if name == 'DS':
        return detail
    if name in ('LEXPR', 'BEXPR', 'EXPR', 'ZEXPR'):
        return detail[0]            # size byte
    if name == 'RELEXPR':
        return detail[0]
    if name in ('RELOC', 'cRELOC', 'INTERSEG', 'cINTERSEG'):
        return detail[0]
    return 0                        # GLOBAL/GEQU/ENTRY/END/ORG/ALIGN: no image


def main():
    src = sys.argv[1]
    segi = int(sys.argv[2])
    objf = src + '.obj' if os.path.exists(src + '.obj') else os.path.splitext(src)[0] + '.obj'
    a = asm.assemble(src, INCS)
    seg = a.segs[segi]
    mine = omf.emit(a)
    orig = open(objf, 'rb').read()
    mr = split_segs(mine)[segi][1]
    orr = split_segs(orig)[segi][1]

    # item image offsets
    items = []
    off = 0
    for it in seg.items:
        if it[0] == 'code':
            items.append((off, it[1].op, it[1].operand, bytes(it[2])))
            off += len(it[2])
        elif it[0] == 'ds':
            items.append((off, 'DS', it[1], None)); off += it[1]
        elif it[0] == 'global':
            items.append((off, 'GLOBAL', it[1], None))

    def item_at(o):
        best = None
        for io, op, operand, b in items:
            if io <= o:
                best = (io, op, operand, b)
            else:
                break
        return best

    # walk mine records with image offset
    moff = 0
    rows = []
    for at, name, detail in mr:
        rows.append((moff, name, detail))
        moff += rec_imglen(name, detail)
    ooff = 0
    orows = []
    for at, name, detail in orr:
        orows.append((ooff, name, detail))
        ooff += rec_imglen(name, detail)

    # show records that differ, with source line
    print(f"seg {segi} mine {len(mr)}rec orig {len(orr)}rec")
    n = max(len(rows), len(orows))
    for i in range(n):
        rm = rows[i] if i < len(rows) else None
        ro = orows[i] if i < len(orows) else None
        sm = f"{rm[1]} {omf_fmt(rm)}" if rm else '-'
        so = f"{ro[1]} {omf_fmt(ro)}" if ro else '-'
        if sm != so:
            o = rm[0] if rm else (ro[0] if ro else 0)
            it = item_at(o)
            print(f"[{i}] @img {o}")
            print(f"   mine= {sm}")
            print(f"   orig= {so}")
            if it:
                print(f"   src @img{it[0]}: {it[1]!r} {it[2]!r}  bytes={it[3].hex() if it[3] else '-'}")


def omf_fmt(r):
    name, detail = r[1], r[2]
    if name in ('CONST', 'LCONST'):
        return f"({len(detail)}) {bytes(detail)[:16].hex()}"
    return str(detail)


if __name__ == '__main__':
    main()
