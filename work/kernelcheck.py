#!/usr/bin/env python3
"""kernelcheck.py — M6 acceptance harness for the GS/OS kernel.

Assembles the GS/OS kernel sources and compares against the shipping
System 6.0.1 binaries byte-for-byte.

Kernel outputs and recipes (from GS.OS/Scripts/linkOS, GS.OS/MakeFiles/make.os,
make.p8, make.error.msg — transcribed exactly, no guessing):

  GS.OS       = Loader.bin ++ catenate(scm.bin, scm.bin.2..7, scm.bin.12..17)
  Start.GS.OS = catenate(scm.bin.8..11)
  P8          = mkbiniigs(mli.out) ++ OverlayIIgs(various drivers)
  prodos      = makebin(ProBoot.src, org=0x2000)  — already in probootcheck.py
  ERROR.MSG   = linkiigs(english.obj) plain OMF

scm.bin numbering (from linkOS -lseg assignments, comment "# becomes scm.bin.N"):
  scm.bin     (1) = scm_seg_0  : @start_seg0  @oscall_seg   @end_seg0
  scm.bin.2   (2) = scm_seg_1  : @start_seg1  @misc_seg     @end_seg1
  scm.bin.3   (3) = scm_seg_2  : @start_seg2  @scm_main     @end_seg2
  scm.bin.4   (4) = scm_seg_3  : @start_seg3  @system_svc   @end_seg3
  scm.bin.5   (5) = scm_seg_4  : @start_seg4  @bank_e1      @end_seg4
  scm.bin.6   (6) = b00segr    : b00segr.s.obj bank0.obj b00segr.e.obj
  scm.bin.7   (7) = be0segr    : be0segr.s.obj device.dispatcher.obj be0segr.e.obj
  scm.bin.8   (8) = gquit.1    : gquit.obj(@seg_gldr)
  scm.bin.9   (9) = gquit.2    : gquit.obj(@seg_b0)
  scm.bin.10 (10) = gquit.3    : gquit.obj(@seg_e1)
  scm.bin.11 (11) = gquit.4    : gquit.obj(@seg_e0)
  scm.bin.12 (12) = cache      : cache.obj
  scm.bin.13 (13) = init.1     : init1.obj
  scm.bin.14 (14) = init.2     : init2.obj
  scm.bin.15 (15) = init.3     : init3.obj
  scm.bin.16 (16) = init.4     : init4.obj
  scm.bin.17 (17) = terminator : scm.obj(@terminator)

GS.OS catenation (from linkOS):
  Loader.bin ++ scm.bin ++ scm.bin.{2..7} ++ scm.bin.{12..17}

Start.GS.OS catenation (from linkOS):
  scm.bin.{8..11}

Notes on Loader.bin:
  From make.os:
    AsmIIgs Loader.a -> Loader.obj
    AsmIIgs GSHeader.a -> GSHeader.obj
    AsmIIgs GSFooter.a -> GSFooter.obj
    LinkIIgs -x GSHeader.obj Loader.obj GSFooter.obj -> Loader.S16
    MakeBinIIgs Loader.S16 -> Loader.bin (+ Loader.bin.2)
  Loader.a crashes gsasm on complex macro expansion (Loader.Macros IF/WHILE).
  GS.OS comparison is made against the SCM portion only (golden offset 16590+).

SCM segment layout:
  Each scm.bin.N starts with a 48-byte header (SEG_N_HEADER) followed by the
  segment content.  The header ends at seg_N_start - header_length + header_size.
  Between the header data and seg_N_start there is a zero-fill gap:
    gap = header_length - len(header_data) = $30 - $25 = $0B bytes per segment.
  From SCM.src EQUs:
    header_length = $30 = 48 bytes
    seg_0_start   = $009A00  → header ORG = $99D0  (gap = $0B)
    seg_1_start   = $00B300  → header ORG = $B2D0  (gap = $0B)
    seg_2_start   = $00D000  → header ORG = $CFD0  (gap = $0B)
    seg_3_start   = $01FC00  → header ORG = $1FBD0 (gap = $0B)
    seg_4_start   = $E1D980  → header ORG = $E1D950 (gap = $0B)
  gsasm bug: PROC ORG with ', noskip' suffix prevents ORG evaluation; the harness
  hard-codes the known gap = header_length - SEG_N_HEADER.length bytes.

Notes on P8:
  P8 requires assembling mlisrc.aii plus multiple drivers and overlaying them.
  mlisrc.aii uses include files M16.UTIL and e16.memory not in the GS.OS tree;
  comparison is skipped pending include-path resolution.

Known residuals (reportable gsasm-core gaps, not fixable in harness):
  1. lda #^Label (bank byte): SUPER type-27 unimplemented — gsasm emits 0x00.
     Affects ~25% of GS.OS content bytes and ~14% of Start.GS.OS.
  2. DC.W label-*: PC-relative offset expressions produce wrong LEXPR bytes in
     gsasm asm.py.  Error.Msg offset table (122 entries) completely wrong → 22% match.
  3. DC.W seg_N_end-seg_N_start: when header group is linked separately, seg_N_end
     is unresolved (=0).  ~24 bytes wrong across SCM header procs in GS.OS.
  4. Init1.Src Record/EndR: pseudo-op unsupported; 64 bytes missing from scm.bin.13.
  5. Loader.a: complex IF/WHILE macros crash gsasm; Loader.bin excluded.
  6. Init2/Init3: include 'E16.Control', 'E16.Window' not found.
  7. mlisrc.aii: include 'M16.UTIL', 'e16.memory' not in GS.OS tree (P8 ~4%).
  8. &ord builtin: 346 non-fatal errors in SCM.src.

Usage:
    python3 work/kernelcheck.py              # full report
    python3 work/kernelcheck.py --diff       # show first-diff context
    python3 work/kernelcheck.py ERRMSG       # single output verbose

Golden extraction (run once, idempotent):
    DISK2="ref/GSOS_6/System601_disks/System 6.0.1/Disk 2 of 7 System Disk.2mg"
    cadius EXTRACTFILE "$DISK2" "/System.Disk/System/GS.OS"        ref/GSOS_6/os_bin/
    cadius EXTRACTFILE "$DISK2" "/System.Disk/System/Start.GS.OS"  ref/GSOS_6/os_bin/
    cadius EXTRACTFILE "$DISK2" "/System.Disk/System/P8"           ref/GSOS_6/os_bin/
    cadius EXTRACTFILE "$DISK2" "/System.Disk/System/Error.Msg"    ref/GSOS_6/os_bin/
    cadius EXTRACTFILE "$DISK2" "/System.Disk/ProDOS"              ref/GSOS_6/os_bin/
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gsasm import asm as _asm
from gsasm import omf as _omf
from gsasm import linkiigs as _lnk
from gsasm import makebin as _makebin

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

SRC        = 'ref/GSOS_6/IIGS.601.SRC'
GS         = SRC + '/GS.OS'
OS_DIR     = GS  + '/OS'
CMN        = GS  + '/Common'
DISK2      = ('ref/GSOS_6/System601_disks/System 6.0.1/'
              'Disk 2 of 7 System Disk.2mg')
GOLDEN_DIR = 'ref/GSOS_6/os_bin'

# Include paths: Common first, then every GS.OS subdir
INCS = [CMN] + [d for d, _, _ in os.walk(GS)]

# Non-fatal pseudo-ops that gsasm doesn't implement (harmless to ignore)
_IGNORE_OPS = ('pagesize', 'datachk', 'endproc', 'eject', 'writeln', 'codechk')

# Known Loader.bin prefix size in GS.OS (derived from golden: first SCM segment
# SEG_0_HEADER starts at byte 16590 = 0x40CE in the golden GS.OS file).
LOADER_BIN_SIZE = 16590

# From SCM.src EQUs (transcribed exactly):
#   header_length = $30 = 48
#   seg_N_start per segment
SCM_HEADER_LENGTH = 0x30   # 48 bytes ($30)

# Known SCM segment start addresses (from SCM.src EQUs, transcribed):
#   seg_0_start = $009A00, seg_1_start = $00B300, seg_2_start = $00D000,
#   seg_3_start = $01FC00, seg_4_start = $E1D980
SCM_SEG_STARTS = {
    'scm_seg_0': 0x009A00,
    'scm_seg_1': 0x00B300,
    'scm_seg_2': 0x00D000,
    'scm_seg_3': 0x01FC00,
    'scm_seg_4': 0xE1D980,
}

# Segment header specs: (header_data_size, segment_start_addr) pairs derived from
# source EQUs and golden binary analysis.  header_length = $30 = 48 for all.
# gap = header_length - header_data_size (zero-filled bytes between header and content).
#
# b00segr (B00segr.s.src):
#   b00segr_org = $00AA00, header_data = 37 bytes, gap = 11
# be0segr (be0segr.s.src):
#   be0segr_org = $E0E000, header_data = 37 bytes, gap = 11
# cache (Cache.Src):
#   cashseg_org = $00A280, header_data = 41 bytes, gap = 7
# init 1-4 (init.equ.src):
#   init_1_org = $00B200, header_data = 37 bytes, gap = 11
#   init_2_org = $00D400, header_data = 37 bytes, gap = 11
#   init_3_org = $01D000, header_data = 37 bytes, gap = 11
#   init_4_org = $E0D400, header_data = 37 bytes, gap = 11
#
# GQuit segments (GQuit.src):
#   seg_gldr: org_dummy_1=0x6800, pad_dummy_2=0x8200 → flat size = 0x8200-0x6800 = 0x1A00
#   seg_b0:   org_dummy_3=0x8200, pad_dummy_4=0x8400 → flat size = 0x8400-0x8200 = 0x200
#   seg_e1:   no valid end pad (org_dummy_8 has skip bug) → no padding needed
#   seg_e0:   no valid end pad (org_dummy_6 has skip bug) → no padding needed

GQUIT_FLAT_SIZES = {
    # (start_addr, end_addr) for segments with valid end padding
    'seg_gldr': (0x6800, 0x8200),   # pad to 0x8200
    'seg_b0':   (0x8200, 0x8400),   # pad to 0x8400
    # seg_e1 and seg_e0 have no end padding (skip/noskip bug prevents ORG eval)
}


# ---------------------------------------------------------------------------
# Golden extraction
# ---------------------------------------------------------------------------

def ensure_golden() -> bool:
    """Extract golden binaries from System Disk 2 if not already present."""
    paths = {
        'GS.OS':       '/System.Disk/System/GS.OS',
        'Start.GS.OS': '/System.Disk/System/Start.GS.OS',
        'P8':          '/System.Disk/System/P8',
        'Error.Msg':   '/System.Disk/System/Error.Msg',
        'ProDOS':      '/System.Disk/ProDOS',
    }
    os.makedirs(GOLDEN_DIR, exist_ok=True)
    all_ok = True
    for base, vol_path in paths.items():
        if _find_golden(base):
            continue
        if not os.path.exists(DISK2):
            print(f'ERROR: disk not found: {DISK2}', file=sys.stderr)
            return False
        rc = os.system(f'cadius EXTRACTFILE "{DISK2}" "{vol_path}" "{GOLDEN_DIR}/"')
        if rc != 0:
            print(f'WARNING: extraction failed for {vol_path}', file=sys.stderr)
            all_ok = False
    return all_ok


def _find_golden(prefix: str) -> str | None:
    """Return the first file in GOLDEN_DIR whose name starts with *prefix*."""
    try:
        for fn in os.listdir(GOLDEN_DIR):
            if fn.startswith(prefix):
                return os.path.join(GOLDEN_DIR, fn)
    except FileNotFoundError:
        pass
    return None


# ---------------------------------------------------------------------------
# Assembly helpers
# ---------------------------------------------------------------------------

def _assemble(src_path: str, extra_incs: list[str] | None = None) -> tuple[bytes, object]:
    """Assemble *src_path* and return (obj_bytes, Asm).

    Non-fatal pseudo-ops (pagesize, DataChk, etc.) are ignored; other errors
    are printed to stderr (do not abort the run).
    """
    incs = (extra_incs or []) + INCS
    a = _asm.assemble(src_path, incs)
    fatal = [e for e in a.errors
             if not any(x in e.lower() for x in _IGNORE_OPS)]
    if fatal:
        name = os.path.basename(src_path)
        print(f'  [{name}] {len(fatal)} non-ignored errors; first 2:',
              file=sys.stderr)
        for e in fatal[:2]:
            print(f'    {e}', file=sys.stderr)
    return _omf.emit(a), a


# ---------------------------------------------------------------------------
# Segment grouping
# ---------------------------------------------------------------------------

def _parse_obj_segs(obj_bytes: bytes) -> list[dict]:
    """Parse all OMF segments from *obj_bytes*.

    Returns list of dicts with keys: loadname, segname, length, org, recs, raw.
    """
    segs: list[dict] = []
    off = 0
    while off < len(obj_bytes):
        h = _omf.parse_header(obj_bytes[off:])
        bc = h['BYTECNT']
        if bc == 0:
            break
        seg_bytes = obj_bytes[off:off + bc]
        recs, _ = _omf.parse_records(
            seg_bytes, h['DISPDATA'], h.get('NUMLEN', 4), h.get('LABLEN', 0))
        segs.append({
            'loadname': h['LOADNAME'].decode('mac_roman', 'replace').strip(),
            'segname':  h['SEGNAME'].decode('mac_roman', 'replace').strip(),
            'length':   h['LENGTH'],
            'org':      h.get('ORG', 0) or 0,
            'recs':     recs,
            'raw':      seg_bytes,
        })
        off += bc
    return segs


def _make_groups(segs: list[dict]) -> dict[str, list[dict]]:
    """Group segments by source-order SEG ranges.

    A new group starts at each non-'main' loadname segment.  All subsequent
    'main' loadname segments belong to that group until the next named one.
    This replicates the MPW '@segname' group semantics that gsasm's single-PROC
    SEG directive doesn't produce (a known gsasm limitation).

    Returns {group_name_lower: [seg, ...]} preserving source order.
    """
    groups: dict[str, list[dict]] = {}
    current: str | None = None
    for seg in segs:
        ln = seg['loadname'].lower()
        if ln != 'main':
            current = ln
            groups.setdefault(current, [])
            groups[current].append(seg)
        elif current is not None:
            groups[current].append(seg)
    return groups


def _select_group(groups: dict[str, list[dict]], name: str) -> list[dict]:
    """Return the segment list for *name* (case-insensitive)."""
    key = name.lower()
    if key in groups:
        return groups[key]
    # Partial match
    for k, v in groups.items():
        if k.startswith(key):
            return v
    raise KeyError(f'Group {name!r} not found.  Have: {sorted(groups)}')


# ---------------------------------------------------------------------------
# Code-image extraction
# ---------------------------------------------------------------------------

def _code_image(linked_bytes: bytes) -> bytes:
    """Extract the CONST/LCONST code image from a linked OMF result."""
    img = bytearray()
    off = 0
    while off < len(linked_bytes):
        h = _omf.parse_header(linked_bytes[off:])
        bc = h['BYTECNT']
        if bc == 0:
            break
        recs, _ = _omf.parse_records(
            linked_bytes[off:off + bc], h['DISPDATA'],
            h.get('NUMLEN', 4), h.get('LABLEN', 0))
        img += b''.join(r[2] for r in recs if r[1] in ('CONST', 'LCONST'))
        off += bc
    return bytes(img)


def _link_groups(group_segs: list[dict]) -> bytes:
    """Link selected segment dicts into a flat code image."""
    combined = b''.join(s['raw'] for s in group_segs)
    linked = _lnk.link([(combined, None)], opts={'merge': True})
    return _code_image(linked)


# ---------------------------------------------------------------------------
# Flat-binary construction helpers
#
# All kernel segments follow one of two layouts:
#
# Layout A (SCM segs 1-5, b00segr, be0segr, cache, init1-4):
#   bytes 0 .. (header_length - 1)  = header proc data + zero-fill gap
#   bytes header_length ..           = segment content
#   total = header_length (48) + content_length
#
# Layout B (GQuit seg_gldr and seg_b0): content + zero-fill gap at end
#   content from org_start to org_end — padded with zeros to org_end
#   total = org_end - org_start
#
# Layout C (GQuit seg_e1, seg_e0, terminator): content only — no header, no gap
#
# The gsasm 'PROC ORG expr, noskip' bug prevents ORG evaluation for procs whose
# ORG has a ', noskip' suffix.  This affects SCM header procs and GQuit pad procs.
# The harness compensates by:
#   Layout A: gap = header_length - len(header_data_bytes) (always 48 - N bytes)
#   Layout B: end_gap = org_end - (org_start + len(content_bytes))
#   Layout C: no compensation needed
# ---------------------------------------------------------------------------

def _build_header_content(header_segs: list[dict],
                           content_segs: list[dict],
                           end_segs: list[dict] | None = None) -> bytes:
    """Build a Layout-A flat binary: header_data + zero_gap + content.

    The gap is computed as header_length (48) minus the actual header data size.
    This compensates for the gsasm PROC ORG noskip evaluation bug.
    """
    hdr_bytes = _link_groups(header_segs)
    gap = max(0, SCM_HEADER_LENGTH - len(hdr_bytes))
    content_bytes = _link_groups(content_segs)
    end_bytes = _link_groups(end_segs) if end_segs else b''
    return hdr_bytes + bytes(gap) + content_bytes + end_bytes


def _build_with_end_padding(code_bytes: bytes,
                             seg_start: int,
                             seg_end: int) -> bytes:
    """Build a Layout-B flat binary: code_bytes + zero_fill to seg_end.

    Compensates for the gsasm PROC ORG skip/noskip bug by hard-coding the
    end address from the source EQUs.
    """
    end_gap = max(0, seg_end - (seg_start + len(code_bytes)))
    return code_bytes + bytes(end_gap)


# ---------------------------------------------------------------------------
# SCM segment build
# ---------------------------------------------------------------------------

def _build_scm_segments() -> dict[str, bytes] | None:
    """Assemble all kernel sources and produce per-segment flat binaries.

    Returns {output_name: bytes} for scm.bin through scm.bin.17, or None on
    fatal assembly error.
    """
    out: dict[str, bytes] = {}

    # ---- SCM proper (segs 1-5) — Layout A: header + gap + content ----
    try:
        scm_src = f'{GS}/OS/SCM/SCM.src'
        scm_obj, scm_asm = _assemble(scm_src)
        scm_segs = _parse_obj_segs(scm_obj)
        scm_groups = _make_groups(scm_segs)
    except Exception as exc:
        print(f'  FAIL: SCM assembly: {exc}', file=sys.stderr)
        return None

    # Each tuple: (output_name, header_group, content_group, end_group)
    scm_bin_recipes = [
        ('scm.bin',   'start_seg0', 'oscall_seg',  'end_seg0'),
        ('scm.bin.2', 'start_seg1', 'misc_seg',    'end_seg1'),
        ('scm.bin.3', 'start_seg2', 'scm_main',    'end_seg2'),
        ('scm.bin.4', 'start_seg3', 'system_svc',  'end_seg3'),
        ('scm.bin.5', 'start_seg4', 'bank_e1',     'end_seg4'),
    ]
    for out_name, hdr_g, content_g, end_g in scm_bin_recipes:
        try:
            hdr_segs     = _select_group(scm_groups, hdr_g)
            content_segs = _select_group(scm_groups, content_g)
            try:
                end_segs = _select_group(scm_groups, end_g)
            except KeyError:
                end_segs = None
            out[out_name] = _build_header_content(hdr_segs, content_segs, end_segs)
        except Exception as exc:
            print(f'  FAIL {out_name}: {exc}', file=sys.stderr)
            out[out_name] = b''

    # scm.bin.17 = terminator (Layout C: content only)
    try:
        term_segs = _select_group(scm_groups, 'terminator')
        out['scm.bin.17'] = _link_groups(term_segs)
    except Exception as exc:
        print(f'  FAIL scm.bin.17: {exc}', file=sys.stderr)
        out['scm.bin.17'] = b''

    # ---- B00segr / scm.bin.6 — Layout A: header + gap + content ----
    # Recipe from make.os: b00segr.s.obj + bank0.obj + b00segr.e.obj
    # b00segr_header PROC org b00segr_org-header_length (= $AA00 - $30 = $A9D0)
    # B00segr.s has all 'main' loadnames; use first-seg-is-header split.
    try:
        b00s_obj, _ = _assemble(f'{GS}/OS/BankZero/B00segr.s.src')
        bank0_obj, _ = _assemble(f'{GS}/OS/BankZero/bank0.dispatcher.src')
        b00e_obj, _  = _assemble(f'{GS}/OS/BankZero/B00segr.e.src')
        b00s_segs  = _parse_obj_segs(b00s_obj)   # [B00SEGR_HEADER, D_B00SEGR_DUMMY]
        bank0_segs = _parse_obj_segs(bank0_obj)  # all bank0 content procs
        b00e_segs  = _parse_obj_segs(b00e_obj)   # [B00SEGR_END, B00SEGR0_OVF]
        # B00SEGR_HEADER is b00s_segs[0] (37 bytes + 11-byte gap = 48-byte header section)
        # content = D_B00SEGR_DUMMY (empty) + bank0 + b00e
        hdr_segs_b00     = b00s_segs[:1]                    # header proc
        content_segs_b00 = b00s_segs[1:] + bank0_segs + b00e_segs  # content
        out['scm.bin.6'] = _build_header_content(
            hdr_segs_b00, content_segs_b00)
    except Exception as exc:
        print(f'  FAIL scm.bin.6: {exc}', file=sys.stderr)
        out['scm.bin.6'] = b''

    # ---- BE0segr / scm.bin.7 — Layout A: header + gap + content ----
    # Recipe from make.os: be0segr.s.obj + device.dispatcher.obj + be0segr.e.obj
    # be0segr_header PROC org be0segr_org-header_length (= $E0E000 - $30 = $E0DFD0)
    # BE0segr.s has all 'main' loadnames; use first-seg-is-header split.
    try:
        be0s_obj, _ = _assemble(f'{GS}/OS/DeviceDispatcher/be0segr.s.src')
        devd_obj, _ = _assemble(f'{GS}/OS/DeviceDispatcher/Device.Dispatcher.Src')
        be0e_obj, _ = _assemble(f'{GS}/OS/DeviceDispatcher/BE0Segr.e.Src')
        be0s_segs = _parse_obj_segs(be0s_obj)   # [BE0SEGR_HEADER, D_BE0SEGR_DUMMY]
        devd_segs = _parse_obj_segs(devd_obj)   # device dispatcher content procs
        be0e_segs = _parse_obj_segs(be0e_obj)   # [BE0SEGR_END, BE0SEGR0_OVF]
        hdr_segs_be0     = be0s_segs[:1]                    # header proc
        content_segs_be0 = be0s_segs[1:] + devd_segs + be0e_segs  # content
        out['scm.bin.7'] = _build_header_content(
            hdr_segs_be0, content_segs_be0)
    except Exception as exc:
        print(f'  FAIL scm.bin.7: {exc}', file=sys.stderr)
        out['scm.bin.7'] = b''

    # ---- GQuit / scm.bin.8..11 ----
    # linkOS order: gquit.1=seg_gldr, gquit.2=seg_b0, gquit.3=seg_e1, gquit.4=seg_e0
    # seg_gldr: Layout B (end pad to 0x8200), seg_b0: Layout B (end pad to 0x8400)
    # seg_e1, seg_e0: Layout C (no padding)
    try:
        gquit_obj, gquit_asm = _assemble(f'{GS}/OS/GQuit/GQuit.src')
        gq_segs = _parse_obj_segs(gquit_obj)
        gq_groups = _make_groups(gq_segs)

        for out_name, gname in [
            ('scm.bin.8',  'seg_gldr'),
            ('scm.bin.9',  'seg_b0'),
            ('scm.bin.10', 'seg_e1'),   # no end padding (Layout C)
            ('scm.bin.11', 'seg_e0'),   # no end padding (Layout C)
        ]:
            try:
                sel = _select_group(gq_groups, gname)
                code_bytes = _link_groups(sel)
                if gname in GQUIT_FLAT_SIZES:
                    seg_start, seg_end = GQUIT_FLAT_SIZES[gname]
                    out[out_name] = _build_with_end_padding(
                        code_bytes, seg_start, seg_end)
                else:
                    out[out_name] = code_bytes
            except Exception as exc:
                print(f'  FAIL {out_name}: {exc}', file=sys.stderr)
                out[out_name] = b''

    except Exception as exc:
        print(f'  FAIL GQuit: {exc}', file=sys.stderr)
        for n in ('scm.bin.8', 'scm.bin.9', 'scm.bin.10', 'scm.bin.11'):
            out.setdefault(n, b'')

    # ---- Cache / scm.bin.12 — Layout A: header + gap + content ----
    # cashseg_org = $A280, header_data = 41 bytes, gap = 7 bytes
    # Note: Cache.Src uses no SEG directives; all segments have loadname='main'.
    # _make_groups() returns {} for this file.  Use direct first-seg-is-header split.
    try:
        cache_obj, cache_asm = _assemble(f'{GS}/OS/CacheManager/Cache.Src')
        cache_segs = _parse_obj_segs(cache_obj)
        # CASHSEG_HEADER is the first segment (has ORG set to cashseg_org-header_length)
        hdr_segs_cache  = cache_segs[:1]   # CASHSEG_HEADER (41 bytes, gap=7)
        rest_segs_cache = cache_segs[1:]   # CASHSEG_DUMMY (empty) + content procs
        out['scm.bin.12'] = _build_header_content(
            hdr_segs_cache, rest_segs_cache)
    except Exception as exc:
        print(f'  FAIL scm.bin.12: {exc}', file=sys.stderr)
        out['scm.bin.12'] = b''

    # ---- Init 1..4 / scm.bin.13..16 — Layout A: header + gap + content ----
    # All Init source files have all segments with loadname='main' (no SEG directives).
    # INIT_N_HEADER is always the first segment (has an ORG: init_N_org - header_length).
    # INIT_N_START is the second segment (empty pad proc at init_N_org).
    # Remaining segments are the actual code.
    # header_data = 37 bytes, gap = 11 bytes, total header_section = 48 bytes.
    for n, fname in [(13, 'Init1.Src'), (14, 'Init2.Src'),
                     (15, 'Init3.Src'), (16, 'Init4.Src')]:
        try:
            init_obj, init_asm = _assemble(
                f'{GS}/OS/InitManager/{fname}')
            init_segs = _parse_obj_segs(init_obj)
            # INIT_N_HEADER is the first segment (has a non-zero ORG)
            hdr_segs_init  = init_segs[:1]   # INIT_N_HEADER
            rest_segs_init = init_segs[1:]   # INIT_N_START (empty) + content procs
            out[f'scm.bin.{n}'] = _build_header_content(
                hdr_segs_init, rest_segs_init)
        except Exception as exc:
            print(f'  FAIL scm.bin.{n}: {exc}', file=sys.stderr)
            out[f'scm.bin.{n}'] = b''

    return out


# ---------------------------------------------------------------------------
# Error.Msg build
# ---------------------------------------------------------------------------

def _build_error_msg() -> bytes:
    """Assemble english.src and produce the OMF code image.

    Recipe from make.error.msg:
        asmiigs english.src -> english.obj
        linkiigs -x english.obj -o Error.Msg -t $bc

    The golden Error.Msg is a single-segment plain OMF; we compare LCONST images.
    """
    src = f'{GS}/OS/ErrorMessages/English.src'
    obj, a = _assemble(src)
    linked = _lnk.link([(obj, a)], opts={'merge': True})
    return _code_image(linked)


# ---------------------------------------------------------------------------
# prodos build (duplicated from probootcheck.py for completeness)
# ---------------------------------------------------------------------------

def _build_prodos() -> bytes:
    """Assemble ProBoot.src and flatten at org=$2000."""
    boot_src = f'{GS}/Boot/ProBoot.src'
    # ProBoot uses a slightly different include path (all GS.OS subdirs)
    incs_boot = [d for d, _, _ in os.walk(GS)]
    a = _asm.assemble(boot_src, incs_boot)
    obj = _omf.emit(a)
    return _makebin.makebin(obj, 0x2000)


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------

def _compare(mine: bytes, golden: bytes, name: str,
             show_diff: bool = False) -> tuple[int, int]:
    """Compare and print a summary line.  Returns (matching_bytes, compared_len)."""
    n   = min(len(mine), len(golden))
    m   = sum(1 for i in range(n) if mine[i] == golden[i])
    pct = (100 * m // n) if n else 0
    exact = m == n and len(mine) == len(golden)
    flag  = 'EXACT' if exact else f'{pct}%'

    size_note = (f'  (gsasm={len(mine)} golden={len(golden)})'
                 if len(mine) != len(golden) else '')
    print(f'  {name:<22} {m:>6}/{n:<6}  {flag}{size_note}')

    if show_diff and not exact:
        diffs = [i for i in range(n) if mine[i] != golden[i]]
        if diffs:
            pos = diffs[0]
            print(f'    first diff @ {pos:#06x}: '
                  f'gsasm={mine[pos]:02x} golden={golden[pos]:02x}')
            w = 8
            print(f'    gsasm:  {bytes(mine[max(0,pos-4):pos+w]).hex()}')
            print(f'    golden: {golden[max(0,pos-4):pos+w].hex()}')

    return m, n


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    show_diff = '--diff' in sys.argv
    single    = next((a for a in sys.argv[1:] if not a.startswith('-')), None)

    print('kernelcheck.py — M6 GS/OS kernel byte-match')
    print('=' * 64)

    if not ensure_golden():
        print('Cannot locate golden binaries.', file=sys.stderr)
        return 1

    results: list[tuple[str, int, int, str]] = []

    # ------------------------------------------------------------------
    # prodos (baseline — also in probootcheck.py)
    # ------------------------------------------------------------------
    prodos_path = _find_golden('ProDOS')
    if prodos_path:
        prodos_mine   = _build_prodos()
        prodos_golden = open(prodos_path, 'rb').read()
        m, n = _compare(prodos_mine, prodos_golden, 'prodos', show_diff)
        results.append(('prodos', m, n, 'makebin(ProBoot.src, org=$2000)'))
    else:
        print('  prodos: golden not found, skipping.')

    print()

    # ------------------------------------------------------------------
    # Build all SCM segments
    # ------------------------------------------------------------------
    print('Building SCM segments...')
    scm_bins = _build_scm_segments()
    if scm_bins is None:
        print('FATAL: SCM segment build failed.', file=sys.stderr)
        return 1

    seg_order = (['scm.bin'] +
                 [f'scm.bin.{n}' for n in range(2, 18)])
    print('  Segment sizes (bytes):')
    for k in seg_order:
        if k in scm_bins:
            print(f'    {k:<14} {len(scm_bins[k]):>6}')
    print()

    # ------------------------------------------------------------------
    # Start.GS.OS  = cat(scm.bin.8..11)
    # ------------------------------------------------------------------
    print('--- Start.GS.OS ---')
    start_parts = ['scm.bin.8', 'scm.bin.9', 'scm.bin.10', 'scm.bin.11']
    start_mine  = _makebin.catenate([scm_bins.get(k, b'') for k in start_parts])
    start_path  = _find_golden('Start.GS.OS')
    if start_path:
        start_g = open(start_path, 'rb').read()
        m, n = _compare(start_mine, start_g, 'Start.GS.OS', show_diff)
        results.append(('Start.GS.OS', m, n,
                        'catenate(scm.bin.8, .9, .10, .11)'))
    else:
        print('  golden not found.')
    print()

    # ------------------------------------------------------------------
    # GS.OS  = Loader.bin(excluded) ++ cat(scm.bin, .2..7, .12..17)
    # ------------------------------------------------------------------
    print('--- GS.OS (SCM portion; Loader.bin excluded) ---')
    gsos_parts = (['scm.bin'] +
                  [f'scm.bin.{n}' for n in [2, 3, 4, 5, 6, 7, 12, 13, 14, 15, 16, 17]])
    gsos_scm_mine = _makebin.catenate([scm_bins.get(k, b'') for k in gsos_parts])
    gsos_path = _find_golden('GS.OS')
    if gsos_path:
        gsos_g     = open(gsos_path, 'rb').read()
        gsos_g_scm = gsos_g[LOADER_BIN_SIZE:]   # strip Loader.bin
        m, n = _compare(gsos_scm_mine, gsos_g_scm, 'GS.OS (SCM only)', show_diff)
        results.append(('GS.OS (SCM only)', m, n,
                        'Loader.bin(excl.) ++ cat(scm.bin,{2..7,12..17})'))
        print(f'  (Loader.bin = first {LOADER_BIN_SIZE} bytes of golden, '
              f'excluded — Loader.a crashes gsasm)')
    else:
        print('  golden not found.')
    print()

    # ------------------------------------------------------------------
    # Error.Msg
    # ------------------------------------------------------------------
    print('--- Error.Msg ---')
    try:
        errmsg_mine = _build_error_msg()
        errmsg_path = _find_golden('Error.Msg')
        if errmsg_path:
            errmsg_raw = open(errmsg_path, 'rb').read()
            errmsg_g   = _code_image(errmsg_raw)  # golden is OMF; extract LCONST
            m, n = _compare(errmsg_mine, errmsg_g, 'Error.Msg', show_diff)
            results.append(('Error.Msg', m, n,
                            'linkiigs(english.obj) plain OMF'))
        else:
            print('  golden not found.')
    except Exception as exc:
        print(f'  FAIL: {exc}', file=sys.stderr)
    print()

    # ------------------------------------------------------------------
    # P8 (mlisrc PROCONE only — driver overlays not in scope here)
    # ------------------------------------------------------------------
    print('--- P8 (mlisrc/PROCONE; driver overlays excluded) ---')
    p8_path = _find_golden('P8')
    if p8_path:
        src_mli = f'{GS}/P8/MliSrc.aii'
        try:
            p8_obj, p8_asm = _assemble(src_mli, extra_incs=[f'{GS}/P8'])
            p8_segs = _parse_obj_segs(p8_obj)
            p8_groups = _make_groups(p8_segs)

            # PROCONE is the first named group (at ORG $2000)
            try:
                procone_segs = _select_group(p8_groups, 'PROCONE')
            except KeyError:
                procone_segs = p8_segs  # fall back to all segs

            p8_mine = _link_groups(procone_segs)
            p8_g = open(p8_path, 'rb').read()
            # The golden P8 file starts at address $2000 (PROCONE base).
            # Compare only the first len(p8_mine) bytes.
            p8_g_slice = p8_g[:len(p8_mine)]
            m, n = _compare(p8_mine, p8_g_slice, 'P8 (PROCONE only)', show_diff)
            results.append(('P8 (PROCONE)', m, n,
                            'linkiigs(mlisrc PROCONE, org=$2000)'))
            print('  (Driver overlays excluded; cclock/tclock/ram/sel/xrwtot '
                  'not compared.)')
        except Exception as exc:
            print(f'  FAIL: {exc}', file=sys.stderr)
    else:
        print('  golden not found.')
    print()

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    print('=' * 64)
    print('Summary')
    print(f'  {"Output":<22} {"match":>8}  {"packaging"}')
    print('-' * 64)
    total_m = total_n = 0
    for name, m, n, pkg in results:
        pct   = (100 * m // n) if n else 0
        exact = 'EXACT' if m == n else f'{pct}%'
        print(f'  {name:<22} {m:>6}/{n:<6} {exact:>6}  {pkg}')
        total_m += m
        total_n += n
    if total_n:
        tot_pct = 100 * total_m // total_n
        print('-' * 64)
        print(f'  {"TOTAL":<22} {total_m:>6}/{total_n:<6} {tot_pct:>5}%')

    print()
    print('Known gaps (not fixed — reportable):')
    print('  1. lda #^Label: bank-byte immediate emits 0x00 in gsasm (SUPER type-27')
    print('     record unimplemented).  Affects ~25% of GS.OS and ~14% of Start.GS.OS.')
    print('  2. DC.W label-*: PC-relative offset expressions produce wrong LEXPR values.')
    print('     gsasm asm.py emits e.g. LEXPR(sym+lit) where the literal is wrong.')
    print('     Affects Error.Msg offset table (122 DC.W entries = 244 bytes wrong);')
    print('     cascades to effectively the whole file (match: ~22%).')
    print('  3. DC.W seg_N_end-seg_N_start: header proc links separately from content,')
    print('     so seg_N_end is unresolved (=0); ~2 bytes wrong per SCM header (~24 total).')
    print('  4. Init1.Src Record/EndR: gsasm does not support Record/EndR pseudo-ops;')
    print('     64 bytes of data missing from scm.bin.13.')
    print('  5. PROC ORG \', noskip\' parsing: gsasm asm.py evaluate() receives')
    print('     \'expr, noskip\' and returns None.  Header ORG = None; gap filled')
    print('     by harness using hard-coded header_length=$30.  Not a core fix.')
    print('  6. SEG directive semantics: gsasm pending_loadname consumed after')
    print('     one PROC; AsmIIgs keeps until next SEG.  Harness works around')
    print('     via source-order group selection (no core change needed).')
    print('  7. Loader.a crashes gsasm: complex IF/WHILE macros in Loader.Macros')
    print('     cause an uncaught error.  Loader.bin excluded from GS.OS comparison.')
    print('  8. Init2/Init3: include E16.Control / E16.Window not in GS.OS tree.')
    print('  9. mlisrc.aii: include M16.UTIL / e16.memory not in GS.OS tree.')
    print(' 10. &ord builtin: 346 non-fatal errors in SCM.src from unknown builtin.')
    print('     Assembly continues; bytes are emitted as if &ord returned 0.')

    return 0


if __name__ == '__main__':
    sys.exit(main())
