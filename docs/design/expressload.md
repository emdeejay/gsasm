# Design: ExpressLoad relinker (M4)

**Status: implemented** (`gsasm/expressload.py`). The case-B relocation
encoding discussed at the end of this doc was believed to be an
unreproducible closed-toolchain quirk; that conclusion was **overturned in
R9** (2026-07) — it is the source expression's own addend, and the rule is
now implemented for the single-segment ExpressLoad path (`_scan_case_b`).
**Replaces:** MPW `ExpressLoad`. **Unlocks:** byte-exact `System/Tools/ToolNNN`
(M1) and the GS/OS `Loader2.0`. Read `README.md` first.

**The authoritative spec is in the tree** — implement from it, do not reverse-
engineer from scratch:
- `GS.OS/Loader/ExpressLoad/ExpressLoad.src` (the tool itself, AsmIIgs)
- `GS.OS/Loader/ExpressLoad/ExpressLoad.Macros`, `ExpressLoad.Data`
- `GS.OS/MakeFiles/make.ExpressLoad` (how it's built/invoked)

## What it does
Converts a plain OMF load file (multi-segment, from M2 in **segmented** mode) into
the ExpressLoad "fast-load" format the System Loader recognizes:
- a leading **`~ExpressLoad`** directory segment (KIND 0x8001) describing the other
  segments so the loader can load them quickly, and
- the load segments reorganized with their relocation dictionaries rewritten as
  compressed **`SUPER`** records instead of individual `RELOC`/`INTERSEG` records.

The **inverse already exists**: `work/toolcheck.py::de_express` pulls the CONST/
LCONST image back out, and its SUPER walker decodes the page-lists. Use those as
the oracle — `de_express(expressload(x))` must round-trip.

## What we already know about the format (from the golden `Tool022`)
A shipping tool = `[~ExpressLoad seg]` + `[main load seg]`. The `main` segment is:
- one big `LCONST` = the full segment-relative code image (base-0 placeholders), then
- one or more `SUPER` records = the relocation dictionary, by type:
  - **type 0** — RELOC size 2, shift 0 (word relocs, e.g. `lda #Label` low word)
  - **type 1** — RELOC size 3, shift 0 (the `DC.L routine-1` dispatch table)
  - **type 27** — the high-word/bank relocs (`lda #^Label`)
  - (types 2–25 = INTERSEG variants; may appear in multi-segment tools)
- `SUPER` page-list encoding: `4-byte count + 1-byte type`, then a byte stream where
  each byte is a **skip** (`bit7 set` → skip `(b&0x7f)+1` pages) or a **patch count**
  (`b+1` offset bytes follow, each an offset within the current 256-byte page;
  advance one page after). Working reader in `toolcheck.py`.
- **Confirm from `ExpressLoad.src`:** the exact `~ExpressLoad` directory layout, the
  full SUPER type table (esp. type 27's size/shift), segment ordering/alignment, and
  whether/what padding is inserted. Do not ship guesses on type 27.

## Algorithm
```
expressload(load_file) -> expressload_file
  segs = parse segments of load_file (from M2 segmented output)
  # 1. rewrite each segment's RELOC/INTERSEG/EXPR reloc records as SUPER groups:
  for seg in segs:
      relocs = collect (offset, size, shift, kind) from seg records
      group by (super_type)                       # per ExpressLoad.src's table
      for each group: emit SUPER(type, page_list(sorted offsets))
      keep the LCONST (base-0 image) as-is
  # 2. build the ~ExpressLoad directory segment from the segment table
  # 3. write ~ExpressLoad seg first, then the rewritten segments, in the tool's order
```
`page_list(offsets)`: bucket offsets into 256-byte pages; emit skip/patch-count
bytes as decoded above (inverse of the walker).

## Integration
- `gsasm/expressload.py`: `expressload(load_file_bytes) -> bytes`,
  `de_express(bytes)` (move the working one from `toolcheck.py` here),
  `parse_super(seg)` / `emit_super(type, offsets)`.
- Pipeline for a tool: `omf.emit` → `linkiigs.link(segmented)` →
  `expressload(...)` → compare vs `ref/GSOS_6/tool_bin/ToolNNN`.

## Validation & acceptance
- Round-trip: `de_express(expressload(L)) == de_express(golden)` for the code image.
- **Full byte-exact:** `expressload(linkiigs.link(scrap.objs))` == `Tool022` byte
  for byte (header + `~ExpressLoad` + LCONST + SUPER + END). Start with **Scrap /
  Tool022** (single object, smallest) — it's the M4 acceptance test.
- Then DialogMgr (Tool021), ListMgr (Tool028) — the other single-object tools.
- ROM unaffected (new code).

## Gotchas
- ExpressLoad reorganizes/aligns segments; segment order and any alignment padding
  must match `ExpressLoad.src`, or offsets shift.
- The `~ExpressLoad` header has KIND 0x8001 and its own LENGTH/DISPDATA — model it on
  the golden `Tool022` header exactly (parse it first with `omf.parse_header`).
- Get type-27's (size, shift) from `ExpressLoad.src`; the base-0-relocation
  experiment in the M1 notes showed guessing it is error-prone.
- Some tools are single-segment (`main` only); multi-segment tools (bigger managers)
  will exercise INTERSEG SUPER types — handle single-segment first, then generalize.

## Case-B relocation encoding — CONFIRMED and implemented (R9)

**Superseded finding.** This section originally concluded the case-B
standalone-RELOC flag was "internal LinkIIgs state" absent from the archive
and out of scope to reproduce (see "Original (superseded) analysis" below for
that reasoning, kept for the record). A source sweep (`docs/TODO.md` section
1) overturned it: **the flag is the source expression's own addend**, not
opaque linker state, and the rule is now implemented in
`gsasm/expressload.py::_scan_case_b`.

**The rule.** A relocation whose target expression carries addend bits >= 24
(out of segment-address range — e.g. the ModalDialog filterProc/hook-pointer
conventions `#Label+$80000000` / `#Label+$C0000000`, bit 31 / bit 30) cannot
be represented in a SUPER page list: a page-list patch only ever restores a
clean, <=24-bit segment-relative offset, never an out-of-range flag OR'd on
top. MPW's ExpressLoad converter recognises this and emits a standalone RELOC
(0xE2) instead, whose `relOffset` is the FULL, un-shifted 32-bit expression
value (flag bits included) — for BOTH halves of a far-pointer PEA pair (the
high-word `pea #^(Label+$80000000)` at shift=16 stores the SAME flagged value
as its low-word `pea #Label+$80000000` partner at shift=0, not the value
shifted right 16), and for an unpaired single shift-16 record (Tool027's `lda
#^(Label+$80000000)` style, no matching low-word half). All 9 golden flagged
case-B records map to exactly this source-level pattern — see `docs/TODO.md`'s
table for the source line of each.

**What the rule does NOT catch (and must not).** `_scan_case_b` restricts
itself to `(size, shift)` in `{(2, 0), (2, 16)}` — SUPER types 0 and 27, the
only two the golden corpus ever shows flagged (`work/reloc_survey.py`
hypothesis test 2). It deliberately excludes the ubiquitous `dc.l routine-1`
dispatch-table idiom (`(size, shift) = (4, 0)`, SUPER type 1): that idiom's
"-1" is OMF-encoded as `ADD lit=0xFFFFFFFF` (two's-complement), and if the
referenced routine symbol is unresolved for an unrelated reason its evaluated
target ALSO lands at 0xFFFFFFFF — a large 32-bit value with no relation to a
deliberate flagged addend. An earlier draft of this fix gated only on the
*evaluated* value exceeding 24 bits and produced exactly this false positive
against Tool023/Tool027's (independently known, pre-existing) unresolved-
symbol residual; restricting to the two confirmed `(size, shift)` pairs closes
that hole without needing to special-case the literal's shape.

**Where the flag was previously lost.** The plain-load-file path (LinkIIgs
`-x`, no ExpressLoad — `work/rezloadcheck.py`'s Launcher.Load) already carried
the flagged addend through to its own standalone RELOC correctly (R6). The
ExpressLoad path lost it because `_scan_relocs` classified every relocation by
`(size, shift)` alone, with no magnitude check: a flagged far-pointer pair has
exactly the same `(size, shift)` as an ordinary `lda #Label` / `lda #^Label`
pair, so it was silently folded into the type-0 / type-27 SUPER groups instead
of staying standalone.

**Measured effect (`work/reloc_diag.py`, `work/gate.py --full`
`disk_logical_exact`):**

| Tool | Before | After | Notes |
|---|---|---|---|
| Tool014 (WindMgr) | 29,998/30,018 B (−20 B, reloc-dict only) | **30,018/30,018 — byte-exact** | sole residual was the far-pointer pair |
| Tool027 (FontMgr) | 13,009/13,019 B (−10 B reloc dict + 2 code-image bytes) | 13,017/13,019 (2 bytes) | reloc dict now exact; remaining 2 bytes are a pre-existing, unrelated code-image residual (`work/diskbuilders/expressload_files.py`) |
| Tool023 (StdFile) | 16,970/17,012 B (missing 4 standalone RELOCs) | 17,010/17,012 | one pair now correct (`0x80002a29`); the other pair's *value* is wrong (`0xC0000000` instead of `0xC00022ec`) because `GETFILTER` resolves unresolved in gsasm's merged symbol table — a pre-existing, unrelated linkiigs scoping bug this packet did not fix, present before this rule as one of the tool's documented "4 code-image diffs" |

`disk_logical_exact` (the full on-disk-file byte-exact count, `work/gate.py
--full`) improved from 16/28 to 17/28 — Tool014 is the one file that flips
fully exact.

**What remains out of scope.** TS2/TS3 (`work/diskbuilders/toolsets.py`) and
the combined Tool.Setup harness (`work/toolsetup_probe.py`) build through
`expressload(..., opts={'multiseg': True})`. That path has never emitted ANY
standalone reloc record (case A or case B) — it only ever produces SUPER
groups — a separate, pre-existing gap from the one this packet closes (which
is scoped to the single-segment `expressload()` path, `_scan_case_b`'s only
caller). TS3's golden case-B record (`docs/TODO.md`'s table, `WindMgr/
NewCalls.asm:6465` again, reassembled into `Patch3/ts3.makeout`) is therefore
still SUPER-ized in gsasm's output, and TS2/TS3/Tool.Setup remain non-byte-
exact for that reason plus the separately-documented symbol-scoping residual
(`toolsets.py`'s module docstring). Extending standalone-reloc support
(case A and case B both) to the multi-segment path is future work.

**Scope re-check (2026-07-18) — Tool016 root-caused, and the earlier framing
was WRONG.** The `tool_bytes` residual was 554 B, dominated by **Tool016
ControlMgr (451 B)**. An earlier draft of this note called Tool016 a
"link-order/value frontier" where "gsasm computes different addresses than gold
(e.g. `0x1017 LDX #$30C9` vs gold `#$0000`)." That was a mis-diagnosis. A full
byte-by-byte decomposition (`work/tool016_diag.py`) proves **every one of the 451
bytes is a segmentation / harness artifact — not a single value error**. gsasm
assembles ControlMgr *byte-exact per segment*.

ControlMgr ships as a **four-segment** ExpressLoad load file, not one flat blob:
`main` (KIND 0) + `StatText` (KIND 0) + `~JumpTable` (KIND 2, linker-generated) +
`Pics` (KIND 0x8000, **dynamic**). The old toolcheck entry flat-linked all 8
objects into one segment and compared against `de_express(gold)` = the four
segments concatenated. On that basis the 451 diffs decompose, with **zero
unclassified residue**, into three mechanical causes:
- **8 B** — 2 `cINTERSEG` far-pointers in `main` to the StatText/Pics segments;
  gold defers them to load time, gsasm's flat merge bakes the merged-image offset.
- **~154 B** — every StatText/Pics intra-segment word reloc is off by *exactly*
  its segment's base in the merged image (`0x30c9` / `0x355f`), because gsasm
  concatenates while gold keeps them separate (each relocated from its own base 0).
  The `0x1017 LDX #$30C9` the old note cited as a "wrong address" is precisely
  this: `0x30C9` **is** StatText's base — gsasm is right, the comparison was wrong.
- **~289 B** — the 26-byte `~JumpTable` gsasm doesn't generate (linker output,
  `docs/TODO.md` §2), plus the 26-byte alignment shift it imposes on all of `Pics`.

**Fix (landed): compare Tool016 the way it is actually segmented** — the same
per-segment methodology `_check_multiseg` already uses for MenuMgr (Tool015).
Result: `StatText` **1174/1174 byte-exact**, `Pics` **358/358 byte-exact**, `main`
**12488/12489**. The one `main` byte (`0x1022`) is a far-pointer operand into the
**dynamic** `Pics` segment, which gold routes through `~JumpTable+0x12` (a
`cINTERSEG` to segment 4); resolving it requires the `~JumpTable` gsasm doesn't
generate — the **same TODO §2 gap**, now precisely located. `tool_bytes` bad:
**554 → 104** (Tool016's share **451 → 1**), all honest.

The `_check_multiseg` "differs at every load-time reloc site by construction"
worry in the earlier draft was overcautious: intra-segment word relocs are stored
segment-relative in gold and gsasm-at-base-0 reproduces them exactly (hence the
two byte-exact segments); only genuine inter-segment references (which go through
`~JumpTable`) stay unresolved — and there is exactly one such byte.

- `Tool023`'s 6-byte residual is **CLOSED (2026-07-18)** — and its cause was NOT
  `GetFilter` (that PROC places correctly at `0x22ec`) nor the case-B rule. It was
  a `DevName` symbol collision in the assembler: the name is BOTH a `PopUpGlobals`
  data-record field and a `GetThePrefix` PROC-local `equ`. The local `equ` was
  (a) clobbering the global data-record label — so `ldx #DevName` in the popup
  code stopped relocating (the `0x0b43` cluster) — and (b) being shadowed by a
  stale `with PopUpGlobals` in `resolve()` (the `0x3392` cluster). Both fixed in
  `gsasm/asm.py`; StdFile is byte-exact. See `docs/TODO.md` §1 and
  `tests/fixtures/042-proc-equ-vs-with-record-field`.

Net: Tool016 is **not** a value frontier — gsasm's ControlMgr is correct. The one
genuine remaining lever for it is `~JumpTable` generation (TODO §2), which would
also close Tool015/Tool018 and let a *full* multi-segment ExpressLoad Tool016 be
rebuilt and compared byte-for-byte (the real acceptance test).

### Original (superseded) analysis

An empirical survey (`work/reloc_survey.py`) plus a read of the archived
converter-side source *appeared* to settle whether the case-B standalone-RELOC
flag could be derived from the input, concluding it could not.

Survey — every standalone RELOC/cRELOC in the 6 `len<EOF` gold files (Tool014/023/
027/034, TS2/TS3): **30 records, a perfect partition:**
- **21 unflagged = case A:** all cRELOC, (size=2, shift=±8), NO SUPER type → must be
  standalone, relOff < 0x10000. Already handled (`_scan_standalone_relocs`).
- **9 flagged = case B:** all RELOC(0xE2), (size=2, shift=0 or 16) — combos that DO
  have SUPER types (type-0 / type-27) — yet gold emits standalone RELOC with
  `relOff = FLAG | offset`, FLAG ∈ {0x80000000 (7×), 0xc0000000 (2×)}. They occur as
  the far-pointer PEA pair (`PEA Label>>16` shift-16 at X + `PEA Label` shift-0 at
  X+3, same target), except Tool027 (unpaired shift-16). The low 28 bits are the
  clean segment-relative offset gsasm already computes; the FLAG is OR'd on top, and
  0x80 vs 0xc0 has **no structural predictor** in the corpus (both appear in Tool023
  for different targets at identical (size,shift)).

Why "not derivable" seemed dispositive at the time: the ExpressLoad
**converter** source — the tool that GENERATES these records — is **absent
from the GS.OS 6.0.1 archive.** Only the runtime loader is present
(`Loader/ExpressLoad*`, `ProcReloc.DataBankChanged`, `Relocation.a`), and it
adds relOff **unmasked**, so it cannot even reveal the flag's meaning. The
generator was part of MPW `LinkIIgs`; the full `IIGS.601.SRC.tar.txt` listing
contains no LinkIIgs / converter / "compress" source.

**What this analysis missed:** it never asked whether 0x80/0xc0 correlated
with the *source*, only with the converter's *output* structure. R6's
Launcher.Load finding (`#VersionFilter+$80000000`) — and then a source sweep
matching all 9 golden records to literal addends at their exact source lines
— showed the FLAG was written by the *programmer*, in the `.asm` file, not
computed by the converter at all. The converter's source being absent turned
out to be irrelevant: there was nothing to reverse-engineer, because the
"internal state" was actually visible input all along.
