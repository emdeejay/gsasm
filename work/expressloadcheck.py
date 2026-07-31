#!/usr/bin/env python3
"""work/expressloadcheck.py — System 6.0.1 single-segment ExpressLoad files.

E1: three shipping ExpressLoad'd files whose flat code image was already
byte-exact but whose ~ExpressLoad wrapper / reloc dictionary differed.  Each is
a plain single-object (or two-object) link, ExpressLoad'd, compared byte-for-
byte against the golden fork on its shipping disk:

  * Start        Disk 1 (Install)       /System/Start
                 A.U.G/CtlPanel/SetStartCDEV/Startup.Aii ; -o SetStart ->
                 the ~ExpressLoad directory LOADNAME is "SetStart" (the
                 pre-rename link name), carried via expressload(loadfile_name=).
  * QuickLogoff  Disk 4 (SystemTools2)  /AppleTalk/QuickLogoff
                 GS.OS/NetBoot/QuickLogoff/Quick.aii ; a ZERO-relocation
                 segment -> the HET reloc pointer is NULL (reloc_start = 0).
  * Tool038      Disk 4 (SystemTools2)  /System/Tools/Tool038  (MediaCtlTool)
                 GSToolbox/MediaCtlTool/{MediaCtrlMgr,dialogdata}.asm ; the
                 per-message length words `EndMsg-Msg` are same-segment label
                 DIFFERENCES (net-zero relocation weight) and take no reloc.

The three expressload.py rules these pin (loadfile_name LOADNAME, null reloc
pointer, net-zero reloc weight) also have a corpus-free guard in
tests/test_expressload_reloc_weight.py.

RESIDUAL (not gated here): ATResponder (Disk 4 /System/System.Setup/ATResponder)
— code image byte-exact, but the assembler treats `EQU *`-defined labels
(`RegCompl equ *-3`, `ATPDone equ *-3`) as absolute rather than segment-
relative, so references like `sta RegCompl+2` MISS 8 SUPER type-0 relocs that
gold emits ([217,220,226,229,396,399,405,408]).  An assembler-level (asm.py)
fix, out of the ExpressLoad wrapper scope.

Prints:
    EXPRESSLOAD_SYS601_BYTES_EXACT good/total
where good = summed bytes of files that are byte-identical to gold, total =
summed gold length of all attempted files.
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from _common import (                                    # noqa: E402
    ensure_repo_on_path, toolbox_root, firmware_root, toolbox_incs,
    gsos_source_root, gsos_incs)
ensure_repo_on_path()

import diskcheck as dc                                   # noqa: E402  (a2til locator)
from a2til.prodos import Volume                          # noqa: E402
from gsasm import asm, omf                               # noqa: E402
from gsasm.expressload import expressload                # noqa: E402

_TB = toolbox_root(abs_path=True)
_FW = firmware_root(abs_path=True)
_SRC = gsos_source_root(abs_path=True)
_TINCS = toolbox_incs(_TB, _FW)
_GINCS = gsos_incs(src=_SRC)


def _one(src, incs, opts=None):
    a = asm.assemble(src, incs)
    if a.errors:
        raise RuntimeError(f'{src}: {len(a.errors)} asm errors; '
                           f'first: {a.errors[0]}')
    return expressload([(omf.emit(a), a)], opts=opts)


def build_start():
    sd = os.path.join(_SRC, 'A.U.G', 'CtlPanel', 'SetStartCDEV')
    return _one(os.path.join(sd, 'Startup.Aii'), [sd] + _TINCS,
                opts={'loadfile_name': 'SetStart'})


def build_quicklogoff():
    ql = os.path.join(_SRC, 'GS.OS', 'NetBoot', 'QuickLogoff')
    return _one(os.path.join(ql, 'Quick.aii'), [ql] + _GINCS)


def build_atresponder():
    # ATResponder (Disk 4 /System/System.Setup) — single-object ExpressLoad file,
    # byte-exact whole-file (code image + wrapper + reloc dict). GS.OS SetupFile.
    ar = os.path.join(_SRC, 'GS.OS', 'SetupFiles', 'ATResponder')
    return _one(os.path.join(ar, 'ATResponder.aii'), [ar] + _GINCS)


def build_net_start():
    # AppleTalk net-boot Start (Disk 4 /AppleTalk/Start) — 4-object ExpressLoad
    # file per GS.OS/MakeFiles/make.net.start (the authoritative rule: StartLog,
    # NOT the superseded NetBoot/Start/Makefile's BootLog16), link order
    # Start.o StartLog.o Console.o DES.o. Byte-exact whole-file after the
    # grouped-import/export, DC.L *, and WITH-precedence fixes.
    nb = os.path.join(_SRC, 'GS.OS', 'NetBoot')
    objs = []
    for rel, incdirs in [('Start/Start.aii', ['Console']),
                         ('Start/StartLog.aii', ['Console', 'Logon']),
                         ('Console/console.aii', ['Console']),
                         ('Logon/des.aii', [])]:
        sub = os.path.join(nb, os.path.dirname(rel))
        incs = [os.path.join(nb, d) for d in incdirs] + [sub] + _GINCS
        a = asm.assemble(os.path.join(nb, rel), incs)
        objs.append((omf.emit(a), a))
    return expressload(objs)


def build_closeview_code():
    # CloseView (Disk 4 /System/System.Setup) — a TWO-load-segment ExpressLoad
    # app (CloseView.make: -lseg INIT Core+Patches+Data [KIND 0x4000] -lseg NDA
    # NDA [KIND 0], -t $B6). Builds the de_express'd CODE image (INIT ++ NDA):
    # each lseg links merged with the OTHER lseg's symbol table as externs at
    # LinkIIGS's link-time bases — load segment N sits at bank N (segnum<<16):
    # INIT (seg #2 after ~ExpressLoad) at $020000, NDA (#3) at $030000 — so
    # cross-lseg refs store the link-time absolute the gold image carries.
    from gsasm import linkiigs
    import drivercheck as _dc
    cv = os.path.join(_SRC, 'A.U.G', 'CloseView')
    objs = {}
    for n in ('Core.aii', 'Patches.aii', 'Data.aii', 'NDA.aii'):
        a = asm.assemble(os.path.join(cv, n), [cv] + _dc.INCS)
        if a.errors:
            raise RuntimeError(f'{n}: {len(a.errors)} asm errors; '
                               f'first: {a.errors[0]}')
        objs[n] = (omf.emit(a), a)
    init_objs = [objs['Core.aii'], objs['Patches.aii'], objs['Data.aii']]
    nda_objs = [objs['NDA.aii']]

    def symtab(ol, base):
        placed, bases, pidx = linkiigs._place(list(ol), base)
        sym, _ = linkiigs._build_symtab(list(ol), placed, bases, pidx)
        return sym

    init = _dc._extract_img(linkiigs.link(list(init_objs), opts={
        'merge': True, 'segname': b'INIT', 'kind': 0x4000,
        'extern': symtab(nda_objs, 0x030000)}))
    nda = _dc._extract_img(linkiigs.link(list(nda_objs), opts={
        'merge': True, 'segname': b'NDA', 'kind': 0x0000,
        'extern': symtab(init_objs, 0x020000)}))
    return bytes(init) + bytes(nda)


def build_atinit():
    # ATInit is NOT ExpressLoad — it is a flat MakeBin file (make.atinit:
    # linkiigs atinit.aii -t $E2 -at $0000 -o ATINIT ; makebiniigs ATINIT).
    # atinit.aii ALONE (the SetupFiles/ATInit MakeFile lists atstart.oii too,
    # but the shipping make.atinit rule links only atinit.oii). 134 B, $E2.
    from gsasm import makebin
    ai = os.path.join(_SRC, 'GS.OS', 'SetupFiles', 'ATInit')
    a = asm.assemble(os.path.join(ai, 'atinit.aii'), [ai] + _GINCS)
    if a.errors:
        raise RuntimeError(f'atinit.aii: {len(a.errors)} asm errors; '
                           f'first: {a.errors[0]}')
    return makebin.makebin(omf.emit(a), 0)


def build_tool038():
    mc = os.path.join(_TB, 'MediaCtlTool')
    objs = []
    for r in ('MediaCtrlMgr.asm', 'dialogdata.asm'):
        a = asm.assemble(os.path.join(mc, r), _TINCS)
        if a.errors:
            raise RuntimeError(f'{r}: {len(a.errors)} asm errors; '
                               f'first: {a.errors[0]}')
        objs.append((omf.emit(a), None))
    return expressload(objs)


# (label, disk basename, disk fork path, builder[, compare])
# compare 'whole' (default): built == the raw on-disk fork.
# compare 'code': built == de_express(fork) — the flat code image (CloseView's
# 2-lseg packaging reloc dicts are not modeled; the code is what's gated).
_TARGETS = [
    ('Start',       'Disk 1 of 7 Install.2mg',      'System/Start',      build_start),
    ('QuickLogoff', 'Disk 4 of 7 SystemTools2.2mg', 'AppleTalk/QuickLogoff', build_quicklogoff),
    ('Tool038',     'Disk 4 of 7 SystemTools2.2mg', 'System/Tools/Tool038',  build_tool038),
    ('ATInit',      'Disk 4 of 7 SystemTools2.2mg', 'System/System.Setup/ATInit', build_atinit),
    ('ATResponder', 'Disk 4 of 7 SystemTools2.2mg', 'System/System.Setup/ATResponder', build_atresponder),
    ('net-Start',   'Disk 4 of 7 SystemTools2.2mg', 'AppleTalk/Start', build_net_start),
    ('CloseView',   'Disk 4 of 7 SystemTools2.2mg', 'System/System.Setup/CloseView',
     build_closeview_code, 'code'),
]


def _golden(disk_basename, path):
    disk = os.path.join(dc.DISKS, disk_basename)
    vol = Volume(open(disk, 'rb').read())
    return vol.read_file(path)


def run():
    from gsasm.expressload import de_express
    good = total = 0
    for target in _TARGETS:
        label, disk, path, builder = target[:4]
        mode = target[4] if len(target) > 4 else 'whole'
        gold = _golden(disk, path)
        if mode == 'code':
            gold = de_express(bytes(gold))
        try:
            built = builder()
        except Exception as e:                            # pragma: no cover
            built = b''
            print(f'  {label:12} BUILD ERROR: {e}')
        total += len(gold)
        if built == gold:
            good += len(gold)
            print(f'  {label:12} PASS  {len(gold)}B  ({path})')
        else:
            print(f'  {label:12} FAIL  built={len(built)}B gold={len(gold)}B  ({path})')
    print(f'EXPRESSLOAD_SYS601_BYTES_EXACT {good}/{total}')
    return 0 if good == total else 1


if __name__ == '__main__':
    sys.exit(run())
