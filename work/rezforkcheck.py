#!/usr/bin/env python3
"""rezforkcheck.py — rebuild five small A.U.G/ToolBoxMisc resource forks
from their archived Rez sources, byte-exact, through the SAME clean-room
pipeline cdevcheck.py/findercheck.py already exercise: `gsasm.rez.parser`
+ `gen` + `emit`, with the clean-room `gsasm/rez/include/TypesIIGS.r`
providing every template (`RezIIGS: 1` predefined). No gsasm pipeline
change was needed to reach byte-exact here — a feasibility probe already
established that; this harness only wires the five forks into a runnable
check + gate metric.

    FindFile     — Desk Accessory (ToolBoxMisc/FindFileGS/Findfile.rez).
                   Ships as /SystemTools1/System/Desk.Accs/FindFile on
                   Disk 3.  Pure-Rez fork: no `read`/code resources.
    Apple.Bowl   — app (A.U.G/Apple.Bowl/Bowl.r).  Ships as
                   /Fonts/Goodies/Apple.Bowl on Disk 5.  rVersion/rIcon/
                   rBundle only — no code resources.
    MediaControl — NDA (A.U.G/MediaCtl/MediaCtlNDA/MediaCtlNDA.rii).
                   Ships as /SystemTools2/System/Desk.Accs/MediaControl
                   on Disk 4.  rVersion/rComment only.
    VideoMix     — NDA (A.U.G/VideoMix/VideoMix.NDA/VideoMixNDA.rii).
                   Ships as /SystemTools2/System/Desk.Accs/VideoMix on
                   Disk 4.  rVersion/rComment only.
    Pioneer4200  — Media.Control driver's RESOURCE fork
                   (A.U.G/MediaCtl/P4200/P4200.r; its DATA fork is already
                   proven byte-exact by work/appdatacheck.py).  Ships as
                   /SystemTools2/System/Drivers/Media.Control/Pioneer4200
                   on Disk 4.  A single rPstring — no code resources.

None of the five sources declare a `read` resource, so — unlike
cdevcheck's rCDEVCode/rCodeResource extraction-feed — no golden bytes need
splicing in here. `build_rez_fork` still DETECTS any `kind == 'read'`
entry generically (matching cdevcheck's rCDEVCode/rCodeResource types plus
any other `read`) and gold-feeds it from the golden fork's raw resource
data, so the harness doesn't silently break if a future target needs it.

Deliberately NOT wired into work/diskcheck.py (none of these five files
are on the System Disk diskcheck walks) — standalone runner + the gate's
rezfork_bytes_exact metric source, same footing as cdevcheck/appdatacheck.

    python3 work/rezforkcheck.py            # summary over all 5 targets
    python3 work/rezforkcheck.py FindFile   # one target, verbose diff
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
SRC_ROOT = 'ref/GSOS_6/IIGS.601.SRC'

D3 = f'{dc.DISKS}/Disk 3 of 7 SystemTools1.2mg'
D4 = f'{dc.DISKS}/Disk 4 of 7 SystemTools2.2mg'
D5 = f'{dc.DISKS}/Disk 5 of 7 Fonts.2mg'

# name -> (disk image, on-disk path, source path relative to SRC_ROOT)
REZMAP = {
    'FindFile': (
        D3, '/SystemTools1/System/Desk.Accs/FindFile',
        'ToolBoxMisc/FindFileGS/Findfile.rez'),
    'Apple.Bowl': (
        D5, '/Fonts/Goodies/Apple.Bowl',
        'A.U.G/Apple.Bowl/Bowl.r'),
    'MediaControl': (
        D4, '/SystemTools2/System/Desk.Accs/MediaControl',
        'A.U.G/MediaCtl/MediaCtlNDA/MediaCtlNDA.rii'),
    'VideoMix': (
        D4, '/SystemTools2/System/Desk.Accs/VideoMix',
        'A.U.G/VideoMix/VideoMix.NDA/VideoMixNDA.rii'),
    'Pioneer4200': (
        D4, '/SystemTools2/System/Drivers/Media.Control/Pioneer4200',
        'A.U.G/MediaCtl/P4200/P4200.r'),
}


def golden(name):
    disk, path, _src = REZMAP[name]
    return rc.golden_fork(path, disk)


def build_rez_fork(name):
    """Build one target's full resource fork; returns bytes."""
    gold = golden(name)
    src = os.path.join(SRC_ROOT, REZMAP[name][2])
    stmts = parser.parse(src, include_dirs=INC, predefined={'RezIIGS': 1})
    entries = gen.generate(stmts)
    # Any `read` (kind == 'read') entry is opaque input Rez never
    # generates itself (see gen.to_emit_tuples' docstring); gold-feed it
    # from the golden fork's raw resource data by (type, id), exactly as
    # cdevcheck.py does for rCDEVCode/rCodeResource. None of the five
    # REZMAP sources currently declare one, but this stays generic rather
    # than hardcoding "no reads here".
    read_types = {e.rtype for e in entries if e.kind == 'read'}
    read_data = {(e.type, e.id): gold.raw[e.offset:e.offset + e.size]
                 for e in gold.used if e.type in read_types}
    tuples = gen.to_emit_tuples(entries, read_data)
    meta = rec._meta_from_golden(gold)
    return emit.emit_fork(tuples, meta)


def check(name, verbose=False):
    gold = golden(name)
    try:
        built = build_rez_fork(name)
    except Exception as e:                                   # noqa: BLE001
        return name, None, f'{type(e).__name__}: {e}'
    ok = built == gold.raw
    if verbose and not ok:
        rep = rc.compare(gold.raw, built)
        for r in rep.get('resources', []):
            if r['status'] != 'match':
                print(f'  {r}')
    return name, (len(built), len(gold.raw), ok), None


def main():
    if len(sys.argv) > 1:
        want = sys.argv[1]
        name, res, err = check(want, verbose=True)
        if err:
            print(f'{name}: {err}')
        else:
            b, g, ok = res
            print(f'{name}: built={b} gold={g} '
                  f'{"BYTE-EXACT" if ok else "DIFFERS"}')
        return
    tot = good = 0
    good_bytes = bad_bytes = 0
    for name in sorted(REZMAP):
        _, res, err = check(name)
        tot += 1
        if err:
            print(f'FAIL {name:12} {err}')
            continue
        b, g, ok = res
        if ok:
            good += 1
            good_bytes += g
            print(f'PASS {name:12} {g} bytes byte-exact (rsrc fork)')
        else:
            bad_bytes += g
            print(f'FAIL {name:12} built={b} gold={g} differs')
    print(f'\nrezforkcheck: {good}/{tot} resource forks byte-exact '
          f'REZFORK_BYTES_EXACT {good_bytes}/{good_bytes + bad_bytes}')


if __name__ == '__main__':
    main()
