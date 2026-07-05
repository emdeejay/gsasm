#!/usr/bin/env python3
"""diskcheck.py — M8: reconstruct the shipping GS/OS 6.0.1 disk images byte-exact.

The disk-level analogue of work/buildrom.py. A shipping .2mg is a ProDOS volume
full of files; most of the System Disk is ASM we build from clean-room source
(GS.OS, prodos, the ToolNNN, FSTs, drivers, …). This harness reconstructs the
image: every file we can BUILD is overlaid into its ORIGINAL data blocks; the
rest (Pascal/C programs, resource forks, fonts/icons/Finder.Data) is kept from the
original — exactly the ROM pattern ("N% gsasm-built, byte-identical via
substitution"). It then byte-compares to the shipping image.

The ProDOS/2IMG layer is the a2til toolkit (github: a2til; /Users/mdj/src/a2til) —
a read/write ProDOS disk-image library cross-checked byte-for-byte against cadius
and real disks — so we do NOT re-implement the filesystem here.

Byte-exact discipline: the overlay writes ONLY a file's data blocks (leaving the
directory entry, dates, index blocks, and every other file untouched), so a
correctly-built file leaves the image byte-identical and an incorrect one shows
exactly which of its bytes differ — turning the structural grind into a precise,
disk-driven worklist.

    python3 work/diskcheck.py            # System Disk: round-trip + inventory
    python3 work/diskcheck.py --selftest # prove the overlay is byte-clean

STATUS: skeleton. The a2til-driven catalog + byte-clean overlay + round-trip are
in place; per-file SOURCE_BUILDERS (path -> our toolchain -> file bytes) are wired
in as each file's disk-build path is confirmed (M8 phase 2).
"""
import sys, os

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))          # gsasm/
sys.path.insert(0, '/Users/mdj/src/a2til')          # the a2til toolkit
from a2til.prodos import Volume, ST_EXTENDED        # noqa: E402

DISKS = 'ref/GSOS_6/System601_disks/System 6.0.1'
SYSTEM_DISK = f'{DISKS}/Disk 2 of 7 System Disk.2mg'

# GS/OS / ProDOS file types that are (or become) clean-room ASM output.
OURS_TYPES = {
    0x00,        # unknown-but-often-ours (checked per file)
    0xB3, 0xB5,  # S16 / EXE (load files)
    0xBB,        # DVR   driver
    0xBC,        # LDF   load file (toolsets, Error.Msg, ...)
    0xBD,        # FST
    0xBF,        # OS    (GS.OS / Start.GS.OS)
    0xFF,        # SYS   (ProDOS 8, P8)
    0xB6,        # PIF   permanent init
    0xE0,        # TOL   toolset (ToolNNN)  (Apple assigns $BA on disk; see below)
    0xBA,        # TOL   toolset
}
SUBSTITUTE_TYPES = {
    0xC9,        # FND   Finder.Data (icons/window metadata)
    0xCA,        # FTD   FType (icon file)
    0xC8,        # FON   font
    0x2A,        # CFG   config (Font.Lists)  (varies)
    0xB8,        # CDV   control panel (mostly Pascal/GUI)
    0xB9,        # NDA   desk accessory (GUI)
}


class DiskFile:
    __slots__ = ('path', 'type', 'aux', 'storage_type', 'data_eof',
                 'has_rsrc', 'is_ours')

    def __init__(self, path, entry):
        self.path = path
        self.type = entry.type
        self.aux = entry.aux_type
        self.storage_type = entry.storage_type
        self.has_rsrc = (entry.storage_type == ST_EXTENDED)
        self.data_eof = entry.eof
        self.is_ours = None      # decided in classify()


def _walk(vol, path):
    """Yield (path, entry) for every FILE under `path` (recursive)."""
    for entry in vol.scandir(path):
        child = path.rstrip('/') + '/' + entry.name
        if entry.is_dir:
            yield from _walk(vol, child)
        else:
            yield child, entry


def catalog_disk(vol):
    """Return [DiskFile] for every file on the volume, classified ours/substitute."""
    root = '/' + vol.name
    files = []
    for path, entry in _walk(vol, root):
        f = DiskFile(path, entry)
        # A resource-forked file needs Rez to rebuild its fork (out of scope) —
        # substitute it whole for now, even if its data fork is ASM.
        if f.has_rsrc:
            f.is_ours = False
        elif f.type in SUBSTITUTE_TYPES:
            f.is_ours = False
        elif f.type in OURS_TYPES:
            f.is_ours = True
        else:
            f.is_ours = False
        files.append(f)
    return files


def data_blocks(vol, path):
    """Ordered data-fork block numbers of `path` (a2til's own walk)."""
    entry = vol.entry_for(path)
    st, key, eof = vol._resolve_fork(entry, 'data')
    return vol._blocks_for(st, key, eof), eof


def overlay(vol, path, content):
    """Write `content` into `path`'s ORIGINAL data blocks (raw, byte-clean).

    Leaves the directory entry, index blocks, and all other files untouched, so a
    byte-correct `content` yields a byte-identical image. `content` must fit the
    file's existing block count (a disk-build produces the same-size file)."""
    blocks, eof = data_blocks(vol, path)
    if len(content) > len(blocks) * 512:
        raise ValueError(f'{path}: build is {len(content)}B > {len(blocks)} blocks')
    for i, blk in enumerate(blocks):
        if blk == 0:
            continue          # sparse (unallocated) block: its data is zero, not
            # stored — the built content must be zero there too (verified by diff)
        vol._write_block(blk, content[i * 512:(i + 1) * 512])


# path -> callable() -> bytes (the exact on-disk file). Wired as build paths land.
# Each builder must return the FULL disk file (e.g. the ExpressLoad'd OMF), not the
# de-ExpressLoad'd code image the *check.py harnesses compare.
SOURCE_BUILDERS: dict = {}


def check(disk_path=SYSTEM_DISK, verbose=False):
    orig = open(disk_path, 'rb').read()
    buf = bytearray(orig)
    vol = Volume(buf)
    files = catalog_disk(vol)

    built = subst = build_bytes = 0
    diffs_by_file = {}
    for f in files:
        if f.path in SOURCE_BUILDERS:
            content = SOURCE_BUILDERS[f.path]()
            overlay(vol, f.path, content)
            built += 1
        else:
            subst += 1
            if f.is_ours:
                build_bytes += f.data_eof    # source-buildable, not yet wired

    recon = bytes(buf)
    n = min(len(recon), len(orig))
    match = sum(1 for i in range(n) if recon[i] == orig[i])
    ours = sum(1 for f in files if f.is_ours)
    ours_bytes = sum(f.data_eof for f in files if f.is_ours)
    total_bytes = sum(f.data_eof for f in files)

    print(f"{os.path.basename(disk_path)}: {vol.name}  {vol.total_blocks} blocks")
    print(f"  files: {len(files)}  |  ours(ASM): {ours}  substitute: {len(files)-ours}")
    print(f"  data bytes: {total_bytes}  |  source-buildable: {ours_bytes} "
          f"({100*ours_bytes//total_bytes}%)")
    print(f"  SOURCE_BUILDERS wired: {built}  (remaining ours to wire: {ours-built})")
    print(f"  image byte-match: {match}/{n} ({100*match//n}%)")
    if verbose:
        for f in files:
            tag = 'OURS ' if f.is_ours else 'subst'
            wired = ' [built]' if f.path in SOURCE_BUILDERS else ''
            print(f"    {tag} ${f.type:02X} {f.data_eof:>7}B "
                  f"{'+rsrc' if f.has_rsrc else '     '} {f.path}{wired}")
    return match, n


def selftest(disk_path=SYSTEM_DISK):
    """Prove the harness + overlay are byte-clean (no builders needed)."""
    orig = open(disk_path, 'rb').read()

    buf = bytearray(orig)
    vol = Volume(buf)
    assert bytes(buf) == orig, "no-op round-trip not byte-identical"
    print("  no-op round-trip: byte-identical  OK")

    # overlay every ASM file with its OWN original content -> must stay identical
    files = catalog_disk(vol)
    overlaid = 0
    for f in files:
        if not f.is_ours:
            continue
        content = vol.read_file(f.path)          # the original bytes
        overlay(vol, f.path, content)
        overlaid += 1
    ok = bytes(buf) == orig
    print(f"  overlay {overlaid} ours-files with original content: "
          f"{'byte-identical  OK' if ok else 'DIFFERS (overlay not clean!)'}")
    if not ok:
        d = [i for i in range(len(orig)) if bytes(buf)[i] != orig[i]]
        print(f"    {len(d)} diffs, first @ {d[0]:#x}")
    return ok


def main():
    if '--selftest' in sys.argv:
        ok = selftest()
        sys.exit(0 if ok else 1)
    check(verbose='-v' in sys.argv or '--verbose' in sys.argv)


if __name__ == '__main__':
    main()
