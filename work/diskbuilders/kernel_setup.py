"""diskbuilders/kernel_setup.py — M8 disk-file builders for GS/OS kernel files.

Wires builders for the kernel and setup files on the System Disk:

  Wired (logical-exact or residual):
    Error.Msg    — linkiigs(english.obj) plain OMF; code 100%, header reformatted
                   to match shipping SEGNAME/LOADNAME format → logical-exact
    Start.GS.OS  — catenate(scm.bin.8..11); size exact, content ~87% → residual

  Skipped (length cannot be matched with current gsasm):
    GS.OS        — needs Loader.bin (Loader.a crashes gsasm) + SCM 64B short
                   (Init1.Src Record/EndR unsupported); built=55331 vs EOF=55395
    GS.OS.Dev    — NewDispatcher.src: built=2256B vs EOF=2388B (content gap)
    CDev.Data    — binary data file; no ASM source available
    P8           — needs 4 PROCs + driver overlays; only PROCONE buildable
    Resource.Mgr — built=11309B vs EOF=11798B (bank-byte / SUPER type-27 gap)
    Tool.Setup   — multi-object build required (tl, desk, misc.tools, etc.)
    TS2          — multi-object build (dozens of files); multi-seg ExpressLoad
    TS3          — multi-object build; multi-seg ExpressLoad

The 'Error.Msg header reformat' technique: the OMF header format that gsasm's
linker emits (SEGNAME=proc-name, LOADNAME=b'main') differs from the shipping
format (SEGNAME=b'main', LOADNAME=zeros) — a known linker cosmetic difference.
The body bytes (LCONST code + END record) are byte-identical.  We reformat the
header post-link to match the shipping format so diskcheck reports logical-exact.
"""
import os
import struct
import sys

# kernel_setup.py lives at work/diskbuilders/kernel_setup.py.
# The project root is three directories up.
_ROOT = os.path.dirname(                    # worktree/
         os.path.dirname(                   # work/
          os.path.dirname(                  # work/diskbuilders/
           os.path.abspath(__file__))))
sys.path.insert(0, _ROOT)                   # so `import gsasm` resolves

from gsasm import asm      as _asm
from gsasm import omf      as _omf
from gsasm import linkiigs as _lnk
from gsasm import makebin  as _makebin

# ---------------------------------------------------------------------------
# Source paths (absolute, derived from project root)
# ---------------------------------------------------------------------------
_SRC      = os.path.join(_ROOT, 'ref/GSOS_6/IIGS.601.SRC')
_GS       = os.path.join(_SRC, 'GS.OS')
_CMN      = os.path.join(_GS,  'Common')
_INCS_DIR = os.path.join(_ROOT, 'work/includes')

# Include path: Common first, then every GS.OS subdir, then work/includes.
_INCS = [_CMN] + [d for d, _, _ in os.walk(_GS)] + [_INCS_DIR]

# Non-fatal pseudo-ops that gsasm doesn't implement (matches kernelcheck.py)
_IGNORE_OPS = ('pagesize', 'datachk', 'endproc', 'eject', 'writeln', 'codechk')


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _assemble(src_path):
    """Assemble *src_path* and return (obj_bytes, Asm).

    Non-fatal pseudo-ops are silently ignored; other errors are printed to
    stderr (do not abort the run, matching kernelcheck.py behaviour).
    """
    a = _asm.assemble(src_path, _INCS)
    fatal = [e for e in a.errors
             if not any(x in e.lower() for x in _IGNORE_OPS)]
    if fatal:
        name = os.path.basename(src_path)
        print(f'  [{name}] {len(fatal)} non-ignored errors; first 2:',
              file=sys.stderr)
        for e in fatal[:2]:
            print(f'    {e}', file=sys.stderr)
    return _omf.emit(a), a


def _reformat_omf_header(linked_bytes,
                         segname=b'main',
                         loadname=b'\x00' * 10) -> bytes:
    """Reformat a single-segment OMF header to match the shipping format.

    gsasm's linker emits SEGNAME=proc-name + LOADNAME=b'main', whereas the
    shipping binaries use SEGNAME=b'main' + LOADNAME=zeros.  The body bytes
    (LCONST + END records from DISPDATA onward) are unchanged.

    Layout of the reformatted header:
      bytes 0..43:  44-byte fixed numeric fields (BYTECNT updated, DISPDATA updated)
      bytes 44..53: LOADNAME (10 bytes of zeros)
      bytes 54..58: SEGNAME field: \\x04main  (length-prefixed, 5 bytes)
      bytes 59..:   body (LCONST record + END byte = linked_bytes[dd_old:])

    new DISPDATA = 44 + 10 + 5 = 59  (same as the shipping Error.Msg)
    """
    h            = _omf.parse_header(linked_bytes)
    dd_old       = h['DISPDATA']
    sname_fld    = bytes([len(segname)]) + segname            # 1 + len bytes
    new_dispdata = 44 + len(loadname) + len(sname_fld)        # 44 + 10 + 5 = 59
    body         = linked_bytes[dd_old:]                      # LCONST … END
    new_bytecnt  = new_dispdata + len(body)

    hdr = bytearray(linked_bytes[:44])                        # fixed numeric fields
    struct.pack_into('<I', hdr, 0,  new_bytecnt)              # BYTECNT
    struct.pack_into('<H', hdr, 42, new_dispdata)             # DISPDATA
    # DISPNAME stays 44; LENGTH, KIND, ORG, ALIGN, SEGNUM, etc. unchanged
    return bytes(hdr) + loadname + sname_fld + body


# ---------------------------------------------------------------------------
# Error.Msg builder
# ---------------------------------------------------------------------------

def _build_errmsg() -> bytes:
    """Assemble English.src and produce the shipping Error.Msg OMF.

    Recipe (make.error.msg):
        asmiigs english.src -> english.obj
        linkiigs -x english.obj -o Error.Msg -t $bc

    The code image is 100% byte-identical to the shipping file.
    The header is reformatted post-link to match the shipping
    SEGNAME/LOADNAME format (SEGNAME=b'main', LOADNAME=10 zeros,
    DISPDATA=59) so diskcheck reports logical-exact.

    Target: /System.Disk/System/Error.Msg — $BC aux $0000, 5472 bytes
    """
    src    = os.path.join(_GS, 'OS', 'ErrorMessages', 'English.src')
    obj, a = _assemble(src)
    linked = _lnk.link([(obj, a)], opts={'merge': True})
    return _reformat_omf_header(linked)


# ---------------------------------------------------------------------------
# Start.GS.OS builder
# ---------------------------------------------------------------------------

def _build_start_gsos() -> bytes:
    """Build Start.GS.OS from scm.bin.8..11 (gquit segments).

    Recipe (linkOS / make.os):
        catenate scm.bin.8 scm.bin.9 scm.bin.10 scm.bin.11 > Start.GS.OS

    Size matches the golden exactly (13169 bytes).  Content is ~87% byte-exact;
    the remaining ~13% diverges due to unresolved SUPER type-27 bank-byte
    relocations (lda #^Label -> gsasm emits 0x00 placeholder instead of the
    bank byte).  diskcheck will report this as residual (first diff @ 0xce).

    Reuses kernelcheck._build_scm_segments() to avoid duplicating all the
    Layout A/B/C flat-binary construction logic.

    Target: /System.Disk/System/Start.GS.OS — $F9 aux $0001, 13169 bytes
    """
    _kc_path = os.path.join(_ROOT, 'work')
    if _kc_path not in sys.path:
        sys.path.insert(0, _kc_path)
    import kernelcheck as _kc                              # noqa: PLC0415

    scm_bins = _kc._build_scm_segments()
    if scm_bins is None:
        raise RuntimeError('_build_scm_segments() returned None')

    parts = ['scm.bin.8', 'scm.bin.9', 'scm.bin.10', 'scm.bin.11']
    return _makebin.catenate([scm_bins.get(k, b'') for k in parts])


# ---------------------------------------------------------------------------
# Public entry point (diskbuilders contract)
# ---------------------------------------------------------------------------

def builders(V):
    """Return {disk_path: callable() -> bytes} for kernel/setup disk files.

    ``V`` is the volume prefix string, e.g. ``'/System.Disk'``.
    Each callable returns the FULL on-disk file bytes (== data-fork EOF length).

    Skipped files and reasons:
      GS.OS        — 55331B built vs 55395B EOF: Loader.a crashes gsasm + 64B
                     missing from Init1.Src (Record/EndR unsupported)
      GS.OS.Dev    — 2256B built vs 2388B EOF: NewDispatcher content gap
      CDev.Data    — no ASM source; it's a binary CDEV configuration data file
      P8           — only PROCONE (6358B) buildable; full file needs 4 PROCs
                     + driver overlays (cclock, tclock, ram, sel, xrwtot)
      Resource.Mgr — 11309B built vs 11798B EOF: bank-byte reloc gap
      Tool.Setup   — multi-object build (tl, desk, misc.tools, …) not yet wired
      TS2          — multi-object / multi-seg ExpressLoad; not yet wired
      TS3          — multi-object / multi-seg ExpressLoad; not yet wired
    """
    return {
        f'{V}/System/Error.Msg':    _build_errmsg,
        f'{V}/System/Start.GS.OS': _build_start_gsos,
    }
