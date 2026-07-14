#!/usr/bin/env python3
"""diskcheck.py — M8: reconstruct the shipping GS/OS 6.0.1 disk images byte-exact.

The disk-level analogue of work/buildrom.py. A shipping .2mg is a ProDOS volume;
most of the System Disk is ASM we build from clean-room source. This harness
reconstructs the image: every file with a wired builder is BUILT from source and
overlaid into its ORIGINAL data blocks; the rest is kept from the original — the
ROM pattern ("N% built, byte-identical via substitution"), one level up.

The ProDOS/2IMG layer is the a2til toolkit (read/write, extended/forked, sparse,
2IMG; byte-cross-checked vs cadius) — we do NOT re-implement the filesystem.

DISCIPLINE (per the M8 second-chair review — the physical image match alone is NOT
a builder-correctness gate; a no-builder run is trivially 100%):
  * ownership is an EXPLICIT manifest, not a file-type heuristic; an on-disk file
    absent from the manifest FAILS the inventory.
  * a wired builder must pass a 7-step contract (build_disk_file -> exact bytes;
    len == data-fork EOF; sparse logical blocks are zero; logical bytes ==
    read_file BEFORE overlay; overlay data blocks only; image stays byte-identical;
    coverage does not drop).
  * metrics are fork-aware and reported as THREE numbers, not one.

    python3 work/diskcheck.py                 # inventory + round-trip
    python3 work/diskcheck.py -v              # per-file manifest listing
    python3 work/diskcheck.py --selftest      # prove overlay byte-cleanliness
    python3 work/diskcheck.py --min-built N   # CI: fail if <N built-bytes covered
"""
import sys, os

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))          # gsasm/


def _find_a2til():
    """Locate the a2til toolkit without a hard-coded absolute path (P3)."""
    for p in (os.environ.get('A2TIL_PATH'),
              os.path.join(os.path.dirname(os.path.dirname(HERE)), 'a2til'),  # sibling
              os.path.expanduser('~/src/a2til')):
        if p and os.path.isdir(os.path.join(p, 'a2til')):
            return p
    return None


_A2TIL = _find_a2til()
if not _A2TIL:
    sys.exit("diskcheck: a2til not found — set A2TIL_PATH, or place it as a sibling "
             "of gsasm (…/a2til/a2til/prodos.py). See docs/design/M8_DISK_IMAGES.md.")
sys.path.insert(0, _A2TIL)
from a2til.prodos import Volume, ST_EXTENDED        # noqa: E402

DISKS = 'ref/GSOS_6/System601_disks/System 6.0.1'
SYSTEM_DISK = f'{DISKS}/Disk 2 of 7 System Disk.2mg'

# ---------------------------------------------------------------------------
# Ownership — an EXPLICIT per-path manifest (P1). Owners:
#   BUILD       clean-room ASM we build from source (data fork)
#   REZ         has a resource fork -> needs Rez (M7); substitute whole for now
#   SUBSTITUTE  data/Pascal/GUI — kept from the original image
#   OOS         out of scope (e.g. ProDOS-8 Applesoft BASIC.System)
# A file whose name is `Finder.Data` is SUBSTITUTE by rule. Any other on-disk
# file not listed here FAILS the inventory (so new files can't slip through).
# ---------------------------------------------------------------------------
BUILD, REZ, SUBSTITUTE, OOS = 'build', 'rez', 'substitute', 'out-of-scope'
V = '/System.Disk'
MANIFEST = {
    f'{V}/ProDOS': BUILD, f'{V}/System/P8': BUILD,
    f'{V}/System/GS.OS': BUILD, f'{V}/System/Start.GS.OS': BUILD,
    f'{V}/System/GS.OS.Dev': BUILD, f'{V}/System/Error.Msg': BUILD,
    f'{V}/System/System.Setup/Resource.Mgr': BUILD,
    f'{V}/System/System.Setup/Tool.Setup': BUILD,
    f'{V}/System/System.Setup/TS2': BUILD, f'{V}/System/System.Setup/TS3': BUILD,
    f'{V}/System/FSTs/Char.FST': BUILD, f'{V}/System/FSTs/Pro.FST': BUILD,
    f'{V}/System/Drivers/AppleDisk3.5': BUILD,
    f'{V}/System/Drivers/AppleDisk5.25': BUILD,
    f'{V}/System/Drivers/Console.Driver': BUILD,
    f'{V}/System/CDevs/CDev.Data': SUBSTITUTE,   # binary CDEV config data, no ASM source
    **{f'{V}/System/Tools/Tool{n}': BUILD for n in
       ('014', '015', '016', '018', '019', '020', '021', '022', '023',
        '025', '027', '028', '034')},
    # resource-forked -> Rez (M7); the data fork may be ASM but the fork isn't
    f'{V}/System/Start': REZ, f'{V}/System/System.Setup/Sys.Resources': REZ,
    f'{V}/System/System.Setup/EasyMount': REZ,
    f'{V}/System/Desk.Accs/ControlPanel': REZ,
    f'{V}/System/CDevs/General': REZ, f'{V}/System/CDevs/Printer': REZ,
    f'{V}/System/CDevs/RAM': REZ, f'{V}/System/CDevs/Slots': REZ,
    f'{V}/System/CDevs/Time': REZ,
    # data / config / fonts / icons — substitute
    f'{V}/System/Fonts/Font.Lists': SUBSTITUTE, f'{V}/System/Fonts/Times.10': SUBSTITUTE,
    f'{V}/Icons/FType.Apple': SUBSTITUTE,
    f'{V}/BASIC.System': OOS,
}


class DiskFile:
    __slots__ = ('path', 'type', 'aux', 'has_rsrc', 'data_eof', 'rsrc_eof',
                 'data_blocks', 'rsrc_blocks', 'owner')

    def __init__(self, path, entry, vol):
        self.path = path
        self.type = entry.type
        self.aux = entry.aux_type
        self.has_rsrc = (entry.storage_type == ST_EXTENDED)
        st, key, self.data_eof = vol._resolve_fork(entry, 'data')
        self.data_blocks = vol._blocks_for(st, key, self.data_eof)   # 0 = sparse
        if self.has_rsrc:
            rst, rkey, self.rsrc_eof = vol._resolve_fork(entry, 'rsrc')
            self.rsrc_blocks = vol._blocks_for(rst, rkey, self.rsrc_eof)
        else:
            self.rsrc_eof = 0
            self.rsrc_blocks = []
        self.owner = owner_for(path)

    @property
    def sparse_idx(self):
        return {i for i, b in enumerate(self.data_blocks) if b == 0}


def owner_for(path):
    if path.rsplit('/', 1)[-1] == 'Finder.Data':
        return SUBSTITUTE
    return MANIFEST.get(path)          # None -> inventory failure


def _walk(vol, path):
    for entry in vol.scandir(path):
        child = path.rstrip('/') + '/' + entry.name
        if entry.is_dir:
            yield from _walk(vol, child)
        else:
            yield child, entry


def catalog_disk(vol):
    files = [DiskFile(p, e, vol) for p, e in _walk(vol, '/' + vol.name)]
    unlisted = [f.path for f in files if f.owner is None]
    if unlisted:
        raise SystemExit("diskcheck: on-disk files not in the manifest "
                         "(add them with an owner):\n  " + "\n  ".join(unlisted))
    return files


def overlay(vol, f, content):
    """Overlay `content` into `f`'s ORIGINAL data blocks (raw, byte-clean).

    Asserts the build fits AND that any sparse logical block is zero in `content`
    (P0: a nonzero sparse block would be silently dropped and mask a bad build)."""
    if len(content) != f.data_eof:
        raise ValueError(f'{f.path}: build {len(content)}B != data-fork EOF {f.data_eof}')
    for i, blk in enumerate(f.data_blocks):
        chunk = content[i * 512:(i + 1) * 512]
        if blk == 0:                                   # sparse (unallocated)
            if any(chunk):
                raise ValueError(f'{f.path}: nonzero data in sparse block {i}')
            continue
        vol._write_block(blk, chunk)


def overlay_rsrc(vol, f, content):
    """The RESOURCE-fork analogue of `overlay()` (M7 flip): a REZ-owned file
    like Sys.Resources has an EMPTY data fork, so a byte-exact build has to
    land in its resource fork's own original blocks instead. Same
    byte-cleanliness contract as `overlay()`, just against `f.rsrc_blocks`/
    `f.rsrc_eof` in place of `f.data_blocks`/`f.data_eof`."""
    if len(content) != f.rsrc_eof:
        raise ValueError(f'{f.path}: build {len(content)}B != rsrc-fork EOF {f.rsrc_eof}')
    for i, blk in enumerate(f.rsrc_blocks):
        chunk = content[i * 512:(i + 1) * 512]
        if blk == 0:                                   # sparse (unallocated)
            if any(chunk):
                raise ValueError(f'{f.path}: nonzero data in sparse rsrc block {i}')
            continue
        vol._write_block(blk, chunk)


# path -> callable() -> the FULL on-disk file bytes (ExpressLoad'd OMF / MakeBin
# output), NOT the de-ExpressLoad'd code image the *check.py harnesses compare.
# Wired as each file's full-file build path is confirmed and passes the contract.
def _build_prodos():
    import probootcheck                     # M3: MakeBin over Boot/ProBoot.src @ $2000
    return probootcheck.build_prodos()


SOURCE_BUILDERS = {
    f'{V}/ProDOS': _build_prodos,           # 1668/1668 exact — first disk-ready file
}
# Per-category builders live in the diskbuilders/ package (auto-discovered), one
# module per category, so they can be developed in parallel without colliding on
# this file. Each module exposes `builders(V) -> {disk_path: callable() -> bytes}`.
try:
    import diskbuilders
    SOURCE_BUILDERS.update(diskbuilders.load(V))
except Exception:                           # missing/partial package is non-fatal
    pass


# path -> callable() -> the FULL RESOURCE-FORK bytes (M7). A REZ-owned file's
# DATA fork is typically empty (e.g. Sys.Resources: 0-byte data fork, the
# whole shipping file is its 24,337-byte resource fork), so these builders
# are wired separately from SOURCE_BUILDERS and overlaid via overlay_rsrc()
# below rather than overlay(). Lazy import (like _build_prodos() above):
# work/rezbuildcheck.py -> work/rezcheck.py -> `import diskcheck as dc` would
# otherwise be a module-level import cycle; deferring the import to call
# time (inside check(), well after this module has finished executing its
# own top level) sidesteps it exactly like _build_prodos()'s lazy
# `import probootcheck` already does.
def _build_sysresources_rsrc():
    import rezbuildcheck                    # M7: Rez pipeline, see docs/design/rez.md
    return rezbuildcheck.build_sysresources_fork()


def _build_easymount_rsrc():
    import easymountcheck                   # M7 follow-on: EasyMount (see docs/design/rez.md)
    return easymountcheck.build_easymount_rsrc_fork()


REZ_BUILDERS = {
    f'{V}/System/System.Setup/Sys.Resources': _build_sysresources_rsrc,
    f'{V}/System/System.Setup/EasyMount': _build_easymount_rsrc,
}


# EasyMount is dual-fork: ALSO has a real (non-empty) data fork, wired
# separately here as a SOURCE_BUILDERS entry -- see the new REZ-owned
# SOURCE_BUILDERS branch in check() below. Lazy import for the same reason
# as _build_sysresources_rsrc()/_build_prodos() above (easymountcheck ->
# rezcheck -> `import diskcheck as dc` would otherwise be a module-load-time
# cycle). NOT byte-exact (see easymountcheck.py's module docstring for the
# two precisely diagnosed residuals, both in core asm/expressload files
# outside this packet's edit scope); build_and_overlay() already tolerates
# and reports a non-exact build without corrupting the image, so it is
# still wired rather than left as an implicit SUBSTITUTE.
def _build_easymount_data():
    import easymountcheck
    return easymountcheck.build_easymount_data_fork()


SOURCE_BUILDERS[f'{V}/System/System.Setup/EasyMount'] = _build_easymount_data


def build_and_overlay(vol, f):
    """The Phase-2 builder contract for one manifest BUILD file. Returns
    (built_ok, note)."""
    try:
        content = SOURCE_BUILDERS[f.path]()
    except Exception as e:                             # noqa: BLE001
        return False, f'builder raised {type(e).__name__}: {e}'
    if len(content) != f.data_eof:
        return False, f'len {len(content)} != EOF {f.data_eof}'
    original = vol.read_file(f.path)                    # logical compare (pre-overlay)
    if content != original:
        # Contract step 6 requires the overlaid image to stay byte-identical, so a
        # non-exact build is NOT overlaid (that would make the image worse than
        # substitution). It is reported as a residual worklist item instead.
        return False, f'logical differs at {_first_diff(content, original)}'
    overlay(vol, f, content)                            # only a byte-exact build
    return True, 'logical-exact'


def build_and_overlay_rsrc(vol, f):
    """The REZ-category analogue of `build_and_overlay()`: builds and
    overlays a RESOURCE fork instead of a data fork (see `REZ_BUILDERS`).
    Same contract otherwise: only a byte-exact build is overlaid."""
    try:
        content = REZ_BUILDERS[f.path]()
    except Exception as e:                             # noqa: BLE001
        return False, f'rez builder raised {type(e).__name__}: {e}'
    if len(content) != f.rsrc_eof:
        return False, f'len {len(content)} != rsrc EOF {f.rsrc_eof}'
    original = vol.read_file(f.path, fork='rsrc')       # logical compare (pre-overlay)
    if content != original:
        return False, f'logical (rsrc) differs at {_first_diff(content, original)}'
    overlay_rsrc(vol, f, content)                       # only a byte-exact build
    return True, 'logical-exact (rsrc)'


def _first_diff(a, b):
    n = min(len(a), len(b))
    for i in range(n):
        if a[i] != b[i]:
            return hex(i)
    return f'len {len(a)} vs {len(b)}'


def check(disk_path=SYSTEM_DISK, verbose=False, min_built=0):
    orig = open(disk_path, 'rb').read()
    buf = bytearray(orig)
    vol = Volume(buf)
    files = catalog_disk(vol)

    from collections import Counter
    own = Counter(f.owner for f in files)
    data_total = sum(f.data_eof for f in files)
    rsrc_total = sum(f.rsrc_eof for f in files)
    build_data = sum(f.data_eof for f in files if f.owner == BUILD)

    built_bytes = built_ok = built_logical = 0
    notes = []
    for f in files:
        if f.owner == BUILD and f.path in SOURCE_BUILDERS:
            ok, note = build_and_overlay(vol, f)
            built_ok += 1
            if ok:                                       # source-built AND byte-exact
                built_logical += 1
                built_bytes += f.data_eof
            else:
                notes.append(f'    {f.path}: {note}')
        if f.owner == REZ and f.path in REZ_BUILDERS:
            ok, note = build_and_overlay_rsrc(vol, f)
            built_ok += 1
            if ok:                                       # source-built AND byte-exact
                built_logical += 1
                built_bytes += f.rsrc_eof
            else:
                notes.append(f'    {f.path}: {note}')
        # A dual-fork REZ file (e.g. EasyMount: resource fork via Rez AND a
        # real 65816 data fork) can ALSO have a data-fork SOURCE_BUILDERS
        # entry -- independent of (not `elif`) the rsrc branch above, so
        # both forks of the same file are attempted. Additive: no BUILD- or
        # REZ-owned file loses coverage; this only adds a third case no
        # prior file could hit (a REZ file's path was never also a
        # SOURCE_BUILDERS key before).
        if f.owner == REZ and f.path in SOURCE_BUILDERS:
            ok, note = build_and_overlay(vol, f)
            built_ok += 1
            if ok:
                built_logical += 1
                built_bytes += f.data_eof
            else:
                notes.append(f'    {f.path}: {note}')

    recon = bytes(buf)
    n = min(len(recon), len(orig))
    match = sum(1 for i in range(n) if recon[i] == orig[i])

    n_wireable = (own[BUILD]
                  + sum(1 for f in files if f.owner == REZ and f.path in REZ_BUILDERS)
                  + sum(1 for f in files if f.owner == REZ and f.path in SOURCE_BUILDERS))
    print(f"{os.path.basename(disk_path)}: {vol.name}  {vol.total_blocks} blocks")
    print(f"  files: {len(files)}  |  build:{own[BUILD]} rez:{own[REZ]} "
          f"substitute:{own[SUBSTITUTE]} oos:{own[OOS]}")
    print(f"  logical bytes:  data-fork {data_total}  resource-fork {rsrc_total}")
    print(f"  source-buildable (BUILD data-fork): {build_data} of {data_total} "
          f"({100*build_data//data_total}%)")
    print(f"  builders wired: {built_ok}/{n_wireable}  "
          f"logical-exact: {built_logical}/{built_ok}  "
          f"built-bytes covered: {built_bytes}")
    print(f"  PHYSICAL image byte-match: {match}/{n} ({100*match//n}%)")
    if notes:
        print("  builder logical mismatches (physical match may still be 100%):")
        print("\n".join(notes))
    if verbose:
        for f in sorted(files, key=lambda x: (x.owner, x.path)):
            w = ' [built]' if (f.path in SOURCE_BUILDERS or f.path in REZ_BUILDERS) else ''
            print(f"    {f.owner:10} ${f.type:02X} d={f.data_eof:>7} "
                  f"r={f.rsrc_eof:>6} {'+rsrc' if f.has_rsrc else '     '} "
                  f"sp={len(f.sparse_idx)} {f.path}{w}")

    if min_built and built_bytes < min_built:
        raise SystemExit(f"diskcheck: built-bytes {built_bytes} < required {min_built}")
    return match, n


def selftest(disk_path=SYSTEM_DISK):
    """Prove the harness + overlay are byte-clean (no builders needed)."""
    orig = open(disk_path, 'rb').read()
    buf = bytearray(orig)
    vol = Volume(buf)
    assert bytes(buf) == orig, "no-op round-trip not byte-identical"
    print("  no-op round-trip: byte-identical  OK")
    files = catalog_disk(vol)
    n = 0
    for f in files:
        if f.owner != BUILD:
            continue
        overlay(vol, f, vol.read_file(f.path))   # original content -> must stay identical
        n += 1
    ok = bytes(buf) == orig
    print(f"  overlay {n} BUILD files with original content: "
          f"{'byte-identical  OK' if ok else 'DIFFERS (overlay not clean!)'}")

    nr = 0
    for f in files:
        if f.owner != REZ or not f.has_rsrc:
            continue
        overlay_rsrc(vol, f, vol.read_file(f.path, fork='rsrc'))  # must stay identical
        nr += 1
    ok_rsrc = bytes(buf) == orig
    print(f"  overlay_rsrc {nr} REZ files with original resource-fork content: "
          f"{'byte-identical  OK' if ok_rsrc else 'DIFFERS (overlay_rsrc not clean!)'}")
    return ok and ok_rsrc


def main():
    if '--selftest' in sys.argv:
        sys.exit(0 if selftest() else 1)
    mb = 0
    if '--min-built' in sys.argv:
        mb = int(sys.argv[sys.argv.index('--min-built') + 1])
    check(verbose=('-v' in sys.argv or '--verbose' in sys.argv), min_built=mb)


if __name__ == '__main__':
    main()
