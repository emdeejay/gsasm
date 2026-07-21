#!/usr/bin/env python3
"""basiccheck.py — rebuild BASIC.System (the ProDOS-8 command interpreter)
byte-exact from clean-room source.

BASIC.System is the ProDOS-8 command interpreter (the ``]`` prompt: PREFIX,
CATALOG, BLOAD, RUN, ``-STARTUP`` chaining, ...).  It is PURE 6502/65C02
assembly — the Applesoft BASIC *language* itself lives in the //e ROM, so the
old "ProDOS-8 / Applesoft, out of scope" classification was wrong: this is an
assembler oracle exactly like P8, and it builds byte-exact through the existing
gsasm + makebin machinery.

Source (ref/GSOS_6/IIGS.601.SRC/BASIC.SYSTEM), per its Makefile:

    ASMIIGS Loader  -o Loader.obj
    ASMIIGS Main    -o Main.obj
    ASMIIGS Globals -o Globals.obj
    LinkIIGS Loader.obj -org $2000 Main.obj Globals.obj -o BASIC.SYSTEM
    MakeBinIIGS BASIC.SYSTEM -org $2000

Each of the three modules is a single PROC; each ``INCLUDE 'EQUATES'`` (a shared
equate file, not a linked object).  LOADER links at $2000, but MAIN and GLOBALS
carry ``temporg`` origins ($9A00 and $BE00) — they are the code/global-page that
gets *copied* to the MLI region at run time, so their internal and exported
labels are absolute at the temporg address while their bytes are stored
sequentially in the file.  That is exactly the ``makebin_segments`` model (P8's
recipe, work/diskbuilders/p8_driver.py): base each named segment at its own org
(LOADER=$2000, MAIN/GLOBALS=their temporg) under one shared symbol table so the
cross-object IMPORTs (LOADER imports VECTOUT/VECTIN/... from GLOBALS; MAIN
imports the global-page cells) resolve to the temporg-absolute addresses, then
concatenate the segment bodies in link order.

Result: BYTE-EXACT 10,240 bytes, verified against BOTH shipping copies —
/System.Disk/BASIC.System (Disk 2) and /SystemTools1/BASIC.System (Disk 3),
which are byte-identical (type=$FF SYS, aux=$2000).

    python3 work/basiccheck.py [--diff]
"""
import sys, os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import ensure_repo_on_path
ensure_repo_on_path()

from gsasm import asm as _asm
from gsasm import omf as _omf
from gsasm import makebin as _makebin

_SRCDIR = os.path.join(
    'ref', 'GSOS_6', 'IIGS.601.SRC', 'BASIC.SYSTEM')
_INCS = [_SRCDIR]

# Link order (Makefile: Loader.obj -org $2000 Main.obj Globals.obj) and the
# origin each module's segment is based at: LOADER at the link -org $2000, MAIN
# and GLOBALS at their source ``temporg`` (read from the assembled module, not
# hard-coded, so a source edit can't silently desync this).
_LINK_ORDER = ['LOADER', 'MAIN', 'GLBSTUFF']
_LOADER_ORG = 0x2000

_MODULES = ['LOADER', 'MAIN', 'GLOBALS']       # source filenames
BASIC_SIZE = 10240

# In-tree golden (identical to both on-disk copies) — a convenient oracle for
# the standalone run; diskcheck compares against the real disk bytes.
_GOLD = os.path.join(_SRCDIR, 'BASIC.SYSTEM')


class BasicAssemblyError(Exception):
    """A BASIC.System module reached an assembler error — the layout would be
    wrong, so we abort rather than emit a plausible-looking image."""


def _assemble(name):
    a = _asm.assemble(os.path.join(_SRCDIR, name), _INCS)
    if a.errors:
        detail = '\n    '.join(a.errors[:5])
        raise BasicAssemblyError(
            f'{name}: {len(a.errors)} assembler error(s):\n    {detail}')
    return _omf.emit(a), a


def build_basic_system() -> bytes:
    """Build the 10,240-byte BASIC.System, byte-exact against the shipping
    copies.  Raises BasicAssemblyError on any assembler error and ValueError if
    the packaged result is not exactly BASIC_SIZE bytes."""
    objs, asms = [], []
    for name in _MODULES:
        obj, a = _assemble(name)
        objs.append(obj)
        asms.append(a)

    # LOADER has no temporg (links at $2000); MAIN/GLOBALS export at their
    # temporg origin.  Derive the org per segment from the assembled module.
    orgs = {'LOADER': _LOADER_ORG}
    for name, seg_name, a in zip(_MODULES, _LINK_ORDER, asms):
        if seg_name == 'LOADER':
            continue
        temporg = a.segs[0].temporg if a.segs else None
        if temporg is None:
            raise BasicAssemblyError(f'{name}: expected a temporg origin')
        orgs[seg_name] = temporg

    combined = b''.join(objs)
    bins = _makebin.makebin_segments(combined, orgs=orgs)

    missing = [s for s in _LINK_ORDER if s not in bins]
    if missing:
        raise BasicAssemblyError(
            f'segments missing from link: {missing}; have {sorted(bins)}')

    image = b''.join(bins[s] for s in _LINK_ORDER)
    if len(image) != BASIC_SIZE:
        raise ValueError(
            f'BASIC.System build produced {len(image)} bytes, '
            f'expected {BASIC_SIZE}')
    return image


# Both shipping copies (byte-identical) — the metric checks the build against
# each, so a partial/one-disk regression is caught.
_DISKS = 'ref/GSOS_6/System601_disks/System 6.0.1'
_COPIES = [
    (f'{_DISKS}/Disk 2 of 7 System Disk.2mg', '/System.Disk/BASIC.System'),
    (f'{_DISKS}/Disk 3 of 7 SystemTools1.2mg', '/SystemTools1/BASIC.System'),
]


def _disk_copies():
    """Read the on-disk BASIC.System from both shipping disks via a2til.
    Returns [(label, bytes), ...]; skips a disk that is not present."""
    from _common import ROOT
    for p in (os.environ.get('A2TIL_PATH'),
              os.path.join(os.path.dirname(ROOT), 'a2til'),
              os.path.expanduser('~/src/a2til')):
        if p and os.path.isdir(os.path.join(p, 'a2til')):
            sys.path.insert(0, p)
            break
    from a2til.prodos import Volume
    out = []
    for disk, path in _COPIES:
        if not os.path.exists(disk):
            continue
        vol = Volume(bytearray(open(disk, 'rb').read()))
        out.append((path, vol.read_file(path)))
    return out


def main():
    show_diff = '--diff' in sys.argv[1:]
    try:
        built = build_basic_system()
    except Exception as e:                                   # noqa: BLE001
        print(f'FAIL build: {type(e).__name__}: {e}')
        print('\nbasiccheck: BASIC_SYSTEM_BYTES_EXACT 0/2')
        return 1

    copies = _disk_copies()
    if not copies:                       # fall back to the in-tree golden
        if os.path.exists(_GOLD):
            copies = [(_GOLD, open(_GOLD, 'rb').read())]
    good = 0
    total = len(copies) if copies else 0
    for label, gold in copies:
        if built == gold:
            print(f'PASS {label} {len(gold)} bytes byte-exact')
            good += 1
        else:
            n = min(len(built), len(gold))
            d = next((i for i in range(n) if built[i] != gold[i]), n)
            print(f'FAIL {label} built={len(built)} gold={len(gold)} '
                  f'first diff at {d:#x}')
            if show_diff and d < n:
                print(f'    built {built[max(0,d-4):d+8].hex()}')
                print(f'    gold  {gold[max(0,d-4):d+8].hex()}')

    print(f'\nbasiccheck: BASIC_SYSTEM_BYTES_EXACT {good}/{total}')
    return 0 if (total and good == total) else 1


if __name__ == '__main__':
    sys.exit(main())
