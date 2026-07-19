#!/usr/bin/env python3
"""cdevcheck.py — rebuild CDEV resource forks from their Rez sources.

Tier-1 of the Rez template proving plan (docs/REZ_TYPES_PLAN.md follow-on):
each Control Panel device ships as a resource fork whose TEMPLATED resources
(rIcon, rCDEVFlags, …) compile from the archived CtlPanel `.r` source
through the clean-room include (gsasm/rez/include/TypesIIGS.r), while its
`read rCDEVCode` code resource is EXTRACTION-FED from the golden fork
itself: the code is opaque `read` input to Rez (the Pascal-built CDEVs are
a known non-reproducible wall; asm-built ones can graduate to source-built
loads later without changing this harness's contract).  What this check
proves byte-exact is the Rez layer: every templated resource, the map, the
memo, and the assembly of the fork around the code.

The five System-Disk CDEVs are wired into work/diskcheck.py's REZ_BUILDERS
(their files then count in disk_logical_exact); this harness is the
standalone runner + the gate's cdev_rsrc_bytes_exact metric source.

    python3 work/cdevcheck.py            # summary over all mapped CDEVs
    python3 work/cdevcheck.py Time       # one CDEV with per-resource detail
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
SRC_ROOT = 'ref/GSOS_6/IIGS.601.SRC/A.U.G/CtlPanel'

# CDEV name (as shipped in System/CDevs) -> archived Rez source.
CDEVMAP = {
    'General': 'GeneralCDEV/General.r',
    'Printer': 'PrinterCDEV/Printer.r',
    'RAM':     'RamDiskCDEV/RAMDisk.r',
    'Slots':   'SlotsCDEV/Slots.r',
    'Time':    'TimeCDEV/Time.r',
}

R_CDEVCODE = 0x8018


def golden(name):
    return rc.golden_fork(f'{dc.V}/System/CDevs/{name}')


def build_cdev_fork(name):
    """Build one CDEV's full resource fork; returns bytes."""
    gold = golden(name)
    src = os.path.join(SRC_ROOT, CDEVMAP[name])
    stmts = parser.parse(src, include_dirs=INC, predefined={'RezIIGS': 1})
    entries = gen.generate(stmts)
    # rCDEVCode is a `read` of the linked CDEV code: opaque bytes, supplied
    # from the golden fork (see module docstring).
    read_data = {(e.type, e.id): gold.raw[e.offset:e.offset + e.size]
                 for e in gold.used if e.type == R_CDEVCODE}
    tuples = gen.to_emit_tuples(entries, read_data)
    meta = rec._meta_from_golden(gold)
    return emit.emit_fork(tuples, meta)


def check(name, verbose=False):
    gold = golden(name)
    try:
        built = build_cdev_fork(name)
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
    for name in sorted(CDEVMAP):
        _, res, err = check(name)
        tot += 1
        if err:
            print(f'FAIL {name:10} {err}')
            continue
        b, g, ok = res
        if ok:
            good += 1
            good_bytes += g
            print(f'PASS {name:10} {g} bytes byte-exact (rsrc fork)')
        else:
            bad_bytes += g
            print(f'FAIL {name:10} built={b} gold={g} differs')
    print(f'\ncdevcheck: {good}/{tot} CDEV resource forks byte-exact '
          f'CDEV_RSRC_BYTES_EXACT {good_bytes}/{good_bytes + bad_bytes}')


if __name__ == '__main__':
    main()
