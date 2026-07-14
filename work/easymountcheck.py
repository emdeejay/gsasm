#!/usr/bin/env python3
"""easymountcheck.py — M7 follow-on: reproduce the shipping EasyMount file.

EasyMount (`/System.Disk/System/System.Setup/EasyMount`) is the second Rez
milestone target (see docs/design/rez.md, "Target order"), and the FIRST
dual-fork target: unlike Sys.Resources (empty data fork), EasyMount carries
BOTH a real 65816 data fork (an ExpressLoad'd GS/OS S16-ish application,
assembled+linked from `EasyMount.aii` + `DES.aii`) and a 2500-byte resource
fork (`EasyMount.rii`).

    RESOURCE FORK: byte-exact.  Every resource type EasyMount.rii uses
    (rVersion, rComment, rIcon, rControlList, rControlTemplate, rPString,
    rTextForLETextBox2, rWindParam1) is already exercised by the golden
    Sys.Resources corpus gen.py was built against -- EasyMount needed two
    small, evidence-backed additions to gsasm/rez/gen.py (see its module
    docstring and tests/test_rez_gen.py for the byte evidence):
      1. `\\$HH` string escape (one byte, hex value HH) -- EasyMount's
         Cancel/Connect rControlTemplate KeyEquiv char pairs use it for
         real (`{"\\$1B","\\$1B",...}` / `{"\\$0D","\\$0D",...}`); the old
         generic backslash-drop fallback produced the wrong bytes.
      2. Nested ArrayField/SwitchField/GroupField partial-fill: when an
         `optional` group's resource value runs out of values AT one of
         these three field kinds (not just a plain TypedField), the field
         is entirely omitted, exactly like the already-known TypedField
         case -- confirmed against CTLTMP_00000008's `iconButtonControl`
         (unnamed `KeyEquiv` array macro omitted, 7 of 8 values supplied).
    No new resource TYPES, no read/Convert statements (EasyMount.rii has
    none), no synthesized rResName (no resource header supplies a "name").

    DATA FORK: NOT byte-exact -- 9214 built vs 9221 golden bytes, two
    precisely diagnosed residuals, BOTH inside gsasm/asm.py + gsasm/
    expressload.py/linkiigs.py (core assembler/linker files this packet's
    brief explicitly forbids editing -- "another concurrent task owns core
    asm/link/expressload files"). Reported here, not fixed:

      (a) ONE wrong byte in the 8223-byte code image (offset 0x688, a
          `beq @done` branch operand inside EasyMount.aii's single
          'EASYMOUNT' segment). `@done` is defined TWICE in the SAME
          `_symkey`-scope ("SFTOOLNUMBER", i.e. no intervening non-`@`
          label) -- offsets 1666 and 1708 -- and the reference at 1671
          sits BETWEEN them. Golden wants the FARTHER-FORWARD def (offset
          1708, branch +0x23); gsasm's `Asm.resolve()` nearest-by-distance
          policy (asm.py ~line 601) picks the CLOSER backward one (branch
          -7 = 0xf9). This looks fixable by "prefer nearest-forward, else
          nearest-backward" -- EXCEPT that same-file evidence contradicts
          it: `L2@RETRY`/`L2@LOOP` (offsets [5804,5921]/[5847,5963], same
          single-segment scope) are only correct under the EXISTING
          nearest-by-distance policy; forcing forward-preference for
          `@done` flips two THEN-wrong bytes there instead (verified by a
          scratch monkeypatch of Asm.resolve during this investigation,
          not kept). So this is a genuine, non-trivial `@`-label
          disambiguation gap -- not a one-line promotable fix -- left for
          whoever next touches asm.py's @-label scoping.
      (b) A 7-byte-shorter ExpressLoad relocation dictionary for the
          'main' segment (846 golden reloc-dict bytes vs 839 built).
          Golden carries two standalone cRELOC records for a `lda #s1` /
          `lda #>s1` pair (DES.aii's own `s1` S-box table label, DES.aii
          source line 99) at patch offsets 8207/8215 in the merged code
          image, both relOffset=6529; the built dictionary has only ONE
          (offset 8215, relOffset=336). 6529 - 336 == 6193 == exactly
          EasyMount.aii's own linked segment length -- i.e. the
          relocation target was computed relative to DES.aii's OWN
          `DESDATA` segment instead of the final merged 'main' segment's
          base, and the sibling `lda #s1` site was dropped from the
          dictionary entirely (presumably folded into an evaluated
          constant instead of flagged as needing relocation). This is a
          multi-segment-per-object placement/reloc-dictionary computation
          bug living in gsasm/expressload.py's `_scan_reloc_dictionary`-
          equivalent machinery (this file's own local copy, mirroring
          work/rezloadcheck.py's `_scan_reloc_dictionary`, does NOT
          reproduce it -- DES.aii's cross-segment DESDATA<-DES reference
          is a case this harness's local linking helper does not need to
          special-case because it delegates straight to
          gsasm.expressload.expressload(), so the bug is core, not
          harness-local).

    Given both residuals sit in files this packet may not edit, the data
    fork is reported PRECISELY (not silently substituted): still wired
    into work/diskcheck.py's SOURCE_BUILDERS (the existing
    build_and_overlay() contract already tolerates and reports a
    non-byte-exact build without corrupting the disk image -- see e.g.
    Tool015/Tool016/Tool018's ~JumpTable gaps in diskbuilders/
    expressload_files.py), so it counts honestly in the inventory instead
    of silently defaulting to SUBSTITUTE.

Inputs, none committed (Apple material, `ref/`/`work/rincludes/` gitignored):
  - `ref/GSOS_6/IIGS.601.SRC/A.U.G/Finder/EasyMount/{EasyMount.rii,
    EasyMount.aii,DES.aii,EasyMount.make}` -- the archive sources (CR line
    endings, MacRoman high bytes; never modified on disk).
  - `work/rincludes/AIIGSIncludes/{E16.Finder,E16.GSOS,E16.Locator,
    E16.QuickDraw,m16.debug}` -- 5 assembler-environment includes
    `EasyMount.aii`/`DES.aii` need that are NOT present anywhere in the
    `ref/GSOS_6/IIGS.601.SRC` archive snapshot (same situation TypesIIGS.r
    was in for the Rez side). Recovered the same way TypesIIGS.r was:
    extracted from `ref/gsrom3/system500.hfv`'s
    `MPW-GM:MPW:Interfaces:AIIGSIncludes:` folder (an HFS volume) via
    `hfsutils` (`brew install hfsutils`):
        hmount ref/gsrom3/system500.hfv
        hcopy ":MPW-GM:MPW:Interfaces:AIIGSIncludes:E16.Finder"   work/rincludes/AIIGSIncludes/E16.Finder
        hcopy ":MPW-GM:MPW:Interfaces:AIIGSIncludes:E16.GSOS"     work/rincludes/AIIGSIncludes/E16.GSOS
        hcopy ":MPW-GM:MPW:Interfaces:AIIGSIncludes:E16.Locator"  work/rincludes/AIIGSIncludes/E16.Locator
        hcopy ":MPW-GM:MPW:Interfaces:AIIGSIncludes:E16.QuickDraw" work/rincludes/AIIGSIncludes/E16.QuickDraw
        hcopy ":MPW-GM:MPW:Interfaces:AIIGSIncludes:m16.debug"    work/rincludes/AIIGSIncludes/m16.debug
        humount
    (hcopy translates CR->LF on data-fork text copies; gsasm's lexer/
    assembler treat CR/CRLF/LF line endings equivalently, so this does not
    affect assembly. Pure ASCII content -- no MacRoman high bytes to lose.)
  - Golden resource fork: `/System.Disk/System/System.Setup/EasyMount`,
    fork='rsrc' (2500 bytes, 25 resources, via work/rezcheck.py).
  - Golden data fork: same path, fork='data' (9221 bytes, via
    work/diskcheck.py's Volume).

Usage:
    python3 work/easymountcheck.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
for _p in (REPO, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from gsasm import asm, omf                          # noqa: E402
from gsasm.rez import parser, gen, emit              # noqa: E402
from gsasm.expressload import expressload, de_express  # noqa: E402
import rezcheck as rc                                 # noqa: E402
import rezemitcheck as rec                            # noqa: E402
import diskcheck as dc                                # noqa: E402
from a2til.prodos import Volume                       # noqa: E402

EM_SRC_DIR = os.path.join(REPO, 'ref', 'GSOS_6', 'IIGS.601.SRC', 'A.U.G',
                          'Finder', 'EasyMount')
FINDER_DIR = os.path.join(REPO, 'ref', 'GSOS_6', 'IIGS.601.SRC', 'A.U.G', 'Finder')
INC_E16 = os.path.join(REPO, 'work', 'rincludes', 'AIIGSIncludes')
RII_SRC = os.path.join(EM_SRC_DIR, 'EasyMount.rii')
INCS_REZ = [os.path.join(REPO, 'work', 'rincludes')]
ASM_INCS = [EM_SRC_DIR, FINDER_DIR, INC_E16]

EASYMOUNT_DISK_PATH = f'{rc.dc.V}/System/System.Setup/EasyMount'

# (source file, `-d` defines from EasyMount.make's `.aii.obj .aii` rule)
ASM_TARGETS = [
    ('EasyMount.aii', {'DebugSymbols': 0}),
    ('DES.aii', {'DebugSymbols': 0}),
]


# ---------------------------------------------------------------------------
# Resource fork
# ---------------------------------------------------------------------------
def _golden_rsrc():
    return rc.golden_fork(EASYMOUNT_DISK_PATH)


def build_easymount_rsrc_fork() -> bytes:
    """Build EasyMount's resource fork byte-exact via the library pipeline,
    using the golden fork's own recovered meta (name/filetype/creator/
    timestamp), exactly like rezbuildcheck.build_sysresources_fork(). No
    `read` statements and no "name" resource headers in EasyMount.rii, so
    `read_data={}` and there is no synthesized rResName entry."""
    stmts = parser.parse(RII_SRC, include_dirs=INCS_REZ,
                         predefined={'RezIIGS': 1})
    entries = gen.generate(stmts)
    tuples = gen.to_emit_tuples(entries, {})

    golden = _golden_rsrc()
    meta = rec._meta_from_golden(golden)
    return emit.emit_fork(tuples, meta)


# ---------------------------------------------------------------------------
# Data fork: assemble EasyMount.aii + DES.aii, link+ExpressLoad (no `-x` in
# the makefile's `linkiigs -t $B6 ...` -- the golden data fork's own bytes
# confirm it IS ExpressLoad'd: a leading '~ExpressLoad' directory segment,
# just like every other GS/OS System.Setup/Tools/FSTs/Drivers file
# diskbuilders/expressload_files.py already builds this way).
# ---------------------------------------------------------------------------
def build_easymount_data_fork() -> bytes:
    """Assemble+link+ExpressLoad EasyMount's data fork per EasyMount.make's
    recipe. Single (default) 'main' output segment -- the makefile has no
    `-lseg` directive, matching e.g. windmgr/printmgr's single-segment
    builders in diskbuilders/expressload_files.py. NOT byte-exact (see
    module docstring for the two precisely diagnosed residuals, both in
    core asm/expressload files this packet may not edit) -- returns
    whatever gsasm actually produces; callers compare against golden."""
    objects = []
    for name, defines in ASM_TARGETS:
        a = asm.assemble(os.path.join(EM_SRC_DIR, name), ASM_INCS,
                         defines=defines)
        if a.errors:
            raise RuntimeError(f'{name}: {len(a.errors)} assembly errors; '
                               f'first: {a.errors[0]}')
        objects.append((omf.emit(a), a))
    return expressload(objects)


def _golden_data():
    orig = open(dc.SYSTEM_DISK, 'rb').read()
    vol = Volume(bytearray(orig))
    return vol.read_file(EASYMOUNT_DISK_PATH, fork='data')


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------
def _first_diff(a, b):
    n = min(len(a), len(b))
    for i in range(n):
        if a[i] != b[i]:
            return i
    return None if len(a) == len(b) else n


def _check_rsrc():
    golden = _golden_rsrc()
    built = build_easymount_rsrc_fork()
    report = rc.compare(golden.raw, built)
    ok = report['ok'] and built == golden.raw
    print(f'{"PASS" if ok else "FAIL"} EasyMount resource fork: '
          f'built={len(built)}B golden={len(golden.raw)}B '
          f'header_diff={report["header_diff"]} memo_diff={report["memo_diff"]} '
          f'map_diff={report["map_diff"]} match={report["n_match"]}/'
          f'{report["n_resources"]} diff={report["n_diff"]} '
          f'missing={report["n_missing"]} extra={report["n_extra"]}')
    if not ok and built != golden.raw:
        d = _first_diff(built, golden.raw)
        print(f'    first raw byte diff at offset {d}: '
              f'golden={golden.raw[d:d+8].hex()} built={built[d:d+8].hex()}')
        for r in report['resources']:
            if r['status'] != 'match':
                print(f'    resource type={r["type"]:#06x} id={r["id"]:#x}: '
                      f'{r["status"]} golden_size={r["golden_size"]} '
                      f'built_size={r["built_size"]} first_diff={r["first_diff"]}')
    return ok


def _check_data():
    golden = _golden_data()
    built = build_easymount_data_fork()
    ok = built == golden
    print(f'{"PASS" if ok else "FAIL"} EasyMount data fork: '
          f'built={len(built)}B golden={len(golden)}B')
    if not ok:
        d = _first_diff(built, golden)
        print(f'    first raw byte diff at offset {d} '
              f'({"length differs, " if len(built) != len(golden) else ""}'
              f'built len {len(built)} vs golden len {len(golden)})')
        print(f'    golden {golden[max(0,d-8):d+24].hex()}')
        print(f'    built  {built[max(0,d-8):d+24].hex()}')
        g_code = de_express(golden)
        b_code = de_express(built)
        code_diffs = [i for i in range(min(len(g_code), len(b_code)))
                     if g_code[i] != b_code[i]]
        print(f'    de-ExpressLoad\'d code image: golden={len(g_code)}B '
              f'built={len(b_code)}B, {len(code_diffs)} differing byte(s) '
              f'at {[hex(i) for i in code_diffs[:10]]} -- see this module\'s '
              f'docstring for the diagnosed root causes (asm.py @-label '
              f'scoping + expressload.py cross-segment reloc base)')
    return ok


def main():
    rsrc_ok = _check_rsrc()
    print()
    data_ok = _check_data()
    print()
    ok = rsrc_ok and data_ok
    print(f'{"PASS" if ok else "FAIL"} easymountcheck: resource fork '
          f'{"byte-exact" if rsrc_ok else "NOT exact"}, data fork '
          f'{"byte-exact" if data_ok else "NOT exact (see above)"}')
    return ok


if __name__ == '__main__':
    sys.exit(0 if main() else 1)
