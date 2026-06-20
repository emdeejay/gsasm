"""CLI entry points for gsasm (assembler) and gslink (linker)."""

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
    off = 0
    while off < len(load_bytes):
        h = omf.parse_header(load_bytes[off:])
        if h["BYTECNT"] == 0:
            break
        nm = h["SEGNAME"].decode("mac_roman", "replace").strip()
        print(f"  {nm:24s}  {h['LENGTH']:#8x}  ({h['LENGTH']} bytes)")
        off += h["BYTECNT"]

    with open(outfile, "wb") as fh:
        fh.write(load_bytes)
    print(f"→ {outfile}  ({len(load_bytes)} bytes)")


if __name__ == "__main__":
    # allow `python -m gsasm` to run the assembler
    asm_main()
