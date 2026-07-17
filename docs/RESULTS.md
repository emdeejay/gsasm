# Results

What the toolchain reproduces, measured against the shipping binaries, and
what it provably cannot — with the evidence for each limit. Numbers are the
committed regression baseline (`work/gate.py`; `work/gate_baseline.json`).

## Reproduced byte-exact

| Target | Size | Verified by |
|---|---|---|
| ROM 03 firmware (all three banks) | 262,144 bytes | `work/buildrom.py` |
| All 7 buildable FSTs (Pro, HFS, Char, HS, DOS3.3, Pascal, MSDos) | 93,759 bytes | `work/fstcheck.py` |
| 11 of 12 drivers (AppleDisk, SCSI CD/Scan/Tape, RAM5, Slinky, AppleTalk stack, …) | 85,119 bytes | `work/drivercheck.py` |
| `prodos` (boot loader) | 1,668 bytes | `work/kernelcheck.py` |
| `Start.GS.OS` | 13,169 bytes | `work/kernelcheck.py` |
| `Error.Msg` | 5,407 bytes | `work/kernelcheck.py` |
| GS.OS kernel (SCM portion) | 38,805 bytes | `work/kernelcheck.py` |
| GS/OS Loader | 16,590 bytes | `work/loader_placed.py` |
| 15 of the 27 System 6.0.1 shipping files the disk harness rebuilds | — | `work/diskcheck.py` |

Close but not exact:

- **Toolbox toolsets** — 118,524 of 119,080 bytes (99.5%) across 14
  `ToolNNN` files (`work/toolcheck.py`; Tool023/StdFile added in R9 — its
  sources assemble cleanly, see `docs/design/expressload.md`).
- **Object-file encoding** — 40 of 61 ROM objects are byte-identical OMF;
  all 61 are *link-identical* (`work/linkcheck.py`): linking gsasm's object
  and Apple's original produces the same load image, so the remaining
  deltas are record-chunking differences with no effect on any output.

## Proven limits

Each of these was settled by evidence, not fatigue. They bound what any
toolchain could reproduce from this source archive.

**GS.OS: the bank-$E1 "external floor" — OVERTURNED, now BYTE-EXACT (94 → 0).**
The GS.OS SCM kernel now reproduces byte-for-byte (38,805/38,805); with the
separately-built Loader (16,590 B, also byte-exact) the whole GS.OS is exact.
The old claim held that the dominant residual was cross-bank references to
`E1_MSG_ADDRESS`, `E1_VOLNAME`, `E1_CURRENT_ID`, `E1_APP_FILENAME` and similar
bank-$E1 vectors that "no file in `IIGS.601.SRC` defines." That is false. They
are `EXPORT`ed `DS.B`/`DC` allocations in `GQuit.src`'s `seg_e1` segment
(`GQuit.src` lines ~10490–10620), ORG'd at `e1_obj_pstn` = `$E1D200`, so gsasm
bakes each at its real address (e.g. `E1_MSG_ADDRESS` = `$E1D6F3`,
`E1_CURRENT_ID` = `$E1D679`). The earlier sweep missed them because it searched
for `EQU`-style defs, not `EXPORT`ed DS-in-segment globals. Apple's `linkOS`
resolves the SCM→GQuit reference because it links every kernel object in one
global pass; `GQuit` merely lands in the sibling `Start.GS.OS` output file.
`work/kernelcheck.py` now mirrors that by seeding `GQuit`'s placed exports into
the SCM link's extern table, recovering **46 bytes** (`38,711 → 38,757`).
(`E1_GET_REF_INFO` and `EQ_MSG_ADDRESS` are `Import`ed by SCM but never
referenced, so they emit no bytes and were never part of the residual.)

The other **44 bytes** were *not* more of the same disease — export-seeding closed
**none** of them. Each was a distinct gsasm assembler/linker correctness bug (plus
one harness gap), root-caused against the MPW 3.0 Assembler Reference and closed
with a corpus-free fixture (035–041). The seven classes:

- **`b00segr` — a duplicate-symbol bug (~20 bytes, plus a scm_main vector: ~26
  recovered) — CLOSED.** `a_reg` is defined *twice* in `bank0.dispatcher.src`: an
  `EXPORT`ed `DS.B` label in `dsptch_vars` (placed `$AC2E`) and a *module-local*
  `a_reg equ dir_reg+2` inside `lc_dispatcher`. gsasm let the proc-local `EQU`
  clobber the global symbol, so the `dispatcher` segment's ten `>a_reg`/`|a_reg`
  references baked the equate value (`$0019`) instead of relocating to the export
  (`$AC2E`). Per the MPW Assembler Reference — *"labels defined inside a code module
  are local to that module"* unless `EXPORT`/`ENTRY` — a proc-interior `EQU` that
  reuses an `EXPORT`/`ENTRY`/`IMPORT` name now stays module-local (`seg_equ`) and
  never overwrites the global (`asm.py` `define_label`; fixture 036). The same
  duplicate class also drove the `scm_main` self-modified `$B9D6` jump vector, so
  the one fix recovered ~26 bytes.
- **`init` header `DC.W init_N_end-init_N_start` (4 bytes, Init1/Init3) — CLOSED.**
  It HAD folded to a bogus literal (`$4E00`/`$3000`) because gsasm baked
  `init_N_end(=0) − init_N_start` at assembly time. `init_N_end` is a relocatable
  end-bracket `PROC` that follows the `std_buffer` data `RECORD` (which resets the
  location counter to 0), so its assembly-time value was 0-based, while
  `init_N_start` is an `ORG`'d (absolute) pad `PROC` — the real segment length is a
  *link-time* constant. Fixed by having `omf._diff_reloc` emit the difference
  expression for a MIXED absolute/relocatable cross-segment pair (bail only when
  *both* segments are `ORG`'d); fixture 035. (The earlier "capital-`I` `Import` not
  case-unified" diagnosis was wrong — `sym_kind` already unifies a local definition
  over an `Import`.)

Two more init sub-classes are now **CLOSED**:

- **`init.1` `ldx #my_dp_size-2` (2 bytes)** — a bare `ORG` with no operand resets a
  template's location counter to the *maximum* offset across its variant `ORG`
  overlays (MPW Asm Ref p.102 union sizing), so `my_direct_page`'s graphics-vs-text
  overlay yields `my_dp_size = $50`, not `$4A`; `asm.py` `_rec_hi_stack`, fixture 037.
- **`init.2` `pea '“'`/`pea '”'` (4 bytes)** — a character constant's value is the
  source **Mac Roman byte** (`$D2`/`$D3`), not the Unicode code point (`$201C`/`$201D`)
  that `ord` yields after mac_roman decode; `gsasm/expr.py`, fixture 038.

One more sub-class (`init.4`) was a **harness** gap, now **CLOSED**:

- **`init.4` field-offset immediates (4 bytes)** — `ldy #s_flags`/`#id`/
  `adc #entry_size`. `S_FLAGS`/`ID`/`ENTRY_SIZE` are absolute `EQU` constants
  `EXPORT`ed by `SCM.src` (`id equ sys_entry+4`, …) and `IMPORT`ed by `Init4`.
  gsasm *correctly* emits them as by-name externals (`LEXPR sym83:S_FLAGS`); they
  baked 0 because `link_placed` returns only *placed positional* symbols, so
  `work/kernelcheck.py`'s SCM extern lacked the constants. Seeding SCM's exported
  constants into `gextern` — mirroring `linkOS`'s single global link, exactly as
  for the e1_*/GQuit case — resolves them. Not a gsasm bug; a harness seeding gap.

One more SCM class (the `more` **ENTRY**) is now **CLOSED**:

- **`scm_main` `MORE` (2 bytes)** — `more` is declared `entry` in `copy_ext_string`
  (`$B70A`) and reused as a plain copy-loop label in `get_prefix`/`get_name`/
  `end_session`/`swapout`. gsasm's last-wins let the final plain def (`$F99B`)
  clobber the global, so `allocvcr`'s cross-module `jsr more` bound the wrong
  instance. Per the MPW rule (interior labels local unless `EXPORT`/`ENTRY`), a
  plain label reusing an `ENTRY` name in another segment stays module-local and
  does not clobber the entry's global binding (`asm.py` `define_label`; fixture
  039). Scoped to `ENTRY` — `EXPORT` keeps last-wins (AppleDisk3.5 `export
  DATAMARKS` vs a local copy).

One more SCM class (`scm_main` `common_int_ent`) is now **CLOSED**:

- **`scm_main` `lda #((common_int_ent<<8)+$5c)` (1 byte)** — packs the `ENTRY`'s
  placed low byte (`$25`) as the high byte of a JML operand — a link-time value. A
  bare `label<<8` already relocated, but the shifted *cross-segment* label plus a
  constant fell through to a baked `$005C`. Fixed by extending
  `omf._mul_reloc_expr` to emit `SEGNAME(common_int_ent)*256 + $5c` for a
  relocatable label in another segment, not only an in-`ORG`-segment one; fixture
  040.

The last byte (`be0segr`) is now **CLOSED** too:

- **`be0segr` `lda |temp_load_addr +2` (1 byte)** — the Device.Dispatcher SIB-copy
  loop reads the *second* word of a pointer. gsasm dropped the ` +2` (whitespace
  before it) and read the same word twice. Per the MPW `BLANKS` directive rule
  (with `BLANKS ON`, the preset, blanks may sit in the operand field and a `;` is
  required for the comment), a **pure numeric addend** (`[+-] <number>`) now folds
  across whitespace into a memory operand — scoped tightly enough that unmarked
  prose comments (`-yes.`, `* text`) still terminate the operand (`asm.py`
  `first_field`; fixture 041).

So GS.OS is byte-exact; the "94-byte external floor" is fully gone. The lesson
holds: the discipline was always sound, and every "unclosable" byte turned out to
be a namable, fixable bug once read against the reference manual.

**ExpressLoad relocation encoding ("case B") — CLOSED for the single-segment
path (R9).** Previously classed as "not a function of the input"; overturned
by a source sweep (`docs/TODO.md`): the case-B standalone-RELOC flag is the
source expression's own out-of-range addend (e.g. `#Label+$80000000` /
`#Label+$C0000000`, the ModalDialog filterProc/hook-pointer convention, bit
31/30), not opaque LinkIIgs state, and the rule (`gsasm/expressload.py::
_scan_case_b`) is now implemented for the single-segment ExpressLoad path.
Measured effect (`work/gate.py --full`'s `disk_logical_exact`, 16/28 ->
17/28): **Tool014 (WindMgr) is now fully byte-exact** (its sole residual was
this flag); Tool027 (FontMgr)'s relocation dictionary is now exact, leaving
only 2 bytes of a separate, pre-existing code-image residual; Tool023
(StdFile) improved but is not byte-exact — one of its two flagged pairs
carries a wrong *value* because of an unrelated, pre-existing linkiigs
symbol-scoping bug (`GETFILTER` resolves unresolved), not a gap in this rule.
TS2/TS3/Tool.Setup build through a separate multi-segment ExpressLoad path
that has never emitted any standalone reloc record (case A or case B) — a
different, still-open gap — so they remain non-byte-exact. See
`docs/design/expressload.md`.

**SCSIHD.Driver: the golden binary does not match the archived source.**
The archived `SCSI.Drivers` source assembles byte-exact for the other three
SCSI drivers, and for SCSIHD it matches no device-type configuration
(the four possible builds yield 13,842/13,442/17,257/8,354 bytes vs the
shipping 15,690). Only a 211-byte prefix and 37-byte suffix agree; command
tables show code inserted throughout. The shipping driver was built from a
later source revision that is not in the archive.

**AppleShare.FST — source IS present; builds to ~85%, not byte-exact (was
wrongly recorded as "no source").** The full source tree is in the archive:
`FSTs/AppleShare/Src/` holds 24 `.aii` modules plus `Equates.aii`, a `MakeFile`,
and `JudgeName.aii`. gsasm assembles all of them (handling the MPW `load`/`dump`
symbol-dump equate-sharing by inlining `Equates.aii`) and links them in MakeFile
order — plus `JudgeName.aii`, a real `proc export` the MakeFile's `objects` list
omits but the shipping FST includes at `$3CB1`. The built image is 17,926 bytes
vs the golden 17,825 and matches ~85% when aligned (positional 18%, cascaded by
a residual sizing gap). Two genuine assembler-dialect gaps were found, both in `WITH`-scoped
record-field addressing:
(1) **FIXED** — `math_temp`/`quotient`/`divisor`, bare alias labels in the `dp`
template record, sized absolute where the golden sizes direct-page because gsasm
typed a storage-less RECORD label as a relocatable code label rather than a
constant field offset. The fix (`gsasm/asm.py` `define_label`: type a
template-record bare label `equ`, not `label`; DATA records keep `label`) is
**applied and gate-improving** — `kernel_bytes` `61867→61871` (the GS.OS kernel
residual `48→44`, the same init-header case), every other metric unchanged, all
seven byte-exact FSTs unchanged — and lifts AppleShare's alignment from ~85% to
~89% (built 17,792 bytes). Regression-tested by fixture
`031-template-record-bare-label-dp`.
(2) **Remaining** — `partial_len` etc., bare aliases in the `tdata` template
accessed via `WITH dp,mydata`, should bind to the `mydata` data-segment instance
(absolute `$3E55+offset`) but gsasm uses the bare template offset (direct-page);
this needs real `WITH`-instance resolution and is the residual ~33-byte / 5-site
gap. `work/fstcheck.py` builds AppleShare informationally (excluded from the
byte-exact CORPUS). Tool015/016/018 embed `~JumpTable` segments generated by the
MPW linker, not present in any source. Tool016 (ControlMgr) is now proven
byte-exact *per segment* (`work/tool016_diag.py`: StatText 1174/1174, Pics
358/358, main 12488/12489); its former 451-byte "residual" was a flat-link
segmentation artifact, and toolcheck now compares it segment-by-segment (like
Tool015). The sole remaining byte is a `~JumpTable`-routed far-pointer into the
dynamic `Pics` segment, i.e. the same missing-`~JumpTable` gap (TODO §2). That
gap's *format* is now fully decoded from the in-tree Loader source
(`work/jumptable_probe.py` reproduces all three golden `~JumpTable`s byte-exact,
and derives Tool016's from scratch); only the linker-side generation (segment +
reference scan) remains to close Tool015/016/018. Tool019 (PrintMgr) builds byte-exact
(5080/5080) from `IIGS.601.SRC/GSToolbox/PrintMgr` (printmgr.asm + dialogdata.asm,
the two-object link its makefile specifies): the archived source IS the shipping
revision. The one byte that used to diverge was a gsasm linker defect, not a
source/binary disagreement -- a pure-literal high-word shift
(`pushlong #LocalPathEnd-LocalPathname`, i.e. `31>>16`, which must resolve to 0)
was wrongly deferred to a load-time reloc and baked the un-shifted low word;
resolving link-time shifts over expressions with no relocatable symbols
(`linkiigs._defer_shifts`) makes it exact and touches nothing else in the corpus.
P8 (ProDOS 8) is out of scope: it needs the OverlayIIgs
driver-overlay build and include files not present in the GS/OS tree.

## Method

Everything rests on differential validation against captured artifacts of
the original build: source, `.lst` listings, `.obj` objects, and shipping
binaries. Any byte gsasm produces that differs from the original is a
measurable defect; any target that matches is proven correct, not assumed.

- `work/gate.py` runs every comparison harness and fails if any metric
  drops below the committed baseline. Nothing regresses silently.
- The golden reference material is copyrighted and not distributable
  (gitignored under `ref/`), so the repo also carries a corpus-free test
  suite (`tests/`): original sources pinning each discovered dialect
  behavior, with expected bytes minted only while the full gate passes.
  A fresh clone can run it; CI does, on every push.
- The disk-image harness additionally needs the `a2til` disk-image tools
  (a sibling project; point `A2TIL_PATH` at a checkout).
