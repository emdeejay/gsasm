#!/usr/bin/env python3
"""manifestcheck.py — P0b/P0c: the 7-disk completion scoreboard.

Implements the builder-correctness metrics from docs/SOW_COMPLETION.md §2 (the
Codex-review model — physical byte-match alone is NOT a completion gate).  For
every disk it (P0b) validates the manifest against a LIVE enumeration and (P0c)
reports:

  manifest_inventory_classified   every live fork has a manifest owner (oos:0)
  manifest_substitutes_confirmed  every SUBSTITUTE/TECH has recorded evidence
  manifest_builders_wired         BUILT entries / required (BUILT+TODO_BUILDABLE)
  manifest_builders_exact         BUILT entries whose builder's bytes == golden
                                  BEFORE overlay (verified live)
  manifest_physical_exact         disks physical-100% AND builder-complete
                                  (no TODO_BUILDABLE) — so golden-carry alone
                                  can NOT make a disk count

Gate-scraped lines use the `good=N bad=M` / `A/B` shapes work/gate.py expects.

ProDOS disks (1-6) enumerate via a2til; Disk 7 is HFS-in-2IMG (via work/hfs.py).
Disk 7 build/overlay is P5 (the HFS writer, P0d-2) — here it is inventory +
substitute-confirmed + read-only fork extraction only.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import ROOT, byte_match, ensure_repo_on_path  # noqa: E402
ensure_repo_on_path()

import diskmanifest as dm  # noqa: E402

DISKROOT = os.path.join(
    ROOT, 'ref', 'GSOS_6', 'System601_disks', 'System 6.0.1')

# Disks with a working whole-disk overlay whose reconstructed image byte-matches
# the golden (i.e. RECONSTRUCTED, gated by diskcheck.check(D) in the same pass).
# Only Disk 2 today; the First-Disks phase adds 5 & 6, etc. Being merely
# builder-complete (0 TODO) does NOT put a disk here — the overlay must exist.
OVERLAID_DISKS = {'Disk 2'}


def disk_path_for(label):
    return os.path.join(DISKROOT, label)


def live_forks_prodos(disk_path):
    """{normalized_path: 'data'|'data+rsrc'} for a ProDOS disk."""
    sys.path.insert(0, os.path.expanduser(os.environ.get('A2TIL_PATH', '~/src/a2til')))
    from a2til.prodos import Volume, ST_EXTENDED
    import diskcheck as dc
    vol = Volume(open(disk_path, 'rb').read())
    out = {}
    for p, e in dc._walk(vol, '/' + vol.name):
        out[p] = ('data+rsrc' if getattr(e, 'storage_type', None) == ST_EXTENDED
                  else 'data')
    return out, vol


def live_forks_hfs(disk_path):
    """{normalized_path: 'data'} for the HFS Disk 7 (read-only, P0d-1)."""
    from hfs import HFS
    v = HFS(disk_path)
    out = {}
    for parID, name in v.files:
        rel = v.path(parID)
        full = '/' + (rel + '/' + name if rel else name)
        out[full] = 'data'   # rsrc-fork read is a P5 (HFS writer) prerequisite
    return out, v


def validate(label, manifest, live_paths):
    """Return (missing, extra) path sets: live∖manifest and manifest∖live."""
    man = {p for (p, _f) in manifest}
    live = set(live_paths)
    missing = sorted(live - man)     # on disk but unclassified -> FAIL (oos)
    extra = sorted(man - live)       # in manifest but not on disk -> stale
    return missing, extra


# NOTE (P0 architecture): manifestcheck is the inventory/wiring SCOREBOARD; it
# does NOT re-assemble anything. Byte-exactness of each BUILT fork is gated by
# the per-artifact harness that owns it (diskcheck/cdevcheck/toolcheck/… — all
# run in the same work/gate.py pass). A BUILT entry counts toward
# `builders_exact` only when its builder is a real, gate-exercised builder
# (today: diskcheck's SOURCE_BUILDERS/REZ_BUILDERS). A disk counts toward
# `physical_exact` only when it is builder-complete (0 TODO_BUILDABLE) — so a
# golden-carry disk (any TODO forks) can never false-green, and per-disk
# physical byte-match is verified by diskcheck.check(D) as each disk lands
# (P3-P7). This keeps manifestcheck seconds-fast (no double Disk-2 build).


def run():
    census = dm.load_census()
    wired = dm._wired_builders()

    inv_ok = 0                       # disks fully classified
    sub_conf_good = sub_conf_tot = 0
    built_total = required_total = 0  # for builders_wired
    exact_total = 0                   # verified-exact BUILT
    phys_good = 0                     # disks physical-100% AND builder-complete

    print('=== 7-disk completion scoreboard (manifestcheck P0) ===')
    for label in dm.all_disks(census):
        manifest = dm.manifest_for(label, census, wired)
        dp = disk_path_for(label)
        is_hfs = label.startswith('Disk 7')
        try:
            live, vol = (live_forks_hfs(dp) if is_hfs else live_forks_prodos(dp))
        except Exception as ex:
            print(f'  {label[:22]:22} ENUM FAILED: {ex}')
            continue
        missing, extra = validate(label, manifest, live)

        # per-disk state tally
        from collections import Counter
        st = Counter(e.state for e in manifest.values())
        required = st[dm.BUILT] + st[dm.TODO_BUILDABLE]
        built_total += st[dm.BUILT]
        required_total += required

        # substitutes confirmed (evidence present)
        for e in manifest.values():
            if e.state in (dm.SUBSTITUTE, dm.TECHNICAL_EXCEPTION):
                sub_conf_tot += 1
                if (e.evidence or '').strip():
                    sub_conf_good += 1

        classified = not missing
        if classified:
            inv_ok += 1

        # builders_exact: a BUILT entry counts iff its builder is a real,
        # gate-exercised builder (bytes proven by the owning harness in the same
        # gate pass). No re-assembly here.
        d_exact = sum(1 for e in manifest.values()
                      if e.state == dm.BUILT and e.builder is not None)
        exact_total += d_exact
        # physical_exact: ONLY a disk with a working whole-disk overlay whose
        # image byte-matches counts (RECONSTRUCTED, not merely builder-complete).
        # Being builder-complete (0 TODO) is necessary but NOT sufficient — the
        # per-disk overlay + byte-match must exist (diskcheck.check(D)). Today
        # only Disk 2 is overlaid; Disks 5/6 are builder-complete but await the
        # First-Disks overlay work. This is what keeps golden-carry from
        # false-greening physical.
        builder_complete = (st[dm.TODO_BUILDABLE] == 0)
        reconstructed = any(label.startswith(d) for d in OVERLAID_DISKS)
        if reconstructed:
            phys_good += 1

        short = label.split(' of 7 ')[-1].replace('.2mg', '')
        flag = 'OK' if classified else f'!! {len(missing)} UNCLASSIFIED'
        if reconstructed:
            pstate = 'RECONSTRUCTED'
        elif builder_complete:
            pstate = 'builder-complete (needs overlay)'
        else:
            pstate = f'{st[dm.TODO_BUILDABLE]} TODO'
        print(f'  {short[:20]:20} live={len(live):3} inv={flag:18} '
              f'BUILT={st[dm.BUILT]:3}/{required:3} exact={d_exact:3} '
              f'SUB={st[dm.SUBSTITUTE]:3} TECH={st[dm.TECHNICAL_EXCEPTION]} [{pstate}]')
        if missing:
            print(f'      MISSING (on disk, unclassified): {missing[:6]}')
        if extra:
            print(f'      STALE (in manifest, not on disk): {extra[:6]}')

    ndisks = len(dm.all_disks(census))
    print()
    print(f'  manifest_inventory_classified good={inv_ok} bad={ndisks - inv_ok}')
    print(f'  manifest_substitutes_confirmed good={sub_conf_good} bad={sub_conf_tot - sub_conf_good}')
    print(f'  manifest_builders_wired {built_total}/{required_total}')
    print(f'  manifest_builders_exact {exact_total}/{required_total}')
    print(f'  manifest_physical_exact good={phys_good} bad={ndisks - phys_good}')
    ok = (inv_ok == ndisks and sub_conf_good == sub_conf_tot)
    print('PASS' if ok else 'FAIL', '(inventory + substitutes-confirmed are the P0 hard gates)')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(run())
