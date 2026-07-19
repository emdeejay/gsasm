#!/usr/bin/env python3
"""appleshare_diag.py — locate the remaining AppleShare.FST sizing drift.

Reuses fstcheck's AppleShare build (24 modules, equates.dump rewrite), builds a
byte-offset -> (module, segment, label, source Line) map from gsasm's own
placement, de-ExpressLoads the golden binary, block-aligns the two, and reports
every structural (size-changing) edit mapped to its source line — i.e. every
instruction gsasm still sizes differently from Apple.

Run:  python3 work/appleshare_diag.py
"""
import sys, os, difflib, tempfile, shutil
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from gsasm import asm, omf, linkiigs
from gsasm.expressload import de_express
import work.fstcheck as F


def build_with_map():
    """Assemble+link AppleShare like fstcheck._build_appleshare, but also return
    an offset map. Returns (image, regions, golden)."""
    g = F.golden('AppleShare.FST')
    src = F.APPLESHARE_DIR
    files = {f.lower(): f for f in os.listdir(src) if f.endswith('.aii')}
    tmp = tempfile.mkdtemp(prefix='asdiag_')
    try:
        eq = [l for l in F.read_text(os.path.join(src, files['equates.aii'])).split('\n')
              if not l.strip().lower().startswith('dump')
              and l.strip().lower() != 'end']
        with open(os.path.join(tmp, 'equates_clean.aii'), 'w', encoding='mac_roman') as f:
            f.write('\n'.join(eq))
        incs = [src, tmp] + F.INCS
        objects = []
        for base in F.APPLESHARE_ORDER:
            text = F.read_text(os.path.join(src, files[base.lower() + '.aii'])).split('\n')
            out = [(F._LOAD_RE.match(l).group(1) + "include 'equates_clean.aii'"
                    if F._LOAD_RE.match(l) else l) for l in text]
            p = os.path.join(tmp, base + '.aii')
            with open(p, 'w', encoding='mac_roman') as f:
                f.write('\n'.join(out))
            a = asm.assemble(p, incs, defines={'DebugCode': 0})
            objects.append((omf.emit(a), a, base))

        link_objs = [(o, a) for o, a, _ in objects]
        placed, _b, _oi = linkiigs._place(link_objs, base_org=0)
        origin = placed[0][2]
        seg_iter = [(a, base, seg) for (_o, a, base) in objects for seg in a.segs]
        regions = []
        for (segname, _r, seg_base, _h, _as), (a, base, seg) in zip(placed, seg_iter):
            off = seg_base - origin
            cur = segname
            for item in seg.items:
                kind = item[0]
                if kind == 'global':
                    cur = item[1]; continue
                if kind == 'ds':
                    n, line = item[1], None
                else:
                    line = item[1]
                    n = len(item[2]) if item[2] is not None else 0
                    if getattr(line, 'label', None):
                        cur = line.label
                if n:
                    regions.append((off, off + n, base, segname, cur, line))
                    off += n
        img = F._extract_img(linkiigs.link(link_objs, opts={'merge': True}))
        return img, regions, g
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def locate(regions, off):
    for s, e, base, seg, lbl, line in regions:
        if s <= off < e:
            return base, seg, lbl, line
    return None, None, None, None


def main():
    img, regions, g = build_with_map()
    print(f'gsasm={len(img)}  golden={len(g)}  (delta {len(img)-len(g):+d})')
    sm = difflib.SequenceMatcher(a=g, b=img, autojunk=False)
    struct = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == 'equal':
            continue
        if tag == 'replace' and i2 - i1 == 1 and j2 - j1 == 1:
            continue                       # single-byte address ripple
        struct.append((tag, i1, i2, j1, j2))
    print(f'structural (size-changing) edits: {len(struct)}\n')
    for tag, i1, i2, j1, j2 in struct:
        base, seg, lbl, line = locate(regions, j1)
        raw = (line.raw.strip() if line is not None and getattr(line, 'raw', None) else '(ds/data)')
        print(f'  {tag} gold[{i1:#06x}:{i2:#06x}]={bytes(g[i1:i2]).hex():<10} '
              f'gsasm[{j1:#06x}:{j2:#06x}]={bytes(img[j1:j2]).hex():<10}')
        print(f'      {base}:{seg}  near {lbl}   | {raw}')


if __name__ == '__main__':
    main()
