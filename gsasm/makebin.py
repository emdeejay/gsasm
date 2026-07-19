"""gsasm/makebin.py — MakeBinIIgs / OverlayIIgs / catenate packager (M3).

Three post-link packaging operations that run after gsasm + linkiigs:

  makebin(load_file_bytes, org)  -> flat bytes
      Flatten an OMF object/load file to a raw memory image at a given origin,
      resolving all relocations for that origin.  Mirrors the real MakeBinIIgs
      (``makebiniigs -org $NNNN``) step.

  overlay(host_bytes, patches)   -> bytes
      Lay driver images into a host binary at fixed offsets.  Mirrors
      OverlayIIgs.

  catenate(parts)                -> bytes
      Join segment images in order.  Mirrors the MPW ``catenate`` command.

  stamp(path, filetype, auxtype) -> None
      Record ProDOS filetype/auxtype alongside the output.  The actual file
      content is unaffected; this writes a sidecar file for use by a future
      disk-image packager.

Implementation notes
--------------------
makebin works on the *raw OMF object* produced by gsasm/omf.emit (before a
separate link step), because the current gsasm/link.py eagerly flattens all
expressions to a single LCONST and loses the relocation structure needed to
re-base the output.  This is equivalent to the real workflow:

    asmiigs src.aii    → multi-segment OMF (.obj)
    linkiigs *.obj     → OMF load file (.lnk)  [all cross-seg refs resolved]
    makebiniigs -org   → flat binary

The OMF load file and the single-file OMF object have the same record encoding,
so makebin can consume either.  When called with a linked load file (single
LCONST segment), it simply copies the bytes; when called with a multi-segment
object it places the segments sequentially from org and resolves each EXPR
record.

This reuses link._build_body (the OMF stack-machine evaluator) and the same
GLOBAL/GEQU symbol-collection pass used by linkrom.py and toolcheck.py.

Historical ProBoot regression marker:
  DC.W LabelA-LabelB where both labels are segment heads (PROC names) in
  different segments must remain a link-time layout constant, not an assembler
  literal 0.  The old ProBoot failure at offset 0x0a produced 1666/1668 bytes;
  work/probootcheck.py now gates the closed behavior at 1668/1668.
"""

from __future__ import annotations
import os
import struct
from . import omf as _omf
from . import link as _link


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _parse_segs(data: bytes) -> list[dict]:
    """Parse all OMF segments from *data* (object or load file).

    Returns a list of dicts with keys:
      'name'  : segment name (str, upper-cased)
      'hdr'   : raw parse_header dict
      'recs'  : list of (offset, name, detail) from parse_records
      'length': declared body length (h['LENGTH'])
    """
    return [
        {
            'name': seg['name'].upper(),
            'hdr': seg['hdr'],
            'recs': seg['recs'],
            'length': seg['hdr']['LENGTH'],
        }
        for seg in _omf.iter_segments(data)
    ]


def _build_sym(segs: list[dict], org: int) -> dict[str, int]:
    """Assign sequential base addresses (starting at *org*) to each segment and
    collect GLOBAL/GEQU symbol definitions.

    Returns a symbol dict mapping upper-case name → integer value suitable for
    passing to link._build_body.
    """
    sym: dict[str, int] = {}
    base = org
    gequ_pending: list[tuple[str, list]] = []

    for seg in segs:
        sym[seg['name']] = base
        body_off = 0
        for _, rname, d in seg['recs']:
            if rname in ('CONST', 'LCONST'):
                body_off += len(d)
            elif rname == 'DS':
                body_off += d
            elif rname in ('LEXPR', 'BEXPR', 'EXPR', 'RELEXPR'):
                body_off += d[0]
            elif rname == 'GLOBAL':
                sym[d['label'].upper()] = base + body_off
            elif rname == 'GEQU':
                # Defer GEQU until all segment bases are assigned (the expression
                # may reference other segment names).
                gequ_pending.append((d['label'].upper(), d['expr']))
        base += seg['length']

    # Resolve deferred GEQUs (two passes to handle forward references).
    for label, ops in gequ_pending:
        val = _link._eval(ops, sym)
        sym.setdefault(label, val)
    for label, ops in gequ_pending:
        sym[label] = _link._eval(ops, sym)

    return sym


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def makebin(load_file_bytes: bytes, org: int) -> bytes:
    """Flatten an OMF object/load-file to a raw memory image at *org*.

    Segments are placed sequentially starting at *org*.  All LEXPR/BEXPR/EXPR
    expressions are evaluated with the resulting symbol table; RELEXPR
    (PC-relative) expressions are evaluated against the current PC.  DS records
    produce zero-fill.  The concatenated segment bodies are returned.

    This is the Python equivalent of ``makebiniigs -org $NNNN``.
    """
    segs = _parse_segs(load_file_bytes)
    if not segs:
        return b''

    sym = _build_sym(segs, org)

    result = bytearray()
    for seg in segs:
        seg_base = sym[seg['name']]
        body = _link._build_body(seg['recs'], dict(sym, __LOC__=seg_base),
                                  seg_base)
        result.extend(body)
    return bytes(result)


def makebin_segments(obj_bytes: bytes,
                     orgs: dict[str, int] | None = None) -> dict[str, bytes]:
    """Link every segment in *obj_bytes* with ONE combined symbol table, then
    flatten each to raw bytes.  Returns an ordered dict {SEGNAME: flat_bytes}.

    Unlike ``makebin`` (which flattens one segment against only its own
    symbols), this shares the symbol table across all segments so a
    cross-segment ENTRY/GLOBAL reference resolves to the *other* segment's
    linked address.  Each segment is based at its OMF-header ORG, or at an
    override supplied in *orgs* ({SEGNAME: org}, case-insensitive).

    This mirrors the linkiigs ``-lseg NAME -org $X`` recipe that places several
    named segments at fixed, non-contiguous origins in a single link before
    MakeBinIIgs flattens each — as used by the P8 build (GS.OS/MakeFiles/make.p8,
    where PROCONE/PROCTWO/PROCTHREE/PROCFOUR sit at $2000/$BF00/$DE00/$FF9B and
    reference one another's entry points).
    """
    segs = _parse_segs(obj_bytes)
    if not segs:
        return {}
    orgs = {k.upper(): v for k, v in (orgs or {}).items()}

    sym: dict[str, int] = {}
    gequ_pending: list[tuple[str, list]] = []
    for seg in segs:
        base = orgs.get(seg['name'], seg['hdr'].get('ORG') or 0)
        seg['base'] = base
        sym[seg['name']] = base
        body_off = 0
        for _, rname, d in seg['recs']:
            if rname in ('CONST', 'LCONST'):
                body_off += len(d)
            elif rname == 'DS':
                body_off += d
            elif rname in ('LEXPR', 'BEXPR', 'EXPR', 'RELEXPR'):
                body_off += d[0]
            elif rname == 'GLOBAL':
                sym[d['label'].upper()] = base + body_off
            elif rname == 'GEQU':
                gequ_pending.append((d['label'].upper(), d['expr']))
    # Resolve deferred GEQUs (two passes for forward references).
    for label, ops in gequ_pending:
        sym.setdefault(label, _link._eval(ops, sym))
    for label, ops in gequ_pending:
        sym[label] = _link._eval(ops, sym)

    out: dict[str, bytes] = {}
    for seg in segs:
        body = _link._build_body(seg['recs'],
                                 dict(sym, __LOC__=seg['base']), seg['base'])
        out[seg['name']] = bytes(body)
    return out


def overlay(host_bytes: bytes,
            patches: list[tuple[bytes, int]]) -> bytes:
    """Lay driver images into *host_bytes* at fixed offsets.

    *patches* is a list of (driver_bytes, offset) pairs.  Each driver image is
    copied into the host at the given offset, overwriting whatever was there.
    The host length is unchanged.

    This is the Python equivalent of OverlayIIgs.
    """
    buf = bytearray(host_bytes)
    for driver, off in patches:
        n = len(driver)
        buf[off:off + n] = driver
    return bytes(buf)


def catenate(parts: list[bytes]) -> bytes:
    """Join segment images in order and return the concatenation.

    This is the Python equivalent of the MPW ``catenate`` command as used in
    GS.OS kernel assembly (joining scm.bin.N files into GS.OS / Start.GS.OS).
    """
    return b''.join(parts)


def stamp(path: str, filetype: int, auxtype: int) -> None:
    """Record ProDOS filetype/auxtype for *path* as a sidecar .filetype file.

    The content of *path* is untouched.  A sidecar file ``<path>.filetype`` is
    written with one line: ``type=0xNN aux=0xNNNNNNNN``.  A future disk-image
    packager (cadius / ProDOS block writer) can read this to set the file's
    ProDOS metadata.

    filetype examples: 0xFF = SYS, 0xB0 = OS, 0xBA = TOL, 0xF0 = PSYS.
    """
    sidecar = path + '.filetype'
    with open(sidecar, 'w') as fh:
        fh.write(f'type={filetype:#04x} aux={auxtype:#010x}\n')
