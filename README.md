# gsasm

A clean-room Python reimplementation of the **MPW IIgs** assembler (`AsmIIgs`)
and **OMF v2 linker**, validated byte-for-byte against the original ROM 03 build.

The original Apple IIgs ROM 03 build chain ran on a 68k Mac under MPW Shell:
`AsmIIgs` assembled each module to an OMF object file, `LinkIIgs` linked the
objects into ROM bank images, and `MakeBinIIgs` split them into the final ROM
binary. Getting this to run today requires SheepShaver → a Mac OS 7 image → MPW
→ the GS cross-tools. `gsasm` replaces the assembler and single-file linker with
a pure-Python implementation — no emulator required.

## Validation

Every output is validated against captured artifacts from the original build:

- **Instruction encoding: 100%** — all ~96 000 instructions in the corpus encode
  to the exact same byte sequence as the original `.lst` files.
- **OMF objects: 61/61 link-identical** — for every source module, linking
  `gsasm`'s `.obj` with either ORCA/M (`iix link`) or the built-in Python linker
  produces an output **byte-identical** to linking the original AsmIIgs `.obj`.
  This is a strict semantic equivalence proof: both representations compute the
  same final load image despite cosmetic encoding differences in the OMF records.

## Install

```sh
pip install git+https://github.com/emdeejay/gsasm.git
```

Or install from a local clone in editable mode:

```sh
git clone https://github.com/emdeejay/gsasm.git
cd gsasm
pip install -e .
```

Requires Python 3.8+. No dependencies outside the standard library.

## CLI

### gsasm — assembler

```
gsasm <source.asm> [-I <incdir>] [-d KEY=VAL] [-o <out.obj>]
```

Assembles an MPW IIgs-dialect 65816 source file and writes an OMF v2 object file.

```sh
# assemble a single file
gsasm MyTool.asm -I ./includes -o MyTool.obj

# pass command-line defines (equivalent to the -d flag in MPW IIgs)
gsasm ROMDataMgr.asm -I ./includes -d Big=1

# multiple include directories
gsasm monitor.aii -I ./includes -I ./romsrc/Monitor
```

Include directories are searched in order for files referenced by `INCLUDE`
directives. The source file's own directory is not searched implicitly — add
`-I .` if you need it.

### gslink — linker

```
gslink <file.obj> [-o <out.load>]
```

Links a single multi-segment OMF object file. All `LEXPR`/`BEXPR`/`EXPR`
relocation records and `RELEXPR` (relative branch) records are fully evaluated
against the collected `GLOBAL` symbol table. The output is a single-segment OMF
load file with a flat body.

```sh
gslink MyTool.obj              # writes MyTool.out
gslink MyTool.obj -o MyTool.load
```

For multi-module linking (placing segments into ROM bank load images) see
`work/linkrom.py`, which implements the full `LinkIIgs`-equivalent bank layout.

## Python API

```python
from gsasm import asm, omf, link

# Assemble
a = asm.assemble("MyTool.asm", include_dirs=["./includes"], defines={"Big": 1})

# Emit OMF object
obj_bytes = omf.emit(a)
with open("MyTool.obj", "wb") as f:
    f.write(obj_bytes)

# Link to a load file
load_bytes = link.link(obj_bytes)
with open("MyTool.out", "wb") as f:
    f.write(load_bytes)

# Parse an existing OMF object
header = omf.parse_header(obj_bytes)
records, _ = omf.parse_records(
    obj_bytes, header["DISPDATA"], header["NUMLEN"], header["LABLEN"]
)
for offset, record_type, data in records:
    print(offset, record_type, data)
```

## Source dialect

`gsasm` implements the **MPW IIgs** (`AsmIIgs`) source dialect as used in the ROM 03
source tree. Notable features:

- **65816 instruction set** — full addressing-mode selection (dp/abs/long,
  cross-bank rules), `MVN`/`MVP`, `PEA`/`PEI`/`PER`
- **Macro engine** — `MACRO`/`ENDM`, positional parameters (`&1`…`&n`),
  keyword parameters, `WHILE`/`ENDWHILE`, `IF`/`ELSE`/`ENDIF`,
  `GOTO`/`AGO`/`AIF`, `MEXIT`, `ANOP`
- **Directives** — `PROC`/`END`, `ENTRY`/`EXPORT`/`IMPORT`, `RECORD`/`ENDR`,
  `WITH`, `DC`/`DS`, `ORG`, `INCLUDE`, `MSB ON/OFF`, `LONGA ON/OFF`,
  `LONGI ON/OFF`, `CASE ON/OFF`, `OBJEND`
- **Label scoping** — `@`-local labels scoped to the nearest enclosing non-`@`
  label (per MPW Assembler Reference p. 17); per-`PROC` namespaces
- **Expression evaluator** — MPW operator precedence, byte-extraction
  (`#<x`, `#>x`, `#^x`), shift operators, `MSB ON` character constants
- **OMF v2 emitter** — `CONST`/`LCONST`/`DS`, `LEXPR`/`BEXPR`/`EXPR`/`RELEXPR`,
  `GLOBAL`/`GEQU`, `SUPER` (efficient relocation bitmap), cross-segment and
  import references

## Module layout

```
gsasm/
  __init__.py
  __main__.py    CLI entry points (gsasm, gslink)
  m65816.py      65816 opcode table and addressing-mode encoding
  expr.py        MPW expression evaluator
  asm.py         Two-pass assembler: macro engine, symbol table, segment model
  omf.py         OMF v2 parser and emitter
  link.py        Single-file OMF linker
```

## Validation scripts (work/)

The `work/` directory contains scripts used during development to validate
`gsasm` output against the original build artifacts. They require you to supply
the original Apple ROM 03 source and include files separately (not included here
due to copyright).

| Script | What it does |
|---|---|
| `hfs.py` | Minimal HFS reader; extracts source from the original `.hfv` disk images |
| `bytecheck.py` | Validates instruction encoding against the `.lst` Object Code column |
| `objcheck.py` | Compares emitted `.obj` files record-by-record against the originals |
| `linkcheck.py` | Differential link oracle: links both original and `gsasm` `.obj` with the same linker and compares the load file. Use `--gs` to use the built-in Python linker instead of ORCA/M |
| `linkrom.py` | Full `LinkIIgs`-equivalent bank linker — places segments from all objects into the three ROM bank images (`ROM.FE`/`ROM.FC`/`ROM.FD`) |
| `buildrom.py` | Reconstructs `rom.03` from assembled + captured artifacts and verifies it byte-identical to the shipping ROM |
| `segdiff.py` | Per-segment OMF record diff between original and `gsasm` objects |
| `recmap.py` | Maps differing OMF records back to source lines via the `.lst` file |

To use these, populate:
- `work/romsrc/GS_ROM/` — the extracted ROM source tree (`.asm`/`.aii` + original `.obj`/`.lst`)
- `work/includes/` — the `AIIGSIncludes` system interfaces (`all.macros`, `E16.*`, `M16.*`)

The source and includes can be extracted from the original `ROMsource.hfv` disk
image using `work/hfs.py`.

## Background

The ROM 03 source was assembled with **AsmIIgs** (MPW IIgs) version 2.0 (circa
1989), an Apple-internal 65816 cross-assembler for MPW that produced OMF v2.0
object files. AsmIIgs is not publicly available. This project reverse-engineered
its behaviour
from the captured `.obj` and `.lst` files: given source + list files + object
files all captured from a known-good build, every discrepancy between `gsasm`'s
output and the original is a measurable bug, and every module that passes the
differential-link test is proven correct.

The OMF (Object Module Format) specification is documented in the _Apple IIgs
Toolbox Reference_ and the _Apple IIgs GS/OS Reference_.

## License

MIT — see [LICENSE](LICENSE).
