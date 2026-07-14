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
    """Decode a SUPER page-list, returning a sorted list of patch byte offsets.

    Format (matching the GS/OS Loader implementation):
      - A byte with bit7=1 is a skip header: advance cur_page by (b & 0x7f) pages.
      - A byte with bit7=0 is a count header: (b & 0x7f)+1 offset bytes follow for
        cur_page, then cur_page advances by 1.
    """
    offsets: list[int] = []
    cur_page = 0
    i = 0
    while i < len(page_list):
        b = page_list[i]; i += 1
        if b & 0x80:
            # Skip (b & 0x7f) pages — note: no +1; matches loader behaviour exactly.
            cur_page += b & 0x7f
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
        # Emit skip bytes if needed: each skip byte can advance at most 127 pages
        # (7-bit field); no +1 adjustment — matches the GS/OS Loader decoder exactly.
        skip = page - cur_page
        while skip > 0:
            chunk = min(skip, 127)   # 7-bit field: max value 127
            out.append(0x80 | chunk)
            skip -= chunk
            cur_page += chunk

        # Emit patch-count byte + offset bytes for this page
        patch_bytes = pages[page]
        assert len(patch_bytes) <= 128
        out.append(len(patch_bytes) - 1)  # bit7=0; count = value+1
        out.extend(patch_bytes)
        cur_page += 1  # advance past this page

    return bytes(out)


def emit_creloc(size: int, shift: int, offset: int, rel_offset: int) -> bytes:
    """Encode one cRELOC record (0xF5): compressed same-segment relocation.

    Layout: opcode(0xF5) + bytesInOperand(1) + bitShiftCount(1, signed) +
    offset(2) + relOffset(2).  ``shift`` is the positive right-shift amount (as
    returned by ``_get_shift``); the stored bitShiftCount is its negation.
    """
    return (bytes([0xF5, size & 0xFF, (-shift) & 0xFF])
            + struct.pack('<H', offset & 0xFFFF)
            + struct.pack('<H', rel_offset & 0xFFFF))


def emit_reloc(size: int, shift: int, offset: int, rel_offset: int) -> bytes:
    """Encode one RELOC record (0xE2): full-width same-segment relocation.

    Layout: opcode(0xE2) + bytesInOperand(1) + bitShiftCount(1, signed) +
    offset(4) + relOffset(4).  Used when the offset/relOffset exceed 16 bits.
    """
    return (bytes([0xE2, size & 0xFF, (-shift) & 0xFF])
            + struct.pack('<I', offset & 0xFFFFFFFF)
            + struct.pack('<I', rel_offset & 0xFFFFFFFF))


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


def _has_sym_ref(ops: list) -> bool:
    """Return True if *ops* contains at least one symbol reference (sym* tuple).

    Pure-literal expressions (e.g. ``[('lit', 40), 'end']``) resolve to a
    compile-time constant and never need a load-time SUPER relocation.
    """
    return any(isinstance(op, tuple) and op[0].startswith('sym') for op in ops)




def _scan_relocs(
        placed: list[tuple[str, list, int, dict, Any]],
) -> dict[int, list[int]]:
    """Scan LEXPR/BEXPR/EXPR records in all placed segments and return
    ``{super_type: sorted_list_of_absolute_byte_offsets}``
    (absolute = seg_base + body_offset_within_seg).

    Only expressions that contain a symbol reference are included; pure
    literals are constant at link time and require no load-time relocation.
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
                if _has_sym_ref(ops):
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


def _scan_standalone_relocs(
        placed: list[tuple[str, list, int, dict, Any]],
) -> list[tuple[int, int, int]]:
    """Relocations MPW ExpressLoad emits as individual cRELOC/RELOC records
    rather than folding into a SUPER record.

    A shifted relocation whose ``(size, shift)`` has NO SUPER encoding must be
    standalone: the >>8 high byte (size 2), and the 1-byte >>16 bank byte
    (``lda #^label`` under ``longa off`` — SUPER type 27 is size 2 only; a
    1-byte patch field also cannot hold the target offset in-image, which is
    why MPW emits the explicit-relOffset record).  Returns a sorted list of
    ``(offset, size, shift, ops)`` (offset = merged-segment-relative byte
    offset; shift = positive right shift; ops = the OMF expression op-list).
    """
    out: list[tuple[int, int, int, list]] = []
    for _segname, recs, seg_base, _hdr, _asm in placed:
        body_off = 0
        for _, nm, d in recs:
            if nm == 'END':
                break
            if nm in ('CONST', 'LCONST'):
                body_off += len(d)
            elif nm in ('LEXPR', 'BEXPR', 'EXPR'):
                size = d[0]
                ops = d[1]
                if _has_sym_ref(ops):
                    shift = _get_shift(ops)
                    if shift and (size, shift) not in _SUPER_TYPE:
                        out.append((seg_base + body_off, size, shift, ops))
                body_off += size
            elif nm == 'RELEXPR':
                body_off += d[0]
            elif nm == 'DS':
                body_off += d
    out.sort()
    return out


def _scan_case_b(
        placed: list[tuple[str, list, int, dict, Any]],
        sym: dict,
) -> list[tuple[int, int, int, int]]:
    """Relocations whose *unshifted* target carries addend bits >= bit 24 —
    e.g. a ModalDialog filterProc/hook pointer written in source as
    ``#Label+$80000000`` or ``#Label+$C0000000`` (bit 31 / bit 30 conventions).

    Such a target cannot ride in a SUPER page list: a page-list patch only
    ever restores a clean segment-relative offset (<= 24 bits), never an
    out-of-range flag OR'd on top.  MPW's ExpressLoad converter recognises
    this and emits a standalone RELOC (0xE2) instead, whose relOffset is the
    FULL, un-shifted 32-bit expression value (flag bits included) — even for
    the paired high-word (``shift=16``, e.g. ``lda #^(Label+$80000000)``) half
    of a far-pointer PEA pair, which stores the SAME full value as its
    low-word (``shift=0``) partner, not the value shifted right 16.

    Confirmed against the golden corpus (work/reloc_survey.py, docs/TODO.md
    section 1): all 9 flagged case-B records are ``(size, shift)`` in
    ``{(2, 0), (2, 16)}`` — SUPER types 0 and 27, the far-pointer PEA-pair /
    bank-byte filter-hook idiom.  Restricting to those two (size, shift) pairs
    (rather than every ``(size, shift)`` in ``_SUPER_TYPE``, which also
    includes the 3/4-byte ``dc.l routine-1`` dispatch-table entries) matters:
    the dispatch idiom's "-1" is OMF-encoded as ``ADD lit=0xFFFFFFFF``
    (two's-complement), and if the referenced routine symbol is unresolved for
    an unrelated reason (a unresolved-symbol linkage bug, e.g. Tool023/Tool027's
    known symbol-scoping residuals) that evaluates to 0xFFFFFFFF too — an
    accident that must not be mistaken for a deliberate flagged addend.

    Returns a sorted list of ``(offset, size, shift, flagged_value)`` —
    offset = merged-segment-relative byte offset; flagged_value = the full
    32-bit relOffset to emit (unmasked).
    """
    out: list[tuple[int, int, int, int]] = []
    for _segname, recs, seg_base, _hdr, _asm in placed:
        body_off = 0
        for _, nm, d in recs:
            if nm == 'END':
                break
            if nm in ('CONST', 'LCONST'):
                body_off += len(d)
            elif nm in ('LEXPR', 'BEXPR', 'EXPR'):
                size = d[0]
                ops = d[1]
                if _has_sym_ref(ops):
                    shift = _get_shift(ops)
                    if _SUPER_TYPE.get((size, shift)) in (0, 27):
                        ops_wo = ops
                        if (shift and len(ops) >= 4 and ops[-1] == 'end'
                                and ops[-2] == ('op', 7)
                                and isinstance(ops[-3], tuple)
                                and ops[-3][0] == 'lit'):
                            ops_wo = ops[:-3] + ['end']
                        site = seg_base + body_off
                        sym['__LOC__'] = site
                        val = _link._eval(ops_wo, sym) & 0xFFFFFFFF
                        if val > 0xFFFFFF:
                            out.append((site, size, shift, val))
                body_off += size
            elif nm == 'RELEXPR':
                body_off += d[0]
            elif nm == 'DS':
                body_off += d
    out.sort()
    return out


# ---------------------------------------------------------------------------
# ~ExpressLoad HET (Header Entry Table) LCONST builder
# ---------------------------------------------------------------------------

def _make_suffix_template(kind: int, segnum: int, dispname: int = 44,
                          align: int = 0) -> bytes:
    """Build the 42-byte suffix template for one output segment's HET entry.

    The template mirrors the OMF segment header shifted by 12
    (template[k] = header[k+12]): NUMLEN/VERSION at [2..3], BANKSIZE at
    [4..7], KIND at [8..9], ALIGN at [16..19], SEGNUM at [22..25],
    DISPNAME at [28..31].

    The full template is:
      [0..1]   = 0x0000
      [2]      = NUMLEN = 4
      [3]      = VERSION = 2
      [4..5]   = 0x0000
      [6]      = 0x01
      [7]      = 0x00
      [8..9]   = KIND as LE 16-bit word
      [10..15] = 6 zero bytes
      [16..19] = ALIGN as LE dword (`PROC align N` — max of the input
                 segments' alignments, same value as the stored output
                 segment header's ALIGN)
      [20..21] = 0x0000
      [22..25] = SEGNUM as LE dword
      [26..27] = 0x0000
      [28..31] = DISPNAME as LE dword
      [32..41] = 10 zero bytes
    """
    return (bytes([0, 0, 4, 2, 0, 0, 1, 0])
            + struct.pack('<H', kind)
            + bytes(6)
            + struct.pack('<I', align)
            + bytes(2)
            + struct.pack('<I', segnum)
            + bytes(2)
            + struct.pack('<I', dispname)
            + bytes(10))


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

    HET layout (byte-exact match against gold ExpressLoad binaries):

    N = number of load segments.

    Offset 0..5    : 6-byte header: [0..3]=0, [4..5]=N-1 LE word
    Offset 6..6+N*8-1 : extra_block, N items of 8 bytes each:
                       item[i] = [entry_ptr_i (LE dword), 0x00000000]
                       entry_ptr_i = absolute offset of entry_i within HET
    Offset 6+N*8 .. 10*N-1 : pre-section segnums (only if N>3):
                       max(0, N-3) * 2 bytes = first N-3 SEGNUMs as LE words
    Offset 10*N onward: entry bodies, structured as described below.

    Entry bodies (chained suffix-spill design):
    - entry_1: [segnums(6)] [code_start(4)] [length(4)] [reloc_start(4)]
               [reloc_size(4)] [partial_suffix_1 bytes]
    - entry_i (2..N-1): [spill_{i} bytes] [name_len(1)] [prev_name]
               [code_start(4)] [length(4)] [reloc_start(4)] [reloc_size(4)]
               [partial_suffix_i bytes]
    - entry_N: [spill_N bytes] [name_len(1)] [prev_name_N-1]
               [code_start(4)] [length(4)] [reloc_start(4)] [reloc_size(4)]
               [full_suffix_42 bytes] [name_N_len(1)] [name_N bytes]

    The "42-byte suffix template" for segment j encodes KIND, SEGNUM, DISPNAME.
    Each intermediate entry emits a prefix of this template; the remainder
    spills into the NEXT entry's prefix area.

    Entry1 partial suffix bytes = 37 (N>=3), 36 (N=2), or 42 (N=1).
    Intermediate entry_i size = 59 + 2*(KIND_i == 0x0002).
    """
    N = len(segs)

    # ---- 6-byte HET header ----
    header = struct.pack('<I', 0) + struct.pack('<H', N - 1)

    if N == 1:
        # ---- N=1: single-segment path (existing validated logic) ----
        # The 'entry' block of 68 bytes starts at payload[6].
        # Its first 8 bytes encode the extra_block item (ptr=10, zeros=0).
        # The real entry body starts at payload[10].
        seg_info = segs[0]
        h        = seg_info['hdr']
        foff     = seg_file_offsets[0]
        body     = seg_info['body']
        segnum   = h['SEGNUM']
        kind     = h['KIND']
        dispdata = h['DISPDATA']
        length   = len(body)
        dispname = h.get('DISPNAME', 44)

        code_start  = foff + dispdata + 5
        reloc_start = code_start + length
        reloc_size  = seg_info.get('reloc_size', 0)

        entry = bytearray(68)
        entry[0] = 0x0a                              # entry_ptr lo byte (ptr=10)
        struct.pack_into('<H', entry,  8, segnum)    # sn1 word (right-justified)
        struct.pack_into('<I', entry, 10, code_start)
        struct.pack_into('<I', entry, 14, length)
        struct.pack_into('<I', entry, 18, reloc_start)
        struct.pack_into('<I', entry, 22, reloc_size)
        entry[28] = 4   # NUMLEN
        entry[29] = 2   # VERSION
        entry[32] = 1   # constant
        # KIND as LE word at entry[34..35] (suffix offset 8..9 from entry body start)
        struct.pack_into('<H', entry, 34, kind)
        struct.pack_into('<I', entry, 42, h.get('ALIGN', 0))  # ALIGN dword
        struct.pack_into('<I', entry, 48, segnum)    # SEGNUM dword
        struct.pack_into('<I', entry, 54, dispname)  # DISPNAME dword

        name_bytes = h['SEGNAME'].rstrip(b'\x00')
        return header + bytes(entry) + bytes([len(name_bytes)]) + name_bytes

    # ---- N>1: multi-segment path ----

    # Build the 42-byte suffix template for each output segment.
    templates = []
    for seg_info in segs:
        h = seg_info['hdr']
        templates.append(_make_suffix_template(
            h['KIND'], h['SEGNUM'], h.get('DISPNAME', 44),
            h.get('ALIGN', 0)
        ))

    # Compute partial_suffix sizes for each entry.
    # partial_suffix[0] = bytes of template[0] emitted in entry1
    # spill[i+1]        = 42 - partial_suffix[i]
    # partial_suffix[i] (2<=i<=N-2, intermediate) = entry_i_size - spill[i] - 1 - name_len[i-1] - 16
    # entry_i_size for intermediate = 59 + 2*(KIND_i == 0x0002)

    partial1 = 37 if N >= 3 else 36   # bytes of template[0] emitted in entry1

    partial = [partial1]
    spill = [0]   # spill[0] unused (entry1 has no prefix)

    # Collect prev_name for each entry (the name embedded IN the entry = name of seg_{i-1})
    # entry_2 embeds name of seg1, entry_3 embeds name of seg2, etc.
    prev_names = []
    for i in range(N):
        prev_names.append(segs[i]['hdr']['SEGNAME'].rstrip(b'\x00'))

    for i in range(1, N):    # i = 0-based entry index (entry i+1 in 1-based)
        spill_i = 42 - partial[i - 1]
        spill.append(spill_i)
        if i < N - 1:
            # Intermediate entry (1-based: entry_{i+1})
            kind_i = segs[i]['hdr']['KIND']
            entry_size = 59 + 2 * (kind_i == 0x0002)
            name_len_prev = len(prev_names[i - 1])
            partial_i = entry_size - spill_i - 1 - name_len_prev - 16
            partial.append(partial_i)
        # last entry: no partial to compute (emits full template + trailing name)

    # Pre-section segnums (only for N>3): first N-3 SEGNUMs as LE words.
    pre_section = bytearray()
    if N > 3:
        for i in range(N - 3):
            sn = segs[i]['hdr']['SEGNUM']
            pre_section += struct.pack('<H', sn)

    # Entry1 segnums (last min(N,3) SEGNUMs, right-justified in 6 bytes):
    # Gold format: 6 bytes with segnums packed at the RIGHT end.
    # For N=2: bytes = [0x0000, sn0_LE16, sn1_LE16]
    # For N=3: bytes = [sn0_LE16, sn1_LE16, sn2_LE16]
    sn_count = min(N, 3)
    segnums_bytes = bytearray(6)
    pad_start = (3 - sn_count) * 2
    for k in range(sn_count):
        seg_k = segs[N - sn_count + k]
        struct.pack_into('<H', segnums_bytes, pad_start + k * 2, seg_k['hdr']['SEGNUM'])

    # Build entry bodies in sequence.
    # We build the HET body bytes from offset 6+N*8 onward.
    # The extra_block pointers must reference absolute HET offsets.
    entry_body_parts: list[bytes] = []   # one element per entry
    body_start_offsets: list[int] = []   # absolute HET offset of each entry's start

    # Entry1 body start = 10*N
    cur_offset = 10 * N

    # ---- Entry 1 ----
    seg1 = segs[0]
    h1   = seg1['hdr']
    foff1 = seg_file_offsets[0]
    code_start1  = foff1 + h1['DISPDATA'] + 5
    reloc_size1  = seg1.get('reloc_size', 0)
    # When reloc_size=0, the gold stores reloc_start=0 as well.
    reloc_start1 = (code_start1 + len(seg1['body'])) if reloc_size1 else 0

    entry1 = bytearray()
    entry1 += segnums_bytes                              # [0..5] segnums
    entry1 += struct.pack('<I', code_start1)             # [6..9]
    entry1 += struct.pack('<I', len(seg1['body']))       # [10..13]
    entry1 += struct.pack('<I', reloc_start1)            # [14..17]
    entry1 += struct.pack('<I', reloc_size1)             # [18..21]
    entry1 += templates[0][:partial[0]]                  # partial suffix

    body_start_offsets.append(cur_offset)
    entry_body_parts.append(bytes(entry1))
    cur_offset += len(entry1)

    # ---- Entries 2..N-1 (intermediate) ----
    for i in range(1, N - 1):
        spill_i = spill[i]
        seg_i   = segs[i]
        h_i     = seg_i['hdr']
        foff_i  = seg_file_offsets[i]
        prev_name = prev_names[i - 1]

        code_start_i  = foff_i + h_i['DISPDATA'] + 5
        reloc_size_i  = seg_i.get('reloc_size', 0)
        reloc_start_i = (code_start_i + len(seg_i['body'])) if reloc_size_i else 0

        entry_i = bytearray()
        entry_i += templates[i - 1][42 - spill_i:]      # spill from prev template
        entry_i += bytes([len(prev_name)]) + prev_name  # prev seg name
        entry_i += struct.pack('<I', code_start_i)
        entry_i += struct.pack('<I', len(seg_i['body']))
        entry_i += struct.pack('<I', reloc_start_i)
        entry_i += struct.pack('<I', reloc_size_i)
        entry_i += templates[i][:partial[i]]             # partial suffix

        body_start_offsets.append(cur_offset)
        entry_body_parts.append(bytes(entry_i))
        cur_offset += len(entry_i)

    # ---- Entry N (last) ----
    spill_last = spill[N - 1]
    seg_last   = segs[N - 1]
    h_last     = seg_last['hdr']
    foff_last  = seg_file_offsets[N - 1]
    prev_name_last = prev_names[N - 2]
    name_last  = prev_names[N - 1]

    code_start_last  = foff_last + h_last['DISPDATA'] + 5
    reloc_size_last  = seg_last.get('reloc_size', 0)
    reloc_start_last = (code_start_last + len(seg_last['body'])) if reloc_size_last else 0

    entry_last = bytearray()
    entry_last += templates[N - 2][42 - spill_last:]     # spill from prev template
    entry_last += bytes([len(prev_name_last)]) + prev_name_last  # prev seg name
    entry_last += struct.pack('<I', code_start_last)
    entry_last += struct.pack('<I', len(seg_last['body']))
    entry_last += struct.pack('<I', reloc_start_last)
    entry_last += struct.pack('<I', reloc_size_last)
    entry_last += templates[N - 1]                        # full 42-byte suffix
    entry_last += bytes([len(name_last)]) + name_last    # this seg's name

    body_start_offsets.append(cur_offset)
    entry_body_parts.append(bytes(entry_last))

    # ---- Assemble final HET payload ----
    # The HET layout after the 6-byte header:
    #   - extra_block items at [6..6+N*8-1], each 8 bytes: [ptr_dword, 0x00000000]
    #   - pre_section (N>3 only) at [6+N*8..]
    #   - entry1 at [10*N..], body_start_offsets[0] = 10*N
    #   - entry2, entry3, ... at successive offsets
    #
    # For N<3 the extra_block zone extends past entry1's start (by 2 bytes for
    # N=2, 4 bytes for N=1 -- but N=1 is handled separately above).  The
    # overlap bytes must be written consistently: extra_block's zero padding
    # happens to equal entry1's segnums leading zeros, so both are zeros and
    # there is no actual conflict.  We write everything into a flat buffer.

    # Compute total HET size.
    total = body_start_offsets[-1] + len(entry_body_parts[-1])
    lconst = bytearray(total)

    # Write header.
    lconst[0:6] = header

    # Write extra_block (ptr_dword then 4 zero bytes for each item).
    for i, ptr in enumerate(body_start_offsets):
        struct.pack_into('<I', lconst, 6 + i * 8, ptr)
        # bytes [6+i*8+4 .. 6+i*8+7] remain zero (already zero in bytearray)

    # Write pre_section (non-empty only for N>3).
    if pre_section:
        ps_start = 6 + N * 8
        lconst[ps_start:ps_start + len(pre_section)] = pre_section

    # Write entry bodies.
    pos = body_start_offsets[0]   # = 10*N
    for i, part in enumerate(entry_body_parts):
        lconst[pos:pos + len(part)] = part
        pos += len(part)

    return bytes(lconst)


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

def _make_output_seg(
        out_name: bytes,
        out_kind: int,
        out_segnum: int,
        merged_body: bytes,
        super_records: bytes,
        align: int = 0,
) -> bytes:
    """Build one OMF load segment from a resolved code body and SUPER records.

    Returns the complete OMF segment bytes (header + body records).
    ``super_records`` must already include the trailing END byte (0x00).
    ``align`` — the output header's ALIGN field (max of the input segments'
    ``PROC align`` values; MPW keeps it on the ExpressLoad output segment).
    """
    sname_field  = bytes([len(out_name)]) + out_name
    out_load     = b'\x00' * 10
    out_dispname = 44
    out_dispdata = out_dispname + 10 + len(sname_field)

    # BANKSIZE: 0x10000 for all ExpressLoad output segments (all gold EL files use this).
    banksize = 0x10000

    # LCONST record
    lconst_rec      = bytes([0xF2]) + struct.pack('<I', len(merged_body)) + merged_body
    full_body_bytes = lconst_rec + super_records

    hdr = bytearray(44)
    struct.pack_into('<I', hdr,  8, len(merged_body))   # LENGTH
    hdr[14] = 4                                          # NUMLEN
    hdr[15] = 2                                          # VERSION
    struct.pack_into('<I', hdr, 16, banksize)            # BANKSIZE
    struct.pack_into('<H', hdr, 20, out_kind)            # KIND
    struct.pack_into('<I', hdr, 28, align)               # ALIGN
    struct.pack_into('<H', hdr, 34, out_segnum)          # SEGNUM
    struct.pack_into('<H', hdr, 40, out_dispname)        # DISPNAME
    struct.pack_into('<H', hdr, 42, out_dispdata)        # DISPDATA

    seg = bytearray(hdr) + out_load + sname_field + full_body_bytes
    struct.pack_into('<I', seg, 0, len(seg))             # BYTECNT
    return bytes(seg)


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
        Options dict.  Keys recognised:

        ``merge``
            Forced to ``False`` internally (segmented pass required).
        ``multiseg``
            If ``True`` and there are multiple input objects, produce one
            output load segment per input object.  Defaults to ``False``
            (original behavior: merge everything into a single ``'main'``
            segment regardless of input-object count).
        ``extern``
            Pre-seeded externals passed to the internal linker.
        ``kind``
            KIND override for single-segment output.
        ``segnames``
            List of segment name overrides (bytes) for multi-segment output,
            one per input object group.  If shorter than the number of groups,
            remaining groups use the first placed segment's SEGNAME.
        ``segkinds``
            List of KIND overrides (int) for multi-segment output, one per
            input object group.  If shorter than the number of groups,
            remaining groups use the first placed segment's KIND.

    Returns
    -------
    bytes
        An ExpressLoad OMF file: ``[~ExpressLoad seg] + [load seg(s)] + …``
    """
    if opts is None:
        opts = {}
    # We must have segmented (not merged) output for the reloc scan.
    opts = dict(opts, merge=False)

    multiseg: bool = opts.get('multiseg', False)

    # ------------------------------------------------------------------
    # Pass 1: parse inputs and place segments
    # ------------------------------------------------------------------
    placed, obj_seg_bases, placed_obj_idx = _linkiigs._place(objects, 0)

    if not placed:
        return b''

    # ------------------------------------------------------------------
    # Pass 2: build global symbol table (shared with linkiigs.link)
    # ------------------------------------------------------------------
    sym, obj_globals = _linkiigs._build_symtab(
        objects, placed, obj_seg_bases, placed_obj_idx,
        opts.get('extern') or {}
    )

    # ------------------------------------------------------------------
    # Pass 3 / Pass 4: resolve each segment's body
    # ------------------------------------------------------------------
    # Defer #^/>>16 high-word shifts to SUPER type-27 relocs (consistent with linkiigs).
    bodies: list[bytes] = []
    for placed_i, (_segname, recs, seg_base, _hdr, _asm) in enumerate(placed):
        recs2, _srels = _linkiigs._defer_shifts(recs)
        oi = placed_obj_idx[placed_i]
        local_sym = sym if not obj_globals[oi] else {**sym, **obj_globals[oi]}
        bodies.append(_link._build_body(recs2, local_sym, seg_base))

    # ------------------------------------------------------------------
    # Pass 5: group placed segments into output load segments
    # ------------------------------------------------------------------
    # Single-segment path: all input objects collapsed into one 'main' segment.
    # Multi-segment path: one output segment per input object (when multiseg=True
    # and there are multiple input objects).

    n_objs = len(objects)
    use_multiseg = multiseg and n_objs > 1

    if not use_multiseg:
        # ---- Single-segment output (original behavior) ----
        merged_body = _linkiigs._merge_bodies(placed, bodies)

        # Standalone cRELOC/RELOC records come BEFORE the SUPER records,
        # matching MPW ExpressLoad, sorted together by patch offset (verified:
        # the golden corpus's standalone records are always in ascending-
        # offset order regardless of case A/B — work/reloc_survey.py).
        #
        # Two cases collapse into one combined, offset-sorted list:
        #   case A — a shifted relocation whose (size, shift) has NO SUPER
        #            encoding at all (e.g. the >>8 high-byte cRELOC); its
        #            relOffset is the plain segment-relative target.
        #   case B — a relocation whose (size, shift) WOULD be SUPER-covered,
        #            but whose target expression carries addend bits >= 24
        #            (out of segment-address range, e.g. a ModalDialog
        #            filterProc `#Label+$80000000` convention) and so cannot
        #            ride a SUPER page list; relOffset is the FULL 32-bit
        #            flagged value (see _scan_case_b).
        combined: list[tuple[int, int, int, int]] = []
        for offset, size, shift, ops in _scan_standalone_relocs(placed):
            if size >= 2:
                rel_off = int.from_bytes(merged_body[offset:offset + size],
                                         'little')
            else:
                # a 1-byte field can't hold the target offset — evaluate the
                # expression without its tail shift (same strip as
                # _defer_shifts) against the placed symbol table
                ops_wo = ops
                if (len(ops) >= 4 and ops[-1] == 'end'
                        and ops[-2] == ('op', 7)
                        and isinstance(ops[-3], tuple) and ops[-3][0] == 'lit'):
                    ops_wo = ops[:-3] + ['end']
                rel_off = _link._eval(ops_wo, sym) & 0xFFFFFF
            combined.append((offset, size, shift, rel_off))

        case_b = _scan_case_b(placed, sym)
        combined.extend(case_b)
        combined.sort(key=lambda r: r[0])

        standalone = bytearray()
        for offset, size, shift, rel_off in combined:
            if offset < 0x10000 and rel_off < 0x10000:
                standalone += emit_creloc(size, shift, offset, rel_off)
            else:
                standalone += emit_reloc(size, shift, offset, rel_off)

        # Scan relocs over ALL placed segments, excluding any site case-B
        # already claimed as standalone (it cannot ALSO ride a SUPER page
        # list — that is the whole point of the flag).
        relocs_by_type = _scan_relocs(placed)
        case_b_offsets = {r[0] for r in case_b}
        if case_b_offsets:
            for stype in list(relocs_by_type):
                relocs_by_type[stype] = [o for o in relocs_by_type[stype]
                                         if o not in case_b_offsets]
                if not relocs_by_type[stype]:
                    del relocs_by_type[stype]
        super_records = bytearray()
        for stype in sorted(relocs_by_type):
            super_records += emit_super(stype, relocs_by_type[stype])
        super_records += b'\x00'   # END record

        all_relocs = bytes(standalone) + bytes(super_records)
        first_hdr   = placed[0][3]
        out_name    = b'main'
        out_kind    = opts.get('kind') or first_hdr['KIND']
        out_align   = max((p[3].get('ALIGN') or 0) for p in placed)
        reloc_size_val = len(all_relocs) - 1  # exclude trailing END byte

        main_seg_bytes = _make_output_seg(
            out_name, out_kind, 2, merged_body, all_relocs, align=out_align
        )

        # Parse back the output seg's DISPDATA for HET.
        out_dispname = 44
        sname_field  = bytes([len(out_name)]) + out_name
        out_dispdata = out_dispname + 10 + len(sname_field)

        het_input = [{
            'hdr': {
                'SEGNUM': 2,
                'KIND': out_kind,
                'DISPDATA': out_dispdata,
                'DISPNAME': out_dispname,
                'SEGNAME': out_name,
                'ALIGN': out_align,
            },
            'body': merged_body,
            'reloc_size': reloc_size_val,
        }]

        # Two-pass to fix up file offset.
        lconst_payload0 = _build_het_lconst(het_input, [0])
        express_bc      = len(_build_express_seg(lconst_payload0))
        lconst_payload  = _build_het_lconst(het_input, [express_bc])
        express_seg     = _build_express_seg(lconst_payload)

        assert len(express_seg) == express_bc, (
            f'~ExpressLoad size changed: {len(express_seg)} != {express_bc}')

        return bytes(express_seg) + main_seg_bytes

    # ---- Multi-segment output ----
    # Build placed_by_obj: for each input object, collect its placed entries.
    placed_by_obj: list[list[int]] = [[] for _ in range(n_objs)]
    for placed_i in range(len(placed)):
        oi = placed_obj_idx[placed_i]
        placed_by_obj[oi].append(placed_i)

    # Caller-supplied name/kind overrides (per output group, indexed by group output idx).
    segnames_opt: list[bytes] = list(opts.get('segnames') or [])
    segkinds_opt: list[int]   = list(opts.get('segkinds') or [])

    # Build the group boundary table: group_idx -> (base_abs, end_abs).
    # Used to classify cross-group references when building SUPER type-2 records.
    # We need to know, for each non-empty object group, its absolute start address.
    group_obj_indices: list[int] = []   # oi values of non-empty groups, in order
    group_bases: list[int] = []         # absolute base of each non-empty group
    for oi in range(n_objs):
        indices = placed_by_obj[oi]
        if indices:
            group_obj_indices.append(oi)
            group_bases.append(placed[indices[0]][2])

    def _group_of(abs_addr: int) -> int:
        """Return the group index (0-based into group_bases) that abs_addr belongs to."""
        for g in range(len(group_bases) - 1, -1, -1):
            if abs_addr >= group_bases[g]:
                return g
        return 0

    # For each object group, merge its placed segments' bodies and collect relocs.
    out_groups: list[dict] = []
    group_out_idx = 0   # index into out_groups (may differ from oi if some objects are empty)
    for oi in range(n_objs):
        indices = placed_by_obj[oi]
        if not indices:
            continue

        group_placed = [placed[idx] for idx in indices]
        group_base = group_placed[0][2]  # absolute base of this group's first segment
        group_g    = group_out_idx       # 0-based group index (= position in out_groups)

        # Build bodies with group-base symbol adjustment.
        # Segments in group G (G > 0) have their seg_base in the joint address space,
        # but the loader will load group G at its own base 0.  Subtract group_base from
        # all symbol values so within-group EXPRs evaluate to group-relative addresses.
        if group_base > 0:
            def _adj(v: Any, gb: int = group_base) -> Any:
                return (v - gb) if isinstance(v, int) else v
            adj_sym = {k: _adj(v) for k, v in sym.items()}
            og = obj_globals[oi]
            adj_og: dict | None = ({k: _adj(v) for k, v in og.items()} if og else None)
        else:
            adj_sym = sym
            adj_og  = obj_globals[oi]

        group_bodies: list[bytes] = []
        for placed_i in indices:
            _segname, recs, seg_base, _hdr, _asm = placed[placed_i]
            recs2, _srels = _linkiigs._defer_shifts(recs)
            local_sym = adj_sym if not adj_og else {**adj_sym, **adj_og}
            # Adjust seg_base to be group-relative (subtract group_base).
            adj_seg_base = seg_base - group_base
            group_bodies.append(_link._build_body(recs2, local_sym, adj_seg_base))

        merged = b''.join(group_bodies)
        merged_arr = bytearray(merged)   # mutable — may be patched for type-2 relocs

        # Collect raw relocs (absolute joint addresses) for this group's segments.
        # _scan_relocs returns joint absolute offsets; we need group-relative offsets.
        # Also detect cross-group interseg references (type-2) from type-1 relocs.
        # And correct bank-byte SUPER type (type-27/28/...) based on target group.
        group_relocs_raw = _scan_relocs(group_placed)

        final_relocs: dict[int, list[int]] = {}
        for stype, abs_offs in group_relocs_raw.items():
            for abs_off in abs_offs:
                rel_off = abs_off - group_base   # group-relative offset

                if stype == 1:
                    # 3-byte (type-1) reloc: check if target is in a different group.
                    # At this point merged_arr has group-base–adjusted code, so we must
                    # read the target from the UN-adjusted body.  The target in
                    # merged_arr[rel_off:rel_off+2] is the group-relative address AFTER
                    # adjustment; the original joint address = rel_target + group_base.
                    rel_target = (merged_arr[rel_off] | (merged_arr[rel_off + 1] << 8))
                    joint_target = rel_target + group_base
                    tgt_group = _group_of(joint_target)
                    if tgt_group != group_g:
                        # Cross-group: encode as SUPER type-2 (INTERSEG, FileNum=1,
                        # SegNum = target group's output segnum).
                        tgt_group_base = group_bases[tgt_group]
                        tgt_segnum     = tgt_group + 2   # segnum 2 = first load seg
                        off_in_tgt = joint_target - tgt_group_base
                        # Patch the 3 bytes in the merged code image.
                        merged_arr[rel_off]     = off_in_tgt & 0xFF
                        merged_arr[rel_off + 1] = (off_in_tgt >> 8) & 0xFF
                        merged_arr[rel_off + 2] = tgt_segnum
                        final_relocs.setdefault(2, []).append(rel_off)
                    else:
                        final_relocs.setdefault(1, []).append(rel_off)

                elif stype == 27:
                    # Bank-byte reloc: type = 25 + target_output_segnum.
                    # Determine which segment's bank byte this references by looking
                    # up the EXPR's symbol value in the joint symbol table.
                    # The body has been group-adjusted, so the stored 2-byte value is
                    # (sym_joint_value - group_base) >> 16 — usually 0 for relocs
                    # within the address space.  We need the JOINT value to classify.
                    # Walk the records to find the EXPR at abs_off.
                    sym_joint: int | None = None
                    for placed_i in indices:
                        _sn2, recs2_raw, sb2, _h2, _a2 = placed[placed_i]
                        recs2_d, _ = _linkiigs._defer_shifts(recs2_raw)
                        body_off2 = 0
                        for _, nm2, d2 in recs2_d:
                            if nm2 == 'END':
                                break
                            if nm2 in ('CONST', 'LCONST'):
                                body_off2 += len(d2)
                            elif nm2 in ('LEXPR', 'BEXPR', 'EXPR'):
                                if sb2 + body_off2 == abs_off:
                                    # Evaluate expression WITHOUT shift to get joint addr
                                    ops2 = d2[1]
                                    # Extract symbol name and look up in joint sym
                                    for op2 in ops2:
                                        if isinstance(op2, tuple) and op2[0].startswith('sym'):
                                            sname2 = op2[1]
                                            # Try joint sym then obj_globals
                                            jv = sym.get(sname2)
                                            if jv is None:
                                                og2 = obj_globals[oi]
                                                jv = og2.get(sname2) if og2 else None
                                            if isinstance(jv, int):
                                                sym_joint = jv
                                            break
                                body_off2 += d2[0]
                            elif nm2 == 'RELEXPR':
                                body_off2 += d2[0]
                            elif nm2 == 'DS':
                                body_off2 += d2
                        if sym_joint is not None:
                            break

                    if sym_joint is not None:
                        tgt_group = _group_of(sym_joint)
                        tgt_segnum = tgt_group + 2
                        corrected_type = 25 + tgt_segnum
                    else:
                        corrected_type = 27  # fallback
                    final_relocs.setdefault(corrected_type, []).append(rel_off)

                else:
                    final_relocs.setdefault(stype, []).append(rel_off)

        merged = bytes(merged_arr)

        super_records = bytearray()
        for stype in sorted(final_relocs):
            super_records += emit_super(stype, sorted(final_relocs[stype]))
        super_records += b'\x00'   # END

        reloc_size_val = len(super_records) - 1

        # Output segment metadata.
        first_placed = group_placed[0]
        first_hdr    = first_placed[3]
        # Use caller-provided name/kind if available, else fall back to first seg's metadata.
        if group_out_idx < len(segnames_opt):
            out_name = segnames_opt[group_out_idx]
        else:
            out_name = first_hdr['SEGNAME'].rstrip(b'\x00') or b'main'
        if group_out_idx < len(segkinds_opt):
            out_kind = segkinds_opt[group_out_idx]
        else:
            out_kind = first_hdr['KIND']
        out_segnum   = group_out_idx + 2   # SEGNUM starts at 2 (1 = ~ExpressLoad)
        out_align    = max((p[3].get('ALIGN') or 0) for p in group_placed)

        # Build the output OMF segment
        seg_bytes = _make_output_seg(
            out_name, out_kind, out_segnum, merged, bytes(super_records),
            align=out_align
        )

        out_dispname = 44
        sname_field  = bytes([len(out_name)]) + out_name
        out_dispdata = out_dispname + 10 + len(sname_field)

        out_groups.append({
            'hdr': {
                'SEGNUM': out_segnum,
                'KIND': out_kind,
                'DISPDATA': out_dispdata,
                'DISPNAME': out_dispname,
                'SEGNAME': out_name,
                'ALIGN': out_align,
            },
            'body': merged,
            'reloc_size': reloc_size_val,
            'seg_bytes': seg_bytes,
        })
        group_out_idx += 1

    N = len(out_groups)

    # Two-pass to resolve ~ExpressLoad file offset.
    # First pass: compute ~ExpressLoad BYTECNT using placeholder offsets.
    # The output segments follow ~ExpressLoad in order.
    placeholder_offsets = [0] * N
    lconst0   = _build_het_lconst(out_groups, placeholder_offsets)
    express0  = _build_express_seg(lconst0)
    express_bc = len(express0)

    # Compute actual file offsets: express_seg | out_groups[0] | out_groups[1] | ...
    file_offsets = []
    cum = express_bc
    for g in out_groups:
        file_offsets.append(cum)
        cum += len(g['seg_bytes'])

    lconst    = _build_het_lconst(out_groups, file_offsets)
    express_seg = _build_express_seg(lconst)

    assert len(express_seg) == express_bc, (
        f'~ExpressLoad size changed: {len(express_seg)} != {express_bc}')

    result = bytearray(express_seg)
    for g in out_groups:
        result += g['seg_bytes']
    return bytes(result)
