"""diskbuilders/toolsets.py — M8 builders for the "Tool Setup" toolset bundles.

Wires TS2 and TS3 (``/System.Disk/System/System.Setup/TS{2,3}``): the multi-object,
multi-segment ExpressLoad'd toolset patch bundles the GS/OS installer loads after
Tool.Setup.  Each is assembled from a large object list and linked with ``linkiigs``
``-lseg`` directives, then ExpressLoad'd — exactly like the ToolNNN builders in
``expressload_files.py``, but with two extra wrinkles this module handles:

  1. Per-object **segment filtering**: the makefiles pass ``object(SYM1,SYM2,...)``
     to the linker, pulling only the OMF segments that DEFINE those symbols into a
     given ``-lseg`` group.  gsasm emits one OMF segment per PROC (segment name =
     the PROC's first label), so most filter names are segment names; a few are
     interior labels, resolved to their containing segment via the Asm's
     ``symseg`` map.  ``_part`` implements this (label-aware, emit-order).

  2. Three named load groups with explicit KINDs (from the ``-lseg`` directives):
       TS2: INIT(KIND=0x2000) + MAIN(0x0000) + BIGONLY(0x0000)
       TS3: INIT(KIND=0x2000) + MAIN(0x0000)

Gold segment layout (from ``omf.parse_header`` over the on-disk files):

  TS2 (36665 B):  ~ExpressLoad + INIT(len 1027) + MAIN(len 22526) + BIGONLY(len 10775)
  TS3 (41700 B):  ~ExpressLoad + INIT(len  662) + MAIN(len 38492)

STATUS — logical residual, NOT byte-exact (see RESIDUAL note below):
  The grouping/filtering is correct: every built segment reproduces the gold's
  EXACT code-image LENGTH (INIT/MAIN/BIGONLY all match to the byte), and long code
  stretches are byte-identical (TS3 MAIN matches through offset 0x2db6).  All 82
  source objects assemble cleanly.  The remaining diff is two gsasm-core gaps
  (both OUTSIDE this module's mandate — do NOT patch gsasm/ from here):
    (a) linkiigs multi-object symbol scoping: with ~40 filtered objects, dispatch
        tables (e.g. tl.asm's TLCALLTABLE) resolve some DC.L entries to the wrong
        same-named definition (e.g. TLVERSION from Locator.pch shadows a local
        target) — the documented Tool019/Tool025 scoping class, at larger scale.
    (b) expressload reloc-record format: gold INIT/MAIN use cINTERSEG + cRELOC +
        RELOC records for interseg/intra refs; expressload() emits only SUPER
        records (and inline-patches type-2 interseg).  BIGONLY (pure SUPER) is the
        only group whose reloc format expressload can already match.
  Both are shared with every other multi-seg tool residual and are owned by the
  gsasm effort, not the disk builders.

Object lists + -lseg groupings are transcribed verbatim from the linkiigs sections
of ``GSToolbox/Patch/Patch2/makefile`` (TS2) and ``.../Patch3/makefile`` (TS3).
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_WORK = os.path.dirname(_HERE)
_REPO = os.path.dirname(_WORK)
for _p in (_REPO, _WORK):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from gsasm import asm, omf
from gsasm.expressload import expressload


# ---------------------------------------------------------------------------
# Source trees / INCS — mirror toolcheck.INCS exactly (do NOT edit toolcheck)
# ---------------------------------------------------------------------------
_SRC = 'ref/GSOS_6/IIGS.601.SRC'
_TB  = _SRC + '/GSToolbox'
_FW  = _SRC + '/GSFirmware'

_INCS = (
    [d for d, _, _ in os.walk(_TB)]
    + [d for d, _, _ in os.walk(_FW)]
    + ['work/includes']
)

# Directory shorthands (case as on disk; the fs is case-insensitive but be exact).
_P2   = f'{_TB}/Patch/Patch2'
_P3   = f'{_TB}/Patch/Patch3'
_TL   = f'{_TB}/tl'
_DESK = f'{_TB}/desk'
_EV   = f'{_TB}/EVENTS'
_IM   = f'{_TB}/INTMATH'
_QD   = f'{_TB}/QD'
_QDA  = f'{_TB}/QD/QDAlone'
_SND  = f'{_TB}/Sound'
_MT   = f'{_TB}/MISC.TOOLS'
_MM   = f'{_TB}/MM'
_WM   = f'{_TB}/WindMgr'
_CM   = f'{_TB}/ControlMgr'
_MENU = f'{_TB}/MenuMgr'
_DLG  = f'{_TB}/DialogMgr'


# ---------------------------------------------------------------------------
# Assembly cache + segment helpers
# ---------------------------------------------------------------------------
_CACHE: 'dict' = {}


def _assemble(path, defines=None):
    """Assemble *path* once (cached); return ``(omf_bytes, Asm)``."""
    key = (path, tuple(sorted((defines or {}).items())))
    if key not in _CACHE:
        a = asm.assemble(path, _INCS, defines=defines or None)
        _CACHE[key] = (omf.emit(a), a)
    return _CACHE[key]


def _obj_seg_list(obj_bytes):
    """Return ``[(SEGNAME_upper, seg_bytes), ...]`` in emit order."""
    out = []
    off = 0
    while off < len(obj_bytes):
        h = omf.parse_header(obj_bytes[off:])
        bc = h['BYTECNT']
        if bc == 0:
            break
        out.append((h['SEGNAME'].rstrip(b'\x00 ').upper(), obj_bytes[off:off + bc]))
        off += bc
    return out


def _whole(path, defines=None):
    """The full OMF object (all segments) — matches ``object`` with no filter."""
    return _assemble(path, defines)[0]


def _part(path, names, defines=None):
    """OMF object filtered to segments defining any of *names* — matches
    ``object(SYM1,SYM2,...)`` in the linkiigs -lseg directive.

    A filter name is normally a segment name (gsasm emits one segment per PROC,
    named for its first label).  When it is instead an interior label, the Asm's
    ``symseg`` map resolves it to the emit-segment that contains it.  Selected
    segments are emitted in their ORIGINAL emit order (not the filter-list order),
    each as a whole — exactly as MPW LinkIIgs pulls a segment for a named symbol.
    """
    obj, a = _assemble(path, defines)
    segl = _obj_seg_list(obj)
    asm_segs = [s for s in a.segs if s.items or s.name]
    want = {n.upper() for n in names}

    keep = set()
    # (1) direct segment-name matches
    for i, (sn, _b) in enumerate(segl):
        if sn in want:
            keep.add(i)
    # (2) interior-label matches via symseg -> containing emit segment
    for lab in want:
        for key in (lab, lab.lower(), lab.capitalize()):
            if key in a.symseg:
                sg = a.symseg[key]
                if sg is None or sg < 0 or sg >= len(a.segs):
                    break
                try:
                    ei = asm_segs.index(a.segs[sg])
                except ValueError:
                    break
                if ei < len(segl):
                    keep.add(ei)
                break

    out = bytearray()
    for i, (_sn, sb) in enumerate(segl):
        if i in keep:
            out += sb
    return bytes(out)


def _expressload_groups(groups):
    """Run expressload over a list of ``(group_obj_bytes, segname, segkind)``.

    Each group's concatenated OMF object bytes become one ExpressLoad load
    segment (in order), preceded by the ~ExpressLoad directory segment.
    """
    objects  = [(g[0], None) for g in groups]
    segnames = [g[1] for g in groups]
    segkinds = [g[2] for g in groups]
    return expressload(objects, opts={
        'multiseg': True,
        'segnames': segnames,
        'segkinds': segkinds,
    })


# ---------------------------------------------------------------------------
# TS2 — GSToolbox/Patch/Patch2/makefile  (linkiigs section)
# ---------------------------------------------------------------------------
def _build_ts2():
    # -lseg:$2000 INIT
    init = _whole(f'{_P2}/install.asm') + _whole(f'{_P2}/InitSeg.asm')

    # -lseg MAIN
    main = b''.join([
        _whole(f'{_P2}/strip.asm'),
        _whole(f'{_P2}/tl.asm'),
        _part(f'{_TL}/tl.asm', ['TLMEMROUTINES', 'TLSTARTANDSTOP'], {'RAMVersion': 0}),
        _part(f'{_TL}/Loading.asm', ['SETDEFAULTTPT', 'UNLOADTOOLS', 'SETUPFORUNLOAD',
                                     'CLEANUPFORUNLOAD', 'MAKEIDNUM']),
        _whole(f'{_TL}/Mount.asm'),
        _whole(f'{_TL}/TextState.asm'),
        _whole(f'{_TL}/messageCenter.asm'),
        _whole(f'{_TL}/msgbyname.asm'),
        _part(f'{_P3}/Locator.pch', ['TLVERSION']),
        _whole(f'{_P2}/desk.asm'),
        _part(f'{_DESK}/desk.asm', ['DONDAINIT', 'DASTARTUP', 'DASHUTDOWN', 'DAVERSION',
                                    'DASTATUS', 'DAGETMEM', 'INITALL'], {'RAMVersion': 0}),
        _part(f'{_DESK}/cdacalls.asm', ['INSTCDA', 'REMOVECDA', 'MYDEREF', 'GROWTABLE']),
        _part(f'{_DESK}/ndacalls.asm', ['INSTALLNDA', 'OPENNDA', 'CLOSENDA', 'GETNUMNDAS',
                                        'ADDTORUNQ', 'REMOVEFROMRUNQ', 'STARTNDACALL',
                                        'DESKUTILS', 'ENDNDACALL', 'FUTZRESIDS', 'SENDINIT',
                                        'SENDOPEN', 'DOCLOSESTUFF', 'SENDCLOSE', 'DIEHORRIBLY']),
        _whole(f'{_P2}/event.asm'),
        _part(f'{_EV}/em.asm', ['KEYBOARD', 'SETMODBITS', 'EMDATA', 'GETKEYTRANSLATION',
                                'SETKEYTRANSLATION', 'USECOOLMOUSEPOS', 'CREATEMOUSEMESSAGE'],
              {'MIDI': 0}),
        _part(f'{_P3}/EventMgr.pch', ['HANDLEPENDINGSYSBEEP2']),
        _whole(f'{_P2}/scheduler.pch'),
        _whole(f'{_P2}/adb.asm'),
        _whole(f'{_P2}/sane.asm'),
        _whole(f'{_P2}/im.asm'),
        _part(f'{_IM}/im.asm', ['LONG2DEC']),
        _part(f'{_QD}/polys.asm', ['ISTDPOLY', 'FRPOLY', 'PPOLY', 'EPOLY', 'IPOLY', 'FPOLY',
                                   'REPRGNSAVE', 'SAVERGNSAVE', 'KILLPOLYREGION', 'FRAMEAPOLY',
                                   'POLYCHECKPENVIS', 'MAKEPOLYREGION']),
        _part(f'{_QD}/init.asm', ['QDSTART', 'NEWHANDLEGLUE', 'DISPOSEHANDLEGLUE']),
        _whole(f'{_P2}/qd.asm'),
        _whole(f'{_P2}/rdf.asm'),
        _part(f'{_QD}/text.asm', ['IGETFGS', 'GETFONTGLOBALS', 'GETFONTLORE', 'GETFL',
                                  'SETUPFONTHEADPTR', 'ISETUPFONTINFO']),
        _whole(f'{_P2}/cursor.patch.asm'),
        _part(f'{_QD}/cursor.asm', ['ISHIELDCURSOR', 'UPDATECURSOR', 'REFRESHCURSOR',
                                    'HANDLECURSOR', 'CLEARSCB', 'CURSORSHUTDOWN'], {'MIDI': 0}),
        _whole(f'{_P2}/sound.asm'),
        _whole(f'{_SND}/StartSound.aii'),
        _whole(f'{_SND}/StopSound.aii'),
        _whole(f'{_SND}/StartPlaying.aii'),
        _whole(f'{_SND}/SetUpDOC.aii'),
        _whole(f'{_SND}/SetGCB.aii'),
        _whole(f'{_SND}/ServeGen.aii'),
        _whole(f'{_SND}/Fsynth_irq.aii'),
        _whole(f'{_P2}/misc.tools.asm'),
        _whole(f'{_MT}/queue.asm'),
        _whole(f'{_MT}/converter.asm'),
        _whole(f'{_MT}/InterruptState.asm'),
        _whole(f'{_MT}/RomDataMgr.asm', {'Big': 1}),
        _part(f'{_P3}/Misc.tools.pch', ['COMPUTEDEFAULTFAILMSG']),
        _whole(f'{_P2}/mm.asm'),
        _part(f'{_MM}/mm.asm', ['REALFREEMEM', 'SEARCHUPFAST', 'SEARCHDOWNFAST', 'GETNEXTFREE',
                                'SEARCHUP', 'SEARCHDOWN', 'STARTX', 'START0', 'STARTXTOP',
                                'SEARCHHANDLE', 'CHECKRECENT', 'GETNEXT', 'XSEARCHFAIL',
                                'XUSERPURGE', 'ADDTOOOMQUEUE', 'DELETEFROMOOMQUEUE',
                                'GETIDOFCALLINGROUTINE', 'MMSHUTDOWN', 'XPURGE', 'NUKEIT',
                                'BESTTOP', 'VERIFYHANDLE', 'SETHANDLEID'], {'RAMVersion': 0}),
        _whole(f'{_P2}/text.tools.asm'),
    ])

    # -lseg BIGONLY
    big = b''.join([
        _part(f'{_QD}/init.asm', ['DOFASTSETUP', 'TESTGPS']),
        _part(f'{_QD}/conics.asm', ['IDRAWCONIC', 'OVALPENSIZE']),
        _part(f'{_QD}/lines.asm', ['ISTDLINE', 'GRABPENLOC', 'STABPENLOC', 'FASTRATIO']),
        _part(f'{_QD}/pixelmaps.asm', ['IRGNBLT']),
        _part(f'{_QD}/rects.asm', ['COMMONSLABSETUP', 'SETFIRSTDESTREF', 'NEXTPATSLICE',
                                   'SETNEXTDESTREF', 'ISETSLABADR', 'CHECKPENVIS', 'GRABPENSIZE',
                                   'FRAMERECT', 'PAINTRECT', 'ERASERECT', 'INVERTRECT',
                                   'FILLRECT', 'JOINRECT', 'CALLRECT', 'GETRECT', 'ISTDRECT',
                                   'FRRECT', 'IDRAWRECTB', 'FASTDRAWRECT', 'IXSETUP', 'XSETUP320',
                                   'XSETUP640', 'SLABTABLE', 'FASTSLABTABLE', 'LEFTMASKTABLE',
                                   'RIGHTMASKTABLE']),
        _part(f'{_QD}/env.asm', ['IROTATEPAT', 'IROTATEMASK', 'IEXPANDMASK', 'EXPANDM640',
                                 'EXPANDM320', 'IUSERPAT2ZP', 'IPORTLOC2ZP', 'IGETPENPREADY',
                                 'IGETBACKPREADY', 'IPEN2ZP', 'IBACK2ZP', 'IGETMASKREADY']),
        _whole(f'{_P2}/slab.asm'),
        _part(f'{_QD}/regions.asm', ['DRAWRGN', 'DEREFC', 'GETBOUNDSC', 'UNLOCKC', 'INITUP3RGNS',
                                     'INITRGNUP', 'IINITRGN', 'LINESETUP', 'ZEROSCANBUF',
                                     'GETNEXTV', 'INITDATAPTR', 'LEFTBITMASK', 'RIGHTBITMASK']),
        _part(f'{_QD}/rgndefs.asm', ['RGNSAVE']),
        _whole(f'{_QD}/slabs.asm'),
        _part(f'{_QD}/text.asm', ['IDCHAR', 'IDTEXT', 'IVALIDCHAR', 'FASTPUTCHAR', 'ISTDTEXT',
                                  'ICALCDRAWSTATUS', 'IADDEXTRAS']),
        _part(f'{_QD}/clipping.asm', ['MINRECTTOY1']),
    ])

    return _expressload_groups([
        (init, b'INIT',    0x2000),
        (main, b'MAIN',    0x0000),
        (big,  b'BIGONLY', 0x0000),
    ])


# ---------------------------------------------------------------------------
# TS3 — GSToolbox/Patch/Patch3/makefile  (linkiigs section)
# ---------------------------------------------------------------------------
def _build_ts3():
    # -lseg:$2000 INIT
    init = _whole(f'{_P3}/install.asm') + _whole(f'{_P3}/InitCode.pch')

    # -lseg MAIN
    main = b''.join([
        _part(f'{_P3}/Locator.pch', ['LOCATORCALLTABLE', 'TLVERSION', 'SAVETEXTSTATE',
                                     'RESTORETEXTSTATE', 'TLSHUTDOWN', 'MESSAGECENTER']),
        _whole(f'{_P3}/WindMgr.pch'),
        _part(f'{_WM}/WindMgr.asm', ['GETWREFCON', 'LONGCALL']),
        _part(f'{_WM}/NewCalls.asm', ['ALERTWINDOW', 'GETAUXWINDINFO', 'KILLAUXWINDINFO',
                                      'DOMODALWINDOW', 'MWGETCTLPART', 'MWSETMENUPROC',
                                      'MWSTDDRAWPROC', 'MWSETUPEDITMENU', 'FINDCURSORCTL',
                                      'RESIZEINFOBAR', 'HANDLEDISKINSERT', 'FLUSHKEYEVENTS',
                                      'DOINITCURSOR', 'UPDATEWINDOW']),
        _whole(f'{_P3}/ControlMgr.pch'),
        _part(f'{_CM}/ControlMgr.asm', ['CTLSHUTDOWN', 'FINDRADIOBUTTON', 'SETLETEXTBYID',
                                        'GETLETEXTBYID', 'CMLOADRESOURCE', 'GETANDSETPREFS',
                                        'LOADRESOURCE', 'DRAWRECT', 'PUSHVVERT_PEN', 'STATICRAM',
                                        'DEREFERENCE', 'SET_PATT', 'SETVERTPEN', 'FRACTION',
                                        'PUSHRECT2', 'PUSHVCTL_FONT', 'PUSHRECORD', 'READMOREFLAGS',
                                        'ENTER470', 'SET_TEXTMODE', 'SMEAR', 'COMPUTESCROLLCOLOR',
                                        'SETCTLVALUEBYID', 'GETCTLVALUEBYID', 'INVALONECTLBYID',
                                        'HILITECTLBYID']),
        _whole(f'{_CM}/StatTextProc.asm'),
        _part(f'{_CM}/PicProc.asm', ['DO_DISPOSE']),
        _part(f'{_CM}/defprocs.asm', ['SCROLL_PROC', 'REC_SIZE', 'SCROLL_DRAW', 'NULL_RET',
                                      'SCROLL_HIT', 'SCROLL_INIT', 'NEWVIEW', 'MOVE_BAR',
                                      'INVAL_RECT', 'CHECKFORVIS', 'SETUPCOLOR', 'UP_BOX',
                                      'DOWN_BOX', 'LEFT_BOX', 'RIGHT_BOX', 'DRAW_ARROW2',
                                      'SET_PATT', 'CENTER_HOR', 'PRINT_ICON', 'SCROLLSTATE',
                                      'SET_PENPOS']),
        _whole(f'{_P3}/MenuMgr.pch'),
        _part(f'{_MENU}/MenuMgr.asm', ['PUSHPORTDATA', 'POPPORTDATA', 'INSERTPATHMITEMS']),
        _whole(f'{_MENU}/PopUpProc.asm'),
        _whole(f'{_P3}/DialogMgr.pch'),
        _part(f'{_DLG}/Dialog.asm', ['DIALOGSTARTUP', 'QUIT2', 'DISPOSELOCALS', 'ALERTICONDATAS']),
        _whole(f'{_P3}/QD.pch'),
        _whole(f'{_P3}/Cursor.Pch'),
        _part(f'{_QD}/Env.asm', ['EXTENDCOLORWORD']),
        _whole(f'{_P3}/Desk.pch'),
        _whole(f'{_QDA}/strip.asm'),
        _part(f'{_DESK}/NDACalls.asm', ['STARTNDACALL', 'DESKUTILS', 'ENDNDACALL', 'OERROUT4',
                                        'OPENNDA', 'FUTZRESIDS', 'AREWETOP', 'SENDOPEN',
                                        'SENDCLOSE', 'CHECKNDASTUFF', 'CALLCDAMENU',
                                        'FINDTHISWINDOW', 'DOCLOSESTUFF', 'FRONTTOAX',
                                        'SENDACTION', 'SENDINIT']),
        _whole(f'{_P3}/Sound.aii'),
        _whole(f'{_SND}/StartSound.aii'),
        _whole(f'{_SND}/Fsynth_irq.aii'),
        _whole(f'{_SND}/ServeGen.aii'),
        _whole(f'{_SND}/SetGCB.aii'),
        _whole(f'{_SND}/StartPlaying.aii'),
        _part(f'{_SND}/StartUp.aii', ['SSTARTUP']),
        _whole(f'{_P3}/memory.Pch'),
        _part(f'{_MM}/mm.asm', ['VERIFYHANDLE', 'SETHANDLEID'], {'RAMVersion': 0}),
        _part(f'{_P3}/Misc.tools.pch', ['MTCALLTABLE', 'MTVER', 'MTINIT', 'NEWSYSFAIL',
                                        'COMPUTEDEFAULTFAILMSG', 'GETADDR', 'ORIGBELLVECTOR',
                                        'NEWSYSBEEP', 'GETROMRESOURCE']),
        _part(f'{_MT}/ROMDataMgr.asm', ['CHOOSEFONTSTUFF'], {'Big': 1}),
        _whole(f'{_P3}/EventMgr.pch'),
        _part(f'{_EV}/em.asm', ['USECOOLMOUSEPOS', 'CREATEMOUSEMESSAGE'], {'MIDI': 0}),
        _whole(f'{_P3}/IntMath.pch'),
        _whole(f'{_P3}/Text.Tools.pch'),
        _whole(f'{_P3}/SANE.pch'),
    ])

    return _expressload_groups([
        (init, b'INIT', 0x2000),
        (main, b'MAIN', 0x0000),
    ])


# ---------------------------------------------------------------------------
# Public entry point — auto-discovered by diskcheck.diskbuilders.load()
# ---------------------------------------------------------------------------
def builders(V):
    """Return {disk_path: callable() -> bytes} for the Tool Setup bundles.

    V is the volume prefix, e.g. '/System.Disk'.  Each callable returns the full
    ExpressLoad'd OMF file.  Both currently produce a precise LOGICAL RESIDUAL
    (correct segment structure + exact code-image lengths; byte diffs confined to
    linkiigs symbol-scoping targets and expressload's SUPER-only reloc format).
    diskcheck's contract compares logical bytes before overlay, so a non-exact
    build is reported as a worklist item and NOT overlaid — the image stays 100%.
    """
    return {
        f'{V}/System/System.Setup/TS2': _build_ts2,
        f'{V}/System/System.Setup/TS3': _build_ts3,
    }
