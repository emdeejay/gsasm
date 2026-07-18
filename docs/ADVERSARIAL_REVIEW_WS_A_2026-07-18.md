# Adversarial Review: WS-A, 2026-07-18

Assumption: "WS-A" means AppleShare Class A, the operand-whitespace continuation
closed by the GS.OS numeric-addend fix (`ora src_ptr +2`).

## Finding 1: DCB is still not protected despite the WS-A scoping comments

Severity: medium.

The WS-A follow-up correctly scopes the numeric-addend path to non-branch 65816
mnemonics, so `ora src_ptr +2` and `lda base +2` fold while branches and `DS` do
not. But the implementation still passes `expr_cont=True` for every `DC*` opcode:

```text
parse_line("\tdcb.b 2 +2\n").operand -> "2 +2"
```

That is byte-visible:

```text
dcb.b 2 +2     -> reserves 4 zero bytes
dcb.b 2 ; +2   -> reserves 2 zero bytes
```

This contradicts the current comments/fixture text that describe count directives
as "DS/DCB" protected. `DS` is guarded by the new `num_cont` scoping, but `DCB`
gets widened earlier through the existing `up.startswith('DC')` expression
continuation path. If `DCB` count expressions are intended to continue like `DC`
data expressions, then the comments and fixture should stop claiming DCB is
excluded. If DCB is intended to behave like DS for unmarked numeric comments, add a
negative DCB fixture and split DCB out of `DC*` expression continuation.

Relevant code:

- `gsasm/asm.py:198`: `expr_cont` remains enabled for `up.startswith('DC')`.
- `gsasm/asm.py:2648`: `_dcb_bytes` evaluates the first comma field as the count.
- `tests/fixtures/041-numeric-addend-whitespace/input.asm:5`: fixture text claims DCB is excluded, but only `DS` is tested.

## Finding 2: AppleShare residual summary omits the `next` bytes

Severity: low.

`work/fstcheck.py` now reports a 12-byte AppleShare residual in two classes, but
its prose for class 2 names only `month_adjust`. A byte-by-byte diagnostic shows
the other two residual bytes are still the `next` branch target:

```text
0x26bb: bne next
0x26ce: beq next
0x2bf5/0x2eda: month_adjust indexed references
```

`docs/TODO.md` has the fuller description (`month_adjust` and `next`), so the
issue is limited to the user-facing `fstcheck.py` summary and can mislead the next
reviewer into thinking 10 bytes are accounted for while the headline says 12.

Relevant code:

- `work/fstcheck.py:331`: says 12 bytes remain.
- `work/fstcheck.py:335`: duplicate-label prose names only `month_adjust`.
- `docs/TODO.md:343`: correctly names both `month_adjust` and `next`.

## Verification

Commands run:

```text
python3 tests/run_fixtures.py
python3 tests/run_fixtures.py 041
python3 work/fstcheck.py
python3 work/appleshare_diag.py
python3 work/gate.py
```

Results:

- Fixtures: `42/42 fixtures pass`; fixture 041 passes.
- AppleShare informational build: `17813/17825`, size exact; WS-A no longer appears
  in `work/appleshare_diag.py`.
- Gate: PASS, with one current-branch improvement reported for `driver_bytes`.

Note: while reviewing, the worktree already contained an unrelated local
`gsasm/asm.py` change in `resolve_include` for HFS filenames containing `/`. This
review did not modify implementation code.
