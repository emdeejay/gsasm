#!/usr/bin/env python3
"""rezloadcheck.py — M7/R6: build the four Sys.Resources .Load files and prove
the RezIIgs `read ... Convert` transformation.

Builds the four embedded code resources of Sys.Resources from the pristine
archive sources (ref/GSOS_6/IIGS.601.SRC/GSToolbox/Sys.Resources — CR line
endings, MacRoman; NOT the LF/UTF-8 working copies in work/txt) with gsasm,
reproducing the makefile recipes:

    asmiigs IconButton.aii -unsafe -wi ; LinkIIGS -x ... -o IconButton.Load
    asmiigs Thermodial.aii -unsafe -wi ; LinkIIGS -x ... -o Thermodial.Load
    asmiigs FrameControl.aii           ; LinkIIGS -x ... -o FrameControl.Load
    Asmiigs Launcher.aii -o Launcher.Obj
    LinkIIGS -x -t $BC -o Launcher.Load -lseg:code:nospecial:static Launcher Launcher.obj

then applies gsasm/rez/convert.py's convert_load() and byte-compares each
result against the golden embedded resource extracted via work/rezcheck.py:

    rCtlDefProc   ($800C) 0x07FF0001  2649 B  IconButton
    rCtlDefProc   ($800C) 0x07FF0002  1313 B  Thermodial
    rCtlDefProc   ($800C) 0x07FF0003   633 B  FrameControl
    rCodeResource ($8017) 0x07FF0001  4899 B  Launcher

STATUS: 4/4 byte-exact.

FINDINGS (the R6 deliverable — each verified against the golden bytes):

1. Convert is the IDENTITY.  Each golden resource is a complete, standalone
   OMF v2 load file (header BYTECNT == resource size, body, relocation
   dictionary, END).  RezIIgs `read ... Convert` embeds the .Load file's
   bytes verbatim; the Convert attribute bit (0x0800) is a Resource Manager
   *runtime* hint (relocate on LoadResource), not a build-time transform.
   Hence gsasm/rez/convert.py::convert_load(b) == b.

2. LinkIIgs -x load-file relocation dictionary (differs from the
   ExpressLoad-converted tools gsasm/expressload.py models):
     - order: standalone RELOC records (sorted by patch offset) first, then
       SUPER records in ascending type order;
     - SUPER types: 0 = (size 2, shift 0), 1 = (size 3/4, shift 0), and
       **26** = (size 2, shift 16) — NOT type 27, which is what the
       ExpressLoad converter uses for the same (2,16) class in ToolNNN files;
     - a relocation whose evaluated target exceeds 24 bits goes standalone:
       Dialog.aii pushes `#VersionFilter+$80000000` (ModalDialog filterProc
       convention), whose target 0x80000FD8 cannot ride in a SUPER page list,
       so LinkIIgs emits two explicit RELOC records (offsets 2628/2631,
       relOffset 0x80000FD8) for the pushlong pair and drops those two sites
       from the SUPER lists.  This also explains the 0x80000000/0xc0000000
       "case-B FLAG" of docs/design/expressload.md — it is the SOURCE
       expression's addend, not opaque LinkIIgs state.
     - header: SEGNAME defaults to 'main' with an all-zero LOADNAME; an
       explicit `-lseg:code:nospecial:static Launcher` names the output
       segment 'Launcher' and sets KIND = 0x1000 (type code=0x00 |
       no-special-memory=0x1000; static = dynamic bit 0x8000 clear).  KIND
       otherwise defaults from the first input segment (0x4000 private for
       Thermodial, whose first PROC is unexported).  `-t $BC` only sets the
       output FILE's ProDOS type — no load-file bytes.

3. Dialect gaps found in the corpus — originally shimmed HARNESS-LOCALLY
   here (R6's file mandate did not include gsasm/asm.py / m65816.py); ALL
   FOUR are now promoted into the core assembler (packet R8), so this
   harness carries no shims of its own any more:
     - TSA/TAS: 65816 alias mnemonics for TSC/TCS (Thermodial.aii:802,805)
       — gsasm/m65816.py's ALIAS table.
     - ENDFUNC: alias for ENDF, closing a FUNC block (FrameControl.aii:442)
       — gsasm/asm.py's FUNC/ENDF dispatch.
     - &LEN(&arg) counts the argument's RAW text when the argument is a
       substituted variable/expression (quotes included), but a literal
       quoted string written directly counts its CONTENT: Launcher.mac's
       wstr macro emits `dc.w &len(&str)-2`, and the golden words for
       'P8'/'PRODOS' are 2/6 == len(raw &str)-2, while Console.aii's
       `dcb.b 31-&len('CONSOLE'),' '` pads to exactly 31 chars, needing
       len('CONSOLE')==7 (content only) — gsasm/asm.py's call_builtin('LEN').
     - Nested-record fields: `Ctl RECORD` containing `Rect ds Rectangle`
       must define doubly-qualified fields (Ctl.Rect.y2 = Ctl.Rect +
       Rectangle.y2 = 12) as plain offset EQUATEs (not relocatable labels),
       so IconButton's 14 `[<CtlPtr],y` index loads resolve without a
       spurious relocation — gsasm/asm.py's DS handling now qualifies a
       nested typed-DS field by its enclosing template (recursing to
       arbitrary depth) instead of exploding only one level.

Usage:
    python3 work/rezloadcheck.py            # build, convert, compare; exit 1 on any FAIL

Artifacts: work/link/rez/{IconButton,Thermodial,FrameControl,Launcher}.Load
(gitignored via work/link/).
"""
import importlib.util
import os
import sys

from _common import (
    ROOT as REPO,
    WORK as HERE,
    ensure_repo_on_path,
    first_diff as _first_diff,
    work_abs,
)
ensure_repo_on_path(HERE)

from gsasm import asm as _asm            # noqa: E402
from gsasm import omf as _omf            # noqa: E402
from gsasm import link as _link          # noqa: E402
from gsasm import linkiigs as _lig       # noqa: E402
from gsasm import expressload as _exl    # noqa: E402
import rezcheck as _rez                  # noqa: E402

# gsasm/rez/{__init__,lexer,emit}.py belong to other R-packets and may be
# mid-flight; load convert.py directly by path so this harness never depends
# on the package's import surface.
_conv_spec = importlib.util.spec_from_file_location(
    'gsasm_rez_convert', os.path.join(REPO, 'gsasm', 'rez', 'convert.py'))
_conv_mod = importlib.util.module_from_spec(_conv_spec)
_conv_spec.loader.exec_module(_conv_mod)
convert_load = _conv_mod.convert_load

SRC = os.path.join(REPO, 'ref', 'GSOS_6', 'IIGS.601.SRC', 'GSToolbox',
                   'Sys.Resources')
INCS = [SRC, work_abs('includes')]
OUTDIR = os.path.join(HERE, 'link', 'rez')

# (source, .Load artifact, res type, res id, output SEGNAME, KIND override)
# KIND None = default from the first input segment (matches LinkIIgs -x).
# Launcher: -lseg:code:nospecial:static Launcher -> SEGNAME 'Launcher',
# KIND 0x1000 (code | no-special-memory; static).
TARGETS = [
    ('IconButton.aii',   'IconButton.Load',   0x800C, 0x07FF0001, b'main',     None),
    ('Thermodial.aii',   'Thermodial.Load',   0x800C, 0x07FF0002, b'main',     None),
    ('FrameControl.aii', 'FrameControl.Load', 0x800C, 0x07FF0003, b'main',     None),
    ('Launcher.aii',     'Launcher.Load',     0x8017, 0x07FF0001, b'Launcher', 0x1000),
]


def assemble(name):
    """Assemble one source; returns the Asm.  (Was two dialect-shim passes —
    see FINDINGS #3 in the module docstring — until packet R8 promoted all
    four gaps into gsasm/asm.py / m65816.py; this is now a plain assemble.)"""
    path = os.path.join(SRC, name)
    return _asm.assemble(path, INCS)


# ---------------------------------------------------------------------------
# LinkIIgs -x load-file linking (FINDINGS #2).
# ---------------------------------------------------------------------------

# (size, shift) -> SUPER type in a plain LinkIIgs -x load file.  NOTE type 26
# for the (2,16) high-word class — the ExpressLoad converter re-encodes the
# same class as type 27 in ToolNNN files (gsasm/expressload.py's table).
_SUPER_TYPE = {(2, 0): 0, (3, 0): 1, (4, 0): 1, (2, 16): 26}


def _scan_reloc_dictionary(placed, sym, abs_syms):
    """Classify every symbol-bearing EXPR-family record into the -x load
    file's relocation dictionary.

    Returns ``(supers, standalone)`` where supers = {super_type: [offsets]}
    and standalone = sorted [(offset, size, shift, target)] for relocations
    whose 32-bit target cannot ride in a SUPER page list (> 24 bits, e.g.
    ``#VersionFilter+$80000000``) or whose (size, shift) has no SUPER type.
    Shift expressions over only link-time constants (GEQUs) resolve at link
    time and get no relocation (mirrors _defer_shifts' const_only rule).
    """
    supers, standalone = {}, []
    for _sn, recs, seg_base, _h, _a in placed:
        off = 0
        for _at, nm, d in recs:
            if nm == 'END':
                break
            if nm in ('CONST', 'LCONST'):
                off += len(d)
            elif nm == 'DS':
                off += d
            elif nm == 'RELEXPR':
                off += d[0]
            elif nm in ('EXPR', 'LEXPR', 'BEXPR'):
                size, ops = d
                if _exl._has_sym_ref(ops):
                    syms = [o[1] for o in ops if isinstance(o, tuple)
                            and str(o[0]).startswith('sym')]
                    shift = _exl._get_shift(ops)
                    ops_wo = ops
                    if (shift and len(ops) >= 4 and ops[-1] == 'end'
                            and ops[-2] == ('op', 7)
                            and isinstance(ops[-3], tuple)
                            and ops[-3][0] == 'lit'):
                        ops_wo = ops[:-3] + ['end']
                    const_only = bool(syms) and all(s in abs_syms for s in syms)
                    if not const_only:
                        site = seg_base + off
                        sym['__LOC__'] = site
                        target = _link._eval(ops_wo, sym) & 0xFFFFFFFF
                        if target > 0xFFFFFF:
                            standalone.append((site, size, shift, target))
                        else:
                            stype = _SUPER_TYPE.get((size, shift))
                            if stype is not None:
                                supers.setdefault(stype, []).append(site)
                            else:
                                standalone.append((site, size, shift, target))
                off += size
    standalone.sort()
    return supers, standalone


def link_load(obj, a, segname, kind=None):
    """Link one assembled object into a plain (-x) OMF load file."""
    objects = [(obj, a)]
    placed, bases, pidx = _lig._place(objects, 0)
    sym, obj_globals = _lig._build_symtab(objects, placed, bases, pidx, {})
    abs_syms = frozenset(d['label'] for _s, recs, _b, _h, _a in placed
                         for _at, nm, d in recs
                         if nm == 'GEQU' and isinstance(d, dict))
    bodies = []
    for i, (_sn, recs, seg_base, _h, _a) in enumerate(placed):
        recs2 = _lig._defer_shifts(recs, abs_syms)[0]
        oi = pidx[i]
        local = sym if not obj_globals[oi] else {**sym, **obj_globals[oi]}
        bodies.append(_link._build_body(recs2, local, seg_base))
    body = _lig._merge_bodies(placed, bodies)

    supers, standalone = _scan_reloc_dictionary(placed, dict(sym), abs_syms)
    tail = b''.join(_exl.emit_reloc(sz, sh, off, rel)
                    for off, sz, sh, rel in standalone)
    for stype in sorted(supers):
        if supers[stype]:
            tail += _exl.emit_super(stype, sorted(supers[stype]))

    out_kind = kind if kind is not None else placed[0][3]['KIND']
    return _link._make_segment(segname, b'\x00' * 10, 0, out_kind, 1, body,
                               tail_recs=tail)


# ---------------------------------------------------------------------------
# Main: build + convert + compare
# ---------------------------------------------------------------------------

def main():
    os.makedirs(OUTDIR, exist_ok=True)

    sysres = next(p for p in _rez.REZ_FILES if p.endswith('Sys.Resources'))
    fork = _rez.golden_fork(sysres)

    ok = True
    n_pass = 0
    for srcname, loadname, rtype, rid, segname, kind in TARGETS:
        golden = fork.resource(rtype, rid)
        if golden is None:
            print('FAIL %-18s golden resource (%#06x, %#010x) missing'
                  % (loadname, rtype, rid))
            ok = False
            continue
        try:
            a = assemble(srcname)
        except Exception as e:                                # noqa: BLE001
            print('FAIL %-18s assemble raised %s: %s'
                  % (loadname, type(e).__name__, e))
            ok = False
            continue
        if a.errors:
            print('FAIL %-18s %d assembly errors; first: %s'
                  % (loadname, len(a.errors), a.errors[0]))
            ok = False
            continue
        load = link_load(_omf.emit(a), a, segname, kind)
        with open(os.path.join(OUTDIR, loadname), 'wb') as fh:
            fh.write(load)

        built = convert_load(load)
        d = _first_diff(built, golden)
        if d is None:
            n_pass += 1
            print('PASS %-18s %5d bytes byte-exact'
                  % (loadname, len(golden)))
        else:
            ok = False
            print('FAIL %-18s built=%dB golden=%dB first diff @%d'
                  % (loadname, len(built), len(golden), d))
            print('     built  %s' % built[max(0, d - 8):d + 12].hex())
            print('     golden %s' % golden[max(0, d - 8):d + 12].hex())

    print('%s rezloadcheck: %d/%d embedded code resources byte-exact'
          % ('PASS' if ok else 'FAIL', n_pass, len(TARGETS)))
    return ok


if __name__ == '__main__':
    sys.exit(0 if main() else 1)
