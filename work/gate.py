#!/usr/bin/env python3
"""Regression gate: run every byte-match check and fail if any metric regresses.

Each check emits a headline "good/total" (or "ok/bad") line.  We parse it into
(good, bad) where the invariant for a non-regression is:

    good  must NOT decrease   (fewer byte-exact matches = regression)
    bad   must NOT increase   (more mismatched bytes    = regression)

Baselines live in work/gate_baseline.json (committed).  Usage:

    python3 work/gate.py            # gate the fast corpus (exit 1 on regression)
    python3 work/gate.py --full     # also run diskcheck (slow; needs a2til)
    python3 work/gate.py --update   # rerun and rewrite the baseline

The gate is deliberately direction-aware, not total-pinned: a corpus that grows
(good up AND bad up) surfaces as a bad-count rise, i.e. "needs review" -> rerun
with --update once you've confirmed the new bytes are accounted for.
"""
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASELINE = os.path.join(ROOT, 'work', 'gate_baseline.json')

# Each check: (name, argv, [(metric, regex, kind), ...])
#   kind 'frac' -> regex groups are (good, total); bad = total - good
#   kind 'okbad'-> regex groups are (good, bad)
#   kind 'count'-> regex group is (good,);        bad = 0
CHECKS = [
    ('objcheck', ['objcheck.py'], [
        ('obj_identical', r'OBJ byte-identical:\s*(\d+)/(\d+)', 'frac')]),
    ('linkcheck', ['linkcheck.py'], [
        ('link_identical', r'(\d+)\s+LINK_IDENTICAL', 'count')]),
    ('kernelcheck', ['kernelcheck.py'], [
        ('kernel_bytes', r'TOTAL\s+(\d+)/(\d+)', 'frac')]),
    ('p8check', ['p8check.py'], [
        ('p8_bytes', r'P8 raw code-image match:\s*(\d+)/(\d+)', 'frac')]),
    # BASIC.System — the ProDOS-8 command interpreter (pure ASM; Applesoft is
    # in ROM, not here). makebin_segments over Loader/Main/Globals @ $2000 +
    # temporg, byte-exact against BOTH shipping copies (Disk 2 System Disk +
    # Disk 3 SystemTools1). See work/basiccheck.py; also counted in diskcheck.
    ('basiccheck', ['basiccheck.py'], [
        ('basic_system_bytes_exact',
         r'BASIC_SYSTEM_BYTES_EXACT\s+(\d+)/(\d+)', 'frac')]),
    ('fstcheck', ['fstcheck.py'], [
        ('fst_bytes', r'CORPUS raw code-image match:\s*(\d+)/(\d+)', 'frac')]),
    ('drivercheck', ['drivercheck.py'], [
        ('driver_bytes', r'CORPUS raw code-image match:\s*(\d+)/(\d+)', 'frac')]),
    ('toolcheck', ['toolcheck.py'], [
        ('tool_bytes', r'CORPUS raw code-image match:\s*(\d+)/(\d+)', 'frac')]),
    # The Disk 4 IWEM driver — NOT 65816 code but the ImageWriter-Emulator
    # PostScript proc set, rebuilt byte-exact by replaying the MPW BuildIWEm
    # text-squeeze script over IWEm.Src (see work/iwemcheck.py; cracked
    # 2026-08-01 — the census's earlier verify-negative had compared against
    # the tree's prebuilt stripped artifact instead of replaying the script).
    ('iwemcheck', ['iwemcheck.py'], [
        ('iwem_bytes_exact', r'IWEM_BYTES_EXACT (\d+)/(\d+)', 'frac')]),
    # The four literal-text DATA forks (Disk 4 Read.Me/Shortcuts/Whats.New +
    # Disk 5 Fonts Read.Me): shipped verbatim from tracked source text files
    # (makefile Duplicate rules); this harness is the 1:1 byte comparison the
    # census gap-list said was missing (see work/textdatacheck.py).
    ('textdatacheck', ['textdatacheck.py'], [
        ('text_data_bytes_exact',
         r'TEXT_DATA_BYTES_EXACT (\d+)/(\d+)', 'frac')]),
    ('bytecheck', ['bytecheck.py'], [
        ('opcode_bytes', r'OPCODE bytes:\s*(\d+) ok / (\d+) bad', 'okbad'),
        ('operand_values', r'OPERAND values[^:]*:\s*(\d+) ok / (\d+) bad', 'okbad')]),
    # M7/R7 done-gate: the golden Sys.Resources resource fork, reproduced
    # byte-exact from source via BOTH the library pipeline and the `gsrez`
    # CLI (work/rezbuildcheck.py). The cheaper per-packet rez suites
    # (rezcheck/rezemitcheck/rezgencheck/rezloadcheck) are deliberately NOT
    # separately gated here: none of them print a "good/bad" pair that
    # actually dips on a missing (as opposed to merely mismatched) resource
    # (see rezgencheck.py's separate n_fail/n_missing counters), so folding
    # them into this table's regex-driven scheme would risk a metric that
    # silently stops catching a real regression; rezbuildcheck.py's single
    # end-to-end byte count has no such gap (any failure anywhere in the
    # pipeline collapses it to 0).
    ('rezbuildcheck', ['rezbuildcheck.py'], [
        ('rez_sysresources_bytes_exact',
         r'REZ_SYSRESOURCES_BYTES_EXACT\s+(\d+)', 'count')]),
    # R10/R11: EasyMount, both forks byte-exact (R11 closed the data fork's
    # two diagnosed residuals: asm.py's @-label macro-scoping bug and
    # expressload.py's per-object reloc-dictionary symbol table -- see
    # work/easymountcheck.py's docstring). Each regex anchors on its own PASS
    # line, so a regression on EITHER fork makes the parse fail loudly rather
    # than shrinking a number.
    ('easymountcheck', ['easymountcheck.py'], [
        ('rez_easymount_rsrc_bytes_exact',
         r'PASS EasyMount resource fork: built=(\d+)B', 'count'),
        ('rez_easymount_data_bytes_exact',
         r'PASS EasyMount data fork: built=(\d+)B', 'count')]),
    # E1: System 6.0.1 single-segment ExpressLoad files whose code image was
    # already byte-exact but whose ~ExpressLoad wrapper/reloc-dict differed —
    # Start (Disk 1, loadfile_name LOADNAME), QuickLogoff (Disk 4, null reloc
    # pointer), Tool038/MediaCtlTool (Disk 4, net-zero-weight same-segment
    # label differences).  See work/expressloadcheck.py.
    ('expressloadcheck', ['expressloadcheck.py'], [
        ('expressload_sys601_bytes_exact',
         r'EXPRESSLOAD_SYS601_BYTES_EXACT (\d+)/(\d+)', 'frac')]),
    # Disk 7 (Apple II Setup, HFS) buildable data forks — builder-correctness
    # only (no whole-disk overlay). See work/disk7check.py.
    ('disk7check', ['disk7check.py'], [
        ('disk7_bytes_exact', r'DISK7_BYTES_EXACT (\d+)/(\d+)', 'frac')]),
    # The Installer DATA fork (Disk 1) — the set's second-largest ExpressLoad
    # application, 9 load segments + ~JumpTable. See work/installerdatacheck.py.
    ('installerdatacheck', ['installerdatacheck.py'], [
        ('installer_data_bytes_exact',
         r'INSTALLER_DATA_BYTES_EXACT (\d+)/(\d+)', 'frac')]),
    # Rez tier-1 CDEV forks (clean-room include; rCDEVCode extraction-fed —
    # see work/cdevcheck.py's docstring for exactly what this proves).
    ('cdevcheck', ['cdevcheck.py'], [
        ('cdev_rsrc_bytes_exact',
         r'CDEV_RSRC_BYTES_EXACT\s+(\d+)/(\d+)', 'frac')]),
    # Rez tier-1 Finder fork (clean-room include; fully source-built, incl.
    # the assembled KeyboardNav read payload — see work/findercheck.py).
    # Checked against BOTH shipped copies (Disk 3 Finder + System Disk
    # Start, byte-identical).
    ('findercheck', ['findercheck.py'], [
        ('finder_rsrc_bytes_exact',
         r'FINDER_RSRC_BYTES_EXACT\s+(\d+)/(\d+)', 'frac')]),
    # Rez tier-1 Installer fork (self-contained Installer.r — corpus-local
    # templates; proves the dialect, see work/installercheck.py).
    ('installercheck', ['installercheck.py'], [
        ('installer_rsrc_bytes_exact',
         r'INSTALLER_RSRC_BYTES_EXACT\s+(\d+)/(\d+)', 'frac')]),
    # Rez tier-1 Teach fork (clean-room include; Pascal code stays a wall,
    # the Rez layer is proven — see work/teachcheck.py).
    ('teachcheck', ['teachcheck.py'], [
        ('teach_rsrc_bytes_exact',
         r'TEACH_RSRC_BYTES_EXACT\s+(\d+)/(\d+)', 'frac')]),
    # Finder DATA fork (work-in-progress: per-segment code images via the
    # jump-table-aware multi-seg link; ratchet metric — see
    # work/finderdatacheck.py).
    # ...plus the per-segment RELOCATION DICTIONARIES (interim ratchet; every
    # load segment's reloc records byte-exact via the injected BankRel/case-B
    # builder — docs/EXPRESSLOAD_FINDER_PLAN.md Stages 0-3). Superseded by a
    # full-fork finder_data_bytes_exact once the ~ExpressLoad directory
    # (Stage 4) lands.
    ('finderdatacheck', ['finderdatacheck.py'], [
        ('finder_data_code_bytes',
         r'FINDER_DATA_CODE_BYTES\s+(\d+)/(\d+)', 'frac'),
        ('finder_reloc_segs_exact',
         r'FINDER_RELOC_SEGS_EXACT\s+(\d+)/(\d+)', 'frac'),
        ('finder_data_bytes_exact',
         r'FINDER_DATA_BYTES_EXACT\s+(\d+)/(\d+)', 'frac')]),
    # MountImageGS NDA data fork — assembler oracle from the archived
    # 30-Apr-93 build (older LinkIIGS SUPER coverage; no rsrc oracle
    # survives, so MountImage.r stays a non-target — see the harness).
    ('mountimagecheck', ['mountimagecheck.py'], [
        ('mountimage_data_bytes_exact',
         r'MOUNTIMAGE_DATA_BYTES_EXACT\s+(\d+)/(\d+)', 'frac')]),
    # Four A.U.G data forks (CDRemote/Pioneer2000/EasyAccess/Pioneer4200) —
    # pure assembler oracles built byte-exact through the existing
    # expressload()/linkiigs.link() machinery (Disks 3/4, not the System
    # Disk, so — like cdevcheck — this contributes only its own metric,
    # NOT diskcheck).  See work/appdatacheck.py.
    ('appdatacheck', ['appdatacheck.py'], [
        ('app_data_bytes_exact',
         r'APP_DATA_BYTES_EXACT\s+(\d+)/(\d+)', 'frac')]),
    # Five small A.U.G/ToolBoxMisc resource forks (FindFile DA, Apple.Bowl,
    # MediaControl NDA, VideoMix NDA, Pioneer4200 rsrc) — same clean-room
    # Rez pipeline as cdevcheck/findercheck, no `read`/code gold-feed
    # needed for any of the five.  Disks 3/4/5, not the System Disk, so —
    # like cdevcheck/appdatacheck — this contributes only its own metric,
    # NOT diskcheck.  See work/rezforkcheck.py.
    ('rezforkcheck', ['rezforkcheck.py'], [
        ('rezfork_bytes_exact',
         r'REZFORK_BYTES_EXACT\s+(\d+)/(\d+)', 'frac')]),
    # 14 template-free `data`-statement resource forks: the 10 System Sounds
    # + 3 TeachText docs (Disk 4) + Fonts Read.Me (Disk 5), each built
    # ENTIRELY from `data <typeID>(<id>){ $"hex" }` statements — the R1
    # packet's new parser/gen/emit path (rResName-type-last data ordering,
    # verbatim hex body, FInfo-tail memo fields).  Non-System-Disk, so —
    # like cdevcheck/rezforkcheck/appdatacheck — it feeds only its own
    # metric, NOT diskcheck.  See work/rezdatacheck.py.
    ('rezdatacheck', ['rezdatacheck.py'], [
        ('rez_data_bytes_exact',
         r'REZ_DATA_BYTES_EXACT\s+(\d+)/(\d+)', 'frac')]),
]

FULL_CHECKS = [
    ('diskcheck', ['diskcheck.py'], [
        ('disk_logical_exact', r'logical-exact:\s*(\d+)/(\d+)', 'frac'),
        ('disk2_physical_exact',
         r'PHYSICAL image byte-match:\s*(\d+)/(\d+)', 'frac')]),
    # First-Disks phase: the generalized whole-disk overlay reconstructs the
    # first NON-System disks (Fonts, synthLAB) byte-exact.  BOTH metrics are
    # gated per disk: logical-exact (the builder count — physical alone is
    # trivially 100% for a no-builder run, since a failed build is simply not
    # overlaid) AND the raw physical byte-match (a corrupted overlay path can
    # break physical while logical stays green — adversarial-review finding #1).
    # These proofs back manifestcheck's OVERLAID_DISKS promotion, exactly as
    # the `diskcheck` entry above backs Disk 2's.
    ('diskcheck5', ['diskcheck.py', '--disk', 'Disk 5 of 7 Fonts.2mg'], [
        ('disk5_logical_exact', r'logical-exact:\s*(\d+)/(\d+)', 'frac'),
        ('disk5_physical_exact',
         r'PHYSICAL image byte-match:\s*(\d+)/(\d+)', 'frac')]),
    ('diskcheck6', ['diskcheck.py', '--disk', 'Disk 6 of 7 synthLAB.2mg'], [
        ('disk6_logical_exact', r'logical-exact:\s*(\d+)/(\d+)', 'frac'),
        ('disk6_physical_exact',
         r'PHYSICAL image byte-match:\s*(\d+)/(\d+)', 'frac')]),
    ('diskcheck1', ['diskcheck.py', '--disk', 'Disk 1 of 7 Install.2mg'], [
        ('disk1_logical_exact', r'logical-exact:\s*(\d+)/(\d+)', 'frac'),
        ('disk1_physical_exact',
         r'PHYSICAL image byte-match:\s*(\d+)/(\d+)', 'frac')]),
    ('diskcheck3', ['diskcheck.py', '--disk', 'Disk 3 of 7 SystemTools1.2mg'], [
        ('disk3_logical_exact', r'logical-exact:\s*(\d+)/(\d+)', 'frac'),
        ('disk3_physical_exact',
         r'PHYSICAL image byte-match:\s*(\d+)/(\d+)', 'frac')]),
    ('diskcheck4', ['diskcheck.py', '--disk', 'Disk 4 of 7 SystemTools2.2mg'], [
        ('disk4_logical_exact', r'logical-exact:\s*(\d+)/(\d+)', 'frac'),
        ('disk4_physical_exact',
         r'PHYSICAL image byte-match:\s*(\d+)/(\d+)', 'frac')]),
    # Disk 7 (HFS): whole-disk reconstruction via a2til's overlay writer
    # (issue #9 phase 2) — diskcheck.reconstruct_hfs overlays the six
    # disk7check-built data forks in place and demands whole-2IMG identity.
    # NB distinct from disk7check's own disk7_bytes_exact (fork-builder
    # correctness); this pair gates the OVERLAY surface.
    ('diskcheck7', ['diskcheck.py', '--disk', 'Disk 7 of 7 Apple II Setup.2mg'], [
        ('disk7_logical_exact', r'logical-exact:\s*(\d+)/(\d+)', 'frac'),
        ('disk7_physical_exact',
         r'PHYSICAL image byte-match:\s*(\d+)/(\d+)', 'frac')]),
    # P0: the 7-disk completion scoreboard (work/manifestcheck.py).  These are
    # the builder-correctness metrics from docs/SOW_COMPLETION.md §2 — physical
    # match alone is NOT the gate (a golden-carry disk is trivially 100%).
    # RATCHET metrics: they climb through SOW phases P2-P7 as builders wire.
    ('manifestcheck', ['manifestcheck.py'], [
        ('manifest_inventory_classified',
         r'manifest_inventory_classified good=(\d+) bad=(\d+)', 'okbad'),
        ('manifest_substitutes_confirmed',
         r'manifest_substitutes_confirmed good=(\d+) bad=(\d+)', 'okbad'),
        # C2 (finding #5): ratchet toward structured (searched_trees +
        # search_patterns + search_date + decision) substitute evidence,
        # instead of bare non-empty prose. Does NOT replace
        # manifest_substitutes_confirmed above -- that stays the P0 hard gate.
        ('manifest_substitutes_structured',
         r'manifest_substitutes_structured good=(\d+) bad=(\d+)', 'okbad'),
        ('manifest_builders_wired',
         r'manifest_builders_wired (\d+)/(\d+)', 'frac'),
        ('manifest_builders_exact',
         r'manifest_builders_exact (\d+)/(\d+)', 'frac'),
        ('manifest_physical_exact',
         r'manifest_physical_exact good=(\d+) bad=(\d+)', 'okbad'),
        # C1 (finding #4): human-acceptance state for TECHNICAL_EXCEPTION
        # forks. Zero such forks remain since the 2026-08-01 Tool.Setup
        # crack (good=0 bad=0); the metric stays as the standing guard for
        # any future exception.
        ('manifest_technical_exceptions_accepted',
         r'manifest_technical_exceptions_accepted good=(\d+) bad=(\d+)', 'okbad')]),
    # The STANDING ledger reconciliation (docs/ARCHITECTURE_REVIEW_2026-08-02.md
    # finding 4, "One fact, seven ledgers"): the census, diskcheck's builder
    # registries, diskcheck's Disk-2 MANIFEST and the OverlayProofs behind
    # manifestcheck.OVERLAID_DISKS must all agree about which forks are built
    # and wired — checked in BOTH directions, every gate pass, instead of by a
    # release-eve audit.  `ledger_census_regenerable` additionally proves the
    # generated census still matches a fresh work/censusledger.py run, so a
    # hand edit to docs/disk_census.json cannot sit undetected until the next
    # regeneration silently reverts it.  See work/reconcilecheck.py.
    ('reconcilecheck', ['reconcilecheck.py'], [
        ('ledger_census_regenerable',
         r'ledger_census_regenerable good=(\d+) bad=(\d+)', 'okbad'),
        ('ledger_forks_reconciled',
         r'ledger_forks_reconciled good=(\d+) bad=(\d+)', 'okbad')]),
]


def run_unit_tests():
    """Run the standalone unit tests (tests/test_*.py) as a HARD gate.

    These assert BEHAVIORS the byte corpus and the expected-bytes fixture suite
    cannot capture — e.g. that do_include RAISES on an unresolvable include
    (test_include_not_found.py) and that an out-of-range branch is an ERROR
    (test_branch_range.py).  Without this, a regression reverting do_include to
    "append to a.errors and continue" would still pass the corpus + fixtures (the
    exact SCSIHD-class silent-drop this milestone closed).  pytest is not assumed
    present: each test file has a __main__ runner that exits non-zero on failure,
    so the returncode IS the gate.  Returns (ok, summary_line)."""
    import glob
    ok, lines = True, []
    for tf in sorted(glob.glob(os.path.join(ROOT, 'tests', 'test_*.py'))):
        proc = subprocess.run([sys.executable, tf], cwd=ROOT,
                              capture_output=True, text=True)
        out = proc.stdout + proc.stderr
        m = re.search(r'(\d+)/(\d+) passed', out)
        tag = m.group(0) if m else (
            out.strip().splitlines()[-1] if out.strip() else '(no output)')
        lines.append(f'{os.path.basename(tf)}: {tag}')
        if proc.returncode != 0:
            ok = False
            fails = [ln.strip() for ln in out.splitlines()
                     if ln.strip().startswith('FAIL')]
            lines[-1] += ''.join('\n      ' + f for f in fails)
    return ok, '\n  '.join(lines)


def run_fixture_suite():
    """Run the corpus-free fixture suite (tests/run_fixtures.py) as a HARD gate.

    The golden-corpus checks below are BLIND to any construct the ROM sources
    don't happen to contain — a change can broaden the assembler's behavior on
    unseen inputs and still leave every corpus byte identical (see
    docs/ADVERSARIAL_REVIEW_2026-07-17.md: a numeric-addend fold that silently
    widened `ds.b`/branch parsing passed the byte gate).  The fixtures are the
    guard for that blind spot, so the gate must enforce them, not just the corpus.
    Returns (ok, summary_line).  Needs no golden material."""
    rf = os.path.join(ROOT, 'tests', 'run_fixtures.py')
    proc = subprocess.run([sys.executable, rf], cwd=ROOT,
                          capture_output=True, text=True)
    out = proc.stdout + proc.stderr
    m = re.search(r'(\d+)/(\d+) fixtures pass', out)
    summary = m.group(0) if m else (out.strip().splitlines() or ['(no output)'])[-1]
    if proc.returncode != 0:
        fails = [ln.strip() for ln in out.splitlines() if ln.strip().startswith('FAIL')]
        summary += ''.join('\n    ' + f for f in fails)
    return proc.returncode == 0, summary


def run_check(name, argv, specs):
    """Run one check; return {metric: (good, bad)} or raise on parse failure."""
    # argv[0] is the script; argv[1:] are its own CLI args (e.g. the First-Disks
    # `--disk 'Disk 5 of 7 Fonts.2mg'`).  Single-element argv is unchanged.
    proc = subprocess.run(
        [sys.executable, os.path.join(ROOT, 'work', argv[0]), *argv[1:]],
        cwd=ROOT, capture_output=True, text=True)
    out = proc.stdout + proc.stderr
    # A nonzero exit is a HARD failure even if every metric line parses: check
    # scripts signal "headline not fully exact" (or fatal validation after the
    # metric print) via returncode, and ignoring it here was adversarial-review
    # finding #7 (docs/ADVERSARIAL_REVIEW_SOW_IMPLEMENTATION_2026-08-01.md).
    if proc.returncode != 0:
        raise RuntimeError(
            f'{name}: exited {proc.returncode}.\n'
            f'--- tail of output ---\n' + '\n'.join(out.splitlines()[-15:]))
    metrics = {}
    for metric, rx, kind in specs:
        m = re.search(rx, out)
        if not m:
            raise RuntimeError(
                f'{name}: could not parse metric {metric!r} (regex {rx!r}).\n'
                f'--- tail of output ---\n' + '\n'.join(out.splitlines()[-15:]))
        if kind == 'frac':
            good, total = int(m.group(1)), int(m.group(2))
            metrics[metric] = (good, total - good)
        elif kind == 'okbad':
            metrics[metric] = (int(m.group(1)), int(m.group(2)))
        else:  # count
            metrics[metric] = (int(m.group(1)), 0)
    return metrics


def main():
    update = '--update' in sys.argv
    full = '--full' in sys.argv or update
    # --skip-fixtures: the run_fixtures --bless interlock calls gate.py to confirm
    # the CORPUS is green BEFORE it mints a new/changed fixture's expected bytes;
    # running the (not-yet-blessed) fixture suite there would deadlock, and the
    # bless step runs the suite itself anyway.
    skip_fixtures = '--skip-fixtures' in sys.argv
    checks = CHECKS + (FULL_CHECKS if full else [])

    if not skip_fixtures:
        print('running corpus-free fixtures ...', flush=True)
        fx_ok, fx_summary = run_fixture_suite()
        print(f'  {fx_summary}')
        if not fx_ok:
            print('\nFAIL: corpus-free fixture suite regressed '
                  '(a behavior changed on inputs the corpus does not exercise).')
            return 1

        print('running unit tests ...', flush=True)
        ut_ok, ut_summary = run_unit_tests()
        print(f'  {ut_summary}')
        if not ut_ok:
            print('\nFAIL: a standalone unit test regressed.')
            return 1

    baseline = {}
    if os.path.exists(BASELINE):
        with open(BASELINE) as f:
            baseline = json.load(f)

    current, regressions, improvements, missing = {}, [], [], []
    for name, argv, specs in checks:
        print(f'running {name} ...', flush=True)
        metrics = run_check(name, argv, specs)
        for metric, (good, bad) in metrics.items():
            current[metric] = [good, bad]
            base = baseline.get(metric)
            if base is None:
                missing.append(metric)
                print(f'  {metric:<20} good={good} bad={bad}   (NEW, no baseline)')
                continue
            bgood, bbad = base
            flag = ''
            if good < bgood or bad > bbad:
                regressions.append((metric, base, [good, bad]))
                flag = '  <<< REGRESSION'
            elif good > bgood or bad < bbad:
                improvements.append((metric, base, [good, bad]))
                flag = '  <<< improved'
            print(f'  {metric:<20} good={good} bad={bad}   '
                  f'(baseline good={bgood} bad={bbad}){flag}')

    if update:
        with open(BASELINE, 'w') as f:
            json.dump(current, f, indent=2, sort_keys=True)
            f.write('\n')
        print(f'\nbaseline written: {BASELINE} ({len(current)} metrics)')
        return 0

    print()
    if regressions:
        print(f'FAIL: {len(regressions)} regression(s)')
        for metric, base, cur in regressions:
            print(f'  {metric}: {base} -> {cur}')
        return 1
    if missing:
        print(f'FAIL: {len(missing)} metric(s) have no baseline; run --update')
        return 1
    if improvements:
        print(f'PASS with {len(improvements)} improvement(s) '
              f'(rerun with --update to lock in):')
        for metric, base, cur in improvements:
            print(f'  {metric}: {base} -> {cur}')
    else:
        print('PASS: all metrics at or above baseline')
    return 0


if __name__ == '__main__':
    sys.exit(main())
