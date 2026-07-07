"""profst_diag.py — full residual diagnosis for Pro.FST (M8 disk file).

One command prints everything a fixer needs:
  1. code-image diff runs (gold vs ours), each mapped to segment + source line
  2. for each diff site: the OMF record OUR emit produced there (literal CONST vs
     LEXPR/BEXPR + expr ops) and the symbol-table view of the referenced idents
  3. the reloc-record set diff of the final ExpressLoad seg (SUPER page lists +
     standalone cRELOC/RELOC), gold vs ours
  4. byte accounting: code diffs + reloc-size delta vs the EOF delta

Run: python3 work/profst_diag.py
Gate after any fix: this + fstcheck + ROM trio (buildrom/objcheck/linkcheck) +
kernelcheck + drivercheck + toolcheck + diskcheck.
"""
import os, re, struct, sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
for _p in (_REPO, _HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from gsasm import asm, omf, expressload, linkiigs           # noqa: E402
from diskcheck import SYSTEM_DISK, _find_a2til, catalog_disk  # noqa: E402
_find_a2til()
from a2til.prodos import Volume                              # noqa: E402

_SRC  = os.path.join(_REPO, 'ref/GSOS_6/IIGS.601.SRC')
_GSOS = _SRC + '/GS.OS'
_CMN  = _GSOS + '/Common'
INCS  = [_CMN] + [d for d, _, _ in os.walk(_GSOS)] + [os.path.join(_REPO, 'work/includes')]
FST_DIR = _GSOS + '/FSTs/ProDOS'
FST_SRC = FST_DIR + '/ProDOS.FST'


# --------------------------------------------------------------------------
# source-line lookup (ProDOS.FST is CR-line-ended mac_roman; grep won't work)
# --------------------------------------------------------------------------
_srclines = None

def srcline_no(raw):
    """Best-effort source line number for a Line.raw (text search)."""
    global _srclines
    if _srclines is None:
        txt = open(FST_SRC, 'rb').read().decode('mac_roman')
        _srclines = re.split(r'\r\n|\r|\n', txt)
    tgt = raw.strip()
    if not tgt:
        return None
    hits = [i + 1 for i, l in enumerate(_srclines) if l.strip() == tgt]
    return hits if hits else None


# --------------------------------------------------------------------------
# build ours + gold
# --------------------------------------------------------------------------

def build():
    a = asm.assemble(FST_SRC, [FST_DIR] + INCS, defines={'DEBUGSYMBOLS': 0})
    obj = omf.emit(a)
    ours_file = expressload.expressload([(obj, a)])
    vol = Volume(bytearray(open(SYSTEM_DISK, 'rb').read()))
    gf = [f for f in catalog_disk(vol) if f.path.endswith('/Pro.FST')][0]
    gold_file = vol.read_file(gf.path)
    return a, obj, ours_file, gold_file, gf


def split_segs(b):
    segs, off = [], 0
    while off < len(b):
        bc = struct.unpack_from('<I', b, off)[0]
        if bc == 0:
            break
        segs.append(b[off:off + bc])
        off += bc
    return segs


def seglen(recs):
    n = 0
    for _, nm, d in recs:
        if nm == 'END':
            break
        if nm in ('CONST', 'LCONST'):
            n += len(d)
        elif nm in ('LEXPR', 'BEXPR', 'EXPR', 'RELEXPR'):
            n += d[0]
        elif nm == 'DS':
            n += d
    return n


# --------------------------------------------------------------------------
# map a merged-image offset -> (segname, seg_base, Line, rel_off)
# --------------------------------------------------------------------------

def make_lookup(a, obj):
    placed, _, _ = linkiigs._place([(obj, a)], 0)
    byname = {}
    for s in a.segs:
        byname.setdefault((s.name or '').upper(), []).append(s)

    def lookup(off):
        for segname, recs, base, hdr, _ in placed:
            L = seglen(recs)
            if base <= off < base + L:
                sn = hdr['SEGNAME'].decode('mac_roman', 'replace').rstrip('\x00').strip().upper()
                aseg = byname.get(sn, [None])[0]
                rel = off - base
                if aseg:
                    o = 0
                    for it in aseg.items:
                        if it[0] == 'code':
                            if o <= rel < o + len(it[2]):
                                return sn, base, it[1], rel
                            o += len(it[2])
                        elif it[0] == 'ds':
                            o += it[1]
                return sn, base, None, rel
        return None, None, None, None
    return lookup, placed


# --------------------------------------------------------------------------
# what OMF record did WE emit covering a given body offset of a given segment?
# --------------------------------------------------------------------------

def rec_at(obj, segname_upper, body_off):
    off = 0
    while off < len(obj):
        h = omf.parse_header(obj[off:])
        bc = h['BYTECNT']
        sn = h['SEGNAME'].decode('mac_roman', 'replace').rstrip('\x00').strip().upper()
        if sn == segname_upper:
            recs, _ = omf.parse_records(obj[off:off + bc], h['DISPDATA'],
                                        h['NUMLEN'], h['LABLEN'])
            o = 0
            for _, nm, d in recs:
                if nm == 'END':
                    break
                if nm in ('CONST', 'LCONST'):
                    if o <= body_off < o + len(d):
                        return f'{nm} (literal), bytes at site: {bytes(d[body_off-o:body_off-o+2]).hex()}'
                    o += len(d)
                elif nm in ('LEXPR', 'BEXPR', 'EXPR', 'RELEXPR'):
                    sz = d[0]
                    if o <= body_off < o + sz:
                        return f'{nm} size={sz} expr={d[1] if nm!="RELEXPR" else d[2]}'
                    o += sz
                elif nm == 'DS':
                    if o <= body_off < o + d:
                        return 'DS'
                    o += d
            return f'(offset 0x{body_off:x} beyond records?)'
        off += bc
    return '(segment not found)'


def syminfo(a, name):
    u = name.upper()
    sg = a.symseg.get(u)
    sgname = (a.segs[sg].name if sg is not None and sg < len(a.segs) else None)
    return (f'{name}: symbols=0x{a.symbols.get(u, 0):x} symtype={a.symtype.get(u)!r} '
            f'symseg={sg}({sgname}) defcount={a.defcount.get(u)} '
            f'temporg={getattr(a.segs[sg], "temporg", None) if sg is not None and sg < len(a.segs) else None}')


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def main():
    a, obj, ours_file, gold_file, gf = build()
    gold = expressload.de_express(gold_file)
    ours = expressload.de_express(ours_file)
    lookup, placed = make_lookup(a, obj)

    print(f'=== files: gold {len(gold_file)}B (EOF {gf.data_eof}) vs ours {len(ours_file)}B '
          f'(delta {len(ours_file)-gf.data_eof:+d}) ===')
    print(f'=== code images: gold {len(gold)}B ours {len(ours)}B ===')

    diffs = [i for i in range(min(len(gold), len(ours))) if gold[i] != ours[i]]
    runs = []
    for i in diffs:
        if runs and i <= runs[-1][1] + 2:
            runs[-1][1] = i
        else:
            runs.append([i, i])
    print(f'--- {len(diffs)} diff bytes in {len(runs)} runs ---')
    idents = set()
    for s, e in runs:
        sn, base, ln, rel = lookup(s)
        src = (ln.raw.strip()[:60] if ln else '?')
        nos = srcline_no(ln.raw) if ln else None
        print(f'@0x{s:04x}(+{e-s+1}) seg={sn}+0x{rel:x} (base 0x{base:x})')
        print(f'   gold {gold[s:e+3].hex()}  ours {ours[s:e+3].hex()}')
        print(f'   src {nos}: {src}')
        if ln:
            print(f'   our record: {rec_at(obj, sn, rel)}')
            for m in re.finditer(r'[A-Za-z_~@?.][\w~@?.]*', ln.operand or ''):
                idents.add(m.group(0))
    print('--- symbol views ---')
    for nm in sorted(idents):
        if nm.upper() in a.symbols or nm.upper() in a.symtype:
            print('  ' + syminfo(a, nm))

    # reloc set diff on the final ExpressLoad output
    gseg1 = split_segs(gold_file)[1]
    oseg1 = split_segs(ours_file)[1]
    gs, os_ = expressload.parse_super(gseg1), expressload.parse_super(oseg1)
    print('--- SUPER set diff (final seg1) ---')
    for t in sorted(set(gs) | set(os_)):
        G, O = set(gs.get(t, [])), set(os_.get(t, []))
        print(f'  type {t}: gold {len(G)} ours {len(O)}'
              f'  gold-only={sorted(hex(x) for x in G-O)[:10]}'
              f'  ours-only={sorted(hex(x) for x in O-G)[:10]}')


if __name__ == '__main__':
    main()
