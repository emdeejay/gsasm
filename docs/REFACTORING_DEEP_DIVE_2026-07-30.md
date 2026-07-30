# Refactoring Deep Dive: Post-R9 Opportunities

Date: 2026-07-30

Scope: `gsasm/`, `work/`, and `tests/` after the R9 ExpressLoad
decomposition and the follow-up release-doc accuracy pass.

This is not a request to refactor everything that is large. Several large
sections are transcriptions of historical build recipes or byte-exact encoder
rules, and the safest move is often to improve isolation and tests before
changing shape. The recommendations below prioritize changes that reduce
future bug risk without hiding provenance or making byte diffs harder to
explain.

## Executive Summary

The best refactor opportunities are:

1. Clean live code-comment drift in `work/` before another release.
2. Finish low-risk `work/_common.py` consolidation so check scripts share path
   setup, comparison, and reporting helpers.
3. Decompose `gsasm/expressload.py::_build_multiseg_output` into named phases
   while preserving the current algorithm.
4. Finish the OMF relocation classifier unification described by P3 by routing
   remaining finite-difference detectors through one decomposition path.
5. Continue small, behavior-preserving extractions inside `gsasm/asm.py`
   instead of splitting the `Asm` class wholesale.
6. Split the largest build harness functions only where the split exposes
   stable domain boundaries: seed construction, fork overlay comparison, resource
   emission, and tool recipe metadata.

The least attractive refactors right now are broad rewrites of the assembler
dispatcher, parser unification between assembly and Rez, and table-driven
rewrites of toolset build scripts. Those would move a lot of code while
increasing the chance of silent byte drift.

## Current Shape

Measured with AST-based line counts and simple import scans.

Repository scale:

| Area | Files | Lines | Functions | Classes |
| --- | ---: | ---: | ---: | ---: |
| `gsasm/` | 16 | 12,614 | 367 | 46 |
| `work/` excluding archive | 45 | 10,209 | 303 | 5 |
| `tests/` | 18 | 3,696 | 161 | 0 |

Largest files:

| File | Lines | Notes |
| --- | ---: | --- |
| `gsasm/asm.py` | 3,382 | Single large state machine class. |
| `gsasm/expressload.py` | 2,142 | Encoder plus disk-oriented ExpressLoad packer. |
| `gsasm/omf.py` | 1,436 | OMF parser/emitter and relocation classifiers. |
| `gsasm/rez/gen.py` | 1,369 | Rez resource generator. |
| `work/kernelcheck.py` | 1,073 | Kernel byte-exact harness and segment builder. |
| `gsasm/rez/parser.py` | 991 | Recursive-descent Rez parser. |
| `tests/test_rez_gen.py` | 899 | Dense but useful coverage. |
| `gsasm/linkiigs.py` | 828 | IIgs linker and SUPER output path. |
| `work/toolcheck.py` | 728 | Tool linker verification harness. |
| `gsasm/rez/lexer.py` | 716 | Lexer, preprocessor, and expression parser. |

Largest functions or classes:

| Symbol | Location | Lines | Refactor Read |
| --- | --- | ---: | --- |
| `Asm` | `gsasm/asm.py:448` | 2,672 | Too central to split wholesale. Prefer internal phase extraction. |
| `_build_multiseg_output` | `gsasm/expressload.py:1275` | 742 | Top target. Long, phase-oriented, and recently stabilized. |
| `_Parser` | `gsasm/rez/parser.py:523` | 453 | Large but coherent recursive descent parser. Lower priority. |
| `_build_scm_segments` | `work/kernelcheck.py:532` | 294 | Split seed construction from link recipe. |
| `emit_segment` | `gsasm/omf.py:1143` | 264 | Extract literal run writer and record emission helpers later. |
| `link_finder` | `work/finderdatacheck.py:144` | 256 | Byte-exact harness; refactor only around shared helpers. |
| `_build_symtab` | `gsasm/linkiigs.py:224` | 234 | Consider after OMF classifier work. |
| `_raw_tokenize` | `gsasm/rez/lexer.py:174` | 208 | Extract token scanners with exact token-stream tests. |
| `_expr_for` | `gsasm/omf.py:759` | 206 | Classifier hub; refactor after P3 detector consolidation. |
| `kernelcheck.main` | `work/kernelcheck.py:894` | 176 | CLI/reporting split after helper consolidation. |

## Opportunity 0: Live Comment And Docstring Drift

Priority: immediate, low risk.

This is not a structural refactor, but it should come first because stale
comments make later refactors harder to review. Several live files still
describe pre-R9 state even though docs were corrected.

Examples:

| File | Current Problem |
| --- | --- |
| `work/toolcheck.py:22` | Docstring still says all 11 mapped tools and `150459` bytes. Current status is 14 mapped tools and `193357` bytes. |
| `work/diskbuilders/expressload_files.py:14` | Header still describes 11 mapped tools and residual `Tool015`, `Tool016`, `Tool018`, `Tool034` gaps. Those were R9 targets. |
| `work/diskbuilders/expressload_files.py:157` | Per-tool comments still mention generic full-file builder length residuals for tools now covered by diskcheck. |
| `work/diskbuilders/toolsets.py:25` | Header says the builder has a logical residual and is not byte-exact, while the same file later says TS2/TS3 are byte-exact today. |
| `work/diskbuilders/kernel_setup.py:11` | Historical limitation text should be checked against current P8 and Tool.Setup behavior so it does not imply the wrong blocker. |

Recommended change:

- Patch only comments/docstrings.
- Add a small drift check to `work/gate.py` or a separate maintenance script
  later if these numbers keep recurring.

Verification:

- `git diff --check`
- No runtime tests required for comment-only changes.

## Opportunity 1: Finish `work/_common.py` Consolidation

Priority: high, low-to-medium risk.

R2 is partially done. `work/_common.py` already centralizes repository path
setup, include path builders, golden-file candidates, error filters, and byte
comparison helpers. The remaining duplication is mostly harness boilerplate.

Current signals:

| Signal | Count |
| --- | ---: |
| Files importing `_common` | 40 |
| Remaining direct `sys.path` setup in non-archive `work/` files | 18 |
| Files using `byte_match` | 12 |
| Files using `first_diff` | 8 |
| Files using `mismatch_offsets` | 11 |
| Direct `os.walk` include scans outside `_common.py` | 0 |

Recommended extraction:

- `compare_and_report(name, actual, expected, *, max_mismatches=...)`
- `compare_file_bytes(actual_path, expected_path, *, logical_name=...)`
- `candidate_or_die(...)` around existing candidate lookup patterns
- `main_status_exit(results)` for the repeated PASS/FAIL-to-exit-code shape
- A single bootstrap helper for scripts that still pre-insert the repo path

Files to start with:

- `work/drivercheck.py`
- `work/fstcheck.py`
- `work/p8check.py`
- `work/linkrom.py`
- `work/romcov.py`
- `work/loader_placed.py`

Files to defer:

- `work/toolcheck.py`
- `work/diskcheck.py`
- `work/kernelcheck.py`

Those have richer reporting and should be migrated after the helper API has
proved stable.

Verification:

- Capture stdout before and after for each migrated script.
- `python3 work/gate.py`
- `python3 work/buildrom.py`

## Opportunity 2: Decompose ExpressLoad Multi-Segment Output

Priority: high, high risk.

`gsasm/expressload.py::_build_multiseg_output` is the largest ordinary function
in the repository at about 742 lines. It is no longer a speculative area after
R9: diskcheck is 39/39, and the one known remaining full-file ExpressLoad case
is `Tool.Setup`, which is deliberately not disk-wired.

The function is phase-oriented today:

| Phase | Approximate Location | Responsibility |
| --- | --- | --- |
| Group planning | `gsasm/expressload.py:1292` | Map object segments to output groups and bounds. |
| Jump-table planning | `gsasm/expressload.py:1351` | Handle dynamic/final segment numbering. |
| Fallback symbol construction | `gsasm/expressload.py:1415` | Seed symbols when references resolve through external maps. |
| Group image construction | `gsasm/expressload.py:1448` | Build packed group payloads and metadata. |
| Standalone and case-B relocation handling | `gsasm/expressload.py:1523` | Convert or preserve relocation records. |
| Final SUPER relocation classification | `gsasm/expressload.py:1674` | Classify relocs once final group layout is known. |
| Output framing | `gsasm/expressload.py:1935` | Emit bytes and optional diagnostics. |

Recommended shape:

- Keep the public `expressload(...)` dispatcher intact.
- Extract `_plan_output_groups(...)`.
- Extract `_plan_jump_table(...)`.
- Extract `_build_group_image(...)`.
- Extract `_emit_group_relocations(...)`.
- Extract `_finish_super_payload(...)`.
- Use small typed records only when they replace ambiguous tuples or parallel
  arrays. Avoid a broad object model for now.

What not to change:

- Do not change the byte-level relocation encoding decisions in the first pass.
- Do not merge Tool.Setup special behavior into the disk-wired path.
- Do not rewrite this as a class until the extracted functions show stable
  inputs and outputs.

Verification:

- `python3 tests/test_expressload.py`
- `python3 tests/test_expressload_finder.py`
- `python3 tests/test_expressload_prodos.py`
- `python3 work/toolcheck.py 015`
- `python3 work/toolcheck.py 016`
- `python3 work/toolcheck.py 018`
- `python3 work/toolcheck.py 020`
- `python3 work/finderdatacheck.py`
- `python3 work/diskcheck.py`
- `python3 work/gate.py`
- `python3 work/buildrom.py`

Acceptance criterion:

- Exact byte identity must hold for all existing passing artifacts. This
  refactor is not done if any change is explained as "equivalent".

## Opportunity 3: Finish OMF Relocation Classifier Unification

Priority: high, high risk.

`docs/design/P3_DECOMPOSE.md` describes the right direction: normalize OMF
relocation expression detection around one decomposition mechanism. The code is
partway there.

Already unified:

- `gsasm/omf.py:326` defines `linear_decompose`.
- `gsasm/omf.py:400` uses it in `_linear_reloc`.
- `gsasm/omf.py:590` uses it in `_diff_reloc`.

Still duplicated or specialized:

- `gsasm/omf.py:468` `_grouped_linear_reloc`
- `gsasm/omf.py:532` `_mul_reloc_expr`
- `gsasm/omf.py:703` `_extern_diff_expr`
- `gsasm/omf.py:759` `_expr_for`

Recommended shape:

- Add an internal "basis evaluator" that can evaluate an expression with one
  symbol set to a nonzero probe while all other relevant symbols are zeroed.
- Have `_mul_reloc_expr` and `_extern_diff_expr` call the same decomposition
  primitive used by `_linear_reloc` and `_diff_reloc`.
- Keep `_expr_for` as the policy hub at first; reduce detectors before reducing
  the dispatcher.
- Add oracle tests that enumerate representative expressions and assert the
  chosen OMF opcode sequence, not just final linked bytes.

Why this matters:

- The current duplication makes it easy for new relocation support to pass one
  path and miss another.
- A shared detector reduces the chance that assembler, linker, and
  ExpressLoad/SUPER output disagree about the same expression form.

Verification:

- Unit-level OMF expression classifier tests.
- `python3 tests/test_omf.py`
- `python3 tests/test_linkiigs.py`
- `python3 tests/run_fixtures.py`
- `python3 work/gate.py`
- `python3 work/buildrom.py`

## Opportunity 4: Continue Internal Assembler Extractions

Priority: medium-high, medium risk.

`gsasm/asm.py` is large because it is a real assembler state machine. A class
split would be risky and probably not clarify much. The better path is to keep
extracting small internal phases with precise tests.

Best targets:

| Symbol | Location | Lines | Suggested Extraction |
| --- | --- | ---: | --- |
| `define_label` | `gsasm/asm.py:1317` | 171 | Split record-field handling, collision policy, and final binding registration. |
| `dispatch` | `gsasm/asm.py:2254` | 163 | Extract remaining SETA/SETB/SETC and simple state-directive handlers. |
| `_proc` | `gsasm/asm.py:2881` | 120 | Extract PROC operand parsing from ORG/TEMPORG/ALIGN side effects. |
| `call_builtin` | `gsasm/asm.py:936` | 121 | Split argument preparation from builtin dispatch if new builtins are added. |

Recommended sequence:

1. Extract predicate-free helpers first: code that receives already-parsed
   values and mutates state in the same order as today.
2. Add targeted fixture runs for affected syntax before and after.
3. Avoid replacing the directive ladder with a registry until most handlers are
   independently testable.

Fixture focus:

- Record and local-label cases: fixtures around 036, 039, 042, 044.
- Macro and variable cases: fixtures around 048, 049, 051.
- PROC and ORG behavior: fixtures around 056, 059, 060, 063.

Verification:

- `python3 tests/run_fixtures.py`
- `python3 work/gate.py`
- `python3 work/buildrom.py`

## Opportunity 5: Split Kernel And Disk Harness Logic Around Stable Domains

Priority: medium, medium risk.

The build harnesses are intentionally procedural, but several large functions
mix domain data construction with comparison/reporting flow.

Targets:

| File | Target | Refactor |
| --- | --- | --- |
| `work/kernelcheck.py:532` | `_build_scm_segments` | Extract SCM export seeding, self-placed segment seeding, and placed export seeding. |
| `work/kernelcheck.py:894` | `main` | Split CLI setup, build, compare, and report phases after `_common` helpers land. |
| `work/diskcheck.py:281` | fork overlay helpers | Merge duplicate data/resource fork build-and-overlay flows behind one helper. |
| `work/diskbuilders/kernel_os.py` | kernel segment builders | Consider sharing seed construction with `kernelcheck.py` only after tests prove identical output. |

Recommended rule:

- Extract around named historical concepts: SCM segments, loader globals,
  self-placed exports, resource fork overlays. Avoid generic helpers that hide
  the source recipe.

Verification:

- `python3 work/kernelcheck.py`
- `python3 work/diskcheck.py`
- `python3 work/gate.py`
- `python3 work/buildrom.py`

## Opportunity 6: Keep Rez Refactors Local To Emission And Lexing

Priority: medium, low-to-medium risk.

Rez support is dense but comparatively well-contained. The parser is large but
regular; the generator and lexer have more obvious extraction points.

Generator targets:

| Symbol | Location | Lines | Suggested Extraction |
| --- | --- | ---: | --- |
| `_emit_field_list` | `gsasm/rez/gen.py:1096` | 97 | Split list traversal from per-field emission. |
| `generate` | `gsasm/rez/gen.py:1252` | 91 | Separate resource ordering from output assembly. |
| `_write_field_value` | `gsasm/rez/gen.py:869` | 55 | Dispatch to per-basetype emitters. |
| `_write_string_like` | `gsasm/rez/gen.py:809` | 58 | Keep as a specialized helper but isolate length-prefix behavior. |

Lexer targets:

| Symbol | Location | Lines | Suggested Extraction |
| --- | --- | ---: | --- |
| `_raw_tokenize` | `gsasm/rez/lexer.py:174` | 208 | Extract comment, string, hex, number, and identifier scanners. |
| `_Preprocessor` | `gsasm/rez/lexer.py:406` | 185 | Split include handling from macro conditional flow if it grows again. |

What not to do:

- Do not unify the Rez expression parser with `gsasm/expr.py` just because both
  parse expressions. The grammars have different historical constraints.
- Do not split `_Parser` first; it is large, but it is not the highest-risk
  maintenance bottleneck.

Verification:

- `python3 tests/test_rez_lexer.py`
- `python3 tests/test_rez_parser.py`
- `python3 tests/test_rez_gen.py`
- `python3 work/rezcheck.py`
- `python3 work/gate.py`

## Opportunity 7: Treat Tool Recipes As Data, But Defer Full Centralization

Priority: medium-low now, high later.

There is duplication across:

- `work/toolcheck.py`
- `work/diskbuilders/expressload_files.py`
- `work/diskbuilders/toolsets.py`

The duplication is annoying, but it also preserves provenance. Toolset source
order, jump-table entries, flags, and file boundaries are byte-significant.
A premature central `tool_specs.py` could make the build cleaner while making
historical exceptions harder to audit.

Recommended path:

1. Fix stale comments first.
2. Introduce a read-only shared spec for one low-risk mapped tool.
3. Have both `toolcheck.py` and one diskbuilder consume it.
4. Prove exact byte identity.
5. Expand only after the diff is boring and the spec reads better than the
   source files it replaces.

Good pilot criteria:

- A tool with no active residuals.
- No special case-B relocation behavior.
- No source-order workaround.
- Existing standalone and diskcheck coverage.

Verification:

- Targeted `toolcheck` for the pilot.
- `python3 work/diskcheck.py`
- `python3 work/gate.py`

## Opportunity 8: Implement R10 Assembly Cache Only After Harness Cleanup

Priority: medium-low, useful for developer speed.

The existing refactoring guide keeps R10 open: an opt-in assembly cache behind
`GSASM_CACHE=1`, disabled by default and forbidden for blessed updates. That
still looks like the right design, but it should wait until `work/_common.py`
owns more common harness behavior.

Recommended guardrails:

- Cache key includes assembler/linker code hashes, command-line options,
  include paths, source file mtimes and sizes, and environment knobs that affect
  assembly.
- Cache is opt-in only.
- `--update`, bless, or golden-output modes must assert the cache is disabled.
- Cache files live under `work/.cache/`.

Verification:

- Run a target once cold and once warm; assert identical output and visible
  cache hit reporting.
- Mutate an include file and assert invalidation.
- `python3 work/gate.py` with cache disabled.
- Selected harnesses with `GSASM_CACHE=1`.

## Opportunity 9: Tests And CLI Structure

Priority: lower, low-to-medium risk.

`tests/test_rez_gen.py` is large at 899 lines, but that size mostly reflects
coverage breadth. It should not be split just for aesthetics. Split only when a
new behavior group needs its own helper or fixture setup.

`gsasm/__main__.py:164` has a 143-line `rez_main`. A modest split would help:

- Parse CLI options.
- Build include/type context.
- Compile resources.
- Write output.
- Format diagnostics.

This is useful if the CLI grows more options, but it is not a current bottleneck.

Verification:

- Existing CLI tests, if added.
- `python3 tests/test_rez_gen.py`
- `python3 work/rezcheck.py`

## Suggested Sequence

1. **D0: Drift cleanup.** Patch stale live comments/docstrings in `work/`.
   This has nearly zero behavioral risk and improves the review surface.
2. **D1: Harness helper pass.** Finish low-risk `work/_common.py` consolidation
   in small scripts and preserve stdout.
3. **D2: Optional cache R10.** Add opt-in cache once common harness entry points
   exist.
4. **D3: ExpressLoad split.** Decompose `_build_multiseg_output` by current
   phases, with byte-identity tests at every step.
5. **D4: OMF P3 follow-through.** Consolidate remaining relocation detectors
   through the shared decomposition path.
6. **D5: Assembler internals.** Extract `define_label`, `_proc`, and remaining
   directive handlers in small commits.
7. **D6: Kernel/disk harness split.** Extract seed construction and overlay
   comparison helpers.
8. **D7: Rez generator/lexer cleanup.** Split emission and raw token scanning
   helpers.
9. **D8: Tool recipe spec pilot.** Only after the above makes drift easier to
   detect.

## Anti-Goals

- Do not split `Asm` into multiple collaborating classes as a first move.
- Do not table-drive the full assembler directive dispatcher yet.
- Do not normalize all parsers into one expression engine.
- Do not centralize every tool recipe in one data file until a one-tool pilot
  proves the idea.
- Do not accept byte-equivalent arguments for generated artifacts. The project
  standard is byte-exact output unless a document explicitly says otherwise.
- Do not refactor archive material unless it is promoted back into a live build
  path.

## Recommended Review Standard For Each Refactor

Every refactor PR or commit should state:

- Which byte-producing paths changed.
- Which historical outputs were compared.
- Whether stdout changed for affected `work/` scripts.
- Whether `work/gate.py` and `work/buildrom.py` were run.
- Whether any docs or comments still mention superseded counts or residuals.

For high-risk areas, the minimum bar should be:

- Focused unit or harness tests for the touched path.
- `python3 tests/run_fixtures.py`
- `python3 work/gate.py`
- `python3 work/buildrom.py`
- `git diff --check`

## Measurement Commands Used

```sh
wc -l gsasm/*.py gsasm/rez/*.py work/*.py work/diskbuilders/*.py tests/*.py
python3 - <<'PY'
import ast
from pathlib import Path

for p in list(Path('gsasm').rglob('*.py')) + list(Path('work').rglob('*.py')):
    if 'archive' in p.parts:
        continue
    tree = ast.parse(p.read_text())
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            end = getattr(node, 'end_lineno', node.lineno)
            print(end - node.lineno + 1, p, node.lineno, node.name)
PY
rg -n "sys\.path|byte_match|first_diff|mismatch_offsets|all 11|150459|Tool015|Tool016|Tool018|Tool034" work gsasm docs
```
