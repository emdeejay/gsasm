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


# (label, disk basename, disk fork path, builder)
_TARGETS = [
    ('Start',       'Disk 1 of 7 Install.2mg',      'System/Start',      build_start),
    ('QuickLogoff', 'Disk 4 of 7 SystemTools2.2mg', 'AppleTalk/QuickLogoff', build_quicklogoff),
    ('Tool038',     'Disk 4 of 7 SystemTools2.2mg', 'System/Tools/Tool038',  build_tool038),
]


def _golden(disk_basename, path):
    disk = os.path.join(dc.DISKS, disk_basename)
    vol = Volume(open(disk, 'rb').read())
    return vol.read_file(path)


def run():
    good = total = 0
    for label, disk, path, builder in _TARGETS:
        gold = _golden(disk, path)
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
