# Adversarial Review: Recent Binary-Exact Changes

Scope reviewed: `HEAD~12..HEAD` at `b215f3c` ("gate: lock in tool_bytes
150459/0 after Tool018 closure"). This covers the recent driver/FST/tool exactness
closures, the assembler scoping fixes, the include hardening, DCB parsing, and the
`~JumpTable` toolcheck/linker work.

## Finding 1: `ORG 0` labels are misclassified by the new grouped relocation path

Severity: high for any linked source that uses explicit zero-origin absolute code
with a multi-term reloc expression; currently not hit by the green corpus.

`gsasm/omf.py` says `_reloc_target_key()` should return `None` for ORG'd and
TEMPORG labels, but it tests origin truthiness:

- `gsasm/omf.py:271-272`: `not (asm.segs[bs].org or asm.segs[bs].temporg)`
- `gsasm/omf.py:281-282`: same test for plain labels
- `gsasm/omf.py:621-627`: `_expr_for()` now calls `_grouped_linear_reloc()`

That treats explicit `ORG 0` / `TEMPORG 0` as if the segment were relocatable.
This matters because the recent AppleShare fix added `_grouped_linear_reloc()` for
multi-term expressions that `_linear_reloc()` deliberately did not classify.

Minimal repro:

```asm
USER    PROC
        longa   on
        longi   on
        lda     #target+here2-here
        rts
        ENDP
ABS     PROC    ORG 0
target  dc.b    0
here    dc.b    0
here2   dc.b    0
        ENDP
        END
```

Observed in the probe:

- `_linear_reloc(a, "target+here2-here")` returns `None`.
- `_grouped_linear_reloc(a, "target+here2-here")` returns `('target', 1)`.
- OMF emits `LEXPR size=2 [sym83:TARGET $1 op1]`.
- `linkiigs.link([(obj, a)], merge=True)` emits `a9 05 00 60 ...` because the
  `ABS` segment is placed after the 4-byte `USER` segment.

Changing only `ORG 0` to `ORG $1000` makes `_reloc_target_key()` return `None` and
the linked operand becomes the literal `a9 01 10 60 ...`. If explicit `ORG 0` is
an absolute origin, the zero-origin version should analogously link as `a9 01 00
60 ...`, not pick up the segment placement base.

This is not purely hypothetical: `work/romsrc/GS_ROM/Monitor/Monitor.aii` contains
`LASTWORD PROC org 0`. I did not find this exact multi-term reference shape in the
current corpus, which explains why the binary gate stays green.

Suggested fix: replace the truthiness checks with explicit `is None` tests, or
better, centralize the predicate used by `needs_reloc()` / `_equ_alias_of()` so
`ORG 0` and `TEMPORG 0` cannot diverge from non-zero ORG handling. Add a linked
fixture for the repro above.

## Finding 2: Data-record masking now silently swallows non-PROC `EQU` collisions

Severity: medium. This is a silent assembler semantics change from the StdFile
collision fix; it is not covered by the corpus.

The recent change widened the data-record `keep_prior` rule from labels to labels
and equates:

- `gsasm/asm.py:1163`: `keep_prior = (kind in ('label', 'equ') ...`
- `gsasm/asm.py:1220-1222`: when `keep_prior` is true, the new value is not stored
  in `self.symbols` / `self.symtype`
- `gsasm/asm.py:1268-1269`: the fallback `seg_equ` registration only runs when
  `self.in_proc`

The comments justify PROC-interior EQUs, but the condition does not require
`self.in_proc`. A top-level equate that collides with a data-record label is
therefore recorded in `labels` but discarded from resolution.

Minimal repro:

```asm
DataRec RECORD  Export
foo     dc.w    0
        ENDR
foo     EQU     $1234
Use     PROC
        dc.w    foo
        ENDP
        END
```

Observed in the probe:

- `labels` contains `('foo', 4660)`.
- `resolve('foo')` still returns `0`.
- `seg_equ` is empty.
- emitted OMF for `dc.w foo` is `LEXPR size=2 [sym83:DATAREC]`, not literal
  `$1234`.

If that duplicate is invalid MPW syntax, it should be a hard duplicate-symbol
diagnostic. If it is valid, `keep_prior` should be scoped to `self.in_proc` for
`kind == 'equ'`, or the non-PROC case should update the global equate normally.

## Finding 3: The include hard-error policy is not in the hard gate

Severity: medium process/gating risk.

`tests/test_include_not_found.py` is a good targeted negative test for the new
`IncludeNotFoundError`, but `work/gate.py` only runs `tests/run_fixtures.py` plus
the corpus check scripts. The new standalone include test is not invoked by the
gate. In this environment `python3 -m pytest ...` also fails because `pytest` is
not installed, so the test only runs when called directly as a script.

Why this matters: a regression that reverts `do_include()` to "append to
`a.errors` and continue" can still pass the fixture suite as long as fixture 043's
slash-to-underscore include continues resolving. The exact bug this change was
meant to prevent was a silent include drop, so the negative case should be part of
the same hard gate.

Suggested fix: either teach `tests/run_fixtures.py` an expected-error fixture mode
and add this case there, or have `work/gate.py` run `python3
tests/test_include_not_found.py` explicitly.

## Checks Performed

- `python3 tests/run_fixtures.py` -> `46/46 fixtures pass`
- `python3 tests/test_include_not_found.py` -> `3/3 passed`
- `python3 work/gate.py` -> `PASS: all metrics at or above baseline`
- `python3 work/gate.py --full` -> `PASS: all metrics at or above baseline`,
  including `disk_logical_exact good=23 bad=7`
- `python3 work/toolcheck.py 015/016/018/020` -> all four byte-exact; Tool015,
  Tool016, and Tool018 generated `~JumpTable` byte-exact
- `python3 work/archive/jumptable_probe.py` -> `JUMPTABLE_FORMAT 4 ok / 0 bad`
- `python3 -m pytest tests/test_include_not_found.py ...` -> not runnable here:
  `No module named pytest`

Residual note: the `~JumpTable` harness is deliberately specialized. Its current
mapped tools pass byte-exact, but `_scan_refs()` still identifies an inter-segment
far pointer by the first symbol in any EXPR-family record. If new tool mappings add
more complex cross-segment expressions, they should get a fixture/probe before
being trusted by the 100% metric.
