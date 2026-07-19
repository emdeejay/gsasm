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
import struct
from . import omf as _omf

# ---------------------------------------------------------------------------
# Expression evaluator
# ---------------------------------------------------------------------------

def _eval(ops: list, sym: dict) -> int:
    """Evaluate an OMF stack-machine expression.

    sym maps FOLDED name -> integer value (segment bases + GLOBAL labels). Names
    are folded (upper-cased, unless a CASE ON module keeps them case-sensitive)
    exactly once at emit time, so the operand `val` is looked up as-is here.
    All arithmetic is 32-bit unsigned; the caller masks to the desired width.
    """
    stack: list[int] = []
    for op in ops:
        if op == 'end':
            break
        if op == 'loc':                         # current PC placeholder
            stack.append(sym.get('__LOC__', 0))
            continue
        if not isinstance(op, tuple):
            continue
        kind, val = op
        if kind == 'lit':
            stack.append(val & 0xFFFFFFFF)
        elif kind.startswith('sym'):            # sym83 / sym84 / sym85 …
            stack.append(sym.get(val, 0) & 0xFFFFFFFF)
        elif kind == 'op':
            if len(stack) < 2:
                continue
            b, a = stack.pop(), stack.pop()
            if val == 0x01:                     # ADD
                stack.append((a + b) & 0xFFFFFFFF)
            elif val == 0x02:                   # SUB
                stack.append((a - b) & 0xFFFFFFFF)
            elif val == 0x03:                   # MUL
                stack.append((a * b) & 0xFFFFFFFF)
            elif val == 0x04:                   # DIV (unsigned)
                stack.append((a // b) & 0xFFFFFFFF if b else 0)
            elif val == 0x07:                   # SHL / SHR (count is signed)
                count = b if b < 0x80000000 else b - 0x100000000
                if count >= 0:
                    stack.append((a << count) & 0xFFFFFFFF)
                else:
                    stack.append((a >> (-count)) & 0xFFFFFFFF)
            else:
                stack.append(0)                 # unsupported op
    return stack[0] if stack else 0


# ---------------------------------------------------------------------------
# Body construction
# ---------------------------------------------------------------------------

def _body_length(records: list) -> int:
    """Compute the segment body length from its OBJ records."""
    n = 0
    for _, nm, d in records:
        if nm == 'END':
            break
        if nm in ('CONST', 'LCONST'):
            n += len(d)
        elif nm in ('LEXPR', 'BEXPR', 'EXPR', 'RELEXPR'):
            n += d[0]
        elif nm == 'DS':
            n += d
    return n


def _build_body(records: list, sym: dict, seg_base: int) -> bytes:
    """Evaluate all records for one segment and return the body bytes."""
    body = bytearray()
    for _, nm, d in records:
        if nm == 'END':
            break
        pos = len(body)
        sym['__LOC__'] = seg_base + pos

        if nm in ('CONST', 'LCONST'):
            body.extend(d)

        elif nm == 'DS':
            body.extend(bytes(d))

        elif nm in ('LEXPR', 'BEXPR', 'EXPR'):
            nb, ops = d
            val = _eval(ops, sym)
            for i in range(nb):
                body.append((val >> (8 * i)) & 0xFF)

        elif nm == 'RELEXPR':
            nb, _origin, ops = d
            # relative = eval(target_expr) - address_of_next_instruction
            target = _eval(ops, sym)
            next_pc = seg_base + pos + nb
            rel = (target - next_pc) & ((1 << (8 * nb)) - 1)
            for i in range(nb):
                body.append((rel >> (8 * i)) & 0xFF)

        # GLOBAL / GEQU: no bytes emitted (handled in symbol-collection pass)

    return bytes(body)


# ---------------------------------------------------------------------------
# OMF output helpers
# ---------------------------------------------------------------------------

def _p4(v: int) -> bytes:
    return struct.pack('<I', v & 0xFFFFFFFF)

def _p2(v: int) -> bytes:
    return struct.pack('<H', v & 0xFFFF)


def _make_segment(segname: bytes, loadname: bytes, org: int, kind: int,
                  segnum: int, body: bytes, tail_recs: bytes = b'') -> bytes:
    """Build a complete OMF segment: header + LCONST(body) [+ tail_recs] + END.

    ``tail_recs`` — pre-encoded OMF records (e.g. SUPER relocation records)
    inserted between the LCONST and the END record.
    """
    sname_field = bytes([len(segname)]) + segname
    lname_field = (loadname + b'\x00' * 10)[:10]
    dispname = 44
    dispdata = dispname + 10 + len(sname_field)
    is_data = bool(kind & 1)
    banksize = 0 if is_data else 0x10000

    hdr = bytearray(44)
    # hdr[0:4] = BYTECNT filled below
    hdr[8:12]  = _p4(len(body))      # LENGTH
    hdr[14]    = 4                    # NUMLEN
    hdr[15]    = 2                    # VERSION
    hdr[16:20] = _p4(banksize)        # BANKSIZE
    hdr[20:22] = _p2(kind)            # KIND
    hdr[24:28] = _p4(org)             # ORG
    hdr[34:36] = _p2(segnum)          # SEGNUM
    hdr[40:42] = _p2(dispname)        # DISPNAME
    hdr[42:44] = _p2(dispdata)        # DISPDATA

    # LCONST: opcode 0xF2 + 4-byte count + body bytes
    body_rec = bytes([0xF2]) + _p4(len(body)) + body + tail_recs + bytes([0x00])  # + END

    seg = bytearray(hdr) + lname_field + sname_field + body_rec
    seg[0:4] = _p4(len(seg))          # BYTECNT
    return bytes(seg)


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
