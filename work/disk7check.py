#!/usr/bin/env python3
"""disk7check.py — builder-correctness for Disk 7 (Apple II Setup).

Disk 7 is an HFS volume (inside a 2IMG wrapper), read via work/hfs.py.  This
harness proves that the buildable forks on that disk rebuild byte-exact from
source — the SOW's builder-correctness target — WITHOUT a whole-disk overlay
(the HFS overlay writer / physical_exact reconstruction is out of scope).

Files proven here (all data forks):
  * /System Folder/Basic.System — the same BASIC.System diskcheck builds for the
    System Disk (basiccheck), byte-identical here.
  * /IWEm — a PostScript prolog, byte-identical to the tracked first-party source
    GSToolbox/PrinterDrivers/IWEm/IWEm (a data file, not assembled).
  * /System Folder/p8 — the ProDOS-8 file, byte-exact from the same MliSrc.aii +
    P8.Drivers as the System Disk's p8 but with this disk's earlier build date
    (02-Apr-93 vs 06-May-93 — the only difference, an embedded date string).

    python3 work/disk7check.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import ensure_repo_on_path
ensure_repo_on_path()

import diskcheck as dc                       # noqa: E402  (DISKS locator)
import drivercheck                           # noqa: E402  (INCS)
import hfs                                   # noqa: E402
import basiccheck                            # noqa: E402
import diskbuilders.p8_driver as p8_driver   # noqa: E402
from gsasm import asm as _asm, omf as _omf, linkiigs as _link, makebin as _mkb  # noqa: E402

_NB = os.path.join('ref/GSOS_6/IIGS.601.SRC', 'GS.OS', 'NetBoot')

_DISK = os.path.join(dc.DISKS, 'Disk 7 of 7 Apple II Setup.2mg')
_IWEM_SRC = os.path.join(
    dc.gsos_source_root() if hasattr(dc, 'gsos_source_root') else
    'ref/GSOS_6/IIGS.601.SRC',
    'GSToolbox', 'PrinterDrivers', 'IWEm', 'IWEm')


def build_basic_system():
    return dc._build_basic_system()


def build_iwem():
    with open(_IWEM_SRC, 'rb') as fh:        # PostScript prolog, carried as-is
        return fh.read()


def build_p8():
    return p8_driver._build_p8(sysdate='02-Apr-93')


def _nb_obj(rel, incdirs=(), defines=None):
    """Assemble one NetBoot source (subdir-first include path)."""
    sub = os.path.join(_NB, os.path.dirname(rel))
    incs = [os.path.join(_NB, d) for d in incdirs] + [sub] + drivercheck.INCS
    a = _asm.assemble(os.path.join(_NB, rel), incs, defines=defines or None)
    if a.errors:
        raise RuntimeError(f'{rel}: {len(a.errors)} asm errors; '
                           f'first: {a.errors[0]}')
    return _omf.emit(a), a


def build_p16_boot_blocks():
    """ProDOS16 Boot Blocks data fork: LinkIIGS boot.o ; MakeBinIIGS -org $800
    (NetBoot/Makefile). The link is fully resolved (defer_shifts=False) at the
    MakeBin org, like the shipping flat file."""
    obj = _nb_obj('Boot/boot.aii')
    linked = _link.link([obj], opts={'merge': True, 'org': 0x800,
                                     'defer_shifts': False})
    return _mkb.makebin(linked, 0x800)


def build_iie_boot_blocks():
    """Apple //e Boot Blocks data fork: Catenate {iie}Reloc :work:P8
    :Logon:BootLog8 (NetBoot/Makefile).
      BootLog8 = LinkIIGS(BootLog8.o, Console.o, DES.o) ; MakeBinIIGS
                 -org $2000+P8Size (P8Size = 17128)
      Reloc    = AsmIIGS -d P8Size -d LogonSize=len(BootLog8) ; Link ; MakeBin
      P8       = this disk's 02-Apr-93 build (build_p8)."""
    objs = [_nb_obj('Logon/BootLog8.aii', ['Console']),
            _nb_obj('Console/Console.aii', ['Console']),
            _nb_obj('Logon/DES.aii')]
    logon_org = 0x2000 + 17128
    linked = _link.link(objs, opts={'merge': True, 'org': logon_org,
                                    'defer_shifts': False})
    bootlog8 = bytes(_mkb.makebin(linked, logon_org))
    robj = _nb_obj('IIeBlocks/Reloc.aii',
                   defines={'P8Size': 17128, 'LogonSize': len(bootlog8)})
    reloc = bytes(_mkb.makebin(
        _link.link([robj], opts={'merge': True, 'org': 0,
                                 'defer_shifts': False}), 0))
    return reloc + bytes(build_p8()) + bootlog8


# (parID, name, builder) — parID from hfs.files (2 = root, 19 = System Folder)
_TARGETS = [
    (19, 'Basic.System', build_basic_system),
    (2,  'IWEm',         build_iwem),
    (19, 'p8',           build_p8),
    (19, 'ProDOS16 Boot Blocks',  build_p16_boot_blocks),
    (19, 'Apple //e Boot Blocks', build_iie_boot_blocks),
]


def run():
    vol = hfs.HFS(path=_DISK)
    good = total = 0
    rows = []
    for parID, name, builder in _TARGETS:
        gold = bytes(vol.data(parID, name))
        try:
            built = bytes(builder())
        except Exception as e:                # pragma: no cover
            rows.append(f'  {name:14} BUILD ERROR: {e}')
            total += len(gold)
            continue
        n = len(gold)
        m = n if built == gold else sum(1 for i in range(min(len(built), n))
                                        if built[i] == gold[i])
        good += m if built == gold else 0     # count only fully-exact forks
        total += n
        rows.append(f'  {name:14} {"PASS" if built == gold else "DIFF"}  '
                    f'{len(built)}/{n}B')
    print('\n'.join(rows))
    print(f'DISK7_BYTES_EXACT {good}/{total}')
    return good, total


if __name__ == '__main__':
    run()
