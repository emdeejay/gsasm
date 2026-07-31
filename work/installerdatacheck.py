#!/usr/bin/env python3
"""installerdatacheck.py — rebuild the Installer DATA fork (Disk 1).

The Installer is the set's second-largest ExpressLoad application (56,163 B):
9 load segments + a linker ~JumpTable, built per the archived MakeFile as

    linkIIGS -t $B3 -at $DB07 Main MainSub Startup Install Subroutines Data
             -lib GSOString.lib

with the load-segment structure coming from in-source `SEG 'Name'` + `SegAttr`
directives (not -lseg):

    seg#  name         KIND     bytes   source
      1   ~ExpressLoad $8001      689   loader directory (generated)
      2   Main         $4000   29,882   SegAttr Static — LOADNAME 'Main' runs
      3   ~direct      $4812    4,096   Data.asm `Stack StackDP` (DP/stack)
      4   main         $0000    1,690   referenced GSOString.lib members
      5   ~JumpTable   $0002      110   7 thunks into the dynamic segments
      6   StartUp      $8000      941   SegAttr Dynamic
      7   Standard     $8000      129   SegAttr Dynamic
      8   Custom       $8000      410   SegAttr Dynamic
      9   BuildList    $C000      430   SegAttr Dynamic (non-exported: private)
     10   Install      $C000   12,826   SegAttr Dynamic (non-exported: private)

Group membership is recovered from each emitted OMF segment's LOADNAME (the
SEG directive) in link order; the `main` group is the library members in MPW's
-lib hash-bucket extraction order (linkiigs.link_lib's scan, replicated).  The
per-segment images, ~JumpTable entries, and relocation dictionaries follow
work/finderdatacheck.py's link_finder algorithm (the golden-proven MPW LinkIIGS
conventions: dynamics route through the ~JumpTable, size-4 cross slots zero +
standalone cINTERSEG, SUPER subtype families, case-B standalone RELOC).

    python3 work/installerdatacheck.py
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import ensure_repo_on_path, first_diff
ensure_repo_on_path()

import diskcheck as dc                        # noqa: E402
import drivercheck                            # noqa: E402  (INCS)
import toolcheck as tc                        # noqa: E402
import finderdatacheck as fd                  # noqa: E402  (_scan_refs_shift)
from a2til.prodos import Volume               # noqa: E402
from gsasm import asm, omf, linkiigs          # noqa: E402
from gsasm.expressload import (               # noqa: E402
    expressload, jt_jsl_offset, _scan_case_b,
    emit_super, emit_cinterseg, emit_reloc)

_INS = os.path.join('ref/GSOS_6/IIGS.601.SRC', 'A.U.G', 'Installer')
_MODS = ['Main.asm', 'MainSub.asm', 'Startup.asm', 'Install.asm',
         'Subroutines.asm', 'Data.asm']
_DISK = 'Disk 1 of 7 Install.2mg'
_PATH = '/Install/Installer'

# load-segment groups in file order (SegAttr Static/Dynamic; BuildList/Install
# are the non-exported dynamics -> private bit set)
_GROUPS = [('Main', 0x4000), ('~direct', 0x4812), ('main', 0x0000),
           ('StartUp', 0x8000), ('Standard', 0x8000), ('Custom', 0x8000),
           ('BuildList', 0xC000), ('Install', 0xC000)]

_CACHE = {}


def _assemble_all():
    if 'objs' in _CACHE:
        return _CACHE['objs']
    roots, lib = [], None
    for m in _MODS + ['GString.lib']:
        a = asm.assemble(os.path.join(_INS, m), [_INS] + drivercheck.INCS)
        # Main.asm carries ONE benign assembly-time error: KeyDown's
        # `bne inControl` targets the inControl PROC in another segment, so the
        # assembly-pass range check trips; the emitted RELEXPR resolves at link
        # (the documented Tool023/Tool028 tolerance class). Anything else fatal.
        real = [e for e in a.errors if 'branch out of range' not in e]
        if real:
            raise RuntimeError(f'{m}: {len(real)} asm errors; first: {real[0]}')
        pair = (omf.emit(a), a)
        if m == 'GString.lib':
            lib = pair
        else:
            roots.append(pair)
    _CACHE['objs'] = (roots, lib)
    return roots, lib


def _seg_ranges(obj_bytes):
    """[(start, end, segname, loadname)] raw byte ranges of each OMF segment."""
    out = []
    p = 0
    while p < len(obj_bytes) - 4:
        bc = struct.unpack('<I', obj_bytes[p:p+4])[0]
        if bc == 0:
            break
        dn = struct.unpack('<H', obj_bytes[p+40:p+42])[0]
        loadname = obj_bytes[p+44:p+54].decode('mac_roman').strip('\x00 ')
        nl = obj_bytes[p+dn+10]
        nm = obj_bytes[p+dn+11:p+dn+11+nl].decode('mac_roman')
        out.append((p, p + bc, nm, loadname.strip() or 'main'))
        p += bc
    return out


def _filter_obj(obj_bytes, want_idx):
    """A new OMF object containing only segments at `want_idx`, in that order."""
    rng = _seg_ranges(obj_bytes)
    return b''.join(obj_bytes[rng[i][0]:rng[i][1]] for i in want_idx)


def _lib_extraction_order(roots, lib):
    """Library segment indices referenced by the root link, in MPW's -lib
    hash-bucket extraction order (linkiigs.link_lib's scan, replicated)."""
    objects = list(roots) + [lib]
    parsed = [linkiigs._parse_obj(ob) for ob, _a in objects]
    n_root = len(roots)
    info, libdef = {}, {}
    for oi, p in enumerate(parsed):
        for si, seg in enumerate(p):
            g, r = linkiigs._seg_globals_refs(seg)
            info[(oi, si)] = (g, r)
            if oi >= n_root:
                for name in g:
                    libdef.setdefault(name, (oi, si))
    order = [(oi, si) for oi in range(n_root) for si in range(len(parsed[oi]))]
    resolved = set()
    for key in order:
        resolved |= info[key][0]
    B = 512
    buckets = [[] for _ in range(B)]
    moved = set()
    cur_bucket = [None]

    def add(sym):
        if sym in resolved:
            return
        b = linkiigs._lib_hash(sym, B)
        if sym in buckets[b]:
            if sym not in moved and b != cur_bucket[0]:
                buckets[b].remove(sym)
                buckets[b].insert(0, sym)
                moved.add(sym)
            return
        buckets[b].insert(0, sym)

    for key in order:
        for r in info[key][1]:
            add(r)
    included = set(order)
    sel = []
    bi = idle = 0
    while idle < B:
        cur_bucket[0] = bi
        found = False
        j = 0
        while j < len(buckets[bi]):
            sym = buckets[bi][j]
            j += 1
            if sym in resolved:
                continue
            key = libdef.get(sym)
            if key is None or key in included:
                resolved.add(sym)
                continue
            included.add(key)
            sel.append(key[1])
            resolved |= info[key][0]
            for r in info[key][1]:
                add(r)
            found = True
        idle = 0 if found else idle + 1
        bi = (bi + 1) % B
    return sel


def _group_objs():
    """{group_name: [(filtered_obj_bytes, asm), ...]} per _GROUPS."""
    if 'groups' in _CACHE:
        return _CACHE['groups']
    roots, lib = _assemble_all()
    out = {g: [] for g, _k in _GROUPS}
    for ob, a in roots:
        rng = _seg_ranges(ob)
        byg = {}
        for i, (_s, _e, nm, ldn) in enumerate(rng):
            if a._fold(nm) in a.stackdp_segs:
                byg.setdefault('~direct', []).append(i)
            else:
                byg.setdefault(ldn, []).append(i)
        for g, idxs in byg.items():
            if g in out:
                out[g].append((_filter_obj(ob, idxs), a))
    out['main'].append((_filter_obj(lib[0], _lib_extraction_order(roots, lib)),
                        lib[1]))
    _CACHE['groups'] = out
    return out


def _gold():
    vol = Volume(open(os.path.join(dc.DISKS, _DISK), 'rb').read())
    return bytes(vol.read_file(_PATH))


def link_installer():
    """finderdatacheck.link_finder's algorithm over the Installer's groups.
    Returns (images, jt_entries, jt_segnum, segnum, reloc_dicts)."""
    groups = _group_objs()
    SEGS = [(g, k) for g, k in _GROUPS]
    nondyn = [s for s in SEGS if not (s[1] & 0x8000)]
    dyn = [s for s in SEGS if (s[1] & 0x8000)]
    jt_segnum = (2 + len(nondyn)) if dyn else None

    segnum, kind_of = {}, {}
    n = 2
    for name, kind in nondyn:
        segnum[name] = n
        kind_of[name] = kind
        n += 1
    if dyn:
        n += 1
    for name, kind in dyn:
        segnum[name] = n
        kind_of[name] = kind
        n += 1

    seg_sym = {name: tc._seg_symbols(groups[name]) for name, _k in SEGS}

    # cross-segment visibility is EXPORT-only (ENTRY is intra-load-segment)
    expmap = {}
    for name, _k in SEGS:
        for _ob, a in groups[name]:
            for e in list(a.exports):
                v = seg_sym[name].get(e.upper())
                if isinstance(v, int):
                    expmap.setdefault(e.upper(), (name, v))
    for name, _k in SEGS:
        for _ob, a in groups[name]:
            for e in list(a.exports) + list(a.entries):
                u = e.upper()
                if u not in expmap and a.symtype.get(u) == 'equ':
                    v = a.symbols.get(u)
                    if isinstance(v, int):
                        expmap[u] = ('=equ', v)

    # INTRA-OBJECT visibility: a module-visible (non-exported) symbol is still
    # reachable from ANOTHER load segment when both segments come from the SAME
    # source object — the Installer's Startup.asm feeds StartUp/Standard/
    # Custom/BuildList, and Custom's `jsl` to the BuildList segment head must
    # resolve (gold routes it through ~JumpTable entry (9,0)). The Finder never
    # exercised this (its groups were whole files). asm_defs[id(a)][SYM] ->
    # (group, value) for each contributing asm's own definitions per group.
    # Only a definition that genuinely SATISFIES an import counts: an EXPORT,
    # an ENTRY, or a segment head (the same rule linkiigs applies) — a plain
    # module-interior label does not (Install.asm's interior `VolTotalBlocks`
    # loses to Main's export even though Install also IMPORTs the name, while
    # its `Entry CloseMsgWindow` wins).
    asm_defs = {}
    for name, _k in SEGS:
        for ob, a in groups[name]:
            m = asm_defs.setdefault(id(a), {})
            heads = {a._fold(s['segname'] or '')
                     for s in linkiigs._parse_obj(ob)}
            visible = set(a.exports) | set(a.entries) | heads
            for symu, v in tc._seg_symbols([(ob, a)]).items():
                if isinstance(v, int) and symu in visible:
                    m.setdefault(symu, (name, v))

    def _cross_target(name, symu, ref_asm=None, ref_seg=None):
        tgt = expmap.get(symu)
        scoped_import = (
            ref_asm is not None and ref_seg is not None
            and symu in getattr(ref_asm, 'seg_imports', {}).get(ref_seg, set()))
        own = (asm_defs.get(id(ref_asm), {}).get(symu)
               if ref_asm is not None else None)
        if tgt is None and own is not None and own[0] != name:
            tgt = own
        if tgt is None:
            return None
        # A definition in the REF'S OWN OBJECT within this load segment
        # satisfies even a declared IMPORT (an ENTRY is intra-object visible):
        # Install.asm's `Import CloseMsgWindow` + its own `Entry CloseMsgWindow`
        # binds the local — gold's same-segment subtype-0 sites — while the
        # Finder's Misc.aii ENTRY (a DIFFERENT object from the referencing
        # modules) still loses to the CODE segment's EXPORT.
        if own is not None and own[0] == name:
            return None
        if not scoped_import and (tgt[0] == name or symu in seg_sym[name]):
            return None
        return tgt

    jt_entries, jt_index = [], {}
    for name, _k in SEGS:
        for _aoff, _size, _shift, symu, addend, _n, oi, si in \
                fd._scan_refs_shift(groups[name], with_owner=True):
            ref_asm = groups[name][oi][1] if oi is not None else None
            tgt = _cross_target(name, symu, ref_asm, si)
            if tgt and tgt[0] != '=equ' and (kind_of[tgt[0]] & 0x8000):
                key = (segnum[tgt[0]], tgt[1] + addend)
                if key not in jt_index:
                    jt_index[key] = len(jt_entries)
                    jt_entries.append(key)

    images = {}
    for name, _k in SEGS:
        externs = {}
        for _ob, a in groups[name]:
            for alias, (base, off) in getattr(a, 'equ_alias', {}).items():
                bu = str(base).upper()
                tgt = expmap.get(bu)
                if tgt and tgt[0] != name and not (
                        tgt[0] != '=equ' and (kind_of[tgt[0]] & 0x8000)):
                    externs[str(alias).upper()] = tgt[1] + off
        for symu, (tname, toff) in expmap.items():
            if tname == name or symu in seg_sym[name]:
                continue
            if tname == '=equ':
                externs[symu] = toff
            elif kind_of[tname] & 0x8000:
                key = (segnum[tname], toff)
                if key not in jt_index:
                    continue
                externs[symu] = jt_jsl_offset(jt_index[key])
            else:
                externs[symu] = toff
        objs = groups[name]
        result = linkiigs.link(objs, opts={'merge': True, 'extern': externs,
                                           'abs_extra': list(externs.keys())})
        img = bytearray(tc._lconst_image(result))
        for aoff, size, shift, symu, addend, nsyms, oi, si in \
                fd._scan_refs_shift(objs, with_owner=True):
            ref_asm = objs[oi][1] if oi is not None else None
            tgt = _cross_target(name, symu, ref_asm, si)
            scoped_import = (
                ref_asm is not None and si is not None
                and symu in getattr(ref_asm, 'seg_imports', {}).get(si, set()))
            if not tgt or tgt[0] == '=equ' or nsyms > 1:
                continue
            if scoped_import and tgt[0] == name and size != 2:
                continue
            dyn_tgt = bool(kind_of[tgt[0]] & 0x8000)
            if dyn_tgt:
                val = jt_jsl_offset(jt_index[(segnum[tgt[0]], tgt[1] + addend)])
            else:
                val = tgt[1] + addend
            if size == 4 and aoff + 4 <= len(img):
                img[aoff:aoff + 4] = b'\x00\x00\x00\x00'
            elif size == 3 and aoff + 3 <= len(img):
                img[aoff:aoff + 2] = (val & 0xFFFF).to_bytes(2, 'little')
                img[aoff + 2] = (jt_segnum if dyn_tgt else segnum[tgt[0]]) & 0xFF
            elif size == 2 and aoff + 2 <= len(img):
                if shift == 16 or dyn_tgt:
                    img[aoff:aoff + 2] = (val & 0xFFFF).to_bytes(2, 'little')
                elif scoped_import and tgt[0] == name:
                    img[aoff:aoff + 2] = (val & 0xFFFF).to_bytes(2, 'little')
        images[name] = bytes(img)

    reloc_dicts = {}
    for name, kind in SEGS:
        objs = groups[name]
        own_bankrel = bool(kind & 0x0100)
        own_seg = segnum[name]

        placed_cb, _ocb, _pcb = linkiigs._place(objs, 0)
        cb_syms = [dict(seg_sym[name]) for _ in placed_cb]
        case_b = [(s, sz, sh, v)
                  for (s, sz, sh, v) in _scan_case_b(placed_cb, cb_syms)
                  if (v & 0x80000000) and (v & 0x3F000000) == 0]
        cb_offsets = {site for site, _cs, _csh, _cv in case_b}

        standalone = []
        for site, csize, cshift, cval in case_b:
            if cshift == 0 and own_bankrel:
                continue
            standalone.append((site, emit_reloc(csize, cshift, site, cval)))

        supers = {}
        for aoff, size, shift, symu, addend, nsyms, oi, si in \
                fd._scan_refs_shift(objs, with_owner=True):
            if aoff in cb_offsets or nsyms > 1:
                continue
            ref_asm = objs[oi][1] if oi is not None else None
            tgt = _cross_target(name, symu, ref_asm, si)
            if tgt is not None and tgt[0] == '=equ':
                continue
            if tgt is None and '.' in symu:
                continue
            if tgt is not None and tgt[0] != name:
                tname = tgt[0]
                if kind_of[tname] & 0x8000:
                    T = jt_segnum
                    tgt_bankrel = False
                    segoff = jt_jsl_offset(
                        jt_index[(segnum[tname], tgt[1] + addend)])
                else:
                    T = segnum[tname]
                    tgt_bankrel = bool(kind_of[tname] & 0x0100)
                    segoff = tgt[1] + addend
                if (size, shift) == (2, 0):
                    if tgt_bankrel:
                        continue
                    supers.setdefault(13 + T, []).append(aoff)
                elif (size, shift) == (2, 16):
                    supers.setdefault(25 + T, []).append(aoff)
                elif size == 3 and shift == 0:
                    supers.setdefault(2, []).append(aoff)
                elif size == 4 and shift == 0:
                    standalone.append(
                        (aoff, emit_cinterseg(4, 0, aoff, T, segoff)))
                else:
                    standalone.append(
                        (aoff, emit_cinterseg(size, shift, aoff, T, segoff)))
            else:
                if (size, shift) == (2, 0):
                    if own_bankrel:
                        continue
                    supers.setdefault(0, []).append(aoff)
                elif (size, shift) == (2, 16):
                    supers.setdefault(25 + own_seg, []).append(aoff)
                elif shift == 0 and size in (3, 4):
                    supers.setdefault(1, []).append(aoff)

        rec = bytearray()
        for _off, b in sorted(standalone, key=lambda p: p[0]):
            rec += b
        for st in sorted(supers):
            rec += emit_super(st, sorted(supers[st]))
        rec += b'\x00'
        reloc_dicts[name] = bytes(rec)

    return images, jt_entries, jt_segnum, segnum, reloc_dicts


def build_installer_data():
    groups = _group_objs()
    images, jt_entries, _jtn, _sn, reloc_dicts = link_installer()
    objects, segnames, segkinds = [], [], []
    for name, kind in _GROUPS:
        combo = b''.join(ob for ob, _a in groups[name])
        objects.append((combo, None))
        segnames.append(name.encode('mac_roman'))
        segkinds.append(kind)
    return expressload(objects, opts={
        'multiseg': True,
        'segnames': segnames,
        'segkinds': segkinds,
        'jt_entries': jt_entries,
        'seg_images': {n.encode('mac_roman'): images[n] for n, _k in _GROUPS},
        'reloc_dicts': {n.encode('mac_roman'): reloc_dicts[n]
                        for n, _k in _GROUPS},
    })


def run():
    gold = _gold()
    try:
        built = bytes(build_installer_data())
    except Exception:                          # pragma: no cover
        import traceback
        traceback.print_exc()
        print(f'INSTALLER_DATA_BYTES_EXACT 0/{len(gold)}')
        return 1
    n = len(gold)
    if built == gold:
        print(f'  Installer data fork BYTE-EXACT ({n} B)')
        good = n
    else:
        d = first_diff(built, gold)
        print(f'  Installer data: built={len(built)} gold={n} '
              f'first diff @ {hex(d) if d is not None else "len"}')
        good = 0
    print(f'INSTALLER_DATA_BYTES_EXACT {good}/{n}')
    return 0 if good == n else 1


if __name__ == '__main__':
    sys.exit(run())
