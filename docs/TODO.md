# TODO — reopened leads (2026-07-14)

The SheepShaver image `ref/gsrom3/system500.hfv` (readable in place with
`work/hfs.py`) contains the original **MPW IIgs tool binaries** and interface
files under `MPW-GM/`. The limits in `RESULTS.md` were proven against the
*source archive* — "not derivable from these sources" — and that reasoning
stands. But the tool binaries reopen the two **toolchain-quirk** limits to
*empirical* attack: boot SheepShaver, feed controlled inputs to the original
tool, capture outputs, derive the rule. Same differential method as the
`.lst`/`.obj` fixtures.

**Update (2026-07-17 audit — see §6):** most of the "missing-source /
external" limits turned out to be under-verified negative claims. GS.OS
(94→44), AppleShare.FST ("no source" → full source builds ~89%), and Tool019
("source disagrees" → byte-exact after a linker fix) were all falsified. Only
**SCSIHD** remains genuinely evidence-backed. Re-verify any "absent/external"
claim against all three source trees before trusting it.

## 1. ExpressLoad "case B" flags (~550 B across Tool014/023/027, TS2/TS3, Tool.Setup)

`docs/design/expressload.md` proved the 0x80/0xc0 standalone-RELOC flag is
"internal LinkIIgs state" and the generator *source* is absent. The generator
*binary* is `MPW-GM/MPW/Tools/LinkIIGS` (with `ExpressIIGS`). Experiment: link
one known input (e.g. Tool023's object) with the image's LinkIIGS and see
whether the flags reproduce.

- If they reproduce → derive the rule from controlled experiments; no longer
  "per-tool magic-number bespokery".
- If they don't → this tool revision postdates Apple's 1993 build; the limit
  survives with stronger evidence. Either outcome is worth recording.
- Fallback: disassemble the 68k binary (code is in the resource fork).

**CONFIRMED (2026-07-14): the flag is the source expression's addend — the
"proven limit" falls to a general rule, no oracle needed.** R6 first showed it
on Launcher.Load (`#VersionFilter+$80000000`, ModalDialog filterProc
convention). A source sweep then matched **all 9** flagged case-B records
(`work/reloc_survey.py`) to literal addends:

| Golden flagged records | Source line |
|---|---|
| Tool014 PEA pair → 0x80005225 | `WindMgr/NewCalls.asm:6465` `pushlong #myEventFilter+$80000000` (bit 31 = Apple-period→ESC) |
| Tool023 pair → 0x80002a29 | `StdFile/sf.asm:1720` `pushlong #UpdateTheDialog+$80000000` |
| Tool023 pair → 0xc00022ec | `StdFile/sf.asm:2070` `PushLong #GetFilter+$C0000000` (comment: "set bit 30 for I-Beams") |
| Tool027 unpaired shift-16 → 0x80001cbb | `FontMgr/fm.asm:5807` `lda #^(cfEventHook+$80000000)` — only the high half references the symbol, hence unpaired |
| TS3 pair → 0x80002ac4 | `NewCalls.asm:6465` again — `Patch3/ts3.makeout` shows TS3 re-assembles WindMgr/NewCalls.asm |

The mysterious 0x80 vs 0xc0 was never linker state: bit 31 vs bit 30 of
toolbox filter/hook pointer conventions, written in the source. Rule to
implement: a relocation whose target expression carries addend bits ≥24 (out
of segment-address range) cannot ride a SUPER page list — emit a standalone
RELOC with the full flagged relOffset. Implementing this in the ExpressLoad
path should close the case-B residuals in Tool014/023/027, TS3 (and the
Tool.Setup reloc-encoding delta) — worth ~550 bytes toward toolcheck.
`docs/design/expressload.md`'s "not reproducible" section should be rewritten
when the rule lands.

**Implemented (2026-07-14, `gsasm/expressload.py::_scan_case_b`):** Tool014
byte-exact; Tool027 reloc dictionary exact (2-byte pre-existing code-image
residual remains); Tool023 wired into toolcheck (one flagged pair exact).
Two follow-up leads from the implementation:

- **Tool023 residual — CLOSED (2026-07-18).** StdFile is now byte-exact
  (15942/15942). The residual was NOT `GETFILTER` (that PROC places correctly
  at 0x22ec); it was a `DevName` name collision. `DevName` is BOTH a
  `PopUpGlobals` data-record field (custompopup.aii, a relocatable data-segment
  label) AND a `GetThePrefix` PROC-local `devName equ ParBlock+02` (sf.asm:6973).
  Two coupled `asm.py` bugs: (1) the PROC-local EQU overwrote the GLOBAL
  `DevName` symbol (label→equ), so a `ldx #DevName` in the popup code stopped
  relocating (baked field offset 0x36 instead of POPUPGLOBALS+0x36); (2)
  `resolve()` consulted the (stale, never-ENDWITH'd) `with PopUpGlobals` field
  namespace BEFORE the PROC-local EQU, so `sta DevName` in GetThePrefix used the
  field offset 0x36 instead of the equate 0xb8. Fix: `keep_prior` extended to
  `kind=='equ'` (a proc-interior EQU never clobbers a data-record label); and
  `resolve()` lets an explicit local def shadow a WITH field. Guard:
  `tests/fixtures/042-proc-equ-vs-with-record-field`.
- **The multi-segment ExpressLoad path (`multiseg=True`) never emits ANY
  standalone reloc records** (case A or B) — this is why TS2/TS3/Tool.Setup
  didn't move. Separate, larger gap; needs its own careful pass.
  (2026-07-15, R11: fixed the SAME class of placement-base bug in the
  **single-segment** path's standalone-reloc scan instead — EasyMount's
  `_scan_standalone_relocs`/`_scan_case_b` were evaluating expressions
  against the plain multi-object `sym` table instead of each segment's own
  `body_syms[placed_i]` — see `docs/design/rez.md`'s EasyMount section and
  `work/easymountcheck.py`'s docstring. Confirmed this does NOT touch
  `multiseg=True` at all: `work/toolsetup_probe.py`'s Tool.Setup output is
  byte-identical before/after, and its residual is a different wall
  anyway — reloc-record *encoding* (SUPER vs standalone cINTERSEG/cRELOC),
  not a placement-base error. The multiseg gap above still needs its own
  pass to port case-A/B scanning into the per-group loop with correct
  group-relative addressing.)

## 2. `~JumpTable` segments (Tool015/016/018)

RESULTS.md classes these as "generated by the MPW linker, not present in any
source" — and the generating linker is in the image. Controlled link
experiments could reverse the jump-table generation algorithm and close all
three tools.

**Now the sole remaining lever for Tool016 (2026-07-18).** Tool016's 451-byte
"residual" was fully root-caused to a segmentation/harness artifact —
`work/tool016_diag.py` proves gsasm assembles ControlMgr byte-exact per segment
(StatText 1174/1174, Pics 358/358, main 12488/12489). Once toolcheck compares it
the way it is actually segmented (per-segment, like MenuMgr), the entire tool
comes down to **one byte** plus the `~JumpTable` gsasm can't emit. That one byte
(`main` `0x1022`) is itself a `~JumpTable`-routed reference, so `~JumpTable`
generation is now the *only* thing between gsasm and a full byte-exact Tool016.

**Format FULLY DECODED (2026-07-18) — no emulator needed.** The `~JumpTable`
layout is completely specified by the GS/OS Loader source already in the tree
(`GS.OS/Loader/Jump.a` + `Loader.Equates`), and a codec built from it reproduces
**all three** golden `~JumpTable`s (Tool015/016/018) byte-exact —
`work/jumptable_probe.py` (`JUMPTABLE_FORMAT 4 ok / 0 bad`). Tool016's is even
derived from scratch (its one dynamic segment is Pics = seg 5, referenced at
offset 0) → BYTE-EXACT.

    OMF segment KIND = 0x02 (Jump_Segment)
    header  : 8 bytes 0x00                    (Loader.Equates seg_jmp_start = 8)
    entries : 14 bytes each (jmp_entry_size):
                UserID  (2) = 0x0000          patched to real UserID at load
                FileNum (2) = 1               this load file
                SegNum  (2) = target dynamic segment number (1-based, file order)
                Offset  (4) = routine offset within that segment
                JSL     (4) = 22 00 00 00     $22=JSL, addr patched to JumpLoad
    trailer : 4 bytes 0x00
    total = 8 + 14*N + 4

- A far pointer to a routine in a **dynamic** segment (KIND & 0x8000) relocates to
  `~JumpTable + (8 + entry_index*14 + 10)` — the entry's JSL, which traps to the
  Loader's `JumpLoad` (loads the segment on demand, overwrites the JSL with `$5C`
  + resolved address, falls through). Tool016 main's cINTERSEG to `~JumpTable+0x12`
  (=8+0*14+10) is exactly this. **Static**-segment references stay direct
  (c)INTERSEGs — no jump-table entry.

**Remaining work** = the *linker* side: (1) segment gsasm's merged objects into
the gold load segments (main/StatText/Pics …) with KINDs, (2) scan inter-segment
references, emit one entry per referenced dynamic-segment routine (order for
multi-entry tools like Tool018 must come from the reference scan — single-entry
015/016 are trivial), (3) rewrite those references to the jump-table JSL, (4) emit
the KIND-2 segment via the proven codec. That closes Tool015/016/018 and enables a
*full* multi-segment ExpressLoad Tool016 for a real byte-for-byte acceptance test
(vs the current per-segment code-image comparison).

**DONE (2026-07-18) — Tool015/016/020 byte-exact; the corpus's final 6 bytes are
CLOSED (toolcheck `tool_bytes` 124154/124160 → 124160/124160).** The linker-side
generation landed in `gsasm/expressload.py` (`encode_jumptable` / `jt_jsl_offset`,
ported from `work/jumptable_probe.py`), a one-line opt in `gsasm/linkiigs.py`
(`abs_extra`, see below), and the jump-table-aware multi-segment link in
`work/toolcheck.py` (`_link_jt_tool` / `_check_jt_tool`; TOOLMAP `'jt_segments'`).
Mechanics, all validated against gold:
  - **File segment numbering.** Non-dynamic segments first (source order), then
    ~JumpTable (only when a dynamic segment exists), then dynamic segments — the
    exact gold layout (015 MainTool/~JumpTable/PopUpProc; 016
    main/StatText/~JumpTable/Pics).
  - **Entry allocation & order.** Scan every load segment's references in body
    (= code-offset) order; a reference into a DYNAMIC (KIND & 0x8000) segment
    claims one 14-byte thunk per distinct (target_segnum, routine_offset),
    first-seen. VERIFIED that MPW LinkIIgs allocates in code-scan order: Tool018's
    12 golden entries are first-referenced in MAINPart at ascending code offsets
    (indices 0..11 in order), and `_link_jt_tool` reproduces all 12 `(seg, off)`
    byte-exact — the multi-entry ordering the task flagged as the risk is
    **derived, not guessed**.
  - **Reference rewrite / encoding.** Each cross-segment far pointer is seeded as
    an extern whose value is the target OFFSET only (the thunk's JSL offset
    `jt_jsl_offset(idx)` for dynamic targets, the routine's own offset for
    STATIC / KIND-0x4000 targets); the field's bank byte (size>=3) is then set to
    the target's file segnum (~JumpTable's for dynamic, the segment's own for
    static) — the cINTERSEG `[off_lo, off_hi, segnum]` convention. The extern
    names are passed as `abs_extra` so any shift on the reference resolves at
    link time (gold encodes these as cINTERSEG-with-shift storing the *shifted*
    placeholder, e.g. ControlMgr main's `LDX #(PICPROC>>8)` at 0x101f stores
    0x12>>8 = 0), while genuine intra-segment `lda #^label` bank refs still defer
    to a SUPER type-27. A symbol the referencing segment defines itself is never
    externed (it stays intra-segment — the `CTLDATATOAX` collision: a main label
    also EXPORTed by Pics).
  - **~JumpTable gated.** `_check_jt_tool` builds the KIND-2 segment via
    `encode_jumptable` and compares it byte-for-byte to gold (a mismatch raises,
    so JT correctness is gated even though the ~JumpTable bytes are not in the
    per-segment `tool_bytes` denominator — that stays exactly the gold-shipped
    non-JT segments = 124160). Tool020 has NO dynamic segment (TheProc is KIND
    0x4000, not 0x8000): its far pointer is a direct cINTERSEG, no jump table.

**Tool018 (QDAux) — NOT mapped: jump-table generation WORKS, but two non-JT
blockers remain.** `_link_jt_tool` derives Tool018's 12-entry ~JumpTable
byte-exact (ordering proven above) and links CopyBits/Pictures/PixelMap2Rgn
byte-exact. The two residuals are OUTSIDE jump-table scope:
  1. **MAINPart (10 B) — the copybits.asm `SEG` section split.** The QDAux
     MakeFile links `copybits.asm.obj(@MAINPart)` into MAINPart and
     `copybits.asm.obj(@CopyBits)` into CopyBits — one object feeding two load
     segments (gsasm captures the sections as LOADNAMEs). MAINPart's references to
     ISTDPIXELS (the @MAINPart section) and to COPYBITS/STRETCHBITS/
     FORCECOPYBITLOAD (the @CopyBits section) need those segment names published
     into the per-segment symbol table; the quick prototype filtered the object
     by LOADNAME with `asm=None`, which drops segment-name symbols. The correct
     fix is a `seg_order`-selected per-LOADNAME placement that keeps the full asm
     (so `_build_symtab` pass (b) publishes each placed segment's name at its
     placed base) — a harness extension, not a jump-table gap.
  2. **SeedFill (1 B, offset 0xae3) — an independent assembler-level byte.** No
     EXPR record covers it; it is an isolated byte in seedfill.asm's STANDALONE
     assembled image (gsasm 0x1c vs gold 0x02), unrelated to jump tables /
     inter-segment linking. This pre-existing gsasm↔gold assembly discrepancy
     would have to be root-caused separately before Tool018 could be gated
     byte-exact.
Because mapping a not-byte-exact tool would REGRESS the gate (`tool_bytes` bad
0 → >0), Tool018 is left unmapped pending those two fixes.

## 3. P8 include files

P8 was scoped out partly for "include files not in the GS/OS tree". The image
carries `Interfaces&Libraries/Interfaces/AIncludes` (352 files) and
`MPW/Interfaces/AIIGSIncludes` (88 files, all the `E16.*` equates). Check
whether P8's specific missing includes are among them. The OverlayIIgs
driver-overlay build recipe is a separate, still-open problem.

## 4. Rez oracles (consumed by M7 — in progress)

`MPW-GM/MPW/Interfaces/TypesIIGS.r` (extracted → `work/rincludes/`), plus
`RezIIGS`, `DeRezIIGS`, `ResEqualIIGS` binaries for capturing oracle outputs
on ambiguous corners of the Rez language. See `docs/design/rez.md`.

## 5. Clean-room, distributable `TypesIIGS.r` (batteries-included gsrez)

Apple's `TypesIIGS.r` is copyright/gitignored, so `gsrez` today can't ship a
usable resource-type library. A clean-room re-implementation — provably correct
because `gsrez` + our file must rebuild the golden Sys.Resources / EasyMount
forks byte-exact (Apple's file off the path) — turns `gsrez` into a
batteries-included IIgs resource toolkit. Proven-core (~17 golden-exercised
types) first, reference-only tail flagged. Full plan:
`docs/design/typesiigs-cleanroom.md`.

## 6. "Proven ceiling" audit follow-ups (2026-07-17)

The audit (see `docs/RESULTS.md` and the case study
`docs/notes/proven-ceiling-audit.md`) falsified four documented limits and
overturned the "at the proven ceiling" framing. Remaining follow-ups:

- **GS.OS — BYTE-EXACT (38805/38805).** The "94-byte external floor" is fully
  gone (94 → 44 → 0). SEVEN classes CLOSED 2026-07-17, each root-caused vs the
  MPW 3.0 Assembler Reference with a corpus-free fixture (035–041):
    1. **init-header `DC.W init_N_end-init_N_start` (4 B, Init1/Init3).** NOT a
       case-fold miss (that diagnosis was wrong — `sym_kind` already unifies a
       local def over an `Import`). Real cause: `init_N_end` is a relocatable
       end-bracket PROC after a data `RECORD` (resets loc to 0), so gsasm baked
       `init_N_end(=0) - init_N_start` as an assembly-time literal while
       `init_N_start` is an ORG'd absolute pad PROC — the length is a LINK-time
       constant. Fixed in `omf._diff_reloc`: a MIXED absolute/relocatable
       cross-seg diff bails only when BOTH segments are ORG'd (`or`→`and`);
       fixture 035.
    2. **`a_reg` duplicate-symbol (~26 B incl. the scm_main `$B9D6` vector).**
       `a_reg` is an EXPORTed `ds.b` in dsptch_vars AND a module-local
       `a_reg equ dir_reg+2` in lc_dispatcher; gsasm let the proc-local EQU
       clobber the global, so the `dispatcher` seg's 10 `>a_reg`/`|a_reg` refs
       baked the equate ($0019) instead of relocating to $AC2E. Fixed in
       `asm.py::define_label`: a proc-interior EQU reusing an EXPORT/ENTRY/IMPORT
       name stays module-local (seg_equ), never clobbers the global (MPW Asm Ref:
       module-interior labels are local unless exported); fixture 036.
    3. **init.1 `ldx #my_dp_size-2` (2 B) — bare-ORG union sizing.** A bare `ORG`
       (no operand) resets a template's location counter to the MAX offset across
       its variant `ORG` overlays (MPW Asm Ref p.102: "ORG with no operand sets
       the location counter to the maximum ... value assigned ... up to this
       point"). my_direct_page overlays a graphics dialog arm over a text arm; the
       record size must span the larger (my_dp_size=$50, not $4A). gsasm sized the
       last arm. Fix: `asm.py` `_rec_hi_stack` tracks the high-water; fixture 037.
    4. **init.2 `pea '“'`/`pea '”'` (4 B) — char literal = Mac Roman byte.** A
       character constant's value is the source Mac Roman BYTE ($D2/$D3), not the
       Unicode code point ($201C/$201D) that `ord` returns after the mac_roman
       decode. Fix: `gsasm/expr.py` re-encodes the char to mac_roman; fixture 038.
    5. **init.4 field-offset immediates (4 B) — HARNESS seeding gap, not a gsasm
       bug.** `ldy #s_flags`/`#id`/`adc #entry_size`: S_FLAGS/ID/ENTRY_SIZE are
       absolute EQU constants EXPORTed by SCM.src and IMPORTed by Init4. gsasm
       correctly emits by-name externals; they baked 0 because `link_placed`
       returns only placed positional symbols, so kernelcheck's SCM extern lacked
       the constants. Fix: seed SCM's exported constants into `gextern`
       (`work/kernelcheck.py`), mirroring linkOS's single global link (e1_*/GQuit
       pattern). No fixture (harness change, no gsasm behaviour change).
    6. **scm_main `MORE` duplicate (2 B) — plain label must not clobber an ENTRY.**
       `more` is declared `entry` in copy_ext_string ($B70A) and reused as a plain
       copy-loop label in 4 other PROCs; gsasm's last-wins let the final plain def
       ($F99B) clobber the global, so `allocvcr`'s cross-module `jsr more` bound
       the wrong instance. Fix: a plain label reusing an ENTRY name in another
       segment stays module-local, keeps the entry's global binding
       (`asm.py::define_label`; fixture 039). Scoped to ENTRY — EXPORT keeps
       last-wins (AppleDisk3.5 `export DATAMARKS`, which regressed 2 B until
       narrowed).
    7. **scm_main `lda #((common_int_ent<<8)+$5c)` (1 B) — shifted cross-seg label
       + const.** Packs the ENTRY's placed low byte ($25) as a JML operand's high
       byte — a link-time value. A bare `label<<8` already relocated, but the
       shifted CROSS-segment label plus a constant baked $005C. Fix: extend
       `omf._mul_reloc_expr` to emit `SEGNAME*N+K` for a relocatable label in
       another segment (not just an in-ORG-seg one); fixture 040.
    8. **be0segr `lda |temp_load_addr +2` (1 B) — numeric addend across whitespace.**
       The Device.Dispatcher SIB-copy reads the SECOND pointer word; gsasm dropped
       the ` +2` and read the same word twice. Per the MPW `BLANKS` rule (BLANKS ON,
       the preset: blanks may sit in the operand field, `;` required for the
       comment), a PURE NUMERIC addend (`[+-] <number>`) now folds across whitespace
       into a memory operand — narrow enough that prose comments (`-yes.`, `* text`)
       still terminate the operand. Fix: `asm.py::first_field` `_NUM_ADDEND_TAIL`;
       fixture 041. (Same class as AppleShare Class A operand-whitespace
       continuation — the AppleShare `+2` cases should now close too; re-check.)
  GS.OS is now byte-exact; nothing left in this residual.
- **AppleShare.FST → byte-exact** — MOSTLY DONE (2026-07-17): 30% → 99.9%
  positional (17812/17825) and **size is now byte-exact** (17825/17825), via
  three gsasm fixes + one harness fix, all with the whole golden gate at
  baseline and corpus-free fixtures:
    1. Bare-label template fields (`asm.py::define_label`): a bare label with no
       `ds` (e.g. `partial_len`) wasn't registered as a record field, so a
       typed-import `WITH mydata` left it at the DP template offset (`a5 04`)
       instead of absolute `mydata+off` (`ad 04 00`). Fixture 032.
    2. `RECORD IMPORT` (`asm.py` RECORD/ENDR): AppleShare's SPWrite/SPCommand
       param blocks are declared `record import` (external instance, fields
       inline). gsasm treated them as base-0 templates, so `sta SPWrite.WrtBufLen`
       sized DP (`85 0f`) instead of absolute `SPWrite+$0f` (`8d 0f 00` + reloc).
       Now registers the record as an import and binds fields via equ_alias.
       Fixture 033. (This was the big one: 40% → 99%.)
    3. Macro `&param=default` keyword params (`asm.py` `_define_macro`/
       `expand_macro`): the `=$FFFFFFFF` default was folded into the param NAME,
       so `ftype`'s `&creator` bound to empty and `dc.l &hfs,&creator` dropped a
       long — the FILETYPES table came out 16 B short. Fixture 034.
    4. Harness encoding (`work/fstcheck.py::_build_appleshare`, and
       `work/appleshare_diag.py`): the rewritten temp modules were written UTF-8
       but `read_text` reads mac_roman, corrupting the `≈` one's-complement byte
       (0xC5) so `and #≈buffer_valid` mis-assembled. NOT a gsasm bug — write
       mac_roman. (Fixed 7 bytes.)
  Remaining: **12 value-bytes** (size exact) in TWO deep, oracle-constrained
  classes (B and C below). Class A CLOSED 2026-07-17. Each remaining class risks
  the 100%-byte-exact GATED corpus for bytes in a NON-gated FST, so left for
  dedicated, gate-guarded work — poor ROI to grind speculatively.

    A. **Operand-whitespace continuation** [was 1 B] — `ora src_ptr +2` — CLOSED.
       The GS.OS `lda |temp_load_addr +2` fix (asm.py `first_field`
       `_NUM_ADDEND_TAIL`, MPW BLANKS ON, fixture 041) folds a pure numeric addend
       across whitespace for a memory operand and closed this too (17812→17813).
       The old "UNSAFE to widen" note was right about `_expr_tail` swallowing prose
       (`-yes.`), which is exactly why the fix is scoped to a pure-numeric tail,
       not the general `_expr_tail`.

    B. **Multi-term mixed absolute/offset field arithmetic** [6 B] —
       `lda my_f_info-tOpt.f_info,y` and `sta user_path+2-us_start+us_end,y`:
       expressions mixing an absolute WITH/import field (equ_alias → external)
       with a plain template offset. The equ_alias absolute binding doesn't
       compose through a multi-term +/- expression, so the value comes out
       direct-page-ish (gsasm 0x0060/0x0126 vs gold 0x3eb5/0x27d2).

    C. **Duplicate-label scoping** [6 B] — `month_adjust` and `next` are each
       defined twice (module-header + in-proc). Two OPPOSITE symptoms of the
       oracle-tuned `keep_prior`/`seg_local` logic in `define_label`
       (asm.py ~1050): `month_adjust` def#1 sits in the unnamed module-header
       segment (`is_data=False`), so `keep_prior` does NOT fire and the in-proc
       def#2 clobbers the global (cross-proc refs get the wrong table);
       `next` def#1 IS in a data segment so `keep_prior` fires — but that
       suppresses registering def#2 in `seg_local`, so the proc-local ref can't
       reach its nearby def. THIS IS THE SAME CLASS AS the GS.OS `a_reg`-twice
       residual (first §6 bullet) — a careful fix here could help both, but the
       `keep_prior` logic is tuned against specific golden cases (Pascal.FST
       `temp`), so it needs the whole gate as a guard, not a quick grind.

  See `work/appleshare_diag.py` (maps any divergence to source). The MakeFile
  also omits `JudgeName.aii` (fstcheck adds it).
- **Linker pure-literal-shift fix (Tool019)** — guarded by Tool019 in the
  gated corpus, but NOT by a corpus-free test (a synthetic attempt was
  vacuous — `dc.w` folds the constant before the deferral path). A CI-visible
  repro needs the exact defer-triggering construct (a `pushlong`/`#` immediate
  over a same-segment label difference that the assembler emits as a deferred
  `EXPR`, not the folded `dc.w` form).
- **SCSIHD.Driver** — the one genuinely evidence-backed limit (shared
  `SCSI.Drivers` source builds its 3 siblings byte-exact; only `type=0`
  diverges, code inserted throughout). Worth a `de_express` + block-align diff
  vs golden someday to characterize the revision delta precisely (à la the
  HFS.FST 6.0.4 analysis) rather than leave it asserted.
- **~JumpTable (§2) / P8 (§3)** — reachable via the image's MPW `LinkIIgs`
  (generates the jump tables) and `AIncludes` (P8's includes); still to do.

Audit lesson: the byte-match discipline was sound; the *negative* claims
("absent/external/unclosable") were the weak spot — always re-verify against
ALL THREE source trees (`IIGS.601.SRC`, `ROM Source Code`, `system500.hfv`)
and for `EXPORT`ed `DS`/`DC` globals, not just `equ`.
