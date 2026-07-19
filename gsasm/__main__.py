"""CLI entry points for gsasm (assembler) and gslink (linker)."""
from __future__ import annotations

import argparse
import os
import sys


def asm_main():
    """gsasm — assemble an MPW IIgs source file to an OMF object file."""
    p = argparse.ArgumentParser(
        prog="gsasm",
        description="MPW IIgs-compatible assembler (65816, OMF v2).",
    )
    p.add_argument("source", help="source file (.asm or .aii)")
    p.add_argument(
        "-I", dest="incdirs", metavar="DIR", action="append", default=[],
        help="include search directory (may be repeated)",
    )
    p.add_argument(
        "-d", dest="defines", metavar="KEY=VAL", action="append", default=[],
        help="pre-define a symbol, e.g. -d Big=1 (may be repeated)",
    )
    p.add_argument(
        "-o", dest="output", metavar="FILE",
        help="output file (default: <source>.obj)",
    )
    args = p.parse_args()

    defines = {}
    for kv in args.defines:
        if "=" in kv:
            k, v = kv.split("=", 1)
            try:
                v = int(v, 0)
            except ValueError:
                pass
            defines[k] = v
        else:
            defines[kv] = 1

    src = args.source
    incdirs = args.incdirs or [os.path.dirname(os.path.abspath(src))]
    outfile = args.output or (src + ".obj")

    from gsasm import asm, omf

    try:
        a = asm.assemble(src, incdirs, defines=defines)
    except Exception as exc:
        print(f"gsasm: error: {exc}", file=sys.stderr)
        sys.exit(1)

    for e in a.errors:
        print(e, file=sys.stderr)
    if a.errors:
        sys.exit(1)

    obj = omf.emit(a)
    with open(outfile, "wb") as fh:
        fh.write(obj)

    # print segment summary
    for seg in a.segs:
        nm = seg.name or "(unnamed)"
        n = seg.length()
        print(f"  {nm:24s}  {n:#8x}  ({n} bytes)")
    print(f"→ {outfile}  ({len(obj)} bytes)")


def link_main():
    """gslink — link an OMF object file to a load file."""
    p = argparse.ArgumentParser(
        prog="gslink",
        description="OMF v2 linker: evaluates relocation records and produces a load file.",
    )
    p.add_argument("obj", help="OMF object file (.obj)")
    p.add_argument(
        "-o", dest="output", metavar="FILE",
        help="output file (default: <obj without .obj>.out, or <obj>.out)",
    )
    args = p.parse_args()

    objfile = args.obj
    if args.output:
        outfile = args.output
    elif objfile.endswith(".obj"):
        outfile = objfile[:-4] + ".out"
    else:
        outfile = objfile + ".out"

    from gsasm import link, omf

    with open(objfile, "rb") as fh:
        obj_bytes = fh.read()

    try:
        load_bytes = link.link(obj_bytes)
    except Exception as exc:
        print(f"gslink: error: {exc}", file=sys.stderr)
        sys.exit(1)

    # print segment summary from the output
    for seg in omf.iter_segments(load_bytes, records=False):
        h = seg["hdr"]
        nm = seg["name"]
        print(f"  {nm:24s}  {h['LENGTH']:#8x}  ({h['LENGTH']} bytes)")

    with open(outfile, "wb") as fh:
        fh.write(load_bytes)
    print(f"→ {outfile}  ({len(load_bytes)} bytes)")


def _resolve_read_file(name, search_dirs):
    """Case-insensitive filename search across `search_dirs`, in order
    (mirrors gsasm.rez.lexer's `#include` search-path convention: the
    including file's own directory, then each configured search directory,
    matched case-insensitively). Returns the resolved path, or None."""
    lname = name.lower()
    for d in search_dirs:
        if not d or not os.path.isdir(d):
            continue
        for entry in os.listdir(d):
            if entry.lower() == lname:
                return os.path.join(d, entry)
    return None


def _parse_meta_override(kv, defaults):
    """Parse one `--meta KEY=VAL` argument against `emit.DEFAULT_META`'s
    field types (bool / int / bytes / str). Raises SystemExit with a
    `gsrez:`-prefixed message on an unknown key or malformed value."""
    if "=" not in kv:
        raise SystemExit(f"gsrez: --meta expects KEY=VAL, got {kv!r}")
    key, val = kv.split("=", 1)
    if key not in defaults:
        raise SystemExit(f"gsrez: unknown --meta key {key!r} "
                          f"(known: {', '.join(sorted(defaults))})")
    default = defaults[key]
    if isinstance(default, bool):
        return key, val.lower() not in ("0", "false", "no", "")
    if isinstance(default, int):
        try:
            return key, int(val, 0)
        except ValueError:
            raise SystemExit(f"gsrez: --meta {key}: invalid integer value "
                              f"{val!r}")
    if isinstance(default, bytes):
        # An explicit `0x` prefix means hex bytes; anything else is taken
        # literally (encoded latin-1). Guessing "looks like hex" from
        # content alone would be ambiguous -- e.g. a 4-character creator
        # like "ABCD" is simultaneously valid hex (2 bytes) and a valid
        # literal (4 bytes) -- so an explicit marker is required instead.
        if val[:2].lower() == "0x":
            try:
                return key, bytes.fromhex(val[2:])
            except ValueError:
                raise SystemExit(f"gsrez: --meta {key}: invalid hex value "
                                  f"{val!r}")
        return key, val.encode("latin-1")
    return key, val


def rez_main():
    """gsrez — compile an Apple IIgs Rez `.r` source into a raw resource-fork
    image (docs/design/rez.md, milestone M7; replaces MPW `RezIIgs`).

    Mirrors the Sys.Resources makefile's `reziigs -rd sys.resources.r -o
    SYS.RESOURCES -t "F9  "` invocation as:

        gsrez sys.resources.r -o SYS.RESOURCES -t F9

    Pipeline: `gsasm.rez.parser.parse()` (always predefining `RezIIGS=1`,
    exactly as the real RezIIgs tool predefines it — see
    `gsasm/rez/lexer.py`'s `_Preprocessor.__init__` docstring: this gates
    the null-longint array terminator some type templates need) ->
    `gsasm.rez.gen.generate()` -> resolve every `read` statement's file
    (searched case-insensitively across each `--read-dir`, in order, then
    the source file's own directory) through `gsasm.rez.convert.
    convert_load()` -> `gsasm.rez.gen.to_emit_tuples()` ->
    `gsasm.rez.emit.emit_fork()` -> write the raw fork bytes to `-o`.

    Output is the RAW RESOURCE-FORK IMAGE ONLY: packaging it together with
    a (typically empty) data fork into one dual-fork disk file is out of
    scope here (see e.g. a2til's `Volume.write_file(..., resource=...)` for
    that step).

    Fork metadata (docs/design/rez.md "Golden fork format", `gsasm/rez/
    emit.py`'s `DEFAULT_META`): this CLI keeps HONEST, non-golden defaults
    (creator `'pdos'`; a zero memo timestamp; no file type set) rather than
    guessing at a specific captured file's undocumented bytes -- reproducing
    one archival fork byte-exact (its name, creation timestamp, ...) is a
    HARNESS's job (`work/rezbuildcheck.py`), done through `-t`/`-c`/`--meta`
    or by calling `gsasm.rez.emit.emit_fork()` directly as a library.
    """
    p = argparse.ArgumentParser(
        prog="gsrez",
        description="Rez resource compiler (Apple IIgs resource-fork image).",
    )
    p.add_argument("source", help="Rez source file (.r/.rez/.rii)")
    p.add_argument(
        "-I", dest="incdirs", metavar="DIR", action="append", default=[],
        help="#include search directory (may be repeated)",
    )
    p.add_argument(
        "-o", dest="output", metavar="FILE",
        help="output file (default: <source>.rsrc)",
    )
    p.add_argument(
        "-t", "--filetype", dest="filetype", metavar="TT",
        help="2-hex-digit ProDOS file type, e.g. -t F9 (default: unset)",
    )
    p.add_argument(
        "-c", "--creator", dest="creator", default="pdos", metavar="CCCC",
        help='4-character creator (default: "pdos", matching every '
             'observed golden fork)',
    )
    p.add_argument(
        "--read-dir", dest="read_dirs", metavar="DIR", action="append",
        default=[],
        help="directory to search for `read` statement files (may be "
             "repeated; searched before the source file's own directory)",
    )
    p.add_argument(
        "--meta", dest="meta_overrides", metavar="KEY=VAL", action="append",
        default=[],
        help="override a gsasm.rez.emit fork-metadata field (may be "
             "repeated), e.g. --meta creation_mac_ts=2819554517",
    )
    args = p.parse_args()

    from gsasm.rez import lexer, parser as rez_parser, gen, emit, convert

    try:
        stmts = rez_parser.parse(args.source, include_dirs=args.incdirs,
                                  predefined={"RezIIGS": 1})
    except (lexer.LexError, rez_parser.ParseError) as exc:
        print(f"gsrez: error: {exc}", file=sys.stderr)
        sys.exit(1)

    try:
        entries = gen.generate(stmts)
    except gen.GenError as exc:
        print(f"gsrez: error: {exc}", file=sys.stderr)
        sys.exit(1)

    src_dir = os.path.dirname(os.path.abspath(args.source))
    search_dirs = args.read_dirs + [src_dir]

    read_stmts = [s for s in stmts if isinstance(s, rez_parser.ReadStmt)]
    read_entries = [e for e in entries if e.kind == "read"]
    # generate() appends exactly one 'read' GenEntry per ReadStmt, in the
    # same source order (see gen.py's "Public API" docstring) -- zipping
    # them pairs each statement with its resolved (rtype, rid) without
    # reimplementing gen.py's own (private) id-expression evaluator here.
    assert len(read_stmts) == len(read_entries)

    read_data = {}
    for stmt, entry in zip(read_stmts, read_entries):
        filename = stmt.filename.decode("latin-1")
        path = _resolve_read_file(filename, search_dirs)
        if path is None:
            print(f"gsrez: error: {stmt.file}:{stmt.line}: read file not "
                  f"found (case-insensitively) in search path: "
                  f"{filename!r}", file=sys.stderr)
            sys.exit(1)
        with open(path, "rb") as fh:
            raw = fh.read()
        read_data[(entry.rtype, entry.rid)] = convert.convert_load(raw)

    try:
        tuples = gen.to_emit_tuples(entries, read_data)
    except gen.GenError as exc:
        print(f"gsrez: error: {exc}", file=sys.stderr)
        sys.exit(1)

    meta = {"creator": args.creator}
    if args.filetype:
        try:
            filetype_val = int(args.filetype, 16)
        except ValueError:
            raise SystemExit(f"gsrez: -t/--filetype: invalid hex value "
                              f"{args.filetype!r}")
        meta["filetype"] = emit.format_filetype(filetype_val)
    for kv in args.meta_overrides:
        key, val = _parse_meta_override(kv, emit.DEFAULT_META)
        meta[key] = val

    try:
        fork = emit.emit_fork(tuples, meta)
    except ValueError as exc:
        print(f"gsrez: error: {exc}", file=sys.stderr)
        sys.exit(1)

    outfile = args.output or (args.source + ".rsrc")
    with open(outfile, "wb") as fh:
        fh.write(fork)
    print(f"  {len(tuples)} resource(s)")
    print(f"→ {outfile}  ({len(fork)} bytes)")


if __name__ == "__main__":
    # allow `python -m gsasm` to run the assembler
    asm_main()
