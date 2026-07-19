"""reloc_diag.py — dump & compare the OMF record stream (esp. reloc records)
of a gold disk file vs our diskbuilder output.  Diagnostic only.

Usage: python3 work/reloc_diag.py <diskpath-substring>   (e.g. Tool027)
"""
import os, sys, struct
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from diskcheck import SYSTEM_DISK, _find_a2til, catalog_disk, owner_for
_find_a2til()
from a2til.prodos import Volume
import diskbuilders

OPNAMES = {0xE2: 'RELOC', 0xE3: 'INTERSEG', 0xF5: 'cRELOC', 0xF6: 'cINTERSEG',
           0xF7: 'SUPER', 0xF2: 'LCONST', 0xF1: 'DS', 0x00: 'END', 0xF3: 'LEXPR',
           0xED: 'BEXPR', 0xEB: 'EXPR', 0xEE: 'RELEXPR', 0xE7: 'GEQU',
           0xE6: 'GLOBAL', 0xF4: 'ENTRY', 0xF8: 'GENERAL'}


def parse_header(b):
    """Return (bytecnt, body_start_offset) for the OMF segment at b[0:]."""
    bytecnt = struct.unpack_from('<I', b, 0)[0]
    lablen = b[13]
    numlen = b[14]
    dispname = struct.unpack_from('<H', b, 40)[0]
    return bytecnt, dispname


def dump_records(seg, lablen=10, numlen=4):
    """Walk the record stream of one OMF segment body; yield (op, opname, size, detail)."""
    _, dispname = parse_header(seg)
    off = dispname
    # SEGNAME follows LOADNAME(10) at dispname
    seg_end = struct.unpack_from('<I', seg, 0)[0]
    # skip SEGNAME (length-prefixed string) — dispname points at LOADNAME
    off = dispname + 10                      # skip LOADNAME (fixed 10)
    slen = seg[off]; off += 1 + slen         # skip SEGNAME (len-prefixed)
    recs = []
    while off < seg_end:
        op = seg[off]; start = off; off += 1
        name = OPNAMES.get(op, f'0x{op:02X}' if op > 0xE0 else 'CONST')
        if op == 0x00:
            recs.append((op, 'END', 1, '')); break
        elif 0x01 <= op <= 0xDF:             # CONST (op = length)
            off += op; recs.append((op, 'CONST', op, ''))
        elif op == 0xF2:                     # LCONST
            n = struct.unpack_from('<I', seg, off)[0]; off += 4 + n
            recs.append((op, 'LCONST', n, ''))
        elif op == 0xF1:                     # DS
            n = struct.unpack_from('<I', seg, off)[0]; off += 4
            recs.append((op, 'DS', n, ''))
        elif op == 0xE2:                     # RELOC: size,shift,off(4),relOff(4)
            size, shift = seg[off], seg[off+1]
            o = struct.unpack_from('<I', seg, off+2)[0]
            r = struct.unpack_from('<i', seg, off+6)[0]
            off += 10
            recs.append((op, 'RELOC', 11, f'size={size} shift={shift} off=0x{o:x} rel=0x{r&0xffffffff:x}'))
        elif op == 0xF5:                     # cRELOC: size,shift,off(2),relOff(2)
            size, shift = seg[off], seg[off+1]
            o = struct.unpack_from('<H', seg, off+2)[0]
            r = struct.unpack_from('<H', seg, off+4)[0]
            off += 6
            recs.append((op, 'cRELOC', 7, f'size={size} shift={shift} off=0x{o:x} rel=0x{r:x}'))
        elif op == 0xE3:                     # INTERSEG: size,shift,off(4),fileno(2),segno(2),relOff(4)
            size, shift = seg[off], seg[off+1]
            o = struct.unpack_from('<I', seg, off+2)[0]
            fn = struct.unpack_from('<H', seg, off+6)[0]
            sn = struct.unpack_from('<H', seg, off+8)[0]
            r = struct.unpack_from('<I', seg, off+10)[0]
            off += 14
            recs.append((op, 'INTERSEG', 15, f'size={size} shift={shift} off=0x{o:x} file={fn} seg={sn} rel=0x{r:x}'))
        elif op == 0xF6:                     # cINTERSEG: size,shift,off(2),segno(1),relOff(2)
            size, shift = seg[off], seg[off+1]
            o = struct.unpack_from('<H', seg, off+2)[0]
            sn = seg[off+4]
            r = struct.unpack_from('<H', seg, off+5)[0]
            off += 7
            recs.append((op, 'cINTERSEG', 8, f'size={size} shift={shift} off=0x{o:x} seg={sn} rel=0x{r:x}'))
        elif op == 0xF7:                     # SUPER
            n = struct.unpack_from('<I', seg, off)[0]     # record length (bytes after the length field)
            stype = seg[off+4]
            off += 4 + n
            recs.append((op, 'SUPER', 5 + n, f'type={stype} len={n}'))
        else:
            recs.append((op, name, 1, '?? unknown, stopping')); break
    return recs


def split_segments(b):
    segs = []
    off = 0
    while off < len(b):
        bc = struct.unpack_from('<I', b, 0 + off)[0]
        if bc == 0:
            break
        segs.append(b[off:off+bc])
        off += bc
    return segs


def summarize(b, label):
    print(f'\n=== {label}: {len(b)} bytes, {len(split_segments(b))} segment(s) ===')
    for si, seg in enumerate(split_segments(b)):
        recs = dump_records(seg)
        reloc = [r for r in recs if r[1] in ('RELOC','cRELOC','INTERSEG','cINTERSEG','SUPER')]
        lconst = sum(r[2] for r in recs if r[1] in ('LCONST','CONST'))
        print(f'  seg{si}: {len(recs)} recs, code={lconst}B, {len(reloc)} reloc recs')
        for op, nm, sz, det in reloc:
            print(f'     {nm:10s} {sz:4d}B  {det}')
    return b


def main():
    which = sys.argv[1] if len(sys.argv) > 1 else 'Tool027'
    vol = Volume(bytearray(open(SYSTEM_DISK, 'rb').read()))
    files = catalog_disk(vol)
    target = None
    for f in files:
        if which in f.path:
            target = f; break
    if not target:
        print('not found:', which); return
    gold = vol.read_file(target.path)
    print('target:', target.path, 'gold EOF', target.data_eof)
    summarize(gold, f'GOLD {target.path}')
    # find & run our builder — V = the volume dir name (first path component)
    V = '/' + target.path.strip('/').split('/')[0]
    import importlib
    for modname in ('expressload_files', 'toolsets', 'kernel_os', 'p8_driver', 'kernel_setup'):
        mod = importlib.import_module(f'diskbuilders.{modname}')
        bset = mod.builders(V)
        if target.path in bset:
            ours = bset[target.path]()
            summarize(ours, f'OURS {target.path}')
            return
    print('no builder found for', target.path, '(V=%r)' % V)


if __name__ == '__main__':
    main()
