#!/usr/bin/env python3
"""findercheck.py — rebuild the Finder resource fork from its Rez sources.

Rez tier-1, Finder sweep (docs/REZ_TYPES_PLAN.md phase-2): the Finder's
resource fork compiles from the archived `A.U.G/Finder/Finder.rez` master
(seven part files + `Finder.rez.equ`) through the clean-room include
(gsasm/rez/include/TypesIIGS.r).  Unlike the CDEV forks there is NO
extraction-fed content: the one non-Rez ingredient, the `read
rFinderExtension` payload (`KeyboardNav:KeyboardNavRsrc`), is itself
assembled+linked+ExpressLoad'd from `KeyboardNav.aii` by gsasm — the whole
fork is source-built.

The same fork ships TWICE in System 6.0.1: as `/SystemTools1/System/Finder`
on Disk 3 and — byte-identical — as the boot program
`/System.Disk/System/Start` on the System Disk (the "Start has no archived
source" dead end recorded in docs/REZ_TYPES_PLAN.md was wrong: Start IS the
Finder).  Both golden copies are checked; the Start entry is also wired
into work/diskcheck.py's REZ_BUILDERS (counts in disk_logical_exact).

    python3 work/findercheck.py          # both golden copies + summary
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import ensure_repo_on_path
ensure_repo_on_path()

import rezcheck as rc
import diskcheck as dc
import easymountcheck as em
import rezemitcheck as rec
from gsasm import asm, omf
from gsasm.expressload import expressload
from gsasm.rez import parser, gen, emit

INC = ['gsasm/rez/include']
SRC_DIR = 'ref/GSOS_6/IIGS.601.SRC/A.U.G/Finder'
REZ_MASTER = os.path.join(SRC_DIR, 'Finder.rez')
KEYNAV_AII = os.path.join(SRC_DIR, 'KeyboardNav', 'KeyboardNav.aii')

# `-d` defines: Finder.make's AOPTIONS + the KeyboardNavRsrc rule's own
# `-d InitVersion=0`.
KEYNAV_DEFINES = {'DEBUGSYMBOLS': 0, 'AllowServerCopies': 0,
                  'AllowSmartDesktop': 0, 'InitVersion': 0}

R_FINDER_EXTENSION = 0x0042

D3 = f'{dc.DISKS}/Disk 3 of 7 SystemTools1.2mg'
GOLDENS = [
    ('Finder (Disk 3)', D3, '/SystemTools1/System/Finder'),
    ('Start (System Disk)', None, f'{dc.V}/System/Start'),
]


def build_keyboardnav() -> bytes:
    """Assemble+link+ExpressLoad the KeyboardNav Finder extension per
    Finder.make's KeyboardNavRsrc rule (`AsmIIgs ... -d InitVersion=0`,
    `LinkIIgs -t $B6`; the golden bytes confirm ExpressLoad)."""
    a = asm.assemble(KEYNAV_AII, em.ASM_INCS, defines=KEYNAV_DEFINES)
    if a.errors:
        raise RuntimeError(f'KeyboardNav.aii: {len(a.errors)} assembly '
                           f'errors; first: {a.errors[0]}')
    return expressload([(omf.emit(a), a)])


def build_finder_fork() -> bytes:
    """Build the full Finder resource fork; returns bytes."""
    stmts = parser.parse(REZ_MASTER, include_dirs=INC,
                         predefined={'RezIIGS': 1})
    entries = gen.generate(stmts)
    keynav = build_keyboardnav()
    read_data = {(e.rtype, e.rid): keynav for e in entries
                 if e.rtype == R_FINDER_EXTENSION}
    tuples = gen.to_emit_tuples(entries, read_data)
    gold = rc.golden_fork(GOLDENS[0][2], GOLDENS[0][1])
    meta = rec._meta_from_golden(gold)
    return emit.emit_fork(tuples, meta)


def main():
    try:
        built = build_finder_fork()
    except Exception as e:                                   # noqa: BLE001
        print(f'FAIL build: {type(e).__name__}: {e}')
        sys.exit(1)
    good = tot = 0
    good_bytes = bad_bytes = 0
    for label, disk, path in GOLDENS:
        gold = rc.golden_fork(path, disk)
        tot += 1
        if built == gold.raw:
            good += 1
            good_bytes += len(gold.raw)
            print(f'PASS {label:20} {len(gold.raw)} bytes byte-exact '
                  f'(rsrc fork)')
        else:
            bad_bytes += len(gold.raw)
            rep = rc.compare(gold.raw, built)
            nbad = sum(1 for r in rep['resources'] if r['status'] != 'match')
            print(f'FAIL {label:20} built={len(built)} gold={len(gold.raw)} '
                  f'({nbad} resources differ)')
    print(f'\nfindercheck: {good}/{tot} golden copies byte-exact '
          f'FINDER_RSRC_BYTES_EXACT {good_bytes}/{good_bytes + bad_bytes}')


if __name__ == '__main__':
    main()
