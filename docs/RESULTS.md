# Results

What the toolchain reproduces, measured against the shipping binaries, and
what it provably cannot — with the evidence for each limit. Numbers are the
committed regression baseline (`work/gate.py`; `work/gate_baseline.json`).

## Reproduced byte-exact

| Target | Size | Verified by |
|---|---|---|
| ROM 03 firmware (all three banks) | 262,144 bytes | `work/buildrom.py` |
| All 8 buildable FSTs (Pro, HFS, Char, HS, DOS3.3, Pascal, MSDos, AppleShare) | 111,584 bytes | `work/fstcheck.py` |
| All 12 drivers (AppleDisk 3.5/5.25, UniDisk, SCSI HD/CD/Scan/Tape + Manager, RAM5, SCC, Console, ATalk) | 94,948 bytes | `work/drivercheck.py` |
| All 12 mapped toolbox toolsets (WindMgr, MenuMgr, ControlMgr, QDAux, PrintMgr, LineEdit, DialogMgr, Scrap, StdFile, FontMgr, ListMgr, TextEdit) | 186,110 bytes | `work/toolcheck.py` |
| P8 (ProDOS 8 compatibility kernel, incl. overlay packaging) | 17,128 bytes | `work/p8check.py` |
| `prodos` (boot loader) | 1,668 bytes | `work/kernelcheck.py` |
| `Start.GS.OS` | 13,169 bytes | `work/kernelcheck.py` |
| `Error.Msg` | 5,407 bytes | `work/kernelcheck.py` |
| GS.OS kernel (SCM portion) | 38,805 bytes | `work/kernelcheck.py` |
| GS/OS Loader | 16,590 bytes | `work/loader_placed.py` |
| **ALL 30** System 6.0.1 logical files the disk harness rebuilds (2026-07-19, E3: Tool034/TextEdit was the last); physical image byte-match 819,264/819,264 | — | `work/diskcheck.py` |

Close but not exact:

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
Measured effect of the original case-B packet (`work/gate.py --full`'s
`disk_logical_exact`, 16/28 -> 17/28): **Tool014 (WindMgr) became fully
byte-exact** (its sole residual was this flag). Later fixes closed the remaining
Tool027 (FontMgr) code-image bytes and Tool023 (StdFile)'s separate `DevName`
symbol-collision bug (a PROC-local `equ` clobbering a same-named data-record
field, plus stale `with` shadowing that local `equ`; see `docs/TODO.md` §1 and
`tests/fixtures/042`). All three are now exact in `work/toolcheck.py`.
TS2/TS3 built through a separate multi-segment ExpressLoad path that
originally emitted no standalone reloc records at all; that gap was CLOSED in
E2 (2026-07-19, commit 8df2a45): the multiseg path now emits the full
standalone/case-B/SUPER dictionary and TS2 (36,665/36,665) and TS3
(41,700/41,700) are byte-exact on disk. Tool034/TextEdit followed in E3
(commits d951821/bc37f8d) — code image AND full on-disk file (38,242/38,242)
— completing `disk_logical_exact` 30/30. See `docs/design/expressload.md` and
`docs/EXPRESSLOAD_TIER2_PLAN.md`.

**SCSIHD.Driver — CLOSED (2026-07-18): byte-exact (15,690/15,690).** This was
NOT a source/binary disagreement; it was a gsasm include-path bug — the same
"under-verified negative" pattern as GS.OS and AppleShare. Two shared SCSI
filter sources pull in extra routines via `INCLUDE 'SCSI Get Vol/Disk'` /
`INCLUDE 'SCSI Set Vol/Disk'`, guarded by `IF scsi_dtype = direct_acc` — so ONLY
SCSIHD (the hard-disk device type) reaches them, which is exactly why the three
sibling drivers were byte-exact and only SCSIHD diverged. `/` is a legal HFS
filename character (MPW's path separator is `:`), so on archive extraction the
file became `SCSI Get Vol_Disk`; gsasm's `_find_ci` split the spec on `/`, never
found the `_` file, and `do_include` only appended to `a.errors` and continued —
silently dropping ~1,850 bytes of Get/Set-Volume-Parms code (the "code inserted
throughout, 211-byte prefix agrees" characterization). Fix: `resolve_include`
retries the spec with `/`→`_` per path component. All four SCSI drivers now
byte-exact; the driver corpus is 100% (94,948/94,948). Regression guard:
`tests/fixtures/043-include-slash-in-hfs-filename`.

**AppleShare.FST — CLOSED (2026-07-18): BYTE-EXACT (17,825/17,825)** (was
wrongly recorded as "no source"; the full tree is present). The source tree is in the archive:
`FSTs/AppleShare/Src/` holds 24 `.aii` modules plus `Equates.aii`, a `MakeFile`,
and `JudgeName.aii`. gsasm assembles all of them (handling the MPW `load`/`dump`
symbol-dump equate-sharing by inlining `Equates.aii`) and links them in MakeFile
order — plus `JudgeName.aii`, a real `proc export` the MakeFile's `objects` list
omits but the shipping FST includes at `$3CB1`. The built image is now byte-exact
(17,825/17,825). Getting there closed several `WITH`-scoped
record-field addressing gaps:
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
(2) **CLOSED (2026-07-18): AppleShare.FST is now BYTE-EXACT (17,825/17,825).**
The single bare-field case (`partial_len`, `WITH inst` over a typed import) was
already handled by fixture 032; the residual 12-byte / 5-site gap was three
finer `WITH`-scoped rules, all now fixed with the seven-FST corpus and the ROM
unchanged (gate at baseline, buildrom byte-identical):
  * **multi-term field arithmetic** — `lda my_f_info-tOpt.f_info,y`
    (send_option) and `sta user_path+2-us_start+us_end,y` (get_user_path). An
    equ-kind `WITH`-instance alias field, or several same-segment labels, that
    net to coefficient +1 must relocate as ONE collapsed reference; the old
    linear-reloc classifier only counted `label`/`import` terms, so the alias
    field folded into the constant and the relocation was lost (baked the
    direct-page offset `$60` where gold links `MYDATA+$60 = $3EB5`). Fix:
    `omf._grouped_linear_reloc` + `_reloc_target_key` (group terms by relocation
    base, emit when exactly one group nets +1). Fixture 044.
  * **`month_adjust` duplicate label** — a module-scope `dc.w 0,1,-1,…` table
    ($2A89) and a same-named in-proc `dc.w 1,4,4,…` inside `dow_convert`
    ($2FA8). gsasm's last-wins `symbols` bound cross-proc refs to the in-proc
    table; MPW keeps interior labels local, so cross-proc refs must reach the
    module-scope def and only `dow_convert` its own. Fix: `asm.py`
    `prior_modscope` (a proc-interior label duplicating a name bound at module
    scope — an anonymous name=None segment — stays local, like the ENTRY
    `foreign_entry_dup` and data-record `keep_prior` rules).
  * **`subcmds` record label `next` masking a proc-local branch target** — the
    `keep_prior` data-record mask correctly kept the record's `next` global but
    also dropped the `get_user_path` proc-local `next` from `seg_local`, so
    `bne next` reached the record label, not the loop label. Fix: register the
    masked proc label in `seg_local` UNLESS the masking record is in the active
    `WITH` scope (which is what makes Pascal.FST's `with GLOBALS`-scoped `temp`
    bind the field, not a proc-local `temp dc.w 0`). AppleShare is now folded into
    the `fst_bytes` gate tally.

Tool015/016/018 no longer have a `~JumpTable` code-image gap in `toolcheck.py`:
the linker-side generation, dynamic-segment thunk routing, and Tool018
multi-entry ordering are implemented and gated. Tool018 (QDAux) is mapped and
byte-exact, including the copybits.asm SEG-section split and SeedFill byte.
Tool019 (PrintMgr) also builds byte-exact (5080/5080) from
`IIGS.601.SRC/GSToolbox/PrintMgr`; the archived source IS the shipping revision.
The one byte that used to diverge was a gsasm linker defect, not a source/binary
disagreement -- a pure-literal high-word shift (`pushlong
#LocalPathEnd-LocalPathname`, i.e. `31>>16`, which must resolve to 0) was wrongly
deferred to a load-time reloc and baked the un-shifted low word. Resolving
link-time shifts over expressions with no relocatable symbols
(`linkiigs._defer_shifts`) makes it exact and touches nothing else in the corpus.
Full on-disk ExpressLoad builders are a separate surface; `work/diskcheck.py`
still lists logical length mismatches for Tool015/016/018/034 while the physical
disk image remains byte-identical via substitution/overlay discipline.
P8 (ProDOS 8) is BYTE-EXACT (`work/p8check.py`, 17128/17128): the full
`/System.Disk/System/P8` — four MLI PROC segments linked at $2000/$BF00/$DE00/
$FF9B plus every OverlayIIgs driver (cclock, tclock, ram1/2/3, sel, sel.alt,
xrwtot, quitcode). The old "out of scope / missing includes" claim was wrong:
`OverlayIIgs == makebin.overlay`, every include resolves, and the residual was
assembler-dialect bugs — `MACHINE M6502/M65C02` 8-bit immediates, backward
mid-segment `ORG` overlays in absolute segments, `IF (A) < (B)` paren
evaluation, DS-count expression folding, undefined-`&NAME`-stays-literal, and
not &-substituting comments (fixtures 049–053).

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
