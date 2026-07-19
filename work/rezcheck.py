#!/usr/bin/env python3
"""rezcheck.py — M7/R1: parse & compare Apple IIgs resource forks.

The Rez-milestone analogue of fstcheck.py/diskcheck.py: extracts the resource
forks of the 9 REZ-owned files (diskcheck.MANIFEST, owner 'rez') from the
System 6.0.1 disk images (reusing diskcheck's a2til Volume), parses the
IIgs resource-fork binary format (header/memo/map/index/free-list/data —
see docs/design/rez.md, "Golden fork format — decoded facts"), and exposes
that parse as a small library (`Fork`, `golden_fork`, `compare`) that later
Rez packets (R2 emitter onward) import to drive byte-exact reconstruction.

Byte-level layout (little-endian throughout; all offsets absolute unless noted):

    header (12 B):  version(4)  toMap(4)  mapSize(4)
    memo   (128 B): opaque per-file metadata (name, filetype/creator, a
                     Mac-epoch timestamp, file length — not yet a decoded
                     field layout; that's packet R2's job). Captured raw here.
    map  @ toMap:    handle(4,=0) flags(2) offset(4,=toMap) size(4,=mapSize)
                     toIndex(2) fileNum(2) fileID(2) indexSize(4) indexUsed(4)
                     freeListSize(2) freeListUsed(2)                  [32 B]
                     free list: freeListSize x {offset(4) size(4)}    [+pad]
                     index @ map+toIndex: indexSize x 20-byte records
                       type(2) id(4) offset(4) attr(2) size(4) handle(4,=0)
                       sorted by (type,id); unused trailing slots all-zero.
                                                                       [+pad]
    resource data @ map+mapSize: contiguous, source-statement order (not
                     index order); tiles exactly to EOF with no gaps.

Reconciliation identity (proven across all 9 golden forks): 12 + 128 +
mapSize + sum(resource sizes) == fork length.

Usage:
    python3 work/rezcheck.py                # self-check: parse all 9 golden
                                             # forks, verify reconciliation,
                                             # Sys.Resources counts, and that
                                             # compare(golden, golden) is clean
    python3 work/rezcheck.py --dump [suffix]  # dump one (path suffix match)
                                               # or all 9 forks: header, map,
                                               # index, reconciliation

Library (for R2+):
    from rezcheck import golden_fork, all_golden, compare, Fork
    compare(golden_bytes, built_bytes) -> report dict with per-resource,
    per-region (header/memo/map) first-diff attribution.
"""
import sys, os, struct
from collections import namedtuple

from _common import WORK, ensure_repo_on_path, first_diff as _first_diff
ensure_repo_on_path(WORK)                # so `import diskcheck` works from anywhere
import diskcheck as dc                   # noqa: E402 (also wires a2til onto sys.path)
from a2til.prodos import Volume          # noqa: E402

REZ_FILES = [p for p, o in dc.MANIFEST.items() if o == dc.REZ]

# --- byte-level constants (docs/design/rez.md) ------------------------------
HDR_SIZE    = 12    # version(4) toMap(4) mapSize(4)
MEMO_SIZE   = 128
MAP_FIXED   = 32    # handle(4) flags(2) offset(4) size(4) toIndex(2) fileNum(2)
                     # fileID(2) indexSize(4) indexUsed(4) freeListSize(2) freeListUsed(2)
FREE_ENTRY  = 8      # offset(4) size(4)
INDEX_ENTRY = 20     # type(2) id(4) offset(4) attr(2) size(4) handle(4)

Header = namedtuple('Header', 'version tomap mapsize')
MapRec = namedtuple('MapRec', 'handle flags offset size toindex filenum fileid '
                               'indexsize indexused freelistsize freelistused')
Entry  = namedtuple('Entry', 'type id offset attr size handle')


class Fork:
    """A parsed Apple IIgs resource fork. Never raises on a spec violation —
    violations are collected in `.violations` so the harness can report
    surprises instead of crashing (per R1's brief)."""

    def __init__(self, path, raw):
        self.path = path
        self.raw = raw
        self.violations = []
        self._parse()

    def _v(self, msg):
        self.violations.append(msg)

    def _parse(self):
        raw = self.raw
        if len(raw) < HDR_SIZE + MEMO_SIZE:
            self._v(f'fork too short for header+memo ({len(raw)}B)')
            self.header = Header(None, None, None)
            self.memo = raw[HDR_SIZE:HDR_SIZE + MEMO_SIZE]
            self.map_off = None
            self.map = None
            self.free_entries = []
            self.used = []
            self.unused = []
            self.data_start = None
            self.contiguous = False
            self.gaps = []
            self.recon_ok = False
            self.recon_total = None
            return

        version, tomap, mapsize = struct.unpack_from('<III', raw, 0)
        self.header = Header(version, tomap, mapsize)
        self.memo = raw[HDR_SIZE:HDR_SIZE + MEMO_SIZE]
        if tomap != HDR_SIZE + MEMO_SIZE:
            self._v(f'header.toMap {tomap:#x} != end-of-memo {HDR_SIZE + MEMO_SIZE:#x}')

        map_off = tomap
        self.map_off = map_off
        handle, flags, offset, size, toindex, filenum, fileid = \
            struct.unpack_from('<IHIIHHH', raw, map_off)
        indexsize, indexused = struct.unpack_from('<II', raw, map_off + 20)
        freelistsize, freelistused = struct.unpack_from('<HH', raw, map_off + 28)
        self.map = MapRec(handle, flags, offset, size, toindex, filenum, fileid,
                           indexsize, indexused, freelistsize, freelistused)
        if handle != 0:
            self._v(f'map.handle {handle} != 0')
        if offset != tomap:
            self._v(f'map.offset {offset:#x} != header.toMap {tomap:#x}')
        if size != mapsize:
            self._v(f'map.size {size} != header.mapSize {mapsize}')
        if indexused > indexsize:
            self._v(f'map.indexUsed {indexused} > indexSize {indexsize}')
        if freelistused > freelistsize:
            self._v(f'map.freeListUsed {freelistused} > freeListSize {freelistsize}')

        free_area_len = toindex - MAP_FIXED
        self.free_pad = free_area_len - freelistsize * FREE_ENTRY
        if self.free_pad < 0:
            self._v(f'free-list area {free_area_len}B too small for '
                    f'freeListSize={freelistsize} ({FREE_ENTRY}B/entry)')
            self.free_entries = []
        else:
            self.free_entries = [struct.unpack_from('<II', raw, map_off + MAP_FIXED + i * FREE_ENTRY)
                                  for i in range(freelistsize)]

        index_off = map_off + toindex
        self.index_off = index_off
        entries = [Entry(*struct.unpack_from('<HIIHII', raw, index_off + i * INDEX_ENTRY))
                   for i in range(indexsize)]
        self.used = entries[:indexused]
        self.unused = entries[indexused:]
        if not all(e == (0, 0, 0, 0, 0, 0) for e in self.unused):
            self._v('unused index slots are not all-zero')
        keys = [(e.type, e.id) for e in self.used]
        if keys != sorted(keys):
            self._v('index is not sorted by (type, id)')
        if len(set(keys)) != len(keys):
            self._v('duplicate (type, id) in index')
        for e in self.used:
            if e.handle != 0:
                self._v(f'resource ({e.type:#06x},{e.id}) has nonzero handle {e.handle:#x}')

        self.data_start = map_off + mapsize
        self.tail_pad = mapsize - (toindex + indexsize * INDEX_ENTRY)
        if self.tail_pad < 0:
            self._v('map.size too small to hold the declared index')

        by_off = sorted(self.used, key=lambda e: e.offset)
        self.gaps = []
        pos = self.data_start
        for e in by_off:
            if e.offset != pos:
                self.gaps.append((pos, e.offset))
            pos = e.offset + e.size
        if pos != len(raw):
            self.gaps.append((pos, len(raw)))
        self.contiguous = not self.gaps

        total = HDR_SIZE + MEMO_SIZE + mapsize + sum(e.size for e in self.used)
        self.recon_total = total
        self.recon_ok = (total == len(raw))
        if not self.recon_ok:
            self._v(f'reconciliation {total} != fork length {len(raw)}')

    def resource(self, type_, id_):
        """Raw bytes of resource (type_, id_), or None if the fork has none."""
        for e in self.used:
            if e.type == type_ and e.id == id_:
                return self.raw[e.offset:e.offset + e.size]
        return None


# --- golden-fork extraction (System 6.0.1 disk image via a2til) ------------

_VOL_CACHE = {}


def _volume(disk):
    if disk not in _VOL_CACHE:
        orig = open(disk, 'rb').read()
        _VOL_CACHE[disk] = Volume(bytearray(orig))
    return _VOL_CACHE[disk]


def golden_raw(path, disk=None):
    """Raw bytes of one REZ-owned file's resource fork from the System Disk."""
    return _volume(disk or dc.SYSTEM_DISK).read_file(path, fork='rsrc')


def golden_fork(path, disk=None):
    return Fork(path, golden_raw(path, disk))


def all_golden(disk=None):
    """Parsed Fork for each of the 9 REZ-owned files, in manifest order."""
    return [golden_fork(p, disk) for p in REZ_FILES]


# --- compare(): the R2-R7 workhorse ----------------------------------------

def compare(golden: bytes, built: bytes) -> dict:
    """Byte-diff two resource forks with per-resource attribution.

    Compares header/memo/map bytes as separate regions, then walks the
    golden index and byte-compares each (type, id) resource against the
    same (type, id) resource in `built` (looked up by content, not by
    position — offsets may legitimately differ between forks).
    """
    g = Fork('golden', golden)
    b = Fork('built', built)

    header_diff = _first_diff(golden[:HDR_SIZE], built[:HDR_SIZE])
    memo_diff = _first_diff(g.memo, b.memo)

    map_diff = None
    if g.map_off is not None and b.map_off is not None:
        gmap = golden[g.map_off:g.data_start]
        bmap = built[b.map_off:b.data_start]
        map_diff = _first_diff(gmap, bmap)
    else:
        map_diff = 0

    resources = []
    n_match = n_diff = n_missing = 0
    for e in g.used:
        gdata = golden[e.offset:e.offset + e.size]
        bdata = b.resource(e.type, e.id)
        if bdata is None:
            n_missing += 1
            resources.append({'type': e.type, 'id': e.id, 'status': 'missing',
                               'golden_size': e.size, 'built_size': None, 'first_diff': None})
            continue
        d = _first_diff(gdata, bdata)
        if d is None:
            n_match += 1
            resources.append({'type': e.type, 'id': e.id, 'status': 'match',
                               'golden_size': e.size, 'built_size': len(bdata), 'first_diff': None})
        else:
            n_diff += 1
            resources.append({'type': e.type, 'id': e.id, 'status': 'diff',
                               'golden_size': e.size, 'built_size': len(bdata), 'first_diff': d})

    golden_keys = {(e.type, e.id) for e in g.used}
    built_keys = {(e.type, e.id) for e in b.used}
    n_extra = len(built_keys - golden_keys)

    ok = (header_diff is None and memo_diff is None and map_diff is None
          and n_diff == 0 and n_missing == 0 and n_extra == 0)
    return {
        'ok': ok,
        'header_diff': header_diff, 'memo_diff': memo_diff, 'map_diff': map_diff,
        'resources': resources,
        'n_resources': len(g.used),
        'n_match': n_match, 'n_diff': n_diff, 'n_missing': n_missing, 'n_extra': n_extra,
    }


# --- --dump ------------------------------------------------------------

def dump(fork: Fork, out=sys.stdout):
    h, m = fork.header, fork.map
    print(f'{fork.path}', file=out)
    print(f'  fork length : {len(fork.raw)}', file=out)
    if h.version is None:
        print('  ** malformed: too short to parse header+memo **', file=out)
        return
    print(f'  header: version={h.version} toMap={h.tomap:#x} mapSize={h.mapsize}', file=out)
    print(f'  map @ {fork.map_off:#x}: handle={m.handle} flags={m.flags:#x} '
          f'offset={m.offset:#x} size={m.size} toIndex={m.toindex:#x} '
          f'fileNum={m.filenum} fileID={m.fileid}', file=out)
    print(f'  indexSize={m.indexsize} indexUsed={m.indexused} '
          f'freeListSize={m.freelistsize} freeListUsed={m.freelistused} '
          f'(free-list pad={fork.free_pad}B, index-tail pad={fork.tail_pad}B)', file=out)
    for i, (fo, fs) in enumerate(fork.free_entries):
        mark = '*' if i < m.freelistused else ' '
        print(f'    free[{i:2}]{mark} offset={fo:#010x} size={fs:#010x}', file=out)
    print(f'  index @ {fork.index_off:#x}: {len(fork.used)} used / {m.indexsize} slots', file=out)
    for e in fork.used:
        print(f'    type={e.type:#06x} id={e.id:<10} attr={e.attr:#06x} '
              f'size={e.size:<6} offset={e.offset:#x}', file=out)
    print(f'  data region [{fork.data_start:#x}, {len(fork.raw):#x}): '
          f'contiguous={fork.contiguous}' + (f' gaps={fork.gaps}' if fork.gaps else ''), file=out)
    print(f'  reconciliation: {HDR_SIZE} + {MEMO_SIZE} + {m.size} + '
          f'{sum(e.size for e in fork.used)} = {fork.recon_total} '
          f'{"==" if fork.recon_ok else "!="} fork length {len(fork.raw)} '
          f'[{"OK" if fork.recon_ok else "FAIL"}]', file=out)
    if fork.violations:
        print('  violations:', file=out)
        for v in fork.violations:
            print(f'    - {v}', file=out)
    else:
        print('  violations: none', file=out)


# --- self-check ----------------------------------------------------------

def selfcheck():
    ok = True
    forks = {}
    for path in REZ_FILES:
        try:
            f = golden_fork(path)
        except Exception as e:                            # noqa: BLE001
            print(f'FAIL {path}: parse raised {type(e).__name__}: {e}')
            ok = False
            continue
        forks[path] = f
        good = f.recon_ok and not f.violations
        print(f'{"PASS" if good else "WARN"} {path}: len={len(f.raw)} '
              f'indexUsed={f.map.indexused}/{f.map.indexsize} '
              f'freeListUsed={f.map.freelistused}/{f.map.freelistsize} '
              f'contiguous={f.contiguous} recon={f.recon_ok} '
              f'violations={len(f.violations)}')
        for v in f.violations:
            print(f'    - {v}')
        if not f.recon_ok:
            ok = False

    sysres_path = next((p for p in REZ_FILES if p.endswith('Sys.Resources')), None)
    sr = forks.get(sysres_path)
    if sr is None:
        print('FAIL: Sys.Resources not parsed')
        ok = False
    else:
        checks = [
            ('resource count == 143', len(sr.used) == 143),
            ('fork length == 24337', len(sr.raw) == 24337),
            ('map at 0x8C', sr.map_off == 0x8C),
            ('map size == 3178', sr.map.size == 3178),
        ]
        for name, cond in checks:
            print(f'{"PASS" if cond else "FAIL"} Sys.Resources {name}')
            ok = ok and cond

        report = compare(sr.raw, sr.raw)
        print(f'{"PASS" if report["ok"] else "FAIL"} compare(golden, golden) zero diffs '
              f'(match {report["n_match"]}/{report["n_resources"]}, '
              f'diff={report["n_diff"]} missing={report["n_missing"]} extra={report["n_extra"]}, '
              f'header_diff={report["header_diff"]} memo_diff={report["memo_diff"]} '
              f'map_diff={report["map_diff"]})')
        ok = ok and report['ok']

    print(f'{"PASS" if ok else "FAIL"} rezcheck self-check')
    return ok


def main():
    if '--dump' in sys.argv:
        i = sys.argv.index('--dump')
        suffix = sys.argv[i + 1] if i + 1 < len(sys.argv) else None
        paths = REZ_FILES if not suffix else [p for p in REZ_FILES if p.endswith(suffix)]
        if not paths:
            sys.exit(f'rezcheck: no REZ file path matches suffix {suffix!r}\n'
                      f'known: {", ".join(REZ_FILES)}')
        for p in paths:
            dump(golden_fork(p))
            print()
        return
    sys.exit(0 if selfcheck() else 1)


if __name__ == '__main__':
    main()
