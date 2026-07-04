# Design docs — shared context (read first)

These designs extend gsasm into a full clean-room MPW IIgs toolchain to reproduce
System 6.0.1 shipping images byte-exact. See `../GSOS_MILESTONES.md` for the
roadmap. Each design here is written to be handed to an implementer (e.g. Sonnet)
who has this README as context.

## The existing codebase to reuse (do not reinvent)

| File | What it gives you |
|---|---|
| `gsasm/asm.py` | `AsmIIgs` assembler. `asm.assemble(path, INCS, defines=)` → an `Asm` with `.segs` (list of `Segment`, each with `.name`, `.items` = `('code', line, bytearray)` / `('ds', n, None)`), `.symbols` (NAME→value), `.symseg` (NAME→seg index), `.symtype`, `.exports`, `.entries`, `.fixups`, and `relink(seg_bases, extern)`. **Do not modify without re-validating the ROM** (see below). |
| `gsasm/omf.py` | OMF v2 read/write. `emit(asm)` → OMF object bytes; `parse_header(d)`, `parse_records(d, dispdata, numlen, lablen)` → `[(offset, name, detail)]` for CONST/LCONST/DS/RELOC/cRELOC/INTERSEG/cINTERSEG/EXPR/LEXPR/BEXPR/RELEXPR/GLOBAL/GEQU/END/SUPER. Record emitter helpers `_p2/_p4`, `emit_segment`. |
| `gsasm/link.py` | Minimal single-file OMF linker. `link(obj_bytes)` merges one object's segments → one load segment, resolving EXPR/LEXPR/RELEXPR. `_eval(ops, sym)` (OMF stack-machine evaluator), `_build_body(records, sym, seg_base)`, `_body_length(records)`, `_make_segment(...)`. **M2 generalizes this.** |
| `work/linkrom.py` | The ROM bank linker: assembles many objects, places segments per bank, builds a global symbol table, resolves every OMF reloc → bank image. `parse_map()`, `place()`, `emit_bank()`, `eval_expr()`, `BANKS` (the module→bank map). The proven multi-object relocation resolver. |
| `work/toolcheck.py` | The M1 tool harness. `link_module(roots)` (assemble→OMF→link with a full symbol table), `de_express(path)` (pull the CONST/LCONST code image out of an ExpressLoad'd tool), `golden(tool)`, `TOOLMAP`, `SUPER` walking. Model new `*check.py` harnesses on this. |
| `work/buildrom.py` | The M0 reference: assemble→flatten→byte-compare vs the real ROM. `flat(asm, segname)` pattern for extracting a segment's code image. |
| `work/hfs.py` | Reads HFS/disk images (for extracting golden files if `cadius` is unavailable). |

## OMF v2 primer (only what these tools need)

A **segment** = a 44+ byte header (`BYTECNT`, `LENGTH`, `KIND`, `ORG`, `NUMLEN`,
`LABLEN`, `BANKSIZE`, `DISPNAME`, `DISPDATA`, `SEGNAME`, `LOADNAME`) followed by
**records** terminated by `END` (0x00):

- `CONST` (0x01–0xDF) — inline literal bytes (count = opcode).
- `LCONST` (0xF2) — `numlen`-byte count + that many literal bytes (the code image).
- `DS` (0xF1) — `numlen`-byte count of zero-fill.
- `RELOC` (0xE2) / `cRELOC` (0xF5) — same-segment relocation: `(size, shift, offset, ref)`.
  The loader stores `(segbase + ref) shifted-by-shift` (size bytes) at `offset`.
- `INTERSEG` (0xE3) / `cINTERSEG` (0xF6) — cross-segment/-file relocation.
- `EXPR`/`LEXPR`/`BEXPR`/`RELEXPR` (0xEB/EC/ED/EE) — an expression to evaluate:
  `(size, ops)` where ops is a stack-machine program (`lit`, `sym83`/`sym85`,
  `op`, `loc`, `end`). LEXPR is used by `omf.emit` for cross-segment references.
- `GLOBAL` (0xE6) / `GEQU` (0xE7) — exported label / equate (name + value/expr).
- `SUPER` (0xF7) — compressed relocation dictionary used by **ExpressLoad load
  files** (not object files). `4-byte count + 1-byte type + page-list`. Types seen:
  **0** = RELOC size 2 shift 0; **1** = RELOC size 3 shift 0 (the `DC.L` address
  table); **27** = the high-word/bank relocs (`lda #^Label`). Page-list encoding:
  each byte is either a skip (`bit7 set` → skip `(b&0x7f)+1` pages) or a patch
  count (`b+1` offsets follow, each the low byte of an offset within the current
  256-byte page; advance one page after). `work/toolcheck.py` has a working walker.

**KIND** bits: bit0 = data segment; the load-file kinds (S16/TOL/etc.) set the
"load segment" attributes. Object files use relocatable segments (ORG 0); load
files are placed/relocated.

## Golden binaries (the source of truth)

- ROM: `ref/gsrom3/ROM 03/ROM03 original` (256K).
- System 6.0.1 disks: `ref/GSOS_6/System601_disks/System 6.0.1/*.2mg` (ProDOS
  2MG, extract with `cadius CATALOG/EXTRACTFILE`). Contain `/System/Tools/ToolNNN`,
  `/System/FSTs/*`, `/System/Drivers/*`, `/System/Desk.Accs/*`, `GS.OS`, `P8`, etc.
- Already extracted: `ref/GSOS_6/tool_bin/ToolNNN#BA0000` (13 toolsets).
- Source tree: `ref/GSOS_6/IIGS.601.SRC/` (the 6.0.1 GS/OS source; `GSToolbox`,
  `GS.OS`, `GSFirmware`, `A.U.G`, `Debugger`, …). **All under `ref/` = gitignored.**

Extraction one-liner (mirror in each harness):
`cadius EXTRACTFILE "<disk>.2mg" "/<VOL>/System/Drivers/<name>" ref/GSOS_6/<stage>/`

## Non-negotiable gotchas (learned the hard way)

1. **Never regress the ROM.** `gsasm/asm.py` + `gsasm/omf.py` are shared with the
   byte-exact ROM build. After ANY change to them run
   `python3 work/buildrom.py && python3 work/objcheck.py && python3 work/linkcheck.py`
   and confirm ROM byte-identical / 36-61 / 61-61. Revert on regression. Prefer
   putting new logic in new files (`gsasm/linkiigs.py`, `gsasm/expressload.py`).
2. **Cross-segment refs must go through OMF emit + link, not `flat()`+`relink`.**
   `flat()` bakes cross-segment `DC.L Label-1` as segment-relative literals (0 →
   `0xFFFFFFFF`); `omf.emit` turns them into LEXPR reloc records the linker resolves.
   This is *the* dispatch-table lever (M1). Corollary: the linker needs a **full**
   symbol table (segment names + every label at base+offset), not just GLOBALs —
   `link.py`'s minimal table misses internal cross-segment data labels.
3. **The tools are relocatable; compare in a consistent relocation frame.**
   The shipping `ToolNNN` LCONST holds base-0 placeholders + a `SUPER` dict.
   `lda #Label` (low word) is a word reloc (SUPER type 0); `lda #^Label` (bank) is
   SUPER type 27. Naive un-relocated comparison mismatches the bank bytes; a
   relocation-aware comparison (or emitting the same reloc dict) is required. Get
   the exact SUPER type→(size,shift) semantics from `ExpressLoad.src` (M4).
4. **Sizing drift is a real class.** Multi-object tools show gsasm emitting an
   instruction 1–2 bytes off (addressing-mode/length), cascading through address
   tables. These are per-module `m65816.py` fixes; use `work/recmap.py`/`segdiff.py`
   to map an image offset to a source instruction, fix, and revalidate the ROM.
5. **MPW line endings.** Source is classic-Mac CR. `asm.read_text` normalizes; if
   you read raw, `tr '\r' '\n'`.
6. **Build recipes are the map.** Each component's `.make`/`makefile`/`Build`
   script (MPW Shell) names the exact objects, link order, KIND/ORG, and output
   filename. Transcribe them (as `linkrom.BANKS` did) rather than guessing.

## House style
Small, composable functions; reuse `omf.py`/`link.py`/`linkrom.py`. New reusable
logic → `gsasm/`; thin validation drivers → `work/*check.py`. Match surrounding
code density and naming. Keep golden/ref data out of git.
