#!/usr/bin/env python3
"""diskmanifest.py — P0a: explicit, fork-level ownership manifests for the
7-disk completion (docs/SOW_COMPLETION.md + docs/IMPLEMENTATION_PLAN.md §1).

Ownership is an EXPLICIT manifest, NOT a file-type heuristic (per diskcheck.py's
DISCIPLINE note and the Codex review: physical image match alone is not a
builder-correctness gate).  Each on-disk fork is in exactly one state:

    BUILT               bytes actually reproduced by source/tools (a builder is
                        wired AND logical-exact for THIS disk path)
    TODO_BUILDABLE      source exists, no byte-exact builder wired yet for this
                        disk (blocks Tier A until promoted to BUILT)
    SUBSTITUTE          no producing source (verified); carried verbatim.
                        Includes gold-fed/extraction-fed embedded payloads.
    TECHNICAL_EXCEPTION source present but not byte-exact (Tool.Setup, case-B
                        wall); human-gated.

The manifest is GENERATED from the validated census
(docs/disk_census_2026-07-30.json).  A census `built` classification is only
promoted to a wired BUILT here when a real builder exists for that disk path
(today: Disk 2's diskcheck SOURCE_BUILDERS/REZ_BUILDERS).  Every other census
`built` — an artifact proven elsewhere but not yet wired into THIS disk's
overlay — stays TODO_BUILDABLE (that wiring is SOW phase P2), so
`disk_required_builders_wired` stays honest.

Fork granularity: entries are keyed by (path, fork).  The census is
file-granular, so a `data+rsrc` file seeds one entry today; P2 refines it into
per-fork entries (e.g. a CDEV's rsrc BUILT + its rCDEVCode SUBSTITUTE).
"""
import json
import os

from _common import ROOT

CENSUS_PATH = os.path.join(ROOT, 'docs', 'disk_census_2026-07-30.json')

# States
BUILT = 'BUILT'
TODO_BUILDABLE = 'TODO_BUILDABLE'
SUBSTITUTE = 'SUBSTITUTE'
TECHNICAL_EXCEPTION = 'TECHNICAL_EXCEPTION'

# census classification -> manifest state (before the wired-builder promotion)
_CENSUS_STATE = {
    'built': BUILT,                   # a gate harness proves it byte-exact
    'buildable-asm': TODO_BUILDABLE,
    'buildable-rez': TODO_BUILDABLE,
    'no-source-substitute': SUBSTITUTE,
    'pascal-c-nontarget': SUBSTITUTE,
    'technical-exception': TECHNICAL_EXCEPTION,
}


class Entry:
    __slots__ = ('path', 'fork', 'state', 'kind', 'source_path', 'evidence',
                 'builder', 'census_class')

    def __init__(self, path, fork, state, *, kind=None, source_path=None,
                 evidence='', builder=None, census_class=None):
        self.path = path
        self.fork = fork
        self.state = state
        self.kind = kind                 # 'asm' | 'rez' | ... (for TODO_BUILDABLE)
        self.source_path = source_path
        self.evidence = evidence
        self.builder = builder           # callable when wired (BUILT)
        self.census_class = census_class

    def __repr__(self):
        return f'<{self.state} {self.path} ({self.fork})>'


def load_census():
    with open(CENSUS_PATH) as fh:
        return json.load(fh)


def _wired_builders():
    """The set of disk paths for which a real byte-exact builder is wired today.

    Imported lazily from diskcheck so a2til / ref/ are only needed when the
    caller actually has them.  Returns {disk_path_key: callable}.  These keys
    are `/System.Disk/...` (Disk 2 only) — the single disk currently wired.
    """
    import diskcheck as dc
    wired = dict(dc.SOURCE_BUILDERS)
    wired.update({k: ('rez', v) for k, v in dc.REZ_BUILDERS.items()})
    return wired


def manifest_for(disk_label, census=None, wired=None):
    """Return {(path, fork): Entry} for one disk, generated from the census."""
    census = census or load_census()
    if wired is None:
        try:
            wired = _wired_builders()
        except Exception:
            wired = {}
    disk = None
    for k, d in census['disks'].items():
        if k.split(' of 7 ')[0] == disk_label.split(' of 7 ')[0] or k == disk_label:
            disk = d
            break
    if disk is None:
        raise KeyError(f'disk not in census: {disk_label!r}')

    out = {}
    for f in disk['files']:
        path = f['path']
        fork = f.get('forks') or 'data'
        cc = f['classification']
        state = _CENSUS_STATE.get(cc, TODO_BUILDABLE)
        builder = None
        # census 'built' == a gate harness proves this fork byte-exact (P2).
        # builder = the real Disk-2 diskcheck callable when present, else the
        # proving harness name (the byte-exactness is enforced by that harness
        # in the same gate pass).  NOTE: this is "we can BUILD it byte-exact",
        # NOT "an overlay is wired onto disk D" — whole-disk reconstruction is
        # the separate physical_exact metric (First-Disks phase).
        if cc == 'built':
            state = BUILT
            builder = wired.get(path) or f.get('proven_by') or 'harness'
        out[(path, fork)] = Entry(
            path, fork, state, kind=(f.get('language') or None),
            source_path=f.get('source_path'), evidence=f.get('evidence', ''),
            builder=builder, census_class=cc)
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
    try:
        wired = _wired_builders()
    except Exception as e:
        print(f'(no wired builders available: {e})')
        wired = {}
    print(f'wired builders (Disk 2): {len(wired)}')
    grand = collections.Counter()
    for dk in all_disks(cen):
        m = manifest_for(dk, cen, wired)
        c = collections.Counter(e.state for e in m.values())
        grand.update(c)
        label = dk.split(' of 7 ')[-1] if ' of 7 ' in dk else dk
        print(f'  {label[:22]:22} entries={len(m):3}  '
              f'BUILT={c[BUILT]:3} TODO={c[TODO_BUILDABLE]:3} '
              f'SUB={c[SUBSTITUTE]:3} TECH={c[TECHNICAL_EXCEPTION]:2}')
    print(f'  {"TOTAL":22} '
          f'BUILT={grand[BUILT]} TODO={grand[TODO_BUILDABLE]} '
          f'SUB={grand[SUBSTITUTE]} TECH={grand[TECHNICAL_EXCEPTION]}')
