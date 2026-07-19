# Adversarial Review: P8, 2026-07-18

**Superseded by later 2026-07-18 fixes.** This review is kept as evidence of
the failure state it found, not as current status. `work/p8check.py` now gates
the full P8 image byte-exact at 17128/17128; the builder raises on real
assembly errors; Sel.Alt DS-count/ORG semantics, comment `&` substitution, and
the stale P8-scope/missing-includes framing are closed.

Scope: remaining P8 assembler objective. Current tree builds all non-P8 corpus
targets at or above baseline, but P8 is still not byte-exact.

## Finding 1: P8 builder returns an image after real assembler errors

Severity: high.

`work/diskbuilders/p8_driver.py` builds a 17128-byte P8 image, but the build is not
clean. Current direct run:

```text
[Ram.n] 1 non-ignored errors:
  Ram.n:101: error: unknown builtin &BLOCK
built 17128
match 13416/17128 vs golden, first diff @ 0xc9
```

The same P8 source path also has real `AError` assertions:

```text
MliSrc.aii:8022: AError: Not enough room for CortFlag
Sel.Alt.n:606: AError: Code length overflow by $12F3 bytes.
```

The harness hides too much of this. `_assemble()` explicitly filters out `aerror`,
prints other fatal errors but still returns emitted OMF, and `_build_p8()` then
re-assembles `MliSrc.aii` with `sysdate` by calling `asm.assemble()` directly and
never checks `mli_asm2.errors`. Finally, the builder clips the overlong `sel.alt`
overlay back to the known P8 size, so a wrong image can look structurally plausible.

Do not use "returns 17128 bytes" as evidence of progress. For P8, any reached
assembler error should fail the builder until the residual is intentionally waived
with a named, measured exception.

Relevant code:

- `work/diskbuilders/p8_driver.py:90`: `_IGNORE_OPS` includes `aerror`.
- `work/diskbuilders/p8_driver.py:105`: `_assemble()` prints errors but still emits.
- `work/diskbuilders/p8_driver.py:205`: sysdate re-assembly ignores `mli_asm2.errors`.
- `work/diskbuilders/p8_driver.py:291`: overlong `sel.alt` is clipped to P8 size.

## Finding 2: `Sel.Alt.n` still exposes the real P8 assembler gap

Severity: high.

The known `sel.alt` failure is still active and reproducible:

```text
ds.b (alt_dispatch + 16) - * -2
expected DS = 5
gsasm DS = 4112
makebin(sel.alt.n) length = 4851
```

The source is an ORG'd PROC at `$1000`; at the DS, `alt_dispatch = $1000` and `*`
should be the ORG-relative current location `$1009`, giving `(0x1000+16)-0x1009-2
= 5`. gsasm evaluates the expression as if `*` is segment-relative zero-origin in
this DS sizing path, producing a huge pad and shifting the whole overlay. This is
not an OverlayIIgs packaging problem; it is an assembler expression/location
semantics problem in a DS count.

Relevant code/source:

- `ref/GSOS_6/IIGS.601.SRC/GS.OS/P8/P8.Drivers/Sel.Alt.n:39`: `alt_dispatch PROC ORG $1000`.
- `ref/GSOS_6/IIGS.601.SRC/GS.OS/P8/P8.Drivers/Sel.Alt.n:53`: failing DS expression.
- `work/diskbuilders/p8_driver.py:49`: current docstring captures the 4112-vs-5 gap.

## Finding 3: `&` substitution runs over semicolon comments

Severity: medium-high.

`Ram.n:101` is valid code with a semicolon comment:

```text
DOCMD1  LDA <CMD,X   ;CMD,UNIT,BUFPTR,&BLOCK(lo)
```

`parse_line()` sees the operand correctly as `<CMD,X`, but the main loop later runs
`self.subst(raw)` over the entire physical line before parsing it again. That means
`&BLOCK(lo)` inside the already-comment portion is treated as a builtin call and
emits `unknown builtin &BLOCK`.

Minimal probe:

```text
parse_line(raw).operand -> "<CMD,X"
Asm([]).subst(raw)      -> records unknown builtin &BLOCK
```

This can create false assembler errors from comments and can also mutate comments
before the final parse. For P8 it is already observable in `Ram.n`; the safer rule
is to strip or preserve comments before macro substitution for ordinary source
lines, while retaining substitution for actual operands/directives.

Relevant code:

- `gsasm/asm.py:720`: `subst()` treats `&NAME(...)` as a builtin call.
- `gsasm/asm.py:1808`: normal lines substitute the full raw line before parsing.
- `ref/GSOS_6/IIGS.601.SRC/GS.OS/P8/P8.Drivers/Ram.n:101`: comment contains `&BLOCK(lo)`.

## Finding 4: P8 reporting is stale and inconsistent

Severity: low.

The docs still say P8 needs include files not present in the GS/OS tree, while the
current repo already has a full P8 builder and include search path. Separately,
`kernelcheck.py` reports "P8 (PROCONE only)" as `2866/15162`, whereas the full
`p8_driver` image currently reports `13416/17128`. Those are different artifacts
and neither is a clean P8 acceptance gate.

Relevant code/docs:

- `docs/TODO.md:217`: still frames P8 around include discovery.
- `docs/RESULTS.md:244`: still says include files are not present.
- `work/kernelcheck.py:1016`: PROCONE-only comparison excludes overlays.
- `work/diskbuilders/p8_driver.py:180`: full P8 builder exists but is not clean.

## Verification

Commands run:

```text
python3 tests/run_fixtures.py
python3 work/gate.py
python3 work/kernelcheck.py P8 --diff
python3 - <<'PY'  # direct p8_driver._build_p8() vs golden
...
PY
```

Results:

- Fixtures: `46/46 fixtures pass`.
- Gate: PASS with current-branch `tool_bytes` improvement.
- Full P8 builder: `13416/17128` bytes match, size exact, first diff at `$00c9`.
- Kernelcheck P8 PROCONE path: `2866/15162` bytes match, first diff at `$00cc`.

Worktree note: this review only added this document.
