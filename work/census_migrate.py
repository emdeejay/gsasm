#!/usr/bin/env python3
"""census_migrate.py — migrates docs/disk_census_2026-07-30.json (FILE-granular,
prose `forks` string) into docs/disk_census_2026-08-01.json (FORK-granular,
structured `forks` dict), per docs/ADVERSARIAL_REVIEW_SOW_IMPLEMENTATION_2026-08-01.md
finding #3 and docs/IMPLEMENTATION_PLAN.md §1's `ForkKey = (path, 'data'|'rsrc')`.

    python3 work/census_migrate.py     # writes docs/disk_census_2026-08-01.json

WHY a script, not a hand edit: 355 files across 7 disks is too much to hand-
migrate without drift, and re-running it is how a future census update stays
honest (re-derive against LIVE disk state, never hand-patch counts).

--- What "fork-granular" means here -----------------------------------------

The v1 (2026-07-30) census has ONE record per file with a free-form `forks`
STRING (e.g. "data=built(...); rsrc=buildable-rez(...) not yet gated", or a
bare "data+rsrc" that says nothing about whether BOTH forks are equally
proven).  `work/manifestcheck.py` validated only path sets, never forks, so a
file could be globally `built` while one of its forks was merely carried
verbatim gold (adversarial-review finding #3 — the Disk 7 NetBoot targets are
the clearest example: the DATA fork is disk7check-proven, the RESOURCE fork
is Mac-Rez output nobody has built).

v2 (2026-08-01) replaces the `forks` STRING with a `forks` DICT keyed by the
forks the LIVE disk image actually has (`live_forks_for_disk()` below — the
ProDOS extended-storage-type bit / the HFS catalog's own data+rsrc length
fields, NOT the prose), each value a per-fork record:

    {"classification": <same vocabulary as the old file-level classification>,
     "proven_by": <harness name, if classification == "built">,
     "source_path": <optional>,
     "size": <live fork length in bytes, ground truth>,
     "evidence": <fork-specific evidence, freshly written for this migration>}

--- Losslessness -------------------------------------------------------------

Every file record's ORIGINAL `forks` STRING is preserved verbatim in a new
`forks_raw_v1` field (the exact prose the string-typed field held before this
migration retyped it to a dict).  Every other v1 field (classification,
proven_by, source_path, evidence, language, confidence) is copied UNCHANGED
at the file level — v2 does not edit v1's file-level summary, it only ADDS
the fork-granular `forks` dict alongside it.  docs/disk_census_2026-07-30.json
itself is untouched (not deleted, not edited) — it remains the historical
record; v2 is a strict superset migration.

--- Where this migration DISAGREES with the v1 per-file summary -------------

`OVERRIDES` below hand-encodes every file where a per-fork split needed
DELIBERATE judgment rather than a mechanical default — either because the v1
`proven_by` harness demonstrably does not cover one of the two forks (verified
by reading the harness's own target list / gate.py metric name, not guessed),
or because the fork's true byte-length forced a choice the v1 file-level
classification blurred (e.g. a CDEV's data fork is 0 bytes: cdevcheck proves
its resource fork; the empty data fork has no proof and is not the same
claim).  Every OVERRIDES entry's evidence field explains the reasoning and
cites what was checked.  See docs/ADVERSARIAL_REVIEW... and the B_REPORT.md
this script's invocation produced for the full audit trail.

The DEFAULT (non-overridden) path is deliberately conservative: for a
2-fork file whose v1 classification/proven_by is the SAME claim for both
forks (verified: no size-based asymmetry — see `default_split()`), both forks
inherit the v1 classification/proven_by/evidence UNCHANGED.  For the
`built` + "one fork is 0 bytes" shape, the 0-byte fork demotes to
`no-source-substitute` (nothing to build, no claim made) rather than
inheriting `built` from the other fork.  Any OTHER 2-fork, both-nonzero,
`built`/`pascal-c-nontarget` file with NO OVERRIDES entry makes this script
raise `AssertionError` rather than guess — every such file in the v1 census
as of 2026-08-01 has one.

--- C1: TECHNICAL_EXCEPTION human-acceptance field (finding #4) -------------

`_entry()` accepts an optional `accepted` dict (`{"by", "date", "rationale"}`)
that, if given, is carried onto the fork record verbatim as `"accepted"`.
Nothing in this script passes it today.  As of 2026-08-01 there are ZERO
TECHNICAL_EXCEPTION records left: the two Tool.Setup forks (Disks 1 + 2) —
the exceptions this field was added for — were CRACKED to BUILT the same day
(see the Tool.Setup OVERRIDES entry below), so
`manifest_technical_exceptions_accepted` reports good=0 bad=0.  The field
and the blocking semantics remain for any future exception; this script
still never fabricates an acceptance.

--- C2: structured substitute/exception search evidence (finding #5) -------

docs/substitute_search_evidence_2026-08-01.json (see the sidecar's own
extraction notes) holds, for 195 of the v1 census's SUBSTITUTE/
TECHNICAL_EXCEPTION file records, the prose `evidence` string's content
re-expressed as structured fields: `{searched_trees, search_date,
search_patterns, decision}` (all nullable — the sidecar was built under a
strict extract-never-invent rule, so a field with no anchor in the original
prose stays `null` rather than being guessed).  This migration folds that
sidecar in: after a file's forks are split (OVERRIDES or `default_split()`),
every resulting fork whose classification is SUBSTITUTE/TECHNICAL_EXCEPTION
(`_CENSUS_STATE` in work/diskmanifest.py — no-source-substitute,
pascal-c-nontarget, or technical-exception) AND whose (disk, path) has a
sidecar record gets a `"search"` object (`{searched_trees, search_date,
search_patterns, decision}`, copied verbatim including any nulls).  A fork
with no matching sidecar record — e.g. one of the per-fork splits above whose
evidence was newly WRITTEN during this migration (OVERRIDES), which the v1
file-granular sidecar extraction could not have seen — gets no `"search"`
key at all; it is not backfilled or guessed.  This is deliberately a MATCH,
not a guarantee: `search.decision` can still be null for a matched record
(the sidecar's `search_date` is null for every one of its 195 records — no
prose anchored a date), and `manifest_substitutes_structured` in
work/manifestcheck.py only counts a fork "good" when `search.decision` is
non-null.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import ROOT, ensure_repo_on_path  # noqa: E402
ensure_repo_on_path()

OLD_CENSUS = os.path.join(ROOT, 'docs', 'disk_census_2026-07-30.json')
NEW_CENSUS = os.path.join(ROOT, 'docs', 'disk_census_2026-08-01.json')
SIDECAR_SEARCH_EVIDENCE = os.path.join(
    ROOT, 'docs', 'substitute_search_evidence_2026-08-01.json')


# ---------------------------------------------------------------------------
# Live fork enumeration — ground truth for fork PRESENCE + SIZE, independent
# of the census prose.  ProDOS: a plain (non-extended) file has ONLY a data
# fork (no rsrc key block exists at all); an extended-storage-type file has
# both, even if one is 0 bytes.  HFS: every catalog file record carries BOTH
# filDLgLen/filRLgLen fields structurally, so both forks always "exist" (0 is
# a real length, not absence) — see work/hfs.py.
# ---------------------------------------------------------------------------
def live_forks_for_disk(disk_label):
    """{path: {'data': size} | {'data': size, 'rsrc': size}}."""
    import diskcheck as dc
    if disk_label.startswith('Disk 7'):
        import hfs
        v = hfs.HFS(path=os.path.join(dc.DISKS, disk_label))
        out = {}
        for (parID, name), (lg, _ext, _ft) in v.files.items():
            rlg, _rext = v.rforks.get((parID, name), (0, []))
            rel = v.path(parID)
            full = '/' + (rel + '/' + name if rel else name)
            out[full] = {'data': lg, 'rsrc': rlg}
        return out
    from a2til.prodos import Volume
    vol = Volume(open(os.path.join(dc.DISKS, disk_label), 'rb').read())
    out = {}
    for p, e in dc._walk(vol, '/' + vol.name):
        f = dc.DiskFile(p, e, vol)
        out[p] = {'data': f.data_eof}
        if f.has_rsrc:
            out[p]['rsrc'] = f.rsrc_eof
    return out


# ---------------------------------------------------------------------------
# `proven_by` normalization — fixes purely COSMETIC v1 drift ('.py' suffixes,
# a couple of parenthetical annotations) that would otherwise fail B1's
# structural harness-name validation for no reason.  Anything that names a
# genuinely WRONG or AMBIGUOUS harness (ControlPanel's "toolcheck(objsel L1)",
# the "appdatacheck + rezforkcheck" combo, "probootcheck" which has no
# gate.py CHECKS entry of its own) is handled in OVERRIDES instead, with the
# verified correct harness cited.
# ---------------------------------------------------------------------------
_PROVEN_BY_ALIASES = {
    'probootcheck': 'diskcheck',   # probootcheck.py has no gate.py CHECKS entry
                                    # of its own; it is exercised ONLY as
                                    # diskcheck._build_prodos's lazy import, so
                                    # 'diskcheck' (disk_logical_exact) is the
                                    # harness that actually gates this fork.
    'cdevcheck.py': 'cdevcheck',
    'drivercheck.py': 'drivercheck',
    'fstcheck.py': 'fstcheck',
    'appdatacheck.py': 'appdatacheck',
    'toolcheck.py': 'toolcheck',
    'basiccheck.py': 'basiccheck',
    'findercheck.py': 'findercheck',
    'rezforkcheck(rsrc-only)': 'rezforkcheck',
    'rezforkcheck.py (rsrc fork only)': 'rezforkcheck',
}


def _normalize_proven_by(pb):
    if not pb:
        return None
    return _PROVEN_BY_ALIASES.get(pb, pb)


def _entry(classification, proven_by=None, evidence='', source_path=None,
           accepted=None):
    d = {'classification': classification, 'evidence': evidence}
    if proven_by:
        d['proven_by'] = proven_by
    if source_path:
        d['source_path'] = source_path
    if accepted:
        # C1 (finding #4): optional human-acceptance marker for a
        # TECHNICAL_EXCEPTION fork -- {"by", "date", "rationale"}. Nothing in
        # this script passes it today; see the module docstring's C1 section.
        d['accepted'] = accepted
    return d


# ---------------------------------------------------------------------------
# C2 (finding #5): fold docs/substitute_search_evidence_2026-08-01.json's
# structured {searched_trees, search_date, search_patterns, decision} fields
# onto every SUBSTITUTE/TECHNICAL_EXCEPTION fork whose (disk, path) the
# sidecar covers. See the module docstring's C2 section for the matching
# rule and what is deliberately left unmatched.
# ---------------------------------------------------------------------------
def _substitute_tech_classes():
    """Census classification strings that map to SUBSTITUTE or
    TECHNICAL_EXCEPTION in work/diskmanifest.py's `_CENSUS_STATE` --
    IMPORTED, not duplicated (same B1 discipline as `_harness_metrics_map`)."""
    import diskmanifest as dm
    return {cc for cc, state in dm._CENSUS_STATE.items()
            if state in (dm.SUBSTITUTE, dm.TECHNICAL_EXCEPTION)}


def _load_sidecar_search():
    """{(disk, path): sidecar record} from the C2 evidence sidecar."""
    if not os.path.exists(SIDECAR_SEARCH_EVIDENCE):
        return {}
    with open(SIDECAR_SEARCH_EVIDENCE) as fh:
        data = json.load(fh)
    return {(r['disk'], r['path']): r for r in data['records']}


def _apply_search_evidence(disk_label, path, forkdict, sidecar, subtech_classes):
    rec = sidecar.get((disk_label, path))
    if rec is None:
        return
    for fork_name, sub in forkdict.items():
        if sub.get('classification') not in subtech_classes:
            continue
        sub['search'] = {
            'searched_trees': rec['searched_trees'],
            'search_date': rec['search_date'],
            'search_patterns': rec['search_patterns'],
            'decision': rec['decision'],
        }


def default_split(f, live_sizes):
    """The non-overridden path. See module docstring for the rule."""
    cls = f['classification']
    pb = _normalize_proven_by(f.get('proven_by'))
    ev = f.get('evidence', '')
    sp = f.get('source_path')
    forks = sorted(live_sizes)          # ['data'] or ['data', 'rsrc']
    if len(forks) == 1:
        return {forks[0]: _entry(cls, pb, ev, sp)}

    d_sz, r_sz = live_sizes['data'], live_sizes['rsrc']
    if cls == 'built' and d_sz == 0 and r_sz > 0:
        return {
            'rsrc': _entry('built', pb, ev, sp),
            'data': _entry(
                'no-source-substitute', None,
                '0-byte data fork (structural — this file type carries its '
                'real content only in the resource fork; the file-level '
                'evidence above proves the RESOURCE fork, not this one).'),
        }
    if cls == 'built' and r_sz == 0 and d_sz > 0:
        return {
            'data': _entry('built', pb, ev, sp),
            'rsrc': _entry(
                'no-source-substitute', None,
                '0-byte resource fork (structural; no content here).'),
        }
    # Both forks present and (for built/pascal-c-nontarget) either agree in
    # size-shape or the file's classification is not a byte-exactness claim
    # at all (no-source-substitute / technical-exception) — safe to replicate
    # the SAME v1 claim onto both forks verbatim.
    if len(forks) == 2 and d_sz > 0 and r_sz > 0 and cls in ('built', 'pascal-c-nontarget'):
        raise AssertionError(
            f'default_split: {f["path"]!r} is a dual-nonzero-fork {cls!r} '
            'record with no OVERRIDES entry -- this shape needs a deliberate '
            'per-fork classification (see census_migrate.py OVERRIDES), not a '
            'guess. Add an OVERRIDES entry.')
    return {'data': _entry(cls, pb, ev, sp), 'rsrc': _entry(cls, pb, ev, sp)}


# ---------------------------------------------------------------------------
# OVERRIDES — every (disk_label, path) whose per-fork split needed a
# deliberate, individually-verified judgment call.  See B_REPORT.md for the
# full audit trail (what was checked, byte counts, harness target lists).
# ---------------------------------------------------------------------------
OVERRIDES = {}


def _add(disk, path, data=None, rsrc=None):
    d = {}
    if data is not None:
        d['data'] = data
    if rsrc is not None:
        d['rsrc'] = rsrc
    OVERRIDES[(disk, path)] = d


D1 = 'Disk 1 of 7 Install.2mg'
D2 = 'Disk 2 of 7 System Disk.2mg'
D3 = 'Disk 3 of 7 SystemTools1.2mg'
D4 = 'Disk 4 of 7 SystemTools2.2mg'
D5 = 'Disk 5 of 7 Fonts.2mg'
D6 = 'Disk 6 of 7 synthLAB.2mg'
D7 = 'Disk 7 of 7 Apple II Setup.2mg'

# --- ControlPanel NDA (Disk 1 + Disk 2 copies; verified byte-identical, cmp) -
# v1 proven_by "toolcheck(objsel L1)" matches NO work/toolcheck.py TOOLMAP
# entry (TOOLMAP only builds Tool0NN toolset files). The real DATA-fork
# builder is work/appdatacheck.py's APPMAP['ControlPanel'] (A.U.G/CtlPanel/
# CtlPanelNDA, 2-object flat link + ExpressLoad kind=0x1000; "Byte-exact
# 15110/15110" per appdatacheck.py's own comment). The RESOURCE fork is
# cdevcheck's _build_cdev('ControlPanel') (wired directly for Disk 2 via
# diskcheck.REZ_BUILDERS). Verified Disk-1 vs Disk-2 copies byte-identical
# (both forks, cmp) before reusing the same proof for both disk paths.
_CTLPANEL_DATA_EV = (
    'DATA fork (15110B, the NDA 65816 code) proven byte-exact by '
    'work/appdatacheck.py APPMAP["ControlPanel"] (A.U.G/CtlPanel/CtlPanelNDA, '
    'two-object flat link CtlPanel.aii+cbp.aii, ExpressLoad kind=0x1000; gate '
    'metric app_data_bytes_exact). v1 proven_by ("toolcheck(objsel L1)") did '
    'not correspond to any work/toolcheck.py TOOLMAP entry -- corrected after '
    'reading appdatacheck.py\'s APPMAP and independently cmp-verifying the '
    'Disk-1/Disk-2 copies are byte-identical (15110/15110).')
_CTLPANEL_RSRC_EV = (
    'RESOURCE fork (1238B) proven byte-exact by work/cdevcheck.py '
    '(_build_cdev("ControlPanel"), CDEV_RSRC_BYTES_EXACT); wired directly in '
    'diskcheck.REZ_BUILDERS for the Disk-2 path (a real CallableProof).')
_add(D1, '/Install/System/Desk.Accs/ControlPanel',
     data=_entry('built', 'appdatacheck', _CTLPANEL_DATA_EV),
     rsrc=_entry('built', 'cdevcheck', _CTLPANEL_RSRC_EV))
_add(D2, '/System.Disk/System/Desk.Accs/ControlPanel',
     data=_entry('built', 'appdatacheck',
                 _CTLPANEL_DATA_EV + ' Disk-2 copy verified cmp-identical to '
                 'the Disk-1 copy appdatacheck actually builds (15110/15110). '
                 'v1 proven_by ("diskcheck") overclaimed: ControlPanel is '
                 'REZ_BUILDERS-owned only in diskcheck -- its data fork is '
                 'carried verbatim by diskcheck.check(), not independently '
                 'checked, so disk_logical_exact does not cover it.'),
     rsrc=_entry('built', 'cdevcheck', _CTLPANEL_RSRC_EV))

# --- Installer (Disk 1): two DIFFERENT harnesses, not one ------------------
_add(D1, '/Install/Installer',
     data=_entry('built', 'installerdatacheck',
                 'DATA fork (56163B) proven byte-exact by '
                 'work/installerdatacheck.py (INSTALLER_DATA_BYTES_EXACT '
                 '56163/56163).'),
     rsrc=_entry('built', 'installercheck',
                 'RESOURCE fork (17895B) proven byte-exact by '
                 'work/installercheck.py (INSTALLER_RSRC_BYTES_EXACT), a '
                 'DIFFERENT harness/gate metric than the data fork. v1 '
                 'proven_by ("installerdatacheck") named only the data-fork '
                 'harness for both forks.'))

# --- Finder (Disk 3 SystemTools1 copy): findercheck (rsrc) vs finderdatacheck
# (data) are separate gate.py entries with separate metrics.
_add(D3, '/SystemTools1/System/Finder',
     data=_entry('built', 'finderdatacheck',
                 'DATA fork (146924B) proven byte-exact by '
                 'work/finderdatacheck.py (FINDER_DATA_BYTES_EXACT, both '
                 'golden copies 293848/293848 total).'),
     rsrc=_entry('built', 'findercheck',
                 'RESOURCE fork (52395B) proven byte-exact by '
                 'work/findercheck.py (FINDER_RSRC_BYTES_EXACT, both golden '
                 'copies). v1 proven_by ("findercheck.py") named only the '
                 'resource-fork harness for both forks.'))

# --- Pascal-wall NDAs/apps whose RESOURCE fork is independently rez-built --
# The v1 FILE-level classification (pascal-c-nontarget) undercounted these:
# their resource fork genuinely IS built+gated, only the Pascal data/code
# fork is the (correctly classified) non-target wall.
_add(D3, '/SystemTools1/System/Desk.Accs/FindFile',
     data=_entry('no-source-substitute', None,
                 'DATA/code fork core is FindFileDA.p (Pascal) -- outside '
                 'the asm/rez target; carried verbatim (pascal-c-nontarget '
                 'wall).'),
     rsrc=_entry('built', 'rezforkcheck',
                 'RESOURCE fork (1852B) proven byte-exact by '
                 'work/rezforkcheck.py from ToolBoxMisc/FindFileGS/'
                 'Findfile.rez (REZFORK_BYTES_EXACT). v1 proven_by '
                 '("rezforkcheck.py (rsrc fork only)") was already scoped to '
                 'rsrc; the FILE-level classification (pascal-c-nontarget) '
                 'undercounted this genuinely-built fork.'))
_add(D3, '/SystemTools1/Adv.Disk.Util',
     data=_entry('no-source-substitute', None,
                 'Application code fork is Pascal (A.U.G/ADU has 11 .pii + 2 '
                 '.aii + 1 adu.rii); outside the asm/rez target '
                 '(pascal-c-nontarget wall).'),
     rsrc=_entry('buildable-rez', None,
                 'Resource fork buildable from adu.rii (Rez) but not yet '
                 'wired into any gate harness -- TODO_BUILDABLE, not proven.',
                 source_path='ref/GSOS_6/IIGS.601.SRC/A.U.G/ADU/adu.rii'))
_add(D4, '/SystemTools2/System/Desk.Accs/MediaControl',
     data=_entry('no-source-substitute', None,
                 'DATA/code fork built from Pascal (MediaCtlNDA.pii + '
                 'MediaCtlUNIT.pii); non-target (pascal-c-nontarget wall).'),
     rsrc=_entry('built', 'rezforkcheck',
                 'RESOURCE fork (670B) proven byte-exact by '
                 'work/rezforkcheck.py (MediaControl -> MediaCtlNDA.rii, '
                 'REZFORK_BYTES_EXACT). v1 left proven_by null despite '
                 'naming rezforkcheck in the prose evidence.'))
_add(D4, '/SystemTools2/System/Desk.Accs/VideoMix',
     data=_entry('no-source-substitute', None,
                 'DATA/code fork is Pascal (PokeyNDA.Pii + PokeyUnit.Pii); '
                 'non-target (pascal-c-nontarget wall).'),
     rsrc=_entry('built', 'rezforkcheck',
                 'RESOURCE fork (625B) proven byte-exact by '
                 'work/rezforkcheck.py (VideoMix -> VideoMixNDA.rii, '
                 'REZFORK_BYTES_EXACT). v1 left proven_by null despite '
                 'naming rezforkcheck in the prose evidence.'))
_add(D4, '/SystemTools2/Teach',
     data=_entry('no-source-substitute', None,
                 'DATA/code fork built from Pascal (uMenu.p, uWindow.p, '
                 'uUtils.p, uGlobals.p, ...); non-target (pascal-c-nontarget '
                 'wall).'),
     rsrc=_entry('built', 'teachcheck',
                 'RESOURCE fork (7333B) proven byte-exact by '
                 'work/teachcheck.py (TEACH_RSRC_BYTES_EXACT). v1 left '
                 'proven_by null despite naming teachcheck in the prose '
                 'evidence.'))
_add(D5, '/Fonts/Goodies/Apple.Bowl',
     data=_entry('no-source-substitute', None,
                 'DATA fork (application) built by IntBasicIIGS, a custom '
                 'BASIC->OMF compiler written in Pascal (Compiler/Basic.p '
                 'etc); non-target (pascal-c-nontarget wall).'),
     rsrc=_entry('built', 'rezforkcheck',
                 'RESOURCE fork (863B) proven byte-exact by '
                 'work/rezforkcheck.py REZMAP["Apple.Bowl"] (Bowl.r, '
                 'REZFORK_BYTES_EXACT). v1 proven_by '
                 '("rezforkcheck(rsrc-only)") normalized.'))

# --- Pioneer4200 (Disk 4): v1 proven_by was the combo string
# "appdatacheck + rezforkcheck" -- split per fork, each a real HarnessProof.
_add(D4, '/SystemTools2/System/Drivers/Media.Control/Pioneer4200',
     data=_entry('built', 'appdatacheck',
                 'DATA fork (6253B) proven byte-exact by work/appdatacheck.py '
                 '(APP_DATA_BYTES_EXACT). v1 proven_by was the combo string '
                 '"appdatacheck + rezforkcheck"; split per fork here.'),
     rsrc=_entry('built', 'rezforkcheck',
                 'RESOURCE fork (505B) proven byte-exact by '
                 'work/rezforkcheck.py (REZFORK_BYTES_EXACT). v1 proven_by '
                 'was the combo string "appdatacheck + rezforkcheck"; split '
                 'per fork here.'))

# --- EasyMount (Disk 4 copy; the Disk 2 copy is wired -- CallableProof wins
# automatically via diskmanifest._wired_builders, no override needed there).
_add(D4, '/SystemTools2/System/System.Setup/EasyMount',
     data=_entry('built', 'easymountcheck',
                 'DATA fork (9221B) proven byte-exact by '
                 'work/easymountcheck.py (rez_easymount_data_bytes_exact).'),
     rsrc=_entry('built', 'easymountcheck',
                 'RESOURCE fork (2500B) proven byte-exact by '
                 'work/easymountcheck.py (rez_easymount_rsrc_bytes_exact).'))

# --- Read.Me / Shortcuts / Whats.New (Disk 4) + Fonts Read.Me (Disk 5):
# rezdatacheck proves ONLY the resource fork (a TE-record + style-block pair).
# The literal text DATA fork is shipped verbatim from a tracked source file
# (makefile Duplicate rule); the missing 1:1 byte comparison — an honest GAP
# in B_REPORT.md until 2026-08-01 — is now wired as work/textdatacheck.py
# (gate metric text_data_bytes_exact, 30520/30520), so both forks are built.
def _readme_pair(rsrc_size, src_hint, text_src):
    return (
        _entry('built', 'textdatacheck',
               f'DATA fork is the literal TeachText text, shipped verbatim '
               f'from the tracked source {text_src} (makefile Duplicate '
               f'rule); proven byte-exact by work/textdatacheck.py '
               f'(TEXT_DATA_BYTES_EXACT — the comparison the B_REPORT gap '
               f'list flagged as missing, wired 2026-08-01; independently '
               f'byte-verified by both dated-search backfill agents the '
               f'same day).',
               source_path=f'ref/GSOS_6/IIGS.601.SRC/{text_src}'),
        _entry('built', 'rezdatacheck',
               f'RESOURCE fork ({rsrc_size}B, TE record + style block) proven '
               f'byte-exact by work/rezdatacheck.py ({src_hint}, '
               f'REZ_DATA_BYTES_EXACT). v1 proven_by ("rezdatacheck") was '
               f'also stamped on the data fork, which rezdatacheck does not '
               f'build.'))

_rm_data, _rm_rsrc = _readme_pair(602, 'Read.Me',
                                   'ToolBoxMisc/ReadMeFiles/Read.Me.text')
_add(D4, '/SystemTools2/Read.Me', data=_rm_data, rsrc=_rm_rsrc)
_sc_data, _sc_rsrc = _readme_pair(3950, 'Shortcuts',
                                   'ToolBoxMisc/ReadMeFiles/Shortcuts.text')
_add(D4, '/SystemTools2/Shortcuts', data=_sc_data, rsrc=_sc_rsrc)
_wn_data, _wn_rsrc = _readme_pair(696, 'Whats.New',
                                   'ToolBoxMisc/ReadMeFiles/Whats.New.text')
_add(D4, '/SystemTools2/Whats.New', data=_wn_data, rsrc=_wn_rsrc)
_fr_data, _fr_rsrc = _readme_pair(628, 'Fonts.Read.Me',
                                   'A.U.G/Apple.Bowl/Read.Me.txt')
_add(D5, '/Fonts/Goodies/Read.Me', data=_fr_data, rsrc=_fr_rsrc)

# --- EasyMount + Start (Disk 2 copies): both forks of both files are
# directly wired CallableProofs (diskcheck.SOURCE_BUILDERS + REZ_BUILDERS for
# '/System.Disk/...' paths) -- diskmanifest._wired_builders() supersedes
# whatever HarnessProof the census names at generation time, so the
# HarnessProof recorded here (matching the v1 'diskcheck' claim) is really
# just a documented fallback/lossless-carry; it is never the proof actually
# used once a CallableProof exists for that (path, fork).
_add(D2, '/System.Disk/System/System.Setup/EasyMount',
     data=_entry('built', 'diskcheck',
                 'Wired directly: diskcheck.SOURCE_BUILDERS['
                 '"/System.Disk/System/System.Setup/EasyMount"] = '
                 '_build_easymount_data (a real CallableProof; supersedes '
                 'this HarnessProof at generation time).'),
     rsrc=_entry('built', 'diskcheck',
                 'Wired directly: diskcheck.REZ_BUILDERS['
                 '"/System.Disk/System/System.Setup/EasyMount"] = '
                 '_build_easymount_rsrc (a real CallableProof; supersedes '
                 'this HarnessProof at generation time).'))
_add(D2, '/System.Disk/System/Start',
     data=_entry('built', 'diskcheck',
                 'Wired directly: diskcheck.SOURCE_BUILDERS['
                 '"/System.Disk/System/Start"] = _build_finder_data (a real '
                 'CallableProof; supersedes this HarnessProof at generation '
                 'time).'),
     rsrc=_entry('built', 'diskcheck',
                 'Wired directly: diskcheck.REZ_BUILDERS['
                 '"/System.Disk/System/Start"] = _build_finder_rsrc (a real '
                 'CallableProof; supersedes this HarnessProof at generation '
                 'time).'))

# --- ProDOS (Disk 1): v1 proven_by "probootcheck" has no gate.py CHECKS
# entry of its own (see _PROVEN_BY_ALIASES) -- but since ProDOS is a
# single-fork file the alias table already fixes this; no OVERRIDES entry
# needed. (Comment retained so the ProDOS fix isn't lost in the noise.)

# ===========================================================================
# Disk 7 (HFS Apple II Setup) -- B3: the six disk7check DATA-fork targets stay
# BUILT (HarnessProof('disk7check', ['disk7_bytes_exact'])); their live
# RESOURCE forks are represented explicitly per B3's rule: TODO_BUILDABLE if
# the census records a buildable source, ELSE SUBSTITUTE with the census
# evidence. Three of the six (Apple //e Boot Blocks, ProDOS16 Boot Blocks,
# ProDOS16 Image) have a terse "buildable-rez(...)" forks-field label BUT
# their fuller v1 evidence text explicitly says the resource fork is
# "same later-revision/no-source class ... carried verbatim" (a VERIFIED
# negative, not merely unattempted) -- SUBSTITUTE wins over the terse label
# for those three. See B_REPORT.md for this call spelled out per-file.
# ===========================================================================
_D7_DATA_EV = 'DATA fork proven byte-exact by work/disk7check.py (DISK7_BYTES_EXACT).'


def _d7_data():
    return _entry('built', 'disk7check', _D7_DATA_EV)


_add(D7, '/System Folder/Basic.System',
     data=_d7_data(),
     rsrc=_entry('no-source-substitute', None,
                 'RECLASSIFIED 2026-08-01 (was buildable-rez): the live fork '
                 'is a MAC resource fork (header dataOff=0x100, single Mac '
                 "'vers' resource, 416B) -- same container class as the "
                 'boot-block rsrc forks. Basic.r (NetBoot/Installer/) is a '
                 'MAC Rez source for the Mac Installer support set; gsrez '
                 'emits IIgs-format forks, so the container format can never '
                 'byte-match. Carried verbatim.',
                 source_path='ref/GSOS_6/IIGS.601.SRC/GS.OS/NetBoot/Installer/Basic.r'))
_add(D7, '/IWEm',
     data=_d7_data(),
     rsrc=_entry('no-source-substitute', None,
                 'rsrc=312B (small vers/finder info); v1 evidence records no '
                 'buildable source for this fork specifically (unlike the '
                 'other five, no .r file is cited) -- carried verbatim.'))
_add(D7, '/System Folder/p8',
     data=_d7_data(),
     rsrc=_entry('no-source-substitute', None,
                 'RECLASSIFIED 2026-08-01 (was buildable-rez): the live fork '
                 'is a MAC resource fork (header dataOff=0x100, single Mac '
                 "'vers' resource, 409B) -- same container class as the "
                 'boot-block rsrc forks. P8.r (NetBoot/Installer/) is a MAC '
                 'Rez source for the Mac Installer support set; gsrez emits '
                 'IIgs-format forks, so the container format can never '
                 'byte-match. Carried verbatim.',
                 source_path='ref/GSOS_6/IIGS.601.SRC/GS.OS/NetBoot/Installer/P8.r'))
_add(D7, '/System Folder/Apple //e Boot Blocks',
     data=_d7_data(),
     rsrc=_entry('no-source-substitute', None,
                 'rsrc=423B (Mac \'vers\' via Bullwinkle.r). v1\'s own file-'
                 'level evidence explicitly calls this fork "same later-'
                 'revision/no-source class as ProDOS16 Boot Blocks; carried '
                 'verbatim" -- a VERIFIED negative, so SUBSTITUTE (not the '
                 'terse forks-field "buildable-rez" label) wins here.',
                 source_path='ref/GSOS_6/IIGS.601.SRC/GS.OS/NetBoot/Installer/Bullwinkle.r'))
_add(D7, '/System Folder/ProDOS16 Boot Blocks',
     data=_d7_data(),
     rsrc=_entry('no-source-substitute', None,
                 'rsrc=426B, Mac \'vers\' resources. v1\'s file-level evidence: '
                 '"verified-no-source: built by Mac Rez from a LATER revision '
                 'of Installer/BootBlocks.r (shipped strings differ from the '
                 'archived source) and its resource map carries build-machine '
                 'heap-garbage handle fields; carried verbatim." A verified '
                 'negative, not merely unattempted -- SUBSTITUTE.',
                 source_path='ref/GSOS_6/IIGS.601.SRC/GS.OS/NetBoot/Installer/BootBlocks.r'))
_add(D7, '/System Folder/ProDOS16 Image',
     data=_d7_data(),
     rsrc=_entry('no-source-substitute', None,
                 'rsrc=420B. v1\'s file-level evidence: "same later-revision/'
                 'no-source class as the boot blocks; carried verbatim." A '
                 'verified negative -- SUBSTITUTE.',
                 source_path='ref/GSOS_6/IIGS.601.SRC/GS.OS/NetBoot/Installer/Image.r'))

# --- Apple II Script (Disk 7): CONTRADICTION RESOLVED 2026-08-01 (was the B3
# "documented tension": v1's census said verified-no-source, the plan's build
# catalog listed it among the buildable text-rez files). Settled by direct
# artifact evidence, three independent axes:
#   (1) the golden 6421-byte rsrc fork parses as a MAC resource fork (header
#       dataOff=0x100/mapOff=0x16bd, self-consistent) whose type list is the
#       Mac Installer 3.x script set: inpk/infr/inrl/infs x10/infa x5/incd
#       (+PICT/vers) -- NOT an IIgs resource fork;
#   (2) the source (Apple2GSInstallerScript.r, which DOES exist) says in its
#       own header comment it is a script for "Installer 3.0.1" -- the Mac
#       68k /Installer shipped on this same HFS disk;
#   (3) its #includes 'Types.r' + 'InstallerTypes.r' are Mac system/Installer
#       templates, absent from every ref tree (re-verified by find).
# Even WITH the templates, gsrez emits IIgs-format resource forks -- the
# container format itself could never byte-match. Same family as the three
# Mac-Rez boot-block rsrc forks above. The plan's catalog entry was the
# error (fixed same day: text-rez 5->4, buildable 58->57);
# docs/IMPLEMENTATION_PLAN.md Section 3 now records the removal.
_add(D7, '/Apple II Script',
     data=_entry('no-source-substitute', None,
                 'data=0B; no data-fork content or claim (the payload is '
                 'entirely the resource fork).'),
     rsrc=_entry('no-source-substitute', None,
                 'VERIFIED 2026-08-01 (contradiction resolved in favor of '
                 'v1): golden fork is a MAC resource fork (header 0x100, '
                 'Mac Installer 3.x script types inpk/infr/inrl/infs/infa/'
                 'incd + PICT/vers) built by Mac Rez from '
                 'Apple2GSInstallerScript.r ("installer script ... for '
                 'Installer 3.0.1" per its own header) for the Mac 68k '
                 'Installer on this disk; #include Types.r/InstallerTypes.r '
                 'are Mac templates absent from all ref trees, and gsrez '
                 'emits IIgs-format forks so the container format can never '
                 'match. Carried verbatim. (The IMPLEMENTATION_PLAN Section-3 '
                 '"text-rez" catalog entry was the stale claim; removed '
                 '2026-08-01.)',
                 source_path='ref/GSOS_6/IIGS.601.SRC/GS.OS/NetBoot/Installer/Apple2GSInstallerScript.r'))

# --- Tool.Setup (Disks 1 + 2): the project's LAST TECHNICAL_EXCEPTION x2 —
# CRACKED 2026-08-01 (SOW P7). The "case-B wall" label was STALE: the E2
# multiseg-dictionary work (2026-07-19) had already closed the reloc-encoding
# gap, and the residual reported by work/archive/toolsetup_probe.py was that
# probe's own recipe drift vs GSToolbox/Patch/Setup/makefile (no
# `-d RAMVersion=0` on tl.asm; CDAMenu/NDACalls double-pulls merged; filter-
# list order instead of _part's natural-order rule). Transcribed verbatim
# through the proven TS2/TS3 machinery
# (work/diskbuilders/toolsets.py::_build_toolsetup), the build is BYTE-EXACT:
# 19232/19232 (~ExpressLoad 228 + main 1460 + patches 17544, incl. reloc
# dictionaries). Disk-1 vs Disk-2 copies cmp-verified byte-identical (19232B
# both) before reusing the proof for both disk paths (the P2 duplicate rule).
_TOOLSETUP_EV = (
    'DATA fork (19232B, the toolset-patch bundle ExpressLoad file) proven '
    'byte-exact by work/diskbuilders/toolsets.py::_build_toolsetup — the '
    'GSToolbox/Patch/Setup/makefile linkiigs section (-lseg:$3000 main + '
    '-lseg patches, tl.asm -d RAMVersion=0, CDAMenu/NDACalls two-pull '
    'references) through the TS2/TS3 _whole/_part/_expressload_groups '
    'machinery. Was TECHNICAL_EXCEPTION ("case-B wall") until 2026-08-01; '
    'the wall was stale post-E2 (see toolsets.py Tool.Setup section header). ')
_add(D1, '/Install/System/System.Setup/Tool.Setup',
     data=_entry('built', 'diskcheck',
                 _TOOLSETUP_EV +
                 'Disk-1 copy cmp-verified byte-identical to the Disk-2 copy '
                 'that diskcheck gates (build_and_overlay logical-exact, '
                 'disk_logical_exact).',
                 source_path='ref/GSOS_6/IIGS.601.SRC/GSToolbox/Patch/Setup/makefile'))
_add(D2, '/System.Disk/System/System.Setup/Tool.Setup',
     data=_entry('built', 'diskcheck',
                 _TOOLSETUP_EV +
                 'Wired as a diskcheck SOURCE_BUILDER (CallableProof) via '
                 'diskbuilders auto-discovery; overlaid + logical-exact in '
                 'the Disk-2 pass.',
                 source_path='ref/GSOS_6/IIGS.601.SRC/GSToolbox/Patch/Setup/makefile'))

# --- IWEM (Disk 4 driver): CRACKED 2026-08-01. v1's VERIFY-NEGATIVE
# ("diverges after 78 bytes ... the matching IWEm.Src version is not
# present") was WRONG: that comparison was against the tree's PREBUILT
# `IWEm` artifact (28523B — the stripped variant that also ships as Disk 7's
# /IWEm), not against a replay of the checked-in MPW BuildIWEm script. The
# shipped 29185B file = prebuilt[:78] + a 662-byte version-guard/ExitServer
# block + prebuilt[78:], and that block sits UNCOMMENTED in IWEm.Src.
# Replaying BuildIWEm's squeeze pipeline (work/iwemcheck.py) reproduces the
# shipped file byte-exact 29185/29185 first try. Gate metric
# iwem_bytes_exact.
_add(D4, '/SystemTools2/System/Drivers/IWEM',
     data=_entry('built', 'iwemcheck',
                 'DATA fork (29185B ASCII PostScript, the ImageWriter '
                 'Emulator proc set) proven byte-exact by work/iwemcheck.py: '
                 'a verbatim Python replay of the MPW BuildIWEm (Ver 1.5) '
                 'text-squeeze script over IWEm.Src, incl. the ExitServer/'
                 'version-guard block the earlier verify-negative missed '
                 '(it had compared against the prebuilt stripped artifact '
                 'instead of replaying the script). Gate metric '
                 'iwem_bytes_exact 29185/29185.',
                 source_path='ref/GSOS_6/IIGS.601.SRC/GSToolbox/PrinterDrivers/IWEm/IWEm.Src'))


def migrate_file(disk_label, f, live_sizes):
    key = (disk_label, f['path'])
    if key in OVERRIDES:
        forkdict = OVERRIDES[key]
        # sanity: an override must cover exactly the forks the live disk has
        if set(forkdict) != set(live_sizes):
            raise AssertionError(
                f'{disk_label} {f["path"]!r}: OVERRIDES covers forks '
                f'{sorted(forkdict)} but the live disk has {sorted(live_sizes)}')
        return forkdict
    return default_split(f, live_sizes)


def migrate():
    with open(OLD_CENSUS) as fh:
        old = json.load(fh)
    new = json.loads(json.dumps(old))   # deep copy; we mutate `files` in place
    used_overrides = set()
    sidecar = _load_sidecar_search()
    subtech_classes = _substitute_tech_classes()
    for disk_label, disk in new['disks'].items():
        live = live_forks_for_disk(disk_label)
        census_paths = set()
        for f in disk['files']:
            path = f['path']
            census_paths.add(path)
            if path not in live:
                raise AssertionError(
                    f'{disk_label}: census path {path!r} not found in LIVE '
                    f'disk enumeration -- census/disk drift.')
            raw_forks = f.get('forks')
            forkdict = migrate_file(disk_label, f, live[path])
            if (disk_label, path) in OVERRIDES:
                used_overrides.add((disk_label, path))
            for fork_name, sub in forkdict.items():
                sub.setdefault('size', live[path][fork_name])
            _apply_search_evidence(disk_label, path, forkdict, sidecar,
                                    subtech_classes)
            f['forks_raw_v1'] = raw_forks
            f['forks'] = forkdict
        missing_live = set(live) - census_paths
        if missing_live:
            raise AssertionError(
                f'{disk_label}: live paths missing from census: '
                f'{sorted(missing_live)[:10]}')
    unused = set(OVERRIDES) - used_overrides
    if unused:
        raise AssertionError(f'OVERRIDES entries never matched a census '
                              f'record (stale): {sorted(unused)}')
    new['_migrated_from'] = os.path.basename(OLD_CENSUS)
    new['_migration_script'] = 'work/census_migrate.py'
    new['_migration_note'] = (
        'Fork-granular migration of the file-granular v1 census (B2, '
        'docs/ADVERSARIAL_REVIEW_SOW_IMPLEMENTATION_2026-08-01.md finding #3). '
        'Every file-level field is preserved verbatim from v1 (including the '
        'original `forks` prose string, now under `forks_raw_v1`); the new '
        '`forks` field is a {fork: {classification, proven_by?, source_path?, '
        'size, evidence, search?, accepted?}} dict, one entry per fork the '
        'LIVE disk actually has. `search` (finding #5, C2) is folded in from '
        'docs/substitute_search_evidence_2026-08-01.json for every SUBSTITUTE/'
        'TECHNICAL_EXCEPTION fork whose (disk, path) that sidecar covers; '
        '`accepted` (finding #4, C1) is a human-acceptance marker for a '
        'TECHNICAL_EXCEPTION fork that this script never fabricates (zero '
        'TECHNICAL_EXCEPTION records remain as of 2026-08-01 — Tool.Setup '
        'x2 cracked to built). '
        'See work/census_migrate.py for the full migration rationale and '
        'per-file OVERRIDES audit trail.')
    with open(NEW_CENSUS, 'w') as fh:
        json.dump(new, fh, indent=2, sort_keys=False)
        fh.write('\n')
    print(f'wrote {NEW_CENSUS}')
    return new


if __name__ == '__main__':
    migrate()
