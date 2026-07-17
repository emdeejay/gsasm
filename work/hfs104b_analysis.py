#!/usr/bin/env python3
"""hfs104b_analysis.py — relocation-aware subtraction of HFS.FST 1.04b.

Same method as the 6.0.4 carry-bug recovery (docs/notes/hfs-fst-6.0.4-carry-bug.md),
applied to the community "1.04b" build (Geoff Body / Petar Puskarich):

  1. de-ExpressLoad all three HFS.FST images to flat code images.
  2. Build a byte-offset -> (segment, nearest-label, source Line) map for the
     6.0.1 original by replaying gsasm's own byte-exact placement (this is the
     leverage: we know every byte's provenance).
  3. difflib block-align 1.04b against the 6.0.1 original; classify each edit
     region as relocation fallout (single-byte 1->1) vs a real structural edit.
  4. Name every structural edit by its source routine.

Run:  python3 work/hfs104b_analysis.py
"""
import sys, os, difflib
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from gsasm import asm, omf, linkiigs
from gsasm.expressload import de_express

GSOS = 'ref/GSOS_6/IIGS.601.SRC/GS.OS'
CMN  = GSOS + '/Common'
INCS = [CMN] + [d for d, _, _ in os.walk(GSOS)] + ['work/includes']
HFS  = GSOS + '/FSTs/HFS'

ORIG_601 = 'ref/GSOS_6/fst_bin/HFS.FST#BD0000'
MOD_604  = 'tmp/hfs604/HFS.FST#BD0000'
MOD_104B = 'tmp/hfs104b/hfs.1.04b.fst#BD0000'


def build_offset_map():
    """Assemble+link 6.0.1 HFS.FST; return (image_len, list of per-byte-region
    (start, end, segname, label, Line)) reproducing gsasm's byte-exact layout."""
    objects = []
    for src in ('hfs.fst.main', 'hfs.fst.btree'):
        a = asm.assemble(f'{HFS}/{src}', [HFS] + INCS, defines={'DEBUGSYMBOLS': 0})
        objects.append((omf.emit(a), a))

    placed, _bases, _oi = linkiigs._place(objects, base_org=0)
    origin = placed[0][2]

    # Placement order == object-by-object, segment-by-segment, matching a.segs.
    seg_iter = [(a, seg) for (_ob, a) in objects for seg in a.segs]
    assert len(seg_iter) == len(placed), (len(seg_iter), len(placed))

    regions = []            # (start, end, segname, label, Line)
    for (segname, _recs, seg_base, _hdr, _asm), (a, seg) in zip(placed, seg_iter):
        assert seg.name == segname, (seg.name, segname)
        off = seg_base - origin
        cur_label = segname
        for item in seg.items:
            kind = item[0]
            if kind == 'global':          # ('global', name, off) — label def, 0 bytes
                cur_label = item[1]
                continue
            if kind == 'ds':              # ('ds', length, None) — reserved bytes
                n, line = item[1], None
            else:                          # 'code' — ('code', Line, bytearray, ...)
                line = item[1]
                n = len(item[2]) if item[2] is not None else 0
                if getattr(line, 'label', None):
                    cur_label = line.label
            if n:
                regions.append((off, off + n, segname, cur_label, line))
                off += n
    total = max(r[1] for r in regions)
    return total, regions


def locate(regions, offset):
    """Return (segname, label, Line) for the region containing offset."""
    for start, end, segname, label, line in regions:
        if start <= offset < end:
            return segname, label, line
    return None, None, None


def context_lines(regions, offset, before=6, after=6):
    """Return source Lines around the region containing offset."""
    idx = None
    for i, (start, end, *_r) in enumerate(regions):
        if start <= offset < end:
            idx = i
            break
    if idx is None:
        return []
    lo, hi = max(0, idx - before), min(len(regions), idx + after + 1)
    out = []
    for start, end, segname, label, line in regions[lo:hi]:
        out.append((start, label, line))
    return out


def fmt_line(line):
    lbl = (line.label or '').ljust(10)
    op  = (line.op or '')
    opd = (line.operand or '')
    return f'{lbl} {op:<8} {opd}'.rstrip()


def classify(orig, mod):
    """difflib block-align; return list of edit regions with classification."""
    sm = difflib.SequenceMatcher(a=orig, b=mod, autojunk=False)
    edits = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == 'equal':
            continue
        alen, blen = i2 - i1, j2 - j1
        single = (tag == 'replace' and alen == 1 and blen == 1)
        edits.append({
            'tag': tag, 'i1': i1, 'i2': i2, 'j1': j1, 'j2': j2,
            'alen': alen, 'blen': blen, 'single': single,
            'orig': bytes(orig[i1:i2]), 'mod': bytes(mod[j1:j2]),
        })
    return edits


# Minimal 65816 disassembler for the opcodes at the two fix sites, longa=longi=1
# (16-bit m,x — the mode both routines run in).  Validated below by disassembling
# the 6.0.1 image, whose instruction boundaries we already know from source.
_OPS = {
 0x00: ('brk #%02x', 2), 0x18: ('clc', 1), 0x38: ('sec', 1), 0xeb: ('xba', 1),
 0x1a: ('inc a', 1), 0x4a: ('lsr a', 1), 0x6a: ('ror a', 1), 0xca: ('dex', 1),
 0xa5: ('lda <%02x', 2), 0x85: ('sta <%02x', 2), 0x64: ('stz <%02x', 2),
 0x46: ('lsr <%02x', 2), 0x66: ('ror <%02x', 2), 0xe6: ('inc <%02x', 2),
 0x65: ('adc <%02x', 2),
 0x6d: ('adc %04x', 3), 0xad: ('lda %04x', 3), 0x8d: ('sta %04x', 3),
 0xed: ('sbc %04x', 3), 0x69: ('adc #%04x', 3), 0xa9: ('lda #%04x', 3),
 0xa0: ('ldy #%04x', 3), 0xa2: ('ldx #%04x', 3),
 0x90: ('bcc %+d', 2), 0xb0: ('bcs %+d', 2), 0xd0: ('bne %+d', 2),
 0xf0: ('beq %+d', 2), 0x80: ('bra %+d', 2), 0x82: ('brl %+d', 3),
 0x20: ('jsr %04x', 3), 0xb7: ('lda [<%02x],y', 2), 0x60: ('rts', 1),
}


def disasm(buf, start, end):
    """Disassemble buf[start:end] (16-bit m/x); yield '  addr: hex  mnemonic'."""
    pc = start
    while pc < end:
        op = buf[pc]
        info = _OPS.get(op)
        if info is None:
            yield f'  {pc:04x}: {op:02x}          .byte ${op:02x}'
            pc += 1
            continue
        fmt, ln = info
        b = buf[pc:pc + ln]
        if '%+d' in fmt:
            rel = b[1] - 256 if b[1] > 127 else b[1]
            txt = fmt % rel + f'   (-> {pc + 2 + rel:04x})'
        elif ln == 1:
            txt = fmt
        elif ln == 2:
            txt = fmt % b[1]
        else:
            txt = fmt % (b[1] | b[2] << 8)
        yield f'  {pc:04x}: {b.hex():<11} {txt}'
        pc += ln


def main():
    orig = de_express(ORIG_601)
    m604 = de_express(MOD_604)
    m104 = de_express(MOD_104B)
    print('=== de-ExpressLoad code image sizes ===')
    print(f'  6.0.1 original : {len(orig)}')
    print(f'  6.0.4 modified : {len(m604)}   (delta {len(m604)-len(orig):+d})')
    print(f'  1.04b modified : {len(m104)}   (delta {len(m104)-len(orig):+d})')
    print()

    total, regions = build_offset_map()
    print(f'=== offset map: gsasm byte-exact layout = {total} bytes '
          f'({"OK" if total == len(orig) else "MISMATCH vs %d" % len(orig)}) ===')
    print()

    for label, mod in (('6.0.4', m604), ('1.04b', m104)):
        edits = classify(orig, mod)
        singles = [e for e in edits if e['single']]
        struct  = [e for e in edits if not e['single']]
        print(f'=== {label}: edit regions vs 6.0.1 original ===')
        print(f'  total edit regions:                    {len(edits)}')
        print(f'  single-byte 1->1 (relocation-shift):   {len(singles)}')
        print(f'  structural edits (insert/delete/multi): {len(struct)}')
        for e in struct:
            seg, lbl, line = locate(regions, e['i1'])
            print()
            print(f'  --- {e["tag"]} orig[{e["i1"]:#06x}:{e["i2"]:#06x}] '
                  f'({e["alen"]} B: {e["orig"].hex()}) -> '
                  f'mod ({e["blen"]} B: {e["mod"].hex()}) ---')
            print(f'      segment {seg}  near label {lbl}')
        print()

    # --- Disassemble the two functional fix sites (1.04b vs 6.0.1) -----------
    # WORD_MULTIPLY shift-add loop and ET_LOG_2_PHYS @ok 32-bit add.  The
    # multiply loop head is BEFORE the -3 delete, so it sits at the same offset
    # in both; ET_LOG_2_PHYS is past the delete, so 1.04b is 3 bytes earlier.
    sites = [
        ('WORD_MULTIPLY (16x16 shift-add loop)', 0x2cd7, 0x2cea, 0),
        ('ET_LOG_2_PHYS @ok (a1 += d1)',         0x56ac, 0x56cc, -3),
    ]
    for title, a, b, shift in sites:
        print(f'=== {title} ===')
        print('  6.0.1 original:')
        for ln in disasm(orig, a, b):
            print('  ' + ln)
        print('  1.04b modified:')
        for ln in disasm(m104, a + shift, b + shift):
            print('  ' + ln)
        print()


if __name__ == '__main__':
    main()
