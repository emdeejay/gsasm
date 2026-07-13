# Corpus-free fixture suite

Every gate under `work/` validates gsasm by diffing against copyrighted Apple
golden binaries (gitignored `ref/`, `work/romsrc/`) — a fresh clone cannot run
any of them. This suite is the redistributable counterpart: **original**
assembly sources, each exercising one discovered AsmIIgs/OMF behavior, with
expected output bytes committed alongside.

```
python3 tests/run_fixtures.py            # check everything (no refs needed)
python3 tests/run_fixtures.py 014 024    # check fixtures matching a substring
python3 tests/run_fixtures.py --bless    # regenerate expected outputs
```

## Where the expected bytes come from (and why that's legitimate)

The inputs are original code written for this suite — no Apple source. The
expected bytes are **gsasm's own output**, minted only at a moment the full
golden-corpus gate passes: `--bless` runs `work/gate.py` first and refuses to
write if it fails. The private corpus validates the toolchain; the toolchain's
output then becomes the committed, redistributable truth. `--no-gate` skips
the interlock (for machines without `ref/`) and must only be used for fixtures
whose expected bytes have been verified by hand.

The corollary: **never bless to make a red suite green.** A fixture failing
after a toolchain change means the change altered a documented behavior;
either the change is wrong, or the behavioral claim in the fixture's header
comment needs re-deriving from the golden corpus before re-blessing.

## Fixture layout

```
tests/fixtures/NNN-rule-name/
    input.asm       original source; header comment names the rule and the
                    gsasm commit that discovered it (MacRoman-encoded, like
                    real MPW sources — fixture 020's '≈' is byte $C5)
    fixture.json    note/commit metadata; optional "defines", "sysdate",
                    "systime" (assembler inputs), "link": true (also run
                    gsasm.link.link and compare expected.out)
    expected.obj    blessed OMF object bytes — the authoritative comparison
    expected.dump   human-readable record dump of expected.obj (derived;
                    regenerated on bless; failures print a diff in this form)
```

The byte comparison is what passes or fails; the dumps exist so a human can
review what was blessed and read failures at the OMF-record level
(`tests/omfdump.py`, also usable standalone: `python3 tests/omfdump.py x.obj`).

## What the first batch covers

Fixtures 001–025 are harvested from the commit log's behavioral discoveries:
the AsmIIgs dialect rules (`$` in identifiers, bitwise IF AND/OR, backslash
continuation, expression continuation across whitespace, doubled-quote
escapes, CASE ON/OFF, RECORD templates and typed DS, TEMPORG, SEG loadname
persistence, `≈` complement, `&sysdate` injection, DC/DCB string semantics)
and the OMF emission rules (by-name expressions for externals ± constants and
two-external differences, same-segment PC-relative literals, EQU aliases
relocating via their target, operand-atomic CONST/LCONST chunking, deferred
`#^label` bank-shift relocations through the linker).

Each fixture's header comment states the behavior it pins. When a new
behavior is discovered against the golden corpus, add a fixture for it in the
same commit — the suite is the executable specification of the dialect, and
it should grow one fixture per discovery, forever.
