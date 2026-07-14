#!/usr/bin/env python3
"""rezemitcheck.py — M7/R2: round-trip check for gsasm/rez/emit.py.

For each of the 9 golden resource forks (work/rezcheck.py's REZ_FILES):
parse it with rezcheck, reconstruct the `(resources, meta)` inputs
`emit_fork` needs straight from the parsed golden Fork (resource list in
*data order*, and every settable memo/map field read back out of the raw
memo bytes — see gsasm/rez/emit.py's docstring for the field layout), call
`emit_fork`, and byte-compare the result against the golden fork via
rezcheck.compare().

Deliberately does NOT import the `gsasm.rez` package (`gsasm/rez/emit.py`
is loaded directly via importlib) so this harness has zero dependency on
`gsasm/rez/__init__.py` / `lexer.py`, which may be under concurrent
development by another packet's agent.

Usage:
    python3 work/rezemitcheck.py         # round-trip all 9 golden forks
"""
import sys, os, struct, importlib.util

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)                 # so `import rezcheck` / `diskcheck` work
import rezcheck as rc                     # noqa: E402

REPO_ROOT = os.path.dirname(HERE)
EMIT_PATH = os.path.join(REPO_ROOT, 'gsasm', 'rez', 'emit.py')
_spec = importlib.util.spec_from_file_location('gsasm_rez_emit', EMIT_PATH)
emit = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(emit)


def _resources_in_data_order(fork: rc.Fork):
    """(type, id, attr, data) tuples in SOURCE (data-offset) order — the
    order emit_fork needs to reproduce the data region byte-for-byte."""
    by_offset = sorted(fork.used, key=lambda e: e.offset)
    return [(e.type, e.id, e.attr, fork.raw[e.offset:e.offset + e.size])
            for e in by_offset]


def _meta_from_golden(fork: rc.Fork) -> dict:
    """Reconstruct every emit.py `meta` field by reading it straight back
    out of the golden fork's raw memo bytes, per gsasm/rez/emit.py's
    documented layout. Pure decode — no guessing beyond what R2 derived."""
    memo = fork.memo
    namelen = memo[emit.MEMO_NAME_OFF]
    name_off = emit.MEMO_NAME_OFF + 1
    name = memo[name_off:name_off + namelen].decode('latin-1')
    off = name_off + namelen
    pad_byte = 0
    if namelen % 2 == 0:
        pad_byte = memo[off]
        off += 1
    memo_const = struct.unpack_from('<I', memo, off)[0]
    off += 4
    copy1_off = off
    copy1_end = copy1_off + 8
    filetype = bytes(memo[copy1_off:copy1_off + 4])
    creator = bytes(memo[copy1_off + 4:copy1_end])

    marker = b'\x00\x00'
    marker_off = copy1_end + emit.MEMO_MARKER_REL
    if marker_off + 2 <= emit.MEMO_COPY2_OFF:
        marker = bytes(memo[marker_off:marker_off + 2])

    # sanity: copy 2 must be byte-identical (true in all 9 golden forks)
    copy2 = bytes(memo[emit.MEMO_COPY2_OFF:emit.MEMO_COPY2_OFF + 8])
    assert copy2 == filetype + creator, (fork.path, copy2, filetype + creator)

    creation_ts = struct.unpack_from('>I', memo, emit.MEMO_TS_OFF)[0]
    unknown_dword = struct.unpack_from('>I', memo, emit.MEMO_DWORD2_OFF)[0]
    # MEMO_FORKLEN_OFF is derived by emit_fork itself, not read back here.

    h = fork.header
    m = fork.map
    return {
        'name': name,
        'filetype': filetype,
        'creator': creator,
        'creation_mac_ts': creation_ts,
        'name_pad_byte': pad_byte,
        'memo_const': memo_const,
        'memo_marker': marker,
        'memo_unknown_dword': unknown_dword,
        'version': h.version,
        'map_flags': m.flags,
        'file_num': m.filenum,
        'file_id': m.fileid,
    }


def roundtrip(path: str) -> bool:
    fork = rc.golden_fork(path)
    resources = _resources_in_data_order(fork)
    meta = _meta_from_golden(fork)
    built = emit.emit_fork(resources, meta)

    report = rc.compare(fork.raw, built)
    ok = report['ok'] and built == fork.raw
    print(f'{"PASS" if ok else "FAIL"} {path}: len golden={len(fork.raw)} built={len(built)} '
          f'header_diff={report["header_diff"]} memo_diff={report["memo_diff"]} '
          f'map_diff={report["map_diff"]} match={report["n_match"]}/{report["n_resources"]} '
          f'diff={report["n_diff"]} missing={report["n_missing"]} extra={report["n_extra"]}')
    if not ok and built != fork.raw:
        n = min(len(built), len(fork.raw))
        first = next((i for i in range(n) if built[i] != fork.raw[i]), n)
        print(f'    first raw byte diff at offset {first}: '
              f'golden={fork.raw[first:first+8].hex()} built={built[first:first+8].hex()}')
    return ok


def main():
    ok = True
    for path in rc.REZ_FILES:
        ok = roundtrip(path) and ok
    print(f'{"PASS" if ok else "FAIL"} rezemitcheck: {len(rc.REZ_FILES)} golden fork(s) round-tripped')
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
