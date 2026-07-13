# gsasm

A clean-room Python reimplementation of the **MPW IIgs cross-development
toolchain** — the `AsmIIgs` assembler, `LinkIIgs` linker, the
`MakeBinIIgs`/`OverlayIIgs`/`catenate` packagers, and the `ExpressLoad`
relinker — validated byte-for-byte against the Apple IIgs ROM 03 and the
GS/OS System 6.0.1 shipping binaries.

Apple built the IIgs ROM and GS/OS on a 68k Mac under MPW Shell. Running that
chain today means SheepShaver → a Mac OS 7 image → MPW → the GS cross-tools.
`gsasm` replaces it with pure Python — no emulator, no dependencies outside
the standard library.

## Results

Rebuilt from the original source and verified byte-identical to the shipping
binaries:

- **ROM 03** — all 262,144 bytes
- **All 7 buildable FSTs** (ProDOS, HFS, Char, High Sierra, DOS 3.3, Pascal,
  MS-DOS) and **11 of 12 device drivers**
- **`prodos`, `Start.GS.OS`, `Error.Msg`, the GS/OS Loader**, and 15 of the
  27 System 6.0.1 files the disk harness rebuilds
- **Instruction encoding: 100%** — every instruction in the ~97,000-line
  corpus encodes to the same bytes as the original listings
- **61/61 ROM objects link-identical** — for every module, linking `gsasm`'s
  object or Apple's original produces the same load image

`GS.OS` itself reaches 38,711 of 38,805 bytes (99.76%); the residual 94 bytes
reference symbols that exist nowhere in the source archive, so a byte-exact
build is provably out of reach from these sources. The other shortfalls have
similarly settled causes (a source-revision skew, a converter whose output
isn't a function of its input, missing sources). The full accounting, with
evidence for each limit, is in [docs/RESULTS.md](docs/RESULTS.md).

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

Requires Python 3.9+. No dependencies outside the standard library.

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

For multi-object linking — libraries, segment naming/placement, the
`LinkIIgs -apw` recipe used by the GS/OS build scripts — use
`gsasm/linkiigs.py`; for ROM bank layout see `work/linkrom.py`.

## Python API

```python
from gsasm import asm, omf, link

# Assemble (include paths are positional; defines optional)
a = asm.assemble("MyTool.asm", ["./includes"], defines={"Big": 1})
if a.errors:
    raise SystemExit("\n".join(a.errors))

# Emit an OMF object
obj_bytes = omf.emit(a)
with open("MyTool.obj", "wb") as f:
    f.write(obj_bytes)

# Link to a load file
load_bytes = link.link(obj_bytes)
with open("MyTool.out", "wb") as f:
    f.write(load_bytes)

# Parse an existing OMF file
header = omf.parse_header(obj_bytes)
records, _ = omf.parse_records(obj_bytes, header["DISPDATA"],
                               numlen=header["NUMLEN"])
for offset, record_type, data in records:
    print(offset, record_type, data)
```

## Source dialect

`gsasm` implements the **MPW IIgs** (`AsmIIgs`) source dialect as used in the
ROM 03 and System 6.0.1 source trees. Notable features:

- **65816 instruction set** — full addressing-mode selection (dp/abs/long,
  cross-bank rules), `MVN`/`MVP`, `PEA`/`PEI`/`PER`
- **Macro engine** — `MACRO`/`ENDM`, positional parameters (`&1`…`&n`),
  keyword parameters, `WHILE`/`ENDWHILE`, `IF`/`ELSE`/`ENDIF`,
  `GOTO`/`AGO`/`AIF`, `MEXIT`, `ANOP`, builtins (`&sysdate`, `&systime`, …)
- **Directives** — `PROC` (with `TEMPORG`/`ENTRY`/`EXPORT` forms),
  `ENTRY`/`EXPORT`/`IMPORT`, `RECORD`/`ENDR` (templates and typed `DS`
  instances), `WITH`, `DC`/`DCB`/`DS`, `ORG`, `SEG`, `INCLUDE`,
  `MSB`/`LONGA`/`LONGI`/`CASE ON|OFF`, `OBJEND`
- **Label scoping** — `@`-local labels scoped to the nearest enclosing
  non-`@` label (per MPW Assembler Reference p. 17); per-`PROC` namespaces
- **Expression evaluator** — MPW operator precedence, byte extraction
  (`#<x`, `#>x`, `#^x`), shifts, the `≈` one's-complement operator,
  `MSB ON` character constants
- **OMF v2 emitter** — `CONST`/`LCONST`/`DS`, `LEXPR`/`BEXPR`/`EXPR`/`RELEXPR`,
  `GLOBAL`/`GEQU`, `SUPER` relocation dictionaries, cross-segment and import
  references, faithful record chunking

Sources are read as MacRoman with classic-Mac line endings, matching real MPW
files.

## Module layout

```
gsasm/
  __init__.py
  __main__.py       CLI entry points (gsasm, gslink)
  m65816.py         65816 opcode table and addressing-mode encoding
  expr.py           MPW expression evaluator
  asm.py            Multi-pass assembler: macro engine, symbols, segments
  omf.py            OMF v2 parser and emitter
  link.py           Single-object OMF linker
  linkiigs.py       General LinkIIgs: multi-object, libraries, -apw recipe,
                    segment naming and placement
  makebin.py        MakeBinIIgs / OverlayIIgs / catenate packaging
  expressload.py    ExpressLoad relinker (fast-load format + SUPER records)
```

## Tests

```sh
python3 tests/run_fixtures.py
```

The `tests/` fixture suite runs on a bare checkout — no reference material
needed. Each fixture is an original source pinning one discovered dialect or
OMF behavior, with expected bytes minted only while the full golden-corpus
validation passes. See [tests/README.md](tests/README.md) for how blessing
works and why the expected bytes are trustworthy.

## Validation harnesses (work/)

The `work/` scripts are the differential-validation harnesses used during
development. They compare rebuilt output against captured artifacts of the
original build — Apple's source, listings, objects, and shipping binaries —
which are copyrighted and **not included** (everything under `ref/` and
`work/romsrc/` is gitignored; supply your own).

| Script | What it validates |
|---|---|
| `gate.py` | Runs every harness below against a committed baseline; fails on any regression |
| `buildrom.py` | Reconstructs `rom.03` and verifies it byte-identical to the shipping ROM |
| `bytecheck.py` | Instruction encoding against the `.lst` Object Code column |
| `objcheck.py` | Emitted `.obj` files record-by-record against the originals |
| `linkcheck.py` | Differential link: original vs `gsasm` object through the same linker |
| `toolcheck.py` | `System/Tools/ToolNNN` toolsets vs the shipping files |
| `fstcheck.py` | `System/FSTs/*` vs the shipping files |
| `drivercheck.py` | `System/Drivers/*` vs the shipping files |
| `kernelcheck.py` | `prodos`, `GS.OS`, `Start.GS.OS`, `Error.Msg`, P8 |
| `diskcheck.py` | Whole System 6.0.1 disk-image files (needs the `a2til` sibling tools; set `A2TIL_PATH`) |
| `linkrom.py` | The `LinkIIgs`-equivalent ROM bank layout |
| `hfs.py` | Minimal HFS reader for extracting sources from `.hfv` images |

## Background

The ROM 03 and System 6.0.1 sources were assembled with **AsmIIgs** (circa
1989–1993), Apple's 65816 cross-assembler for MPW, distributed through APDA
with the rest of the MPW IIgs cross-development tools. The tools' own source
code was never published, so this project is a clean-room reimplementation:
behaviour was reverse-engineered from captured `.obj` and `.lst` files. Given
source, listings, and objects from a known-good build, every discrepancy
between `gsasm`'s output and the original is a measurable bug, and every
target that passes a differential comparison is proven correct rather than
assumed. The same method then extended, tool by tool, to the rest of the MPW
IIgs chain until whole shipping binaries reproduced.

The OMF (Object Module Format) specification is documented in the _Apple IIgs
Toolbox Reference_ and the _Apple IIgs GS/OS Reference_.

## License

MIT — see [LICENSE](LICENSE).
