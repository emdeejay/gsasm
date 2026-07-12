#!/usr/bin/env python3
"""drivercheck.py — validate gsasm against shipping System 6.0.1 driver files.

Assembles each driver from source (ref/GSOS_6/IIGS.601.SRC/GS.OS/{Drivers,
SupervisoryDrivers}/), links the object(s), and byte-compares against the
shipping driver binary extracted from the System 6.0.1 disk images
(ref/GSOS_6/driver_bin/).

All shipping drivers are ExpressLoad'd OMF (leading ~ExpressLoad segment,
KIND 0x8001).  de_express() strips the directory segment and returns the
CONST/LCONST code image; our linked image is compared against that.

    python3 work/drivercheck.py               # summary over every mapped driver
    python3 work/drivercheck.py Console.Driver  # one driver with first-diff detail
    python3 work/drivercheck.py SCSIHD        # partial name match also works

Golden binary extraction (one-time, cadius):
    DISK1="ref/GSOS_6/System601_disks/System 6.0.1/Disk 1 of 7 Install.2mg"
    DISK2="ref/GSOS_6/System601_disks/System 6.0.1/Disk 2 of 7 System Disk.2mg"
    DISK3="ref/GSOS_6/System601_disks/System 6.0.1/Disk 3 of 7 SystemTools1.2mg"
    DISK4="ref/GSOS_6/System601_disks/System 6.0.1/Disk 4 of 7 SystemTools2.2mg"

    # Disk 2 (System Disk)
    for f in AppleDisk3.5 AppleDisk5.25 Console.Driver; do
      cadius EXTRACTFILE "$DISK2" "/System.Disk/System/Drivers/$f" ref/GSOS_6/driver_bin/
    done
    # Disk 1 (Install) — SCSIHD.Driver and UniDisk3.5
    cadius EXTRACTFILE "$DISK1" "/Install/System/Drivers/SCSIHD.Driver" ref/GSOS_6/driver_bin/
    cadius EXTRACTFILE "$DISK1" "/Install/System/Drivers/UniDisk3.5"    ref/GSOS_6/driver_bin/
    # Disk 3 (SystemTools1)
    for f in RAM5 SCSI.Manager SCSICD.Driver SCSIScan.Driver SCSITape.Driver; do
      cadius EXTRACTFILE "$DISK3" "/SystemTools1/System/Drivers/$f" ref/GSOS_6/driver_bin/
    done
    # Disk 4 (SystemTools2)
    for f in ATalk SCC.Manager; do
      cadius EXTRACTFILE "$DISK4" "/SystemTools2/System/Drivers/$f" ref/GSOS_6/driver_bin/
    done

Source → shipping-name map (from GS.OS/MakeFiles/make.*):
  AppleDisk3.5  — Drivers/AppleDisk3.5/AD3.5.src     (single src, -i common)
  AppleDisk5.25 — Drivers/AppleDisk5.25/AppleDisk5.25.src
  Console.Driver — Drivers/Console.Driver/Console.aii + New.DRI.Patch  (-d Library=0)
  UniDisk3.5    — Drivers/UniDisk3.5/UniDisk3.5.src
  RAM5          — Drivers/RAM5/RAM5.aii
  ATalk         — Drivers/ATalk/Main.aii + rpm.aii + AppleTalk.aii + Others.aii
  SCSIHD.Driver — Drivers/SCSI.Drivers/{SCSI Driver main,...} × 13  (-d type=0)
  SCSICD.Driver — same shared sources × 13  (-d type=1)
  SCSIScan.Driver — same shared sources × 13  (-d type=3)  (at $0103)
  SCSITape.Driver — same shared sources × 13  (-d type=2)  (at $0103)
  SCSI.Manager  — SupervisoryDrivers/SCSI.Manager(1meg)/SCSIM.{Header,...} × 11
  SCC.Manager   — SupervisoryDrivers/SCCManager/Driver.aii
  (Slinky not shipped on 6.0.1 disks; ETalk / ATBoot / ATRam / ATRom not in scope)

Packaging: all drivers are ExpressLoad'd (KIND 0x8001 leading segment).

Known residuals:
  * lda #^Label bank-byte immediates resolve to 0 (SUPER type 27 reloc gap).
    This accounts for some diffs in Console.Driver (277/6297 bytes).
  * Multi-object drivers (SCSI family, ATalk, SCSI.Manager): sizing drift.
    Per-segment m65816 instruction-length mismatches cascade through address
    tables.  Same class as multi-object tool managers — unfixed per-module
    gsasm-core issue.  NOT a new gap: the ROM effort documented this.
  * RAM5: size mismatch (1459 gsasm vs 1564 golden).  Separately tracked as
    OurDIB-RAMDisk = 0x549 vs 0x599 sizing drift; will improve with core fix.
  * AppleDisk3.5: size mismatch (6381 vs 6984).  Multi-segment sizing drift.
  * SCC.Manager: small size mismatch (1261 vs 1500).  Same class.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from gsasm import asm, omf, linkiigs
from gsasm.expressload import de_express

SRC   = 'ref/GSOS_6/IIGS.601.SRC'
GSOS  = SRC + '/GS.OS'
CMN   = GSOS + '/Common'
DBIN  = 'ref/GSOS_6/driver_bin'

# Include path: Common first (has common.equ.src / hw.equ.src / driver.equ.src),
# then every GS.OS subdir (so per-driver equate files are reachable).
INCS = ([CMN] + [d for d, _, _ in os.walk(GSOS)]
        + [os.path.join(os.path.dirname(os.path.abspath(__file__)), 'includes')])

# SCSI shared source files (shared by HD/CD/Scan/Tape with different -d type=N)
_SCSI_SHARED = [
    'SCSI Driver main',
    'SCSI Command Table',
    'SCSI Filter startup',
    'SCSI Filter open',
    'SCSI Filter read',
    'SCSI Filter write',
    'SCSI Filter close',
    'SCSI Filter status',
    'SCSI Filter control',
    'SCSI Filter flush',
    'SCSI Filter shutdown',
    'SCSI Main Driver',
    'SCSI Driver Mgmt',
]
_SCSI_DRV_DIR = 'Drivers/SCSI.Drivers'

# SCSI.Manager supervisory driver source files
_SCSI_MGR_FILES = [
    'SCSIM.Header',
    'SCSIM.History',
    'SCSIM.Variables',
    'SCSIM.Entry',
    'SCSIM.Startup',
    'SCSIM.Shutdown',
    'SCSIM.Req.Devs',
    'SCSIM.Claim.Devs',
    'SCSIM.IO.Calls',
    'SCSIM.Mgmnt',
    'SCSIM.Misc',
]
_SCSI_MGR_DIR = 'SupervisoryDrivers/SCSI.Manager(1meg)'

# Driver shipping-name -> (source-subdir, [source-files], {defines})
# Per GS.OS/MakeFiles/make.* — transcribed exactly, no guessing.
DRIVERMAP = {
    'AppleDisk3.5': (
        'Drivers/AppleDisk3.5',
        ['AD3.5.src'],
        {},
    ),
    'AppleDisk5.25': (
        'Drivers/AppleDisk5.25',
        ['AppleDisk5.25.src'],
        {},
    ),
    'Console.Driver': (
        'Drivers/Console.Driver',
        ['Console.aii', 'New.DRI.Patch'],
        {'Library': 0},
    ),
    'UniDisk3.5': (
        'Drivers/UniDisk3.5',
        ['UniDisk3.5.src'],
        {},
    ),
    'RAM5': (
        'Drivers/RAM5',
        ['RAM5.aii'],
        {},
    ),
    'ATalk': (
        'Drivers/ATalk',
        ['Main.aii', 'rpm.aii', 'AppleTalk.aii', 'Others.aii'],
        {},
    ),
    'SCSIHD.Driver': (
        _SCSI_DRV_DIR,
        _SCSI_SHARED,
        {'type': 0},
    ),
    'SCSICD.Driver': (
        _SCSI_DRV_DIR,
        _SCSI_SHARED,
        {'type': 1},
    ),
    'SCSITape.Driver': (
        _SCSI_DRV_DIR,
        _SCSI_SHARED,
        {'type': 2},
    ),
    'SCSIScan.Driver': (
        _SCSI_DRV_DIR,
        _SCSI_SHARED,
        {'type': 3},
    ),
    'SCSI.Manager': (
        _SCSI_MGR_DIR,
        _SCSI_MGR_FILES,
        {},
    ),
    'SCC.Manager': (
        'SupervisoryDrivers/SCCManager',
        ['Driver.aii'],
        {},
    ),
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
    """Return candidate paths for the golden binary (cadius appends #TTAAAA)."""
    # Drivers are type $BB; aux type varies per make.*
    # cadius preserves original filename + appends #TTAAAA
    yield f'{DBIN}/{name}#BB0101'
    yield f'{DBIN}/{name}#BB0104'
    yield f'{DBIN}/{name}#BB0107'
    yield f'{DBIN}/{name}#BB0108'
    yield f'{DBIN}/{name}#BB010E'
    yield f'{DBIN}/{name}#BB0110'
    yield f'{DBIN}/{name}#BB013F'
    yield f'{DBIN}/{name}#BB0140'
    yield f'{DBIN}/{name}#BB0103'
    yield f'{DBIN}/{name}'
    # Fallback: scan directory for any file starting with the name
    try:
        for fn in os.listdir(DBIN):
            if fn.startswith(name + '#') or fn == name:
                yield f'{DBIN}/{fn}'
    except FileNotFoundError:
        pass


def golden(name: str) -> bytes | None:
    seen = set()
    for cand in _golden_candidates(name):
        if cand in seen:
            continue
        seen.add(cand)
        if os.path.exists(cand):
            return de_express(cand)
    return None


# Drivers that embed the original build timestamp via `dc.b '&Sysdate &SysTime'`
# — the &Sysdate/&SysTime builtins must reproduce the captured build time for a
# byte-exact match (same mechanism kernelcheck uses for GS.OS's 06-May-93 build).
# The value is a fact of the shipping binary, extracted from the golden image.
DRIVER_BUILD_TIME = {
    'RAM5': ('06-May-93', '16:11:47'),
}


def link_driver(subdir, sources, defines, build_time=None):
    """Assemble and link one driver.  Returns the code image bytes."""
    drv_dir = f'{GSOS}/{subdir}'
    extra = [drv_dir]
    incs = extra + INCS
    sysdate, systime = build_time or (None, None)
    objects = []
    for src in sources:
        a = asm.assemble(f'{drv_dir}/{src}', incs, defines=defines or None,
                         sysdate=sysdate, systime=systime)
        obj = omf.emit(a)
        objects.append((obj, a))
    result = linkiigs.link(objects, opts={'merge': True})
    return _extract_img(result)


def check(name: str, verbose: bool = False):
    if name not in DRIVERMAP:
        return name, None, None, f'not in DRIVERMAP'
    subdir, sources, defines = DRIVERMAP[name]
    g = golden(name)
    if g is None:
        return name, subdir, None, 'no golden binary (run cadius extraction)'
    try:
        mine = link_driver(subdir, sources, defines,
                           DRIVER_BUILD_TIME.get(name))
    except Exception as e:
        import traceback
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
        arg = sys.argv[1]
        name = arg
        if name not in DRIVERMAP:
            # Try partial match (e.g. "SCSIHD" -> "SCSIHD.Driver")
            matches = [k for k in DRIVERMAP if k.startswith(arg) or arg.upper() in k.upper()]
            if len(matches) == 1:
                name = matches[0]
            elif len(matches) > 1:
                print(f'ambiguous: {", ".join(matches)}')
                return
            else:
                print(f'unknown/unmapped driver {arg!r}; mapped: {", ".join(sorted(DRIVERMAP))}')
                return
        check(name, verbose=True)
        return

    print(f'{"Driver":<18} {"subdir":<38} {"match":>7}  {"bytes (gsasm/gold)":>20}  {"pkg"}')
    print('-' * 100)
    tot_m = tot_n = 0
    for name in sorted(DRIVERMAP):
        n_name, subdir, res, err = check(name)
        pkg = _packaging(name)
        if res is None:
            print(f'{name:<18} {str(subdir):<38} {"--":>7}  {err}  {pkg}')
            continue
        pct, m, n, lg, lo = res
        tot_m += m
        tot_n += n
        print(f'{name:<18} {subdir:<38} {pct:>6}%  {lg:>8}/{lo:<8}  ({m}/{n} bytes)  {pkg}')
    print()
    if tot_n:
        print(f'CORPUS raw code-image match: {tot_m}/{tot_n} ({100 * tot_m // tot_n}%)')
    print()
    print('Packaging note: all drivers are ExpressLoad\'d (KIND 0x8001 leading segment).')
    print('Slinky, ETalk/ATBoot/ATRam/ATRom not on any 6.0.1 disk or skipped.')


if __name__ == '__main__':
    main()
