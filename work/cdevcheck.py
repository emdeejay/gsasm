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

# Shipped file -> (disk image, absolute volume path, archived Rez source).
# The ControlPanel NDA rides along: same CtlPanel tree, pure-Rez fork (no
# rCDEVCode), one extra template (rTwoRects) + the listControl case.
# CDEVs shipping on several disks are checked against ONE canonical copy.
D1 = f'{dc.DISKS}/Disk 1 of 7 Install.2mg'
D2 = None                                   # the default System Disk
D3 = f'{dc.DISKS}/Disk 3 of 7 SystemTools1.2mg'
D4 = f'{dc.DISKS}/Disk 4 of 7 SystemTools2.2mg'

CDEVMAP = {
    'General': (D2, f'{dc.V}/System/CDevs/General',  'GeneralCDEV/General.r'),
    'Printer': (D2, f'{dc.V}/System/CDevs/Printer',  'PrinterCDEV/Printer.r'),
    'RAM':     (D2, f'{dc.V}/System/CDevs/RAM',      'RamDiskCDEV/RAMDisk.r'),
    'Slots':   (D2, f'{dc.V}/System/CDevs/Slots',    'SlotsCDEV/Slots.r'),
    'Time':    (D2, f'{dc.V}/System/CDevs/Time',     'TimeCDEV/Time.r'),
    'ControlPanel': (D2, f'{dc.V}/System/Desk.Accs/ControlPanel',
                     'CtlPanelNDA/CtlPanel.rez'),
    'DirectConnect': (D3, '/SystemTools1/System/CDevs/DirectConnect',
                      'DirectConnectCDEV/DIRECTCONNECT.R'),
    'Keyboard': (D3, '/SystemTools1/System/CDevs/Keyboard',
                 'KeyboardCDEV/Keyboard.r'),
    'Modem':   (D3, '/SystemTools1/System/CDevs/Modem',   'ModemCDEV/Modem.r'),
    'Monitor': (D3, '/SystemTools1/System/CDevs/Monitor', 'MonitorCDEV/Monitor.r'),
    'Sound':   (D3, '/SystemTools1/System/CDevs/Sound',   'SoundCDEV/Sound.r'),
    'AppleShare': (D4, '/SystemTools2/System/CDevs/AppleShare',
                   'AppleShareCDEV/AppleShare.r'),
    'FolderPriv': (D4, '/SystemTools2/System/CDevs/FolderPriv',
                   'FolderPrivCDEV/FolderPriv.r'),
    'Namer':   (D4, '/SystemTools2/System/CDevs/Namer',   'NamerCDEV/namer.r'),
    'NetPrinter': (D4, '/SystemTools2/System/CDevs/NetPrinter',
                   'NetPrinterCDEV/netprinter.r'),
    'Network': (D4, '/SystemTools2/System/CDevs/Network', 'NetworkCDEV/network.r'),
    'SetStart': (D1, '/Install/System/CDevs/SetStart',    'SetStartCDEV/SetStart.r'),
}

R_CDEVCODE = 0x8018
R_CODERESOURCE = 0x8017


def golden(name):
    disk, path, _src = CDEVMAP[name]
    return rc.golden_fork(path, disk)


def build_cdev_fork(name):
    """Build one CDEV's full resource fork; returns bytes."""
    gold = golden(name)
    src = os.path.join(SRC_ROOT, CDEVMAP[name][2])
    stmts = parser.parse(src, include_dirs=INC, predefined={'RezIIGS': 1})
    entries = gen.generate(stmts)
    # rCDEVCode / rCodeResource are `read`s of linked code: opaque bytes,
    # supplied from the golden fork (see module docstring).
    read_data = {(e.type, e.id): gold.raw[e.offset:e.offset + e.size]
                 for e in gold.used
                 if e.type in (R_CDEVCODE, R_CODERESOURCE)}
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
