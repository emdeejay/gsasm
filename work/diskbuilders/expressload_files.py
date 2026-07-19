"""diskbuilders/expressload_files.py — M8 ExpressLoad'd file builders.

Wires builders for every ExpressLoad'd tool, FST, and driver on the System Disk.
Each builder returns the FULL on-disk file bytes (the ExpressLoad'd OMF), NOT the
de-ExpressLoad'd code image the *check.py harnesses compare.

Recipe for each file:
    objects = [(omf.emit(asm.assemble(src, INCS)), asm_obj) for src in module_list]
    full_file = gsasm.expressload.expressload(objects, opts)

Module lists and INCS are taken directly from toolcheck.TOOLMAP/INCS,
fstcheck.FSTMAP/INCS, and drivercheck.DRIVERMAP/INCS — do NOT edit those files.

Acceptance split:
  * work/toolcheck.py compares de-ExpressLoad'd code images and now gates all 11
    mapped tools byte-exact (150459/150459), including Tool015/016/018
    ~JumpTable routing and Tool023/027 case-B closures.
  * This module returns full on-disk ExpressLoad OMF files for work/diskcheck.py.
    The current logical residuals on the System Disk are Tool015/016/018/034
    length/content mismatches; Tool014/019/020/021/022/023/025/027/028, the FSTs,
    drivers, and Resource.Mgr are byte-exact at the full-file surface.

CASE A vs CASE B relocations:
  CASE A = >>8 high-byte reloc (size=2, shift=8) -> standalone cRELOC.
  CASE B = source-flagged far-pointer/high-half addends such as
      `Label+$80000000` or `Label+$C0000000` -> standalone RELOC/cRELOC.
  Both classes are handled for the gated single-segment path.  The remaining
  full-file multi-segment residuals are diskbuilder/ExpressLoad packaging work,
  not evidence that the mapped tool code images are wrong.
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_WORK = os.path.dirname(_HERE)
if _WORK not in sys.path:
    sys.path.insert(0, _WORK)

from _common import (
    ensure_repo_on_path,
    firmware_root,
    gsos_incs,
    gsos_source_root,
    toolbox_incs,
    toolbox_root,
)
ensure_repo_on_path()

from gsasm import asm, omf
from gsasm.expressload import expressload

# TOOLMAP['015'/'016'/'018']'s jt_segments spec and the jump-table-aware
# multi-segment linker that derives (and gate-proves against gold) each
# tool's ~JumpTable entries — imported, not copied (E1: the diskbuilder must
# reuse the SAME derivation toolcheck uses).
import toolcheck


def _jt_entries_for(tool):
    """[(target_segnum, routine_offset), ...] for ToolNNN's ~JumpTable, using
    toolcheck's own jt_segments spec and _link_jt_tool derivation (already
    gated byte-exact against gold's ~JumpTable segment for this tool)."""
    subdir, spec = toolcheck.TOOLMAP[tool]
    _images, jt_entries, _jt_segnum, _segnum = toolcheck._link_jt_tool(
        subdir, spec['jt_segments'])
    return jt_entries


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
    for seg in omf.iter_segments(obj_bytes, records=False):
        ln = seg['hdr'].get('LOADNAME', b'').rstrip(b'\x00 ')
        if ln in loadnames:
            out += seg['raw']
    return bytes(out)

# ---------------------------------------------------------------------------
# Source trees — mirrors exactly what toolcheck/fstcheck/drivercheck use
# ---------------------------------------------------------------------------
_SRC  = gsos_source_root()
_TB   = toolbox_root()
_FW   = firmware_root()
_GSOS = os.path.join(_SRC, 'GS.OS')
_CMN  = os.path.join(_GSOS, 'Common')

# Tool INCS (from toolcheck.INCS)
_TOOL_INCS = toolbox_incs(_TB, _FW)

# FST / Driver INCS (from fstcheck.INCS / drivercheck.INCS)
_GOS_INCS = gsos_incs(src=_SRC)


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
    # Full on-disk file is byte-exact; the former case-B far-pointer RELOC pair
    # is now emitted standalone.
    return _build_tool('windmgr', [
        'windmgr.asm', 'task.asm', 'NewCalls.asm', 'WDefProc.asm',
        'WCtlDef.asm', 'WMPatch.asm', '../MenuMgr/wcm.asm',
    ])


def _build_tool015():
    # MenuMgr — makefile: -lseg MainTool menumgr.asm.obj wcm.asm.obj;
    #                     -lseg:dynamic PopUpProc popupproc.asm.obj
    # Gold segments: ~ExpressLoad + MainTool(KIND=0x0000) + ~JumpTable(KIND=0x0002)
    #                + PopUpProc(KIND=0x8000)
    # toolcheck.py proves the code image and generated ~JumpTable routing
    # byte-exact. This generic full-file builder still has a diskcheck logical
    # length residual.
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
            'jt_entries': _jt_entries_for('015'),
        },
    )


def _build_tool016():
    # ControlMgr — makefile: (main) ControlMgr SuperControl NewControl2
    #              DefProcs CtlPatch DummyDrag;
    #              -lseg StatText stattextproc   (NOT :dynamic — KIND=0x0000)
    #              -lseg:dynamic Pics picproc     (KIND=0x8000)
    # Gold segments: ~ExpressLoad + main(KIND=0x0000) + StatText(KIND=0x0000)
    #                + ~JumpTable(KIND=0x0002) + Pics(KIND=0x8000)
    # toolcheck.py proves the code image and generated ~JumpTable routing
    # byte-exact. This generic full-file builder still has a diskcheck logical
    # length residual.
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
            'jt_entries': _jt_entries_for('016'),
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
    # toolcheck.py proves the five code-image segments and 12-entry ~JumpTable
    # byte-exact. This generic full-file builder still has a diskcheck logical
    # length residual.
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
            'jt_entries': _jt_entries_for('018'),
        },
    )


def _build_tool019():
    # PrintMgr — single-segment KIND=0x0000 (no -lseg in makefile).
    # Byte-exact. The former pure-literal high-word-shift residual was a
    # linkiigs bug, not a source mismatch.
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
    # Byte-exact. The former case-B and DevName scoping residuals are closed.
    return _build_tool('stdfile', ['sfmain.asm', 'sf.asm'])


def _build_tool025():
    # NoteSynth — single-segment KIND=0x4000 (no -lseg in makefile).
    # Full on-disk file is byte-exact in diskcheck.
    return _build_tool('notesynth', [
        'note.exec.aii', 'alloc.aii', 'noteon.aii', 'noteoff.aii',
        'update.aii', 'freq.aii', 'tables.aii',
    ])


def _build_tool027():
    # FontMgr — single-segment KIND=0x0000 (no -lseg in makefile).
    # Byte-exact. The former case-B high-half and code-image residuals are closed.
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
# System.Setup builders — ExpressLoad'd toolbox files
# ---------------------------------------------------------------------------

def _build_resource_mgr():
    # Resource.Mgr — GSToolbox/ResourceMgr/makefile:
    #   Asmiigs -d debug=0 -d JimsExperiment=1 Resource.a ; Linkiigs ... -t $B6
    # Single ExpressLoad'd object; byte-exact (SUPER-ized relocs).  The earlier
    # "489B bank-byte gap" was pre-SUPER-ization; the case-A/SUPER work closed it.
    rm_dir = f'{_TB}/ResourceMgr'
    incs = [rm_dir] + _GOS_INCS
    a = asm.assemble(f'{rm_dir}/Resource.a', incs,
                     defines={'debug': 0, 'JimsExperiment': 1})
    return expressload([(omf.emit(a), a)])


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
        # System.Setup
        f'{V}/System/System.Setup/Resource.Mgr': _build_resource_mgr,
    }
