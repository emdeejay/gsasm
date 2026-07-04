# Design: ExpressLoad relinker (M4)

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
