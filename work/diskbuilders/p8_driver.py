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

The result is BYTE-EXACT against the golden P8#FF0000 (work/p8check.py).  The
four MLI PROC segments are linked together (makebin_segments, so cross-segment
ENTRY references resolve) and every driver is byte-exact.  The gsasm fixes that
closed this milestone: MACHINE M6502/M65C02 forcing 8-bit immediates (QuitCode,
Ram); backward mid-segment ORG overlays in ORG'd segments (`jmp/jsr 0 / org *-2`
self-modified vectors); the `(A) < (B)` conditional-paren fix (the loader-pad
`if`); DS-count expression folding (sel.alt's paragraph pad); an undefined
top-level `&NAME` staying literal (CClock `&MIKE`); and not &-substituting
;-comments (Ram `&BLOCK`).

Target: /System.Disk/System/P8 — type=$FF (SYS), aux=$0000, 17128 bytes
"""
import os
import sys

_WORK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _WORK not in sys.path:
    sys.path.insert(0, _WORK)

from _common import (
    ensure_repo_on_path,
    gsos_incs,
    gsos_source_root,
    work_abs,
)
ensure_repo_on_path()

from gsasm import asm      as _asm
from gsasm import omf      as _omf
from gsasm import makebin  as _makebin

# ---------------------------------------------------------------------------
# Source paths
# ---------------------------------------------------------------------------
_SRC      = gsos_source_root(abs_path=True)
_GS       = os.path.join(_SRC, 'GS.OS')
_CMN      = os.path.join(_GS,  'Common')
_P8       = os.path.join(_GS,  'P8')
_P8D      = os.path.join(_P8,  'P8.Drivers')
_INCS_DIR = work_abs('includes')

# Include path: Common first, then every GS.OS subdir, then work/includes.
_INCS = gsos_incs(_INCS_DIR, src=_SRC)

# P8 original build date (embedded in golden P8#FF0000 at offset 0x26)
_P8_SYSDATE = '06-May-93'

# Expected final P8 file size (data-fork EOF = 17128 bytes)
P8_SIZE = 17128


# ---------------------------------------------------------------------------
# Assembly helpers
# ---------------------------------------------------------------------------

class P8AssemblyError(Exception):
    """A P8 source file reached an assembler error (including AError size
    assertions).  P8 is a clean, byte-exact build: any reached error means the
    layout is wrong, so we abort rather than emit a plausible-looking image."""


def _assemble(src_path, extra_incs=None, sysdate=None):
    """Assemble *src_path* and return (obj_bytes, Asm).

    Raises P8AssemblyError on ANY assembler error — including the AError size
    assertions the P8 sources embed (`AError: Not enough room for CortFlag`,
    `Code length overflow`).  Those fire exactly when a segment does not lay out
    to its expected length, so treating them as fatal is what keeps a wrong
    image from passing as progress.
    """
    incs = list(extra_incs or []) + _INCS
    a = _asm.assemble(src_path, incs, sysdate=sysdate)
    if a.errors:
        name = os.path.basename(src_path)
        detail = '\n    '.join(a.errors[:5])
        raise P8AssemblyError(
            f'{name}: {len(a.errors)} assembler error(s):\n    {detail}')
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
    return [
        {
            'name':   seg['name'],
            'raw':    seg['raw'],
            'length': seg['hdr']['LENGTH'],
            'org':    seg['hdr'].get('ORG', 0) or 0,
        }
        for seg in _omf.iter_segments(obj_bytes, records=False)
    ]


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

    Returns exactly P8_SIZE (17128) bytes — byte-exact against the golden
    P8#FF0000.  Raises P8AssemblyError on any reached assembler error and
    ValueError if the packaged result is not exactly P8_SIZE bytes.
    """
    # ----------------------------------------------------------------
    # Step 1: Assemble MliSrc.aii -> parse PROC segments
    # ----------------------------------------------------------------
    # &sysdate must expand to the build date embedded in the golden P8 (offset
    # 0x26) for byte-exactness; _assemble threads it through and raises on any
    # assembler error.
    mli_obj, _mli_asm = _assemble(
        os.path.join(_P8, 'MliSrc.aii'),
        extra_incs=[_P8],
        sysdate=_P8_SYSDATE,
    )

    # linkiigs -lseg PROCONE -org $2000 ... links all four PROC segments into
    # one load file BEFORE MakeBinIIgs flattens each, so cross-segment ENTRY
    # references (e.g. PROCONE's `lda kversion` -> PROCTWO+$FF = $BFFF) resolve
    # to their linked absolute addresses.  makebin_segments reproduces that with
    # a combined symbol table; the PROC ORGs already ride in the OMF headers
    # ($2000/$BF00/$DE00/$FF9B), matching make.p8's -org values.
    proc_bins = _makebin.makebin_segments(mli_obj)

    def _proc_bin(name):
        try:
            return proc_bins[name.upper()]
        except KeyError:
            raise KeyError(f'Segment {name!r} not found in mlisrc.obj; '
                           f'have: {sorted(proc_bins)}')

    procone_bin   = _proc_bin('PROCONE')
    proctwo_bin   = _proc_bin('PROCTWO')
    procthree_bin = _proc_bin('PROCTHREE')
    procfour_bin  = _proc_bin('PROCFOUR')

    # ----------------------------------------------------------------
    # Step 2: Assemble driver binaries
    # ----------------------------------------------------------------

    # ram.n — three segments (RAM1 @ $200, RAM2 @ $2C80, RAM3 @ $FF00) linked
    # together (make.p8: linkiigs -lseg RAM1 -org $200 -lseg RAM2 -org $2C80
    # -lseg RAM3 -org $FF00) so their cross-segment references resolve: RAM1
    # imports NOERR/MAINWRT from RAM3 and exports DONEWRT (an independent
    # per-segment makebin baked those to $0000).
    ram_obj, _ram_asm = _assemble(os.path.join(_P8D, 'Ram.n'))
    ram_bins = _makebin.makebin_segments(ram_obj)
    ram1_bin = ram_bins['RAM1']
    ram2_bin = ram_bins['RAM2']
    ram3_bin = ram_bins['RAM3']

    # Single-segment drivers
    cclock_bin = _makebin_single(os.path.join(_P8D, 'CClock.n'),    0xd742)
    tclock_bin = _makebin_single(os.path.join(_P8D, 'TClock.n'),    0xd742)
    sel_bin    = _makebin_single(os.path.join(_P8D, 'Sel.n'),       0x1000)
    xrwtot_bin = _makebin_single(os.path.join(_P8D, 'XrwTot.n'),    0xd000)
    quitcode_bin = _makebin_single(
        os.path.join(_P8D, 'QuitCode.aii'), 0x0000,
        extra_incs=[_P8D],
    )

    # sel.alt.n — single segment, 744 bytes; overlaid at $4000 it extends the
    # file to exactly P8_SIZE ($4000 + 744 = $42E8).  Its paragraph-pad
    # `ds.b (alt_dispatch + 16) - * -2` now sizes to 5 (was 4112 before the
    # DS-expression fold + ORG-relative `*` fixes).
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

    # After the last overlay the file is exactly P8_SIZE (sel.alt at $4000 runs
    # to $42E8).  Assert rather than silently clip: an oversize dest means a
    # driver segment came out the wrong length, which must fail — not be hidden
    # by trimming the image back to a plausible size.
    if len(dest) != P8_SIZE:
        raise ValueError(
            f'P8 build produced {len(dest)} bytes, expected {P8_SIZE} '
            f'(a driver/PROC segment is the wrong length)')
    return bytes(dest)


# ---------------------------------------------------------------------------
# Public entry point (diskbuilders contract)
# ---------------------------------------------------------------------------

def builders(V):
    """Return {disk_path: callable() -> bytes} for P8.

    *V* is the volume prefix (e.g. '/System.Disk').  The callable returns the
    full 17128-byte P8 data-fork bytes — byte-exact against the golden
    P8#FF0000 (verified by work/p8check.py).
    """
    return {
        f'{V}/System/P8': _build_p8,
    }
