#!/usr/bin/env python3
"""manifestcheck.py — P0b/P0c (+B1/B2 hardening): the 7-disk completion
scoreboard, now at FORK granularity.

Implements the builder-correctness metrics from docs/SOW_COMPLETION.md §2 (the
Codex-review model — physical byte-match alone is NOT a completion gate).  For
every disk it (P0b) validates the FORK-level manifest against a LIVE
enumeration and (P0c) reports:

  manifest_inventory_classified   every live (path, fork) has a manifest owner
                                  (oos:0)
  manifest_substitutes_confirmed  every SUBSTITUTE/TECH fork has recorded
                                  evidence
  manifest_builders_wired         BUILT forks / required (BUILT+TODO_BUILDABLE)
  manifest_builders_exact         BUILT forks whose PROOF is currently exact
                                  (a CallableProof, always; or a HarnessProof
                                  whose every metric shows bad==0 in
                                  work/gate_baseline.json RIGHT NOW — B1,
                                  ties "exact" to live gate state instead of a
                                  bare `builder is not None` check)
  manifest_physical_exact         disks physical-100% AND builder-complete
                                  (no TODO_BUILDABLE) — so golden-carry alone
                                  can NOT make a disk count

Gate-scraped lines use the `good=N bad=M` / `A/B` shapes work/gate.py expects
(UNCHANGED from the file-granular version — only what feeds them changed).

ProDOS disks (1-6) enumerate via a2til; Disk 7 is HFS-in-2IMG (via
work/hfs.py) — B2 fixed `live_forks_hfs` to enumerate BOTH the data AND
resource fork of every file (work/hfs.py's `HFS.rsrc()` can read them; the
2026-07-30 file-granular version silently treated Disk 7 as data-only,
adversarial-review finding #3).  Disk 7 build/overlay remains P5 (the HFS
writer, P0d-2) — here it is inventory + substitute-confirmed + read-only fork
extraction only.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import ROOT, ensure_repo_on_path  # noqa: E402
ensure_repo_on_path()

import diskmanifest as dm  # noqa: E402

DISKROOT = os.path.join(
    ROOT, 'ref', 'GSOS_6', 'System601_disks', 'System 6.0.1')

# Disks with a working whole-disk overlay whose reconstructed image byte-matches
# the golden (RECONSTRUCTED).  Membership here is BACKED by hard gate metrics in
# the same --full pass: disk2/5/6_physical_exact scrape diskcheck's PHYSICAL
# line, and diskcheck exits nonzero on any physical mismatch (which gate.py now
# treats as fatal).  A disk must NOT be added here without also adding its
# physical metric to work/gate.py FULL_CHECKS — otherwise physical_exact would
# revert to an unbacked label count (adversarial-review finding #1).  Being
# merely builder-complete (0 TODO) does NOT put a disk here — the overlay must
# exist.
OVERLAID_DISKS = {'Disk 2', 'Disk 5', 'Disk 6'}


def disk_path_for(label):
    return os.path.join(DISKROOT, label)


def live_forks_prodos(disk_path):
    """{(path, fork): size} for a ProDOS disk.  A plain (non-extended) file
    contributes only its 'data' key; an extended-storage-type file
    contributes both 'data' and 'rsrc' (even if one is 0 bytes — the key
    block genuinely exists on disk)."""
    sys.path.insert(0, os.path.expanduser(os.environ.get('A2TIL_PATH', '~/src/a2til')))
    from a2til.prodos import Volume
    import diskcheck as dc
    vol = Volume(open(disk_path, 'rb').read())
    out = {}
    for p, e in dc._walk(vol, '/' + vol.name):
        f = dc.DiskFile(p, e, vol)
        out[(p, 'data')] = f.data_eof
        if f.has_rsrc:
            out[(p, 'rsrc')] = f.rsrc_eof
    return out, vol


def live_forks_hfs(disk_path):
    """{(path, fork): size} for the HFS Disk 7 (read-only, P0d-1).

    B2 fix (adversarial-review finding #3): every HFS catalog file record
    structurally carries BOTH a data-fork and a resource-fork length field
    (filDLgLen / filRLgLen), even when one is 0 bytes — so both are ALWAYS
    enumerated here, not just the data fork.  work/hfs.py's `HFS.rsrc()`
    performs the actual resource-fork extent read (verified: reads all 12
    Disk-7 files' resource forks, sizes matching the census exactly)."""
    from hfs import HFS
    v = HFS(disk_path)
    out = {}
    for (parID, name), (lg, _ext, _ft) in v.files.items():
        rel = v.path(parID)
        full = '/' + (rel + '/' + name if rel else name)
        rlg, _rext = v.rforks.get((parID, name), (0, []))
        out[(full, 'data')] = lg
        out[(full, 'rsrc')] = rlg
    return out, v


def validate(manifest, live):
    """Return (missing, extra) (path, fork) key sets: live∖manifest and
    manifest∖live — BOTH directions, at fork granularity (B2)."""
    man = set(manifest)
    liv = set(live)
    missing = sorted(liv - man)     # on disk but unclassified -> FAIL (oos)
    extra = sorted(man - liv)       # in manifest but not on disk -> stale
    return missing, extra


def check_sizes(manifest, live):
    """Compare live fork SIZES against census-recorded sizes where the
    census records them (B2).  Reports mismatches; never fails the gate on
    them (absent size data is reported, not treated as a failure) — this is
    a diagnostic, not (yet) a gated metric."""
    mismatches = []
    unrecorded = 0
    for key, entry in manifest.items():
        if key not in live:
            continue
        if entry.size is None:
            unrecorded += 1
            continue
        if entry.size != live[key]:
            mismatches.append((key, entry.size, live[key]))
    return mismatches, unrecorded


def _proof_is_exact(proof, baseline):
    return proof is not None and proof.is_exact(baseline)


def run():
    census = dm.load_census()
    harness_metrics = dm._harness_metrics_map()
    baseline = dm._baseline_metrics()

    inv_ok = 0                       # disks fully classified
    sub_conf_good = sub_conf_tot = 0
    built_total = required_total = 0  # for builders_wired
    exact_total = 0                   # verified-exact BUILT
    phys_good = 0                     # disks physical-100% AND builder-complete
    all_size_mismatches = []

    print('=== 7-disk completion scoreboard (manifestcheck P0, fork-granular) ===')
    for label in dm.all_disks(census):
        try:
            wired = dm._wired_builders(label)
        except Exception:
            wired = {}
        try:
            manifest = dm.manifest_for(label, census, wired,
                                       harness_metrics=harness_metrics,
                                       baseline=baseline)
        except RuntimeError as ex:
            # A GENERATION ERROR (B1: an invalid BUILT proof) is a hard stop,
            # not a metric dip -- surface it loudly and let the caller's
            # nonzero exit (below) fail the gate.
            print(f'  {label[:22]:22} MANIFEST GENERATION FAILED: {ex}')
            return 1
        dp = disk_path_for(label)
        is_hfs = label.startswith('Disk 7')
        try:
            live, vol = (live_forks_hfs(dp) if is_hfs else live_forks_prodos(dp))
        except Exception as ex:
            print(f'  {label[:22]:22} ENUM FAILED: {ex}')
            continue
        missing, extra = validate(manifest, live)
        mismatches, unrecorded = check_sizes(manifest, live)
        all_size_mismatches.extend(mismatches)

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

        # builders_exact (B1): a BUILT entry counts iff its proof is a
        # CallableProof (always exact by construction), OR a HarnessProof
        # whose every metric currently shows bad==0 in gate_baseline.json.
        # This can legitimately sit BELOW builders_wired.
        d_exact = sum(1 for e in manifest.values()
                      if e.state == dm.BUILT and _proof_is_exact(e.proof, baseline))
        exact_total += d_exact
        # physical_exact: ONLY a disk with a working whole-disk overlay whose
        # image byte-matches counts (RECONSTRUCTED, not merely builder-complete).
        builder_complete = (st[dm.TODO_BUILDABLE] == 0)
        reconstructed = any(label.startswith(d) for d in OVERLAID_DISKS)
        if reconstructed and builder_complete:
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
        if mismatches:
            print(f'      SIZE MISMATCH (census vs live, informational): '
                  f'{mismatches[:6]}')

    ndisks = len(dm.all_disks(census))
    print()
    print(f'  manifest_inventory_classified good={inv_ok} bad={ndisks - inv_ok}')
    print(f'  manifest_substitutes_confirmed good={sub_conf_good} bad={sub_conf_tot - sub_conf_good}')
    print(f'  manifest_builders_wired {built_total}/{required_total}')
    print(f'  manifest_builders_exact {exact_total}/{required_total}')
    print(f'  manifest_physical_exact good={phys_good} bad={ndisks - phys_good}')
    if all_size_mismatches:
        print(f'  fork-size mismatches (census vs live, informational, '
              f'NOT gated): {len(all_size_mismatches)}')
    ok = (inv_ok == ndisks and sub_conf_good == sub_conf_tot)
    print('PASS' if ok else 'FAIL', '(inventory + substitutes-confirmed are the P0 hard gates)')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(run())
