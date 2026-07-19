# Adversarial Review: Last 8 Commits, 2026-07-19

Scope reviewed: `HEAD~8..HEAD` at `c3bf9f7` ("docs: REFACTORING.md
status - R6/R7/R8 landed (R10 sole remaining packet)").

The reviewed range covers the R6/R7/R8 refactors, TS2/TS3 ExpressLoad closure,
Tool034/TextEdit byte-exact closure, and the 30/30 logical disk exact gate
baseline update.

## Finding 1: Release-facing docs are stale after E2/E3 closure

Severity: high for release-candidate readiness.

The last eight commits close important public milestones: TS2/TS3 ExpressLoad,
Tool034/TextEdit, GS.OS byte exactness, and 30/30 logical disk exactness. The
release-facing documents still describe older status.

Stale references:

- `README.md:20-24`: still says all 7 buildable FSTs, 11 of 12 device drivers,
  Tool014, and 19/30 System files.
- `README.md:33-39`: still says GS.OS reaches 38,757/38,805 and has 48 bytes
  remaining.
- `docs/RESULTS.md:14`: still says all 11 mapped toolbox toolsets and 150,459
  bytes.
- `docs/RESULTS.md:20`: still says 24/30 logical files.
- `docs/GSOS_MILESTONES.md:41`: still says 11 tools and 150,459 bytes, and
  still describes full on-disk ExpressLoad residuals for Tool015/016/018/034.
- `docs/GSOS_MILESTONES.md:63-65`: repeats the older 11-tool and diskcheck
  residual framing.
- `docs/EXPRESSLOAD_TIER2_PLAN.md:216-223`: says the public push gate includes
  refreshed README/RESULTS whole-disk numbers, but these files were not refreshed.

Current direct checks contradict those docs:

- `work/toolcheck.py`: corpus `186110/186110`, including Tool034/TextEdit.
- `work/kernelcheck.py`: GS.OS total `59049/59049`.
- `work/diskcheck.py`: logical exact `30/30`, physical `819264/819264`.

This is a release blocker because the repo now presents two different truths:
the gate says RC-quality exactness improved substantially, while the public docs
still advertise pre-closure residuals.

Suggested fix: refresh README, RESULTS, and GSOS_MILESTONES before tagging an RC.
Treat the docs update as part of the closure, not as a later polish pass.

## Finding 2: REFACTORING.md overstates completion; R9 is still unresolved

Severity: medium.

The latest status note says R9 landed and that only R10 remains:

- `docs/REFACTORING.md:7-13`: says R1-R5 and R9 landed with Tier-1/E0,
  R8/R6/R7 landed post-E3, and "Remaining backlog: R10 only."

The same document still lists R9 as pending work:

- `docs/REFACTORING.md:286-291`: R9 plan to decompose `_build_het_lconst` and
  `expressload()`.
- `docs/REFACTORING.md:356-361`: sequencing table still lists
  `R9 expressload decomposition` before R10.
- `docs/REFACTORING.md:363-365`: says R9 should land before the ExpressLoad
  multi-segment packaging feature.

The current code shape also supports that R9 has not truly landed:

- `gsasm/expressload.py:815`: `_build_het_lconst` is still about 125 lines.
- `gsasm/expressload.py:1050`: `expressload()` is still about 943 lines.

The R6/R7/R8 refactors appear gated and behavior-preserving, but the R9 status is
not coherent. This matters because `REFACTORING.md` is now being used as a
release-triage source of truth.

Suggested fix: either complete R9 or change the status note to say R9 remains.
Do not leave the file claiming both "R9 landed" and "R9 should land before..."
at the same time.

## Finding 3: Left-shift deferral test does not assert relocation semantics

Severity: medium.

Commit `d951821` changed `_defer_shifts()` so any nonzero shift on a non-constant
relocation expression is deferred:

- `gsasm/linkiigs.py:80-97`: docstring says non-constant shifts are represented
  in load-time relocation records.
- `gsasm/linkiigs.py:120-122`: `count != 0 and not const_only` appends a deferred
  relocation tuple.

The new regression test only proves the stored operand body bytes:

- `tests/test_linkiigs_defer_left_shift.py:59-69`: extracts merged CONST/LCONST
  bytes and asserts both operands remain `b'\x05\x00'`.

It does not prove that a corresponding SUPER relocation record is emitted with
the correct offset, size, and positive shift. In the `merge=True` non-SUPER path,
the body bytes are intentionally emitted without consuming the relocation tail:

- `gsasm/linkiigs.py:526`: only the rewritten body records are consumed for the
  merged data pass.
- `gsasm/linkiigs.py:546-570`: SUPER relocation output only exists under
  `opts['super']`.

A bug that preserves the unshifted body bytes but drops or mis-encodes the
load-time relocation record could pass this unit test while still producing
wrong runtime relocation behavior for the TextEdit class of fix. The golden
Tool034 check catches today's corpus, but the boundary test is incomplete for the
behavior it documents.

Suggested fix: extend `tests/test_linkiigs_defer_left_shift.py` to run the
SUPER path and decode/assert the relocation tail. At minimum it should prove that
the positive left-shift relocation survives with the expected target offset.

## Non-Findings

R6/R7 themselves look clean from this pass. `Asm.dispatch` and `define_label`
were split into smaller helpers without an obvious behavioral regression, and the
full gates still pass.

The Python 3.9 annotation compatibility issue in several `work/*check.py` files
appears to predate this eight-commit window, so it is not charged to this review.
It remains relevant to release packaging only if Python 3.9 support is required.

## Verification

Commands run:

```text
python3 tests/run_fixtures.py
python3 work/gate.py
python3 work/gate.py --full
python3 work/buildrom.py
python3 -m compileall -q gsasm tests work
python3 -m pip wheel . -w /tmp/gsasm-wheel --no-deps
python3 work/toolcheck.py
python3 work/fstcheck.py
python3 work/drivercheck.py
python3 work/kernelcheck.py
python3 work/diskcheck.py
```

Results:

- Fixtures: `57/57 fixtures pass`.
- Default gate: PASS.
- Full gate: PASS, including `disk_logical_exact good=30 bad=0`.
- ROM 03 build: byte-identical.
- Compileall: PASS.
- Wheel build: PASS, produced `gsasm-0.2.0-py3-none-any.whl`.
- Tool corpus: `186110/186110`.
- FST corpus: `111584/111584`.
- Driver corpus: `94948/94948`.
- Kernel corpus: `59049/59049`.
- Diskcheck: builders wired `30/31`, logical exact `30/30`, physical
  `819264/819264`.

`pytest` was not run because it is not available in this environment; the repo's
standalone fixture and gate checks were run instead.

Worktree note: this review adds this document only.
