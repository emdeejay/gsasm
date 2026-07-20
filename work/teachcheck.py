#!/usr/bin/env python3
"""teachcheck.py — rebuild the Teach resource fork from its Rez source.

Rez tier-1, Teach sweep (docs/REZ_TYPES_PLAN.md phase-2): the shipped
Teach editor's resource fork (Disk 4, 7,333 B, 133 resources) compiles
from the archived `ToolBoxMisc/Teach/teach.r` through the clean-room
include (Teach's code is Pascal — the data fork stays a wall; the Rez
layer is what this proves).  Teach exercised previously-unproven include
surface: the rMenuBar template, the TB* LETextBox2 escape defines, the
wFrameBits defines, and six menu/menu-item flag constants — all recovered
via the token oracle and byte-proven here.

    python3 work/teachcheck.py
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
SRC = 'ref/GSOS_6/IIGS.601.SRC/ToolBoxMisc/Teach/teach.r'
DISK = f'{dc.DISKS}/Disk 4 of 7 SystemTools2.2mg'
PATH = '/SystemTools2/Teach'


def build_teach_fork() -> bytes:
    """Build the Teach resource fork; returns bytes."""
    stmts = parser.parse(SRC, include_dirs=INC, predefined={'RezIIGS': 1})
    entries = gen.generate(stmts)
    gold = rc.golden_fork(PATH, DISK)
    return emit.emit_fork(gen.to_emit_tuples(entries),
                          rec._meta_from_golden(gold))


def main():
    gold = rc.golden_fork(PATH, DISK)
    try:
        built = build_teach_fork()
    except Exception as e:                                   # noqa: BLE001
        print(f'FAIL build: {type(e).__name__}: {e}')
        sys.exit(1)
    if built == gold.raw:
        print(f'PASS Teach {len(gold.raw)} bytes byte-exact (rsrc fork)')
        good, bad = len(gold.raw), 0
    else:
        rep = rc.compare(gold.raw, built)
        nbad = sum(1 for r in rep['resources'] if r['status'] != 'match')
        print(f'FAIL Teach built={len(built)} gold={len(gold.raw)} '
              f'({nbad} resources differ)')
        good, bad = 0, len(gold.raw)
    print(f'\nteachcheck: TEACH_RSRC_BYTES_EXACT {good}/{good + bad}')


if __name__ == '__main__':
    main()
