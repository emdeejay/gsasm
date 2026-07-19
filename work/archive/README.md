# work/archive — retired forensic/diagnostic scripts

Date archived: 2026-07-18 (refactoring packet R3, see `docs/REFACTORING.md`).

These scripts are **evidence, not tooling**. Each one was a one-off
investigation written to answer a specific question during development, and
several `docs/` claims cite their output as the proof of a finding (e.g. "451
bytes decompose with no residue" or "`~JumpTable` reproduces byte-exact").
Deleting them would orphan that paper trail, so they are kept here instead of
in `work/` proper, where the *living* gate scripts (`work/gate.py` and the
harnesses it calls: `toolcheck.py`, `fstcheck.py`, `drivercheck.py`,
`diskcheck.py`, `kernelcheck.py`, `buildrom.py`, etc.) live.

**These scripts are frozen as of the date above and are expected to bit-rot.**
They ran against a specific tree state (specific `ref/` corpus, specific
`gsasm` behavior at the time) and their code is deliberately **not**
maintained — do not "fix" them to run against a changed tree, and do not
trust their output if you do run them without first re-verifying by hand
against the current gate. If you need the *finding* they proved, treat the
docs that cite them as the durable record; treat the script itself as the
lab notebook page behind that record.

## Index

### `appleshare_diag.py`
Locates the remaining AppleShare.FST sizing drift: builds a byte-offset ->
(module, segment, label, source line) map from gsasm's own placement,
de-ExpressLoads the golden AppleShare.FST binary, block-aligns the two, and
reports every structural (size-changing) edit mapped back to its source line.
Cited by `docs/TODO.md` and `docs/ADVERSARIAL_REVIEW_WS_A_2026-07-18.md`.

### `hfs104b_analysis.py`
Relocation-aware subtraction that isolates the structural edits in the
community "1.04b" HFS.FST build (Geoff Body / Petar Puskarich) from the 6.0.1
original, by de-ExpressLoading both, mapping every byte to its source
routine, and block-diffing to separate relocation fallout from real edits.
Cited by `docs/notes/hfs-fst-1.04b-uninitialized-hiword.md`.

### `hfs104b_roundtrip.py`
Proves the patch recovered by `hfs104b_analysis.py`: applies the three
recovered edits to the 6.0.1 HFS.FST source, reassembles/relinks/re-
ExpressLoads with gsasm, and byte-compares the result against the real
1.04b binary. Cited by `docs/notes/hfs-fst-1.04b-uninitialized-hiword.md`.

### `jumptable_probe.py`
Decodes and proves the ExpressLoad `~JumpTable` segment format (OMF KIND
0x02) directly from the GS/OS System Loader source (`Loader/Jump.a` +
`Loader.Equates`), showing it reproduces every golden `~JumpTable` byte-
exact — superseding the earlier assumption that the format would need to be
reverse-engineered from the MPW linker binary. Superseded as *tooling* by
`gsasm.expressload.encode_jumptable`, which is ported from this probe (see
the comment at `gsasm/expressload.py:182`). Cited by `docs/TODO.md`,
`docs/RESULTS.md`, and `docs/ADVERSARIAL_REVIEW_RECENT_BINARY_EXACT_2026-07-18.md`.

### `loader_residual.py`
Categorizes the Loader placed-link residual (the 448-byte operand-resolution
gap left after the cracked placement in `loader_placed.py`) by symbol, to
determine whether it is BOUNDED (a few distinct symbols/patterns, fixable) or
genuinely DIFFUSE. Not cited by any doc found in this sweep.

### `mpwmake_probe.py`
Read-only probe that parses the shipping MPW makefiles' LinkIIGS invocations
and diffs the object lists against the hand-transcribed harness maps
(`toolcheck.TOOLMAP` / `fstcheck.FSTMAP` / `drivercheck.DRIVERMAP`), to
answer how much of the harness recipe is a faithful copy of the makefile
versus a transcription error. Not cited by any doc found in this sweep.

### `p3_oracle.py`
Equivalence oracle for the (now-superseded) P3 decompose refactor: for every
`_expr_for` call across `buildrom`/`toolcheck`/`drivercheck`/`fstcheck`, computes
both the current-detector path and the would-be classifier-over-
`linear_decompose` path and asserts the emitted OMF op-bytes are byte-
identical, so the refactor could be verified as behavior-preserving before and
during migration. Cited by `docs/design/P3_DECOMPOSE.md`.

### `profst_diag.py`
Full residual diagnosis for Pro.FST (the M8 disk file): code-image diffs
mapped to segment + source line, the OMF record our emit produced at each
diff site vs the symbol-table view, the reloc-record set diff of the final
ExpressLoad segment, and byte accounting reconciling code diffs against the
EOF delta. Not cited by any doc found in this sweep.

### `reloc_diag.py`
Dumps and compares the OMF record stream (especially reloc records) of a
gold disk file vs gsasm's diskbuilder output, for a single named disk file
passed on the command line. Diagnostic-only building block, reused by
`reloc_survey.py` (which imports `dump_records`/`split_segments`/
`parse_header` from it — that import still resolves since both scripts moved
together into this directory). Cited by `docs/design/expressload.md`.

### `reloc_survey.py`
Empirical survey (built on `reloc_diag.py`) of every standalone RELOC/cRELOC
record across six target gold files (Tool014, Tool023, Tool027, Tool034,
TS2, TS3), tabulating size/shift/offset/relOffset per record and analyzing
which (size, shift) combinations appear standalone vs. SUPER-only — the data
behind the ExpressLoad case-A/case-B reloc-encoding rules. Cited by
`docs/TODO.md`, `docs/design/expressload.md`, `tests/test_expressload_case_b.py`,
and `work/diskbuilders/expressload_files.py`.

### `startgsos_diag.py`
Diagnoses the Start.GS.OS residual and tests whether a GLOBAL kernel symtab
(union of scm/bank0/device.dispatcher/... exports) closes GQuit's cross-
module externals — the linkOS scoping experiment. Not cited by any doc found
in this sweep.

### `tool016_diag.py`
Decomposes Tool016 (ControlMgr, a four-segment ExpressLoad load file) against
the shipping binary and proves that a previously-documented 451-byte
"residual" (once framed as a link-order/value-frontier discrepancy where
"gsasm computes different addresses than gold") is in fact entirely a
segmentation/harness artifact: gsasm assembles ControlMgr byte-exact per
segment, and the 451 bytes decompose with no residue into three mechanical,
fully-understood classes. Cited by `docs/TODO.md`, `docs/RESULTS.md`, and
`docs/design/expressload.md`.

### `toolsetup_probe.py`
Diagnostic for the Tool.Setup disk file: reproduces the System.Setup/
Tool.Setup ExpressLoad build (multi-object, segment-name-filtered, two
`-lseg` groups `main`+`patches`) from clean-room source and diffs it against
the shipping binary, establishing that both segments' CODE lengths match
exactly and the only residual is relocation-record *encoding* (gsasm SUPER-
izes all relocs; golden keeps standalone cINTERSEG/cRELOC) — the ExpressLoad
case-B converter wall, so Tool.Setup is code-exact but not byte-exact and is
deliberately left unwired. Cited by `docs/TODO.md`, `docs/design/expressload.md`,
and `docs/design/rez.md`.
