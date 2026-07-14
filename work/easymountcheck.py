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

    DATA FORK (2026-07-15, R11): byte-exact, 9221/9221.  Two precisely
    diagnosed residuals -- one in gsasm/asm.py, one in gsasm/expressload.py
    -- fixed at their root cause (both were mis-SCOPING bugs, not the
    "nearest-def tie-break" / "wrong reloc value" symptoms they first
    looked like):

      (a) `Asm.expand_macro()`'s @-label scope restore, not
          `Asm.resolve()`'s nearest-by-distance tie-break, was the actual
          bug. `@done` was defined TWICE under the SAME `_symkey` scope
          key ("SFTOOLNUMBER@DONE", offsets 1666 and 1708) because
          `GetStandardFile`/`KillStandardFile` are declared via the MPW
          `&lab NAME` macro idiom (`NAME`'s whole body is just `&lab` --
          a bare label-only line that re-emits the call-site label to
          define it as a REAL, @-scope-resetting global, exactly as if
          written directly with no macro at all). Since `NAME` has a
          `label_var`, `dispatch()` never calls `define_label` at the
          call site itself -- the label is defined INSIDE the macro body
          -- and `expand_macro()` unconditionally restored
          `self.last_global` to its pre-call value once the body
          finished (a guard meant to sandbox a macro's PRIVATE
          `local_ctx` @-labels), silently discarding that definition's
          effect on @-scope. Two NAME-declared routines back-to-back
          sharing an @-label name then fell back to whichever REAL
          (non-macro) label preceded them BOTH -- exactly reproduced by
          `GetStatus`/`TestUserVolume`'s `@retry`/`@loop`/`@match`/
          `@exit` colliding into a bogus "L2@..." scope the same way
          (offsets [5804,5921] etc.), confirming this is a general rule,
          not an ad hoc `@done`-only fix. Fix (asm.py, `expand_macro`):
          after the macro body runs, keep `last_global` as the body left
          it when it now equals the call site's OWN (non-`@`) label --
          i.e. only skip the restore in exactly that case -- else
          restore as before (protecting a macro's other, genuinely
          private internal labels; verified this moves NO other
          @-label's resolved value across the full bytecheck/
          kernelcheck/fstcheck/drivercheck/toolcheck corpus). With scope
          keys correctly disambiguated, every @-label in
          EasyMount.aii/DES.aii ends up with exactly ONE definition per
          key -- `Asm.resolve()`'s nearest-by-distance tie-break
          (asm.py ~line 601) is untouched and never even exercised for
          these cases. Fixture: tests/fixtures/030-name-macro-at-label-scope/.
      (b) `expressload.py`'s single-segment standalone-reloc scan
          (`_scan_standalone_relocs`/`_scan_case_b`) evaluated
          expressions against the plain multi-object-shared `sym` table
          instead of the per-object-merged table `_link._build_body`
          actually resolves each segment's body against.
          `linkiigs._build_symtab` deliberately keeps segment names
          object-PRIVATE in a multi-object link (a segment named
          `SHUTDOWN` in one object must not shadow another object's
          EXPORT of the same name) -- visible only via
          `obj_globals[obj_idx]`. DES.aii's own `DES` code segment
          addresses its own `DESDATA` data segment (the `lda #s1` /
          `lda #>s1` S-box table pointer pair, DES.aii source line 99)
          via exactly that object-private binding
          (`sym83('DESDATA') + lit(336)`), but the reloc scan evaluated
          it against bare `sym`, where `DESDATA` isn't a key -- 0 instead
          of DESDATA's real placed base 6193 (EasyMount.aii's own linked
          segment length, prepended before it) -- 6193 bytes short,
          matching the originally observed relOffset delta exactly.
          Separately, the `#s1` (low byte, shift=0) half of the pair was
          dropped from the dictionary entirely: the standalone-scan
          condition required a truthy `shift`, but a 1-byte field can't
          ride ANY SUPER page list regardless of shift (`_SUPER_TYPE` has
          no size-1 entry at all), so it needs a standalone record
          either way, same as the already-handled size-1/shift=16 and
          size-2/shift=8 cases. Fix: `expressload()` now keeps
          `body_syms[placed_i]` (the exact table each segment's body was
          resolved against) alongside `bodies[placed_i]`;
          `_scan_standalone_relocs`/`_scan_case_b` are evaluated
          per-segment against that table, and the standalone condition
          drops the `shift and` guard. The multi-segment
          (`multiseg=True`) ExpressLoad output path has NO analogous fix
          -- it never scans for standalone case-A/B records at all (a
          separate, larger gap; docs/TODO.md section 1).
          `work/toolsetup_probe.py`'s Tool.Setup output is byte-identical
          before and after this fix (confirmed) -- its residual is a
          different wall (reloc-record ENCODING: SUPER vs standalone
          cINTERSEG/cRELOC, not a placement-base error).

    Both fixes verified against the full gate (work/gate.py, at/above
    baseline with a NEW rez_easymount_data_bytes_exact: 9221 metric),
    tests/run_fixtures.py (30/30, including the new fixture above), and
    the rez/kernel/fst/driver/tool suites unchanged. Wired into
    work/diskcheck.py's SOURCE_BUILDERS (now producing a byte-exact
    overlay, not merely a tolerated non-exact build) -- disk_logical_exact
    improved 18->19/30 in the gate baseline as a result.

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
    builders in diskbuilders/expressload_files.py. Byte-exact as of R11
    (see module docstring for the two now-fixed root-cause bugs) -- returns
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
