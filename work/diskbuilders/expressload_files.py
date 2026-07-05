"""diskbuilders/expressload_files.py — M8 ExpressLoad'd file builders.

Wires builders for every ExpressLoad'd tool, FST, and driver on the System Disk.
Each builder returns the FULL on-disk file bytes (the ExpressLoad'd OMF), NOT the
de-ExpressLoad'd code image the *check.py harnesses compare.

Recipe for each file:
    objects = [(omf.emit(asm.assemble(src, INCS)), asm_obj) for src in module_list]
    full_file = gsasm.expressload.expressload(objects, opts)

Module lists and INCS are taken directly from toolcheck.TOOLMAP/INCS,
fstcheck.FSTMAP/INCS, and drivercheck.DRIVERMAP/INCS — do NOT edit those files.

Multi-segment wiring (from makefile -lseg directives, confirmed byte-exact vs gold):

  Tool014 (windmgr): single-seg KIND=0x0000 — residual (missing cRELOC/RELOC records,
      code image identical to gold)

  Tool015 (menumgr): MainTool(KIND=0x0000, menumgr+wcm) + ~JumpTable(KIND=0x0002,
      MPW-generated, NOT reproduced) + PopUpProc(KIND=0x8000, popupproc).
      Residual: ~JumpTable gap prevents byte-exact match.

  Tool016 (controlmgr): main(KIND=0x0000, 6 objects) + StatText(KIND=0x0000,
      stattextproc; note: makefile has #-lseg:dynamic StatText, i.e. static)
      + ~JumpTable(KIND=0x0002, NOT reproduced) + Pics(KIND=0x8000, picproc).
      Residual: ~JumpTable gap prevents byte-exact match.

  Tool018 (qdaux): MAINPart(KIND=0x0000) + CopyBits(KIND=0x0000) + ~JumpTable
      (KIND=0x0002, NOT reproduced) + Pictures(KIND=0x8000) + SeedFill(KIND=0x8000)
      + PixelMap2Rgn(KIND=0x8000).  CopyBits uses LOADNAME-filtered copybits.asm.
      Residual: ~JumpTable gap.

  Tool019 (printmgr): single-seg KIND=0x0000, residual (1 code-image diff, symbol
      scoping bug: interior label 'PEA' target resolves differently)

  Tool023 (stdfile): single-seg KIND=0x4000 — residual (missing RELOC records +
      4 code-image diffs)

  Tool025 (notesynth): single-seg KIND=0x4000 — residual (4 code-image diffs,
      interior label 'UpDate' in SETUSERUPDATERTN shadows segment name 'UPDATE',
      linkiigs symbol scoping bug)

  Tool027 (fontmgr): single-seg KIND=0x0000 — residual (missing RELOC record +
      2 code-image diffs)

  Tool034 (textedit): single-seg KIND=0x0000 — residual (4444-byte code-image
      shortfall, assembler bug)
"""
import os
import sys

# Ensure gsasm is importable (diskcheck already prepends sys.path, but be safe)
_HERE = os.path.dirname(os.path.abspath(__file__))
_WORK = os.path.dirname(_HERE)
_REPO = os.path.dirname(_WORK)
for _p in (_REPO, _WORK):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from gsasm import asm, omf
from gsasm.expressload import expressload


# ---------------------------------------------------------------------------
# OMF filter helper — select segments by LOADNAME (for copybits.asm @SEGname)
# ---------------------------------------------------------------------------

def _filter_omf_by_loadname(obj_bytes: bytes, loadnames: 'set[bytes]') -> bytes:
    """Return a new OMF object containing only segments whose LOADNAME
    (stripped of trailing spaces/nulls) matches one of the given names.

    Used to split copybits.asm into its MAINPart and CopyBits load-segment
    contributions, exactly as MPW's -lseg <name> ... file(@SEGname) does.
    """
    out = bytearray()
    off = 0
    while off < len(obj_bytes):
        h = omf.parse_header(obj_bytes[off:])
        bc = h['BYTECNT']
        if bc == 0:
            break
        ln = h.get('LOADNAME', b'').rstrip(b'\x00 ')
        if ln in loadnames:
            out += obj_bytes[off:off + bc]
        off += bc
    return bytes(out)

# ---------------------------------------------------------------------------
# Source trees — mirrors exactly what toolcheck/fstcheck/drivercheck use
# ---------------------------------------------------------------------------
_SRC  = 'ref/GSOS_6/IIGS.601.SRC'
_TB   = _SRC + '/GSToolbox'
_FW   = _SRC + '/GSFirmware'
_GSOS = _SRC + '/GS.OS'
_CMN  = _GSOS + '/Common'

# Tool INCS (from toolcheck.INCS)
_TOOL_INCS = (
    [d for d, _, _ in os.walk(_TB)]
    + [d for d, _, _ in os.walk(_FW)]
    + ['work/includes']
)

# FST / Driver INCS (from fstcheck.INCS / drivercheck.INCS)
_GOS_INCS = (
    [_CMN]
    + [d for d, _, _ in os.walk(_GSOS)]
    + ['work/includes']
)


def _build_tool(subdir, srcs, defines=None):
    """Assemble srcs (relative to _TB/subdir), link, and expressload."""
    objects = []
    for r in srcs:
        a = asm.assemble(f'{_TB}/{subdir}/{r}', _TOOL_INCS, defines=defines or None)
        obj = omf.emit(a)
        objects.append((obj, a))
    return expressload(objects)


def _build_fst(subdir, srcs, defines=None):
    """Assemble srcs (relative to _GSOS/subdir), link, and expressload."""
    fst_dir = f'{_GSOS}/{subdir}'
    incs = [fst_dir] + _GOS_INCS
    objects = []
    for r in srcs:
        a = asm.assemble(f'{fst_dir}/{r}', incs, defines=defines or None)
        obj = omf.emit(a)
        objects.append((obj, a))
    return expressload(objects)


def _build_driver(subdir, srcs, defines=None):
    """Assemble srcs (relative to _GSOS/subdir), link, and expressload."""
    drv_dir = f'{_GSOS}/{subdir}'
    incs = [drv_dir] + _GOS_INCS
    objects = []
    for r in srcs:
        a = asm.assemble(f'{drv_dir}/{r}', incs, defines=defines or None)
        obj = omf.emit(a)
        objects.append((obj, a))
    return expressload(objects)


# ---------------------------------------------------------------------------
# Tool builders — from toolcheck.TOOLMAP + discovered unmapped tools
# ---------------------------------------------------------------------------

def _build_tool014():
    # WindMgr — single-segment KIND=0x0000 (no -lseg in makefile).
    # Code image is byte-identical to gold; residual diff = missing cRELOC/RELOC
    # records that our expressload() does not generate (-34 bytes vs gold).
    return _build_tool('windmgr', [
        'windmgr.asm', 'task.asm', 'NewCalls.asm', 'WDefProc.asm',
        'WCtlDef.asm', 'WMPatch.asm', '../MenuMgr/wcm.asm',
    ])


def _build_tool015():
    # MenuMgr — makefile: -lseg MainTool menumgr.asm.obj wcm.asm.obj;
    #                     -lseg:dynamic PopUpProc popupproc.asm.obj
    # Gold segments: ~ExpressLoad + MainTool(KIND=0x0000) + ~JumpTable(KIND=0x0002)
    #                + PopUpProc(KIND=0x8000)
    # ~JumpTable is auto-generated by MPW and NOT reproducible from ASM source.
    # Residual: ~JumpTable gap prevents byte-exact match.
    # Code-image sizes: MainTool=14045 ✓  PopUpProc=2735 ✓
    TB_menumgr = f'{_TB}/menumgr'
    incs = _TOOL_INCS
    combo = b''
    for r in ['menumgr.asm', 'wcm.asm']:
        a = asm.assemble(f'{TB_menumgr}/{r}', incs)
        combo += omf.emit(a)
    a_pu = asm.assemble(f'{TB_menumgr}/popupproc.asm', incs)
    return expressload(
        [(combo, None), (omf.emit(a_pu), a_pu)],
        opts={
            'multiseg': True,
            'segnames': [b'MainTool', b'PopUpProc'],
            'segkinds':  [0x0000, 0x8000],
        },
    )


def _build_tool016():
    # ControlMgr — makefile: (main) ControlMgr SuperControl NewControl2
    #              DefProcs CtlPatch DummyDrag;
    #              -lseg StatText stattextproc   (NOT :dynamic — KIND=0x0000)
    #              -lseg:dynamic Pics picproc     (KIND=0x8000)
    # Gold segments: ~ExpressLoad + main(KIND=0x0000) + StatText(KIND=0x0000)
    #                + ~JumpTable(KIND=0x0002) + Pics(KIND=0x8000)
    # ~JumpTable NOT reproducible — residual gap.
    # Code-image sizes: main=12489 ✓  StatText=1174 ✓  Pics=358 ✓
    TB16 = f'{_TB}/controlmgr'
    incs = _TOOL_INCS
    main_combo = b''
    for r in ['ControlMgr.asm', 'SuperControl.asm', 'NewControl2.asm',
              'DefProcs.asm', 'CtlPatch.asm', 'DummyDrag.asm']:
        a = asm.assemble(f'{TB16}/{r}', incs)
        main_combo += omf.emit(a)
    a_st = asm.assemble(f'{TB16}/StatTextProc.asm', incs)
    a_pp = asm.assemble(f'{TB16}/PicProc.asm', incs)
    return expressload(
        [(main_combo, None), (omf.emit(a_st), a_st), (omf.emit(a_pp), a_pp)],
        opts={
            'multiseg': True,
            'segnames': [b'main', b'StatText', b'Pics'],
            'segkinds':  [0x0000, 0x0000, 0x8000],
        },
    )


def _build_tool018():
    # QDAux (qdaux) — multi-segment (5 load segments + ~JumpTable).
    # Makefile -lseg grouping (from qdaux/makefile):
    #   -lseg MAINPart: qdaux, faces, icon, special.slabs, common,
    #                   copybits.asm(@MAINPart)  [LOADNAME='MAINPart' segs only]
    #   -lseg:Dynamic Pictures: pics, pixel, text, slabs
    #   -lseg CopyBits: copybits.asm(@CopyBits)  [LOADNAME='CopyBits' + 'main' segs]
    #   -lseg:DYNAMIC SeedFill: seedfill
    #   -lseg:DYNAMIC PixelMap2Rgn: PixelMap2Rgn.aii
    # Gold: ~ExpressLoad + MAINPart(0x0000) + CopyBits(0x0000) + ~JumpTable(0x0002)
    #       + Pictures(0x8000) + SeedFill(0x8000) + PixelMap2Rgn(0x8000)
    # ~JumpTable NOT reproducible — residual gap.
    # Code-image sizes: MAINPart=12105 ✓  CopyBits=1629 ✓  Pictures=7533 ✓
    #                   SeedFill=3137 ✓   PixelMap2Rgn=1895 ✓
    #
    # copybits.asm uses SEG directives to assign segments to load groups via LOADNAME:
    #   LOADNAME='MAINPart' → goes into MAINPart group (segment ISTDPIXELS, 105 bytes)
    #   LOADNAME='CopyBits' → goes into CopyBits group (segment COPYBITS, 143 bytes)
    #   LOADNAME='main'     → also in CopyBits group (stretch/slice code, 1486 bytes)
    TB18 = f'{_TB}/qdaux'
    incs = _TOOL_INCS

    # Assemble copybits.asm once; filter by LOADNAME for each group.
    a_cb = asm.assemble(f'{TB18}/copybits.asm', incs)
    o_cb = omf.emit(a_cb)
    cb_mainpart = _filter_omf_by_loadname(o_cb, {b'MAINPart'})
    # CopyBits group = LOADNAME='CopyBits' + LOADNAME='main' (the stretch/slice segments)
    cb_copybits = _filter_omf_by_loadname(o_cb, {b'CopyBits', b'main'})

    # MAINPart: base objects + copybits(@MAINPart)
    mainpart_combo = b''
    for r in ['qdaux.asm', 'faces.asm', 'icon.asm', 'special.slabs.asm', 'common.asm']:
        a = asm.assemble(f'{TB18}/{r}', incs)
        mainpart_combo += omf.emit(a)
    mainpart_combo += cb_mainpart

    # Pictures group
    pics_combo = b''
    for r in ['pics.asm', 'pixel.asm', 'text.asm', 'slabs.asm']:
        a = asm.assemble(f'{TB18}/{r}', incs)
        pics_combo += omf.emit(a)

    # SeedFill and PixelMap2Rgn
    a_sf = asm.assemble(f'{TB18}/seedfill.asm', incs)
    a_pm = asm.assemble(f'{TB18}/PixelMap2Rgn.aii', incs)

    return expressload(
        [
            (mainpart_combo,  None),
            (cb_copybits,     None),
            (pics_combo,      None),
            (omf.emit(a_sf),  a_sf),
            (omf.emit(a_pm),  a_pm),
        ],
        opts={
            'multiseg': True,
            'segnames': [b'MAINPart', b'CopyBits', b'Pictures', b'SeedFill', b'PixelMap2Rgn'],
            'segkinds':  [0x0000,      0x0000,      0x8000,      0x8000,      0x8000],
        },
    )


def _build_tool019():
    # PrintMgr — single-segment KIND=0x0000 (no -lseg in makefile).
    # Residual: 1 code-image diff at offset 0x884 — NSSTARTUP segment of
    # printmgr.asm contains PEA $0000 in gold vs PEA $001f in our build.
    # Root cause: assembler/source discrepancy (likely a constant differs
    # between the exact shipped source and what we have).
    return _build_tool('printmgr', ['printmgr.asm', 'dialogdata.asm'])


def _build_tool020():
    # LineEdit — multi-segment: TheTool (le+common, KIND=0x0000) + TheProc (LineEditProc, KIND=0x4000)
    # Makefile: -lseg TheTool le.asm.obj common.asm.obj; -lseg:dynamic TheProc LineEditProc.asm.obj
    LE = f'{_TB}/lineedit'
    incs = _TOOL_INCS
    combo0 = b''
    for r in ['le.asm', 'common.asm']:
        a = asm.assemble(f'{LE}/{r}', incs)
        combo0 += omf.emit(a)
    a_proc = asm.assemble(f'{LE}/lineeditproc.asm', incs)
    return expressload(
        [(combo0, None), (omf.emit(a_proc), a_proc)],
        opts={
            'multiseg': True,
            'segnames': [b'TheTool', b'TheProc'],
            'segkinds':  [0x0000, 0x4000],
        },
    )


def _build_tool021():
    # DialogMgr — from toolcheck.TOOLMAP['021']
    return _build_tool('dialogmgr', ['dialog.asm'])


def _build_tool022():
    # Scrap — from toolcheck.TOOLMAP['022']
    return _build_tool('scrap', ['scrap.asm', 'common.asm'])


def _build_tool023():
    # StandardFile — single-segment KIND=0x4000 (no -lseg in makefile).
    # Residual: gold has 4 RELOC + 3 cRELOC records that expressload() does
    # not generate, plus 4 code-image diffs caused by those RELOC patches
    # (gold pre-stores relative values; our build stores absolute addresses).
    return _build_tool('stdfile', ['sfmain.asm', 'sf.asm'])


def _build_tool025():
    # NoteSynth — single-segment KIND=0x4000 (no -lseg in makefile).
    # Residual: 4 code-image diffs due to linkiigs symbol scoping bug:
    # interior label 'UpDate' in SETUSERUPDATERTN segment shadows the
    # segment-name 'UPDATE' from update.aii, causing the NSSTARTUP
    # dispatch table to load the wrong address (0x08be vs gold 0x0639).
    return _build_tool('notesynth', [
        'note.exec.aii', 'alloc.aii', 'noteon.aii', 'noteoff.aii',
        'update.aii', 'freq.aii', 'tables.aii',
    ])


def _build_tool027():
    # FontMgr — single-segment KIND=0x0000 (no -lseg in makefile).
    # Residual: gold has 1 RELOC record (11 bytes) that expressload() does
    # not generate, plus 2 code-image diffs (gold stores 0x0000 at the RELOC
    # site; our build resolves to $02e3 pre-patched at link time, -10 bytes).
    return _build_tool('fontmgr', ['fm.asm', 'common.asm', 'scale.asm'])


def _build_tool028():
    # ListMgr — from toolcheck.TOOLMAP['028']
    return _build_tool('listmgr', ['ListMgr.asm'])


def _build_tool034():
    # TextEdit — single-segment KIND=0x0000 (no -lseg in makefile).
    # Residual: 4444-byte code-image shortfall (31207 built vs 35651 gold).
    # Root cause: assembler bug — our build produces less code than the shipped
    # binary, suggesting conditional assembly or macro expansion differences.
    # Gold also has 2 cRELOC records that expressload() does not generate.
    return _build_tool('textedit', [
        'highlevel.aii', 'block.aii', 'defproc.aii', 'draw.aii',
        'entry.aii', 'fastdraw.aii', 'format.aii', 'idle.aii',
        'key.aii', 'measure.aii', 'memory.aii', 'record.aii',
        'scrap.aii', 'scroll.aii', 'selection.aii', 'super.aii',
        'text.aii', 'width.aii', 'wrap.aii',
    ])


# ---------------------------------------------------------------------------
# FST builders — from fstcheck.FSTMAP (System Disk entries only)
# ---------------------------------------------------------------------------

def _build_char_fst():
    # Character FST — fstcheck.FSTMAP['Char.FST']
    return _build_fst('FSTs/Character', ['Character.FST'], {})


def _build_pro_fst():
    # ProDOS FST — fstcheck.FSTMAP['Pro.FST']
    return _build_fst('FSTs/ProDOS', ['ProDOS.FST'], {'DEBUGSYMBOLS': 0})


# ---------------------------------------------------------------------------
# Driver builders — from drivercheck.DRIVERMAP (System Disk entries only)
# ---------------------------------------------------------------------------

def _build_appledisk35():
    # AppleDisk3.5 — drivercheck.DRIVERMAP['AppleDisk3.5']
    return _build_driver('Drivers/AppleDisk3.5', ['AD3.5.src'], {})


def _build_appledisk525():
    # AppleDisk5.25 — drivercheck.DRIVERMAP['AppleDisk5.25']
    return _build_driver('Drivers/AppleDisk5.25', ['AppleDisk5.25.src'], {})


def _build_console_driver():
    # Console.Driver — drivercheck.DRIVERMAP['Console.Driver']
    return _build_driver('Drivers/Console.Driver',
                         ['Console.aii', 'New.DRI.Patch'],
                         {'Library': 0})


# ---------------------------------------------------------------------------
# Public entry point — auto-discovered by diskcheck.diskbuilders.load()
# ---------------------------------------------------------------------------

def builders(V):
    """Return {disk_path: callable() -> bytes} for all ExpressLoad'd files.

    V is the volume prefix, e.g. '/System.Disk'.
    """
    return {
        # Tools
        f'{V}/System/Tools/Tool014': _build_tool014,
        f'{V}/System/Tools/Tool015': _build_tool015,
        f'{V}/System/Tools/Tool016': _build_tool016,
        f'{V}/System/Tools/Tool018': _build_tool018,
        f'{V}/System/Tools/Tool019': _build_tool019,
        f'{V}/System/Tools/Tool020': _build_tool020,
        f'{V}/System/Tools/Tool021': _build_tool021,
        f'{V}/System/Tools/Tool022': _build_tool022,
        f'{V}/System/Tools/Tool023': _build_tool023,
        f'{V}/System/Tools/Tool025': _build_tool025,
        f'{V}/System/Tools/Tool027': _build_tool027,
        f'{V}/System/Tools/Tool028': _build_tool028,
        f'{V}/System/Tools/Tool034': _build_tool034,
        # FSTs
        f'{V}/System/FSTs/Char.FST':  _build_char_fst,
        f'{V}/System/FSTs/Pro.FST':   _build_pro_fst,
        # Drivers
        f'{V}/System/Drivers/AppleDisk3.5':   _build_appledisk35,
        f'{V}/System/Drivers/AppleDisk5.25':  _build_appledisk525,
        f'{V}/System/Drivers/Console.Driver': _build_console_driver,
    }
