# Review Comments: Completion SOW And Implementation Plan

Date: 2026-07-30

Reviewed:

- `docs/SOW_COMPLETION.md`
- `docs/IMPLEMENTATION_PLAN.md`
- `docs/disk_census_2026-07-30.json`
- `work/diskcheck.py`
- `work/gate.py`
- `work/hfs.py`

## Summary

The SOW and implementation plan are directionally strong: they define a
machine-checkable completion target, use the existing disk image oracle, and
make substitute decisions explicit instead of pretending every byte is
source-derived.

The main problem is that the proposed P0/P2 mechanics can accidentally make
completion look greener than it is. Current `diskcheck.py` deliberately warns
that physical image equality alone is not a builder-correctness gate. Because
unbuilt files remain golden bytes in the overlay buffer, a disk can physically
match while required builders are missing or failing. The plan needs stronger
state categories and metrics before manifest generation is automated.

## Comments

### 1. Do not let `disk_physical_exact` become a false completion metric

Severity: high.

`docs/IMPLEMENTATION_PLAN.md:43` defines `disk_physical_exact` as the fraction
of disks whose physical image byte-match is 100%. That is not enough for this
project. `work/diskcheck.py:13` already says the physical image match alone is
not a builder-correctness gate because a no-builder run is trivially 100%.

If the new manifests keep substitute and not-yet-wired files as golden bytes,
then `disk_physical_exact` can reach 7/7 before the planned builders exist. That
would make the top-line metric misleading.

Suggested change:

- Keep `disk_physical_exact`, but make it secondary.
- Add required metrics such as:
  - `disk_inventory_classified`: every on-disk fork has an owner.
  - `disk_required_builders_wired`: every entry classified as source-built has a callable builder.
  - `disk_required_builders_exact`: every required builder produces logical bytes equal to golden before overlay.
  - `disk_substitutes_confirmed`: every substitute has recorded evidence.
- Define Tier A completion as all of those being complete, not physical byte
  match alone.

### 2. P0 collapses `built` and `buildable`, which breaks the workflow model

Severity: high.

`docs/IMPLEMENTATION_PLAN.md:33` says to seed `built`/`buildable` census entries
as `BUILD(builder)`. That is too coarse. In the census, `built` means a
byte-exact harness or builder already exists. `buildable-asm` and
`buildable-rez` mean source exists but no byte-exact builder is wired yet.

If buildable-but-not-built files are generated as `BUILD(builder)`, P0 either
has to invent placeholder builders or treat missing builders as normal. Both
choices weaken the gate.

Suggested change:

- Model at least four manifest states:
  - `BUILT(builder, evidence)`
  - `TODO_BUILDABLE(kind, source_path, evidence)`
  - `SUBSTITUTE(reason, evidence)`
  - `PARTIAL(...)` or fork-level entries for mixed files
- Only `BUILT` entries count toward required-builder exactness.
- `TODO_BUILDABLE` entries keep `oos` at zero while still blocking Tier A until
  promoted to `BUILT` or explicitly downgraded by a human policy decision.

### 3. The census JSON is not ready to be the sole manifest generator input

Severity: high.

The SOW and implementation plan treat `docs/disk_census_2026-07-30.json` as the
authoritative source for all seven manifests. It is not complete enough in its
current form:

- The JSON has six top-level disk entries, not seven. Disk 2 is omitted.
- Disk 5 has 29 file records in JSON, but the actual disk and the census note
  both have 30 files.
- The missing Disk 5 record appears to be `/Fonts/Icons/Finder.Data`, which the
  live ProDOS enumeration sees.
- `docs/SOW_COMPLETION.md:222` says "354 files", while the same table totals
  355 files.
- `docs/SOW_COMPLETION.md:237` says 57 remaining buildable files, while the
  post-resolution count is 59.

Suggested change:

- Add a P0 validation step before manifest generation:
  - enumerate each disk live;
  - compare every live path/fork against the census JSON;
  - fail on missing, extra, or duplicate census records;
  - merge the existing Disk 2 manifest into the generated census state.
- Regenerate or patch the census JSON before using it as a generator source.

### 4. Completion is currently file-level, but the project is already fork-level

Severity: high.

`docs/SOW_COMPLETION.md:50` says every file is exactly one of `built` or
`substitute`. That does not match current reality. Several important files are
dual-fork or resource-composite cases where one fork or resource payload is
built while another payload is copied from golden bytes.

Examples:

- CDEV resource forks can be byte-exact through Rez while their `rCDEVCode`
  payloads are extraction-fed from the golden fork.
- Finder/Start and EasyMount already have independent data/resource fork
  builders.
- Disk 7 HFS files carry small resource forks even when the data fork is the
  main build target.

Suggested change:

- Define ownership at fork or payload level, not only file path level.
- Allow a file to be "fully accounted for" as a composition of built and
  substituted forks/resources.
- Reserve "built from source" for bytes actually reproduced by source/tools.
  Use "gold-fed" or "extraction-fed substitute" for copied embedded payloads.

### 5. `Tool.Setup` needs an explicit policy state

Severity: high.

The SOW says substitutes are for files where no archived source exists
(`docs/SOW_COMPLETION.md:53`), but `Tool.Setup` has source and is currently the
known ExpressLoad case-B encoding residual. Later sections say it may become a
documented exception if the crack workflow fails.

Those two policies conflict. If `Tool.Setup` remains non-byte-exact but is still
accepted, it is not a normal no-source substitute. It is a technical exception
with source present.

Suggested change:

- Add an explicit manifest state such as `TECHNICAL_EXCEPTION(reason, evidence,
  golden_bytes=True)`.
- Make it human-gated and rare.
- Decide whether Tier A allows this state. If yes, say Tier A is "100% physical
  and 100% accounted for" rather than "all source-bearing files built."
- If Tier A does not allow it, then P7 must be completed before Disk 1 and Disk
  2 can count as complete.

### 6. The phase arithmetic is inconsistent around P4/P5/P7

Severity: medium.

`docs/IMPLEMENTATION_PLAN.md:90` says P3 makes disks 5 and 6 complete, raising
`disk_physical_exact` to 3/7 with Disk 2. Then `docs/IMPLEMENTATION_PLAN.md:93`
says P4 makes disks 1, 3, and 4 complete but reaches only 5/7. That should be
6/7 if Disk 2, 5, and 6 were already complete.

There is also a sequencing conflict: Disk 1 contains `Tool.Setup`, but P7 is
the `Tool.Setup` phase. P4 cannot honestly make Disk 1 100% unless `Tool.Setup`
is either already solved or explicitly accepted as a technical exception.

Suggested change:

- Move `Tool.Setup` before the "Disk 1 complete" acceptance, or keep Disk 1 open
  until P7.
- Recalculate the expected fractions:
  - after P3: 3/7 if Disk 2, 5, 6 are complete;
  - after P4 for disks 1, 3, 4: 6/7, unless Disk 1 remains blocked by Tool.Setup;
  - after P5 Disk 7: 7/7, again assuming Tool.Setup is not blocking.

### 7. The HFS path is underspecified and probably larger than P0 suggests

Severity: medium-high.

`docs/IMPLEMENTATION_PLAN.md:48` says to add `check_hfs(disk)` using
`work/hfs.py`: read, rebuild the HFS B-tree/allocation, overlay built forks, and
physical-match. Current `work/hfs.py` is a minimal read-only data-fork extractor.
It does not expose a `Volume` writer API, resource-fork accessors, catalog
mutation, allocation bitmap updates, or an overlay contract analogous to
`work/diskcheck.py`.

Disk 7 needs resource forks, date/version resources, and likely exact metadata
preservation. That makes HFS more than a small wrapper around the existing file.

Suggested change:

- Split P0:
  - P0a: ProDOS multi-disk manifest model and structured result object.
  - P0b: census validation against live ProDOS/HFS enumeration.
  - P0c: HFS read-only checker that proves path/fork extraction.
  - P0d: HFS overlay writer with selftest using original bytes.
- Do not let the ProDOS manifest work wait on the HFS writer if it can land
  independently.

### 8. Gate wording should distinguish refactors from corpus expansion

Severity: medium.

`docs/SOW_COMPLETION.md:124` and `docs/IMPLEMENTATION_PLAN.md:121` say every
code-touching change must keep gate stdout byte-identical to baseline, and that
even improvements mean behavior changed and should stop. That is appropriate
for refactor packets, but not for builder expansion phases. P2-P7 are supposed
to add coverage and new metrics.

Current `work/gate.py` is direction-aware: improvements pass but are reported
so the baseline can be updated after review. It is not stdout-pinned.

Suggested change:

- For refactors: require unchanged metrics and no stdout/reporting drift unless
  the refactor explicitly targets reporting.
- For expansion: allow reviewed metric improvements, require no regressions,
  and update `work/gate_baseline.json` in the same accepted packet.
- For new metrics: fail until a baseline is committed.

### 9. Tier C scope is inconsistent between the SOW and implementation plan

Severity: medium.

`docs/SOW_COMPLETION.md:45` and `docs/SOW_COMPLETION.md:69` define Tier C as
R10 plus deep-dive D1-D8. The workstream and implementation plan later include
only R10, D1, D3, D4, and D5.

Suggested change:

- Either redefine Tier C as the selected subset `R10 + D1 + D3 + D4 + D5`, or
  add explicit acceptance/defer decisions for D2, D6, D7, and D8 from
  `docs/REFACTORING_DEEP_DIVE_2026-07-30.md`.

### 10. P2 needs a sharper acceptance metric than "built files match"

Severity: medium.

`docs/IMPLEMENTATION_PLAN.md:56` describes wiring 105 already-built files. That
is a good phase, but its acceptance should not be `oos:0` or physical match.
Those can be true while no new builder is wired.

Suggested change:

- Track a per-disk/per-fork count:
  - expected built entries;
  - builders wired;
  - logical-exact builders;
  - built bytes covered.
- For duplicate artifacts, record whether the target disk copy was independently
  compared to the already-gated source artifact before reusing the builder.

## Suggested Patch Direction

I would not rewrite the SOW yet. First make a small accuracy packet:

1. Fix the census/count inconsistencies:
   - SOW "354" vs 355.
   - SOW 57 vs 59 buildable.
   - Disk 5 JSON missing `/Fonts/Icons/Finder.Data`.
   - Document that the JSON excludes Disk 2 and must be merged with the existing
     Disk 2 manifest.
2. Add the missing manifest states:
   - `BUILT`
   - `TODO_BUILDABLE`
   - `SUBSTITUTE`
   - `TECHNICAL_EXCEPTION`
   - fork/payload-level ownership where needed.
3. Revise the completion predicate so it is not only physical byte equality.
4. Split HFS work into explicit read, validate, and write/selftest stages.
5. Recalculate P3-P7 fractions after the `Tool.Setup` policy is settled.

## Verification Performed

Commands run during this review:

```sh
python3 work/diskcheck.py
python3 work/gate.py --full
python3 - <<'PY'
import json
from collections import Counter
data = json.load(open('docs/disk_census_2026-07-30.json'))
for disk_name, disk in data['disks'].items():
    print(disk_name, len(disk.get('files', [])))
PY
```

Observed current baseline:

- `work/diskcheck.py`: Disk 2 only, 50 files, `builders wired: 39/40`,
  `logical-exact: 39/39`, physical `819264/819264`.
- `work/gate.py --full`: pass, including `disk_logical_exact good=39 bad=0`.
- Live ProDOS enumeration shows Disk 5 has 30 files; census JSON has 29 records.

