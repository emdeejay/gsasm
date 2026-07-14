"""Hand-authored END-TO-END pipeline test for the Rez milestone (packet R7).

Exercises the FULL public pipeline over a small ORIGINAL `.r` source (not
derived from any Apple material): `gsasm.rez.parser.parse()` ->
`gsasm.rez.gen.generate()` -> resolve the one `read` statement against a
small hand-made binary payload (`gsasm.rez.convert.convert_load()`) ->
`gsasm.rez.gen.to_emit_tuples()` -> `gsasm.rez.emit.emit_fork()` -- and,
separately, the `gsrez` CLI (`gsasm.__main__.rez_main`, invoked
out-of-process so it runs the real argv/argparse surface).

The source declares its own tiny type template (an `integer` + a
`pstring`), two `resource` statements (one attaching a `"name"` string,
which exercises rResName ($8014) synthesis; a different attribute on
each), and one `read` statement over a small hand-made binary.

The expected fork bytes are computed BY HAND in `_expected_fork()` below
(`struct.pack` calls mirroring `gsasm/rez/emit.py`'s documented header/
memo/map/index/data layout -- see its module docstring and
docs/design/rez.md's "Golden fork format" section), NOT by calling
`emit_fork()` for the expected side too: a bug in the library would have
to be independently reproduced here to slip through undetected.

Run either as:
    python3 -m pytest tests/test_rez_pipeline.py
    python3 tests/test_rez_pipeline.py
"""
import os
import struct
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from gsasm.rez import parser, gen, emit, convert  # noqa: E402

# --------------------------------------------------------------------------
# The fixture source: own tiny type template, two resources (one named,
# exercising rResName synthesis; different attributes on each), one `read`.
# --------------------------------------------------------------------------
SOURCE = (
    b'type 1 {\r'
    b'  integer;\r'
    b'  pstring;\r'
    b'};\r'
    b'resource 1 (100, "Alpha", locked) { $1234, "Hi" };\r'
    b'resource 1 (200, fixed) { $5678, "Yo" };\r'
    b'read 2 (300, Convert, locked) "payload.bin";\r'
)
PAYLOAD = b'\xDE\xAD\xBE\xEF\x00\x01'

# Fork metadata for this test -- deliberately NOT the "pdos"/golden-style
# defaults, to prove nothing here is hardcoded to the Sys.Resources corpus.
META = {
    'name': 'Tiny',
    'filetype': b'TEST',
    'creator': b'ABCD',
    'creation_mac_ts': 0x12345678,
}


def _write_fixture(d):
    src = os.path.join(d, 'tiny.r')
    with open(src, 'wb') as f:
        f.write(SOURCE)
    with open(os.path.join(d, 'payload.bin'), 'wb') as f:
        f.write(PAYLOAD)
    return src


def _expected_fork():
    """The expected fork, built by hand from the documented layout (NOT via
    gsasm.rez.emit): header(12) + memo(128) + map + data, source-order data
    with the synthesized rResName last, index sorted by (type, id)."""
    data1 = struct.pack('<H', 0x1234) + bytes([2]) + b'Hi'            # 5 B
    data2 = struct.pack('<H', 0x5678) + bytes([2]) + b'Yo'            # 5 B
    data3 = PAYLOAD                                                    # 6 B (Convert == identity)
    resname = (struct.pack('<H', 1) + struct.pack('<I', 1)
               + struct.pack('<I', 100) + bytes([5]) + b'Alpha')       # 16 B
    assert (len(data1), len(data2), len(data3), len(resname)) == (5, 5, 6, 16)

    n = 4
    index_size = n + 10                        # INDEX_SLACK
    map_size = 0x74 + index_size * 20 + 2       # TOINDEX + index + TAIL_PAD
    data_start = 12 + 128 + map_size
    offsets, pos = [], data_start
    for chunk in (data1, data2, data3, resname):
        offsets.append(pos)
        pos += len(chunk)
    fork_length = pos

    header = struct.pack('<III', 0, 140, map_size)

    memo = bytearray(128)
    name = META['name'].encode('latin-1')
    memo[36] = len(name)
    memo[37:37 + len(name)] = name
    off = 37 + len(name)
    if len(name) % 2 == 0:
        memo[off] = 0                          # name_pad_byte default
        off += 1
    struct.pack_into('<I', memo, off, 2)       # memo_const default
    off += 4
    copy1 = off
    memo[copy1:copy1 + 4] = META['filetype']
    memo[copy1 + 4:copy1 + 8] = META['creator']
    memo[70:74] = META['filetype']
    memo[74:78] = META['creator']
    struct.pack_into('>I', memo, 102, META['creation_mac_ts'])
    struct.pack_into('>I', memo, 106, 0)       # memo_unknown_dword default
    struct.pack_into('>I', memo, 110, fork_length)

    m = bytearray()
    m += struct.pack('<IHIIHHH', 0, 0, 140, map_size, 0x74, 0, 0)
    m += struct.pack('<II', index_size, n)
    m += struct.pack('<HH', 10, 1)
    m += struct.pack('<Ii', fork_length, -(fork_length + 1))
    m += bytes(8 * 9)                          # 9 unused free-list entries
    m += bytes(4)                              # constant pad
    records = sorted([
        (1, 100, offsets[0], 0x8000, len(data1)),
        (1, 200, offsets[1], 0x4000, len(data2)),
        (2, 300, offsets[2], 0x8800, len(data3)),
        (gen.RESNAME_TYPE, gen.RESNAME_ID, offsets[3], 0, len(resname)),
    ], key=lambda r: (r[0], r[1]))
    for rtype, rid, off_, attr, size in records:
        m += struct.pack('<HIIHII', rtype, rid, off_, attr, size, 0)
    m += bytes(20 * 10)                        # 10 unused index slack slots
    m += bytes(2)                               # constant tail pad
    assert len(m) == map_size

    fork = bytes(header) + bytes(memo) + bytes(m) + data1 + data2 + data3 + resname
    assert len(fork) == fork_length
    return fork


def test_full_pipeline_hand_computed_fork():
    with tempfile.TemporaryDirectory() as d:
        src = _write_fixture(d)
        stmts = parser.parse(src, predefined={'RezIIGS': 1})
        entries = gen.generate(stmts)

        read_stmts = [s for s in stmts if isinstance(s, parser.ReadStmt)]
        read_entries = [e for e in entries if e.kind == 'read']
        assert len(read_stmts) == len(read_entries) == 1
        payload_path = os.path.join(d, read_stmts[0].filename.decode('latin-1'))
        with open(payload_path, 'rb') as f:
            raw = f.read()
        read_data = {(read_entries[0].rtype, read_entries[0].rid):
                     convert.convert_load(raw)}

        tuples = gen.to_emit_tuples(entries, read_data)
        built = emit.emit_fork(tuples, META)

    assert built == _expected_fork()


def test_cli_matches_library_pipeline():
    """gsasm.__main__.rez_main() (the `gsrez` CLI), invoked out-of-process
    exactly as an installed script would run, must reproduce the SAME bytes
    as the direct library call above -- the CLI-faithfulness half of
    packet R7's acceptance test, done corpus-free."""
    with tempfile.TemporaryDirectory() as d:
        src = _write_fixture(d)
        out = os.path.join(d, 'out.rsrc')
        argv = [sys.executable, '-c',
                'from gsasm.__main__ import rez_main; rez_main()',
                src, '-o', out,
                '--meta', "filetype=" + META['filetype'].decode('ascii'),
                '--meta', "creator=" + META['creator'].decode('ascii'),
                '--meta', "name=" + META['name'],
                '--meta', f"creation_mac_ts={META['creation_mac_ts']}"]
        proc = subprocess.run(argv, cwd=REPO, capture_output=True, text=True)
        assert proc.returncode == 0, proc.stdout + proc.stderr
        with open(out, 'rb') as f:
            cli_built = f.read()

    assert cli_built == _expected_fork()


def test_cli_read_dir_search_is_case_insensitive():
    """--read-dir search must find the `read` statement's file
    case-insensitively, in a directory SEPARATE from the source file (the
    shape work/rezbuildcheck.py relies on: archive sources live under
    ref/, built .Load files under work/link/rez/)."""
    with tempfile.TemporaryDirectory() as d:
        src_dir = os.path.join(d, 'src')
        read_dir = os.path.join(d, 'reads')
        os.makedirs(src_dir)
        os.makedirs(read_dir)
        src = os.path.join(src_dir, 'tiny.r')
        with open(src, 'wb') as f:
            f.write(SOURCE)
        # Deliberately upper-cased on disk vs. the source's "payload.bin".
        with open(os.path.join(read_dir, 'PAYLOAD.BIN'), 'wb') as f:
            f.write(PAYLOAD)

        out = os.path.join(d, 'out.rsrc')
        argv = [sys.executable, '-c',
                'from gsasm.__main__ import rez_main; rez_main()',
                src, '-o', out, '--read-dir', read_dir,
                '--meta', "filetype=" + META['filetype'].decode('ascii'),
                '--meta', "creator=" + META['creator'].decode('ascii'),
                '--meta', "name=" + META['name'],
                '--meta', f"creation_mac_ts={META['creation_mac_ts']}"]
        proc = subprocess.run(argv, cwd=REPO, capture_output=True, text=True)
        assert proc.returncode == 0, proc.stdout + proc.stderr
        with open(out, 'rb') as f:
            cli_built = f.read()

    assert cli_built == _expected_fork()


# ==========================================================================
# Adversarial-review regression (docs/REZ_REVIEW_2026-07-14.md, Low
# finding): malformed CLI numeric metadata (`--meta KEY=VAL`, `-t`) must
# exit as `SystemExit('gsrez: ...')` with the offending key/value included
# -- not a raw Python traceback (ValueError from int()/bytes.fromhex()).
# --------------------------------------------------------------------------
def _run_gsrez(argv, d):
    full = [sys.executable, '-c',
            'from gsasm.__main__ import rez_main; rez_main()'] + argv
    return subprocess.run(full, cwd=REPO, capture_output=True, text=True)


def test_cli_bad_meta_int_value_exits_cleanly():
    with tempfile.TemporaryDirectory() as d:
        src = _write_fixture(d)
        out = os.path.join(d, 'out.rsrc')
        proc = _run_gsrez([src, '-o', out, '--meta', 'creation_mac_ts=notanumber'], d)
    assert proc.returncode != 0
    assert 'Traceback' not in proc.stderr
    assert proc.stderr.strip().startswith('gsrez:')
    assert 'creation_mac_ts' in proc.stderr
    assert 'notanumber' in proc.stderr


def test_cli_bad_meta_hex_bytes_value_exits_cleanly():
    with tempfile.TemporaryDirectory() as d:
        src = _write_fixture(d)
        out = os.path.join(d, 'out.rsrc')
        proc = _run_gsrez([src, '-o', out, '--meta', 'filetype=0xZZ'], d)
    assert proc.returncode != 0
    assert 'Traceback' not in proc.stderr
    assert proc.stderr.strip().startswith('gsrez:')
    assert 'filetype' in proc.stderr


def test_cli_bad_filetype_hex_exits_cleanly():
    with tempfile.TemporaryDirectory() as d:
        src = _write_fixture(d)
        out = os.path.join(d, 'out.rsrc')
        proc = _run_gsrez([src, '-o', out, '-t', 'ZZ'], d)
    assert proc.returncode != 0
    assert 'Traceback' not in proc.stderr
    assert proc.stderr.strip().startswith('gsrez:')
    assert 'ZZ' in proc.stderr


_TESTS = [(n, f) for n, f in sorted(globals().items())
          if n.startswith('test_') and callable(f)]


if __name__ == '__main__':
    failed = 0
    for name, fn in _TESTS:
        try:
            fn()
        except AssertionError as exc:
            failed += 1
            print(f'FAIL {name}: {exc}')
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f'ERROR {name}: {exc!r}')
        else:
            print(f'ok   {name}')
    print(f'{len(_TESTS) - failed}/{len(_TESTS)} passed')
    sys.exit(1 if failed else 0)
