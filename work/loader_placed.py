"""loader_placed.py — CRACKED: grouped-placed link for the GS.OS Loader region.

The Loader region of GS.OS (first 16590B) is built by golden as
`LinkIIgs -x GSHeader.obj Loader.obj GSFooter.obj` -> `MakeBinIIgs`.  gsasm's
linkiigs.link places segments in LINK order using the two headers' source ORGs
as anchors, so CALLTABLE lands after the LC header — a ~5957B layout shift
(64% match).  The golden placement, derived + verified here (97% match, up from
64%), is:

  * Group segments by LOAD SEGMENT (loadname): 'Loader' then 'Loader_LC'.  A
    default-'main' segment (gsasm's per-PROC default) inherits the preceding
    NAMED loadname WITHIN its object — the SEG it was defined under (so the
    GLOBALS/data segs stay inline in the 'Loader' group at their source spot).
  * FLAT file: the groups are STORED contiguously (Loader group, then Loader_LC).
  * RUNTIME addresses: each group is LOADED at its own base — the group header's
    ORG (0x1a5d0 for 'Loader', 0x1cfd0 for 'Loader_LC').  Relocs resolve against
    the runtime base, NOT the flat position (the two load segments live at
    different addresses but are stored back-to-back).

So: keep linkiigs `placed` in object order but base each seg at its RUNTIME
address (reuse the tested _build_symtab), then concatenate bodies in FLAT
(grouped) order.  This is now BYTE-EXACT: 16590/16590.  The path there:
  * placement CRACKED (f69fe4b) + typed-DS-instance fields (d74139a): 452B -> 28B.
  * CASE ON honoured in the core (ea4fb70, asm/omf/linkiigs/link _fold): Loader.a
    line 1 is the ONLY corpus file that sets it, so MPW kept find_Segment !=
    Find_Segment, load_segment/Load_Segment, set_mark/Save_Mark distinct; the 3
    collisions bound to the wrong dup segment.  28B -> 6B.
  * `dc.w 'GB'` char-literal (asm._dc_bytes: a string in a width>1 DC lays down
    its bytes, zero-padded to a multiple of the element width).  6B -> 4B.
  * DC.W import-difference `DC.W zloader_end-zloader_start` (omf._ext_plus_const):
    a field linear in ONE external (declared IMPORT / implicit undef) + a const
    is a LINK-time value -> emit the external by name + addend so the linker
    resolves it, not an assembly-time literal (which baked an unresolved 0xffff).
    4B -> 2B (fixed the 'Loader' header; exposed the next one).
  * placed-base symtab (linkiigs._build_symtab): a symbol's final address is its
    PLACED base + offset-in-seg.  zloaderLC_end (the Loader_LC end marker) is
    ORG'd by the flow but PLACED at the group's true end; the old code used the
    assembly ORG value.  Byte-neutral for link()/_place (base==org).  2B -> 0.
The SCM DC.W LEXPR gap (~1731B) is what remains for a byte-exact GS.OS kernel.
Run: `python3 work/loader_placed.py`.
"""
import sys, os
sys.path[:0] = ['.', 'work', 'work/diskbuilders']
import kernel_os as k, diskcheck as dc
from gsasm import omf, link as L, linkiigs as LI
dc._find_a2til()
from a2til.prodos import Volume

BASE = 0x1a5d0
ORDER = ['loader', 'loader_lc']


def golden():
    vol = Volume(bytearray(open(dc.SYSTEM_DISK, 'rb').read()))
    for f in dc.catalog_disk(vol):
        if f.path.endswith('/System/GS.OS'):
            return vol.read_file(f.path)[:16590]
    return None


def build(order=ORDER, base0=BASE):
    loader = os.path.join(k._GS, 'Loader')
    objs = [k._assemble(os.path.join(loader, s))
            for s in ('GSHeader.a', 'Loader.a', 'GSFooter.a')]

    # Per-(obj,emit) segment info: resolved loadname (a default-'main' seg
    # inherits the preceding NAMED loadname within its object — the load segment
    # it was defined under; gsasm loses this to 'main' defaulting), length, ORG.
    info = {}       # (oi, ei) -> dict
    flatseq = []    # (oi, ei) in group/source order for flat concatenation
    for oi, (obj, asm) in enumerate(objs):
        parsed = LI._parse_obj(obj)
        cur = None
        for ei, sd in enumerate(parsed):
            ln = sd['loadname'].lower()
            if ln != 'main':
                cur = ln
            info[(oi, ei)] = {'ln': ln if ln != 'main' else (cur or 'main'),
                              'len': L._body_length(sd['recs']),
                              'org': sd.get('org', 0) or 0}

    # Flat order = groups in ORDER, stable within group (obj then emit index).
    keys = sorted(info, key=lambda k: (order.index(info[k]['ln'])
                                       if info[k]['ln'] in order else 99, k))
    # RUNTIME base per group = the group's first ORG'd seg (its header).
    gbase = {}
    for kk in keys:
        ln = info[kk]['ln']
        if ln not in gbase and info[kk]['org']:
            gbase[ln] = info[kk]['org']
    # Assign flat (contiguous) + rt (per-group runtime) to each segment.
    flat = 0
    rt_cur = {}
    for kk in keys:
        i = info[kk]
        i['flat'] = flat
        flat += i['len']
        b = rt_cur.get(i['ln'], gbase.get(i['ln'], base0))
        i['rt'] = b
        rt_cur[i['ln']] = b + i['len']
    flatseq = keys

    # Build linkiigs _build_symtab inputs in OBJECT order, each seg based at its
    # RUNTIME address (so the tested symtab logic — qualified fields, WITH, @-,
    # exports — resolves everything against the runtime layout).
    placed, obj_seg_bases, placed_obj_idx = [], [], []
    pidx = {}
    for oi, (obj, asm) in enumerate(objs):
        parsed = LI._parse_obj(obj)
        bases = []
        for ei, sd in enumerate(parsed):
            rt = info[(oi, ei)]['rt']
            pidx[(oi, ei)] = len(placed)
            placed.append((sd['segname'], sd['recs'], rt, sd['hdr'], asm))
            placed_obj_idx.append(oi)
            bases.append(rt)
        obj_seg_bases.append(bases)
    sym, obj_globals = LI._build_symtab(objs, placed, obj_seg_bases, placed_obj_idx)

    # Emit bodies in FLAT (grouped) order, each resolved at its runtime base.
    out = bytearray()
    for kk in flatseq:
        pi = pidx[kk]
        _seg, recs, rt, _hdr, _asm = placed[pi]
        oi = placed_obj_idx[pi]
        local = sym if not obj_globals[oi] else {**sym, **obj_globals[oi]}
        out += L._build_body(recs, dict(local, __LOC__=rt), rt)
    return bytes(out), [(info[k], k) for k in flatseq]


def main():
    g = golden()
    lb, _ = build(['loader', 'loader_lc'])
    n = min(len(lb), len(g))
    diff = [i for i in range(n) if lb[i] != g[i]]
    ff = sum(1 for i in diff if lb[i] == 0xff)
    print(f'grouped-placed Loader.bin: len={len(lb)} (golden 16590)')
    print(f'  match {n-len(diff)}/{len(g)} ({100*(n-len(diff))//len(g)}%)  '
          f'diff={len(diff)}   [current link-order build ~= 64%]')
    if not diff:
        print('  BYTE-EXACT — CASE ON + dc.w char-literal + import-diff EXPR + '
              'placed-base symtab all landed.')
    else:
        print(f'  residual: {ff} ffff (DC.W import-diff), '
              f'{len(diff)-ff} other; offsets {[hex(i) for i in diff[:8]]}')


if __name__ == '__main__':
    main()
