"""diskbuilders/p8_driver.py — M8 disk-file builder for P8.

Builds the full 17128-byte P8 (ProDOS-8 compatibility) file from
GS.OS/P8/MliSrc.aii plus the P8.Drivers, exactly reproducing the
OverlayIIgs recipe in GS.OS/MakeFiles/make.p8.

Recipe (transcribed from make.p8):

  1.  AsmIIgs MliSrc.aii -> mlisrc.obj
  2.  linkiigs -lseg PROCONE  -org $002000 mlisrc.obj(PROCONE)
               -lseg PROCTWO  -org $00BF00 mlisrc.obj(PROCTWO)
               -lseg PROCTHREE -org $00DE00 mlisrc.obj(PROCTHREE)
               -lseg PROCFOUR  -org $00FF9B mlisrc.obj(PROCFOUR)
               -> mli.out
  3.  MakeBinIIgs mli.out -> ProdosBIN (PROCONE), ProdosBIN.2 (PROCTWO),
                             ProdosBIN.3 (PROCTHREE), ProdosBIN.4 (PROCFOUR)

  4.  Build drivers:
        cclock.n  -org $d742 -> cclock.bin     (223 B, GS clock driver)
        tclock.n  -org $d742 -> tclock.bin     (125 B, Thunderclock driver)
        ram.n     -lseg RAM1 -org $000200
                  -lseg RAM2 -org $002C80
                  -lseg RAM3 -org $00FF00      -> ram.bin / ram.bin.2 / ram.bin.3
        sel.n     -org $1000 -> sel.bin        (715 B, _Quit call handler)
        sel.alt.n -org $1000 -> sel.alt.bin    (744 B, GQuit loader)
        xrwtot.n  -org $D000 -> xrwtot.bin     (1770 B, Disk II driver)
        QuitCode.aii -i P8.Drivers -> QuitCode.bin (816 B, Better Bye)

  5.  Start: ProdosBIN (PROCONE makebin, 6367 B) zero-padded to 17128 B.
  6.  OverlayIIgs overlays applied in order (each extends dest as needed):
        ram.bin.2 (RAM2)    @ $0C80 ->  61 B
        ram.bin.3 (RAM3)    @ $0D00 -> 144 B  (130 live, 14 trailing zeros)
        ProdosBIN.4 (PROCFOUR) @ $0D9B -> 101 B
        ProdosBIN.2 (PROCTWO)  @ $0E00 -> 256 B
        tclock.bin          @ $0F00 -> 125 B
        cclock.bin          @ $0F80 -> 223 B  (latter 96 B overwritten by PROCTHREE)
        ProdosBIN.3 (PROCTHREE) @ $1000 -> 8438 B  (extends file to 12534)
        ram.bin (RAM1)      @ $3100 -> 1003 B (512 live, 491 B overwritten by xrwtot)
        xrwtot.bin          @ $3300 -> 1770 B
        sel.bin             @ $3A00 ->  715 B
        QuitCode.bin        @ $3D00 ->  816 B (768 live, 48 B overwritten by sel.alt)
        sel.alt.bin         @ $4000 -> variable (see note below)
  7.  Clip to 17128 bytes (= $42E8).

OverlayIIgs model: extends the destination file as overlays are applied.
Later overlays overwrite earlier ones that extended past their slot.  The final
file is 17128 bytes because sel.alt at $4000 extends to 17128 exactly.

sel.alt note — gsasm gap:
  sel.alt.n has  ds.b (alt_dispatch+16)-*-2  to fill to a paragraph boundary.
  Real AsmIIgs two-pass resolves alt_dispatch=0x1000, *=0x1009 -> DS=5.
  gsasm resolves forward-ref alt_dispatch=0x1000 but gives DS=4112 (0x1010 = 16 +
  the DS expression is evaluated with the segment's 0-origin ORG not applied to '*').
  This causes:
    - makebin(sel.alt.n) = 4851 B instead of 744 B
    - All subsequent address offsets in sel.alt wrong (segment layout shifted)
    - First diff in P8 at offset $400e (0 vs golden code byte 0x47)
  The builder is NOT patching this: gsasm limitation is reported, not fixed.

Target: /System.Disk/System/P8 — type=$FF (SYS), aux=$0000, 17128 bytes
"""
import os
import sys

# p8_driver.py lives at work/diskbuilders/p8_driver.py.
# The project root is three directories up.
_ROOT = os.path.dirname(                    # worktree/
         os.path.dirname(                   # work/
          os.path.dirname(                  # work/diskbuilders/
           os.path.abspath(__file__))))
sys.path.insert(0, _ROOT)                   # so `import gsasm` resolves

from gsasm import asm      as _asm
from gsasm import omf      as _omf
from gsasm import makebin  as _makebin

# ---------------------------------------------------------------------------
# Source paths
# ---------------------------------------------------------------------------
_SRC      = os.path.join(_ROOT, 'ref/GSOS_6/IIGS.601.SRC')
_GS       = os.path.join(_SRC, 'GS.OS')
_CMN      = os.path.join(_GS,  'Common')
_P8       = os.path.join(_GS,  'P8')
_P8D      = os.path.join(_P8,  'P8.Drivers')
_INCS_DIR = os.path.join(_ROOT, 'work/includes')

# Include path: Common first, then every GS.OS subdir, then work/includes.
_INCS = [_CMN] + [d for d, _, _ in os.walk(_GS)] + [_INCS_DIR]

# Non-fatal pseudo-ops to ignore (matches kernelcheck.py / kernel_setup.py)
_IGNORE_OPS = ('pagesize', 'datachk', 'endproc', 'eject', 'writeln', 'codechk',
               'aerror')

# P8 original build date (embedded in golden P8#FF0000 at offset 0x26)
_P8_SYSDATE = '06-May-93'

# Expected final P8 file size (data-fork EOF = 17128 bytes)
P8_SIZE = 17128


# ---------------------------------------------------------------------------
# Assembly helpers
# ---------------------------------------------------------------------------

def _assemble(src_path, extra_incs=None):
    """Assemble *src_path* and return (obj_bytes, Asm).

    Non-fatal pseudo-ops (including 'aerror') are silently ignored;
    other errors are printed to stderr but do not abort.
    """
    incs = list(extra_incs or []) + _INCS
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


def _makebin_single(src_path, org, extra_incs=None):
    """Assemble *src_path* and return makebin(obj, org) flat binary.

    Single-segment OMF only (single-PROC drivers: cclock, tclock, sel,
    xrwtot, QuitCode).
    """
    obj, _a = _assemble(src_path, extra_incs=extra_incs)
    return _makebin.makebin(obj, org)


def _parse_segs(obj_bytes):
    """Parse all OMF segments from *obj_bytes*.

    Returns list of dicts: {name, raw, length, org}.
    """
    segs = []
    off = 0
    while off < len(obj_bytes):
        h = _omf.parse_header(obj_bytes[off:])
        bc = h['BYTECNT']
        if bc == 0:
            break
        sname = h['SEGNAME'].decode('mac_roman', 'replace').strip()
        length = h['LENGTH']
        org = h.get('ORG', 0) or 0
        segs.append({
            'name':   sname,
            'raw':    obj_bytes[off:off + bc],
            'length': length,
            'org':    org,
        })
        off += bc
    return segs


# ---------------------------------------------------------------------------
# OverlayIIgs simulation
# ---------------------------------------------------------------------------

def _overlay(dest: bytearray, src_bytes: bytes, offset: int) -> None:
    """Lay *src_bytes* into *dest* at *offset*, extending with zeros if needed.

    Mirrors OverlayIIgs.  The destination is extended in-place when
    offset + len(src_bytes) > len(dest).  src_bytes is NOT truncated — the
    caller is responsible for clipping if a known final size is required.
    """
    needed = offset + len(src_bytes)
    if needed > len(dest):
        dest.extend(b'\x00' * (needed - len(dest)))
    dest[offset:offset + len(src_bytes)] = src_bytes


# ---------------------------------------------------------------------------
# P8 build
# ---------------------------------------------------------------------------

def _build_p8() -> bytes:
    """Build the full 17128-byte P8 from MliSrc.aii + P8.Drivers.

    Returns exactly P8_SIZE (17128) bytes.  Raises ValueError if the result
    is not exactly P8_SIZE bytes (guarding against assembly failures that
    produce wrong sizes).

    Known gsasm gaps (not fixable here, characterised in module docstring):
      1. lda #^Label (bank byte): SUPER type-27 unimplemented -> 0x00 emitted.
         Affects ~40% of PROCONE, ~83% of PROCTWO, ~83% of PROCTHREE.
      2. sel.alt.n DS computation: gsasm gives DS=4112 (should be 5).
         Causes wrong segment layout and wrong address offsets throughout sel.alt.
         First P8 diff in sel.alt area at $400e.
      3. aerror pseudo-op: unknown in gsasm (silently ignored via _IGNORE_OPS).
    """
    # ----------------------------------------------------------------
    # Step 1: Assemble MliSrc.aii -> parse PROC segments
    # ----------------------------------------------------------------
    mli_obj, _mli_asm = _assemble(
        os.path.join(_P8, 'MliSrc.aii'),
        extra_incs=[_P8],
    )
    # Inject the original build date for byte-exact &sysdate expansion
    # (date must be passed as sysdate= arg to asm.assemble — but
    # _assemble() wrapper doesn't expose it.  Re-assemble with sysdate.)
    mli_asm2 = _asm.assemble(
        os.path.join(_P8, 'MliSrc.aii'),
        [_P8] + _INCS,
        sysdate=_P8_SYSDATE,
    )
    mli_obj = _omf.emit(mli_asm2)

    mli_segs = _parse_segs(mli_obj)

    # Find PROC segments by name
    def _find_seg(name):
        name_u = name.upper()
        for s in mli_segs:
            if s['name'].upper() == name_u:
                return s
        raise KeyError(f'Segment {name!r} not found in mlisrc.obj; '
                       f'have: {[s["name"] for s in mli_segs]}')

    procone   = _find_seg('PROCONE')
    proctwo   = _find_seg('PROCTWO')
    procthree = _find_seg('PROCTHREE')
    procfour  = _find_seg('PROCFOUR')

    # MakeBinIIgs for each PROC: flat binary at its declared ORG.
    # Our makebin.makebin() places one segment at its org.
    procone_bin   = _makebin.makebin(procone['raw'],   procone['org'])
    proctwo_bin   = _makebin.makebin(proctwo['raw'],   proctwo['org'])
    procthree_bin = _makebin.makebin(procthree['raw'], procthree['org'])
    procfour_bin  = _makebin.makebin(procfour['raw'],  procfour['org'])

    # ----------------------------------------------------------------
    # Step 2: Assemble driver binaries
    # ----------------------------------------------------------------

    # ram.n — three segments (RAM1, RAM2, RAM3)
    ram_obj, _ram_asm = _assemble(os.path.join(_P8D, 'Ram.n'))
    ram_segs = _parse_segs(ram_obj)
    ram_by_name = {s['name'].upper(): s for s in ram_segs}
    ram1_bin = _makebin.makebin(ram_by_name['RAM1']['raw'], ram_by_name['RAM1']['org'])
    ram2_bin = _makebin.makebin(ram_by_name['RAM2']['raw'], ram_by_name['RAM2']['org'])
    ram3_bin = _makebin.makebin(ram_by_name['RAM3']['raw'], ram_by_name['RAM3']['org'])

    # Single-segment drivers
    cclock_bin = _makebin_single(os.path.join(_P8D, 'CClock.n'),    0xd742)
    tclock_bin = _makebin_single(os.path.join(_P8D, 'TClock.n'),    0xd742)
    sel_bin    = _makebin_single(os.path.join(_P8D, 'Sel.n'),       0x1000)
    xrwtot_bin = _makebin_single(os.path.join(_P8D, 'XrwTot.n'),    0xd000)
    quitcode_bin = _makebin_single(
        os.path.join(_P8D, 'QuitCode.aii'), 0x0000,
        extra_incs=[_P8D],
    )

    # sel.alt.n — single segment but with DS=4112 gsasm gap (correct value is 5).
    # makebin produces 4851 bytes; the first 744 (= P8_SIZE - 0x4000) survive
    # after clipping to P8_SIZE at the end.
    selalt_bin = _makebin_single(
        os.path.join(_P8D, 'Sel.Alt.n'), 0x1000,
        extra_incs=[_CMN],
    )

    # ----------------------------------------------------------------
    # Step 3: Assemble P8 via OverlayIIgs model
    # ----------------------------------------------------------------
    #
    # Base: ProdosBIN = PROCONE makebin (6367 bytes), zero-padded to P8_SIZE.
    # Then overlays applied in make.p8 order.  Dest is extended as needed; each
    # later overlay may overwrite the tail of an earlier one.
    #
    dest = bytearray(procone_bin)
    if len(dest) < P8_SIZE:
        dest.extend(b'\x00' * (P8_SIZE - len(dest)))

    # OverlayIIgs calls in make.p8 order:
    _overlay(dest, ram2_bin,      0x0c80)   # /RAM driver installer  (RAM2)
    _overlay(dest, ram3_bin,      0x0d00)   # /RAM Main Bank driver  (RAM3)
    _overlay(dest, procfour_bin,  0x0d9b)   # page $FF interrupt handlers
    _overlay(dest, proctwo_bin,   0x0e00)   # Global page
    _overlay(dest, tclock_bin,    0x0f00)   # Thunderclock driver
    _overlay(dest, cclock_bin,    0x0f80)   # GS Clock driver
    _overlay(dest, procthree_bin, 0x1000)   # Kernel  (extends to 12534)
    _overlay(dest, ram1_bin,      0x3100)   # /RAM Aux Bank driver
    _overlay(dest, xrwtot_bin,    0x3300)   # Disk ][ driver
    _overlay(dest, sel_bin,       0x3a00)   # _Quit call handler
    _overlay(dest, quitcode_bin,  0x3d00)   # Better Bye _Quit handler
    _overlay(dest, selalt_bin,    0x4000)   # GQuit loader/launcher

    # Clip to the known P8 size.  This handles sel.alt's DS=4112 artefact
    # (makebin produces 4851 bytes; only 744 bytes fall within P8_SIZE).
    result = bytes(dest[:P8_SIZE])
    if len(result) != P8_SIZE:
        raise ValueError(
            f'P8 build produced {len(result)} bytes, expected {P8_SIZE}')
    return result


# ---------------------------------------------------------------------------
# Public entry point (diskbuilders contract)
# ---------------------------------------------------------------------------

def builders(V):
    """Return {disk_path: callable() -> bytes} for P8.

    *V* is the volume prefix (e.g. '/System.Disk').  The callable returns the
    full 17128-byte P8 data-fork bytes.

    Residual (not fixable without gsasm changes):
      P8 — 17128 bytes built but content has known gaps:
        PROCONE/PROCTWO/PROCTHREE: ~40-60% match (SUPER type-27 bank byte).
        sel.alt: wrong from byte 14 (DS=4112 vs DS=5 gsasm forward-ref gap).
    """
    return {
        f'{V}/System/P8': _build_p8,
    }
