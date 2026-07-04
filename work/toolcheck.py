#!/usr/bin/env python3
"""toolcheck.py — validate gsasm against the shipping System 6.0.1 tool files.

Assembles each toolbox module from the GS/OS 6.0.1 source (ref/GSOS_6/IIGS.601.SRC/
GSToolbox), links its object segments, and compares the resulting code image
byte-for-byte against the shipping ToolNNN binary from the 6.0.1 System Disk.

    python3 work/toolcheck.py          # summary over every mapped tool
    python3 work/toolcheck.py 022      # one tool, with first-diff detail

The source -> ToolNNN map is taken from GSToolbox/build.tools; the multi-object
composition per manager mirrors work/linkrom.py's proven module lists. Golden
binaries live in ref/GSOS_6/tool_bin/ (extracted from the disk images with cadius).

The shipping tools are ExpressLoad'd OMF: a leading '~ExpressLoad' directory
segment plus the real load segments (LCONST code image + a SUPER relocation
dictionary). de_express() returns the concatenated CONST/LCONST image — the
segment-relative code the loader relocates — which is what gsasm's linked image
is compared against (exactly the flat()-image comparison work/buildrom.py uses
for the ROM banks).

STATUS (2026-07): the OMF emit+link path resolves cross-segment/-object
references, including the per-tool dispatch table (DC.L routine-1) — the lever
that gates every tool. Single-object managers reach 98-99% byte-identical
(DialogMgr, ListMgr, Scrap); the corpus sits at ~78%.

Known remaining residuals (per-module levers, not a shared blocker):
  * bank-byte immediates `lda #^Label` — a high-word/bank relocation gsasm
    currently resolves to 0 (the low-word `lda #Label` form resolves correctly);
  * multi-object managers (WindMgr, ControlMgr, ...) carry a per-segment SIZING
    drift (an instruction assembled n bytes off) that cascades through the DC.L
    address tables — the same class the ROM effort ground through module by
    module;
  * a small trailing code stub (~a few dozen bytes) some tools carry.
These live in the OMF emitter, which the byte-exact ROM build depends on, so any
fix must be re-validated with work/buildrom.py + objcheck + linkcheck.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from gsasm import asm, omf, link, linkiigs
from gsasm.expressload import de_express

SRC = 'ref/GSOS_6/IIGS.601.SRC'
TB  = SRC + '/GSToolbox'
FW  = SRC + '/GSFirmware'
BIN = 'ref/GSOS_6/tool_bin'
INCS = [d for d, _, _ in os.walk(TB)] + [d for d, _, _ in os.walk(FW)] + ['work/includes']

# ToolNNN -> (manager subdir, entry).
# entry is either:
#   [files]                    — single-segment flat link; compare against de_express(gold)
#   {'segments': [...], ...}   — multi-segment tool; per-segment comparison
#
# Multi-segment entry keys:
#   'segments': list of dicts, each with:
#       'gold_name':  segment name in the gold ExpressLoad binary (matched by SEGNAME)
#       'srcs':       [relative source files] for this segment's main objects
#       'extern_base': optional int — if set, this segment's symbols are injected as
#                      extern overrides at this base address into PRECEDING segments
#
# Object file lists mirror the MPW makefile link order for each tool.
# This is critical: (a) symbol addresses depend on placement order, and (b) for
# duplicate GLOBAL exports (ENTRY in multiple objects), last-wins in linkiigs
# matches MPW LinkerIIgs behaviour — so the last object's definition prevails.
TOOLMAP = {
    '014': ('WindMgr',    ['windmgr.asm', 'task.asm', 'NewCalls.asm', 'WDefProc.asm',
                           'WCtlDef.asm', 'WMPatch.asm', '../MenuMgr/wcm.asm']),
    # MenuMgr has a multi-segment ExpressLoad binary:
    #   MainTool (menumgr + wcm) at base 0
    #   PopUpProc (popupproc) at base 0x030000 (dynamic/bank segment)
    # Compare each segment independently.
    '015': ('MenuMgr',    {'segments': [
        {'gold_name': 'MainTool',  'srcs': ['menumgr.asm', 'wcm.asm'],
         'extern_srcs': [('PopUpProc', 0x030000, ['popupproc.asm'])]},
        {'gold_name': 'PopUpProc', 'srcs': ['popupproc.asm']},
    ]}),
    # Real link order from ControlMgr/makefile — was missing CtlPatch + DummyDrag
    # (DummyDrag defines WindDragRect, ControlMgr's first divergence).
    '016': ('ControlMgr', ['ControlMgr.asm', 'SuperControl.asm', 'NewControl2.asm',
                           'DefProcs.asm', 'CtlPatch.asm', 'DummyDrag.asm',
                           'StatTextProc.asm', 'PicProc.asm']),
    '020': ('LineEdit',   ['le.asm', 'LineEditProc.asm']),
    '021': ('DialogMgr',  ['dialog.asm']),
    '022': ('Scrap',      ['scrap.asm', 'common.asm']),
    '027': ('FontMgr',    ['fm.asm', 'scale.asm']),
    '028': ('ListMgr',    ['ListMgr.asm']),
}


def flat(seg):
    """Segment-relative code image of one gsasm segment."""
    out = bytearray()
    for it in seg.items:
        if it[0] == 'code':
            out += it[2]
        elif it[0] == 'ds':
            out += b'\x00' * it[1]
    return bytes(out)


def _open_gold(tool):
    """Return raw bytes of the gold binary for this tool, or None."""
    for cand in (f'{BIN}/Tool{tool}#BA0000', f'{BIN}/Tool{tool}'):
        if os.path.exists(cand):
            return open(cand, 'rb').read()
    return None


def golden(tool):
    """Return flat de_express'd code image for simple single-segment tools."""
    raw = _open_gold(tool)
    if raw is None:
        return None
    return de_express(raw)


def _gold_segment(raw_bytes, gold_name):
    """Extract the LCONST image of one named segment from an ExpressLoad binary."""
    off = 0
    while off < len(raw_bytes):
        h = omf.parse_header(raw_bytes[off:])
        bc = h['BYTECNT']
        if bc == 0:
            break
        nm = h['SEGNAME'].decode('mac_roman', 'replace').strip().rstrip('\x00')
        if nm == gold_name:
            recs, _ = omf.parse_records(raw_bytes[off:off + bc], h['DISPDATA'],
                                        h.get('NUMLEN', 4), h.get('LABLEN', 0))
            return b''.join(r[2] for r in recs if r[1] in ('CONST', 'LCONST'))
        off += bc
    return None


def _assemble_objects(srcs, subdir):
    """Assemble a list of source paths (relative to TB/subdir) into OMF objects."""
    objects = []
    for r in srcs:
        a = asm.assemble(f'{TB}/{subdir}/{r}', INCS)
        obj = omf.emit(a)
        objects.append((obj, a))
    return objects


def _compute_externs(srcs, subdir, base):
    """Assemble srcs and compute their exported symbol addresses at given base."""
    asm_segs_list = []
    for r in srcs:
        a = asm.assemble(f'{TB}/{subdir}/{r}', INCS)
        asm_segs_list.append(a)

    externs = {}
    cur_base = base
    for a in asm_segs_list:
        asm_segs = [s for s in a.segs if s.items or s.name]
        seg_bases = []
        for seg in asm_segs:
            seg_bases.append(cur_base)
            sz = 0
            for it in seg.items:
                if it[0] == 'code':
                    sz += len(it[2])
                elif it[0] == 'ds' and isinstance(it[1], int):
                    sz += it[1]
            cur_base += sz
        for lab, v in a.symbols.items():
            sg_idx = a.symseg.get(lab)
            if sg_idx is None or not isinstance(v, int):
                continue
            if sg_idx < 0 or sg_idx >= len(asm_segs):
                continue
            seg_base = seg_bases[sg_idx]
            seg_org = asm_segs[sg_idx].org or 0
            abs_val = (v & 0xFFFFFF) if seg_org else ((seg_base + v) & 0xFFFFFF)
            externs[lab.upper()] = abs_val
    return externs


def _lconst_image(linked_bytes):
    """Extract the flat LCONST code image from a merged linkiigs result."""
    img = bytearray()
    off = 0
    while off < len(linked_bytes):
        h = omf.parse_header(linked_bytes[off:])
        bc = h['BYTECNT']
        if bc == 0:
            break
        recs, _ = omf.parse_records(linked_bytes[off:off + bc], h['DISPDATA'],
                                    h.get('NUMLEN', 4), h.get('LABLEN', 0))
        for r in recs:
            if r[1] in ('CONST', 'LCONST'):
                img += r[2]
        off += bc
    return bytes(img)


def link_module(roots):
    """Assemble each object to OMF (cross-segment/-object references become
    relocation records), place every segment sequentially into one load image,
    and resolve each segment's relocations against a FULL symbol table built
    from gsasm's own symbols (segment names + every label at base+offset).

    Thin wrapper over gsasm.linkiigs.link — all linking logic lives there.
    Returns the concatenated, relocated code image."""
    objects = []
    for r in roots:
        a = asm.assemble(f'{TB}/{r}', INCS)
        obj = omf.emit(a)
        objects.append((obj, a))

    # linkiigs.link builds the full symbol table and resolves all relocs
    result = linkiigs.link(objects, opts={'merge': True})
    return _lconst_image(result)


def _check_multiseg(tool, subdir, seg_specs, verbose=False):
    """Check a multi-segment tool: each segment compared independently."""
    raw = _open_gold(tool)
    if raw is None:
        return tool, subdir, None, "no golden binary"

    tot_m = tot_n = 0
    tot_mine = tot_gold = 0
    first_diff_info = None

    for seg_spec in seg_specs:
        gold_name = seg_spec['gold_name']
        srcs = seg_spec['srcs']
        extern_specs = seg_spec.get('extern_srcs', [])

        g_seg = _gold_segment(raw, gold_name)
        if g_seg is None:
            continue

        # Build extern overrides from any declared extern segments
        externs = {}
        for _xname, xbase, xsrcs in extern_specs:
            externs.update(_compute_externs(xsrcs, subdir, xbase))

        try:
            objs = _assemble_objects(srcs, subdir)
            result = linkiigs.link(objs, opts={'merge': True, 'extern': externs})
            mine_seg = _lconst_image(result)
        except Exception as e:
            return tool, subdir, None, f"{type(e).__name__}: {e}"

        n = min(len(mine_seg), len(g_seg))
        diffs_i = [i for i in range(n) if mine_seg[i] != g_seg[i]]
        m = n - len(diffs_i)
        tot_m += m
        tot_n += n
        tot_mine += len(mine_seg)
        tot_gold += len(g_seg)

        if verbose and diffs_i and first_diff_info is None:
            i = diffs_i[0]
            first_diff_info = (gold_name, i, mine_seg[i], g_seg[i],
                               mine_seg[max(0,i-4):i+8], g_seg[max(0,i-4):i+8])

    pct = (100 * tot_m // tot_n) if tot_n else 0
    if verbose:
        print(f"Tool{tool} ({subdir}): gsasm={tot_mine} gold={tot_gold} "
              f"match {tot_m}/{tot_n} ({pct}%)")
        if first_diff_info:
            gn, i, mi, gi, m_ctx, g_ctx = first_diff_info
            print(f"  first diff in {gn!r} @ {i:#06x}: gsasm={mi:02x} gold={gi:02x}")
            print(f"    gsasm {m_ctx.hex()}")
            print(f"    gold  {g_ctx.hex()}")
    return tool, subdir, (pct, tot_m, tot_n, tot_mine, tot_gold), None


def check(tool, verbose=False):
    entry = TOOLMAP[tool]
    subdir, spec = entry
    if isinstance(spec, dict):
        return _check_multiseg(tool, subdir, spec['segments'], verbose=verbose)

    roots = spec
    g = golden(tool)
    if g is None:
        return tool, subdir, None, "no golden binary"
    try:
        mine = link_module([f'{subdir}/{r}' for r in roots])
    except Exception as e:
        return tool, subdir, None, f"{type(e).__name__}: {e}"
    n = min(len(mine), len(g))
    m = sum(1 for i in range(n) if mine[i] == g[i]) if n else 0
    pct = (100 * m // n) if n else 0
    if verbose:
        print(f"Tool{tool} ({subdir}): gsasm={len(mine)} gold={len(g)} "
              f"match {m}/{n} ({pct}%)")
        for i in range(n):
            if mine[i] != g[i]:
                print(f"  first diff @ {i:#06x}: gsasm={mine[i]:02x} gold={g[i]:02x}")
                print(f"    gsasm {mine[max(0,i-4):i+8].hex()}")
                print(f"    gold  {g[max(0,i-4):i+8].hex()}")
                break
    return tool, subdir, (pct, m, n, len(mine), len(g)), None


def main():
    if len(sys.argv) > 1:
        t = sys.argv[1].lstrip('Tool').zfill(3)
        if t not in TOOLMAP:
            print(f"unknown/unmapped tool {t}; mapped: {', '.join(sorted(TOOLMAP))}")
            return
        check(t, verbose=True)
        return
    print(f"{'Tool':7} {'Manager':12} {'match':>7}  {'bytes (gsasm/gold)':>20}")
    tot_m = tot_n = 0
    for t in sorted(TOOLMAP):
        _, sub, res, err = check(t)
        if res is None:
            print(f"Tool{t}  {sub:12} {'--':>7}  {err}")
            continue
        pct, m, n, lg, lo = res
        tot_m += m; tot_n += n
        print(f"Tool{t}  {sub:12} {pct:>6}%  {lg:>8}/{lo:<8}  ({m}/{n} bytes)")
    if tot_n:
        print(f"\nCORPUS raw code-image match: {tot_m}/{tot_n} ({100*tot_m//tot_n}%)")


if __name__ == '__main__':
    main()
