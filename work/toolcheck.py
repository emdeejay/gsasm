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

SRC = 'ref/GSOS_6/IIGS.601.SRC'
TB  = SRC + '/GSToolbox'
FW  = SRC + '/GSFirmware'
BIN = 'ref/GSOS_6/tool_bin'
INCS = [d for d, _, _ in os.walk(TB)] + [d for d, _, _ in os.walk(FW)] + ['work/includes']

# ToolNNN -> (manager subdir, [object source files]). From build.tools; the
# object lists mirror linkrom.BANKS. Only tools we have BOTH source and a
# shipping binary for are listed.
TOOLMAP = {
    '014': ('WindMgr',    ['WindMgr.asm', 'Task.asm', 'NewCalls.asm', 'WCtlDef.asm', 'WDefProc.asm']),
    '015': ('MenuMgr',    ['MenuMgr.asm', 'PopUpProc.asm', 'WCM.asm']),
    '016': ('ControlMgr', ['ControlMgr.asm', 'DefProcs.asm', 'NewControl2.asm',
                           'SuperControl.asm', 'StatTextProc.asm', 'PicProc.asm']),
    '020': ('LineEdit',   ['le.asm', 'LineEditProc.asm']),
    '021': ('DialogMgr',  ['dialog.asm']),
    '022': ('Scrap',      ['scrap.asm']),
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


def de_express(path):
    """Concatenated CONST/LCONST code image of a (possibly ExpressLoad'd) tool."""
    d = open(path, 'rb').read()
    off = 0
    img = bytearray()
    while off < len(d):
        h = omf.parse_header(d[off:])
        bc = h['BYTECNT']
        if bc == 0:
            break
        nm = h['SEGNAME'].decode('mac_roman', 'replace').strip()
        if not nm.startswith('~ExpressLoad'):
            recs, _ = omf.parse_records(d[off:off + bc], h['DISPDATA'],
                                        h.get('NUMLEN', 4), h.get('LABLEN', 0))
            img += b''.join(r[2] for r in recs if r[1] in ('CONST', 'LCONST'))
        off += bc
    return bytes(img)


def golden(tool):
    for cand in (f'{BIN}/Tool{tool}#BA0000', f'{BIN}/Tool{tool}'):
        if os.path.exists(cand):
            return de_express(cand)
    return None


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

    # Extract the code image from the merged load segment
    img = bytearray()
    off = 0
    while off < len(result):
        h = omf.parse_header(result[off:])
        bc = h['BYTECNT']
        if bc == 0:
            break
        recs, _ = omf.parse_records(result[off:off + bc], h['DISPDATA'],
                                    h.get('NUMLEN', 4), h.get('LABLEN', 0))
        for r in recs:
            if r[1] in ('CONST', 'LCONST'):
                img += r[2]
        off += bc
    return bytes(img)


def check(tool, verbose=False):
    subdir, roots = TOOLMAP[tool]
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
