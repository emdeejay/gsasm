#!/usr/bin/env python3
"""fstcheck.py — validate gsasm against shipping System 6.0.1 FST files.

Assembles each FST from source (ref/GSOS_6/IIGS.601.SRC/GS.OS/FSTs/), links
the object(s), and byte-compares against the shipping FST binary extracted
from the System 6.0.1 disk images (ref/GSOS_6/fst_bin/).

All shipping FSTs are ExpressLoad'd OMF (leading ~ExpressLoad segment,
KIND 0x8001).  de_express() strips the directory segment and returns the
CONST/LCONST code image; our linked image is compared against that.

    python3 work/fstcheck.py            # summary over every mapped FST
    python3 work/fstcheck.py Pro.FST    # one FST with first-diff detail

Golden binary extraction (one-time, cadius):
    DISK3="ref/GSOS_6/System601_disks/System 6.0.1/Disk 3 of 7 SystemTools1.2mg"
    DISK2="ref/GSOS_6/System601_disks/System 6.0.1/Disk 2 of 7 System Disk.2mg"
    cadius EXTRACTFILE "$DISK2" "/System.Disk/System/FSTs/Char.FST"  ref/GSOS_6/fst_bin/
    cadius EXTRACTFILE "$DISK2" "/System.Disk/System/FSTs/Pro.FST"   ref/GSOS_6/fst_bin/
    for f in DOS3.3.FST HFS.FST HS.FST MSDOS.FST Pascal.FST; do
      cadius EXTRACTFILE "$DISK3" "/SystemTools1/System/FSTs/$f" ref/GSOS_6/fst_bin/
    done

Source → shipping-name map (from GS.OS/MakeFiles/make.*.fst):
  Pro.FST    — FSTs/ProDOS/ProDOS.FST          (-D DEBUGSYMBOLS=0)
  Char.FST   — FSTs/Character/Character.FST
  HFS.FST    — FSTs/HFS/hfs.fst.main + hfs.fst.btree  (-D DEBUGSYMBOLS=0, -unsafe -wi)
  HS.FST     — FSTs/HighSierra/HS.FST.src
  Pascal.FST — FSTs/Pascal/pascal.fst.aii       (-D DEBUGSYMBOLS=0)
  DOS3.3.FST — FSTs/DOS3.3/DOS3.3.FST          (-D DEBUGSYMBOLS=0)
  MSDos.FST  — FSTs/MSDos/MSDos.aii + Calls + Subs + Data  (lib ordering)
  (AppleShare.FST sources absent — skipped)

Packaging: all FSTs are ExpressLoad'd (KIND 0x8001 leading segment).

Known residuals:
  * lda #^Label bank-byte immediates resolve to 0 (SUPER type 27 reloc gap).
    Affects Pro.FST (79 diffs), Pascal.FST, and potentially others.
    These are same-class as the Tool-manager residuals — not a new gsasm gap.
  * HFS.FST, HS.FST, DOS3.3.FST: sizing drift in multi-segment sources
    (per-module m65816 instruction-length mismatch, cascades through address
    tables).  Same class as multi-object tool managers — unfixed, not new.
  * MSDos.FST: large sizing drift (MSDos.Calls.aii / MSDos.Subs.aii have
    many segments; multi-segment link produces 17239 vs 10068 golden bytes).
    Root cause: same multi-object sizing-drift class.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from gsasm import asm, omf, linkiigs
from gsasm.expressload import de_express

SRC  = 'ref/GSOS_6/IIGS.601.SRC'
GSOS = SRC + '/GS.OS'
CMN  = GSOS + '/Common'
FBIN = 'ref/GSOS_6/fst_bin'

# Include path: Common first (has common.equ.src / hw.equ.src / driver.equ.src),
# then every GS.OS subdir (so per-FST equate files are reachable).
INCS = ([CMN] + [d for d, _, _ in os.walk(GSOS)]
        + [os.path.join(os.path.dirname(os.path.abspath(__file__)), 'includes')])

# FST shipping-name -> (source-subdir, [source-files], {defines}, packaging)
# packaging: 'expressload' for all (determined by parsing golden OMF headers)
FSTMAP = {
    'Pro.FST': (
        'FSTs/ProDOS',
        ['ProDOS.FST'],
        {'DEBUGSYMBOLS': 0},
    ),
    'Char.FST': (
        'FSTs/Character',
        ['Character.FST'],
        {},
    ),
    'HFS.FST': (
        'FSTs/HFS',
        ['hfs.fst.main', 'hfs.fst.btree'],
        {'DEBUGSYMBOLS': 0},
    ),
    'HS.FST': (
        'FSTs/HighSierra',
        ['HS.FST.src'],
        {},
    ),
    'Pascal.FST': (
        'FSTs/Pascal',
        ['pascal.fst.aii'],
        {'DEBUGSYMBOLS': 0},
    ),
    'DOS3.3.FST': (
        'FSTs/DOS3.3',
        ['DOS3.3.FST'],
        {'DEBUGSYMBOLS': 0},
    ),
    'MSDos.FST': (
        'FSTs/MSDos',
        ['MSDos.aii', 'MSDos.Calls.aii', 'MSDos.Subs.aii', 'MSDos.Data.aii'],
        {},
    ),
    # AppleShare.FST: sources absent in this source tree — skipped
}


def _extract_img(result: bytes) -> bytes:
    """Extract the CONST/LCONST code image from a linked OMF result."""
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


def _packaging(name: str) -> str:
    """Determine packaging type from the golden binary OMF header."""
    for cand in _golden_candidates(name):
        if os.path.exists(cand):
            with open(cand, 'rb') as f:
                hdr = f.read(256)
            h = omf.parse_header(hdr)
            segname = h.get('SEGNAME', b'').rstrip(b'\x00')
            if segname == b'~ExpressLoad':
                return 'ExpressLoad'
            return 'plain-OMF'
    return 'unknown'


def _golden_candidates(name: str):
    """Return possible paths for the golden binary (cadius appends #TTAAAA)."""
    # Try common suffixes for FSTs (type BD)
    yield f'{FBIN}/{name}#BD0000'
    yield f'{FBIN}/{name}'
    # cadius may use uppercase or original case
    yield f'{FBIN}/{name.upper()}#BD0000'
    yield f'{FBIN}/{name.upper()}'
    # disk 3 ships MSDOS.FST (all-caps) even though source is MSDos
    stem = name.split('.')[0].upper()
    yield f'{FBIN}/{stem}.FST#BD0000'


def golden(name: str) -> bytes | None:
    for cand in _golden_candidates(name):
        if os.path.exists(cand):
            return de_express(cand)
    return None


def link_fst(subdir, sources, defines):
    """Assemble and link one FST.  Returns the code image bytes."""
    fst_dir = f'{GSOS}/{subdir}'
    extra = [fst_dir]
    incs = extra + INCS
    objects = []
    for src in sources:
        a = asm.assemble(f'{fst_dir}/{src}', incs, defines=defines or None)
        obj = omf.emit(a)
        objects.append((obj, a))
    result = linkiigs.link(objects, opts={'merge': True})
    return _extract_img(result)


def check(name: str, verbose: bool = False):
    if name not in FSTMAP:
        return name, None, None, f'not in FSTMAP'
    subdir, sources, defines = FSTMAP[name]
    g = golden(name)
    if g is None:
        return name, subdir, None, 'no golden binary (run cadius extraction)'
    try:
        mine = link_fst(subdir, sources, defines)
    except Exception as e:
        return name, subdir, None, f'{type(e).__name__}: {e}'
    n = min(len(mine), len(g))
    m = sum(1 for i in range(n) if mine[i] == g[i]) if n else 0
    pct = (100 * m // n) if n else 0
    pkg = _packaging(name)
    if verbose:
        print(f'{name} ({subdir}): gsasm={len(mine)} gold={len(g)} '
              f'match {m}/{n} ({pct}%)  pkg={pkg}')
        diffs = [(i, mine[i], g[i]) for i in range(n) if mine[i] != g[i]]
        if diffs:
            pos, a, b = diffs[0]
            print(f'  first diff @ {pos:#06x}: gsasm={a:02x} gold={b:02x}')
            print(f'    gsasm {bytes(mine[max(0, pos - 4):pos + 8]).hex()}')
            print(f'    gold  {g[max(0, pos - 4):pos + 8].hex()}')
        else:
            print('  BYTE-EXACT')
    return name, subdir, (pct, m, n, len(mine), len(g)), None


def main():
    if len(sys.argv) > 1:
        name = sys.argv[1]
        # Allow bare name like "Pro" or full "Pro.FST"
        if name not in FSTMAP:
            name = name + '.FST'
        if name not in FSTMAP:
            print(f'unknown/unmapped FST {sys.argv[1]}; mapped: {", ".join(sorted(FSTMAP))}')
            return
        check(name, verbose=True)
        return

    print(f'{"FST":<15} {"subdir":<25} {"match":>7}  {"bytes (gsasm/gold)":>20}  {"pkg"}')
    print('-' * 85)
    tot_m = tot_n = 0
    for name in sorted(FSTMAP):
        n_name, subdir, res, err = check(name)
        pkg = _packaging(name)
        if res is None:
            print(f'{name:<15} {str(subdir):<25} {"--":>7}  {err}  {pkg}')
            continue
        pct, m, n, lg, lo = res
        tot_m += m
        tot_n += n
        print(f'{name:<15} {subdir:<25} {pct:>6}%  {lg:>8}/{lo:<8}  ({m}/{n} bytes)  {pkg}')
    print()
    if tot_n:
        print(f'CORPUS raw code-image match: {tot_m}/{tot_n} ({100 * tot_m // tot_n}%)')
    print()
    print('Packaging note: all FSTs are ExpressLoad\'d (KIND 0x8001 leading segment).')
    print('AppleShare.FST: sources absent in this source tree — skipped.')


if __name__ == '__main__':
    main()
