#!/usr/bin/env python3
"""appdatacheck.py — rebuild four A.U.G data forks byte-exact from source.

These four shipping files are pure assembler oracles (no resource fork we
target): each is a 65816 DATA fork whose whole content is assembled+linked
from the archived `.aii` sources through the EXISTING gsasm machinery — the
same expressload()/linkiigs.link() paths drivercheck/easymountcheck/
mountimagecheck already exercise.  No assembler or linker change is needed;
this harness only WIRES the builds and gates them.

    CDRemote    — CD Remote NDA ($B8), Disk 3 SystemTools1, 15,745-byte
                  ExpressLoad'd data fork.  Three objects merged to a single
                  'main' segment (cdremote.make: cdremote.obj draw.obj
                  gsosdriver.obj, in that link order; no -d defines).
                  spdriver.aii is dead source in the tree — the makefile does
                  NOT link it, and adding it overshoots — so it is excluded.
    Pioneer2000 — Media.Control driver ($BB), Disk 4 SystemTools2,
                  3,830-byte single-object ExpressLoad (P2000.aii).
    EasyAccess  — Easy Access NDA/INIT ($B6), Disk 4 SystemTools2,
                  3,191-byte single-object ExpressLoad (EasyAccess.aii).
    Pioneer4200 — Media.Control driver ($BB), Disk 4 SystemTools2,
                  6,253-byte PLAIN super:True LOAD file (P4200.aii).  Despite
                  P4200.make's `linkiigs -x`, the SHIPPED fork is a plain
                  (non-ExpressLoad) load file: leading segment KIND $4000, no
                  ~ExpressLoad directory.  Built via linkiigs.link(...,
                  opts={'super':True,'segname':b'main','loadname':nulls}) —
                  the real LinkIIGS merges P4200.aii's 32 segments into one
                  output segment named 'main' with an empty (all-NUL) LOADNAME,
                  exactly what expressload() names its merged 'main' segment.

Include path (per target):  [source_dir, FINDER_DIR, INC_E16] — identical in
spirit to easymountcheck.ASM_INCS.  FINDER_DIR is load-bearing: CDRemote /
draw / GSOSDriver / P2000 / P4200 all `include 'all.macros'`, and the copy in
work/rincludes/AIIGSIncludes/all.macros was line-ending/charset mangled at
recovery time — its `IF &addr≠'' THEN` guards were corrupted to `!=`, which
gsasm's expression lexer (asm.py maps `≠`→`<>`, `≤`,`≥`; it has no `!=`) does
NOT read as a relational operator, so those addressing macros expand to the
wrong (shorter) code.  ref/.../A.U.G/Finder/all.macros is the authentic Apple
original with the MacRoman `≠` (0xAD) intact, so it takes precedence.
EasyAccess includes the M16.*/E16.* headers directly (never all.macros) and is
byte-exact regardless, but shares the same include order for uniformity.

Inputs (Apple material, ref/ + work/rincludes/ gitignored — same footing as
easymountcheck/drivercheck): the archived A.U.G sources and the four golden
data forks read straight off the System 6.0.1 Disk 3/Disk 4 images.

    python3 work/appdatacheck.py            # summary over all four targets
    python3 work/appdatacheck.py CDRemote   # one target with first-diff detail
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import ensure_repo_on_path, first_diff, work_abs
ensure_repo_on_path()

import diskcheck as dc                        # sets up a2til on sys.path
from a2til.prodos import Volume               # noqa: E402
from gsasm import asm, omf, linkiigs          # noqa: E402
from gsasm.expressload import expressload     # noqa: E402

SRC = os.path.join(dc.ROOT, 'ref', 'GSOS_6', 'IIGS.601.SRC')
FINDER_DIR = os.path.join(SRC, 'A.U.G', 'Finder')   # authentic all.macros (≠)
INC_E16 = work_abs('rincludes', 'AIIGSIncludes')    # M16.*/E16.* headers
DISKS = os.path.join(dc.ROOT, dc.DISKS)
D3 = os.path.join(DISKS, 'Disk 3 of 7 SystemTools1.2mg')
D4 = os.path.join(DISKS, 'Disk 4 of 7 SystemTools2.2mg')

# A plain (non-ExpressLoad) merged load file, as the real LinkIIGS emits it:
# every input segment folded into one output segment named 'main' with an
# all-NUL LOADNAME, low-word relocs packed into SUPER records.
PLAIN_OPTS = {'super': True, 'segname': b'main', 'loadname': b'\x00' * 10}

# name -> (disk image, on-disk path, source subdir, [modules], build_kind)
#   build_kind: 'expressload' -> expressload(objects)
#               'plainload'   -> linkiigs.link(objects, opts=PLAIN_OPTS)
# Module order is the makefile's link order; no target takes -d defines.
APPMAP = {
    'CDRemote': (
        D3, '/SystemTools1/System/Desk.Accs/CDRemote',
        'A.U.G/CDRemote',
        ['CDRemote.aii', 'draw.aii', 'GSOSDriver.aii'],
        'expressload'),
    'Pioneer2000': (
        D4, '/SystemTools2/System/Drivers/Media.Control/Pioneer2000',
        'A.U.G/MediaCtl/Pioneer2000',
        ['P2000.aii'],
        'expressload'),
    'EasyAccess': (
        D4, '/SystemTools2/System/System.Setup/EasyAccess',
        'A.U.G/EasyAccess',
        ['EasyAccess.aii'],
        'expressload'),
    'Pioneer4200': (
        D4, '/SystemTools2/System/Drivers/Media.Control/Pioneer4200',
        'A.U.G/MediaCtl/P4200',
        ['P4200.aii'],
        'plainload'),
}

_VOL_CACHE = {}


def _volume(disk):
    if disk not in _VOL_CACHE:
        _VOL_CACHE[disk] = Volume(bytearray(open(disk, 'rb').read()))
    return _VOL_CACHE[disk]


def golden(name) -> bytes:
    disk, path, *_ = APPMAP[name]
    return _volume(disk).read_file(path, fork='data')


def build_app_data(name) -> bytes:
    """Assemble+link one target's data fork; returns whatever gsasm produces
    (callers compare against the golden on-disk fork)."""
    _disk, _path, subdir, modules, kind = APPMAP[name]
    src_dir = os.path.join(SRC, subdir)
    incs = [src_dir, FINDER_DIR, INC_E16]
    objects = []
    for m in modules:
        a = asm.assemble(os.path.join(src_dir, m), incs)
        if a.errors:
            raise RuntimeError(f'{name}:{m}: {len(a.errors)} assembly errors; '
                               f'first: {a.errors[0]}')
        objects.append((omf.emit(a), a))
    if kind == 'expressload':
        return expressload(objects)
    if kind == 'plainload':
        return linkiigs.link(objects, opts=PLAIN_OPTS)
    raise ValueError(f'{name}: unknown build_kind {kind!r}')


def check(name, verbose=False):
    gold = golden(name)
    try:
        built = build_app_data(name)
    except Exception as e:                                   # noqa: BLE001
        return name, None, f'{type(e).__name__}: {e}'
    ok = built == gold
    if verbose and not ok:
        d = first_diff(built, gold)
        print(f'  first diff at {d:#x} '
              f'(built {len(built)}B vs gold {len(gold)}B)')
        print(f'    gold  {gold[max(0, d - 8):d + 24].hex()}')
        print(f'    built {built[max(0, d - 8):d + 24].hex()}')
    return name, (len(built), len(gold), ok), None


def main():
    if len(sys.argv) > 1:
        name = sys.argv[1]
        if name not in APPMAP:
            print(f'unknown target {name!r}; mapped: {", ".join(APPMAP)}')
            return
        _n, res, err = check(name, verbose=True)
        if err:
            print(f'{name}: {err}')
        else:
            b, g, ok = res
            print(f'{name}: built={b} gold={g} '
                  f'{"BYTE-EXACT" if ok else "DIFFERS"}')
        return
    good = tot = 0
    good_bytes = bad_bytes = 0
    for name in APPMAP:
        _n, res, err = check(name)
        tot += 1
        if err:
            print(f'FAIL {name:12} {err}')
            continue
        b, g, ok = res
        if ok:
            good += 1
            good_bytes += g
            print(f'PASS {name:12} {g} bytes byte-exact (data fork)')
        else:
            bad_bytes += g
            print(f'FAIL {name:12} built={b} gold={g} differs '
                  f'(first diff @ {first_diff(build_app_data(name), golden(name))})')
    print(f'\nappdatacheck: {good}/{tot} data forks byte-exact '
          f'APP_DATA_BYTES_EXACT {good_bytes}/{good_bytes + bad_bytes}')


if __name__ == '__main__':
    main()
