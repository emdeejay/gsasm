#!/usr/bin/env python3
"""finderdatacheck.py — rebuild the Finder DATA fork (the Finder itself).

The largest program in System 6.0.1: ~22 AsmIIGS modules linked into nine
static load segments + three DYNAMIC segments (ABOUT/Help/FIFIFIONE)
routed through a linker-generated ~JumpTable, ExpressLoad'd, 146,924 B.
Ships twice, byte-identical: `/System.Disk/System/Start` and
`/SystemTools1/System/Finder` (Disk 3) — same discovery as the resource
fork (work/findercheck.py).

Reuses the jump-table-aware multi-segment machinery proven byte-exact on
Tool015/016/018/020 (work/toolcheck.py + diskbuilders/expressload_files),
parameterized for the Finder tree: `Finder.make`'s AOPTIONS defines and
`-lseg` layout (KIND $1100 FINDER main segment, $1000 statics, dynamic
ABOUT/Help/FIFIFIONE, `-at $DB03`).

    python3 work/finderdatacheck.py            # summary
    python3 work/finderdatacheck.py -v         # per-segment detail
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import ensure_repo_on_path
ensure_repo_on_path()

import diskcheck as dc
import easymountcheck as em
import toolcheck as tc
from a2til.prodos import Volume
from gsasm import asm, omf, linkiigs
from gsasm.expressload import (expressload, encode_jumptable, jt_jsl_offset,
                               _get_shift, _addend_of, _scan_case_b,
                               emit_super, emit_cinterseg, emit_reloc)

FD = 'ref/GSOS_6/IIGS.601.SRC/A.U.G/Finder'
DEFINES = {'DEBUGSYMBOLS': 0, 'AllowServerCopies': 0, 'AllowSmartDesktop': 0}
INCS = [FD] + em.ASM_INCS
CASE_EQU_VARIANTS = {'HANDLE', 'PTR'}

# Finder.make's -lseg layout (gold segment table confirms names/kinds/order).
SEGS = [
    ('FINDER',    0x1100, ['Main.aii', 'request.aii', 'icons.aii', 'menu.aii',
                           'drives.aii', 'util.aii', 'data.aii', 'Misc.aii']),
    ('BUFFERS',   0x1000, ['buffers.aii']),
    ('VERIFY',    0x1000, ['verify.aii']),
    ('INFO',      0x1000, ['GetInfo.aii']),
    ('CONTROL',   0x1000, ['common.aii']),
    ('MATCH',     0x1000, ['match.aii']),
    ('ALERT',     0x1000, ['alert.aii']),
    ('CODE',      0x1000, ['GSOS.aii', 'Utility.aii', 'File.aii',
                           'fififitwo.aii']),
    ('DATA',      0x1000, ['Strings.aii']),
    ('ABOUT',     0x8000, ['About.aii']),
    ('Help',      0x8000, ['Help.aii']),
    ('FIFIFIONE', 0x8000, ['fififione.aii']),
]

_ASM_CACHE = {}


def _scan_refs_shift(objs, with_owner=False):
    """Like toolcheck._scan_refs but also yields the expression's tail
    right-shift (0 when unshifted) and constant addend:
    (abs_off, size, shift, symbol_upper, addend).  The addend matters for
    jump-table allocation: gold gives `routine+2` its OWN ~JumpTable entry
    (Finder ABOUT refs at +0x2bc/+0x2be and +0x2c4/+0x2c6)."""
    placed, osb, poi = linkiigs._place(objs, 0)
    for pi, (_sn, recs, sb, _hdr, _a) in enumerate(placed):
        oi = poi[pi]
        si = next((i for i, base in enumerate(osb[oi]) if base == sb), None)
        boff = 0
        for _at, nm, d in recs:
            if nm in ('CONST', 'LCONST'):
                boff += len(d)
            elif nm in ('LEXPR', 'BEXPR', 'EXPR'):
                size, ops = d[0], d[1]
                syms = [op[1].upper() for op in ops
                        if isinstance(op, tuple) and str(op[0]).startswith('sym')]
                if syms:
                    item = (sb + boff, size, _get_shift(ops),
                            syms[0], _addend_of(ops), len(syms))
                    yield item + (oi, si) if with_owner else item
                boff += size
            elif nm == 'RELEXPR':
                boff += d[0]
            elif nm == 'DS':
                boff += d


def _assemble(fname, import_wins=None):
    wins = frozenset(import_wins or ())
    key = (fname, tuple(sorted(wins)))
    if key not in _ASM_CACHE:
        a = asm.assemble(os.path.join(FD, fname), INCS, defines=dict(DEFINES),
                         import_wins=wins,
                         case_equ_variants=CASE_EQU_VARIANTS)
        if a.errors:
            raise RuntimeError(f'{fname}: {len(a.errors)} assembly errors; '
                               f'first: {a.errors[0]}')
        _ASM_CACHE[key] = (omf.emit(a), a)
    return _ASM_CACHE[key]


def _finder_import_wins(prelim):
    """Names where a Finder object IMPORT collides with its own proc-local EQU,
    while another Finder object EXPORTs that same name.  Those imports need to
    stay module-visible outside the defining PROC (icons.aii deltay/deltax)."""
    exporters = {}
    for src, (_ob, a) in prelim.items():
        for e in a.exports:
            exporters.setdefault(e.upper(), set()).add(src)

    wins = {}
    for src, (_ob, a) in prelim.items():
        proc_eq = set()
        for eq in a.seg_equ.values():
            proc_eq.update(eq)
        names = {
            u for u in a.imports & proc_eq
            if any(owner != src for owner in exporters.get(u.upper(), set()))
        }
        if names:
            wins[src] = frozenset(names)
    return wins


def golden():
    vol = Volume(bytearray(open(dc.SYSTEM_DISK, 'rb').read()))
    return vol.read_file(f'{dc.V}/System/Start', fork='data')


def link_finder():
    """The _link_jt_tool algorithm (work/toolcheck.py) over the Finder's
    segment spec.  Returns (images, jt_entries, jt_segnum, segnum)."""
    all_srcs = []
    for _name, _kind, srcs in SEGS:
        for src in srcs:
            if src not in all_srcs:
                all_srcs.append(src)
    prelim = {src: _assemble(src) for src in all_srcs}
    import_wins = _finder_import_wins(prelim)

    nondyn = [s for s in SEGS if not (s[1] & 0x8000)]
    dyn    = [s for s in SEGS if (s[1] & 0x8000)]
    jt_segnum = (2 + len(nondyn)) if dyn else None

    segnum, kind_of = {}, {}
    n = 2
    for name, kind, _srcs in nondyn:
        segnum[name] = n; kind_of[name] = kind; n += 1
    if dyn:
        n += 1
    for name, kind, _srcs in dyn:
        segnum[name] = n; kind_of[name] = kind; n += 1

    seg_objs, seg_sym = {}, {}
    for name, _kind, srcs in SEGS:
        objs = [_assemble(f, import_wins.get(f)) for f in srcs]
        seg_objs[name] = objs
        seg_sym[name] = tc._seg_symbols(objs)

    # Cross-SEGMENT visibility is EXPORT-only: an ENTRY is an intra-object
    # (here, intra-load-segment) private entry point, so a module's `ENTRY
    # GetFileInfo` (Misc.aii's own local proc) must NOT shadow the real
    # program-wide `EXPORT GetFileInfo` (GSOS.aii, in the CODE segment) that
    # other segments IMPORT.  (The same exports-vs-entries distinction the
    # linkiigs GLOBAL-record path already makes.)
    expmap = {}
    for name, _kind, _srcs in SEGS:
        for _ob, a in seg_objs[name]:
            for e in list(a.exports):
                v = seg_sym[name].get(e.upper())
                if isinstance(v, int):
                    expmap.setdefault(e.upper(), (name, v))

    def _cross_target(name, symu, ref_asm=None, ref_seg=None):
        tgt = expmap.get(symu)
        scoped_import = (
            ref_asm is not None and ref_seg is not None
            and symu in getattr(ref_asm, 'seg_imports', {}).get(ref_seg, set()))
        if tgt is None:
            return None
        if not scoped_import and (tgt[0] == name or symu in seg_sym[name]):
            return None
        return tgt

    # exported EQUATES are link-time constants too (INFO's absolute refs to
    # DP-area globals like $00B7 — exported equ values, not labels)
    for name, _kind, _srcs in SEGS:
        for _ob, a in seg_objs[name]:
            for e in list(a.exports) + list(a.entries):
                u = e.upper()
                if u not in expmap and a.symtype.get(u) == 'equ':
                    v = a.symbols.get(u)
                    if isinstance(v, int):
                        expmap[u] = ('=equ', v)

    jt_entries, jt_index = [], {}
    for name, _kind, _srcs in SEGS:
        for _aoff, _size, _shift, symu, addend, _n in _scan_refs_shift(seg_objs[name]):
            tgt = _cross_target(name, symu)
            if tgt and tgt[0] != '=equ' and (kind_of[tgt[0]] & 0x8000):
                key = (segnum[tgt[0]], tgt[1] + addend)
                if key not in jt_index:
                    jt_index[key] = len(jt_entries)
                    jt_entries.append(key)

    images = {}
    for name, _kind, _srcs in SEGS:
        externs = {}
        # Qualified typed-import field refs (IMPORT name:Type -> emitted as
        # 'NAME.FIELD...' by-name ops): the referencing module's equ_alias
        # table maps the dotted name to (base_import, offset) — seed the
        # extern as the base's link value + offset (GetInfo's
        # INFOWINPARAM.WPOSITION.* -> absolute $B7/$B9/... DP-record fields).
        for _ob, a in seg_objs[name]:
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
        objs = seg_objs[name]
        result = linkiigs.link(objs, opts={'merge': True, 'extern': externs,
                                           'abs_extra': list(externs.keys())})
        img = bytearray(tc._lconst_image(result))
        # In-image conventions for inter-segment sites (golden Finder
        # evidence, matching MPW LinkIIGS's INTERSEG record family):
        #   size 3 (jsl/far code ref): offset word + file segnum bank byte
        #     (the cINTERSEG convention; toolcheck's established patch).
        #   size 2, shift 16 (lda #^extern): the UNSHIFTED offset word —
        #     the shift is deferred to the interseg reloc (gold nullStrg
        #     $0613 at VERIFYMEDIUM+31, not $0000).
        #   size 4 (dc.l pointer table): ZERO image bytes — the value
        #     lives entirely in the dictionary's INTERSEG record (gold's
        #     zero-filled dispatch tables at FINDER+0x428).
        for aoff, size, shift, symu, addend, nsyms, oi, si in \
                _scan_refs_shift(objs, with_owner=True):
            ref_asm = objs[oi][1] if oi is not None else None
            tgt = _cross_target(name, symu, ref_asm, si)
            scoped_import = (
                ref_asm is not None and si is not None
                and symu in getattr(ref_asm, 'seg_imports', {}).get(si, set()))
            if not tgt or tgt[0] == '=equ' or nsyms > 1:
                # equ targets are absolute constants the linker already
                # resolved; multi-symbol expressions (extern differences)
                # are link-time constants, not address relocations.
                continue
            if scoped_import and tgt[0] == name and size != 2:
                continue
            dyn_tgt = bool(kind_of[tgt[0]] & 0x8000)
            if dyn_tgt:
                # A dynamic-segment target routes through its OWN JT entry
                # (per distinct target address incl. addend); the extern-
                # based value the linker wrote (base entry + addend) is
                # wrong for addended refs — overwrite uniformly.
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
                    # shifted: store the UNSHIFTED offset (deferred shift);
                    # plain dynamic: the JT jsl offset word.
                    img[aoff:aoff + 2] = (val & 0xFFFF).to_bytes(2, 'little')
                elif scoped_import and tgt[0] == name:
                    img[aoff:aoff + 2] = (val & 0xFFFF).to_bytes(2, 'little')
        images[name] = bytes(img)

    # -----------------------------------------------------------------
    # Per-load-segment RELOCATION DICTIONARIES (FINDER_PLAN A.3/A.4/A.6),
    # derived from the SAME site enumeration that produced the byte-exact
    # images above — injected into expressload() via opts['reloc_dicts'].
    #
    # Per site (base-0 offset within the load segment):
    #   * link-time constants (nsyms>1, absolute equ, dotted equ_alias field
    #     refs) emit NO record;
    #   * CROSS  (target in another segment): (2,0)->SUPER 13+T [BankRel-
    #     suppressed if T bank-aligned], (2,16)->SUPER 25+T, (3,0)->SUPER 2,
    #     (4,0)->standalone cINTERSEG (image already zeroed); dynamic targets
    #     route through the ~JumpTable (T=jt_segnum, segoff=jt jsl offset);
    #   * SAME-SEG: (2,0)->SUPER 0 [suppressed if own seg bank-aligned],
    #     (3,0)/(4,0)->SUPER 1, (2,16)->SUPER 25+S;
    #   * case-B flagged (+$80000000/+$C0000000) -> standalone RELOC/E2
    #     (the shift-0 lo half is BankRel-suppressed for a bank-aligned seg).
    # Order: standalone (ascending offset, interleaved) -> SUPER (ascending
    # subtype) -> single END.
    # -----------------------------------------------------------------
    reloc_dicts = {}
    for name, kind, _srcs in SEGS:
        objs = seg_objs[name]
        own_bankrel = bool(kind & 0x0100)
        own_seg = segnum[name]

        # case-B standalone RELOC/E2 sites.  _scan_case_b's size-2 path accepts
        # any value > 0xFFFFFF, which in this per-segment context also catches a
        # `Label-2` whose symbol is CROSS (resolves to 0 here -> 0xFFFFFFFE) —
        # SPIKE-2's false-positive trap.  Keep ONLY the genuine bit-31/bit-30
        # flag family (top byte exactly 0x80/0xC0); a real cross low-word ref is
        # then classified normally by the SUPER loop below.
        placed_cb, _ocb, _pcb = linkiigs._place(objs, 0)
        cb_syms = [dict(seg_sym[name]) for _ in placed_cb]
        case_b = [(s, sz, sh, v) for (s, sz, sh, v) in _scan_case_b(placed_cb, cb_syms)
                  if (v & 0x80000000) and (v & 0x3F000000) == 0]
        cb_offsets = {site for site, _cs, _csh, _cv in case_b}

        standalone = []          # (offset, record_bytes)
        for site, csize, cshift, cval in case_b:
            if cshift == 0 and own_bankrel:
                continue         # BankRel drops the shift-0 (lo) case-B half
            standalone.append((site, emit_reloc(csize, cshift, site, cval)))

        supers = {}              # subtype -> [offsets]
        for aoff, size, shift, symu, addend, nsyms, oi, si in \
                _scan_refs_shift(objs, with_owner=True):
            if aoff in cb_offsets or nsyms > 1:
                continue
            ref_asm = objs[oi][1] if oi is not None else None
            tgt = _cross_target(name, symu, ref_asm, si)
            if tgt is not None and tgt[0] == '=equ':
                continue                     # absolute exported equate
            if tgt is None and '.' in symu:
                continue                     # dotted equ_alias field -> absolute

            if tgt is not None and tgt[0] != name:
                # ---- CROSS-SEGMENT ----
                tname = tgt[0]
                if kind_of[tname] & 0x8000:
                    T = jt_segnum
                    tgt_bankrel = False
                    segoff = jt_jsl_offset(jt_index[(segnum[tname], tgt[1] + addend)])
                else:
                    T = segnum[tname]
                    tgt_bankrel = bool(kind_of[tname] & 0x0100)
                    segoff = tgt[1] + addend
                if (size, shift) == (2, 0):
                    if tgt_bankrel:
                        continue             # BankRel cross low-word suppression
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
                # ---- SAME-SEGMENT relocatable label ----
                if (size, shift) == (2, 0):
                    if own_bankrel:
                        continue             # BankRel same-seg subtype-0 kill
                    supers.setdefault(0, []).append(aoff)
                elif (size, shift) == (2, 16):
                    supers.setdefault(25 + own_seg, []).append(aoff)
                elif shift == 0 and size in (3, 4):
                    supers.setdefault(1, []).append(aoff)
                # any other same-seg (size,shift) is left unrecorded; --segdiff
                # will surface it if the Finder actually exercises one.

        rec = bytearray()
        for _off, b in sorted(standalone, key=lambda p: p[0]):
            rec += b
        for st in sorted(supers):
            rec += emit_super(st, sorted(supers[st]))
        rec += b'\x00'           # END
        reloc_dicts[name] = bytes(rec)

    return images, jt_entries, jt_segnum, segnum, reloc_dicts


def _finder_objects():
    """Per-load-segment OMF object combos + names/kinds for expressload(),
    in SEGS order (mirrors work/diskbuilders/expressload_files.py tool
    builders — one combined object per output load segment)."""
    all_srcs = []
    for _n, _k, srcs in SEGS:
        for s in srcs:
            if s not in all_srcs:
                all_srcs.append(s)
    prelim = {src: _assemble(src) for src in all_srcs}
    import_wins = _finder_import_wins(prelim)
    objects, segnames, segkinds = [], [], []
    for name, kind, srcs in SEGS:
        combo = b''.join(_assemble(f, import_wins.get(f))[0] for f in srcs)
        objects.append((combo, None))
        segnames.append(name.encode())
        segkinds.append(kind)
    return objects, segnames, segkinds


def build_finder_data():
    """Assemble + link + ExpressLoad-package the whole Finder DATA fork,
    injecting link_finder()'s byte-exact per-segment images AND relocation
    dictionaries (FINDER_PLAN B.5).  NOTE: the ~ExpressLoad directory segment
    is still built by expressload()'s own machinery (Stage 4 work), so the
    full fork is NOT yet byte-exact — the load segments are."""
    images, jt_entries, jt_segnum, _segnum, reloc_dicts = link_finder()
    objects, segnames, segkinds = _finder_objects()
    seg_images = {name.encode(): images[name] for name, _k, _s in SEGS}
    dicts = {name.encode(): reloc_dicts[name] for name, _k, _s in SEGS}
    return expressload(objects, opts={
        'multiseg': True,
        'segnames': segnames,
        'segkinds': segkinds,
        'jt_entries': jt_entries,
        'seg_images': seg_images,
        'reloc_dicts': dicts,
    })


def _split_seg(raw_seg):
    """Split one raw OMF segment into (header, lconst_image, reloc_bytes)
    assuming the single-$F2-LCONST body layout every gold load segment uses.
    reloc_bytes INCLUDES the trailing END (0x00)."""
    h = omf.parse_header(raw_seg)
    dd = h['DISPDATA']
    hdr = raw_seg[:dd]
    if raw_seg[dd] != 0xF2:
        return hdr, None, raw_seg[dd:]
    lcsz = int.from_bytes(raw_seg[dd + 1:dd + 5], 'little')
    lconst = raw_seg[dd + 5:dd + 5 + lcsz]
    reloc = raw_seg[dd + 5 + lcsz:]
    return hdr, lconst, reloc


def _named_segs(fork):
    """name -> raw segment bytes, in file order (list of (name, raw))."""
    out = []
    for seg in omf.iter_segments(fork):
        nm = (seg['hdr']['SEGNAME'].decode('mac_roman', 'replace')
              .strip().rstrip('\x00'))
        out.append((nm, seg['raw']))
    return out


def _reloc_seg_rows(built=None):
    """Per-load-segment (name, hdr_ok, lconst_ok, reloc_ok, dRELOC, e2e) rows
    plus (good, total) reloc-dict tally, comparing build_finder_data() to gold.
    Shared by main()'s ratchet line and the --segdiff view."""
    raw = golden()
    if built is None:
        built = build_finder_data()
    built_map = dict(_named_segs(built))
    load_names = {n for n, _k, _s in SEGS} | {'~JumpTable'}
    rows = []
    good = total = 0
    for nm, graw in _named_segs(raw):
        braw = built_map.get(nm)
        if braw is None:
            rows.append((nm, None, None, None, None, None))
            continue
        gh, gl, gr = _split_seg(graw)
        bh, bl, br = _split_seg(braw)
        if nm in load_names and nm != '~ExpressLoad':
            total += 1
            if br == gr:
                good += 1
        rows.append((nm, bh == gh, bl == gl, br == gr,
                     len(br) - len(gr), braw == graw))
    return rows, good, total


def segdiff():
    """Per-segment end2end/hdr/lconst/reloc booleans + reloc byte-delta,
    comparing build_finder_data() to gold (FINDER_PLAN D.2)."""
    rows, good, total = _reloc_seg_rows()
    print(f'{"segment":14} {"e2e":>4} {"hdr":>4} {"lcon":>4} {"reloc":>5} '
          f'{"dRELOC":>7}   note')
    for nm, hdr, lcon, reloc, drel, e2e in rows:
        if hdr is None:
            print(f'{nm:14} {"MISS":>4}')
            continue
        note = '' if reloc else f'reloc len delta {drel}'
        print(f'{nm:14} {str(e2e):>4} {str(hdr):>4} {str(lcon):>4} '
              f'{str(reloc):>5} {drel:>7}   {note}')
    print(f'\nFINDER_RELOC_SEGS_EXACT {good}/{total}')
    return good, total


def main():
    if '--segdiff' in sys.argv:
        segdiff()
        return
    verbose = '-v' in sys.argv
    raw = golden()
    try:
        images, jt_entries, jt_segnum, _segnum, _reloc = link_finder()
    except Exception as e:                                   # noqa: BLE001
        print(f'FAIL link: {type(e).__name__}: {e}')
        sys.exit(1)

    tot_m = tot_n = 0
    for name, _kind, _srcs in SEGS:
        g = tc._gold_segment(raw, name)
        b = images[name]
        m, n = tc.byte_match(b, g)
        tot_m += m; tot_n += n
        note = ''
        if verbose and b != g:
            diffs = tc.mismatch_offsets(b, g)
            i = diffs[0]
            note = (f'  first diff @{i:#06x} mine={b[i]:02x} gold={g[i]:02x} '
                    f'({len(diffs)} bytes)')
        print(f'{"PASS" if b == g else "FAIL"} {name:10} '
              f'mine={len(b):6d} gold={len(g):6d} match {m}/{n}{note}')

    gold_jt = tc._gold_segment(raw, '~JumpTable')
    mine_jt = encode_jumptable(jt_entries)
    print(f'{"PASS" if mine_jt == gold_jt else "FAIL"} ~JumpTable '
          f'{len(jt_entries)} entries mine={len(mine_jt)} gold={len(gold_jt)}')

    print(f'\nfinderdatacheck: FINDER_DATA_CODE_BYTES {tot_m}/{tot_n}')
    # Interim ratchet: every load-segment reloc dictionary byte-exact (Stages
    # 0-3). The ~ExpressLoad directory (Stage 4) is excluded from this tally.
    try:
        _rows, good, total = _reloc_seg_rows()
        print(f'finderdatacheck: FINDER_RELOC_SEGS_EXACT {good}/{total}')
    except Exception as e:                                   # noqa: BLE001
        print(f'finderdatacheck: FINDER_RELOC_SEGS_EXACT 0/13  ({type(e).__name__}: {e})')


if __name__ == '__main__':
    main()
