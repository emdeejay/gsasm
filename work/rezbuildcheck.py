#!/usr/bin/env python3
"""rezbuildcheck.py — M7/R7: the Rez-milestone done-gate.

Builds the golden `Sys.Resources` resource fork byte-exact from source
through the PUBLIC library pipeline (`gsasm.rez.{lexer,parser,gen,convert,
emit}`), then separately through the `gsrez` CLI (`gsasm.__main__.rez_main`,
invoked out-of-process so it exercises the exact same argv/argparse/stdout
path an installed script would), and byte-compares BOTH results against the
golden fork extracted by `work/rezcheck.py`.

Reuses, rather than duplicates, the two harnesses this packet's brief calls
out by name:
  - `work/rezloadcheck.py` builds (and byte-verifies) the four embedded
    `.Load` code resources from the archive `.aii`/`.mac` sources; this
    module imports its `_install_dialect_shims`/`assemble`/`link_load`/
    `TARGETS` directly rather than reassembling that recipe.
  - `work/rezemitcheck.py`'s `_meta_from_golden` recovers the exact
    `emit.py` `meta` dict (name/filetype/creator/timestamp/...) straight
    back out of the golden fork's own memo bytes -- reused verbatim so the
    fork this module builds is compared apples-to-apples against the same
    archival file.

`build_sysresources_fork()` is also the function `work/diskcheck.py` wires
in (lazily, at call time -- see its module docstring) as Sys.Resources'
resource-fork builder for the M8 disk-image reconstruction, once this
packet flips it from REZ/substitute to REZ/buildable.

PASS = both the library call and the `gsrez` subprocess reproduce the
golden 24,337-byte Sys.Resources fork byte-for-byte.

Usage: python3 work/rezbuildcheck.py
"""
import os
import subprocess
import sys

from _common import (
    ROOT as REPO,
    WORK as HERE,
    ensure_repo_on_path,
    first_diff as _first_diff,
    rincludes,
    sysresources_rez,
    sysresources_root,
)
ensure_repo_on_path(HERE)

from gsasm import omf as _omf                      # noqa: E402
from gsasm.rez import parser, gen, emit, convert    # noqa: E402
import rezcheck as rc                                # noqa: E402
import rezemitcheck as rec                           # noqa: E402
import rezloadcheck as rlc                           # noqa: E402

SRC_DIR = sysresources_root(abs_path=True)
SRC_R = sysresources_rez(abs_path=True)
INCS = rincludes(abs_path=True)
SYSRES_DISK_PATH = f'{rc.dc.V}/System/System.Setup/Sys.Resources'


def _ensure_loads_built():
    """Build (and byte-verify) the four embedded `.Load` files by calling
    rezloadcheck's own builder loop -- reused, not duplicated. Returns the
    directory the `.Load` files were written to (`rezloadcheck.OUTDIR`)."""
    ok = rlc.main()
    if not ok:
        raise RuntimeError('rezloadcheck did not build the four .Load '
                            'files byte-exact; Sys.Resources cannot be '
                            'reproduced (see the FAIL lines above)')
    return rlc.OUTDIR


def _read_data_from_loads(load_dir):
    """{(rtype, rid): convert_load(bytes)} for the four `read` statements,
    reading the already-built `.Load` files back from `load_dir`."""
    out = {}
    for _srcname, loadname, rtype, rid, _segname, _kind in rlc.TARGETS:
        with open(os.path.join(load_dir, loadname), 'rb') as fh:
            raw = fh.read()
        out[(rtype, rid)] = convert.convert_load(raw)
    return out


def _golden():
    return rc.golden_fork(SYSRES_DISK_PATH)


def build_sysresources_fork():
    """Build the Sys.Resources resource fork byte-exact via the library
    pipeline, using the golden meta values recovered from the golden fork
    itself (exactly like `work/rezemitcheck.py`'s round-trip check). This
    is the single function both this harness and (once wired) `work/
    diskcheck.py`'s REZ builder registry call. Returns `bytes`."""
    load_dir = _ensure_loads_built()
    read_data = _read_data_from_loads(load_dir)

    stmts = parser.parse(SRC_R, include_dirs=INCS, predefined={'RezIIGS': 1})
    entries = gen.generate(stmts)
    tuples = gen.to_emit_tuples(entries, read_data)

    golden = _golden()
    meta = rec._meta_from_golden(golden)
    return emit.emit_fork(tuples, meta)


# ---------------------------------------------------------------------------
# CLI path: invoke gsasm.__main__.rez_main() out-of-process (so it runs the
# real argparse/sys.argv/stdout surface an installed `gsrez` script would),
# with --meta overrides supplying the same golden values `build_
# sysresources_fork()` recovers via rezemitcheck -- proving the CLI is a
# faithful wrapper around the library, not a second, divergent codepath.
# ---------------------------------------------------------------------------
_CLI_BOOTSTRAP = 'from gsasm.__main__ import rez_main; rez_main()'


def _run_cli(load_dir, out_path, meta):
    argv = [sys.executable, '-c', _CLI_BOOTSTRAP,
            SRC_R,
            '-I', INCS[0],
            '--read-dir', load_dir,
            '-o', out_path,
            '-t', meta['filetype'].decode('ascii').strip() or '00',
            '-c', meta['creator'].decode('latin-1'),
            '--meta', f"name={meta['name']}",
            '--meta', f"creation_mac_ts={meta['creation_mac_ts']}"]
    proc = subprocess.run(argv, cwd=REPO, capture_output=True, text=True)
    return proc


def main():
    golden = _golden()
    print(f'golden Sys.Resources: {len(golden.raw)} bytes, '
          f'{len(golden.used)} resources')

    # -- 1. library pipeline -------------------------------------------------
    lib_ok = False
    try:
        built = build_sysresources_fork()
    except Exception as exc:                              # noqa: BLE001
        print(f'FAIL library pipeline raised {type(exc).__name__}: {exc}')
        built = b''
    else:
        report = rc.compare(golden.raw, built)
        lib_ok = report['ok'] and built == golden.raw
        print(f'{"PASS" if lib_ok else "FAIL"} library pipeline: '
              f'built={len(built)}B golden={len(golden.raw)}B '
              f'header_diff={report["header_diff"]} '
              f'memo_diff={report["memo_diff"]} map_diff={report["map_diff"]} '
              f'match={report["n_match"]}/{report["n_resources"]} '
              f'diff={report["n_diff"]} missing={report["n_missing"]} '
              f'extra={report["n_extra"]}')
        if not lib_ok and built != golden.raw:
            d = _first_diff(built, golden.raw)
            print(f'    first raw byte diff at offset {d}: '
                  f'golden={golden.raw[d:d+8].hex()} built={built[d:d+8].hex()}')

    # -- 2. gsrez CLI (subprocess), --meta-driven to the same golden values --
    cli_ok = False
    meta = rec._meta_from_golden(golden)
    load_dir = rlc.OUTDIR   # already built by build_sysresources_fork() above
    out_path = os.path.join(HERE, 'link', 'rez', 'gsrez_cli_sysresources.rsrc')
    proc = _run_cli(load_dir, out_path, meta)
    if proc.returncode != 0:
        print('FAIL gsrez CLI exited non-zero:')
        print('    ' + (proc.stdout + proc.stderr).replace('\n', '\n    '))
    elif not os.path.exists(out_path):
        print(f'FAIL gsrez CLI did not produce {out_path}')
    else:
        with open(out_path, 'rb') as fh:
            cli_built = fh.read()
        report = rc.compare(golden.raw, cli_built)
        cli_ok = report['ok'] and cli_built == golden.raw
        print(f'{"PASS" if cli_ok else "FAIL"} gsrez CLI: '
              f'built={len(cli_built)}B golden={len(golden.raw)}B '
              f'match={report["n_match"]}/{report["n_resources"]} '
              f'diff={report["n_diff"]} missing={report["n_missing"]} '
              f'extra={report["n_extra"]}')
        if not cli_ok and cli_built != golden.raw:
            d = _first_diff(cli_built, golden.raw)
            print(f'    first raw byte diff at offset {d}: '
                  f'golden={golden.raw[d:d+8].hex()} built={cli_built[d:d+8].hex()}')
        # the CLI must be a faithful wrapper: same bytes as the library call.
        if lib_ok and cli_ok and cli_built != built:
            print('WARNING: library and CLI both matched golden but '
                  'DIFFER from each other -- should be impossible')

    ok = lib_ok and cli_ok
    n_exact_bytes = len(golden.raw) if ok else 0
    print()
    print(f'{"PASS" if ok else "FAIL"} rezbuildcheck: Sys.Resources '
          f'byte-exact (library={"yes" if lib_ok else "no"}, '
          f'cli={"yes" if cli_ok else "no"}) '
          f'REZ_SYSRESOURCES_BYTES_EXACT {n_exact_bytes}')
    return ok


if __name__ == '__main__':
    sys.exit(0 if main() else 1)
