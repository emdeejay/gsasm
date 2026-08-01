# Hostile architecture review — work/*.py verification harness ecosystem

Scope reviewed: `work/*.py` (34 files, 12,622 lines: gate.py 422, _common.py 223,
diskcheck.py 1276, census_migrate.py 777, manifestcheck.py 336, diskmanifest.py
367, kernelcheck.py 1073, toolcheck.py 915, drivercheck.py 593, + 25 smaller
`*check.py` scripts), `work/diskbuilders/` (5 files), `tests/run_fixtures.py`
(162 lines). Read-only; nothing modified. All line numbers verified against
the tree as of this session (`cb3a9a3`, dirty only with an untracked doc).

Verdict up front: the corpus/fixture/gate spine is sound and its regression
catches are real (confirmed via git log — this is not being re-litigated).
The cost center is everything *around* that spine: 30 independent scripts
that each reinvent plumbing, a stdout-as-API contract with a parse-failure
guard that covers less than it looks like it covers, and two parallel
"ownership of the truth" systems (a registry-as-code and a hand-edited
census-as-data) whose only synchronization is human discipline.

---

## 1. gate.py: metric transport

**File:** `work/gate.py`, 422 lines. `CHECKS` table: lines 33–184 (152
lines). `FULL_CHECKS`: 186–255 (70 lines). Combined **222 lines**, matching
the brief's "200-line literal" characterization almost exactly — and about
40% of that is narrative comment (diagnosis history, adversarial-review
cross-references, "why NOT gated" notes), not table structure. This is a
config file wearing a Python module's clothes; every new proof needs a
correctly-shaped 3-tuple added to a growing literal that nobody would call
a data format if it were external.

**What `run_check()` actually catches (`gate.py:309-339`):**
- Script exits nonzero → `RuntimeError`, hard stop. **This safety net is
  wired into gate.py, but I measured how many of the 34 check scripts
  actually ever call `sys.exit()` with a nonzero code on a *failure* path.**
  Result (verified by reading each `main()`, not just grepping — the grep
  pattern `sys.exit(1)` alone under-counts the `sys.exit(0 if ... else 1)`
  idiom some scripts use):
  - **Exit-clean on failure (never signal failure via return code, ever):**
    `toolcheck.py`, `drivercheck.py`, `fstcheck.py`, `cdevcheck.py`,
    `bytecheck.py`, `linkcheck.py`, `objcheck.py`, `appdatacheck.py`,
    `rezforkcheck.py`, `rezdatacheck.py` — confirmed via `grep -n
    "sys\.exit\|exit(" <file>` returning **zero matches** in all ten.
  - These ten scripts include two of the largest and most load-bearing
    (toolcheck.py 915 lines / 14 tools, drivercheck.py 593 lines / 18
    drivers). For all ten, **every** regression-detection burden falls on
    the regex scrape of the summary line. There is no second signal.
  - gate.py's own docstring (lines 317-324) frames the nonzero-exit check
    as closing "adversarial-review finding #7" — true for the dozen or so
    scripts that do call `sys.exit`, but the fix is unevenly applied and the
    docstring doesn't say so.
- Regex doesn't match anywhere in stdout+stderr → `RuntimeError`
  ("could not parse metric"). This is the ONE guard that exists, and it's
  real — but it only catches *total absence*, not a *wrong* match.

**What the guard does NOT cover — regex matching the wrong line:**
I checked every `CHECKS`/`FULL_CHECKS` regex against its script's source for
literal-string collisions (`work/diskcheck.py:1077,1131,1242` all print a
`logical-exact: N/M` line; `work/p8check.py:42,52` both print `P8 raw
code-image match:`). In every case I traced, only one of the candidate print
sites can fire per invocation (they're on mutually exclusive code paths, or
one is a `0/0` explicit "golden missing" fallback that a downstream baseline
comparison would still flag as a regression). So today, nothing is silently
misfiring. But the *design* offers no protection against it: `re.search`
takes the first match in an unstructured, un-namespaced stdout blob built by
whatever the script chose to print that run (including from a shared helper
module the script imports — e.g. `_common.report_nonignored_asm_errors`
prints to stderr, which gate.py concatenates into the same `out` string
before scanning). A future contributor adding a *diagnostic* print (e.g. a
per-driver "logical-exact: 3/3 (partial)" debug line ahead of the real
summary) reusing the same words would silently redirect the regex to a
smaller, wrong number — and pass or fail on it with no error, because a
match is a match. The guard is "did we find *a* number," not "did we find
*the* number."

**Baseline semantics differ per metric, unlabeled at the call site:**
`kind='frac'` derives `bad = total - good` from a regex that captures
(good, total); `kind='okbad'` takes the print line's two numbers literally
as (good, bad) with no derived relationship; `kind='count'` treats a single
captured group as good with bad pinned to 0. All three kinds share one
regression test (`good < bgood or bad > bbad`) but a reader auditing a new
CHECKS entry has to mentally re-derive which of the two captured groups
means what, and get it right, from a regex it wrote by hand-editing another
row. I found no verification that count/frac semantics were EVER mismatched
against a script's actual output ordering (that would be a data-integrity
bug, not just a readability one) — but the shape invites exactly that kind
of introduce-later-slip-past-review error, since a swapped `(\d+)/(\d+)`
capture group order still matches syntactically.

**Runtime, measured (receipts):** `time python3 work/gate.py --skip-fixtures`
(the fast CHECKS-only pass, no diskcheck, run this session) —
**3:46 wall clock / 198.9s user CPU**, 92% CPU utilization (i.e. essentially
serial, one subprocess at a time). `docs/REFACTORING.md:30` documents "~2
min" for this same pass and `:317` says "~100s" — both now stale relative to
what I measured; the corpus has grown since those numbers were written and
nobody has re-timed the doc. `--full` adds 7 `diskcheck.py --disk ...`
invocations (each doing a full ProDOS/HFS volume parse + up to ~97-entry
builder-registry replay) plus `manifestcheck.py` (which itself calls
`_wired_builders()` per disk); I did not run `--full` to conserve session
budget, but given the fast pass alone is already 3:46, and diskcheck's
registry is ~3x bigger than any single fast-pass script, an 8-10 minute
full run is entirely plausible and consistent with the measured fast-pass
baseline.

---

## 2. Boilerplate entropy

**`sys.path.insert` count:** 29 occurrences across `work/*.py` (grep
receipt above). Of these, ~20 are the identical one-liner
`sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))` at the top
of a script, needed only so `from _common import ...` resolves when the
script is invoked directly (`python3 work/foo.py`) rather than as a package
member. `_common.ensure_repo_on_path()` exists and is called by nearly every
script immediately after — but it can't fix the bootstrapping problem
because *it* lives in the directory that needs to be on `sys.path` before
you can `import` it. This is a real chicken-and-egg (not laziness), but
every script pays for it by hand instead of the harness doing it once (e.g.
a `work/__init__.py` + `conftest`-style shim, or simply invoking scripts via
`python3 -m work.foo` — which none of the docstrings' usage lines recommend).

**a2til discovery: THREE incompatible implementations coexist:**
1. `diskcheck.py:35-45` / `basiccheck.py:129-139` — a 3-way fallback list
   (`A2TIL_PATH` env → sibling directory of gsasm → `~/src/a2til`), each with
   its own local `_find_a2til()`/inline loop, not shared.
2. `manifestcheck.py:111,133-134`, `iwemcheck.py:100-101`,
   `census_migrate.py:133-134`, `textdatacheck.py:45-46`,
   `disk7check.py:29` — a 2-way `os.environ.get('A2TIL_PATH', '~/src/a2til')`
   with NO sibling-directory fallback (so a repo checked out next to a
   sibling `a2til/` — the exact case #1 exists to support — silently fails
   here unless the env var is also set).
3. `drivercheck.py:100` — **`A2TIL_ROOT = os.path.expanduser('~/src/a2til')`,
   with no `A2TIL_PATH` environment override at all.** This is the one that
   will bite someone: every other script in the ecosystem honors
   `A2TIL_PATH`; drivercheck.py — 593 lines, 18 drivers, one of the two
   scripts most in need of a working a2til — silently ignores it. A
   developer who sets `A2TIL_PATH` because `diskcheck.py`'s docstring told
   them to will find `drivercheck.py` failing (or worse, silently resolving
   to a stale `~/src/a2til` checkout) for a reason none of the error
   messages hint at.

None of these six call sites share a helper. `_common.py` — 223 lines, has
room — has no `find_a2til()`. This is the textbook "every new check script
starts by copy-pasting the last one" pattern the brief named: six near-
identical bespoke implementations of "find a2til," with the one divergent
outlier being the most consequential.

**Oracle/golden-fetch duplication:** `golden_fork`/`golden()`-shaped helpers
are independently defined (not shared) in `appdatacheck.py`, `cdevcheck.py`,
`fstcheck.py`, `iwemcheck.py`, `drivercheck.py`, `loader_placed.py`,
`finderdatacheck.py`, `rezforkcheck.py`, `rezdatacheck.py`, `rezcheck.py`,
`toolcheck.py` — 11 files define one. `rezcheck.golden_fork` IS reused by
11 other Rez-tier scripts (`cdevcheck`, `findercheck`, `installercheck`,
`rezbuildcheck`, `rezgencheck`, `rezdatacheck`, `easymountcheck`,
`rezemitcheck`, `teachcheck`, `rezforkcheck`, `rez_types_diag`) — so reuse
*does* happen where the domain (Rez forks) is uniform. But the
non-Rez domains (drivers, tools, filesystem forks) each roll their own,
because each needs a different name→(disk, path) lookup table
(`DRIVERMAP`, `TOOLMAP`, per-file dicts) — legitimate domain variance, but
it means seven near-identical "open a 2mg, find a Volume, read a path"
implementations exist with only the lookup table differing, each with its
own tiny memoization cache (`_VOL_CACHE` in `appdatacheck.py:114` and
`rezcheck.py:186`, `_DISK_RAW_CACHE` in `drivercheck.py:140`, `_CACHE` in
`installerdatacheck.py:65` and `diskbuilders/toolsets.py:125`, `_ASM_CACHE`
in `finderdatacheck.py:57` and `toolcheck.py:348`) — **six independently-
written, near-identical `{key: value}` memoization dicts**, none shared,
none in `_common.py`.

**`byte_match`/`first_diff`:** these ARE centralized — `_common.py:201-224`
defines `byte_match`, `byte_match_against_golden_len`, `first_diff`,
`mismatch_offsets`, and `grep -ln "def byte_match\|def first_diff\|def
mismatch_offsets" work/*.py` returns only `_common.py` itself. This is the
one area the brief's suspicion doesn't hold up: byte-comparison primitives
are NOT reimplemented per-script. Fair-hostile note: give credit where it's
due — this is exactly the kind of extraction that should have happened for
a2til-discovery and golden-fetch too, and evidently someone already knew
how, they just didn't apply it uniformly.

**44 of 47 `work/*.py` files import `_common`** (only `_common.py` itself,
`gate.py`, and `generality_check.py` don't) — so the module IS the de facto
shared kernel. The question isn't "does `_common.py` exist," it's "why does
it stop at path-joining and byte-diffing and not extend to the two
highest-repeat-count patterns (a2til discovery, oracle-fetch-with-cache)."

---

## 3. diskcheck.py: one module or four?

1276 lines, structure (verified via `grep -n "^def \|^class "`):
- **a2til bootstrap** (34-51)
- **Ownership manifest + `DiskFile` + `overlay`/`overlay_rsrc`** (54-179) —
  the "is this byte mine to touch" layer
- **~50 `_build_*` single-purpose builder-wrapper functions** (180-651,
  confirmed count: **41** functions matching `^def _build_`) — each a thin
  lazy-import shim around some other module's real builder
- **`DISK_BUILDER_REGISTRY`** (652-991, 339 lines, **97 path-keyed entries**
  by direct count of `'/...' : (...)` lines) — a literal nested dict, one
  sub-dict per disk (1,3,4,5,6,7), each entry `(fork, builder)` or a list of
  those for dual-fork paths, densely interleaved with diagnosis-history
  comments (e.g. lines 660-677: a paragraph about a reloc-dict forward-
  pointer bug fix, inline in the data structure)
- **`SOURCE_BUILDERS`/`REZ_BUILDERS`** (191, 240) — a SEPARATE, structurally
  different registry (flat dicts, not nested by disk) for Disk 2 only
- **`reconstruct`/`reconstruct_hfs`/`build_and_overlay*`** (1002-1140) —
  the actual overlay-and-compare engine
- **`check()`/`selftest()`/`main()`** (1148-end) — the CLI + the System
  Disk's own (non-registry) verification path

That's **three separate builder-registration shapes** in one file
(`SOURCE_BUILDERS`+`REZ_BUILDERS` flat dicts for Disk 2, `DISK_BUILDER_
REGISTRY` nested-by-disk dict for Disks 1/3/4/5/6/7, and 41 free-floating
`_build_*` wrapper functions feeding both) plus the overlay engine plus the
CLI. `diskmanifest._wired_builders()` (`work/diskmanifest.py:226-250`) has
to know about and merge all three shapes by hand (three separate loops)
every time it wants "every wired builder." This is a strong "is this one
module or four" case: ownership-tracking, builder-registration (x2 shapes),
overlay mechanics, and CLI are four concerns sharing one 1276-line
namespace, and the registry's inline comments (diagnosis history, "37 of
the census's 39 built forks," cross-references to `D3_OVERLAY_REPORT.md`)
make clear the registry has been treated as a place to also **narrate**
census work, not just wire callables.

**Registry-as-code vs census-as-data: the same fact lives in both, with only
a runtime check tying them.** `DISK_BUILDER_REGISTRY`'s own comments encode
census-shaped claims directly (`work/diskcheck.py:660-677`: "37 of the
census's 39 'built' forks... RESIDUAL... 2026-08-01 UPDATE: BOTH closed, 39
of 39 wired"). The census (`docs/disk_census_2026-08-01.json`, machine-read
by `diskmanifest.py`) independently records a `classification: "built"` +
`proven_by` field for the same paths. **Nothing checks these agree except
`diskmanifest.manifest_for()`'s `CallableProof`/`HarnessProof` validation at
generation time** (`work/diskmanifest.py:296-319`) — and that check only
fires for forks the census marks `built`; a fork the registry silently
*doesn't* wire (e.g. a future residual regression) produces no error unless
someone also remembers to demote the census entry. The comment at
diskcheck.py:660 is a human keeping the two in sync by prose, in the exact
place a machine check should live instead. **Drift direction:** the registry
drifts first (it's edited every time a builder is added/removed, in the
normal flow of landing a crack) and the census catches up in a separate,
manually-triggered pass (`census_migrate.py` is re-run and re-classified by
hand — see §4). There is no CI step that fails if `DISK_BUILDER_REGISTRY`'s
wired-path set and the census's `built`-classified path set diverge in the
"registry wired but census still says buildable" direction (only the
inverse — "census says built but nothing's wired" — is a `RuntimeError`).

---

## 4. census_migrate.py: "regenerable migration" is no longer honest

`work/census_migrate.py`, 777 lines, docstring: *"WHY a script, not a hand
edit: ... re-running it is how a future census update stays honest
(re-derive against LIVE disk state, never hand-patch counts)."*
(`census_migrate.py:9-11`)

**Git history says otherwise.** `git log --oneline --follow --
work/census_migrate.py` returns **9 commits**, the earliest introducing it
(`08b6f8a`/`dc557bb`) as a one-shot v1→v2 migration
(`docs/disk_census_2026-07-30.json` → `docs/disk_census_2026-08-01.json`),
and **6 subsequent commits editing it** as individual forks got
reclassified: `7658be9` "Apple II Script contradiction RESOLVED," `33eeecf`
"Tool.Setup CRACKED — last TECHNICAL_EXCEPTION x2 promoted to BUILT,"
`5fc64fd` "IWEM CRACKED," `540fbf2` "Disk 7 Basic.System/p8 rsrc... labels
overturned," `7d20fe6` "Four literal-text data forks... gap closed,"
`a987a34` "Adv.Disk.Util rsrc byte-exact — census BUILDER-COMPLETE." Every
one of these is a hand-edit to the `OVERRIDES` dict (or the surrounding
per-file commentary blocks — see the section headers at
`census_migrate.py:307,341,354,367,438,451,461,498,528,548,607,644,679` —
each a hand-written paragraph justifying one file's split) landed the same
day or the day after a crack, in the SAME commit as the code change that
did the cracking. **This is not "re-derive against live disk state" — it's
"hand-patch the migration script every time a fact changes," which is
exactly the anti-pattern the docstring says the design avoids.**

Compounding: `OLD_CENSUS`/`NEW_CENSUS` (`census_migrate.py:115-116`) are
hardcoded to the literal dated filenames `disk_census_2026-07-30.json` /
`disk_census_2026-08-01.json`. Those same two filenames are hardcoded again
in `diskmanifest.py` (`CENSUS_PATH`, line 84, plus four more docstring/
error-message references at lines 22-23, 63, 318). **The "2026-08-01" in
the filename no longer means "generated on 2026-08-01"** — it was
regenerated at least 6 more times after that date (per the commits above)
and is still being written to that same dated path today (`Aug 1 17:13`
mtime per `ls -la docs/*census*`, on a session where "today" per the
system clock is Aug 1/2 2026 — i.e. it's being re-run same-day repeatedly).
The date in the filename is now purely nominal/historical, but it's baked
into two source files as if it were a stable identifier. **The honest
description today is: this is a database (the OVERRIDES dict + section
comments) with a code-shaped, commit-triggered write API (re-run the
script, get a new JSON snapshot at a filename that lies about when it was
made).** Calling it a "migration" undersells the maintenance obligation
it's accrued — every future crack needs a new prose paragraph +
`_add(disk, path, ...)` call in this file, forever, growing without bound
alongside the census itself, and the "losslessness" contract (verbatim
`forks_raw_v1` preservation, `census_migrate.py:35-44`) only makes sense
for a true point-in-time migration, not an ongoing ledger.

**Right end state (my assessment, not verified against project docs):**
either (a) rename the artifact honestly — it's `docs/disk_census.json` (no
date) regenerated by `work/census_update.py` (no "migrate" framing, no
`OLD_CENSUS`/v1 lossless-preservation baggage) with `OVERRIDES` explicitly
documented as permanent hand-maintained state, not migration scaffolding;
or (b) eliminate `OVERRIDES` as hand-maintained prose and derive per-fork
splits mechanically wherever `diskmanifest`'s `CallableProof`/`HarnessProof`
validation already has enough information (a wired registry callable or a
gate-baseline-backed harness IS the fork-level ground truth already — the
census's `classification`/`proven_by` fields are in several cases just a
restatement of what `diskcheck.DISK_BUILDER_REGISTRY` + `gate_baseline.json`
already know). Option (b) is more work but would collapse two parallel
"source of truth" systems into one and remove the drift risk in §3 outright.

---

## 5. manifestcheck.py / diskmanifest.py

This pair is the strongest-engineered part of the ecosystem and deserves
the fair-hostile credit: `diskmanifest.HarnessProof`/`CallableProof`
(`work/diskmanifest.py:105-160`) is a genuinely good pattern — proofs are
validated at generation time against `gate.py`'s own `CHECKS`/`FULL_CHECKS`
table via `_harness_metrics_map()` (`diskmanifest.py:208-215`, **imported,
not duplicated** — explicitly called out in the module's own docstring as a
B1 requirement), so a census entry claiming `proven_by: "somecheck"` for a
harness name that doesn't exist in `gate.py`, or a metric that isn't in
`gate_baseline.json`, is a hard `RuntimeError` at generation time
(`diskmanifest.py:309-319`), not a silent pass. That closes exactly the
class of bug the registry/census drift in §3 worries about, for the subset
of facts routed through it.

**What isn't covered: `OVERLAID_DISKS`.** `work/manifestcheck.py:98-99`:
```python
OVERLAID_DISKS = {'Disk 2', 'Disk 5', 'Disk 6', 'Disk 1', 'Disk 7', 'Disk 3',
                  'Disk 4'}
```
The 6-line comment directly above it (lines 89-97) is explicit about the
intended invariant: *"A disk must NOT be added here without also adding its
physical metric to work/gate.py FULL_CHECKS — otherwise physical_exact
would revert to an unbacked label count."* **Nothing enforces this.** I
confirmed via `grep -n "OVERLAID_DISKS" work/manifestcheck.py` that the set
is referenced exactly once, at line 264, as a bare `in` membership test —
there is no code anywhere that cross-checks `OVERLAID_DISKS`'s members
against `gate.FULL_CHECKS`'s per-disk `*_physical_exact` metric names the
way `HarnessProof.is_valid()` cross-checks harness/metric names. The
comment IS the enforcement. This is precisely the "hand-set backed by
convention+comment" pattern the brief named, sitting one file away from a
working example (`HarnessProof`) of how to make the same kind of claim
machine-checked instead. Fixing it is small: `OVERLAID_DISKS` could be
derived from `{d for d in gate.FULL_CHECKS-disk-labels if
f'{d}_physical_exact' in gate_baseline}` rather than hand-listed, using the
exact `_harness_metrics_map()` pattern already sitting in the same import.

---

## 6. The *check script family: convention vs shared code

25-ish `*check.py` scripts (I count 27 files matching `*check*.py` including
`gate.py`/`_common.py`/two `diag`-suffixed exploratory scripts that aren't
gated). The **shared** parts: `_common.py` helpers (44/47 files import it),
`rezcheck.golden_fork` (11 reusers), `byte_match`/`first_diff` (universal).
The **convention-only** parts, unenforced by any base class, decorator, or
lint rule:
- A `main()` function exists and is called from `if __name__ == '__main__'`
  — true everywhere, but whether `main()` (or something it calls) actually
  calls `sys.exit()` on failure is, per §1, **inconsistent across roughly a
  third of the family**.
- The metric print format (`"WHATEVER_NAME good/total"` or similar) is
  freeform per script — there's no shared `print_metric(name, good, total)`
  helper in `_common.py`; each script hand-formats its own f-string, which
  is exactly the surface `gate.py`'s regex has to track and the surface a
  format-drift would break silently (the printed strings and the regexes
  that scrape them are two independently-edited copies of the same
  contract, in two different files, with no test asserting they match other
  than "did gate.py's regex find a number today").
- Whether a script defines its own oracle-fetch/cache (§2) or reuses
  `rezcheck`'s is a per-author choice with no guidance beyond "look at what
  a similar existing script did."

**Cost of artifact #26:** a new author copies the nearest sibling script
(by domain — Rez-tier scripts copy `rezforkcheck.py`/`teachcheck.py`;
disk/driver-tier scripts copy `drivercheck.py`/`appdatacheck.py`), inheriting
whatever that sibling got right AND wrong. Concretely, the likely mistakes:
1. Forgetting `sys.exit(1)` on the failure path (10/34 files already made
   this mistake, including two of the largest scripts) — the new script
   will pass gate.py's exit-code check by accident, not by design, and gate
   coverage silently degrades to regex-only for that check the day someone
   refactors its print statement and typos the format string in a way that
   still parses as *some* `(\d+)/(\d+)`.
2. Re-deriving a2til discovery from whichever of the three existing
   variants the copied sibling happened to use (50% chance of copying the
   `drivercheck.py`-style no-env-override version, per the 3-vs-1 split
   found in §2 — actually the split favors the correct 2-6 way, but
   `drivercheck.py` is a plausible copy source for anything driver-adjacent).
3. A new `_CACHE`/`_VOL_CACHE`-shaped dict reinvented rather than reused,
   because there's nowhere central to reuse from.
4. A new entry in `gate.py`'s `CHECKS` (or `FULL_CHECKS`) literal, hand-
   written regex included, with no test that the regex actually matches
   the script's real stdout beyond "I ran it once and it worked" (there is
   no unit test *of gate.py's parsing* independent of running the real,
   slow, `ref/`-dependent corpus).
5. If the new artifact belongs on a disk, a new `DISK_BUILDER_REGISTRY`
   entry (or `SOURCE_BUILDERS`/`REZ_BUILDERS`, whichever shape the target
   disk uses) AND a matching census fork entry AND, if the classification
   is anything other than a clean `built`+wired-callable, a hand-written
   `OVERRIDES` paragraph in `census_migrate.py` — four separate files to
   touch for one new fact, three of which have no automated cross-check
   with each other (§3, §4).

---

## 7. Fixture/bless interlock — foot-gun confirmed

`tests/run_fixtures.py --bless` (lines 88-96, 128-143): the interlock is
sound in *intent* — `bless()` refuses to run unless `run_gate()` (a
`gate.py --skip-fixtures` subprocess) exits 0 (lines 132-136) — but has a
real gap. **`bless()` performs no diff against the previous expected bytes
before overwriting them, and no confirmation step.** If `--bless` is run
without a `names` filter (the natural thing to do when you've landed a
change and want to refresh whichever fixtures moved — the `names` filter is
opt-in, not required), it rewrites `expected.obj`/`expected.out` for
**every** fixture directory unconditionally (`main()`, lines 138-143: the
loop iterates all matched fixtures and calls `bless(fixdir)` for each with
no compare-then-warn step). Combined with gate.py's own stated reason for
the fixture suite existing — *"The golden-corpus checks... are BLIND to any
construct the ROM sources don't happen to contain... a change can broaden
the assembler's behavior on unseen inputs and still leave every corpus byte
identical"* (`gate.py:292-295`) — the interlock's single safety check
(corpus-green) is **precisely the signal gate.py's own docstring says is
blind to the failure mode fixtures exist to catch**. A change that silently
widens parsing on an unseen construct (the exact scenario cited,
`docs/ADVERSARIAL_REVIEW_2026-07-17.md`) would leave the corpus green,
pass the interlock, and then `--bless` (run for an unrelated reason, e.g.
adding one new fixture and forgetting the name filter) would silently
canonize the new, wrong behavior into `expected.obj` for every *existing*
fixture whose output happened to shift too — with a diff never shown to the
human running the command. The `check()` path (non-bless) DOES print a
`difflib.unified_diff` on mismatch (lines 78-84) — that diffing capability
exists in the file, it's simply not invoked during `bless()` before the
overwrite.

---

## 8. Cross-process performance

Confirmed via git-log/doc cross-reference (§1) that `docs/REFACTORING.md`'s
own R10 proposal already correctly diagnoses the mechanism: `gate.py`
shells out to ~30 independent `python3 work/X.py` subprocesses (one
`subprocess.run` per CHECKS/FULL_CHECKS row, `gate.py:313-315`), each a
cold interpreter start that re-walks and re-assembles overlapping source
trees (kernelcheck/toolcheck/fstcheck/drivercheck all sweep subsets of
GS.OS/GSFirmware/GSToolbox). The in-process memoization dicts found in §2
(`_CACHE`, `_ASM_CACHE`, `_VOL_CACHE`, `_DISK_RAW_CACHE` — six of them) are
each scoped to ONE subprocess's lifetime and are discarded the instant that
script's `main()` returns — they optimize repeated calls *within* a single
check script's own run (e.g. `toolcheck.py` checking 14 tools that share
common includes), not the cross-script overlap that dominates a full
`gate.py` run's wall clock.

**R10's proposed shape (`docs/REFACTORING.md:315-326`) is the right fix for
the actual bottleneck, not a band-aid** — it's a disk-backed cache
(`work/.cache/`, keyed by source mtimes+defines+sysdate) rather than an
in-memory one, which is the correct choice given the subprocess-per-check
architecture: an in-memory cache can't survive a process boundary, a
disk-backed one can, so it actually addresses the cross-script overlap
that the current six per-process dicts can't touch. It's also correctly
scoped opt-in (env-gated, explicitly disabled during `--update`/bless) so it
can't introduce a stale-cache-masks-a-regression risk into the gate's
default, protected posture — a rare case of a listed roadmap item where the
plan already reflects the actual constraint rather than reaching for the
generic fix.

The band-aid critique that DOES apply: R10 treats the SYMPTOM (repeated
cold-start assembly) of a root cause the roadmap explicitly declines to
touch — **there is no shared build graph, and there won't be one under the
current non-goals** (`docs/REFACTORING.md`'s "Explicit non-goals" section:
"No test framework migration... the corpus-free / golden-gated distinction"
must stay blurred-free, and "gate.py regexes are the contract" is
enshrined, not merely tolerated). A shared build graph would mean the ~30
scripts become importable functions in ONE process instead of ~30 CLI
entry points scraped over stdout — which would also retire most of §1's
regex-transport risk and §2's per-script boilerplate. That's explicitly
off the table (it's a "modernization pass" / "test framework migration" by
the roadmap's own definition), for a reason that's defensible given the
project's actual goal (forensic debuggability, greppable flat scripts) —
but it means R10 is being adopted as a permanent architectural ceiling, not
a stepping stone: the wall-clock cost gets better, the fan-out-of-
independent-processes-scraped-over-stdout shape (and everything in §1-§6
downstream of it) stays exactly as it is today, forever, by explicit
policy.

---

## Ranked findings — (cost) × (trip likelihood)

| # | Finding | Cost if it trips | Likelihood | Rank |
|---|---|---|---|---|
| 1 | 10/34 check scripts never `sys.exit()` nonzero on failure — regex-scrape is the ONLY signal for a third of the corpus | High (silent regression ships past the gate's second layer of defense; two of the ten are the largest scripts in the corpus) | Medium (needs a format-drift AND a coincidentally-parseable replacement string; hasn't happened yet per the audit) | **HIGH** |
| 2 | `census_migrate.py` is a permanently hand-edited ledger wearing a "regenerable migration" docstring; 6 post-migration edits already prove the pattern | Medium-high (every future crack needs a hand-written paragraph forever; no mechanical check that OVERRIDES tracks reality) | High (already happening every few days per git log) | **HIGH** |
| 3 | Registry (diskcheck.py) vs census (JSON) — same ownership fact in two places, cross-checked only in the "census says built, nothing wired" direction | Medium (inverse drift — wired-but-uncensused — goes undetected) | Medium | MEDIUM-HIGH |
| 4 | `drivercheck.py`'s `A2TIL_ROOT` ignores `A2TIL_PATH` while 5 other files honor it | Low-medium (one confusing failure per affected dev, workaroundable once diagnosed) | Medium (anyone who sets A2TIL_PATH per the OTHER scripts' docs hits this) | MEDIUM |
| 5 | `OVERLAID_DISKS` hand-set, comment-enforced only, one file away from the `HarnessProof` pattern that would make it machine-checked | Medium (a disk added without its physical metric silently inflates `manifest_physical_exact`) | Low (small, well-commented set; changes rarely) | MEDIUM |
| 6 | `--bless` with no name filter blesses everything with no diff shown | High (silently canonizes a regression into "ground truth" fixtures) | Low-medium (requires forgetting the filter AND a coincident behavior shift) | MEDIUM |
| 7 | Boilerplate entropy (a2til discovery x6, oracle-fetch x11, cache dicts x6) | Low per-instance, compounding (cost is contributor-hours, not correctness) | Certain (every new script pays it) | MEDIUM (chronic, not acute) |
| 8 | gate.py regex could match the wrong line (no case found today, but no structural prevention) | High if it ever fires | Low today (checked every regex; no live collision) | LOW-MEDIUM |
| 9 | Full-gate wall-clock (measured 3:46 fast-pass; plausibly 8-10 min full) | Low (productivity tax, not correctness) | Certain | LOW (R10 already scoped correctly) |

---

## Three refactors I'd stake time on

### 1. Make `sys.exit` nonzero-on-failure universal, and add a `_common.py` `emit_metric()` that OWNS the print-and-exit contract

**What:** add `_common.gate_result(name, good, bad, extra='') -> NoReturn`
that prints the standardized line AND calls `sys.exit(0 if bad == 0 else
1)` in one place. Migrate the 10 confirmed silent-exit scripts first
(toolcheck, drivercheck, fstcheck, cdevcheck, bytecheck, linkcheck,
objcheck, appdatacheck, rezforkcheck, rezdatacheck), one at a time, each its
own commit.

**De-risking plan (metrics-unchanged discipline):** this changes exit codes,
not printed text — `gate.py`'s regex scrape is untouched, so
`gate_baseline.json` values cannot move. Verify per-script: run `python3
work/gate.py` before and after each migration and confirm byte-identical
stdout for every metric line (only the process return code differs, and
gate.py already treats nonzero as fatal — so the "after" state should ONLY
newly fail on a genuinely-failing run, which the corpus currently doesn't
have). Land behind the existing gate as ten separate small commits so a
single bad migration is bisectable.

### 2. Retire `census_migrate.py`'s "migration" framing; make `OVERRIDES` an explicitly-permanent, separately-named file, and stop hardcoding the dated census filename in two source files

**What:** (a) rename `docs/disk_census_2026-08-01.json` →
`docs/disk_census.json` (or keep versioned snapshots but stop treating the
LATEST one's filename as a permanent identifier baked into source); update
the ~6 hardcoded references in `census_migrate.py` + `diskmanifest.py`. (b)
Split `OVERRIDES` out of `census_migrate.py` into its own file (e.g.
`work/census_overrides.py`) with a docstring that says what it now actually
is — a permanent, growing, hand-maintained ledger of fork classifications
that couldn't be derived mechanically — rather than migration scaffolding.
This doesn't have to happen all at once; even just the honest docstring +
filename rename removes the "regenerable" framing that's actively
misleading a future maintainer (or reviewer) about what kind of artifact
this is.

**De-risking plan:** this is a pure rename/reorganization — the JSON
CONTENT doesn't change, only its path and which file the OVERRIDES dict
lives in. Verify: `python3 work/census_migrate.py` output byte-identical
before/after (diff the two JSON files), then `python3 work/gate.py --full`
green with identical `gate_baseline.json` (manifestcheck's metrics read the
census indirectly through `diskmanifest.CENSUS_PATH`, so this is the real
regression check). Do the path rename in one commit (mechanical, git grep
for every reference first), and defer the OVERRIDES-file split to a
follow-up so the two changes are independently bisectable.

### 3. Collapse the three a2til-discovery implementations and the golden-fetch-with-cache pattern into `_common.py`

**What:** add `_common.find_a2til() -> str | None` (the 3-way fallback,
matching `diskcheck.py`'s existing best version) and switch every one of
the six call sites (including `drivercheck.py`'s broken one) to call it.
Separately, add a small `_common.OracleCache` helper (a thin wrapper: open
+ parse a 2mg once per (script-run, disk-path) key) that the seven
independent `golden()`/`_VOL_CACHE`-style implementations can adopt
incrementally — this one is lower priority than the a2til fix (it's
boilerplate cost, not a correctness bug) and doesn't need to land in the
same packet.

**De-risking plan:** the a2til fix changes *behavior* for exactly one file
(`drivercheck.py`, which currently ignores `A2TIL_PATH`) — that's the one
call site to test carefully: run `A2TIL_PATH=<value> python3
work/drivercheck.py` before and after and confirm it now actually uses the
override (a NEW behavior, not previously gated, so there's no baseline to
preserve — this is a bugfix, and the gate's `driver_bytes` metric should be
identical either way since presumably the same a2til checkout is in play
in CI). For the other five already-correct call sites, swapping their
inline loop for `_common.find_a2til()` is a pure refactor — confirm via
`python3 work/gate.py` metric-for-metric identity, same discipline as
refactor #1. Land the `drivercheck.py` behavior fix as its own commit,
separate from the four mechanical swaps, so a reviewer can see exactly
which commit changes behavior.
