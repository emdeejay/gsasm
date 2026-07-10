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
  GS.OS (WP-4.1: now LENGTH-exact (55395B) but not yet byte-exact):
    - Loader.bin: SIZE-exact (16590B) via the RECORD `DS RecordName` sizeof fix
      (Data.a GLOBALS: 204B of record-template DS now allocate correctly) plus
      the AError / Func / endf directives.  CONTENT still differs (~5976/16590B),
      but the cause is LOAD-SEGMENT PLACEMENT, not relocs.  CRACKED + proven at
      97% (from 64%) in work/loader_placed.py: golden groups by SEG/load segment
      ('Loader' then 'Loader_LC'; a default-'main' seg inherits the preceding
      named loadname within its object), STORES the groups contiguously, but
      LOADS each at its own base (the group header's ORG: 0x1a5d0 / 0x1cfd0) —
      relocs resolve against the runtime base, not the flat position.  linkiigs
      instead places in link order anchored on the two headers' ORGs, so
      zloader_lc_header lands at flat 0x30 where gold has CALLTABLE.  The residual
      3% is NOT placement — it is the operand-resolution long-tail (qualified
      record fields e.g. HEADER.DISPNAME, cross-seg refs) + ~4B DC.W import-diff
      (omf bakes CONST ffff not an EXPR record).  To flip GS.OS: integrate the
      loader_placed algorithm + close that long-tail + the SCM DC.W LEXPR gap.
    - SCM: the WP-2.1 placed symtab is now seeded into every SCM content link,
      so macro-generated `lda #^Label` bank bytes resolve to real addresses
      (SCM 74% -> 95%; kernelcheck GS.OS 28831 -> 37072/38805).  ~1731 SCM bytes
      still differ (DC.W offset-table LEXPR values + residual relocs).
    - Net: LENGTH-exact 55395B; ~7707 content bytes differ (Loader + SCM) -> not
      yet a byte-exact overlay (no diskcheck flip).  SUPER type-6 cINTERSEG is
      OMF-internal and does not affect the flat GS.OS image.
  GS.OS.Dev:
    - BYTE-EXACT (2388/2388).  Two general fixes closed it: bare `ds N`
      counts WORDS (asm._ds_size, MPW default width — NewDispatcher's
      `ds 32` reserves 64 zero bytes), and linkiigs.link opts['super']
      emits SUPER type-0/1 relocation records for the merged load segment
      (scan via expressload._scan_relocs, encode via emit_super).
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
from gsasm import link     as _link
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
# Loader.bin — grouped-placed link (byte-exact; proven in work/loader_placed.py)
# ---------------------------------------------------------------------------

# The Loader region of GS.OS is `LinkIIgs -x GSHeader.obj Loader.obj GSFooter.obj`
# -> MakeBinIIgs.  A plain link places segments in LINK order (CALLTABLE lands
# after the LC header — a ~5957B layout shift, 64% match).  The golden placement
# groups segments by LOAD SEGMENT and loads each group at its own runtime ORG base
# while storing them contiguously; relocs resolve against the runtime base.  See
# work/loader_placed.py (the oracle that validates this to 16590/16590 byte-exact).
_LOADER_ORDER = ('loader', 'loader_lc')
_LOADER_BASE  = 0x1a5d0


def _build_loader_bin(order=_LOADER_ORDER, base0=_LOADER_BASE, return_meta=False):
    """Byte-exact Loader.bin image (GSHeader+Loader+GSFooter, grouped-placed).

    Groups the three objects' segments by resolved LOAD SEGMENT (a default-'main'
    seg inherits the preceding NAMED loadname within its object), stores the groups
    contiguously in ``order``, but bases each group at its runtime ORG (the group
    header's ORG) so relocations resolve against the runtime address, not the flat
    position.  Reuses the tested ``linkiigs._build_symtab`` + ``link._build_body``.
    """
    loader = os.path.join(_GS, 'Loader')
    objs = [_assemble(os.path.join(loader, s))
            for s in ('GSHeader.a', 'Loader.a', 'GSFooter.a')]

    # Per-(obj,emit) segment info: resolved loadname, body length, ORG.
    info = {}
    for oi, (obj, _a) in enumerate(objs):
        cur = None
        for ei, sd in enumerate(_lnk._parse_obj(obj)):
            ln = sd['loadname'].lower()
            if ln != 'main':
                cur = ln
            info[(oi, ei)] = {'ln': ln if ln != 'main' else (cur or 'main'),
                              'len': _link._body_length(sd['recs']),
                              'org': sd.get('org', 0) or 0}

    # Flat order = groups in ``order``, stable within a group (obj then emit idx).
    keys = sorted(info, key=lambda k: (order.index(info[k]['ln'])
                                       if info[k]['ln'] in order else 99, k))
    # Runtime base per group = the group's first ORG'd seg (its header).
    gbase = {}
    for kk in keys:
        ln = info[kk]['ln']
        if ln not in gbase and info[kk]['org']:
            gbase[ln] = info[kk]['org']
    flat = 0
    rt_cur = {}
    for kk in keys:
        i = info[kk]
        i['flat'] = flat
        flat += i['len']
        b = rt_cur.get(i['ln'], gbase.get(i['ln'], base0))
        i['rt'] = b
        rt_cur[i['ln']] = b + i['len']

    # linkiigs._build_symtab inputs in OBJECT order, each seg at its runtime base.
    placed, obj_seg_bases, placed_obj_idx = [], [], []
    pidx = {}
    for oi, (obj, asm) in enumerate(objs):
        bases = []
        for ei, sd in enumerate(_lnk._parse_obj(obj)):
            rt = info[(oi, ei)]['rt']
            pidx[(oi, ei)] = len(placed)
            placed.append((sd['segname'], sd['recs'], rt, sd['hdr'], asm))
            placed_obj_idx.append(oi)
            bases.append(rt)
        obj_seg_bases.append(bases)
    sym, obj_globals = _lnk._build_symtab(objs, placed, obj_seg_bases, placed_obj_idx)

    # Emit bodies in FLAT (grouped) order, each resolved at its runtime base.
    out = bytearray()
    for kk in keys:
        pi = pidx[kk]
        _seg, recs, rt, _hdr, _asm = placed[pi]
        oi = placed_obj_idx[pi]
        local = sym if not obj_globals[oi] else {**sym, **obj_globals[oi]}
        out += _link._build_body(recs, dict(local, __LOC__=rt), rt)
    if return_meta:
        return bytes(out), [(info[k], k) for k in keys]
    return bytes(out)


# ---------------------------------------------------------------------------
# GS.OS builder
# ---------------------------------------------------------------------------

def _build_gsos() -> bytes:
    """Build GS.OS from Loader.bin + catenate(scm.bin, .2..7, .12..17).

    Recipe (from make.os / linkOS):
        LinkIIgs -x GSHeader.obj Loader.obj GSFooter.obj -> Loader.S16
        MakeBinIIgs Loader.S16 -> Loader.bin (+ Loader.bin.2)
        catenate Loader.bin Loader.bin.2 scm.bin ... scm.bin.17 > GS.OS

    Residual (length-exact 55395B):
      - Loader region [0:16590]: BYTE-EXACT via _build_loader_bin (grouped-placed
        link + CASE ON + DC.W char-literal + import-diff EXPR + placed-base symtab).
      - SCM region [16590:]: ~1731 bytes differ — DC.W offset-table LEXPR values
        (the remaining GS.OS gap; see kernelcheck._build_scm_segments()).

    Target: /System.Disk/System/GS.OS — $F9 aux $0000, 55395 bytes
    """
    if _WORK not in sys.path:
        sys.path.insert(0, _WORK)
    import kernelcheck as _kc                              # noqa: PLC0415

    # Build the Loader region (Loader.bin ++ Loader.bin.2) via the byte-exact
    # grouped-placed link — GSHeader/Loader/GSFooter grouped by load segment and
    # based at each group's runtime ORG (see _build_loader_bin / loader_placed.py).
    loader_bin = _build_loader_bin()

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

    BYTE-EXACT: 2388/2388 (opts['super'] emits the SUPER type-0/1
    relocation records the shipping load file carries).

    Target: /System.Disk/System/GS.OS.Dev — $BC aux $0000, 2388 bytes
    """
    src    = os.path.join(_GS, 'OS', 'DeviceDispatcher', 'NewDispatcher.src')
    obj, a = _assemble(src)
    linked = _lnk.link([(obj, a)], opts={'merge': True, 'super': True})
    return _reformat_omf_header(linked)


# ---------------------------------------------------------------------------
# Public entry point (diskbuilders contract)
# ---------------------------------------------------------------------------

def builders(V):
    """Return {disk_path: callable() -> bytes} for GS.OS kernel disk files.

    ``V`` is the volume prefix string, e.g. ``'/System.Disk'``.
    Each callable returns the FULL on-disk file bytes (== data-fork EOF length,
    or close to it — see module docstring for precise residuals).

    GS.OS.Dev is byte-exact.  GS.OS is wired as a precise residual: the
    builder runs, produces correct bytes up to known gsasm gaps (the SCM
    external floor), so diskcheck reports it as a logical mismatch (not
    overlaid) and the physical image stays byte-identical.
    """
    return {
        f'{V}/System/GS.OS':     _build_gsos,
        f'{V}/System/GS.OS.Dev': _build_gsos_dev,
    }
