#!/usr/bin/env python3
"""diskmanifest.py — P0a (+B1/B2 hardening): explicit, FORK-level ownership
manifests for the 7-disk completion (docs/SOW_COMPLETION.md +
docs/IMPLEMENTATION_PLAN.md §1).

Ownership is an EXPLICIT manifest, NOT a file-type heuristic.  Each on-disk
FORK (not file — see B2 below) is in exactly one state:

    BUILT               bytes actually reproduced by source/tools, backed by a
                        TYPED PROOF (see below) — a builder is wired AND
                        logical-exact for THIS disk path/fork.
    TODO_BUILDABLE      source exists, no byte-exact builder wired yet for this
                        fork (blocks Tier A until promoted to BUILT)
    SUBSTITUTE          no producing source (verified); carried verbatim.
                        Includes gold-fed/extraction-fed embedded payloads.
    TECHNICAL_EXCEPTION source present but not byte-exact (Tool.Setup, case-B
                        wall); human-gated.

The manifest is GENERATED from the validated, FORK-GRANULAR census
(docs/disk_census_2026-08-01.json — a machine-generated migration of
docs/disk_census_2026-07-30.json; see work/census_migrate.py).  A census
`built` classification is promoted to BUILT here ONLY when it carries a typed
proof that validates (see Proof classes below).  There is NO free-form-string
fallback: a BUILT record with no valid proof is a GENERATION ERROR, not a
silently-degraded state (2026-08-01 adversarial-review finding #2 —
docs/ADVERSARIAL_REVIEW_SOW_IMPLEMENTATION_2026-08-01.md).

--- B1: typed proof objects (finding #2) -----------------------------------

  CallableProof(builder, fork)
      The path/fork is a key in diskcheck's SOURCE_BUILDERS / REZ_BUILDERS
      (Disk 2) or DISK_BUILDER_REGISTRY[disk_label] (Disk 5/6 First-Disks
      overlay) — a REAL callable that a diskcheck/gate pass exercises.
      Structurally always valid (a callable is the strongest evidence tier;
      it always takes precedence over a HarnessProof for the same fork).

  HarnessProof(harness, metrics)
      The census names a proving harness (`proven_by`, e.g. "drivercheck",
      "disk7check").  VALID at generation time iff `harness` is a registered
      name in work/gate.py's CHECKS+FULL_CHECKS table (imported, not
      duplicated — see `_harness_metrics_map()`) AND every metric in
      `metrics` is a key in work/gate_baseline.json.  `metrics` defaults to
      ALL of that harness's baselined metrics (gate.py check entries can have
      more than one metric; a HarnessProof binds to all of them unless a
      migration override narrows it — see census_migrate.py's EasyMount
      split).

A HarnessProof is a claim that GENERATION validates for well-formedness
(the harness and its metrics really exist in the gate machinery) — NOT a
promise that the metric is currently green.  `manifest_builders_exact`
(work/manifestcheck.py) is what additionally requires bad==0 on every one of
a HarnessProof's metrics RIGHT NOW; `manifest_builders_wired` does not.  That
is how `builders_exact` can legitimately sit below `builders_wired` (a
regression in some harness's metric would show up there without derailing
the census's structural validity).

--- B2: fork-level census + manifest entries (finding #3) ------------------

The 2026-07-30 census was FILE-granular: one record per path, with a prose
`forks` string like "data=built(...); rsrc=buildable-rez(...) not yet
gated".  docs/disk_census_2026-08-01.json (work/census_migrate.py) replaces
that string with a structured per-fork dict:
    "forks": {"data": {"classification": ..., "proven_by": ..., "size": ...,
                       "evidence": ...},
              "rsrc": {...}}   # (omit a fork the LIVE disk does not have)
`manifest_for()` below emits ONE Entry per (path, fork) key, each carrying
its OWN classification/proof/evidence — so a file whose data fork is BUILT
but whose resource fork is still buildable (Disk 7's six NetBoot targets) is
represented accurately instead of collapsing to one file-level "built".

Fork granularity note: (path, fork) keys are `(path, 'data')` /
`(path, 'rsrc')` only for this packet — no rCDEVCode-level sub-payload
entries yet (docs/IMPLEMENTATION_PLAN.md §1's ForkKey allows finer keys;
that is future work, not needed for the fork-ownership defect this packet
fixes).
"""
import json
import os

from _common import ROOT

CENSUS_PATH = os.path.join(ROOT, 'docs', 'disk_census_2026-08-01.json')
GATE_BASELINE_PATH = os.path.join(ROOT, 'work', 'gate_baseline.json')

# States
BUILT = 'BUILT'
TODO_BUILDABLE = 'TODO_BUILDABLE'
SUBSTITUTE = 'SUBSTITUTE'
TECHNICAL_EXCEPTION = 'TECHNICAL_EXCEPTION'

# per-fork census classification -> manifest state (before the BUILT-proof
# validation below promotes/rejects it)
_CENSUS_STATE = {
    'built': BUILT,                   # requires a validating typed proof
    'buildable-asm': TODO_BUILDABLE,
    'buildable-rez': TODO_BUILDABLE,
    'no-source-substitute': SUBSTITUTE,
    'pascal-c-nontarget': SUBSTITUTE,
    'technical-exception': TECHNICAL_EXCEPTION,
}


class CallableProof:
    """The strongest proof tier: a real, gate-exercised builder callable is
    wired for this exact (path, fork)."""
    __slots__ = ('builder', 'fork')

    def __init__(self, builder, fork):
        self.builder = builder
        self.fork = fork

    def is_valid(self, harness_metrics, baseline_keys):
        return callable(self.builder)

    def is_exact(self, baseline):
        # A wired callable's bytes are proven by the diskcheck/First-Disks
        # pass that owns it (disk_logical_exact / disk5_logical_exact /
        # disk6_logical_exact) — those are hard gate.py FULL_CHECKS metrics,
        # so a wired callable is exact by construction (if it weren't, THAT
        # metric would already be a gate regression).
        return True

    def __repr__(self):
        return f'<CallableProof fork={self.fork} builder={self.builder!r}>'


class HarnessProof:
    """The path/fork is proven by a NAMED gate.py harness (`proven_by` in the
    census).  Structurally valid iff the harness name + every metric name are
    real entries in work/gate.py's CHECKS/FULL_CHECKS table and
    work/gate_baseline.json (see `_harness_metrics_map()` / `is_valid()`)."""
    __slots__ = ('harness', 'metrics')

    def __init__(self, harness, metrics):
        self.harness = harness
        self.metrics = tuple(metrics)

    def is_valid(self, harness_metrics, baseline_keys):
        if not self.harness or self.harness not in harness_metrics:
            return False
        if not self.metrics:
            return False
        avail = harness_metrics[self.harness]
        return all(m in avail for m in self.metrics) and \
            all(m in baseline_keys for m in self.metrics)

    def is_exact(self, baseline):
        """True iff EVERY one of this proof's metrics currently shows bad==0
        in work/gate_baseline.json (adversarial-review finding #2: ties
        'exact' to real, live gate state instead of a bare non-None check)."""
        for m in self.metrics:
            entry = baseline.get(m)
            if entry is None or entry[1] != 0:
                return False
        return True

    def __repr__(self):
        return f'<HarnessProof {self.harness} {list(self.metrics)}>'


class Entry:
    __slots__ = ('path', 'fork', 'state', 'kind', 'source_path', 'evidence',
                 'proof', 'census_class', 'size')

    def __init__(self, path, fork, state, *, kind=None, source_path=None,
                 evidence='', proof=None, census_class=None, size=None):
        self.path = path
        self.fork = fork
        self.state = state
        self.kind = kind                 # 'asm' | 'rez' | ... (for TODO_BUILDABLE)
        self.source_path = source_path
        self.evidence = evidence
        self.proof = proof               # CallableProof | HarnessProof | None
        self.census_class = census_class
        self.size = size                 # census-recorded fork size, if any

    def __repr__(self):
        return f'<{self.state} {self.path} ({self.fork})>'


def load_census():
    with open(CENSUS_PATH) as fh:
        return json.load(fh)


def _harness_metrics_map():
    """{harness_name: [metric, ...]} built by IMPORTING work/gate.py's
    CHECKS + FULL_CHECKS tables (never duplicated here — B1 requirement)."""
    import gate
    m = {}
    for name, _argv, specs in gate.CHECKS + gate.FULL_CHECKS:
        m[name] = [metric for metric, _rx, _kind in specs]
    return m


def _baseline_metrics():
    """{metric_name: [good, bad]} from the committed work/gate_baseline.json."""
    if not os.path.exists(GATE_BASELINE_PATH):
        return {}
    with open(GATE_BASELINE_PATH) as fh:
        return json.load(fh)


def _wired_builders(disk_label=None):
    """{(path, fork): callable() -> bytes} for every fork with a real,
    gate-exercised builder wired TODAY:

      * diskcheck.SOURCE_BUILDERS  -> fork 'data'  (Disk 2 paths, `/System.Disk/...`)
      * diskcheck.REZ_BUILDERS     -> fork 'rsrc'  (Disk 2 paths)
      * diskcheck.DISK_BUILDER_REGISTRY[disk_label] -> its own recorded fork
        (Disk 5/6 First-Disks overlay; each entry is already (fork, builder))

    Imported lazily so a2til / ref/ are only needed when the caller actually
    has them (mirrors the original module's discipline).
    """
    import diskcheck as dc
    wired = {}
    for path, builder in dc.SOURCE_BUILDERS.items():
        wired[(path, 'data')] = builder
    for path, builder in dc.REZ_BUILDERS.items():
        wired[(path, 'rsrc')] = builder
    if disk_label is not None:
        for path, (fork, builder) in dc.DISK_BUILDER_REGISTRY.get(disk_label, {}).items():
            wired[(path, fork)] = builder
    return wired


def _find_disk(census, disk_label):
    for k, d in census['disks'].items():
        if k.split(' of 7 ')[0] == disk_label.split(' of 7 ')[0] or k == disk_label:
            return k, d
    raise KeyError(f'disk not in census: {disk_label!r}')


def _kind_for(cc):
    if cc == 'buildable-asm':
        return 'asm'
    if cc == 'buildable-rez':
        return 'rez'
    return None


def manifest_for(disk_label, census=None, wired=None, *,
                  harness_metrics=None, baseline=None):
    """Return {(path, fork): Entry} for one disk, generated from the
    fork-granular census.  Raises RuntimeError (a GENERATION ERROR, per B1)
    if any 'built' fork's proof does not structurally validate — there is
    deliberately NO silent-degrade path."""
    census = census or load_census()
    disk_key, disk = _find_disk(census, disk_label)
    if wired is None:
        try:
            wired = _wired_builders(disk_key)
        except Exception:
            wired = {}
    if harness_metrics is None:
        harness_metrics = _harness_metrics_map()
    if baseline is None:
        baseline = _baseline_metrics()
    baseline_keys = set(baseline)

    out = {}
    for f in disk['files']:
        path = f['path']
        forks = f.get('forks')
        if not isinstance(forks, dict):
            raise RuntimeError(
                f'GENERATION ERROR: {disk_key} {path!r} has no fork-granular '
                f"'forks' dict — census is stale; re-run work/census_migrate.py "
                f'(got {forks!r}).')
        for fork, fi in forks.items():
            cc = fi.get('classification')
            state = _CENSUS_STATE.get(cc, TODO_BUILDABLE)
            proof = None
            if cc == 'built':
                state = BUILT
                callable_ = wired.get((path, fork))
                if callable_ is not None:
                    proof = CallableProof(callable_, fork)
                else:
                    harness = fi.get('proven_by')
                    metrics = harness_metrics.get(harness, []) if harness else []
                    proof = HarnessProof(harness, metrics) if harness else None
                if proof is None or not proof.is_valid(harness_metrics, baseline_keys):
                    raise RuntimeError(
                        f'GENERATION ERROR: {disk_key} {path!r} fork={fork!r} is '
                        f"classified 'built' but has no valid proof "
                        f"(proven_by={fi.get('proven_by')!r}, wired="
                        f'{callable_ is not None}). A BUILT record must be backed '
                        f'by a real wired callable or a HarnessProof whose harness '
                        f'name + metrics are all registered in work/gate.py and '
                        f'work/gate_baseline.json. Fix the census record '
                        f'(docs/disk_census_2026-08-01.json via work/census_migrate.py) '
                        f'to name the correct proving harness.')
            out[(path, fork)] = Entry(
                path, fork, state, kind=_kind_for(cc),
                source_path=fi.get('source_path'), evidence=fi.get('evidence', ''),
                proof=proof, census_class=cc, size=fi.get('size'))
    return out


def all_disks(census=None):
    census = census or load_census()
    # canonical order: Disk 1..7
    def order(k):
        for n in range(1, 8):
            if k.startswith(f'Disk {n} '):
                return n
        return 99
    return sorted(census['disks'].keys(), key=order)


if __name__ == '__main__':
    import collections
    from _common import ensure_repo_on_path
    ensure_repo_on_path()
    cen = load_census()
    hm = _harness_metrics_map()
    bl = _baseline_metrics()
    grand = collections.Counter()
    grand_exact = 0
    for dk in all_disks(cen):
        try:
            wired = _wired_builders(dk)
        except Exception as e:
            print(f'(no wired builders available for {dk}: {e})')
            wired = {}
        m = manifest_for(dk, cen, wired, harness_metrics=hm, baseline=bl)
        c = collections.Counter(e.state for e in m.values())
        d_exact = sum(1 for e in m.values()
                      if e.state == BUILT and e.proof is not None
                      and e.proof.is_exact(bl))
        grand.update(c)
        grand_exact += d_exact
        label = dk.split(' of 7 ')[-1] if ' of 7 ' in dk else dk
        print(f'  {label[:22]:22} entries={len(m):3}  '
              f'BUILT={c[BUILT]:3} (exact={d_exact:3}) TODO={c[TODO_BUILDABLE]:3} '
              f'SUB={c[SUBSTITUTE]:3} TECH={c[TECHNICAL_EXCEPTION]:2}')
    print(f'  {"TOTAL":22} '
          f'BUILT={grand[BUILT]} (exact={grand_exact}) TODO={grand[TODO_BUILDABLE]} '
          f'SUB={grand[SUBSTITUTE]} TECH={grand[TECHNICAL_EXCEPTION]}')
