"""diskbuilders/kernel_os.py — M8 disk-file builders for GS.OS and GS.OS.Dev.

Wires builders for the on-disk GS.OS and GS.OS.Dev kernel files on the System
Disk.  These files are wired as precise residuals: the builders produce the best
possible bytes with current gsasm capabilities, but the output does not yet
match the golden exactly (known gaps documented below).

  GS.OS  = Loader.bin ++ cat(scm.bin, scm.bin.{2..7}, scm.bin.{12..17})
  GS.OS.Dev = linkiigs(NewDispatcher.src) with reformatted header

Build recipe (from GS.OS/MakeFiles/make.os and GS.OS/Scripts/linkOS):
  Loader:
    AsmIIgs Loader.a       -> Loader.obj
    AsmIIgs GSHeader.a     -> GSHeader.obj
    AsmIIgs GSFooter.a     -> GSFooter.obj
    LinkIIgs -x GSHeader.obj Loader.obj GSFooter.obj -> Loader.S16
    MakeBinIIgs Loader.S16 -> Loader.bin (+ Loader.bin.2)
  SCM: see kernelcheck._build_scm_segments()
  GS.OS.Dev: linkiigs -t $bc NewDispatcher.Obj -> GS.OS.Dev

Known residuals (precise, not unknown gaps):
  GS.OS:
    - Loader.bin: Loader.a missing toolbox headers (M16.Memory, E16.Memory,
      M16.MiscTool, E16.GSOS etc.) and AError pseudo-op; built Loader.bin is
      16386B vs golden 16590B (204 bytes short).
    - SCM: bank-byte SUPER type-27 relocations unresolved (lda #^Label emits
      $00 placeholder); SUPER type-6 cINTERSEG records missing; init1
      Record/EndR data segment STD_BUFFER is now assembled correctly but
      still 34 bytes short across all SCM segments vs golden.
    - Net: built 55361B vs golden 55395B (34 bytes short -- size mismatch
      prevents overlay; reported as precise residual).
  GS.OS.Dev:
    - NewDispatcher.src: 32 bytes of code missing in install_dev_svc proc
      (likely from unimplemented #^Label / SUPER type-27 bank-byte records)
      plus SUPER relocation records absent; built 2256B vs golden 2388B
      (size mismatch prevents overlay; reported as precise residual).
"""
import os
import struct
import sys

# kernel_os.py lives at work/diskbuilders/kernel_os.py.
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

# kernelcheck.py helper path (for _build_scm_segments())
_WORK = os.path.join(_ROOT, 'work')


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
    (LCONST + SUPER + END records from DISPDATA onward) are unchanged.

    new DISPDATA = 44 + 10 + 5 = 59  (same as the shipping GS.OS.Dev / Error.Msg)
    """
    h            = _omf.parse_header(linked_bytes)
    dd_old       = h['DISPDATA']
    sname_fld    = bytes([len(segname)]) + segname            # 1 + len bytes
    new_dispdata = 44 + len(loadname) + len(sname_fld)        # 44 + 10 + 5 = 59
    body         = linked_bytes[dd_old:]                      # LCONST/SUPER…END
    new_bytecnt  = new_dispdata + len(body)

    hdr = bytearray(linked_bytes[:44])                        # fixed numeric fields
    struct.pack_into('<I', hdr, 0,  new_bytecnt)              # BYTECNT
    struct.pack_into('<H', hdr, 42, new_dispdata)             # DISPDATA
    # DISPNAME stays 44; LENGTH, KIND, ORG, ALIGN, SEGNUM, etc. unchanged
    return bytes(hdr) + loadname + sname_fld + body


# ---------------------------------------------------------------------------
# GS.OS builder
# ---------------------------------------------------------------------------

def _build_gsos() -> bytes:
    """Build GS.OS from Loader.bin + catenate(scm.bin, .2..7, .12..17).

    Recipe (from make.os / linkOS):
        LinkIIgs -x GSHeader.obj Loader.obj GSFooter.obj -> Loader.S16
        MakeBinIIgs Loader.S16 -> Loader.bin (+ Loader.bin.2)
        catenate Loader.bin Loader.bin.2 scm.bin ... scm.bin.17 > GS.OS

    Precise residuals (output will not match golden byte-for-byte):
      - Loader.bin: missing toolbox includes + AError pseudo-op -> 16386B
        vs golden 16590B (204 bytes short); correct bytes up to missing
        includes.
      - SCM segments: bank-byte SUPER type-27 not implemented; 34 bytes short.
      - Net: 55361B built vs 55395B golden.

    Target: /System.Disk/System/GS.OS — $F9 aux $0000, 55395 bytes
    """
    if _WORK not in sys.path:
        sys.path.insert(0, _WORK)
    import kernelcheck as _kc                              # noqa: PLC0415

    # Build Loader.bin + Loader.bin.2 from source
    loader_src   = os.path.join(_GS, 'Loader', 'Loader.a')
    header_src   = os.path.join(_GS, 'Loader', 'GSHeader.a')
    footer_src   = os.path.join(_GS, 'Loader', 'GSFooter.a')

    loader_obj, loader_asm = _assemble(loader_src)
    header_obj, header_asm = _assemble(header_src)
    footer_obj, footer_asm = _assemble(footer_src)

    # Link: GSHeader.obj Loader.obj GSFooter.obj (order from make.os: -x flag)
    linked_s16 = _lnk.link(
        [(header_obj, header_asm), (loader_obj, loader_asm),
         (footer_obj, footer_asm)],
        opts={'merge': False})
    loader_bin = _makebin.makebin(linked_s16, 0)

    # Build SCM segments via kernelcheck helpers
    scm_bins = _kc._build_scm_segments()
    if scm_bins is None:
        raise RuntimeError('_build_scm_segments() returned None')

    # GS.OS catenation order (from linkOS / make.os):
    #   Loader.bin Loader.bin.2 scm.bin scm.bin.{2..7} scm.bin.{12..17}
    # Note: makebin() on a multi-segment Loader.S16 produces Loader.bin
    # concatenated with Loader.bin.2 (second segment) as a single flat image.
    # The SCM parts follow immediately.
    scm_parts = (['scm.bin'] +
                 [f'scm.bin.{n}' for n in [2, 3, 4, 5, 6, 7, 12, 13, 14, 15, 16, 17]])
    scm_cat = _makebin.catenate([scm_bins.get(k, b'') for k in scm_parts])

    return loader_bin + scm_cat


# ---------------------------------------------------------------------------
# GS.OS.Dev builder
# ---------------------------------------------------------------------------

def _build_gsos_dev() -> bytes:
    """Build GS.OS.Dev from NewDispatcher.src.

    Recipe (from make.os):
        AsmIIgs NewDispatcher.Src -o NewDispatcher.Obj -i {common}
        linkiigs -t $bc -x NewDispatcher.Obj -o GS.OS.Dev

    The shipping GS.OS.Dev uses the same header format as Error.Msg:
        SEGNAME = b'main', LOADNAME = 10 zero bytes, DISPDATA = 59.
    We reformat the header post-link to match.

    Precise residual: 2256B built vs 2388B golden (132 bytes short).
      - LCONST: 2180B built vs 2212B golden (32 bytes of code missing,
        likely from #^Label / SUPER type-27 bank-byte not implemented).
      - SUPER relocation records: absent in built output.

    Target: /System.Disk/System/GS.OS.Dev — $BC aux $0000, 2388 bytes
    """
    src    = os.path.join(_GS, 'OS', 'DeviceDispatcher', 'NewDispatcher.src')
    obj, a = _assemble(src)
    linked = _lnk.link([(obj, a)], opts={'merge': True})
    return _reformat_omf_header(linked)


# ---------------------------------------------------------------------------
# Public entry point (diskbuilders contract)
# ---------------------------------------------------------------------------

def builders(V):
    """Return {disk_path: callable() -> bytes} for GS.OS kernel disk files.

    ``V`` is the volume prefix string, e.g. ``'/System.Disk'``.
    Each callable returns the FULL on-disk file bytes (== data-fork EOF length,
    or close to it — see module docstring for precise residuals).

    Both GS.OS and GS.OS.Dev are wired as precise residuals: the builders
    run, produce correct bytes up to known gsasm gaps, but the sizes and
    some byte values will not match the golden exactly.  diskcheck reports
    them as logical mismatches (not overlaid) so the physical image stays
    byte-identical.
    """
    return {
        f'{V}/System/GS.OS':     _build_gsos,
        f'{V}/System/GS.OS.Dev': _build_gsos_dev,
    }
