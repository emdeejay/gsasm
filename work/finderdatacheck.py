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
                               _get_shift, _addend_of)

FD = 'ref/GSOS_6/IIGS.601.SRC/A.U.G/Finder'
DEFINES = {'DEBUGSYMBOLS': 0, 'AllowServerCopies': 0, 'AllowSmartDesktop': 0}
INCS = [FD] + em.ASM_INCS

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


def _scan_refs_shift(objs):
    """Like toolcheck._scan_refs but also yields the expression's tail
    right-shift (0 when unshifted) and constant addend:
    (abs_off, size, shift, symbol_upper, addend).  The addend matters for
    jump-table allocation: gold gives `routine+2` its OWN ~JumpTable entry
    (Finder ABOUT refs at +0x2bc/+0x2be and +0x2c4/+0x2c6)."""
    placed, _osb, _poi = linkiigs._place(objs, 0)
    for _sn, recs, sb, _hdr, _a in placed:
        boff = 0
        for _at, nm, d in recs:
            if nm in ('CONST', 'LCONST'):
                boff += len(d)
            elif nm in ('LEXPR', 'BEXPR', 'EXPR'):
                size, ops = d[0], d[1]
                syms = [op[1].upper() for op in ops
                        if isinstance(op, tuple) and str(op[0]).startswith('sym')]
                if syms:
                    yield (sb + boff, size, _get_shift(ops),
                           syms[0], _addend_of(ops), len(syms))
                boff += size
            elif nm == 'RELEXPR':
                boff += d[0]
            elif nm == 'DS':
                boff += d


def _assemble(fname):
    if fname not in _ASM_CACHE:
        a = asm.assemble(os.path.join(FD, fname), INCS, defines=dict(DEFINES))
        if a.errors:
            raise RuntimeError(f'{fname}: {len(a.errors)} assembly errors; '
                               f'first: {a.errors[0]}')
        _ASM_CACHE[fname] = (omf.emit(a), a)
    return _ASM_CACHE[fname]


def golden():
    vol = Volume(bytearray(open(dc.SYSTEM_DISK, 'rb').read()))
    return vol.read_file(f'{dc.V}/System/Start', fork='data')


def link_finder():
    """The _link_jt_tool algorithm (work/toolcheck.py) over the Finder's
    segment spec.  Returns (images, jt_entries, jt_segnum, segnum)."""
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
        objs = [_assemble(f) for f in srcs]
        seg_objs[name] = objs
        seg_sym[name] = tc._seg_symbols(objs)

    expmap = {}
    for name, _kind, _srcs in SEGS:
        for _ob, a in seg_objs[name]:
            for e in list(a.exports) + list(a.entries):
                v = seg_sym[name].get(e.upper())
                if isinstance(v, int):
                    expmap.setdefault(e.upper(), (name, v))

    def _cross_target(name, symu):
        tgt = expmap.get(symu)
        if tgt is None or tgt[0] == name or symu in seg_sym[name]:
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
        for aoff, size, shift, symu, addend, nsyms in _scan_refs_shift(objs):
            tgt = _cross_target(name, symu)
            if not tgt or tgt[0] == '=equ' or nsyms > 1:
                # equ targets are absolute constants the linker already
                # resolved; multi-symbol expressions (extern differences)
                # are link-time constants, not address relocations.
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
        images[name] = bytes(img)

    return images, jt_entries, jt_segnum, segnum


def main():
    verbose = '-v' in sys.argv
    raw = golden()
    try:
        images, jt_entries, jt_segnum, _segnum = link_finder()
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


if __name__ == '__main__':
    main()
