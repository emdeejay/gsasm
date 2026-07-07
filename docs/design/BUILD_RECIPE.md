# Build recipe is data, not code — read the tree's own recipe, don't transcribe it

**Status:** finding + work packages (2026-07-07). Extends `ARCHITECTURE_REVIEW.md`
(§3 `link_placed` still open) and qualifies `BESPOKERY_AUDIT.md`'s "bespoke in
`work/` is legitimate, like a makefile" claim. Surfaced by the question:
*"is there no file in the source tree that instructs the linker to create the
objects?"* — there is, and we're hand-copying it.

## The finding

The original ROM 03 build's **placement recipe already exists in the source
tree as data**, and `work/linkrom.py` re-encodes it by hand as a Python literal
instead of reading it. The recipe is not build *config* we author — it is a
*transcription* of an original artifact, i.e. a second copy that can silently
drift and that hides a missing tool capability.

- **The recipe:** `ref/gsrom3/tools.map.doc` — opens each bank with the literal
  linker directive and lists every object *in link order with its address
  range*:
  ```
      -lseg bankFE   -org $FE0000
  ::tl:tl.asm.obj              $0000-082F
  ::qd:objs:INIT.asm.obj       $0B89-155E
  … (bankFC -org $FC0000 @ line 35, bankFD -org $FD0000 @ line 60)
  ```
  **68 `.asm.obj` entries, 3 banks (FE/FC/FD).**
- **The transcription:** `work/linkrom.py:22` `BANKS = { 0xFE: [...], 0xFC: [...],
  0xFD: [...] }` — **68 object entries, same 3 banks, same order.** A 1:1 hand
  copy of `tools.map.doc`.
- **The irony that proves the point:** `linkrom.py:71 parse_map()` already reads
  an original linker artifact (`ROM/rom.map`) for symbol validation. Reading
  original files is a solved capability here; the *placement* recipe just was
  never pointed at its source file.

There is more of this layer in the tree, unused:
- **`.makeout` files** (e.g. `ref/GSOS_6/IIGS.601.SRC/GSFirmware/Applesoft/Applesoft.makeout`)
  are the fully-expanded original commands — `AsmIIgs … -o X.obj` → `LinkIIgs
  X.obj -o X.rel` → `MakeBinIIgs X.rel`. The exact per-module build, verbatim.
- **`makeROM3.bat`** is the final `binput`/concat that assembles the banks into
  `rom.03`.
- Per-module **`makefile`s** and APW **`Build.*`** scripts throughout
  `ref/GSOS_6/IIGS.601.SRC/` (GSToolbox, GS.OS/MakeFiles, GSFirmware/BuildFFROM…)
  — the build-orchestration for the *second* corpus we're now grinding.

## Why it matters

The originally-exposed toolchain surface has **three** layers:

1. the assembler (`AsmIIgs`) — reimplemented in `gsasm/asm.py` ✅
2. the linker (`LinkIIgs`) — reimplemented in `gsasm/link.py` (single-file);
   the **placed multi-`-lseg`** form is still missing (`ARCHITECTURE_REVIEW §3`)
3. the **build orchestration** (MPW `Make` / APW `Build.*` / `tools.map.doc` /
   `.makeout`) — **not reimplemented; hand-coded per build in `work/`.**

We faithfully rebuilt 1 and 2 and are re-authoring 3. Every hand-transcribed
table (the `BANKS` map, per-object org) is generality that belongs *in the tool*,
living instead as bespoke Python — and, worse here, as a *duplicate of a file
that already ships in the tree*. As we grind the GS/OS tree (which has its own
makefiles and `Build.*` scripts), re-authoring this layer per module is exactly
how "general tool" quietly becomes "good at two specific codebases."

## The regeneralisation move

Read the recipe; delete the transcription. Two pieces, in order:

1. **`linkiigs.link_placed(objs, placement)`** — the general placed multi-`-lseg`
   link with a cross-group global symbol table. This is `ARCHITECTURE_REVIEW §3` /
   the review's F1; it also retires `work/kernelcheck.py`'s hand-rolled placer.
2. **A recipe reader** that produces `placement` from the tree's own files, so no
   object list / bank / org is ever hand-typed again.

### Work packages

- **WP1 — `tools.map.doc` parser.** Parse `-lseg <bank> -org $ADDR` headers +
  the ordered `::path:obj $lo-$hi` lines → `[(bank, org, [ordered objs], [ranges])]`.
  Small, regular format. The `$lo-$hi` ranges are a **built-in oracle**: the
  placement the parser yields must reproduce them.
- **WP2 — `linkiigs.link_placed`.** Promote the algorithm currently inside
  `work/kernelcheck.py` (`_make_groups`, `_placed_symtab`) into the shipping
  library, fed by WP1's placement.
- **WP3 — rewire `linkrom.py` / `kernelcheck.py`.** Drive them from WP1+WP2;
  **delete the `BANKS` literal** (`linkrom.py:22`). Keep `parse_map()`'s `rom.map`
  read for *validation* only (symbol values), not placement.
- **WP4 (stretch) — a `.makeout`/makefile reader.** Drive per-module
  Asm→Link→MakeBin from the original expanded commands rather than re-encoding
  them. This is the full build-orchestration layer, and it's what lets the GS/OS
  grind be recipe-driven instead of hand-transcribed. Feeds the M-series /
  `GSOS_MILESTONES` work directly.

### Fidelity guard

This is a corpus no-op by construction: WP1's parsed placement must reproduce
`tools.map.doc`'s own address ranges, and the existing byte-exact `buildrom.py`
check stays the backstop. Nothing about the linker's *behaviour* changes — only
the *source* of the placement recipe moves from a hand-typed dict to the file
that already defines it.

## Provenance

Surfaced during a Starter Culture architecture-review pass (regeneralisation
lens) on 2026-07-07; the full ranked agenda for that pass lives outside this repo
at `companion/pipelines/architecture/runs/gsasm-2026-07-07/agenda.md` (F1 =
`link_placed`; this doc is the promoted, sharper form of the same seam). Self-
contained here so the gsasm project can resume without it.
