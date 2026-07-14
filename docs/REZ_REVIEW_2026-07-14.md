# Rez adversarial review - 2026-07-14

Scope: uncommitted Rez lexer/parser/generator/emitter/CLI work in this tree.

## Findings

### High: missing mandatory values can silently shrink resources

`gsasm/rez/gen.py:957-1021` applies the optional-group "partial fill" rule to
every field list, including the top-level resource body, bounded arrays, switch
cases, and named groups. `_generate_resource_data()` only checks whether the
top-level cursor consumed the supplied top-level values at
`gsasm/rez/gen.py:1053-1057`; it does not know that mandatory trailing fields
were skipped.

This accepted input succeeds and emits only one integer:

```rez
type 1 { integer; integer; };
resource 1(1) { 7 };
```

Observed resource data:

```text
0700
```

Nested values can be dropped the same way. `_emit_array_field()` has no inner
cursor exhaustion check at `gsasm/rez/gen.py:867-875`, and group/switch emission
does not validate that the nested cursor was fully consumed:

```rez
type 1 { array [2] { integer; }; integer; };
resource 1(1) { { 1, 2, 3 }, 9 };
```

Observed resource data:

```text
010002000900
```

The `3` inside the bounded array was silently ignored.

Recommended fix: make partial-fill an explicit mode used only while emitting an
`optional` group. Mandatory top-level/group/switch/bounded-array field lists
should raise `GenError` when values run out, and nested cursors should be checked
for unconsumed values before returning.

### Medium: `$$Word` / `$$Byte` / `$$Long` label lookup is case-sensitive

`gsasm/rez/gen.py:576-581` looks up the raw label returned by `_call_name_arg()` in
`ctx.values`. Labels are otherwise normalized through `_key()` before storage, and
the generator comments state that real Rez resolves label references
case-insensitively.

This means a template field declared as `Height:` can be written to `ctx.values` as
`height`, then rejected by `$$Word(Height)`:

```rez
type 1 {
    Height: integer;
    integer = $$Word(Height);
};
resource 1(1) { 7 };
```

Observed result:

```text
GenError: $$Word(Height) refers to a field not yet written
```

Recommended fix: normalize the lookup with `_key(_call_name_arg(call))`, while
preserving the original spelling in diagnostics.

### Medium/low: named-value resolution has the same casing trap

`gsasm/rez/gen.py:620-632` stores named values under `nv.name` and later checks
`val.name` directly. If Rez enum-style names are intended to follow the same
case-insensitive identifier model, valid-looking input is rejected:

```rez
type 1 { integer release=1; };
resource 1(1) { Release };
```

Observed result:

```text
GenError: 'Release' is not one of this field's named values (['release'])
```

Recommended fix: build the table with `_key(nv.name)` and look up `_key(val.name)`.

### Medium/low: accepted identifier type IDs can crash the CLI

`gsasm/rez/parser.py` documents and accepts literal identifier type IDs, and
`gsasm/rez/gen.py:1102-1130` carries `s.typeid` through unchanged into
`GenEntry.rtype`. That works internally for matching `type Foo` to
`resource Foo`, but `gsasm/rez/emit.py:241-244` assumes every resource type is
numeric and applies `& 0xFFFF`.

This accepted input reaches a Python traceback instead of a `gsrez:` error:

```rez
type Foo { byte; };
resource Foo(1) { 7 };
```

Observed result:

```text
TypeError: unsupported operand type(s) for &: 'str' and 'int'
```

Recommended fix: either reject nonnumeric resource type IDs in `generate()` with
a `GenError`, or implement an explicit type-name-to-numeric-ID rule before
entries reach `emit_fork()`.

### Medium/low: out-of-range resource types are silently truncated

Resource types are stored in a 16-bit index field, but `emit_fork()` masks rather
than validates them at `gsasm/rez/emit.py:241-245`.

```rez
type $10000 { byte; };
resource $10000(1) { 7 };
```

`gen.to_emit_tuples()` produces type `65536`, but the emitted fork index stores
type `$0000`.

Recommended fix: validate `0 <= rtype <= 0xffff` before emitting. Do uniqueness
checks after the same normalization rules the emitter uses, so `$0000` and
`$10000` cannot become an accidental collision.

### Medium/low: duplicate final resource keys are emitted unchecked

The compiler allows multiple final resources with the same `(type, id)` key,
including collisions with the synthesized `rResName` entry. `generate()` appends
entries at `gsasm/rez/gen.py:1118-1137`, `to_emit_tuples()` passes them through
at `gsasm/rez/gen.py:1153-1164`, and `emit_fork()` writes one index record per
entry at `gsasm/rez/emit.py:240-245`.

For example:

```rez
type 1 { byte; };
resource 1(1) { 1 };
resource 1(1) { 2 };
```

`gsrez` exits successfully and emits a fork with two index records for the same
resource key. Resource lookup by `(type, id)` is inherently ambiguous in that
output. The same issue can be triggered by naming any resource and also defining
an explicit `resource $8014($00018001)`, which collides with the synthesized
`rResName`.

Recommended fix: validate uniqueness over all final entries before emitting,
including the synthesized `rResName`, and raise `GenError` with both source
locations when a duplicate is found.

### Medium/low: expression domain errors leak raw exceptions or drop data

Accepted expressions are not consistently range-checked before low-level Python
operations:

- `gsasm/rez/gen.py:515-519` divides without a zero check, so `integer = 1/0`
  exits as `ZeroDivisionError`.
- `gsasm/rez/gen.py:798-800` calls `_mask(width)` before validating a bitstring
  width, so `bitstring[-1]` exits as `ValueError: negative shift count`.
- `gsasm/rez/gen.py:867-875` treats a negative bounded-array count as
  `range(-1)`, emitting zero iterations and then dropping the supplied group
  values.

Recommended fix: validate division operands, bit widths, fill counts, and array
bounds in `_eval_expr()` consumers and raise `GenError` with source location.

### Low: malformed CLI numeric metadata escapes as Python tracebacks

`gsasm/__main__.py:145-154` documents `SystemExit` with a `gsrez:`-prefixed
message for malformed `--meta`, but `int(val, 0)` and `bytes.fromhex(...)` can
raise raw `ValueError`. `gsasm/__main__.py:274` does the same for `-t ZZ` via
`int(args.filetype, 16)`.

This does not corrupt output, but it makes the command-line surface brittle and
harder to script.

Recommended fix: catch `ValueError` around these conversions and raise
`SystemExit("gsrez: ...")` with the bad key/value included.

### Low: parser import mutates global `sys.path`

`gsasm/rez/parser.py:329` inserts the repository root into `sys.path` at import
time. The module already imports via `gsasm.rez...`, so this appears unnecessary.
As package code, the side effect can alter unrelated import resolution in callers
or tests.

Recommended fix: remove the `sys.path.insert(...)` and the now-unused `os`/`sys`
imports.

## Checks run

- `python3 tests/run_fixtures.py` - 29/29 fixtures passed
- `python3 tests/test_rez_lexer.py` - 14/14 passed
- `python3 tests/test_rez_parser.py` - 10/10 passed
- `python3 tests/test_rez_gen.py` - 32/32 passed
- `python3 tests/test_rez_pipeline.py` - 3/3 passed
- `python3 tests/test_expressload_case_b.py` - 1/1 passed
- `python3 work/gate.py` - PASS
- `python3 work/gate.py --full` - PASS

`pytest` is not available in this environment.
