#!/usr/bin/env python3
"""Native toolbox-bank linker (LinkIIgs-equivalent) for ROM 03.

linkiigs placed the toolbox object segments into three bank load-segments
(bankFE@$FE0000, bankFC@$FC0000, bankFD@$FD0000), each a flat image, then
makebiniigs split them into ROM.FE/FC/FD. The bank groupings and object order
come from the original ROM/MakeFile recipe (lines 82..164).

This module assembles each object with gsasm, emits its OMF object, places its
segments consecutively within its bank (link order), builds a global symbol
table, then resolves every OMF relocation record against the final addresses to
produce the bank images. Validated against rom.map (the original linker's
symbol->address map) and the real ROM.FE/FC/FD.
"""
import sys, os, re, glob, struct
sys.path.insert(0, '.')
from gsasm import asm, omf

ROOT = 'work/romsrc/GS_ROM'
INCS = ['work/includes'] + [d for d, _, _ in os.walk(ROOT)]

BANKS = {
    0xFE: ['tl/tl.asm', 'tl/loading.asm', 'toolpatch/toolpatch.asm',
           'qd/INIT.asm', 'qd/ENV.asm', 'qd/UTILS.asm', 'qd/SLABS.asm',
           'qd/RECTS.asm', 'qd/LINES.asm', 'qd/slices.asm', 'qd/pixelmaps.asm',
           'qd/SHIFTS.asm', 'qd/clipping.asm', 'qd/cursor.asm', 'qd/regions.asm',
           'qd/rgndefs.asm', 'qd/text.asm', 'qd/conics.asm', 'qd/polys.asm',
           'misc.tools/misc.tools.asm', 'text.tools/text.tools.asm',
           'desk/desk.asm', 'desk/cdacalls.asm', 'desk/cdamenu.asm',
           'desk/ndacalls.asm', 'events/em.asm', 'intmath/im.asm',
           'common/common.asm', 'misc.tools/queue.asm'],
    0xFC: ['mm/mm.asm', 'mm/peeker.asm', 'sane/sane.asm', 'sane/elems.asm',
           'lineedit/le.asm', 'lineedit/LineEditProc.asm', 'dialogmgr/dialog.asm',
           'scrap/scrap.asm', 'fontmgr/fm.asm', 'fontmgr/scale.asm',
           'sound/sound.aii', 'adb/adb.asm', 'scheduler/scheduler.asm',
           'qd/font.asm', 'kidding/kidding.asm', 'kidding/morekidding.asm',
           'ListMgr/ListMgr.asm', 'QD/CallTable.asm', 'misc.tools/Converter.asm',
           'misc.tools/InterruptState.asm'],
    0xFD: ['WindMgr/WindMgr.asm', 'WindMgr/Task.asm', 'WindMgr/NewCalls.asm',
           'WindMgr/WCtlDef.asm', 'WindMgr/WDefProc.asm', 'MenuMgr/MenuMgr.asm',
           'MenuMgr/PopUpProc.asm', 'MenuMgr/WCM.asm', 'ControlMgr/ControlMgr.asm',
           'ControlMgr/DefProcs.asm', 'ControlMgr/NewControl2.asm',
           'ControlMgr/SuperControl.asm', 'ControlMgr/StatTextProc.asm',
           'ControlMgr/PicProc.asm', 'tl/MsgByName.asm', 'tl/MessageCenter.asm',
           'tl/StartStop.asm', 'tl/textstate.asm', 'tl/mount.asm',
           'misc.tools/RomDataMgr.asm', 'appletalk/aptalk.aii',
           'appletalk/atp_includes.aii', 'appletalk/lap_includes.aii'],
}
BANK_ORDER = [0xFE, 0xFC, 0xFD]

# asmiigs `-d NAME=VALUE` command-line defines, per object (from the per-dir
# makefiles): RomDataMgr is built `Asmiigs ROMDataMgr.asm -d Big=1`.
DEFINES = {'misc.tools/RomDataMgr.asm': {'Big': 1}}


def src_path(rel):
    cand = ROOT + '/' + rel
    if os.path.exists(cand):
        return cand
    base = os.path.basename(rel)
    for g in glob.glob(ROOT + '/**/' + base, recursive=True):
        if os.path.basename(g).lower() == base.lower():
            return g
    for g in glob.glob(ROOT + '/**', recursive=True):
        if g.lower().endswith('/' + rel.lower()):
            return g
    return None


def parse_map():
    raw = open(ROOT + '/ROM/rom.map', 'rb').read().decode('mac_roman', 'replace')
    sym2val = {}
    for r in raw.split('\r'):
        m = re.match(r'(\S+)\s+[PG][DR]\|[0-9A-F]{4}\s+[0-9A-F]{4}:[0-9A-F]{4}'
                     r'\s+[0-9A-F]{8}\|[0-9A-F]{4} [0-9A-F]{4} [0-9A-F]{8}\|([0-9A-F]{8})', r)
        if m:
            sym2val[m.group(1).upper()] = int(m.group(2), 16)
    return sym2val


def split_obj(blob):
    """Split a multi-segment OMF object into per-segment (header, recs, length)."""
    segs = []
    i = 0
    while i < len(blob):
        h = omf.parse_header(blob[i:])
        recs, _ = omf.parse_records(blob[i:i+h['BYTECNT']], h['DISPDATA'],
                                    h['NUMLEN'], h['LABLEN'])
        segs.append((h, recs))
        if h['BYTECNT'] == 0:
            break
        i += h['BYTECNT']
    return segs


def place():
    """Assemble + place all segments. Returns (placements, gtab).
    gtab['defs'][name] = [(linkidx, addr, kind)] for every cross-module definition
    (kind: 'export' public / 'entry' private same-assembly / 'local'). A reference
    binds to the FIRST definition in link order, EXCLUDING other-file ENTRY defs
    (per MPW: ENTRY is same-assembly only; multiple external defs -> first wins).
    Each placement carries 'linkidx' (its module's link-order position)."""
    placements = {b: [] for b in BANK_ORDER}
    defs = {}                # name -> [(linkidx, addr, kind)]
    linkidx = 0
    for bank in BANK_ORDER:
        org = bank << 16
        off = 0
        for rel in BANKS[bank]:
            p = src_path(rel)
            a = asm.assemble(p, INCS, defines=DEFINES.get(rel))
            blob = omf.emit(a)
            objsegs = split_obj(blob)
            asm_segs = [s for s in a.segs if s.items or s.name]
            bases = []
            msym = {}        # this module's ENTRY/EXPORT symbols (.obj symbol table)
            msloc = {}       # this module's plain-local symbols
            o2 = off
            for (h, recs), aseg in zip(objsegs, asm_segs):
                base = org + o2
                bases.append(base)
                idx = a.segs.index(aseg)
                for nm, v in a.seg_local.get(idx, {}).items():
                    kind = ('export' if nm in a.exports
                            else 'entry' if nm in a.entries else 'local')
                    defs.setdefault(nm, []).append((linkidx, base + v, kind))
                    # entry/export symbols are in the .obj symbol table (a by-name
                    # cross-segment ref resolves to them); plain locals are not, so
                    # keep them separate (an external EXPORT of the same name wins).
                    # When a name is defined MULTIPLE times in one module, the
                    # canonical symbol-table entry is the segment that OWNS the
                    # in-segment ENTRY/EXPORT directive (entry_seg), e.g. WDefProc's
                    # two `setLong` entries -> the HSetInfoDraw copy. With no such
                    # directive (entry_seg empty) the FIRST definition wins (e.g.
                    # MenuMgr's two `NewMenu`, cdamenu's two `done`).
                    es = a.entry_seg.get(nm, '')
                    route = kind
                    if (kind != 'local' and es
                            and (aseg.name or '').upper() != es.upper()):
                        route = 'local'
                    (msloc if route == 'local' else msym).setdefault(nm, base + v)
                o2 += h['LENGTH']
            # exported/entry EQUATES (e.g. ToolPatch `ToolBoxPatcher equ $E101BC`)
            for nm in (a.exports | a.entries):
                if a.symtype.get(nm) == 'equ' and nm in a.symbols:
                    kind = 'export' if nm in a.exports else 'entry'
                    defs.setdefault(nm, []).append((linkidx, a.symbols[nm], kind))
                    msym.setdefault(nm, a.symbols[nm])
            # All SEGNAMEs (PROC/FUNC heads) of THIS object. A PROC head is a
            # same-assembly definition that satisfies this object's own by-name
            # refs BEFORE any cross-module export (e.g. tl's TLTABLE -> tl's own
            # `SetWAP PROC`, even though ControlMgr also `setWAP proc EXPORT`s one
            # and tl `import`s SetWAP). This differs from an interior plain local
            # (msloc): an interior label that collides with an imported name DOES
            # yield to the external export (lever 34: atp's `closeskt` label ->
            # aptalk's exported closeskt). PROC-head locality is the segment, not
            # the label.
            objsegbase = {}
            for (h, recs), base in zip(objsegs, bases):
                objsegbase[h['SEGNAME'].decode('mac_roman').strip().upper()] = base
            for (h, recs), aseg, base in zip(objsegs, asm_segs, bases):
                placements[bank].append(dict(
                    objrel=rel, segname=h['SEGNAME'].decode('mac_roman'),
                    base=base, length=h['LENGTH'], recs=recs, msym=msym,
                    msloc=msloc, objsegbase=objsegbase, linkidx=linkidx))
                off += h['LENGTH']
            linkidx += 1
    return placements, {'defs': defs}


def resolve_name(nm, segbase, msym, gtab, rommap, linkidx, msloc=None,
                 objsegbase=None):
    """Resolve a by-name reference. Order: this object's SEGNAMEs; this MODULE's
    own ENTRY/EXPORT symbols; rom.map; a global EXPORT (public, in the .obj symbol
    table); this MODULE's plain locals; else the last def at/before this module in
    link order. A same-module PLAIN local does NOT shadow an external EXPORT (it is
    not in the symbol table a by-name ref resolves against) -- so e.g. atp's own
    local `closeskt` yields to aptalk's exported `closeskt`."""
    v = segbase.get(nm)
    if v is None and msym is not None:
        v = msym.get(nm)
    if v is None:
        v = rommap.get(nm)
    if v is None and objsegbase is not None:
        v = objsegbase.get(nm)                           # same-object PROC head
    ds = gtab['defs'].get(nm)
    if v is None and ds:
        exp = [d for d in ds if d[2] == 'export']
        if exp:
            v = max(exp, key=lambda d: d[0])[1]          # public export
    if v is None and msloc is not None:
        v = msloc.get(nm)                                # this module's plain local
    if v is None and ds:
        cands = [d for d in ds if d[0] <= linkidx]
        v = (max(cands, key=lambda d: d[0]) if cands
             else min(ds, key=lambda d: d[0]))[1]        # last def at/before
    return v


def eval_expr(ops, segbase, msym, gtab, rommap, linkidx, msloc=None,
              objsegbase=None):
    """Evaluate an OMF load-time expression to a final value."""
    st = []
    for op in ops:
        if op == 'end':
            break
        if op[0] == 'lit':
            st.append(op[1] & 0xFFFFFFFF)
        elif isinstance(op[0], str) and op[0].startswith('sym'):
            v = resolve_name(op[1].upper(), segbase, msym, gtab, rommap,
                             linkidx, msloc, objsegbase)
            st.append((v if v is not None else 0) & 0xFFFFFFFF)
        elif op == 'loc':
            st.append(0)
        elif op[0] == 'op':
            o = op[1]
            b = st.pop() if st else 0
            a_ = st.pop() if st else 0
            if o == 0x01:   st.append((a_ + b) & 0xFFFFFFFF)
            elif o == 0x02: st.append((a_ - b) & 0xFFFFFFFF)
            elif o == 0x03: st.append((a_ * b) & 0xFFFFFFFF)
            elif o == 0x04: st.append((a_ // b) & 0xFFFFFFFF if b else 0)
            elif o == 0x07:                       # shift: b>=0 left, b<0 right
                sb = b if b < 0x80000000 else b - 0x100000000
                st.append(((a_ << sb) if sb >= 0 else (a_ >> -sb)) & 0xFFFFFFFF)
            else:           st.append(a_)         # unhandled op -> passthrough
    return st[-1] if st else 0


def emit_bank(bank, placements, gtab, rommap):
    org = bank << 16
    img = bytearray()
    for seg in placements[bank]:
        segbase = {seg['segname'].upper(): seg['base']}
        msym = seg.get('msym')
        msloc = seg.get('msloc')
        objsegbase = seg.get('objsegbase')
        li = seg['linkidx']
        body = bytearray()
        for at, name, detail in seg['recs']:
            if name == 'CONST' or name == 'LCONST':
                body += bytes(detail)
            elif name == 'DS':
                body += b'\x00' * detail
            elif name in ('LEXPR', 'BEXPR', 'EXPR', 'ZEXPR'):
                size, ops = detail
                v = eval_expr(ops, segbase, msym, gtab, rommap, li, msloc, objsegbase)
                body += bytes((v >> (8 * i)) & 0xFF for i in range(size))
            elif name == 'RELEXPR':
                size, origin, ops = detail
                v = eval_expr(ops, segbase, msym, gtab, rommap, li, msloc, objsegbase)
                here = seg['base'] + len(body)
                rel = (v - (here + origin)) & ((1 << (8 * size)) - 1)
                body += bytes((rel >> (8 * i)) & 0xFF for i in range(size))
            # GLOBAL/GEQU/ENTRY/END: no image bytes
        # pad/trim to the declared segment length
        body = body[:seg['length']].ljust(seg['length'], b'\x00')
        img += body
    return bytes(img)


def main():
    sym2val = parse_map()
    placements, gtab = place()
    want = {0xFE: 'ROM.FE', 0xFC: 'ROM.FC', 0xFD: 'ROM.FD'}
    only = [int(sys.argv[1], 16)] if len(sys.argv) > 1 else BANK_ORDER
    for bank in only:
        img = emit_bank(bank, placements, gtab, sym2val)
        real = open(ROOT + '/ROM/' + want[bank], 'rb').read()
        n = min(len(img), len(real))
        m = sum(1 for i in range(n) if img[i] == real[i])
        fd = next((i for i in range(n) if img[i] != real[i]), -1)
        print(f"bank {bank:02X}: mine {len(img)} real {len(real)}  "
              f"match {m}/{n} ({100*m//max(n,1)}%)  first diff @ "
              f"{hex(fd) if fd >= 0 else 'NONE'}")


if __name__ == '__main__':
    main()
