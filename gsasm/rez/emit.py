"""gsasm/rez/emit.py — M7/R2: byte-exact Apple IIgs resource-fork emitter.

Packs an ordered list of `(type, id, attr, data)` resource tuples plus a
small metadata dict into the exact byte layout Apple's `RezIIgs` produces
(see docs/design/rez.md, "Golden fork format — decoded facts", and
work/rezcheck.py — the R1 harness this was reverse-engineered against).

    fork = header(12) + memo(128) + map(mapSize) + data

Header (12 B, little-endian): rFileVersion(4)=0, rFileToMap(4)=0x8C
(=12+128, constant), rFileMapSize(4).

Map @ 0x8C: handle(4,=0) flags(2) offset(4,=0x8C) size(4,=mapSize)
toIndex(2,=0x74, constant) fileNum(2) fileID(2) indexSize(4) indexUsed(4)
freeListSize(2,=10, constant) freeListUsed(2,=1, constant); free list (10 x
{offset(4) size(4)}, only entry 0 used — an EOF sentinel `(offset=fork
length, size=-(fork length + 1))`); 4-byte zero pad (constant, since
freeListSize is always 10); index (indexSize x 20-byte records `type(2)
id(4) offset(4) attr(2) size(4) handle(4,=0)`, sorted by (type, id),
indexSize = indexUsed + 10 — a flat +10 slack observed in all 9 golden
forks); 2-byte zero pad (constant). Resource data follows immediately,
contiguous, in SOURCE order (not index order).

THE MEMO AREA (offset 12, 128 bytes) — reverse-engineered byte-by-byte
against all 9 golden forks (System 6.0.1 golden `Sys.Resources`, `Start`
(Finder), `EasyMount`, `ControlPanel`, `General`/`Printer`/`RAM`/`Slots`/
`Time` CDEVs) using work/rezcheck.py's parse + a scratch byte-diff pass (not
committed to the repo). Absolute offsets are memo-relative (i.e. add 12 for
the fork-absolute offset):

    [  0: 36]  zero (36 bytes, constant)
    [ 36    ]  Pascal-string length byte for the file name
    [ 37: 37+n]  file name bytes (n = length byte)
    [37+n   ]  ONE pad byte, present iff n is even (i.e. iff the name
               field's total size 1+n would be odd) — rounds the name
               field up to an even length. UNEXPLAINED: its value is not
               zero in the golden forks (0xb4, 0x47, 0x81 observed) and
               looks like uninitialized tool memory, not a meaningful
               field. Settable per file (`name_pad_byte`); defaults to 0.
    [X   :X+4]  constant dword, little-endian = 2 in all 9 forks
                (X = 36 + roundup_even(1+n)). Settable (`memo_const`),
                defaults to 2.
    [X+4 :X+12] "copy 1" of the file-type/creator field (8 bytes) — see
                below. Ends at C1E = X + 12.
    [C1E+10 : C1E+12]  a 2-byte field, ONLY present when C1E+12 <= 70 (i.e.
                the name is short enough to leave room before the fixed
                copy-2 anchor at offset 70). UNEXPLAINED: byte 0 is 0x30 in
                every golden fork that has one, byte 1 varies (0xaa, 0x44,
                0x92, 0x45, 0x93, 0x95) and does not correlate with any
                ProDOS directory field, aux type, or resource count we
                tried. Settable per file (`memo_marker`, 2 bytes); defaults
                to zero. Silently dropped (not written) when it would not
                fit before offset 70 — matches every golden fork with a
                long name (`Sys.Resources`, `ControlPanel`).
    [70  : 78]  "copy 2" of the file-type/creator field (8 bytes),
                byte-identical to copy 1 in all 9 forks. ALWAYS at this
                fixed absolute offset regardless of name length.
    [78  :102]  zero (24 bytes, constant)
    [102 :106]  creation timestamp: Mac epoch (seconds since 1904-01-01),
                BIG-ENDIAN u32 (unlike everything else in the format,
                which is little-endian — consistent with this whole memo
                area being lifted verbatim from a Mac-side (68k) File
                Manager record by a host tool that never byte-swapped it).
                Matches each file's ProDOS ``creation`` date/time to the
                minute in every golden fork, with extra seconds precision
                ProDOS dates don't carry. NOT derivable from the ProDOS
                catalog alone; settable (`creation_mac_ts`), no default.
    [106 :110]  UNEXPLAINED dword, big-endian. Zero in 6/9 golden forks
                (Sys.Resources, General, Printer, RAM, Slots, Time);
                nonzero in the other 3 (Start/Finder 0x00023dec, EasyMount
                0x00002405, ControlPanel 0x00003b06) with no correlation
                found to fork length, map size, data-fork length, aux
                type, or resource count. Settable (`memo_unknown_dword`);
                defaults to 0.
    [110 :114]  fork length, big-endian u32 — DERIVED (computed from the
                assembled fork, not settable).
    [114 :128]  zero (14 bytes, constant).

"Copy 1"/"copy 2" (8 bytes: a 4-byte file-type field + 4-byte creator,
always literally "pdos" (`70 64 6f 73`) in all 9 forks): the 4-byte
file-type field's encoding depends on aux type. When aux_type == 0 (8 of 9
forks) it's the ASCII rendering RezIigs's `-t` flag takes literally, e.g.
`-t "F9  "` -> `46 39 20 20` ("F9  "). When aux_type != 0 (`/System/Start`,
the Finder, aux=$03DB) there's no room for a readable string, so it's
`'p'` + raw ProDOS type byte + raw aux_type (2 bytes, little-endian) — this
is the classic ProDOS<->HFS ".info" file-type-string convention. See
`format_filetype()` below, which implements this derivation; `emit_fork`
does not call it automatically — pass the resulting bytes (or your own) as
`meta['filetype']`.

None of the 9 unexplained-byte categories above block byte-exact
reconstruction: they are exposed as explicitly settable `meta` fields
(golden per-file values reproduce the golden forks bit-for-bit; new files
can just leave them at their zero defaults).

API:
    emit_fork(resources, meta) -> bytes
        resources: ordered list of (rtype: int, rid: int, attr: int,
            data: bytes) in SOURCE order — this order becomes the resource
            *data* layout; the index is built sorted by (type, id)
            separately, as the real format requires.
        meta: dict, see DEFAULT_META below for every recognized key,
            its meaning, and its default.
"""
from __future__ import annotations
import struct

# --- byte-level constants (see docstring above and docs/design/rez.md) -----
HDR_SIZE = 12
MEMO_SIZE = 128
MAP_FIXED = 32                              # handle+flags+offset+size+toIndex+
                                             # fileNum+fileID+indexSize+indexUsed+
                                             # freeListSize+freeListUsed
FREE_LIST_SIZE = 10                         # constant in all 9 golden forks
FREE_ENTRY = 8                              # offset(4) size(4)
FREE_LIST_PAD = 4                           # constant zero pad after the free list
INDEX_ENTRY = 20                            # type(2) id(4) offset(4) attr(2) size(4) handle(4)
INDEX_SLACK = 10                            # indexSize = indexUsed + 10, flat, all 9 forks
TAIL_PAD = 2                                # constant zero pad after the index
TOINDEX = MAP_FIXED + FREE_LIST_SIZE * FREE_ENTRY + FREE_LIST_PAD   # 0x74, constant

MEMO_NAME_OFF = 36                          # offset of the pstring length byte
MEMO_COPY2_OFF = 70                         # copy-2 of type/creator: fixed, always here
MEMO_TS_OFF = 102                           # creation timestamp (big-endian)
MEMO_DWORD2_OFF = 106                       # unexplained dword (big-endian)
MEMO_FORKLEN_OFF = 110                      # fork length (big-endian) — derived
MEMO_MARKER_REL = 10                        # marker sits copy1_end + 10 (if it fits)

# Every recognized `meta` key with its default. Keys not settable here
# (fork length, header/map sizes) are always derived from `resources`.
DEFAULT_META = {
    'name': '',                    # file name (Pascal string, <=127 bytes as latin-1)
    'filetype': b'\x00\x00\x00\x00',  # 4 raw bytes — see format_filetype()
    'creator': b'pdos',             # 4 raw bytes, "pdos" in all 9 golden forks
    'creation_mac_ts': 0,           # seconds since 1904-01-01, big-endian; not
                                    # derivable from ProDOS's minute-granularity dates
    'name_pad_byte': 0,             # unexplained pad byte after an even-length name
    'memo_const': 2,                # unexplained-but-constant dword after the name; =2
    'memo_marker': b'\x00\x00',     # unexplained 2-byte field (see docstring)
    'memo_unknown_dword': 0,        # unexplained dword near the tail (see docstring)
    'version': 0,                   # header rFileVersion; 0 in all 9 golden forks
    'map_flags': 0,                 # map.flags; 0 in all 9 golden forks
    'file_num': 0,                  # map.fileNum; 0 in all 9 golden forks
    'file_id': 0,                   # map.fileID; 0 in all 9 golden forks
}


def format_filetype(type_byte: int, aux_type: int = 0) -> bytes:
    """The observed derivation for the memo's 4-byte file-type field.

    aux_type == 0: two uppercase-hex-digit ASCII characters + two spaces,
    e.g. type $F9 -> b'F9  ' (matches RezIigs's `-t "F9  "` command-line
    convention, observed in 8 of the 9 golden forks).

    aux_type != 0: b'p' + raw type byte + raw aux_type (2 bytes, LE) — the
    classic ProDOS<->HFS file-type-string convention that also preserves
    the aux type, observed on `/System/Start` (the Finder, type=$B3,
    aux=$03DB).

    `emit_fork` never calls this itself; pass its result (or your own 4
    raw bytes) as `meta['filetype']`.
    """
    if aux_type == 0:
        return ('%02X  ' % (type_byte & 0xFF)).encode('ascii')
    return bytes([0x70, type_byte & 0xFF, aux_type & 0xFF, (aux_type >> 8) & 0xFF])


def _fixed_bytes(v, n: int) -> bytes:
    """Coerce `v` (str or bytes) to exactly `n` bytes (latin-1 if str)."""
    b = v.encode('latin-1') if isinstance(v, str) else bytes(v)
    if len(b) != n:
        raise ValueError(f'expected {n} bytes, got {len(b)}: {b!r}')
    return b


def _build_memo(meta: dict, fork_length: int) -> bytes:
    m = bytearray(MEMO_SIZE)

    name = meta['name'].encode('latin-1') if isinstance(meta['name'], str) else bytes(meta['name'])
    if not (0 <= len(name) <= 127):
        raise ValueError(f'file name must be 0..127 bytes, got {len(name)}')

    off = MEMO_NAME_OFF
    m[off] = len(name)
    off += 1
    m[off:off + len(name)] = name
    off += len(name)
    if len(name) % 2 == 0:              # even name length -> pad to even field size
        m[off] = meta['name_pad_byte'] & 0xFF
        off += 1
    struct.pack_into('<I', m, off, meta['memo_const'] & 0xFFFFFFFF)
    off += 4

    copy1_off = off
    copy1_end = copy1_off + 8
    if copy1_end > MEMO_COPY2_OFF:
        raise ValueError(f'file name {meta["name"]!r} too long: type/creator '
                          f'field (ends at {copy1_end}) collides with the '
                          f'fixed copy-2 anchor at {MEMO_COPY2_OFF}')

    filetype = _fixed_bytes(meta['filetype'], 4)
    creator = _fixed_bytes(meta['creator'], 4)
    m[copy1_off:copy1_off + 4] = filetype
    m[copy1_off + 4:copy1_end] = creator

    marker_off = copy1_end + MEMO_MARKER_REL
    if marker_off + 2 <= MEMO_COPY2_OFF:
        m[marker_off:marker_off + 2] = _fixed_bytes(meta['memo_marker'], 2)

    m[MEMO_COPY2_OFF:MEMO_COPY2_OFF + 4] = filetype
    m[MEMO_COPY2_OFF + 4:MEMO_COPY2_OFF + 8] = creator

    struct.pack_into('>I', m, MEMO_TS_OFF, meta['creation_mac_ts'] & 0xFFFFFFFF)
    struct.pack_into('>I', m, MEMO_DWORD2_OFF, meta['memo_unknown_dword'] & 0xFFFFFFFF)
    struct.pack_into('>I', m, MEMO_FORKLEN_OFF, fork_length & 0xFFFFFFFF)

    return bytes(m)


def _build_map(resources, meta: dict, map_size: int, data_offsets, fork_length: int) -> bytes:
    n = len(resources)
    index_size = n + INDEX_SLACK

    out = bytearray()
    out += struct.pack('<IHIIHHH',
                        0,                          # handle
                        meta['map_flags'] & 0xFFFF,
                        HDR_SIZE + MEMO_SIZE,        # offset (= header.toMap)
                        map_size,                    # size (= header.mapSize)
                        TOINDEX,
                        meta['file_num'] & 0xFFFF,
                        meta['file_id'] & 0xFFFF)
    out += struct.pack('<II', index_size, n)
    out += struct.pack('<HH', FREE_LIST_SIZE, 1)     # freeListSize, freeListUsed

    # free list: one used EOF-sentinel entry, the rest zeroed.
    out += struct.pack('<Ii', fork_length, -(fork_length + 1))
    out += bytes(FREE_ENTRY * (FREE_LIST_SIZE - 1))
    out += bytes(FREE_LIST_PAD)

    # index: sorted by (type, id); trailing slack slots stay zeroed.
    order = sorted(range(n), key=lambda i: (resources[i][0] & 0xFFFF, resources[i][1] & 0xFFFFFFFF))
    for i in order:
        rtype, rid, attr, data = resources[i]
        out += struct.pack('<HIIHII', rtype & 0xFFFF, rid & 0xFFFFFFFF,
                            data_offsets[i], attr & 0xFFFF, len(data), 0)
    out += bytes(INDEX_ENTRY * INDEX_SLACK)
    out += bytes(TAIL_PAD)

    assert len(out) == map_size, (len(out), map_size)
    return bytes(out)


def emit_fork(resources, meta: dict) -> bytes:
    """Build a byte-exact Apple IIgs resource fork.

    `resources`: ordered list of (rtype, rid, attr, data) in SOURCE order —
    this order is preserved for the resource *data* region; the map's index
    is built separately, sorted by (type, id), as the real format requires.

    `meta`: dict of settable fields; see DEFAULT_META for the full list,
    defaults, and docs/design/rez.md + this module's docstring for how each
    was reverse-engineered. Unknown keys are rejected; missing keys take
    their default.
    """
    unknown = set(meta) - set(DEFAULT_META)
    if unknown:
        raise ValueError(f'unknown meta key(s): {sorted(unknown)}')
    m = dict(DEFAULT_META)
    m.update(meta)

    # Validate rather than silently truncate: the map's index stores type
    # in a 16-bit field and id in a 32-bit field (see docstring's index
    # layout), so an out-of-range value here would otherwise be masked
    # (`& 0xFFFF`/`& 0xFFFFFFFF` below) and could alias a different,
    # in-range resource's key without either caller noticing (Medium/low
    # finding: `type $10000 { byte; }; resource $10000(1) { 7 };` used to
    # silently produce type `$0000` in the emitted fork). `gsasm.rez.gen`'s
    # `generate()` already rejects these before they get here in the
    # normal `gsrez` pipeline; this check makes `emit_fork()` itself robust
    # for any other/direct caller.
    for i, (rtype, rid, _attr, _data) in enumerate(resources):
        if not (0 <= rtype <= 0xFFFF):
            raise ValueError(f'resource #{i}: type {rtype:#x} out of range '
                              f'(must fit in the 16-bit type-index field, '
                              f'0..0xFFFF)')
        if not (0 <= rid <= 0xFFFFFFFF):
            raise ValueError(f'resource #{i}: id {rid:#x} out of range '
                              f'(must fit in the 32-bit id field, '
                              f'0..0xFFFFFFFF)')

    n = len(resources)
    index_size = n + INDEX_SLACK
    map_size = TOINDEX + index_size * INDEX_ENTRY + TAIL_PAD

    data_start = HDR_SIZE + MEMO_SIZE + map_size
    data_offsets = []
    pos = data_start
    for _, _, _, data in resources:
        data_offsets.append(pos)
        pos += len(data)
    fork_length = pos

    header = struct.pack('<III', m['version'] & 0xFFFFFFFF, HDR_SIZE + MEMO_SIZE, map_size)
    memo = _build_memo(m, fork_length)
    map_bytes = _build_map(resources, m, map_size, data_offsets, fork_length)
    data = b''.join(data for _, _, _, data in resources)

    out = header + memo + map_bytes + data
    assert len(out) == fork_length, (len(out), fork_length)
    return out
