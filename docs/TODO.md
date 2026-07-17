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

- **Tool023 `GETFILTER` resolves unresolved** in gsasm's link of StdFile —
  its flagged pair emits relOffset 0xC0000000 instead of golden 0xC00022ec.
  Looks like a linkiigs symbol-scoping bug, independent of the case-B rule.
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

- **GS.OS residual 44 bytes** — now known to be gsasm assembler/linker bugs,
  not an external floor: a duplicate-symbol case (`a_reg` defined twice,
  baked 0-based), a case-fold miss (`Import Init_1_end` vs `init_1_end`
  `PROC`), baked bank-0 constants, and a `WITH`-instance binding gap. Each is
  a real fix in `asm.py`/`linkiigs.py` — the most oracle-constrained files —
  so gate-verify hard.
- **AppleShare.FST → byte-exact** — PARTIAL (2026-07-17): the bare-label
  typed-import `WITH` case is fixed. `tdata`-template *bare* labels (no `ds`,
  e.g. `partial_len`, an alias of the following field) were never registered as
  record fields, so a typed-import `WITH mydata` bound only the `ds` fields; the
  bare ones fell back to the direct-page template offset (`lda partial_len` ->
  `a5 04` instead of golden `ad 04 00` = mydata+off). Fixed in
  `asm.py::define_label` (register positional template labels — DS OR bare — as
  fields); guarded by fixture `032-template-bare-label-typed-with`; whole golden
  gate stays at baseline. AppleShare moved 30%→40% positional, 17792→17802 B
  (33→23 B short). Remaining ~23 B: a *further* WITH/aliasing class (surfaces as
  +3/+7 address ripple from a handful of leftover undersizings) — likely the
  `WITH dp,mydata` dp-vs-instance PRECEDENCE case (a field present in BOTH `dp`
  and the typed `mydata`: which base wins?), the deeper "real WITH-instance
  resolution" root shared with the GS.OS residual. Still to characterize field
  by field. The MakeFile also omits `JudgeName.aii` (fstcheck's build adds it).
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
