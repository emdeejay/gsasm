# Adversarial Review: Recent Changes, 2026-07-17

Scope: latest recent commits through `b1b66e3 asm: fold a numeric addend across whitespace into a memory operand`.

## Finding 1: numeric-addend folding is not scoped to memory operands

Severity: high.

The new `_NUM_ADDEND_TAIL` continuation is implemented in `first_field`, which is the generic operand splitter used by all non-multi-token ops. The comment says this is for "A MEMORY-operand instruction", and the surrounding `_EXPR_CONT_OPS` comments explicitly exclude instructions, branches, and DS because unmarked comments can start with operator-looking text. The actual code has no opcode context, so any operand followed by whitespace and a pure numeric `+/-` tail is widened.

Concrete probes on current `HEAD`:

```text
parse_line("\tbne done +2\n").operand  -> "done +2"
parse_line("\tbra * +2\n").operand     -> "* +2"
parse_line("\tds.b $10 +2\n").operand  -> "$10 +2"
parse_line("\tlda base +2\n").operand  -> "base +2"
```

This reaches emitted bytes, not just parsing:

```text
bne done +2       -> d0 03 aa 6b
bne done ; +2     -> d0 01 aa 6b

ds.b 2 +2         -> reserves 4 zero bytes
ds.b 2 ; +2       -> reserves 2 zero bytes
```

The existing fixture only proves the intended `lda base +2` case and one prose-comment non-match. It does not guard branches, DS/DCB-like storage directives, or other non-memory operands. The safest fix is to move this continuation decision out of `first_field` or pass enough opcode/addressing context to limit it to the specific instruction operand class that needs BLANKS ON numeric addends. At minimum, add negative fixtures for branches and DS before relying on this as comment-safe.

Relevant code:

- `gsasm/asm.py:198`: comments exclude instructions, branches, and DS from whitespace expression continuation.
- `gsasm/asm.py:269`: new memory-operand comment is inside generic `first_field`.
- `gsasm/asm.py:279`: `_NUM_ADDEND_TAIL` check applies without opcode context.
- `tests/fixtures/041-numeric-addend-whitespace/input.asm:9`: positive fixture only covers `lda base +2`.

## Finding 2: the addend matcher is narrower than its own contract

Severity: medium-low.

The comment says the tail may be `[+-] <number>` term(s), with `+4-2` as an example. It only works when there is no whitespace between the previous number and the next sign:

```text
parse_line("\tlda base +2 -1\n").operand       -> "base"
parse_line("\tlda base + 2 - 1\n").operand     -> "base"
parse_line("\tlda base + $10 - $02\n").operand -> "base"
```

So the new behavior silently handles `base +2` but not the natural BLANKS ON spelling `base +2 -1`. It also excludes `%binary` numeric literals even though `_expr_tail` supports them. This is less urgent than finding 1, but the code and fixture should either document the stricter grammar or use the same expression-tail numeric lexer for all numeric terms.

## Verification

Commands run:

```text
python3 tests/run_fixtures.py
python3 work/gate.py
```

Results:

- Fixtures: `41/41 fixtures pass`.
- Gate: `PASS: all metrics at or above baseline`.

The passing gate means the current corpus does not exercise the branch/DS leak. It does not make the generic parser broadening safe.

---

## Resolution (both findings verified and fixed)

Both findings were independently reproduced (parse-level AND byte-level) before
fixing — Finding 1's DS leak was the real hazard: `ds.b 2 +2` silently reserved
4 bytes.

**Finding 1 (high) — FIXED.** The numeric-addend continuation is no longer
opcode-blind. `first_field` takes a `num_cont` flag that the caller
(`parse_line`) sets **only** for a real 65816 memory-operand mnemonic —
`up in m65816.MNEMONICS and up not in BRANCH8|BRANCH16`. DS/DCB and other
directives aren't in `MNEMONICS`, so they're excluded automatically; branches are
excluded explicitly. After the fix: `lda base +2` still folds (`ad 02 10`),
`bne done +2` does not (`d0 00`), `ds.b 2 +2` reserves 2. Fixture 041 now guards
the branch and DS negative cases alongside the positive and prose-comment cases.

**Finding 2 (medium-low) — FIXED.** `_NUM_ADDEND_TAIL` now matches its documented
contract: optional blanks around each sign/term and `%binary` literals, so
`+2 -1`, `+ 2 - 1`, `+$10 - $02`, `+%1010` all match while prose (`+2 nice`) still
does not.

**Verification:** `python3 work/gate.py` → PASS at baseline (kernel_bytes 61915,
GS.OS still byte-exact — the scoping fix is byte-neutral, confirming the corpus
never relied on the over-broad fold). `python3 tests/run_fixtures.py` → 41/41.

Fixed in the follow-up commit; the review's core point — "a passing gate doesn't
make a generic parser broadening safe" — was exactly right, and drove scoping the
continuation to the opcode class that needs it.
