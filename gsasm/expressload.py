"""gsasm/expressload.py — ExpressLoad relinker (M4).

Converts a plain multi-segment OMF object file (as produced by omf.emit on
a single Asm object, or as returned by linkiigs.link in segmented mode) into
the ExpressLoad "fast-load" format recognised by the System 6 Loader:

  expressload(objects, opts) -> bytes

where ``objects`` matches the linkiigs.link() signature.

The inverse — extracting the flat code image back out — is de_express(),
moved here from work/toolcheck.py (toolcheck still imports it from here).

Page-list codec helpers:
  parse_super(seg_bytes) -> {type: [offsets]}   decode SUPER records in a seg
  emit_super(super_type, offsets) -> bytes       encode as one SUPER record

ExpressLoad format:
  [~ExpressLoad seg (KIND=0x8001)] + [main load seg] + ...

Main load segment body:
  LCONST(code_image) + SUPER(type=0) + SUPER(type=1) + SUPER(type=27) + END

~ExpressLoad LCONST (HET — Header Entry Table):
  6-byte HET header + per-segment entry (68 bytes) + name (1+len bytes)
  For nseg=1: header = 6 zeros.
  For nseg>1: header bytes [4..5] = nseg-1 (word); entry fields shifted by 16.
"""

from __future__ import annotations
import struct
from typing import Any

from . import omf as _omf
from . import link as _link
from . import linkiigs as _linkiigs


# ---------------------------------------------------------------------------
# SUPER page-list codec
# ---------------------------------------------------------------------------

def parse_super(seg_bytes: bytes) -> dict[int, list[int]]:
    """Decode all SUPER records in *seg_bytes* (a single OMF segment).

    Returns ``{super_type: sorted_list_of_byte_offsets}``.
    Ignores all non-SUPER records (LCONST, END, …).
    """
    result: dict[int, list[int]] = {}
    dd = _omf.parse_header(seg_bytes)['DISPDATA']
    off = dd
    while off < len(seg_bytes):
        op = seg_bytes[off]
        if op == 0x00:          # END
            break
        if op == 0xF2:          # LCONST
            sz = struct.unpack_from('<I', seg_bytes, off + 1)[0]
            off += 5 + sz
        elif op == 0xF7:        # SUPER
            total_size = struct.unpack_from('<I', seg_bytes, off + 1)[0]
            super_type  = seg_bytes[off + 5]
            page_list   = seg_bytes[off + 6 : off + 5 + total_size]
            offsets = _decode_page_list(page_list)
            result.setdefault(super_type, []).extend(offsets)
            off += 5 + total_size
        else:
            # Unknown/unsupported record: bail
            break
    return result


def _decode_page_list(page_list: bytes | bytearray) -> list[int]:
    """Decode a SUPER page-list, returning a sorted list of patch byte offsets."""
    offsets: list[int] = []
    cur_page = 0
    i = 0
    while i < len(page_list):
        b = page_list[i]; i += 1
        if b & 0x80:
            # Skip (b & 0x7f) + 1 pages
            cur_page += (b & 0x7f) + 1
        else:
            # (b & 0x7f) + 1 offset bytes follow for patches in cur_page
            cnt = (b & 0x7f) + 1
            for _ in range(cnt):
                offsets.append(cur_page * 256 + page_list[i])
                i += 1
            cur_page += 1
    return offsets


def emit_super(super_type: int, offsets: list[int]) -> bytes:
    """Encode *offsets* (must be sorted) as a single SUPER record.

    Returns the complete SUPER record bytes (opcode 0xF7 included).
    """
    if not offsets:
        return b''

    page_list = _encode_page_list(sorted(offsets))
    # total_size = 1 (type byte) + len(page_list)
    total_size = 1 + len(page_list)
    return (bytes([0xF7])
            + struct.pack('<I', total_size)
            + bytes([super_type])
            + page_list)


def _encode_page_list(sorted_offsets: list[int]) -> bytes:
    """Encode a sorted list of byte offsets as a SUPER page-list."""
    if not sorted_offsets:
        return b''

    # Group offsets by page (256-byte page)
    pages: dict[int, list[int]] = {}
    for offset in sorted_offsets:
        page, byte_in_page = divmod(offset, 256)
        pages.setdefault(page, []).append(byte_in_page)

    out = bytearray()
    cur_page = 0
    for page in sorted(pages):
        # Emit skip bytes if needed
        skip = page - cur_page
        while skip > 0:
            chunk = min(skip, 128)  # skip count fits in 7 bits + 1
            out.append(0x80 | (chunk - 1))
            skip -= chunk
            cur_page += chunk

        # Emit patch-count byte + offset bytes for this page
        patch_bytes = pages[page]
        assert len(patch_bytes) <= 128
        out.append(len(patch_bytes) - 1)  # bit7=0; count = value+1
        out.extend(patch_bytes)
        cur_page += 1  # advance past this page

    return bytes(out)


# ---------------------------------------------------------------------------
# de_express — move from work/toolcheck.py (kept backward-compatible)
# ---------------------------------------------------------------------------

def de_express(path_or_bytes) -> bytes:
    """Return the concatenated CONST/LCONST code image of an ExpressLoad'd tool.

    Accepts either a filesystem path (str/Path) or raw bytes.  The
    ``~ExpressLoad`` directory segment is skipped; all other segments'
    CONST/LCONST bytes are concatenated in order.
    """
    if isinstance(path_or_bytes, (str, bytes)) and not isinstance(path_or_bytes, bytes):
        data = open(path_or_bytes, 'rb').read()
    elif hasattr(path_or_bytes, '__fspath__') or hasattr(path_or_bytes, 'read'):
        # Path-like or file object
        try:
            data = open(path_or_bytes, 'rb').read()
        except TypeError:
            data = path_or_bytes.read()
    else:
        data = bytes(path_or_bytes)

    off = 0
    img = bytearray()
    while off < len(data):
        h = _omf.parse_header(data[off:])
        bc = h['BYTECNT']
        if bc == 0:
            break
        nm = h['SEGNAME'].decode('mac_roman', 'replace').strip()
        if not nm.startswith('~ExpressLoad'):
            recs, _ = _omf.parse_records(
                data[off:off + bc], h['DISPDATA'],
                h.get('NUMLEN', 4), h.get('LABLEN', 0))
            img += b''.join(r[2] for r in recs if r[1] in ('CONST', 'LCONST'))
        off += bc
    return bytes(img)


# ---------------------------------------------------------------------------
# Relocation scanning
# ---------------------------------------------------------------------------

# OMF LEXPR/BEXPR → SUPER type mapping
# size=2,  shift=0  → type  0 (16-bit addr; lda #Label)
# size=3,  shift=0  → type  1 (24-bit addr; DC.L label, size=3 patch)
# size=4,  shift=0  → type  1 (24-bit addr; DC.L label, size=4 but only 24 bits needed)
# size=2,  shift=16 → type 27 (bank byte;   lda #^Label)

_SUPER_TYPE: dict[tuple[int, int], int] = {
    (2, 0): 0,
    (3, 0): 1,
    (4, 0): 1,
    (2, 16): 27,
}


def _get_shift(ops: list) -> int:
    """Extract the right-shift amount from an OMF expression op-list.

    The shift value is encoded as a negative literal before a SHL (0x07)
    operator.  E.g. ``[sym, lit(-16), op(SHL)]`` → shift = 16.
    Returns 0 if no shift is found.
    """
    for idx, op in enumerate(ops):
        if isinstance(op, tuple) and op[0] == 'op' and op[1] == 0x07:
            if idx > 0 and isinstance(ops[idx - 1], tuple) and ops[idx - 1][0] == 'lit':
                neg_shift = ops[idx - 1][1]
                if neg_shift == 0:
                    return 0
                # neg_shift is unsigned 32-bit; convert to signed
                signed = neg_shift if neg_shift < 0x80000000 else neg_shift - 0x100000000
                return int(-signed)  # shift = -neg_shift
    return 0


def _scan_relocs(
        placed: list[tuple[str, list, int, dict, Any]],
) -> dict[int, list[int]]:
    """Scan LEXPR/BEXPR/EXPR records in all placed segments and return
    ``{super_type: sorted_list_of_absolute_byte_offsets}``
    (absolute = seg_base + body_offset_within_seg).
    """
    relocs: dict[int, list[int]] = {}
    for _segname, recs, seg_base, _hdr, _asm in placed:
        body_off = 0
        for _, nm, d in recs:
            if nm == 'END':
                break
            if nm in ('CONST', 'LCONST'):
                body_off += len(d)
            elif nm in ('LEXPR', 'BEXPR', 'EXPR'):
                size = d[0]
                ops  = d[1]
                shift = _get_shift(ops)
                stype = _SUPER_TYPE.get((size, shift))
                if stype is not None:
                    relocs.setdefault(stype, []).append(seg_base + body_off)
                body_off += size
            elif nm == 'RELEXPR':
                body_off += d[0]
            elif nm == 'DS':
                body_off += d
    # Sort each list
    for k in relocs:
        relocs[k].sort()
    return relocs


# ---------------------------------------------------------------------------
# ~ExpressLoad HET (Header Entry Table) LCONST builder
# ---------------------------------------------------------------------------

def _build_het_lconst(
        segs: list[dict],
        seg_file_offsets: list[int],
) -> bytes:
    """Build the LCONST payload for the ~ExpressLoad directory segment.

    Parameters
    ----------
    segs
        List of dicts (one per main load segment), each with keys:
        ``hdr`` (parsed OMF header), ``body`` (resolved body bytes).
        Ordered as they will appear in the output file.
    seg_file_offsets
        File offset of each segment in the output file.  The ~ExpressLoad
        segment itself is at offset 0; the first main segment is at offset
        ``~ExpressLoad.BYTECNT``, etc.

    Returns
    -------
    bytes
        The HET LCONST payload (not including the LCONST opcode/count prefix).
    """
    nseg = len(segs)

    # ---- 6-byte HET header ----
    # [0..3] = 0x00000000 (reserved)
    # [4..5] = nseg - 1 (word, 0 for single-segment tools)
    header = struct.pack('<I', 0) + struct.pack('<H', nseg - 1)

    # ---- Per-segment entry bodies (68 bytes each) + names ----
    # Field layout (0-indexed within the 68-byte body):
    #   [0]       = 0x0a for nseg=1; differs for multi-seg (see below)
    #   [8..9]    = segnum (word)
    #   [10..13]  = code_start = file_off + DISPDATA + 5
    #   [14..17]  = LENGTH
    #   [18..21]  = reloc_start = code_start + LENGTH
    #   [22..25]  = reloc_size = BYTECNT - DISPDATA - 5 - LENGTH - 1
    #   [28]      = NUMLEN = 4
    #   [29]      = VERSION = 2
    #   [32]      = 0x01
    #   [35]      = KIND >> 8
    #   [48..51]  = segnum (4 bytes)
    #   [54..57]  = DISPNAME (4 bytes) = 0x2c
    #
    # For nseg > 1, an extra 16-byte block is inserted before the entry bodies.
    # Empirically (from Tool020): entries start at LCONST[22] for 2-seg tools,
    # adding segnum_0 at [16..17], segnum_1 at [18..19], code_start_0 at [26..29].
    # The extra 16 bytes hold the segment-count table used by setup_seg_ptrs.

    # Build each entry body
    entry_bytes_list: list[bytes] = []
    for i, seg_info in enumerate(segs):
        h   = seg_info['hdr']
        foff = seg_file_offsets[i]
        body = seg_info['body']

        segnum     = h['SEGNUM']
        kind       = h['KIND']
        dispdata   = h['DISPDATA']
        length     = len(body)            # resolved body length
        dispname   = h.get('DISPNAME', 44)

        code_start  = foff + dispdata + 5  # file offset of first code byte
        reloc_start = code_start + length
        # reloc_size = size of SUPER records + END byte
        reloc_size  = seg_info.get('reloc_size', 0)

        entry = bytearray(68)
        # [0]: 0x0a for single-seg, varies for multi (set later)
        entry[0]    = 0x0a
        struct.pack_into('<H', entry, 8,  segnum)
        struct.pack_into('<I', entry, 10, code_start)
        struct.pack_into('<I', entry, 14, length)
        struct.pack_into('<I', entry, 18, reloc_start)
        struct.pack_into('<I', entry, 22, reloc_size)
        entry[28]   = 4          # NUMLEN
        entry[29]   = 2          # VERSION
        entry[32]   = 1          # constant
        entry[35]   = (kind >> 8) & 0xFF   # KIND high byte
        struct.pack_into('<I', entry, 48, segnum)
        struct.pack_into('<I', entry, 54, dispname)

        name_bytes = h['SEGNAME'].rstrip(b'\x00')
        entry_bytes_list.append(bytes(entry) + bytes([len(name_bytes)]) + name_bytes)

    # For multi-segment tools the layout is more complex (extra 16-byte header
    # block). For now we handle nseg=1 correctly; nseg>1 will need more work.
    lconst = header + b''.join(entry_bytes_list)
    return lconst


def _build_express_seg(lconst_payload: bytes) -> bytes:
    """Build the complete ~ExpressLoad directory segment."""
    segname   = b'~ExpressLoad'
    loadname  = b'\x00' * 10
    sname_field = bytes([len(segname)]) + segname  # 13 bytes
    dispname  = 44
    dispdata  = dispname + 10 + len(sname_field)   # 44 + 10 + 13 = 67

    length    = len(lconst_payload)
    kind      = 0x8001
    banksize  = 0

    hdr = bytearray(44)
    # hdr[0..3] = BYTECNT (filled below)
    struct.pack_into('<I', hdr, 8,  length)     # LENGTH
    hdr[14] = 4                                  # NUMLEN
    hdr[15] = 2                                  # VERSION
    struct.pack_into('<I', hdr, 16, banksize)    # BANKSIZE
    struct.pack_into('<H', hdr, 20, kind)        # KIND
    struct.pack_into('<H', hdr, 34, 1)           # SEGNUM
    struct.pack_into('<H', hdr, 40, dispname)    # DISPNAME
    struct.pack_into('<H', hdr, 42, dispdata)    # DISPDATA

    # LCONST record
    body_rec = bytes([0xF2]) + struct.pack('<I', length) + lconst_payload + bytes([0x00])

    seg = bytearray(hdr) + loadname + sname_field + body_rec
    struct.pack_into('<I', seg, 0, len(seg))    # BYTECNT
    return bytes(seg)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def expressload(
        objects: list[tuple[bytes, Any | None]],
        opts: dict | None = None,
) -> bytes:
    """Convert OMF object(s) to ExpressLoad format.

    Parameters
    ----------
    objects
        Same as ``linkiigs.link(objects, …)`` — list of
        ``(obj_bytes, asm_or_None)`` pairs.
    opts
        Passed to the internal linker.  ``merge`` is forced to ``False``
        (segmented output is required).

    Returns
    -------
    bytes
        An ExpressLoad OMF file: ``[~ExpressLoad seg] + [main seg] + …``
    """
    if opts is None:
        opts = {}
    # We must have segmented (not merged) output for the reloc scan.
    opts = dict(opts, merge=False)

    # ------------------------------------------------------------------
    # Pass 1: parse inputs and place segments (mirrors linkiigs logic)
    # ------------------------------------------------------------------
    placed: list[tuple[str, list, int, dict, Any | None]] = []
    obj_seg_bases: list[list[int]] = []

    base = 0
    for obj_bytes, asm_obj in objects:
        segs = _linkiigs._parse_obj(obj_bytes)
        bases_this_obj: list[int] = []
        for seg in segs:
            h = seg['hdr']
            seg_org = h['ORG'] or 0
            seg_base = seg_org if seg_org else base
            placed.append((seg['segname'], seg['recs'], seg_base, h, asm_obj))
            bases_this_obj.append(seg_base)
            base = seg_base + _link._body_length(seg['recs'])
        obj_seg_bases.append(bases_this_obj)

    if not placed:
        return b''

    # ------------------------------------------------------------------
    # Pass 2: build global symbol table (mirrors linkiigs.link)
    # ------------------------------------------------------------------
    sym: dict[str, int] = {'__LOC__': 0}
    placed_idx = 0

    for obj_idx, (obj_bytes, asm_obj) in enumerate(objects):
        segs_in_obj = _linkiigs._parse_obj(obj_bytes)
        n_segs = len(segs_in_obj)
        bases_this_obj = obj_seg_bases[obj_idx]

        for k in range(n_segs):
            segname, _recs, seg_base, _hdr, _asm = placed[placed_idx + k]
            sym.setdefault(segname, seg_base)

        if asm_obj is not None:
            asm_segs = [s for s in asm_obj.segs if s.items or s.name]
            for lab, v in asm_obj.symbols.items():
                sg_idx = asm_obj.symseg.get(lab)
                if sg_idx is None:
                    continue
                if not isinstance(v, int):
                    continue
                if sg_idx < 0 or sg_idx >= len(asm_segs):
                    continue
                try:
                    emit_idx = asm_segs.index(asm_obj.segs[sg_idx])
                except (ValueError, IndexError):
                    continue
                if emit_idx >= len(bases_this_obj):
                    continue
                seg_placed_base = bases_this_obj[emit_idx]
                seg_obj = asm_obj.segs[sg_idx]
                seg_own_org = seg_obj.org or 0
                if seg_own_org:
                    sym.setdefault(lab.upper(), v & 0xFFFFFF)
                else:
                    sym.setdefault(lab.upper(), (seg_placed_base + v) & 0xFFFFFF)

        placed_idx += n_segs

    for _segname, recs, seg_base, _hdr, _asm in placed:
        body_off = 0
        for _, nm, d in recs:
            if nm == 'END':
                break
            if nm in ('CONST', 'LCONST'):
                body_off += len(d)
            elif nm in ('LEXPR', 'BEXPR', 'EXPR', 'RELEXPR'):
                body_off += d[0]
            elif nm == 'DS':
                body_off += d
            elif nm == 'GLOBAL':
                label = d['label'].upper()
                sym.setdefault(label, seg_base + body_off)
            elif nm == 'GEQU':
                label = d['label'].upper()
                sym.setdefault(label, _link._eval(d['expr'], sym))

    for k, v in (opts.get('extern') or {}).items():
        sym[k.upper()] = v

    # ------------------------------------------------------------------
    # Pass 3: scan reloc records BEFORE resolving bodies
    # ------------------------------------------------------------------
    relocs_by_type = _scan_relocs(placed)

    # ------------------------------------------------------------------
    # Pass 4: resolve each segment's body
    # ------------------------------------------------------------------
    bodies: list[bytes] = [
        _link._build_body(recs, sym, seg_base)
        for (_segname, recs, seg_base, _hdr, _asm) in placed
    ]

    # ------------------------------------------------------------------
    # Pass 5: merge all bodies into one flat code image (single main seg)
    # ------------------------------------------------------------------
    # Tools are single-segment in ExpressLoad output (all segs merged into
    # one big LCONST, same as merge=True linkiigs output).
    merged_body = b''.join(bodies)

    # Build SUPER records
    super_records = bytearray()
    for stype in sorted(relocs_by_type):
        super_records += emit_super(stype, relocs_by_type[stype])
    super_records += b'\x00'   # END record

    # Build the main load segment.
    # The merged output is always named 'main' (matching MPW LinkIIgs -t TOL output).
    first_hdr = placed[0][3]
    out_name = b'main'
    out_load = b'\x00' * 10
    out_kind = opts.get('kind') or first_hdr['KIND']
    # DISPNAME and DISPDATA are the same as a standard _make_segment would build
    sname_field = bytes([len(out_name)]) + out_name
    out_dispname = 44
    out_dispdata = out_dispname + 10 + len(sname_field)

    # LCONST record for code image
    lconst_rec = bytes([0xF2]) + struct.pack('<I', len(merged_body)) + merged_body

    # Full body records = LCONST + SUPERs + END (END already in super_records)
    full_body_bytes = lconst_rec + bytes(super_records)

    # Build header
    hdr_main = bytearray(44)
    struct.pack_into('<I', hdr_main,  8, len(merged_body))   # LENGTH
    hdr_main[14] = 4                                          # NUMLEN
    hdr_main[15] = 2                                          # VERSION
    struct.pack_into('<I', hdr_main, 16, 0)                   # BANKSIZE=0 for data
    struct.pack_into('<H', hdr_main, 20, out_kind)            # KIND
    struct.pack_into('<H', hdr_main, 34, 2)                   # SEGNUM=2
    struct.pack_into('<H', hdr_main, 40, out_dispname)        # DISPNAME
    struct.pack_into('<H', hdr_main, 42, out_dispdata)        # DISPDATA

    main_seg = bytearray(hdr_main) + (out_load + b'\x00'*10)[:10] + sname_field + full_body_bytes
    struct.pack_into('<I', main_seg, 0, len(main_seg))        # BYTECNT

    # ------------------------------------------------------------------
    # Pass 6: build ~ExpressLoad HET and directory segment
    # ------------------------------------------------------------------
    # We need the file offset of main_seg.  ~ExpressLoad seg comes first.
    # Compute ~ExpressLoad BYTECNT first (depends on LCONST size).
    # We'll do a two-pass: estimate, build, confirm.

    # Estimate: reloc_size = len(super_records) = SUPERs + END
    reloc_size_val = len(super_records)

    # ~ExpressLoad LCONST payload (HET)
    het_input = [{
        'hdr': {
            'SEGNUM': 2,
            'KIND': out_kind,
            'DISPDATA': out_dispdata,
            'DISPNAME': out_dispname,
            'SEGNAME': out_name,   # b'main'
            'LOADNAME': (out_load + b'\x00'*10)[:10],
        },
        'body': merged_body,
        'reloc_size': reloc_size_val,
    }]
    # The ~ExpressLoad seg BYTECNT = len(_build_express_seg(lconst_payload))
    # We need the file offset of main_seg, which = ~ExpressLoad BYTECNT.
    # Bootstrap: first build with placeholder file_off=0, then fix.
    lconst_payload0 = _build_het_lconst(het_input, [0])
    express_seg0 = _build_express_seg(lconst_payload0)
    express_bc = len(express_seg0)

    # Now rebuild with correct file offset
    lconst_payload = _build_het_lconst(het_input, [express_bc])
    express_seg = _build_express_seg(lconst_payload)

    # Sanity check: express_bc should not have changed
    assert len(express_seg) == express_bc, (
        f"~ExpressLoad segment size changed: {len(express_seg)} != {express_bc}")

    return bytes(express_seg) + bytes(main_seg)
