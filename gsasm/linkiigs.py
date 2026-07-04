"""gsasm/linkiigs.py — general OMF v2 load-file linker (M2 — LinkIIgs keystone).

Links N OMF object files (each possibly multi-segment, APW/OMF format as produced
by omf.emit) into one relocated OMF load file.  Two output modes:

  merged  (merge=True)  — concatenate all segment bodies into a single LCONST
                          load segment (matches link.link for the single-object case).
  segmented (merge=False) — keep each segment as a distinct OMF segment with its
                          body resolved but retaining its header; suitable for
                          ExpressLoad (M4) reprocessing and multi-segment load files.

A *full* symbol table is built from every Asm object's .symbols/.symseg maps so
that internal cross-segment data labels (e.g. ``lda #SomeVar`` where SomeVar lives
in a sibling segment) resolve correctly — not just GLOBALs and segment-name refs.

Public interface:
    link(objects, opts) -> bytes

    objects  list of (obj_bytes, Asm|None)
             obj_bytes: raw OMF object as returned by omf.emit(asm)
             Asm:       the gsasm.asm.Asm that produced it (may be None; gives full
                        internal-symbol coverage when present)

    opts     dict with keys:
             order    (ignored — callers pass objects already in link order)
             kind     (int, default 0x0000) KIND field for merged output segment
             org      (int|None, default 0) base address for first segment
             loadname (bytes, default b'main') LOADNAME for merged output
             merge    (bool, default True) merged vs segmented output
             extern   ({str: int}) pre-seeded externals (override unresolved names)

Returns raw OMF bytes: a single segment (merge=True) or concatenated segments
(merge=False).

Reuses link._eval, link._build_body, link._body_length, link._make_segment
without modification so the ROM-validated path is unchanged.
"""

from __future__ import annotations
from typing import Any
from . import omf as _omf
from . import link as _link

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _decode_segname(h: dict) -> str:
    """Return the upper-cased, stripped segment name from a parsed header."""
    return h['SEGNAME'].decode('mac_roman', 'replace').rstrip('\x00').strip().upper()


def _parse_obj(obj_bytes: bytes) -> list[dict]:
    """Split a multi-segment OMF object into a list of dicts
    {hdr, recs, segname, length}."""
    segs: list[dict] = []
    off = 0
    while off < len(obj_bytes):
        h = _omf.parse_header(obj_bytes[off:])
        bc = h['BYTECNT']
        if bc == 0:
            break
        seg_data = obj_bytes[off:off + bc]
        recs, _ = _omf.parse_records(seg_data, h['DISPDATA'],
                                     h['NUMLEN'], h['LABLEN'])
        segs.append({
            'hdr': h,
            'recs': recs,
            'segname': _decode_segname(h),
            'length': h['LENGTH'],
        })
        off += bc
    return segs


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def _defer_shifts(recs):
    """Rewrite EXPR-family records whose expression ends in a RIGHT shift
    (e.g. `#^Label` / `Label>>16` in a relocatable segment) so the STORED value
    is the un-shifted, segment-relative placeholder, and collect the shift as a
    deferred relocation.  Returns ``(recs', [(body_offset, size, shift_count)])``
    where ``shift_count`` is negative (a right shift).

    A relocatable load file (ToolNNN/driver/FST) stores the base-0 value and lets
    the loader apply the high-word shift via a SUPER type-27 reloc; resolving the
    shift at link time would bake 0 (`offset >> 16`), which is the bank-byte gap.
    Only right shifts on a reloc expression are deferred; left shifts / non-reloc
    constants fall through and resolve normally."""
    out = []
    relocs = []
    pos = 0
    for rec in recs:
        at, nm, det = rec
        if (nm in ('EXPR', 'LEXPR', 'BEXPR') and isinstance(det, tuple)
                and isinstance(det[1], list)):
            size, ops = det
            if (len(ops) >= 3 and ops[-1] == 'end' and ops[-2] == ('op', 7)
                    and isinstance(ops[-3], tuple) and ops[-3][0] == 'lit'):
                lit = ops[-3][1]
                count = lit if lit < 0x80000000 else lit - 0x100000000
                if count < 0:                       # right shift -> defer to load
                    out.append((at, nm, (size, ops[:-3] + ['end'])))
                    relocs.append((pos, size, count))
                    pos += size
                    continue
            out.append(rec); pos += size
        elif nm in ('CONST', 'LCONST'):
            out.append(rec); pos += len(det)
        elif nm == 'DS':
            out.append(rec); pos += det
        elif nm == 'RELEXPR':
            out.append(rec); pos += det[0]
        else:
            out.append(rec)
    return out, relocs


def link(objects: list[tuple[bytes, Any | None]],
         opts: dict | None = None) -> bytes:
    """Link N OMF object files into one relocated load file.

    Parameters
    ----------
    objects
        List of ``(obj_bytes, asm_or_None)``.  ``obj_bytes`` is the raw OMF
        object (one or more segments).  ``asm_or_None`` is the ``gsasm.asm.Asm``
        that produced it; when present its full internal symbol table seeds the
        linker so cross-segment data refs resolve correctly.
    opts
        Linker options dict.  Keys: ``kind`` (int), ``org`` (int|None),
        ``loadname`` (bytes), ``merge`` (bool), ``extern`` ({str: int}).

    Returns
    -------
    bytes
        A single merged OMF segment (``merge=True``) or concatenated per-segment
        OMF records (``merge=False``).
    """
    if opts is None:
        opts = {}

    merge: bool = bool(opts.get('merge', True))
    base_org: int = opts.get('org') or 0
    kind: int = opts.get('kind', 0)
    loadname: bytes = opts.get('loadname', b'main')
    extern: dict = opts.get('extern') or {}

    # ------------------------------------------------------------------
    # Pass 1: parse all input objects and place segments sequentially
    # ------------------------------------------------------------------
    # Each entry: (segname, recs, base, hdr, asm_obj_or_None)
    placed: list[tuple[str, list, int, dict, Any | None]] = []
    # Track each (obj_idx, seg_within_obj) -> placed_base for Asm symbol seeding
    obj_seg_bases: list[list[int]] = []   # obj_seg_bases[obj_idx][seg_idx] = base
    # placed_obj_idx[i] = which object index produced placed[i]
    placed_obj_idx: list[int] = []

    base = base_org
    for obj_idx, (obj_bytes, asm_obj) in enumerate(objects):
        segs = _parse_obj(obj_bytes)
        bases_this_obj: list[int] = []
        for seg in segs:
            h = seg['hdr']
            seg_org = h['ORG'] or 0
            if seg_org:
                seg_base = seg_org
            else:
                seg_base = base
            placed.append((seg['segname'], seg['recs'], seg_base, h, asm_obj))
            placed_obj_idx.append(obj_idx)
            bases_this_obj.append(seg_base)
            base = seg_base + _link._body_length(seg['recs'])
        obj_seg_bases.append(bases_this_obj)

    if not placed:
        return b''

    # ------------------------------------------------------------------
    # Pass 2: build the global symbol table
    #
    # Symbol resolution order — processed per object in link order so that
    # first-definition wins (matching MPW LinkIIgs behaviour):
    #
    # For each object in link order:
    #   a. Segment names from that object's placement (pass 1 result)
    #   b. Every internal label from the Asm's .symbols/.symseg
    #      (base_of_segment + symbol_offset — the "full symbol table" fix)
    # After all objects:
    #   c. GLOBAL / GEQU records from all OMF bodies (setdefault)
    #   d. Caller-supplied extern overrides (override / last-wins)
    #
    # Interleaving (a) and (b) per object is critical: an interior label from
    # object 0 (e.g. PUSHRECT inside PUSHYRAT) must shadow a proc-head segment
    # name from object 3 (e.g. the PUSHRECT PROC in WCtlDef) — exactly as the
    # old toolcheck link_module did by processing seg names then labels per obj.
    # ------------------------------------------------------------------
    sym: dict[str, int] = {'__LOC__': 0}
    # Per-object label/GLOBAL maps: indexed by obj_idx.  Accumulated through
    # both pass (b) and pass (c) so that all symbols from an object override
    # the global sym when building that object's segment bodies in Pass 3.
    obj_globals: list[dict[str, int]] = [{} for _ in objects]

    # We process segment-name/interior-label pairs per object.  The placed list
    # is ordered globally; we need per-object segment slices.
    placed_idx = 0   # index into placed[], advances as we consume each obj's segs

    for obj_idx, (obj_bytes, asm_obj) in enumerate(objects):
        segs_in_obj = _parse_obj(obj_bytes)
        n_segs = len(segs_in_obj)
        bases_this_obj = obj_seg_bases[obj_idx]

        # (a) Segment names for this object.
        #
        # In multi-object links, segment names are PRIVATE to the defining
        # object — they must not shadow cross-object public EXPORT symbols of
        # the same name (e.g. a PROC named 'SHUTDOWN' in one object must not
        # hide the EXPORT 'SHUTDOWN' from a later object).
        # Single-object links keep the original first-wins global table.
        for k in range(n_segs):
            segname, _recs, seg_base, _hdr, _asm = placed[placed_idx + k]
            if len(objects) == 1:
                sym.setdefault(segname, seg_base)
            # Always add to per-object map so intra-object cross-segment refs work.
            obj_globals[obj_idx].setdefault(segname, seg_base)

        # (b) Interior labels from this Asm object.
        #
        # For multi-object links only ENTRY/EXPORT labels are globally visible
        # (matching MPW LinkerIIgs: plain local labels in one object must not
        # shadow same-named ENTRY/EXPORT labels from another object).  For
        # single-object links all labels are included (unchanged behaviour).
        #
        # All labels (including locals) also go into the per-object map so that
        # segments within this object can resolve their own local references.
        if asm_obj is not None:
            is_single_obj = len(objects) == 1
            asm_segs = [s for s in asm_obj.segs if s.items or s.name]
            for lab, v in asm_obj.symbols.items():
                sg_idx = asm_obj.symseg.get(lab)
                if sg_idx is None:
                    continue
                if not isinstance(v, int):
                    continue
                if sg_idx < 0 or sg_idx >= len(asm_segs):
                    continue
                # Map sg_idx (into asm_obj.segs) to emit position among
                # non-empty segs (which is what we placed)
                try:
                    emit_idx = asm_segs.index(asm_obj.segs[sg_idx])
                except (ValueError, IndexError):
                    continue
                if emit_idx >= len(bases_this_obj):
                    continue
                seg_placed_base = bases_this_obj[emit_idx]
                # v is the label's value within the segment (segment-relative
                # for ORG=0 segs, absolute for ORG'd segs).
                seg_obj = asm_obj.segs[sg_idx]
                seg_own_org = seg_obj.org or 0
                if seg_own_org:
                    abs_val = v & 0xFFFFFF
                else:
                    abs_val = (seg_placed_base + v) & 0xFFFFFF

                # Global table: only ENTRY/EXPORT labels (unless single-object)
                is_public = lab in asm_obj.entries or lab in asm_obj.exports
                if is_single_obj or is_public:
                    sym.setdefault(lab.upper(), abs_val)

                # Per-object table: ALL labels (for intra-object resolution)
                obj_globals[obj_idx].setdefault(lab.upper(), abs_val)

        placed_idx += n_segs

    # (c) GLOBAL / GEQU records from all OMF bodies (setdefault — lower priority)
    #
    # Also updates per-object GLOBAL maps (obj_globals[obj_idx]) so that
    # segments within an object can prefer their own GLOBAL definitions over
    # definitions from other objects with the same name.  This matches MPW
    # LinkerIIgs behaviour where e.g. windmgr.asm's PUSHRECT is used by
    # windmgr.asm's own code while WDefProc.asm's PUSHRECT is used by
    # WDefProc.asm's own code (both define and export PUSHRECT).
    for placed_i, (_segname, recs, seg_base, _hdr, _asm) in enumerate(placed):
        oi = placed_obj_idx[placed_i]
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
                val = seg_base + body_off
                is_priv = d.get('priv', 0)  # 1 = ENTRY (private), 0 = EXPORT (public)
                if is_priv:
                    # Private (ENTRY): intra-object only — do NOT add to global sym.
                    # Other objects that IMPORT this name should see the canonical
                    # public EXPORT, not this intra-object entry point.
                    pass
                elif len(objects) == 1:
                    # Single-object link: first-wins (original behaviour).
                    sym.setdefault(label, val)
                else:
                    # Multi-object link: last-wins for public EXPORT GLOBALs.
                    # This ensures that the "canonical" library module (typically
                    # linked last, e.g. wcm.asm) wins over earlier duplicates.
                    sym[label] = val
                # Per-object: ALL globals (including private) go here so that
                # intra-object cross-segment references resolve correctly.
                obj_globals[oi][label] = val
            elif nm == 'GEQU':
                label = d['label'].upper()
                sym.setdefault(label, _link._eval(d['expr'], sym))

    # Caller-supplied externals (e.g. from linkrom's rommap) — last-wins
    for k, v in extern.items():
        sym[k.upper()] = v

    # ------------------------------------------------------------------
    # Pass 3: build each segment body using the full symbol table,
    # augmented by this segment's object's own GLOBAL definitions so that
    # intra-object cross-segment references use the local export.
    # ------------------------------------------------------------------
    bodies: list[bytes] = []
    for placed_i, (_segname, recs, seg_base, _hdr, _asm) in enumerate(placed):
        recs2, _srels = _defer_shifts(recs)   # defer #^/>>16 to load-time relocs
        oi = placed_obj_idx[placed_i]
        # Local sym: global table overridden by this object's own GLOBALs.
        # This ensures e.g. WDefProc's JSR PUSHRECT resolves to WDefProc's
        # own PUSHRECT, not windmgr.asm's same-named export.
        local_sym = sym if not obj_globals[oi] else {**sym, **obj_globals[oi]}
        bodies.append(_link._build_body(recs2, local_sym, seg_base))

    # ------------------------------------------------------------------
    # Pass 4: emit the output
    # ------------------------------------------------------------------
    if merge:
        # Single merged output segment: concatenate all bodies.
        # Use the first input segment's metadata for the output header.
        first_hdr = placed[0][3]
        out_name = first_hdr['SEGNAME']
        out_load = first_hdr['LOADNAME']
        out_org = placed[0][2]
        out_kind = kind if opts.get('kind') is not None else first_hdr['KIND']
        merged = b''.join(bodies)
        return _link._make_segment(out_name, out_load, out_org, out_kind, 1, merged)
    else:
        # Segmented: re-emit each segment as a separate OMF segment with its
        # resolved body replacing the original records.  The segment header
        # is rebuilt via _make_segment using the original metadata.
        out = bytearray()
        for seg_idx, (segname, recs, seg_base, hdr, _asm) in enumerate(placed):
            body = bodies[seg_idx]
            seg_name = hdr['SEGNAME']
            seg_load = hdr['LOADNAME']
            seg_kind = kind if opts.get('kind') is not None else hdr['KIND']
            out += _link._make_segment(
                seg_name, seg_load, seg_base, seg_kind, seg_idx + 1, body
            )
        return bytes(out)
