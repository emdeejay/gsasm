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
  EXACT code-image LENGTH (INIT/MAIN/BIGONLY all match to the byte).  All 82
  source objects assemble cleanly.  Each object() is now passed to
  expressload() as its own real per-file object (``obj_group``/``order`` opts,
  E2c) rather than a pre-concatenated combo blob, so linkiigs._build_symtab's
  per-object scoping (private segment names, EXPORT/ENTRY visibility) applies
  per FILE — this closed some, but not all, of the earlier "wrong same-named
  definition wins" binding class (E2's reloc-record-format gap is also closed:
  expressload()'s case-A/case-B standalone-reloc paths already emit
  cRELOC/RELOC/cINTERSEG/INTERSEG where gold does).

  RESIDUAL (E2c investigation, gold-confirmed, OUTSIDE this module's symbol-
  scoping mandate — do NOT hack around it here): MPW LinkIIgs's
  ``object(SYM1,SYM2,...)`` segment SELECTION ORDER is not uniformly
  "filter-list mention order" as `_part`'s ordering assumes. Two confirmed,
  gold-verified counter-examples in TS3's MAIN group alone:
    - Locator.pch: filter list is ``...,RESTORETEXTSTATE,TLSHUTDOWN,
      MESSAGECENTER`` (TLSHUTDOWN mentioned before MESSAGECENTER, out of
      their natural/emit order 5,6). `_part`'s filter-list order places
      TLSHUTDOWN right after RESTORETEXTSTATE (addr 0x103); gold's own
      ``dc.l TLShutDown-1`` dispatch entry at MAIN body offset 0xc stores
      0x121, i.e. TLShutDown at 0x122 — gold placed MESSAGECENTER FIRST
      (natural order), not filter-list order.
    - WindMgr/NewCalls.asm: filter list mentions DOINITCURSOR LAST (after
      FLUSHKEYEVENTS), out of its natural position (right after
      DOMODALWINDOW). Gold's MAIN body diverges from built starting exactly
      at MWGETCTLPART's filter-list-order position (0x202c) — consistent
      with gold inserting DOINITCURSOR in its NATURAL position instead.
    - Counter-counter-example (still holds, do not "fix" by switching to
      natural order everywhere): ControlMgr.asm's CMLOADRESOURCE. Gold's own
      ``dc.l CMLoadResource-1`` entry (ControlMgr.pch's CONTROLCALLTABLE,
      MAIN offset 0x2db6) stores 0x32a1 -> CMLoadResource at 0x32a2, which is
      EXACTLY `_part`'s FILTER-LIST-order prediction (immediately after
      SETLETEXTBYID, skipping the six ByID/helper segments the makefile lists
      later) — natural order predicts 0x3388 instead (230 bytes off, the
      exact size of those six segments), which is wrong.
  So the true MPW rule depends on something not yet identified (not simply
  natural order, not simply filter-list order) and is the majority
  contributor to the remaining TS2/TS3 byte residual. See the git history
  around the "E2c" commit for the analysis; `_part`'s filter-list order is
  left AS IS pending a real reverse-engineered rule (changing it blind
  regresses the confirmed-correct ControlMgr.asm case).

Object lists + -lseg groupings are transcribed verbatim from the linkiigs sections
of ``GSToolbox/Patch/Patch2/makefile`` (TS2) and ``.../Patch3/makefile`` (TS3).
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
    toolbox_incs,
    toolbox_root,
)
ensure_repo_on_path()

from gsasm import asm, omf
from gsasm.expressload import expressload


# ---------------------------------------------------------------------------
# Source trees / INCS — mirror toolcheck.INCS exactly (do NOT edit toolcheck)
# ---------------------------------------------------------------------------
_TB  = toolbox_root()
_FW  = firmware_root()

_INCS = toolbox_incs(_TB, _FW)

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
    return [
        (seg['hdr']['SEGNAME'].rstrip(b'\x00 ').upper(), seg['raw'])
        for seg in omf.iter_segments(obj_bytes, records=False)
    ]


def _whole(path, defines=None):
    """The full OMF object (all segments), plus its ``Asm`` — matches
    ``object`` with no filter.  Returns ``(obj_bytes, asm)``: unlike the
    earlier blob-concatenation design, the object bytes are passed to
    ``expressload()`` UNMODIFIED (with real per-file ``Asm`` metadata) so
    ``linkiigs._build_symtab``'s per-object symbol scoping — private segment
    names, EXPORT/ENTRY visibility — applies per FILE, exactly as MPW
    LinkIIgs binds it, instead of being flattened into one combo blob.
    """
    return _assemble(path, defines)


def _part(path, names, defines=None):
    """The full OMF object (all segments) — like ``_whole`` — plus the
    ordered list of segment indices selected by *names*, matching
    ``object(SYM1,SYM2,...)`` in the linkiigs -lseg directive.

    Returns ``(obj_bytes, asm, seg_order)``.  ``obj_bytes``/``asm`` are the
    FULL, unfiltered object (no byte filtering here — selection happens via
    ``expressload()``'s ``opts['order']``, which needs the real segment
    indices into this object to keep the asm-index mapping ``_build_symtab``
    relies on intact).  ``seg_order`` is the ordered list of segment indices
    into ``obj.segs``' emit order.

    A filter name is normally a segment name (gsasm emits one segment per PROC,
    named for its first label).  When it is instead an interior label, the Asm's
    ``symseg`` map resolves it to the emit-segment that contains it.  Selected
    segments are emitted in FILTER-LIST order (first mention wins when several
    names resolve to the same segment) — GOLDEN PROOF, overturning the earlier
    "original emit order" reading: TS3's golden MAIN places CMLOADRESOURCE at
    0x32a2, immediately after the SETLETEXTBYID segment (which also contains
    the interior label GETLETEXTBYID), exactly the makefile's
    ``ControlMgr.asm.obj(...,SETLETEXTBYID,GETLETEXTBYID,CMLOADRESOURCE,...)``
    order — while ControlMgr.asm's source order has the six ByID/helper
    segments (230 bytes) between them, which is where gsasm used to place them.
    """
    obj, a = _assemble(path, defines)
    segl = _obj_seg_list(obj)
    asm_segs = [s for s in a.segs if s.items or s.name]

    def _resolve(lab):
        """Filter name -> emit-segment index (segment name, else interior
        label via symseg), or None."""
        # (1) direct segment-name match
        for i, (sn, _b) in enumerate(segl):
            if sn == lab:
                return i
        # (2) interior label -> containing emit segment
        for key in (lab, lab.lower(), lab.capitalize()):
            if key in a.symseg:
                sg = a.symseg[key]
                if sg is None or sg < 0 or sg >= len(a.segs):
                    return None
                try:
                    ei = asm_segs.index(a.segs[sg])
                except ValueError:
                    return None
                return ei if ei < len(segl) else None
        return None

    order: list[int] = []
    for lab in (n.upper() for n in names):
        ei = _resolve(lab)
        if ei is not None and ei not in order:
            order.append(ei)

    return obj, a, order


def _expressload_groups(groups):
    """Run expressload over a list of ``(items, segname, segkind)``, where
    each *items* is a list of ``_whole()``/``_part()`` results (2-tuples or
    3-tuples respectively) for one named load group (INIT/MAIN/BIGONLY).

    Builds the flat per-file ``objects`` list, the ``obj_group`` map (one
    entry per object, giving its output-group index — monotonic
    non-decreasing, group order preserved exactly as *groups* lists them),
    and the global ``order`` list of ``(obj_idx, seg_idx)`` pairs (honoring
    each file's segment selection; a whole file contributes all its segments
    in emit order).  Each named group's placed segments stay contiguous and
    in *groups*' sequence — expressload() groups strictly by ``obj_group``,
    and objects are appended group-by-group below.
    """
    objects: list[tuple[bytes, object]] = []
    obj_group: list[int] = []
    order: list[tuple[int, int]] = []
    segnames = [g[1] for g in groups]
    segkinds = [g[2] for g in groups]

    for gi, (items, _segname, _segkind) in enumerate(groups):
        for item in items:
            if len(item) == 2:
                obj_bytes, a = item
                seg_order = list(range(len(_obj_seg_list(obj_bytes))))
            else:
                obj_bytes, a, seg_order = item
            oi = len(objects)
            objects.append((obj_bytes, a))
            obj_group.append(gi)
            order.extend((oi, si) for si in seg_order)

    return expressload(objects, opts={
        'multiseg': True,
        'obj_group': obj_group,
        'order': order,
        'segnames': segnames,
        'segkinds': segkinds,
    })


# ---------------------------------------------------------------------------
# TS2 — GSToolbox/Patch/Patch2/makefile  (linkiigs section)
# ---------------------------------------------------------------------------
def _build_ts2():
    # -lseg:$2000 INIT
    init = [_whole(f'{_P2}/install.asm'), _whole(f'{_P2}/InitSeg.asm')]

    # -lseg MAIN
    main = [
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
    ]

    # -lseg BIGONLY
    big = [
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
    ]

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
    init = [_whole(f'{_P3}/install.asm'), _whole(f'{_P3}/InitCode.pch')]

    # -lseg MAIN
    main = [
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
    ]

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
    (correct segment structure + exact code-image lengths) — see this module's
    top-of-file STATUS/RESIDUAL note for the current gap (a `_part` segment-
    selection-ORDER question, not symbol scoping). diskcheck's contract
    compares logical bytes before overlay, so a non-exact build is reported as
    a worklist item and NOT overlaid — the image stays 100%.
    """
    return {
        f'{V}/System/System.Setup/TS2': _build_ts2,
        f'{V}/System/System.Setup/TS3': _build_ts3,
    }
