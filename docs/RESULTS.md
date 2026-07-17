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
| GS/OS Loader | 16,590 bytes | `work/loader_placed.py` |
| 15 of the 27 System 6.0.1 shipping files the disk harness rebuilds | — | `work/diskcheck.py` |

Close but not exact:

- **GS.OS** — 38,791 of 38,805 bytes (99.96%). The former 94-byte "external
  floor" was half wrong: 46 of those bytes were the bank-$E1 vectors, which
  are *defined* in `GQuit.src` and are now resolved; see below. The remaining
  14 bytes are gsasm assembler/linker bugs (template-offset immediates, a
  mis-scoped `MORE`, an off-by-2 placement) — baked constants that
  export-seeding cannot touch; see below.
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

**GS.OS: the bank-$E1 "external floor" — OVERTURNED (94 → 14 bytes).** The
old claim held that the dominant residual was cross-bank references to
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

The remaining **14 bytes** are *not* more of the same disease. The export-seeding
that recovered the 46 bank-$E1 bytes closes **none** of them, because every
residual byte is a **baked constant** — emitted at assembly time with no
relocation record for the linker/extern to override — or an **ambiguous duplicate
symbol** the link binds to a valid-but-wrong instance. They are gsasm
assembler/linker correctness bugs. Two whole classes are now **CLOSED**:

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

The remaining **14 bytes** are three smaller classes:

- **`init` template immediates ~10 bytes** (`init.1`/`init.2`/`init.4`) —
  `ldx #dp_size`-style immediates computed from `record`/template field offsets
  (e.g. `init.1` `$48` vs golden `$4E`), baked from the wrong template size. A
  `record`/template-typing bug.
- **`scm_main` 3 bytes** — an immediate `$255C` (baked `$005C`), and a duplicate
  local label `MORE` the link resolves to the wrong instance (`$F99B` vs golden
  `$B70A`).
- **`be0segr` 1 byte** — a live `BANK_E0_SEGR+$A86` reference whose placed low byte
  is off by 2 (`$86` vs `$88`), a placement/size discrepancy.

The correct fixes for the rest live in the *assembler* (`record`/template field
typing) and the *linker* (local-label scoping), not in the kernel-link seeding —
so the seeding ceiling is genuinely 14 bytes short here.

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
MPW linker, not present in any source. Tool019 (PrintMgr) builds byte-exact
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
