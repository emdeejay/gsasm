# Changelog

All notable changes to **gsasm** are recorded here. The format is loosely based
on [Keep a Changelog](https://keepachangelog.com/); this project's version of
"notable" is: which shipping Apple IIgs / GS/OS artifacts now rebuild
**byte-exact** from source, plus toolchain/library changes.

## [Unreleased]

## [0.6.0] — 2026-08-22

**The pay-down release.** No new reproduction claims and not one output byte
changed: all seven disks still reconstruct at 819,264/819,264, the ROM still
builds byte-identical, and every one of the 29 pre-existing gate metrics is
exactly where 0.5.0 left it. What changed is what the 2026-08-02 architecture
review asked for — the bytes were certain while the *model* was folklore. This
release writes the model down, tests it, and fixes what the tests found.

Implements slate items 1–6 of `docs/ARCHITECTURE_REVIEW_2026-08-02.md`.

### The pure core is under test (slate item 1)

- **306 new unit tests** across the five modules the review named as having
  zero direct coverage — `expr` (49), `makebin` (35), `m65816` (82), `omf`
  (74), `linkiigs`' symbol machinery (34) — plus the contract suites below.
  All corpus-free, all inside `gate.py`'s hard unit-test gate, so a broken
  MPW division rule or a moved `_build_symtab` pass now fails with a *name*
  instead of "byte 0xe5d differs" in a 59 KB kernel image.
- The m65816 suite writes out a canonical 16×16 opcode matrix independently
  and cross-checks `OPTABLE` against it, making the "100% opcode corpus"
  claim machine-checkable: all 256 byte values covered exactly once, with
  `$5C`/`$DC` the only duplicates and only as the deliberate JMP/JML aliases.

### Two contracts, written and enforced (slate item 2)

- **`docs/CONTRACT_SYMBOL_PRECEDENCE.md`** — the composite truth table the
  review found "exists nowhere but in the corpus itself": the four passes,
  their individual precedence policies, thirteen definition shapes × three
  tables, the rule interactions, five *negative* clauses, and a seven-question
  routing checklist for whoever adds rule #7.
- **`_build_symtab`'s docstring was wrong and is fixed.** It claimed
  "processed per object in link order so that first-definition wins", citing
  the MPW manual — while its own multi-object arm is `_kind_override` under a
  comment reading "last-wins for public EXPORT GLOBALs". The outer key of the
  table is **pass order, not object order**; first-wins holds only *within* a
  pass. That one sentence would have misled the next person to touch the
  linker.
- **`docs/CONTRACT_EXPRESSLOAD_RELOC.md`** — the semantic model of the two
  ExpressLoad output paths, eleven documented divergences with the golden
  artifact that forced each, and the **routing rule** that did not previously
  exist: classify a discovery by the question it answers, not the file you
  found it in. Grounded in the GS/OS System Loader source, which contradicted
  nothing.
- **A third reloc producer, which the review undercounted.**
  `work/finderdatacheck.py` and `work/installerdatacheck.py` each carry a
  complete classifier and inject it via `opts['reloc_dicts']`, bypassing both
  library paths — and `BankRel_Segment` ($0100) is modelled *only* there,
  nowhere in `gsasm/`.

### Both live disagreements between the shadowing restatements are closed

0.5.5 found them; this closes them, on two separately gated commits, with **no
output byte changed** — all 52 gate metrics stayed exactly at baseline through
both, the ROM still builds byte-identical, and `work/gate_baseline.json` was
never touched.

- **X2 (ladder row 0)** — `needs_reloc` had no current-segment fallback.
- **X1 (ladder row 9)** — `needs_reloc` never consulted `case_symbols`, so an
  exact-spelling EQU variant was invisible to the gate the emitter asks first.

Neither was closed by adding the missing branch to `needs_reloc`: that would
have made a *fifth* restatement of a ladder that already had four. Instead each
row now exists **once** — `asm._cur_seg()` for row 0, `asm._case_exact_equ()`
for row 9 — with `resolve`, `sym_kind` and `needs_reloc` as its three callers,
the shape `asm._with_active_field()` already gave row 5. The pinning tests
assert the *sharing*, not just the current agreement: each overrides the one
helper and requires all three answers to follow, so a future private copy fails
even while the answers still look right.

Measured before gating, by instrumenting `needs_reloc` in-process: row 0 was
structurally unreachable (`_rseg` set on all 58,838 calls in `objcheck` and all
38,022 in `finderdatacheck`), but **row 0's twin was not** — `finderdatacheck`,
the only build that opts into `case_equ_variants`, put 391 row-9 identifiers
through `needs_reloc`. Zero of them flipped, because no variant's folded
spelling is a relocatable label there. That defect was one source line from
being live, not impossible.

What is **not** closed, and `docs/CONTRACT_SYMBOL_PRECEDENCE.md` §II.5 now says
so under its own heading: `needs_reloc` still runs only from `omf.py`'s emit
paths while `asm.is_reloc()` — the same relocatability question in the sizing
vocabulary — runs in the main assembly pass. The two halves of one decision now
agree in *both* scopes instead of neither, which is why the corpus never
noticed either defect; they are still two functions reached from two phases.

### Structure (slate items 5 and 6)

- **`_build_multiseg_output`'s triple record-stream walk collapsed**, removing
  an O(relocs × records) re-scan and its repeated `_defer_shifts` calls, then
  **split into eleven named phases** against the reloc contract. Proven by
  hashing every actual multiseg emission across a full gate — 14 distinct
  artifacts, element-wise identical before and after.
- **`SymTab` kinds are native.** A KIND is a property of a binding, so it now
  lives on the value: `Sym` is an `int` subclass carrying `.kind`, and
  `.kinds` is a read-only view *derived* from the values, structurally
  incapable of disagreeing with them. This removes the sidecar that
  `{**a, **b}` silently dropped — including the latent gap at the old
  `linkiigs.py:624`, where a future kinds consumer would have read an empty
  table and re-classified every symbol as not-an-EQU. Value binding is
  untouched: 32 of the 34 pinning tests pass unchanged.

### Harness hygiene (slate item 3)

- **The census system is named what it is.** `work/census_migrate.py` →
  `work/censusledger.py`: it was never a one-shot migration (its `OVERRIDES`
  dict was hand-edited six times in its first 36 hours), it is a
  hand-maintained fork-ownership **ledger** plus a **regenerator**. Its
  docstring now documents the actual write API — how to add an `OVERRIDES`
  entry, and that the only supported way to change the census is to change
  the ledger and re-run. The generated census moved from the date-stamped
  `docs/disk_census_2026-08-01.json` to the undated `docs/disk_census.json`;
  the dated files stay committed (the 2026-07-30 one is also the
  regenerator's frozen input, and the 2026-08-01 one is the record of what
  v0.5.0 claimed). No fork's classification changed: the regenerated census
  is byte-identical to the committed one apart from three renamed top-level
  provenance keys.
- **Registry↔census reconciliation is now a standing gate**, not a
  release-eve audit (`work/reconcilecheck.py`, gate metrics
  `ledger_census_regenerable` + `ledger_forks_reconciled`). It runs both
  directions — a builder wired for a fork the census does not call `built`,
  and a census-`built` fork with no builder on a RECONSTRUCTED disk — plus
  diskcheck's Disk-2 `MANIFEST` against the census, and re-proves the
  census is still exactly what the ledger regenerates (so a hand edit to
  `docs/disk_census.json` cannot sit undetected until the next
  regeneration silently reverts it). 181/181 fork claims reconcile today.
- **`manifestcheck.OVERLAID_DISKS` converged on the typed-proof pattern.**
  It was a hand-set literal of seven disk labels enforced only by a comment
  ("do not add a disk here without also adding its physical metric to
  gate.py"); it is now derived from `diskmanifest.overlay_proofs()` — one
  `OverlayProof` per registered, baselined `diskN_physical_exact` metric.
  The derived set is identical to the literal it replaced.

- **Every gate-invoked check now exits nonzero when it regresses.** Ten of
  the 34 never called `sys.exit` at all, so the stdout scrape was their only
  signal. They now report through a shared `_common.gate_result()`, whose
  contract is deliberately "worse than its ACCEPTED STATE", not "bad > 0" —
  objcheck legitimately carries 21 link-identical objects and bytecheck 745
  known-benign operand deltas, and a naive sweep would have taken the whole
  gate red. Seven byte-tallying checks also gained an `*_unbuilt` counter,
  because a build that *raises* is caught and skipped: it contributes no
  mismatched bytes, so a bytes-only exit code would have been a fake.
- **One a2til discovery mechanism.** `$A2TIL_PATH` (already the de-facto
  override at 8 of 10 sites) is now the single path, replacing ten
  copy-pasted hardcodes across ten files — including `drivercheck.py`'s
  `~/src/a2til` with no override at all, and a copy of the discovery loop in
  `basiccheck.py` that silently continued when a2til was absent. A set-but-
  wrong override is now a hard error rather than a silent fall-back to
  another developer's layout.

### Opt-in assembly cache (slate item 4, R10)

- `GSASM_CACHE=1` enables a persistent memo of `omf.emit(asm.assemble(...))`
  under `work/.cache/`. Off by default and inert when off. Warm `objcheck`
  31.3 s → 0.4 s; full gate 3m42s → 2m31s.
- The key is **not** the `docs/REFACTORING.md` sketch, which was unsound:
  mtimes make `touch` a miss and `git checkout` of an older revision a *hit*,
  and a version string is constant during a refactor while the code changes
  every few minutes — so a version-keyed cache serves the previous edit's
  output, which is precisely how a cache makes the gate lie. It keys on a
  content digest of the whole imported `gsasm` package, plus every
  `assemble()` argument, and replays a recorded oracle of every include probe
  **including the misses** — because resolution stops at the first hit, so a
  file added *ahead* of the winner changes the result while every previously
  read file stays byte-identical.
- `gate.py --update` and `run_fixtures.py --bless` refuse to run with the
  cache on. The interlock raises `AssertionError` directly rather than using
  `assert`, because `python3 -O` strips `assert` and a blessed fixture minted
  from cached bytes is a permanent false claim about what gsasm emits.
- The documented gate runtime ("~2 minutes") was stale and is corrected to the
  measured 3m42s.

### Defects fixed (found by the new tests and contracts)

The tests were written to pin current behaviour; what several of them pinned
was a defect.  Each fix below is its own gated commit, and no golden byte moved
for any of them.

**Assembler / encoder**

- **`BLE`/`BGT` removed as dead `BRANCH8` entries.** They were wired through
  neither `OPTABLE` nor `ALIAS`, so `encode('BLE', …)` returned `(None, None)`
  while `test_branch_range.py`'s docstring claimed them as handled aliases.
  They are not aliases: the 65816 has nine short-branch opcodes and none spare,
  and the corpus defines `ble`/`bgt` as two-instruction **macros**
  (`QD/rects.asm`: "macros for branching on conditions that take more than one
  instruction").  The MPW Assembler Reference does list BGE/BGT/BLE/BLT — as
  *68000* instructions.  `BLT`/`BGE` are genuine and unaffected.
- **`lda #` reports an encode error** instead of raising `IndexError`
  (`'' in '<>^'` is `True` in Python, so an empty operand entered the
  part-selector branch).
- **An operand that fits no addressing mode is an error**, not two silent zero
  bytes (`stz $10,y`, `ldx 3,s`), and neither is a silent narrowing into a
  **one-byte** operand (`stx $1234,y`, `lda $1234,s`) where nothing can supply
  the missing half.  New `m65816.EncodeError`, surfaced through the existing
  `Asm.errors` channel.
- **Block moves report a bank they cannot account for** rather than baking
  zero.
- `instr_length()` takes `pc`/`reloc` instead of hard-coding them to `0`/`None`
  and disagreeing with `encode()` on cross-bank sizing.

**Expression evaluator**

- **`5 MOD 0` yields 0**, like `/` by 0.  This is documented, not a consistency
  guess: the Assembler Reference names `MOD` and `//` as *modulus division*
  (Table 2-2, p.29) and states *"Division by 0 yields 0 as the result"* (p.30).
- **`parse()` must consume its whole token stream.**  `'2 3'` no longer
  evaluates to 2, `'1)'` no longer to 1, a missing `)` is no longer tolerated.
  New `BadExpression`, a subclass of `Unresolved` so every existing
  `except Unresolved` site is unaffected, filed into `Asm.errors`.

**OMF**

- **`parse_records` decodes SUPER (0xF7)** instead of breaking the walk.  It
  previously fell through to `UNHANDLED` and stopped, so
  `iter_segments(records=True)` silently truncated any linked or ExpressLoad'd
  segment — 1,719 unparsed bytes on shipping Tool014, which now walks to `END`.
  The page-list codec moved from `expressload` into `omf` (re-exported by
  identity, the shape R8 used for `link.py`), so there is one copy, not two.
- **A truncated record raises `OMFParseError`** (a `ValueError` subclass)
  instead of running the cursor past the buffer, and an unterminated
  expression raises instead of returning an op-list with no `'end'` sentinel.

**Linker / symbols**

- Both `needs_reloc` disagreements closed — see above.

**makebin**

- `overlay`: the docstring was wrong about growth (the real OverlayIIgs extends
  its destination, as `p8_driver` already encoded in the one place it is
  byte-proved), and the **code** was wrong about gaps — `bytearray` slice
  assignment clamps, so a patch wholly past the end silently landed at the
  wrong address.  `p8_driver._overlay` now delegates, so the model has one home.
- Deferred GEQUs resolve to a **fixed point** with a cycle guard, not to a
  hard-coded two passes (a three-deep forward chain resolved wrong).
- A segment declaring a longer `LENGTH` than its body is zero-padded, so the
  flat image and its own symbol table describe one layout; an over-long body
  now raises.

**ExpressLoad**

- **`opts['super_classes']` is rejected on the multiseg path** rather than
  silently ignored.  Honouring it would move a `(size, shift)` class from the
  targeting phase into the case-A encoder, leaving absolute-equate bank-word
  sites holding the unshifted low word — an unforced redesign with no golden
  artifact to gate it.
- **The multiseg group image fills its ALIGN gaps.**  This was filed as latent,
  and was not: `AppleDisk5.25` declares `align 256` on four segments and is the
  only artifact in the gate whose merge fills anything (173, 12, 22, 9 bytes).
  It reaches `_merge_bodies` only via the single path, which is why the
  multiseg gap went unseen — the pinning test fails against the previous tree
  with a SUPER record naming an offset outside its own image.
- A `stype == 1` branch whose arms had become character-identical is collapsed
  (both comments kept), a dead `tgt_segnum` store removed, and the unguarded
  `expr_at` lookup now names the offset and the invariant instead of raising a
  bare `KeyError`.

**Harness**

- `bytecheck` names the modules its "0 opcode errors" count leaves out, and
  gained zero-accepting counters for modules whose assembly raised and for
  one-sided row yields.  The three excluded modules are `sys.equs.asm`,
  `QD/CallTable.asm` and `QD/font.asm` — 466 `EQU` lines and two pure data
  tables, zero 65816 mnemonics between them.  A category, not a residual, so no
  metric grew.
- `objcheck` distinguishes an assembler crash from a byte mismatch (it
  previously swallowed every exception with `except Exception: pass`, so a
  crash landed in the accepted 21).
- A tool parked in `toolcheck`'s WIP set is now reported as WIP rather than
  silently absent from both signals.

### Discovered, not fixed — three "defects" that were MPW behaviour

Filing these as defects is what made them findable; the gate is what stopped
them being "fixed" into regressions.

- **`lda $bbxxxx,y` dropping its bank is real AsmIIgs behaviour.**  The naive
  fix took `linkcheck` to 60/61 with 23 encode errors in `Serial.aii`.  The
  oracle settles it: `Serial.aii.lst:336` has `QBASE equ $E11DD8`, line 2624
  emits `LDA QBase,y` → `B9 1DD8` — bank dropped — and the listing ends
  "Assembly complete - no errors found."  The bank comes from the Data Bank
  Register at run time.  A probe over all 28 checks found 414 narrowings in the
  corpus, **every one** of class `w=3 → nb=2 absy` on ADC/CMP/LDA/SBC/STA.
  Now documented with the citation instead of labelled suspicious.
- **`NOT` does not continue an expression.**  `_EXPR_TAIL_OP` treated it as a
  continuation operator, folding prose comments into data operands;
  `NewCalls.asm.lst:2973` shows MPW emitting `00000032` for
  `p_wdefProc equ p_wInfoH+2` and reading the trailing `NOT USED.` as a
  comment.  `NOT` is unary (Asm Ref Table 2-2).
- **`eval_cond` stripped `THEN`/`DO` with a literal-space test** while the
  corpus overwhelmingly writes a tab.  Together these two produced correct
  bytes only because `expr` silently swallowed what they leaked — two bugs
  cancelling, invisible until the parser got strict.  Tightening `parse()`
  surfaced 6,702 evaluations across 47 operand texts; with both callers fixed,
  it rejects **zero**.

### Declined, with reasons

- **`MOD`'s sign.**  `/` truncates (documented, and `-7/2 == -3` not `-4`);
  `MOD` floors.  The manual is silent on modulus sign, and the corpus cannot
  arbitrate: all 22 genuine MOD sites across 3,521 files use **non-negative
  operands**, where floored and truncated agree.  Changing it would encode an
  undocumented, untestable claim about Apple's assembler into a byte-exact
  reproduction.  Recorded in the §5 Do-Not-Touch registry instead.
- **A relocatable operand narrowing to dp,y** still truncates quietly:
  `_width`'s "never direct page" answer for a relocatable is a policy, not a
  measurement, so reporting there risked pass-1 false positives.

### Corrected (found by the new reconciliation)

- The **prose** fork counts in `README.md` and in the 0.5.0 entry below said
  **178** forks (System Disk 40, Fonts 1); the census, the builder registry
  and `manifest_builders_wired` all say **181** (System Disk 41, Fonts 3).
  The three forks are exactly the ones commit `6f00bf3` wired — Disk 2
  ControlPanel data, Disk 5 Read.Me data, Disk 5 Apple.Bowl rsrc — after
  those two prose passages were written. The machinery has been right since
  2026-08-02; the sentences were stale. Both passages are corrected above
  and in `README.md`. The error understated the work — 0.5.0 built three
  more forks than it claimed — and the v0.5.0 tag is left as published;
  only the prose is fixed. This was an **eighth ledger the architecture
  review did not count: the release prose**, and it is the one that had
  actually diverged.

## [0.5.0] — 2026-08-01

**Tier A: the complete System 6.0.1 seven-disk set reconstructs byte-exact.**
One day, one arc: an adversarial review of the completion machinery in the
morning; every one of its seven findings closed; every remaining wall cracked;
zero unbuilt files by night.

### Completion (the headline)

- **All seven disk images reconstruct physically byte-identical**
  (819,264/819,264 each): Disks 1–6 via the generalized ProDOS overlay,
  Disk 7 (HFS-in-2IMG) via a2til's new allocation-preserving HFS overlay
  engine (a2til issue #9, developed in tandem and merged upstream).
- **Every fork with producing source is wired and logical-exact** — 181
  registry entries across the set (Install 39, System Disk 41, SystemTools1
  38, SystemTools2 52, Fonts 3, synthLAB 2, Apple II Setup 6). Zero
  residuals: the census classifies no file as buildable-but-unbuilt.
  *(Corrected in 0.5.5: this entry as published said 178 / System Disk 40 /
  Fonts 1. The number was stale, not the work — 0.5.0 did ship all 181.)*
- **`work/manifestcheck.py --tier-a` passes** on all six machine-checked
  conditions (inventory 7/7, substitutes confirmed AND structured with
  dated search evidence, builders wired/exact with typed proofs, physical
  7/7, no unaccepted technical exceptions).

### Byte-exact reproduction (new since 0.4.0)

- **Tool.Setup** (19,232 B, Disks 1+2) — the last TECHNICAL_EXCEPTION;
  the "case-B wall" was stale, the residual was recipe drift.
- **IWEM** (29,185 B, Disk 4) — the ImageWriter-Emulator PostScript proc
  set, rebuilt by replaying the MPW `BuildIWEm` text-squeeze script.
- **Adv.Disk.Util** resource fork (8,037 B) — the census's final
  TODO_BUILDABLE.
- **The SCSI family** — SCSI.Manager, SCSIHD/CD/Scan/Tape drivers — plus
  **ImageWriter, ImageWriter.LQ, StyleWriter, Epson, ATP1.ATROM,
  AppleShare.FST, VideoKeyboard, CloseView, LaserWriter** full ExpressLoad
  files (previously only their de-ExpressLoad'd code images were proven).
- Four literal-text data forks (Read.Me/Shortcuts/Whats.New/Fonts Read.Me,
  30,520 B) gated 1:1 against their tracked sources.

### Toolchain (three linker discoveries, each corpus-free-guarded)

- **Exported-EQU symbol kinds** (`linkiigs.SymTab.kinds`): reloc
  suppression for link-time constants now uses the assembler's structural
  GEQU-vs-GLOBAL signal at per-object precedence, replacing a value-range
  proxy that misfired on small constants (spurious SUPER/cRELOC records).
- **Constant-shift resolution**: `#const>>16`-style shifts over exported
  EQUs resolve at link time in the ExpressLoad single path (the SCSI
  "badmin bug" that turned out never to exist).
- **MPW module scoping**: a plain interior label is module-local — a
  by-name reference binds the program-wide EXPORT even from a sibling
  module of the same object; ENTRYs, unexported names, and segment names
  are exempt (the TS2 private-wins shapes hold).
- `expressload()` gains `opts['segname']` (a load segment's name is
  byte-load-bearing: header + directory `entry_len`).

### Verification machinery (the adversarial-review response)

- Typed builder proofs (CallableProof/HarnessProof) replace label counts;
  fork-granular census with machine-regenerated migration; physical
  byte-match hard-gated per disk with enforced exit codes; technical-
  exception acceptance markers; dated structured substitute-search
  evidence (247 records re-searched); `--tier-a` completion command.
- HFS access (read + overlay write) moved upstream to a2til
  (`a2til.hfs.HfsVolume`); gsasm's vendored copy deleted.

## [0.4.0] — 2026-07-30

Coverage beyond the System Disk, an internals refactor, and a Python-floor bump.

### Byte-exact reproduction (new since 0.3.0)

- **`BASIC.System`** — the ProDOS 8 command interpreter (disk 38→39; the last
  out-of-scope file on the System Disk retired).
- **Toolbox toolsets: 14/14** (193,357 B) — NoteSeq (Tool026) and VideoMix
  (Tool033) close the corpus.
- **Control-Panel CDEVs/NDAs: 19/19** resource forks (156,917 B) — adds
  MediaControl and MIDI.
- **The Finder** — both forks byte-exact: the 52,395 B resource fork and the
  146,924 B data fork (the largest program in System 6.0.1, ExpressLoad'd with
  its relocation dictionaries). Ships twice byte-identical — as the Disk-3
  `Finder` and as the System-Disk boot program `Start`.
- **Installer** (17,895 B) and **Teach** (7,333 B) resource forks.
- **MountImageGS** NDA data fork (5,750 B), four A.U.G data forks (29,019 B:
  CDRemote / Pioneer2000 / EasyAccess / Pioneer4200), and five more resource
  forks (4,515 B: FindFile, Apple.Bowl, MediaControl & VideoMix NDAs,
  Pioneer4200).
- **Whole System Disk**: `diskcheck` logical-exact 39/39, physical image
  byte-match 819,264/819,264. (The one remaining full-file ExpressLoad residual
  is `Tool.Setup` — code image byte-exact, its relocation encoding blocked on
  the case-B converter wall; deliberately left unwired.)

### Changed

- **Refactor (R9):** `expressload()` decomposed into a thin dispatcher plus
  `_build_single_output_seg()` and `_build_multiseg_output()`. Zero-drift —
  verified gate-stdout and ROM byte-identical.
- **Python floor raised to 3.10** (`requires-python = ">=3.10"`); 3.9 reached
  end-of-life in Oct 2025.
- Documentation accuracy pass across README / RESULTS / GSOS_MILESTONES.

### Packaging

- Source distribution no longer bundles reference disk images or PDFs (`tmp/`,
  `Users/` excluded); only project source ships. The clean-room `TypesIIGS.r`
  Rez include continues to ship in the wheel, so `gsrez` works out of the box.

## [0.3.0] — 2026-07-19

- **The whole System 6.0.1 System Disk rebuilds byte-exact.** GS.OS SCM
  (38,805/38,805), P8 (17,128/17,128), the mapped tools, drivers, and FSTs, plus
  the Rez-compiled resource forks (Sys.Resources, EasyMount, all CDEVs). First
  release to ship the clean-room `TypesIIGS.r` include in the package.

## [0.2.0] — 2026-07-15

- Initial public release: clean-room Python reimplementation of the MPW IIgs
  cross-development toolchain (AsmIIgs / LinkIIgs / RezIIgs and the
  MakeBin/Overlay/ExpressLoad packagers), validated byte-for-byte against the
  IIgs ROM 03 and GS/OS 6.0.1 shipping binaries.

[0.4.0]: https://github.com/emdeejay/gsasm/releases/tag/v0.4.0
[0.3.0]: https://github.com/emdeejay/gsasm/releases/tag/v0.3.0
[0.2.0]: https://github.com/emdeejay/gsasm/releases/tag/v0.2.0
