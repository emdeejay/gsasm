# Adversarial Review: SOW Implementation

Date: 2026-08-01

Scope reviewed:

- `work/diskmanifest.py`
- `work/manifestcheck.py`
- `work/diskcheck.py`
- `work/gate.py`
- `work/hfs.py`
- `work/disk7check.py`
- `work/installerdatacheck.py`
- `docs/SOW_COMPLETION.md`
- `docs/IMPLEMENTATION_PLAN.md`
- `docs/disk_census_2026-07-30.json`

## Bottom Line

The new byte builders are real: the current tree passes the full gate, Disk 5
and Disk 6 generalized overlays are logical-exact, Disk 7 data-fork builders are
byte-exact, and the Installer data fork is byte-exact.

The SOW completion machinery is still too easy to fool. Several metrics that
read like builder-correctness gates are actually census-label or harness-name
counts. The implementation has not yet reached the fork/payload-level,
machine-checkable acceptance model described by the current SOW.

## Findings

### 1. Physical image equality is printed but not gated for generalized disks

Severity: high.

`work/diskcheck.py::reconstruct()` prints the physical byte-match and returns
`(match, n, ok, total)` (`work/diskcheck.py:363-370`), but `main()` discards the
return value and exits successfully (`work/diskcheck.py:527-529`). The full gate
then scrapes only `logical-exact` for Disk 5 and Disk 6 (`work/gate.py:181-184`).

That means a corrupted overlay can pass the gate as long as the builder bytes
matched the pre-overlay logical fork.

Proof by in-memory fault injection, no file edits:

```text
Disk 5 of 7 Fonts.2mg: Fonts  1600 blocks
  builders wired: 1  logical-exact: 1/1
  PHYSICAL image byte-match: 819152/819264 (99%)
RETURN 819152 819264 1 1
```

The current gate regex would still read `disk5_logical_exact 1/1`.

Impact:

- `disk_physical_exact` is not backed by an enforced diskcheck physical result
  for the generalized disk path.
- P3/P5 can claim whole-image reconstruction while the image differs physically.

Required fix:

- Make `reconstruct()` return nonzero or raise if `match != n`.
- Add gate metrics for physical match, not just logical builder count:
  `disk5_physical_exact`, `disk6_physical_exact`, and later per-disk HFS
  physical metrics.
- Alternatively make the existing `disk*_logical_exact` entries parse both
  logical and physical lines and fail if either fails.

### 2. `manifest_builders_exact` is mostly a census-label count, not builder exactness

Severity: high.

`work/diskmanifest.py:120-122` promotes every census record with
`classification == "built"` to `BUILT`, assigning either a real diskcheck
builder, a `proven_by` string, or the string `"harness"` as `Entry.builder`.
`work/manifestcheck.py:133-138` then counts a `BUILT` entry as exact when
`e.builder is not None`.

That is not a builder exactness check. It does not call a builder, compare bytes,
or tie the manifest entry to a parsed gate metric.

Observed state:

```text
Disk 1 BUILT 36 callable 0 noncallable 36
Disk 3 BUILT 35 callable 0 noncallable 35
Disk 4 BUILT 43 callable 0 noncallable 43
Disk 5 BUILT 1 callable 0 noncallable 1
Disk 6 BUILT 2 callable 0 noncallable 2
Disk 7 BUILT 6 callable 0 noncallable 6
```

Only Disk 2 has direct diskcheck callables; most other "builders" are strings
such as `drivercheck`, `toolcheck`, `disk7check`, or `installerdatacheck`.

Impact:

- Editing the census from `TODO_BUILDABLE` to `built` can improve
  `manifest_builders_wired` and `manifest_builders_exact` without adding a
  callable or a byte comparison.
- A stale `proven_by` string still counts as exact.
- The metric name overclaims: it is closer to `manifest_claimed_built`.

Required fix:

- Replace `builder is not None` with a typed proof object:
  - callable builder plus fork/key and golden source, or
  - harness metric name plus exact path/fork membership assertion.
- Fail if a `BUILT` entry has only a free-form string proof.
- Store proof identity in structured fields, not in `evidence` prose.

### 3. Fork-level ownership is specified but not actually validated

Severity: high.

The SOW requires fork/payload ownership (`docs/SOW_COMPLETION.md:65-83`) and the
implementation plan explicitly defines `ForkKey = (path, 'data'|'rsrc'|...)`
(`docs/IMPLEMENTATION_PLAN.md:48-55`). The implementation still treats fork
data mostly as an opaque string.

Examples:

- `work/diskmanifest.py:109-123` uses `fork = f.get('forks') or 'data'`.
  Values include prose like
  `data=built(...); rsrc=buildable-rez(...) not yet gated`.
- `work/manifestcheck.py:72-78` validates only path sets. It ignores the fork
  component entirely.
- `work/manifestcheck.py:60-69` reports HFS live forks as data-only, even though
  `work/hfs.py` can now read resource forks.

Disk 7 proves the gap. The live HFS image has resource forks:

```text
/System Folder/Basic.System data=10240 rsrc=416
/IWEm data=28523 rsrc=312
/System Folder/p8 data=17128 rsrc=409
/System Folder/Apple //e Boot Blocks data=35221 rsrc=423
/System Folder/ProDOS16 Boot Blocks data=478 rsrc=426
/System Folder/ProDOS16 Image data=92672 rsrc=420
/Apple II Script data=0 rsrc=6421
```

But `work/disk7check.py` explicitly proves only data forks
(`work/disk7check.py:9-17`, `_TARGETS` at `work/disk7check.py:194-202`), while
the census marks the six data-fork targets as `built` even when their resource
forks are still described as buildable Rez (`docs/disk_census_2026-07-30.json`
around the Disk 7 entries).

Impact:

- `manifest_builders_exact 160/160` omits real HFS resource-fork work.
- `manifest_inventory_classified 7/7` can pass with wrong or missing fork
  ownership as long as every path exists.
- `Apple II Script` is classified as `no-source-substitute` even though the
  same census records a buildable Rez source path for its resource fork; that may
  be a valid Mac-Rez policy decision, but it is not represented as a structured
  fork-level state.

Required fix:

- Expand census records into one manifest entry per fork or payload.
- Compare live fork presence and sizes against manifest fork keys.
- For HFS, enumerate both data and resource forks in `manifestcheck`.
- Make `disk7check` either prove resource forks or leave them as explicit
  `TODO_BUILDABLE`/`SUBSTITUTE` entries.

### 4. `TECHNICAL_EXCEPTION` does not block builder-complete status or require acceptance

Severity: high.

The plan says Tool.Setup blocks builder completion until P7 cracks it or a human
explicitly accepts the exception (`docs/IMPLEMENTATION_PLAN.md:127-150`).

The code treats technical exceptions as neither required nor blocking:

- `required = BUILT + TODO_BUILDABLE` (`work/manifestcheck.py:118`)
- `builder_complete = (TODO_BUILDABLE == 0)` (`work/manifestcheck.py:146`)
- substitute confirmation treats `TECHNICAL_EXCEPTION` as confirmed if it has
  non-empty evidence (`work/manifestcheck.py:122-127`)

Current output shows the problem:

```text
Install      BUILT=36/36 SUB=60 TECH=1 [builder-complete (needs overlay)]
System Disk  BUILT=37/37 SUB=12 TECH=1 [RECONSTRUCTED]
```

Impact:

- P7 can be bypassed by classifying Tool.Setup as `technical-exception`.
- There is no machine-readable human acceptance marker for the exception.
- Disk 1 and Disk 2 can be displayed as builder-complete even while the
  case-B wall remains unresolved.

Required fix:

- Add a separate metric, for example `manifest_technical_exceptions_accepted`.
- Treat unaccepted technical exceptions as blockers for builder-complete.
- Include the exception in per-disk completion state, not only in substitute
  evidence.

### 5. Substitute confirmation is only "non-empty evidence"

Severity: medium-high.

The SOW requires every substitute or technical exception claim to be
adversarially source-searched across all trees (`docs/SOW_COMPLETION.md:141-154`,
`docs/IMPLEMENTATION_PLAN.md:169-183`). The implementation checks only whether
the `evidence` string is non-empty (`work/manifestcheck.py:122-127`).

Impact:

- A stale or vague sentence passes as substitute confirmation.
- The historic failure mode this SOW is trying to prevent, false no-source
  claims, is not machine-checked.

Required fix:

- Add structured fields such as `searched_trees`, `search_date`,
  `search_patterns`, and `decision`.
- Fail substitute confirmation if any required tree is missing from the proof.
- Keep free-form evidence, but do not use it as the only gate condition.

### 6. `manifestcheck` prints `PASS` while key completion metrics are still incomplete

Severity: medium.

`manifestcheck.run()` returns success when inventory and substitute evidence are
good (`work/manifestcheck.py:174-176`). It does not include builders or physical
metrics in its own success predicate.

Current output:

```text
manifest_physical_exact good=3 bad=4
PASS (inventory + substitutes-confirmed are the P0 hard gates)
```

The full gate baseline catches regressions, but the standalone command reads as
more complete than it is. That is especially risky because this is the SOW
scoreboard.

Required fix:

- Print `P0 PASS` or `INVENTORY PASS`, not plain `PASS`.
- For Tier A, add a `--tier-a` or separate command mode that fails unless all
  five completion metrics are satisfied.

### 7. `gate.py` ignores subprocess return codes for check scripts

Severity: medium.

`work/gate.py::run_check()` captures stdout/stderr and parses regex metrics, but
does not fail on a nonzero process return code (`work/gate.py:254-276`). If a
script prints a parseable baseline metric and exits nonzero, gate can still pass.

`work/disk7check.py` also returns `(good, total)` from `run()` but does not call
`sys.exit()` with failure status (`work/disk7check.py:229-230`). The current gate
would still catch a bytes metric regression, but command exit status is not a
hard signal.

Impact:

- Check scripts can signal failure in the conventional way and be ignored.
- Future SOW tooling may add fatal validation after printing metrics and assume
  gate catches it.

Required fix:

- In `run_check()`, fail if `proc.returncode != 0` after including the metric
  tail in the error message.
- Update check scripts to return nonzero when their headline exact metric is not
  fully exact.

## Non-Findings

- `python3 work/gate.py --full` passes on the current tree.
- `python3 work/disk7check.py` proves the six Disk 7 data forks it claims:
  `DISK7_BYTES_EXACT 184262/184262`.
- `python3 work/installerdatacheck.py` proves the Installer data fork:
  `INSTALLER_DATA_BYTES_EXACT 56163/56163`.
- `python3 work/diskcheck.py --disk 'Disk 5 of 7 Fonts.2mg'` and Disk 6 both
  produce physical byte-match on the current implementation. The issue is that
  this is not enforced by the gate.

## Recommended Fix Order

1. Gate physical byte-match for generalized disk reconstruction.
2. Stop counting `BUILT` from strings; require structured proof objects.
3. Expand manifest validation to fork/payload keys, starting with HFS resource
   forks.
4. Add an explicit accepted/not-accepted state for `TECHNICAL_EXCEPTION`.
5. Make substitute verification structured instead of free-text-only.
6. Rename or split the standalone `manifestcheck` PASS mode.
7. Make `gate.py` honor subprocess return codes.

## Verification Commands Run

```sh
python3 work/manifestcheck.py
python3 work/diskmanifest.py
python3 work/diskcheck.py --disk 'Disk 5 of 7 Fonts.2mg'
python3 work/diskcheck.py --disk 'Disk 6 of 7 synthLAB.2mg'
python3 work/disk7check.py
python3 work/installerdatacheck.py
python3 work/gate.py --full
git diff --check
```

Key current outputs:

```text
manifest_builders_wired good=160 bad=0
manifest_builders_exact good=160 bad=0
manifest_physical_exact good=3 bad=4
DISK7_BYTES_EXACT 184262/184262
INSTALLER_DATA_BYTES_EXACT 56163/56163
PASS: all metrics at or above baseline
```

