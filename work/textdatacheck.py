#!/usr/bin/env python3
"""textdatacheck.py — the four literal-text DATA forks, byte-compared to their
tracked sources.

The Disk 4 Read.Me / Shortcuts / Whats.New and Disk 5 Fonts Read.Me files
have Rez-built RESOURCE forks (work/rezdatacheck.py, `rez_data_bytes_exact`)
but their DATA forks are the plain document text, shipped verbatim from
tracked source files (the makefiles' `Duplicate` rules).  Until 2026-08-01 no
gate harness performed that byte comparison, so the census carried them as
no-source-substitute "byte-identical to a tracked source, but not gated" —
the exact gap flagged in the Packet-B report and re-confirmed by the dated
search backfill (both the D3/D4 and D5-7 search agents independently
byte-verified the equality against the golden images).

This harness IS that comparison: golden data fork (from the .2mg) == the
tracked source file, 1:1.  Trivial by design — the proof is the equality
itself, there is no build step (mirrors the makefiles, which just Duplicate).

Gate line: `TEXT_DATA_BYTES_EXACT good/total`; exit 0 only when fully exact.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import ROOT, ensure_a2til_on_path, ensure_repo_on_path  # noqa: E402
ensure_repo_on_path()

DISKS = os.path.join(ROOT, 'ref', 'GSOS_6', 'System601_disks', 'System 6.0.1')
SRC = os.path.join(ROOT, 'ref', 'GSOS_6', 'IIGS.601.SRC')

# (disk image, on-disk path, tracked source file)
TARGETS = [
    ('Disk 4 of 7 SystemTools2.2mg', '/SystemTools2/Read.Me',
     f'{SRC}/ToolBoxMisc/ReadMeFiles/Read.Me.text'),
    ('Disk 4 of 7 SystemTools2.2mg', '/SystemTools2/Shortcuts',
     f'{SRC}/ToolBoxMisc/ReadMeFiles/Shortcuts.text'),
    ('Disk 4 of 7 SystemTools2.2mg', '/SystemTools2/Whats.New',
     f'{SRC}/ToolBoxMisc/ReadMeFiles/Whats.New.text'),
    ('Disk 5 of 7 Fonts.2mg', '/Fonts/Goodies/Read.Me',
     f'{SRC}/A.U.G/Apple.Bowl/Read.Me.txt'),
]


def run():
    ensure_a2til_on_path('textdatacheck')
    from a2til.prodos import Volume
    vols = {}
    good = total = 0
    for disk, path, src in TARGETS:
        if disk not in vols:
            vols[disk] = Volume(open(os.path.join(DISKS, disk), 'rb').read())
        gold = vols[disk].read_file(path)
        mine = open(src, 'rb').read()
        n = len(gold)
        ok = mine == gold
        good += n if ok else sum(1 for a, b in zip(mine, gold) if a == b)
        total += n
        print(f'  {path:30} {"PASS" if ok else "DIFF"}  {n}B')
    print(f'TEXT_DATA_BYTES_EXACT {good}/{total}')
    return good, total


if __name__ == '__main__':
    good, total = run()
    sys.exit(0 if good == total else 1)
