"""gsasm/link.py — minimal OMF v2 linker.

Links a single OMF object file (possibly multi-segment) into a load file.
All LEXPR/BEXPR/EXPR expressions are fully evaluated; RELEXPR (relative)
expressions are resolved against the global symbol table.  The output is a
single-segment OMF file whose body is the concatenation of all input-segment
bodies (matching what ORCA/M 'link' produces for a one-file link job).

Supported input records: CONST, LCONST, DS, LEXPR, BEXPR, EXPR, RELEXPR,
GLOBAL, GEQU, END.  INTERSEG/IMPORT are not yet handled (none appear in the
ROM 03 sources when linked one file at a time).
"""

from __future__ import annotations
from . import omf as _omf

# R8: the OMF-record evaluation / segment-construction utilities that grew up
# here (_eval, _body_length, _build_body, _make_segment) moved verbatim to
# gsasm/omf.py — they are OMF-record semantics, not linking policy.  They are
# re-exported so historical `link._eval` / `_link._build_body` call sites keep
# working; new code should import them from gsasm.omf directly.
from .omf import _eval, _body_length, _build_body, _make_segment  # noqa: F401


# ---------------------------------------------------------------------------
# Main linker entry point
# ---------------------------------------------------------------------------

def link(obj_bytes: bytes) -> bytes:
    """Link a single OMF object file; return the linked OMF load file.

    The output is one OMF segment whose body is the concatenation of all
    input-segment bodies (in order), with all expressions evaluated.
    This matches the structure ORCA/M produces for a single-file link.
    """
    # ---- 1. Parse all input segments ----
    segs: list[dict] = [
        {'hdr': seg['hdr'], 'recs': seg['recs']}
        for seg in _omf.iter_segments(obj_bytes)
    ]

    if not segs:
        return b''

    # ---- 2. Assign base addresses ----
    # Fixed-ORG (non-zero) segments keep their declared base.
    # Relocatable (ORG = 0 or None) segments are laid out sequentially from 0.
    sym: dict[str, int] = {}
    reloc_next = 0

    for seg in segs:
        h = seg['hdr']
        org = h['ORG'] or 0
        name = h['SEGNAME'].decode('mac_roman', 'replace').rstrip('\x00').strip().upper()
        if org:
            seg['base'] = org
        else:
            seg['base'] = reloc_next
            reloc_next += h['LENGTH']
        sym[name] = seg['base']

    # ---- 3. Collect GLOBAL / GEQU symbols (first pass through records) ----
    for seg in segs:
        base = seg['base']
        body_off = 0
        for _, nm, d in seg['recs']:
            if nm == 'END':
                break
            if nm in ('CONST', 'LCONST'):
                body_off += len(d)
            elif nm in ('LEXPR', 'BEXPR', 'EXPR', 'RELEXPR'):
                body_off += d[0]
            elif nm == 'DS':
                body_off += d
            elif nm == 'GLOBAL':
                sym[d['label'].upper()] = base + body_off
            elif nm == 'GEQU':
                sym[d['label'].upper()] = _eval(d['expr'], sym)

    # ---- 4. Build each segment body ----
    bodies: list[bytes] = []
    for seg in segs:
        bodies.append(_build_body(seg['recs'], sym, seg['base']))

    # ---- 5. Emit a single merged output segment ----
    # Use the first segment's metadata for the output segment header.
    first_h = segs[0]['hdr']
    out_name  = first_h['SEGNAME']
    out_load  = first_h['LOADNAME']
    out_org   = segs[0]['base']
    out_kind  = first_h['KIND']
    merged    = b''.join(bodies)

    return _make_segment(out_name, out_load, out_org, out_kind, 1, merged)
