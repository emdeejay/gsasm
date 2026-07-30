# Adversarial Review: R9 Refactor + Release Docs, 2026-07-30

Scope reviewed: `origin/main..HEAD` at `3ec5eb4`:

- `56aebf3` docs+config: pre-0.4.0 accuracy pass; Python floor 3.10.
- `3ec5eb4` refactor(R9): decompose `expressload()` into dispatcher plus
  single/multiseg builders.

The worktree was clean before review. This pass focused on adversarially checking
whether the `expressload()` refactor preserved behavior and whether the release
accuracy/docs pass actually leaves the repo with one coherent source of truth.

## Summary

No functional regression was found in the `expressload()` refactor under the
available gates. The risky paths passed:

- `tool_bytes` stayed at `193357/0`.
- `finder_data_bytes_exact` stayed at `293848/0`.
- ROM rebuild stayed byte-identical.

The remaining issues are release/documentation hygiene, plus one mechanical
`diff --check` failure. They are not runtime regressions, but they undermine the
purpose of the pre-0.4.0 accuracy pass.

## Finding 1: README still advertises Python 3.9 support

Severity: medium for release readiness.

`pyproject.toml` and CI now declare Python 3.10 as the floor:

- `pyproject.toml:11`: `requires-python = ">=3.10"`
- `.forgejo/workflows/tests.yml:13`: matrix is `["3.10", "3.12", "3.14"]`

But the README still says:

- `README.md:78`: `Requires Python 3.9+. No dependencies outside the standard library.`

This is a direct contradiction in user-facing installation docs. Anyone using
the README as the source of truth can reasonably try Python 3.9, while package
metadata will reject it.

Suggested fix: change the README line to Python 3.10+.

Claude response requested: confirm whether the intended floor is 3.10, then
patch the README or explain why `pyproject.toml`/CI should instead revert.

## Finding 2: REFACTORING.md is stale in proof-critical status text

Severity: medium.

`docs/REFACTORING.md` was updated to mark R9 complete, but it still contains
several stale claims:

- `docs/REFACTORING.md:14`, `:288`, `:299`, `:375`: cite commit `e2126dd`.
  That object exists locally, but it is not an ancestor of `HEAD`; the branch
  commit is `3ec5eb4`.
- `docs/REFACTORING.md:29` and `:52`: still say `53/53` fixtures. The current
  fixture suite is `62/62`.
- `docs/REFACTORING.md:31`: still says the gate has 13 metrics. The current
  committed baseline has 24 metrics.
- `docs/REFACTORING.md:194-203`: R4 still describes the old Python 3.9 floor
  and a 3.9/3.12/3.14 CI matrix, contradicting the new 3.10 floor.

This file is used as a refactor/release source of truth, so stale proof text is
not harmless. It makes reviewers re-verify whether the guide or the gate is
current.

Suggested fix: update the R9 commit reference to `3ec5eb4`, change fixture/gate
counts to the current values, and revise R4 to describe the now-landed Python
3.10 floor instead of the old 3.9 hygiene problem.

Claude response requested: patch the stale references or identify which ones are
intentionally historical and should be labeled as such.

## Finding 3: GSOS_MILESTONES still describes full-file ExpressLoad residuals

Severity: low to medium.

The same file now claims full on-disk ExpressLoad byte-exactness for the mapped
tools:

- `docs/GSOS_MILESTONES.md:41`: diskcheck logical-exact is `39/39`.
- `docs/GSOS_MILESTONES.md:64-66`: full on-disk ExpressLoad files are
  byte-exact too.

But the M4 milestone text still says:

- `docs/GSOS_MILESTONES.md:80-86`: the gated code-image corpus is byte-exact,
  while remaining full on-disk ExpressLoad mismatches are tracked separately by
  `work/diskcheck.py`.

That was true historically, but it contradicts the updated 39/39/full-file exact
claims in the same document.

Suggested fix: rewrite M4 to say the full-file ExpressLoad residuals for the
mapped/disk-gated corpus are closed, with diskcheck as the proof rather than a
residual tracker.

Claude response requested: clarify whether any full-file ExpressLoad residual
still exists outside the gated corpus. If not, patch M4 to match the current
results.

## Finding 4: `git diff --check` fails

Severity: low.

`git diff --check origin/main..HEAD` reports:

```text
gsasm/expressload.py:2143: new blank line at EOF.
```

This is trivial, but it is exactly the kind of mechanical issue that should not
survive a release/refactor cleanup branch.

Suggested fix: remove the extra trailing blank line.

Claude response requested: patch the EOF whitespace and rerun
`git diff --check origin/main..HEAD`.

## Non-Findings

The `expressload()` decomposition itself looks behavior-preserving under the
available evidence. The dispatcher still performs option normalization, segment
placement, and symbol table construction before splitting into the single- and
multi-segment builders. The single-segment and multiseg paths passed the
corpus-free tests and golden gate.

I did not find a functional issue in `_build_single_output_seg()` or
`_build_multiseg_output()` during this pass.

## Verification Run

Commands run from `/Users/mdj/src/gsasm`:

```sh
python3 tests/run_fixtures.py
```

Result: `62/62 fixtures pass`.

```sh
for t in tests/test_*.py; do python3 "$t"; done
```

Result: all test files passed, including the ExpressLoad case-B, Finder,
super-class, and shift-defer guards.

```sh
python3 work/gate.py
```

Result: `PASS: all metrics at or above baseline`, including:

- `tool_bytes good=193357 bad=0`
- `finder_data_code_bytes good=135444 bad=0`
- `finder_reloc_segs_exact good=13 bad=0`
- `finder_data_bytes_exact good=293848 bad=0`
- `mountimage_data_bytes_exact good=5750 bad=0`

```sh
python3 work/buildrom.py | tail -5
```

Result: full ROM image verified byte-identical; `261377` bytes source-built
byte-exact, output `work/rom.03.built` at `262144` bytes.

```sh
git diff --check origin/main..HEAD
```

Result: failed only on the extra blank line at EOF in `gsasm/expressload.py`.
