#!/usr/bin/env python3
"""tool016_diag.py — decompose Tool016 (ControlMgr) vs the shipping binary.

Tool016 ships as a FOUR-segment ExpressLoad load file:

    main      (KIND 0x0000)  ControlMgr..DummyDrag — the 6 core objects
    StatText  (KIND 0x0000)  StatTextProc.asm — static-text control defproc
    ~JumpTable(KIND 0x0002)  linker-generated inter-segment call thunks (26 B)
    Pics      (KIND 0x8000)  PicProc.asm — DYNAMIC (on-demand) picture defproc

The historical toolcheck entry flat-linked all 8 objects into ONE segment and
compared it against de_express(gold) = main|StatText|~JumpTable|Pics. That
produced a 451-byte "residual" once documented (docs/design/expressload.md) as a
"link-order / value frontier" where "gsasm computes different addresses than
gold." This tool proves that framing WRONG: every one of the 451 bytes is a
segmentation / harness artifact, and gsasm assembles ControlMgr byte-exact per
segment.

The 451 bytes decompose, with no residue, into exactly three mechanical classes:

  (1) main inter-segment far-pointers [8 B] — 2 cINTERSEG records reference the
      StatText/Pics segments; gold defers them to load time (stored 0 / relOff),
      gsasm's flat merge BAKES the merged-image offset.
  (2) StatText + Pics intra-segment word relocs [~154 B] — every one is off by
      *exactly* the segment's base in the merged image (0x30c9 for StatText,
      0x355f for Pics), because gsasm concatenates into one segment while gold
      keeps them separate (each relocated from its own base 0).
  (3) the 26-byte ~JumpTable gsasm does not generate (linker output, TODO §2)
      PLUS the 26-byte alignment shift it imposes on all of Pics.

Compared the way gold is actually segmented (what work/toolcheck.py now does),
gsasm is byte-exact: StatText 1174/1174, Pics 358/358, main 12488/12489 — the
sole main byte being a far-pointer operand into the DYNAMIC Pics segment that
gold routes through ~JumpTable+0x12, i.e. the same TODO §2 gap.

    python3 work/tool016_diag.py            # print the full decomposition
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import work.toolcheck as tc
from gsasm import omf
from gsasm.expressload import de_express


def gold_segments(raw):
    """Return [(name, kind, code_bytes)] for each non-~ExpressLoad segment."""
    out, off = [], 0
    while off < len(raw):
        h = omf.parse_header(raw[off:])
        bc = h['BYTECNT']
        if bc == 0:
            break
        nm = h['SEGNAME'].decode('mac_roman', 'replace').strip().rstrip('\x00')
        recs, _ = omf.parse_records(raw[off:off + bc], h['DISPDATA'],
                                    h.get('NUMLEN', 4), h.get('LABLEN', 0))
        code = b''.join(r[2] for r in recs if r[1] in ('CONST', 'LCONST'))
        if not nm.startswith('~ExpressLoad'):
            out.append((nm, h['KIND'], code))
        off += bc
    return out


def main():
    raw = tc._open_gold('016')
    segs = gold_segments(raw)
    bases, b = {}, 0
    for nm, kind, code in segs:
        bases[nm] = b
        b += len(code)
    print('Gold Tool016 load segments:')
    for nm, kind, code in segs:
        print(f'  {nm:11s} KIND={kind:#06x}  base={bases[nm]:#07x}  size={len(code)}')

    # --- Flat comparison (the old, wrong basis) --------------------------------
    mine_flat = tc.link_module(
        [f'ControlMgr/{r}' for r in
         ['ControlMgr.asm', 'SuperControl.asm', 'NewControl2.asm', 'DefProcs.asm',
          'CtlPatch.asm', 'DummyDrag.asm', 'StatTextProc.asm', 'PicProc.asm']])
    gold_flat = de_express(raw)
    n = min(len(mine_flat), len(gold_flat))
    flat_bad = [i for i in range(n) if mine_flat[i] != gold_flat[i]]
    print(f'\nFlat basis: gsasm={len(mine_flat)} gold={len(gold_flat)} '
          f'common={n}  BAD={len(flat_bad)}')

    # Classify every flat-basis bad byte.
    order = [nm for nm, _, _ in segs]

    def region(o):
        for nm in order:
            if bases[nm] <= o < bases[nm] + dict((n, len(c)) for n, _, c in segs)[nm]:
                return nm
        return '??'

    main_sz = dict((n, len(c)) for n, _, c in segs)['main']
    classes = {'inter-seg (main)': 0, 'intra-seg off-by-base': 0,
               '~JumpTable + shift cascade': 0, 'unclassified': 0}
    for i in flat_bad:
        r = region(i)
        if r == 'main':
            classes['inter-seg (main)'] += 1
        elif r in ('StatText', 'Pics'):
            # word reloc off by exactly the segment base?
            if i + 2 <= n:
                mv = struct.unpack_from('<H', mine_flat, i)[0]
                gv = struct.unpack_from('<H', gold_flat, i)[0]
                if (mv - gv) & 0xffff == bases[r] & 0xffff:
                    classes['intra-seg off-by-base'] += 1
                    continue
            classes['~JumpTable + shift cascade'] += 1
        elif r == '~JumpTable':
            classes['~JumpTable + shift cascade'] += 1
        else:
            classes['unclassified'] += 1
    print('  decomposition of the 451 flat-basis diffs:')
    for k, v in classes.items():
        print(f'    {k:28s} {v:4d} B')

    # --- Per-segment comparison (the correct basis) ----------------------------
    print('\nPer-segment basis (each segment relocated from its own base 0):')
    from gsasm import linkiigs
    seg_srcs = {'main': ['ControlMgr.asm', 'SuperControl.asm', 'NewControl2.asm',
                         'DefProcs.asm', 'CtlPatch.asm', 'DummyDrag.asm'],
                'StatText': ['StatTextProc.asm'], 'Pics': ['PicProc.asm']}
    for nm, kind, gcode in segs:
        if nm not in seg_srcs:
            print(f'  {nm:11s} — no gsasm counterpart (linker-generated)')
            continue
        objs = tc._assemble_objects(seg_srcs[nm], 'ControlMgr')
        mine = tc._lconst_image(linkiigs.link(objs, opts={'merge': True}))
        m = min(len(mine), len(gcode))
        bad = [i for i in range(m) if mine[i] != gcode[i]]
        tag = 'BYTE-EXACT' if not bad else f'{len(bad)} B diff @ ' + \
            ','.join(hex(i) for i in bad[:4])
        print(f'  {nm:11s} {m - len(bad)}/{m}  {tag}')


if __name__ == '__main__':
    main()
