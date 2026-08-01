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
                                  evidence (prose non-empty — P0 hard gate,
                                  UNCHANGED by the C2 packet below)
  manifest_substitutes_structured every SUBSTITUTE/TECH fork's evidence is
                                  STRUCTURED (a `search` object with a
                                  non-null `decision` — see C2 below).  A
                                  RATCHET metric, not (yet) a P0 hard gate:
                                  it exists to migrate substitute claims off
                                  bare prose over time.  From this packet
                                  forward, any NEW substitute/exception claim
                                  should carry a full search object
                                  (searched_trees + search_patterns +
                                  search_date + decision), not just prose —
                                  see docs/substitute_search_evidence_2026-08-01.json
                                  for the shape.
  manifest_builders_wired         BUILT forks / required (BUILT+TODO_BUILDABLE)
  manifest_builders_exact         BUILT forks whose PROOF is currently exact
                                  (a CallableProof, always; or a HarnessProof
                                  whose every metric shows bad==0 in
                                  work/gate_baseline.json RIGHT NOW — B1,
                                  ties "exact" to live gate state instead of a
                                  bare `builder is not None` check)
  manifest_physical_exact         disks physical-100% AND builder-complete
                                  (no TODO_BUILDABLE, no UNACCEPTED
                                  TECHNICAL_EXCEPTION fork — see C1 below) —
                                  so golden-carry alone can NOT make a disk
                                  count
  manifest_technical_exceptions_accepted
                                  TECHNICAL_EXCEPTION forks with a machine-
                                  readable human `accepted` marker (C1,
                                  finding #4) vs. without one.  An unaccepted
                                  TECHNICAL_EXCEPTION now BLOCKS
                                  builder-complete for its disk (shown as
                                  "blocked: unaccepted TECH_EXCEPTION" in the
                                  per-disk state) — P7 (or a human explicitly
                                  accepting the exception) is required before
                                  that disk can count toward
                                  manifest_physical_exact.

Gate-scraped lines use the `good=N bad=M` / `A/B` shapes work/gate.py expects
(UNCHANGED from the file-granular version — only what feeds them changed).

ProDOS disks (1-6) enumerate via a2til; Disk 7 is HFS-in-2IMG (via
work/hfs.py) — B2 fixed `live_forks_hfs` to enumerate BOTH the data AND
resource fork of every file (work/hfs.py's `HFS.rsrc()` can read them; the
2026-07-30 file-granular version silently treated Disk 7 as data-only,
adversarial-review finding #3).  Disk 7 build/overlay remains P5 (the HFS
writer, P0d-2) — here it is inventory + substitute-confirmed + read-only fork
extraction only.

--- Reporting honesty (finding #6) ------------------------------------------

The no-flag default mode's summary line is `P0 PASS` / `P0 FAIL (...)`, not a
bare `PASS`/`FAIL` — it is explicitly scoped to the two P0 hard gates
(inventory + substitutes-confirmed), never a claim that builders/physical
metrics are complete.  Its exit code is UNCHANGED (0 iff those two P0 gates
hold) — work/gate.py's FULL_CHECKS entry for `manifestcheck` still requires
this to stay exit-0 while its P0 gates pass.

`--tier-a` is a SEPARATE, stricter mode (the P8 completion command) that
prints a per-metric verdict list and exits nonzero unless ALL of: inventory
7/7, substitutes_confirmed bad=0, builders_wired bad=0, builders_exact bad=0,
physical_exact good=7, and every TECHNICAL_EXCEPTION accepted.  It is NOT
wired into work/gate.py (by design it must fail today — Tier A is not done).
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
OVERLAID_DISKS = {'Disk 2', 'Disk 5', 'Disk 6', 'Disk 1', 'Disk 7', 'Disk 3',
                  'Disk 4'}


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
    enumerated here, not just the data fork.  HFS access is a2til's
    (a2til.hfs.HfsVolume, upstreamed 2026-08-01 — a2til issue #9 / PR #10;
    fork sizes come off each HfsEntry's own catalog record)."""
    sys.path.insert(0, os.path.expanduser(
        os.environ.get('A2TIL_PATH', '~/src/a2til')))
    from a2til.hfs import HfsVolume
    v = HfsVolume(disk_path, readonly=True)
    out = {}
    for path, _dirs, files in v.walk():
        base = path.rstrip('/')
        for e in files:
            out[(f'{base}/{e.name}', 'data')] = e.size
            out[(f'{base}/{e.name}', 'rsrc')] = e.rsrc_size
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


def run(tier_a=False):
    census = dm.load_census()
    harness_metrics = dm._harness_metrics_map()
    baseline = dm._baseline_metrics()

    inv_ok = 0                       # disks fully classified
    sub_conf_good = sub_conf_tot = 0
    struct_good = struct_bad = 0      # C2: substitutes_structured
    built_total = required_total = 0  # for builders_wired
    exact_total = 0                   # verified-exact BUILT
    phys_good = 0                     # disks physical-100% AND builder-complete
    tech_acc_good = tech_acc_bad = 0  # C1: technical_exceptions_accepted
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

        # substitutes confirmed (evidence present) + C2 structured evidence
        for e in manifest.values():
            if e.state in (dm.SUBSTITUTE, dm.TECHNICAL_EXCEPTION):
                sub_conf_tot += 1
                if (e.evidence or '').strip():
                    sub_conf_good += 1
                if e.search is not None and e.search.get('decision') is not None:
                    struct_good += 1
                else:
                    struct_bad += 1
            if e.state == dm.TECHNICAL_EXCEPTION:
                if e.is_accepted():
                    tech_acc_good += 1
                else:
                    tech_acc_bad += 1

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
        # builder_complete (C1, finding #4): no TODO_BUILDABLE AND no
        # UNACCEPTED TECHNICAL_EXCEPTION fork. An exception nobody has
        # explicitly accepted now blocks completion exactly like an
        # unbuilt fork does — P7 (crack the case-B wall) or a human
        # `accepted` marker are the only ways past it.
        has_unaccepted_tech = any(
            e.state == dm.TECHNICAL_EXCEPTION and not e.is_accepted()
            for e in manifest.values())
        builder_complete = (st[dm.TODO_BUILDABLE] == 0) and not has_unaccepted_tech
        # physical_exact: ONLY a disk with a working whole-disk overlay whose
        # image byte-matches counts (RECONSTRUCTED, not merely builder-complete).
        reconstructed = any(label.startswith(d) for d in OVERLAID_DISKS)
        if reconstructed and builder_complete:
            phys_good += 1

        short = label.split(' of 7 ')[-1].replace('.2mg', '')
        flag = 'OK' if classified else f'!! {len(missing)} UNCLASSIFIED'
        if reconstructed and builder_complete:
            pstate = 'RECONSTRUCTED'
        elif builder_complete:
            pstate = 'builder-complete (needs overlay)'
        else:
            blockers = []
            if st[dm.TODO_BUILDABLE] > 0:
                blockers.append(f'{st[dm.TODO_BUILDABLE]} TODO')
            if has_unaccepted_tech:
                blockers.append('unaccepted TECH_EXCEPTION')
            pstate = 'blocked: ' + ', '.join(blockers)
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
    print(f'  manifest_substitutes_structured good={struct_good} bad={struct_bad}')
    print(f'  manifest_builders_wired {built_total}/{required_total}')
    print(f'  manifest_builders_exact {exact_total}/{required_total}')
    print(f'  manifest_physical_exact good={phys_good} bad={ndisks - phys_good}')
    print(f'  manifest_technical_exceptions_accepted good={tech_acc_good} bad={tech_acc_bad}')
    if all_size_mismatches:
        print(f'  fork-size mismatches (census vs live, informational, '
              f'NOT gated): {len(all_size_mismatches)}')

    p0_ok = (inv_ok == ndisks and sub_conf_good == sub_conf_tot)

    if tier_a:
        # --tier-a (finding #6): the P8 completion command. NOT wired into
        # work/gate.py -- by design it must fail until Tier A is genuinely
        # done. Every condition below is re-derived from the SAME counters
        # the scoreboard above just printed, so this can never disagree with
        # the gate-scraped lines.
        verdicts = [
            ('inventory 7/7', inv_ok == ndisks),
            ('substitutes_confirmed bad=0', sub_conf_good == sub_conf_tot),
            ('builders_wired bad=0', built_total == required_total),
            ('builders_exact bad=0', exact_total == required_total),
            ('physical_exact good=7', phys_good == ndisks),
            ('technical exceptions all accepted', tech_acc_bad == 0),
        ]
        print()
        print('=== Tier-A completion verdict ===')
        tier_a_ok = True
        for label, cond_ok in verdicts:
            print(f'  [{"PASS" if cond_ok else "FAIL"}] {label}')
            tier_a_ok = tier_a_ok and cond_ok
        print('TIER-A PASS' if tier_a_ok else 'TIER-A FAIL')
        return 0 if tier_a_ok else 1

    print('P0 PASS' if p0_ok else
          'P0 FAIL (inventory + substitutes-confirmed are the P0 hard gates)')
    return 0 if p0_ok else 1


if __name__ == '__main__':
    sys.exit(run(tier_a='--tier-a' in sys.argv))
