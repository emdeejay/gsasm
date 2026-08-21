#!/usr/bin/env python3
"""reconcilecheck.py — the STANDING reconciliation between the ledgers that
each independently record "this fork is built from source and wired into its
disk" (docs/ARCHITECTURE_REVIEW_2026-08-02.md finding 4, "One fact, seven
ledgers", and the 0.6.0 slate item 3).

    python3 work/reconcilecheck.py

That one fact is written down in seven places: the census fork
classification, the census `proven_by`, diskcheck's `DISK_BUILDER_REGISTRY`
(+ SOURCE_BUILDERS/REZ_BUILDERS and disk7check's `_TARGETS`), diskcheck's
Disk-2-only `MANIFEST`, `manifestcheck.OVERLAID_DISKS`, work/gate.py's CHECKS
table, and the committed baseline.  Some pairs were already reconciled at
runtime (`diskmanifest._wired_builders`); most were reconciled only by a
release-eve audit, which is exactly how three strays survived until release
eve once already.  This check runs the reconciliation on EVERY gate pass and
exits nonzero the day the ledgers disagree.

It deliberately does NOT collapse the ledgers into one — that is a later,
larger packet.  It makes their disagreement loud.

--- What is reconciled -------------------------------------------------------

1. CENSUS REGENERABILITY (ledger -> census).  docs/disk_census.json must be
   byte-identical to a fresh `work/censusledger.py` regeneration.  This is the
   guard for the failure mode the review named: someone edits the generated
   JSON by hand, and the next regeneration silently reverts them.
   Metric: `ledger_census_regenerable good=1 bad=0`.

2. REGISTRY -> CENSUS.  Every (path, fork) with a wired builder for a disk
   must be classified `built` in that disk's census records.  A builder wired
   for a fork the census calls SUBSTITUTE/TODO_BUILDABLE is a STRAY: either
   the census is stale or the builder is overlaying something nobody claims.

3. CENSUS -> REGISTRY.  Every fork the census classifies `built` on a disk
   that is RECONSTRUCTED (an OverlayProof — see diskmanifest.overlay_proofs())
   must have a builder wired for that disk.  A `built` fork with no wiring on
   a reconstructed disk means the whole-disk image is carrying golden bytes
   for something the census says we build — the exact overclaim the 2026-08-01
   release review had to catch by hand.
   Metric for 2+3 together: `ledger_forks_reconciled good=<agreeing pairs>
   bad=<divergences>`, where `bad` also absorbs the structural failures in 4.

4. THE REMAINING TABLES.  diskcheck's Disk-2 `MANIFEST` ownership label must
   agree with the Disk-2 census (BUILD/REZ <-> at least one `built` fork;
   SUBSTITUTE <-> no `built` fork), and every OverlayProof behind
   `manifestcheck.OVERLAID_DISKS` must validate structurally.  These fold
   into `ledger_forks_reconciled`'s `bad` count rather than earning metrics of
   their own; the printed report names each one individually.

--- Where the wired set comes from ------------------------------------------

`wired_forks_for_disk()` mirrors diskcheck's OWN overlay routing rather than
re-deriving it, so this check cannot drift from what a gate pass actually
exercises:

    Disk 2  -> diskcheck.SOURCE_BUILDERS (data) + REZ_BUILDERS (rsrc)
               (diskcheck.check()'s path)
    Disk 7  -> disk7check._TARGETS, HFS colon paths mapped to '/' paths
               (diskcheck.reconstruct_hfs()'s path)
    others  -> diskcheck.DISK_BUILDER_REGISTRY[label] via _iter_registry()
               (diskcheck.reconstruct()'s path)

--- Exit code ---------------------------------------------------------------

Nonzero on ANY divergence, so the gate fails hard even before its regex scrape
(work/gate.py treats a nonzero check exit as fatal — 2026-08-01 adversarial-
review finding #7).  Both metric lines are printed either way.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import ensure_repo_on_path  # noqa: E402
ensure_repo_on_path()

import censusledger  # noqa: E402
import diskmanifest as dm  # noqa: E402


def _hfs_path(colon_path):
    """':System Folder:Basic.System' -> '/System Folder/Basic.System' (the
    census/manifestcheck spelling of an HFS path)."""
    return '/' + colon_path.lstrip(':').replace(':', '/')


def wired_forks_for_disk(disk_label):
    """{(path, fork): builder} exactly as diskcheck would overlay this disk.

    NB this is deliberately narrower than diskmanifest._wired_builders(), which
    unions the Disk-2 SOURCE_BUILDERS/REZ_BUILDERS into every disk's wired set
    (harmless there — the Disk-2 paths never match another disk's census paths
    — but it would make a registry->census sweep silently skip real strays)."""
    import diskcheck as dc
    if disk_label.startswith('Disk 7'):
        import disk7check
        return {(_hfs_path(p), 'data'): b for p, b in disk7check._TARGETS}
    if disk_label.startswith('Disk 2'):
        wired = {(p, 'data'): b for p, b in dc.SOURCE_BUILDERS.items()}
        wired.update({(p, 'rsrc'): b for p, b in dc.REZ_BUILDERS.items()})
        return wired
    reg = dc.DISK_BUILDER_REGISTRY.get(disk_label, {})
    return {(p, f): b for p, f, b in dc._iter_registry(reg)}


def census_forks_for_disk(census, disk_label):
    """{(path, fork): fork record} from the live census."""
    out = {}
    for f in census['disks'][disk_label]['files']:
        forks = f.get('forks')
        if not isinstance(forks, dict):
            raise RuntimeError(
                f'GENERATION ERROR: {disk_label} {f["path"]!r} has no '
                f"fork-granular 'forks' dict — census is stale; re-run "
                f'work/censusledger.py')
        for fork, fi in forks.items():
            out[(f['path'], fork)] = fi
    return out


def reconcile_disk(census, disk_label, reconstructed):
    """Two-directional reconciliation for one disk.
    Returns (agreements, [divergence strings])."""
    cen = census_forks_for_disk(census, disk_label)
    wired = wired_forks_for_disk(disk_label)
    built = {k for k, v in cen.items() if v.get('classification') == 'built'}
    problems = []

    # direction A: registry -> census
    for key in sorted(wired):
        rec = cen.get(key)
        if rec is None:
            problems.append(
                f'{disk_label}: STRAY BUILDER {key[0]!r} fork={key[1]!r} is '
                f'wired in diskcheck but has NO census fork record (the disk '
                f'or the census moved without the other)')
        elif rec.get('classification') != 'built':
            problems.append(
                f'{disk_label}: STRAY BUILDER {key[0]!r} fork={key[1]!r} is '
                f'wired in diskcheck but the census classifies it '
                f'{rec.get("classification")!r}, not \'built\' (either the '
                f'census is stale or the overlay is claiming a substitute)')

    # direction B: census -> registry (only on a RECONSTRUCTED disk; a disk
    # with no whole-disk overlay legitimately proves forks by harness alone)
    if reconstructed:
        for key in sorted(built - set(wired)):
            problems.append(
                f'{disk_label}: UNWIRED BUILT FORK {key[0]!r} fork={key[1]!r} '
                f'is census-\'built\' (proven_by='
                f'{cen[key].get("proven_by")!r}) but no builder is wired for '
                f'it, so the reconstructed image carries its GOLDEN bytes')

    agreements = len(built & set(wired))
    return agreements, problems


def reconcile_disk2_manifest(census):
    """diskcheck's Disk-2-only MANIFEST ownership labels vs the census."""
    import diskcheck as dc
    label = next(d for d in dm.all_disks(census) if d.startswith('Disk 2'))
    cen = census_forks_for_disk(census, label)
    by_path = {}
    for (path, fork), rec in cen.items():
        by_path.setdefault(path, {})[fork] = rec.get('classification')
    problems = []
    checked = 0
    for path, owner in sorted(dc.MANIFEST.items()):
        classes = by_path.get(path)
        if classes is None:
            problems.append(
                f'{label}: diskcheck.MANIFEST lists {path!r} but the census '
                f'has no record for it')
            continue
        checked += 1
        has_built = any(c == 'built' for c in classes.values())
        if owner in (dc.BUILD, dc.REZ) and not has_built:
            problems.append(
                f'{label}: diskcheck.MANIFEST calls {path!r} {owner!r} but the '
                f'census classifies no fork of it \'built\' ({classes})')
        elif owner == dc.SUBSTITUTE and has_built:
            problems.append(
                f'{label}: diskcheck.MANIFEST calls {path!r} a substitute but '
                f'the census classifies a fork of it \'built\' ({classes})')
    return checked, problems


def reconcile_overlay_proofs(proofs, baseline):
    """Every OverlayProof behind manifestcheck.OVERLAID_DISKS must validate."""
    problems = []
    for disk in sorted(proofs):
        if not proofs[disk].is_valid(None, set(baseline)):
            problems.append(
                f'{disk}: OverlayProof metric {proofs[disk].metric!r} is not '
                f'baselined in work/gate_baseline.json, so this disk cannot '
                f'be called RECONSTRUCTED')
    return len(proofs), problems


def run():
    print('=== ledger reconciliation (census <-> registry <-> gate) ===')

    # 1. census regenerability -------------------------------------------
    regen_ok, regen_detail = censusledger.check()
    print(f'  census regenerable from work/censusledger.py: {regen_detail}')

    census = dm.load_census()
    baseline = dm._baseline_metrics()
    proofs = dm.overlay_proofs(baseline)

    agreements = 0
    problems = []
    for label in dm.all_disks(census):
        short = label.split(' of 7 ')[0]
        reconstructed = short in proofs
        n, probs = reconcile_disk(census, label, reconstructed)
        agreements += n
        problems.extend(probs)
        state = 'RECONSTRUCTED' if reconstructed else 'no whole-disk overlay'
        print(f'  {label.split(" of 7 ")[-1].replace(".2mg", "")[:20]:20} '
              f'reconciled={n:3} divergent={len(probs):2} [{state}]')

    n_manifest, probs = reconcile_disk2_manifest(census)
    problems.extend(probs)
    print(f'  diskcheck.MANIFEST (Disk 2) entries checked: {n_manifest} '
          f'divergent={len(probs)}')

    n_proofs, probs = reconcile_overlay_proofs(proofs, baseline)
    problems.extend(probs)
    print(f'  OverlayProofs behind OVERLAID_DISKS: {n_proofs} '
          f'divergent={len(probs)}')

    if problems:
        print()
        print(f'  DIVERGENCE ({len(problems)}):')
        for p in problems:
            print(f'    {p}')

    print()
    print(f'  ledger_census_regenerable good={1 if regen_ok else 0} '
          f'bad={0 if regen_ok else 1}')
    print(f'  ledger_forks_reconciled good={agreements} bad={len(problems)}')

    ok = regen_ok and not problems
    print('LEDGERS RECONCILED' if ok else
          'LEDGERS DIVERGED (see the DIVERGENCE list above)')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(run())
