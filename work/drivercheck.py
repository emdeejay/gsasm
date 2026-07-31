#!/usr/bin/env python3
"""drivercheck.py — validate gsasm against shipping System 6.0.1 driver files.

Assembles each driver from source — the GS.OS drivers under
ref/GSOS_6/IIGS.601.SRC/GS.OS/{Drivers,SupervisoryDrivers}/ and the shipped
PrinterDrivers/MIDI drivers under .../GSToolbox/ — links the object(s), and
byte-compares against the shipping driver binary.  The golden binary is either a
cadius-extracted file in ref/GSOS_6/driver_bin/ or, when that is absent, the data
fork read straight out of the 6.0.1 disk image via a2til (NO cadius needed).

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
  A2.RAMCard    — Drivers/Slinky/slinky.aii  (the shipped Slinky/RamFactor driver,
                  SystemTools1/Disk 3)
  Modem         — GSToolbox/PrinterDrivers/Modem/{modem,dialogdata}.asm
  Parallel.Card — GSToolbox/PrinterDrivers/GraphiCard/{graphicard,dialogdata}.asm
  Printer       — GSToolbox/PrinterDrivers/Printer/{printer,dialogdata}.asm
  AppleTalk     — GSToolbox/PrinterDrivers/AppleTalk/{appletalk,dialogdata}.asm
                  (the PRINTER driver on SystemTools2/Disk 4, NOT GS.OS ATalk)
  Apple.Midi    — GSToolbox/Midi/Drivers/Apple.Midi/apple.midi.aii
  Card6850.MIDI — GSToolbox/Midi/Drivers/Card6850.Midi/card6850.midi.aii
  (ETalk / ATBoot / ATRam / ATRom not in scope)

Packaging: all drivers are ExpressLoad'd (KIND 0x8001 leading segment).

Status:
  All 19 mapped shipping drivers are byte-exact (106,730/106,730) — the original
  12 GS.OS drivers (94,948 B) plus 7 sweep-proven adds: A2.RAMCard (Slinky) and
  the 6 GSToolbox printer/MIDI drivers (Modem, Parallel.Card, Printer, AppleTalk,
  Apple.Midi, Card6850.MIDI).  Historical residual classes here — bank-byte SUPER
  relocations, multi-object sizing drift, SCSIHD include-path loss,
  RAM5/AppleDisk/SCC length drift — are closed and guarded by this harness plus
  work/gate.py.
"""
import sys, os
from _common import (
    byte_match,
    ensure_repo_on_path,
    first_existing_path,
    gsos_incs,
    gsos_source_root,
    mismatch_offsets,
    prefixed_file_candidates,
    suffixed_file_candidates,
    work_abs,
)
ensure_repo_on_path()
from gsasm import asm, omf, linkiigs
from gsasm.expressload import de_express

SRC   = gsos_source_root()
GSOS  = os.path.join(SRC, 'GS.OS')
CMN   = os.path.join(GSOS, 'Common')
DBIN  = 'ref/GSOS_6/driver_bin'

# For drivers whose golden binary was never cadius-extracted into DBIN, read the
# shipping fork straight out of the System 6.0.1 disk image with a2til (NO
# cadius).  name -> (2mg filename under DISK_DIR, ProDOS path of the driver).
A2TIL_ROOT = os.path.expanduser('~/src/a2til')
DISK_DIR = 'ref/GSOS_6/System601_disks/System 6.0.1'
DRIVER_DISK = {
    'A2.RAMCard':    ('Disk 3 of 7 SystemTools1.2mg',
                      '/SystemTools1/System/Drivers/A2.RAMCard'),
    'Modem':         ('Disk 3 of 7 SystemTools1.2mg',
                      '/SystemTools1/System/Drivers/Modem'),
    'Parallel.Card': ('Disk 3 of 7 SystemTools1.2mg',
                      '/SystemTools1/System/Drivers/Parallel.Card'),
    'Printer':       ('Disk 3 of 7 SystemTools1.2mg',
                      '/SystemTools1/System/Drivers/Printer'),
    'AppleTalk':     ('Disk 4 of 7 SystemTools2.2mg',
                      '/SystemTools2/System/Drivers/AppleTalk'),
    'LaserWriter':   ('Disk 4 of 7 SystemTools2.2mg',
                      '/SystemTools2/System/Drivers/LaserWriter'),
    'Apple.Midi':    ('Disk 3 of 7 SystemTools1.2mg',
                      '/SystemTools1/System/Drivers/Apple.Midi'),
    'Card6850.MIDI': ('Disk 3 of 7 SystemTools1.2mg',
                      '/SystemTools1/System/Drivers/Card6850.MIDI'),
    'ImageWriter':    ('Disk 3 of 7 SystemTools1.2mg',
                       '/SystemTools1/System/Drivers/ImageWriter'),
    'ImageWriter.LQ': ('Disk 3 of 7 SystemTools1.2mg',
                       '/SystemTools1/System/Drivers/ImageWriter.LQ'),
    'StyleWriter':    ('Disk 3 of 7 SystemTools1.2mg',
                       '/SystemTools1/System/Drivers/StyleWriter'),
}
_DISK_RAW_CACHE: dict[str, bytes] = {}


def _extract_from_disk(name: str) -> bytes | None:
    """Read a driver's shipping data fork from its 2mg image via a2til."""
    disk = DRIVER_DISK.get(name)
    if disk is None:
        return None
    if name in _DISK_RAW_CACHE:
        return _DISK_RAW_CACHE[name]
    if A2TIL_ROOT not in sys.path:
        sys.path.insert(0, A2TIL_ROOT)
    from a2til.prodos import Volume
    disk_file, path = disk
    with open(os.path.join(DISK_DIR, disk_file), 'rb') as f:
        vol = Volume(f.read())
    raw = vol.read_file(path, fork='data')
    _DISK_RAW_CACHE[name] = raw
    return raw


def _golden_raw(name: str) -> bytes | None:
    """Raw shipping OMF bytes: a cadius-extracted DBIN file if present, else the
    fork read directly from the disk image (a2til)."""
    cand = first_existing_path(_golden_candidates(name))
    if cand:
        with open(cand, 'rb') as f:
            return f.read()
    return _extract_from_disk(name)

# Include path: Common first (has common.equ.src / hw.equ.src / driver.equ.src),
# then every GS.OS subdir (so per-driver equate files are reachable).
INCS = gsos_incs(work_abs('includes'))

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
_SCSI_DRV_DIR = 'GS.OS/Drivers/SCSI.Drivers'

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
_SCSI_MGR_DIR = 'GS.OS/SupervisoryDrivers/SCSI.Manager(1meg)'

# Driver shipping-name -> (source-subdir, [source-files], {defines})
# source-subdir is relative to the IIGS.601.SRC root (SRC): GS.OS/… drivers live
# under GS.OS, the shipped PrinterDrivers/Midi drivers under GSToolbox/….
# Per GS.OS/MakeFiles/make.* and GSToolbox/build.tools — transcribed exactly.
DRIVERMAP = {
    'AppleDisk3.5': (
        'GS.OS/Drivers/AppleDisk3.5',
        ['AD3.5.src'],
        {},
    ),
    'AppleDisk5.25': (
        'GS.OS/Drivers/AppleDisk5.25',
        ['AppleDisk5.25.src'],
        {},
    ),
    'Console.Driver': (
        'GS.OS/Drivers/Console.Driver',
        ['Console.aii', 'New.DRI.Patch'],
        {'Library': 0},
    ),
    'UniDisk3.5': (
        'GS.OS/Drivers/UniDisk3.5',
        ['UniDisk3.5.src'],
        {},
    ),
    'RAM5': (
        'GS.OS/Drivers/RAM5',
        ['RAM5.aii'],
        {},
    ),
    'ATalk': (
        'GS.OS/Drivers/ATalk',
        ['Main.aii', 'rpm.aii', 'AppleTalk.aii', 'Others.aii'],
        {},
    ),
    # A2.RAMCard is the shipped name for the Slinky (RAM-card/RamFactor) driver
    # on SystemTools1 — source GS.OS/Drivers/Slinky/slinky.aii.
    'A2.RAMCard': (
        'GS.OS/Drivers/Slinky',
        ['slinky.aii'],
        {},
    ),
    # PrinterDrivers (GSToolbox/build.tools 'BuildProgram <ship-name>'):
    #   Modem/GraphiCard/Printer/AppleTalk each link the driver body + the
    #   shared dialogdata.asm (setup-dialog resources); special.macros is
    #   picked up from the driver's own dir (first on the include path).
    'Modem': (
        'GSToolbox/PrinterDrivers/Modem',
        ['modem.asm', 'dialogdata.asm'],
        {},
    ),
    # ImageWriter / ImageWriter.LQ: flat multi-object link (each makefile's OBJ=
    # order); byte-exact once BUG-A (spaced-comma dc.b lists — imager.aii
    # intl_tbl) and BUG-C (@-scope resets at record fields — dialogdata.aii)
    # landed.  Same 8-object shape; ImageWriter.LQ is the LaserQuality sibling.
    'ImageWriter': (
        'GSToolbox/PrinterDrivers/New.IW',
        ['entry.aii', 'printloop.aii', 'metrics.aii', 'dialog.aii',
         'dialogdata.aii', 'spool.aii', 'imager.aii', 'imagerdata.aii'],
        {},
    ),
    'ImageWriter.LQ': (
        'GSToolbox/PrinterDrivers/LQ',
        ['entry.aii', 'printloop.aii', 'metrics.aii', 'dialog.aii',
         'dialogdata.aii', 'spool.aii', 'imager.aii', 'imagerdata.aii'],
        {},
    ),
    # StyleWriter (Tabasco): 9-object link. Byte-exact once BUG-C (@-scope in
    # record) and BUG-D (EQU *±const relocation) land.
    'StyleWriter': (
        'GSToolbox/PrinterDrivers/Tabasco',
        ['entry.a', 'printloop.a', 'patchprocs.a', 'metrics.a', 'dialog.a',
         'dialogdata.a', 'spool.a', 'imager.a', 'communications.a'],
        {},
    ),
    'Parallel.Card': (
        'GSToolbox/PrinterDrivers/GraphiCard',
        ['graphicard.asm', 'dialogdata.asm'],
        {},
    ),
    'Printer': (
        'GSToolbox/PrinterDrivers/Printer',
        ['printer.asm', 'dialogdata.asm'],
        {},
    ),
    # AppleTalk here is the PRINTER driver (Disk 4 / SystemTools2), NOT the
    # GS.OS AppleTalk network driver mapped above as 'ATalk'.
    'AppleTalk': (
        'GSToolbox/PrinterDrivers/AppleTalk',
        ['appletalk.asm', 'dialogdata.asm'],
        {},
    ),
    # LaserWriter is a MULTI-SEGMENT printer driver (GSToolbox/PrinterDrivers/LW/
    # makefile): `-lseg MAIN lw.asm+dialogdata.asm` (resident) plus
    # `-lseg:Dynamic PREPFILE prepfile.asm` (an on-demand KIND-0x8000 segment).
    # MAIN's far pointer into PREPFILE routes through a linker-generated 26-byte
    # ~JumpTable exactly like Tool016's dynamic Pics — so this takes the
    # jump-table-aware multi-segment link (dict spec below), NOT the flat driver
    # link.  de_express(gold) concatenates MAIN + ~JumpTable + PREPFILE in file
    # order, which is what the built image reproduces.  Byte-exact 36644/36644.
    'LaserWriter': {
        'subdir': 'GSToolbox/PrinterDrivers/LW',
        'jt_segments': [
            ('MAIN',     0x0000, ['lw.asm', 'dialogdata.asm']),
            ('PREPFILE', 0x8000, ['prepfile.asm']),
        ],
    },
    # MIDI drivers (GSToolbox/Midi/Drivers):
    'Apple.Midi': (
        'GSToolbox/Midi/Drivers/Apple.Midi',
        ['apple.midi.aii'],
        {},
    ),
    'Card6850.MIDI': (
        'GSToolbox/Midi/Drivers/Card6850.Midi',
        ['card6850.midi.aii'],
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
        'GS.OS/SupervisoryDrivers/SCCManager',
        ['Driver.aii'],
        {},
    ),
}


def _extract_img(result: bytes) -> bytes:
    """Extract the CONST/LCONST code image from a linked OMF result."""
    img = bytearray()
    for seg in omf.iter_segments(result):
        for r in seg['recs']:
            if r[1] in ('CONST', 'LCONST'):
                img += r[2]
    return bytes(img)


def _packaging(name: str) -> str:
    """Determine packaging type from the golden binary OMF header."""
    raw = _golden_raw(name)
    if raw:
        h = omf.parse_header(raw[:256])
        segname = h.get('SEGNAME', b'').rstrip(b'\x00')
        if segname == b'~ExpressLoad':
            return 'ExpressLoad'
        return 'plain-OMF'
    return 'unknown'


def _golden_candidates(name: str):
    """Return candidate paths for the golden binary (cadius appends #TTAAAA)."""
    # Drivers are type $BB; aux type varies per make.*
    # cadius preserves original filename + appends #TTAAAA
    yield from suffixed_file_candidates(
        DBIN, name,
        ('#BB0101', '#BB0104', '#BB0107', '#BB0108', '#BB010E',
         '#BB0110', '#BB013F', '#BB0140', '#BB0103', ''),
    )
    # Fallback: scan directory for any file starting with the name
    yield from prefixed_file_candidates(DBIN, name)


def golden(name: str) -> bytes | None:
    raw = _golden_raw(name)
    return de_express(raw) if raw else None


# Drivers that embed the original build timestamp via `dc.b '&Sysdate &SysTime'`
# — the &Sysdate/&SysTime builtins must reproduce the captured build time for a
# byte-exact match (same mechanism kernelcheck uses for GS.OS's 06-May-93 build).
# The value is a fact of the shipping binary, extracted from the golden image.
DRIVER_BUILD_TIME = {
    'RAM5': ('06-May-93', '16:11:47'),
}


def link_driver(subdir, sources, defines, build_time=None):
    """Assemble and link one driver.  Returns the code image bytes.

    subdir is relative to the IIGS.601.SRC root (SRC), so both the GS.OS
    drivers (GS.OS/Drivers/…, GS.OS/SupervisoryDrivers/…) and the shipped
    GSToolbox printer/MIDI drivers (GSToolbox/…) are reachable.
    """
    drv_dir = f'{SRC}/{subdir}'
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


def _link_jt_driver(spec):
    """Jump-table-aware multi-segment link of a driver (LaserWriter), returning
    the flat CONST/LCONST image de_express(gold) compares against.

    Reuses toolcheck's ``_link_jt_tool`` (its ``subdir`` is relative to the
    GSToolbox root, matching toolcheck.TB) to place the load segments, route
    each MAIN->PREPFILE far pointer through the generated ~JumpTable, and build
    every segment's relocated image.  The images are then concatenated in FILE
    segment order (non-dynamic block, ~JumpTable, dynamic block — the order
    de_express walks the shipping file), with the generated ~JumpTable inserted
    at its own segnum slot."""
    import toolcheck as _tc
    subdir = spec['subdir']
    if subdir.startswith('GSToolbox/'):
        subdir = subdir[len('GSToolbox/'):]
    segs = spec['jt_segments']
    images, jt_entries, jt_segnum, segnum = _tc._link_jt_tool(subdir, segs)
    by_segnum = {segnum[name]: images[name] for name, _k, _s in segs}
    if jt_entries:
        by_segnum[jt_segnum] = _tc.encode_jumptable(jt_entries)
    out = bytearray()
    for sn in sorted(by_segnum):
        out += by_segnum[sn]
    return bytes(out)


def check(name: str, verbose: bool = False):
    if name not in DRIVERMAP:
        return name, None, None, f'not in DRIVERMAP'
    entry = DRIVERMAP[name]
    if isinstance(entry, dict):
        subdir = entry['subdir']
        g = golden(name)
        if g is None:
            return name, subdir, None, 'no golden binary (DBIN file or disk image)'
        try:
            mine = _link_jt_driver(entry)
        except Exception as e:
            return name, subdir, None, f'{type(e).__name__}: {e}'
        m, n = byte_match(mine, g)
        pct = (100 * m // n) if n else 0
        if verbose:
            print(f'{name} ({subdir}): gsasm={len(mine)} gold={len(g)} '
                  f'match {m}/{n} ({pct}%)  pkg=multiseg+jt')
            diffs = mismatch_offsets(mine, g)
            if diffs:
                pos = diffs[0]
                print(f'  first diff @ {pos:#06x}: gsasm={mine[pos]:02x} gold={g[pos]:02x}')
                print(f'    gsasm {bytes(mine[max(0, pos - 4):pos + 8]).hex()}')
                print(f'    gold  {g[max(0, pos - 4):pos + 8].hex()}')
            else:
                print('  BYTE-EXACT')
        return name, subdir, (pct, m, n, len(mine), len(g)), None
    subdir, sources, defines = entry
    g = golden(name)
    if g is None:
        return name, subdir, None, 'no golden binary (DBIN file or disk image)'
    try:
        mine = link_driver(subdir, sources, defines,
                           DRIVER_BUILD_TIME.get(name))
    except Exception as e:
        import traceback
        return name, subdir, None, f'{type(e).__name__}: {e}'
    m, n = byte_match(mine, g)
    pct = (100 * m // n) if n else 0
    pkg = _packaging(name)
    if verbose:
        print(f'{name} ({subdir}): gsasm={len(mine)} gold={len(g)} '
              f'match {m}/{n} ({pct}%)  pkg={pkg}')
        diffs = mismatch_offsets(mine, g)
        if diffs:
            pos = diffs[0]
            a, b = mine[pos], g[pos]
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
    print('Slinky ships as A2.RAMCard on SystemTools1 (now wired, byte-exact);'
          ' ETalk/ATBoot/ATRam/ATRom not on any 6.0.1 disk or skipped.')


if __name__ == '__main__':
    main()
