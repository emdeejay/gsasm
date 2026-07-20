#!/usr/bin/env python3
"""installercheck.py — rebuild the Installer resource fork from its Rez source.

Rez tier-1, Installer sweep (docs/REZ_TYPES_PLAN.md phase-2): the shipped
Installer's resource fork (Disk 1, 17,895 B, 90 resources) compiles from
the archived `A.U.G/Installer/Installer.r`.  Unlike the CDEV/Finder
targets, Installer.r is fully SELF-CONTAINED: it declares all fifteen of
its own type templates (rInstallScript, rDiskNames, rPicture, rMenuBar,
rCtlColorTbl, ... — corpus-local, same policy as rMyCursor) and includes
nothing, so this target proves the DIALECT rather than the bundled
include: `<<`/`>>` shift operators, `0b` literals, `#if defined`, `\\t`,
`string [N]` zero-padding, and the rPicture Clip case's subscripted
`$$Word(label[$$ArrayIndex(...)])` width idiom.

The MakeFile builds the shipped variant with `-d SystemSoftware` (Easy
Update activated); RezIIGS is predefined as usual.

    python3 work/installercheck.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import ensure_repo_on_path
ensure_repo_on_path()

import rezcheck as rc
import diskcheck as dc
import rezemitcheck as rec
from gsasm.rez import parser, gen, emit

INC = ['gsasm/rez/include']
SRC = 'ref/GSOS_6/IIGS.601.SRC/A.U.G/Installer/Installer.r'
DISK = f'{dc.DISKS}/Disk 1 of 7 Install.2mg'
PATH = '/Install/Installer'


def build_installer_fork() -> bytes:
    """Build the Installer resource fork; returns bytes."""
    stmts = parser.parse(SRC, include_dirs=INC,
                         predefined={'RezIIGS': 1, 'SystemSoftware': 1})
    entries = gen.generate(stmts)
    gold = rc.golden_fork(PATH, DISK)
    meta = rec._meta_from_golden(gold)
    return emit.emit_fork(gen.to_emit_tuples(entries), meta)


def main():
    gold = rc.golden_fork(PATH, DISK)
    try:
        built = build_installer_fork()
    except Exception as e:                                   # noqa: BLE001
        print(f'FAIL build: {type(e).__name__}: {e}')
        sys.exit(1)
    if built == gold.raw:
        print(f'PASS Installer {len(gold.raw)} bytes byte-exact (rsrc fork)')
        good, bad = len(gold.raw), 0
    else:
        rep = rc.compare(gold.raw, built)
        nbad = sum(1 for r in rep['resources'] if r['status'] != 'match')
        print(f'FAIL Installer built={len(built)} gold={len(gold.raw)} '
              f'({nbad} resources differ)')
        good, bad = 0, len(gold.raw)
    print(f'\ninstallercheck: INSTALLER_RSRC_BYTES_EXACT {good}/{good + bad}')


if __name__ == '__main__':
    main()
