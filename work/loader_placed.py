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
The broader GS.OS kernel is now byte-exact as well; this oracle remains the
Loader-specific guard.
Run: `python3 work/loader_placed.py`.
"""
import sys, os
from _common import WORK, byte_match, ensure_repo_on_path, mismatch_offsets
ensure_repo_on_path(WORK, os.path.join(WORK, 'diskbuilders'))
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
    # The grouped-placed algorithm now lives in the BUILDER
    # (kernel_os._build_loader_bin), which _build_gsos uses for the real GS.OS.
    # This oracle just diffs that output against golden — ONE implementation, no
    # drift. Returns (image_bytes, meta) where meta = [(seg_info, (obj,emit))].
    return k._build_loader_bin(tuple(order), base0, return_meta=True)


def main():
    g = golden()
    lb, _ = build(['loader', 'loader_lc'])
    m, n = byte_match(lb, g)
    diff = mismatch_offsets(lb, g)
    ff = sum(1 for i in diff if lb[i] == 0xff)
    print(f'grouped-placed Loader.bin: len={len(lb)} (golden 16590)')
    print(f'  match {m}/{len(g)} ({100*m//len(g)}%)  '
          f'diff={len(diff)}   [current link-order build ~= 64%]')
    if not diff:
        print('  BYTE-EXACT — CASE ON + dc.w char-literal + import-diff EXPR + '
              'placed-base symtab all landed.')
    else:
        print(f'  residual: {ff} ffff (DC.W import-diff), '
              f'{len(diff)-ff} other; offsets {[hex(i) for i in diff[:8]]}')


if __name__ == '__main__':
    main()
