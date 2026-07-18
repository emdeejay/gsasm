#!/usr/bin/env python3
"""toolcheck.py — validate gsasm against the shipping System 6.0.1 tool files.

Assembles each toolbox module from the GS/OS 6.0.1 source (ref/GSOS_6/IIGS.601.SRC/
GSToolbox), links its object segments, and compares the resulting code image
byte-for-byte against the shipping ToolNNN binary from the 6.0.1 System Disk.

    python3 work/toolcheck.py          # summary over every mapped tool
    python3 work/toolcheck.py 022      # one tool, with first-diff detail

The source -> ToolNNN map is taken from GSToolbox/build.tools; the multi-object
composition per manager mirrors work/linkrom.py's proven module lists. Golden
binaries live in ref/GSOS_6/tool_bin/ (extracted from the disk images with cadius).

The shipping tools are ExpressLoad'd OMF: a leading '~ExpressLoad' directory
segment plus the real load segments (LCONST code image + a SUPER relocation
dictionary). de_express() returns the concatenated CONST/LCONST image — the
segment-relative code the loader relocates — which is what gsasm's linked image
is compared against (exactly the flat()-image comparison work/buildrom.py uses
for the ROM banks).

STATUS (2026-07): the OMF emit+link path resolves cross-segment/-object
references, including the per-tool dispatch table (DC.L routine-1) — the lever
that gates every tool. Single-object managers reach 98-99% byte-identical
(DialogMgr, ListMgr, Scrap); the corpus sits at ~78%.

Multi-segment tools (MenuMgr, ControlMgr, LineEdit) ship several load segments,
some plus a linker-generated `~JumpTable`; they take the 'jt_segments' TOOLMAP
form and go through the jump-table-aware multi-segment link (_link_jt_tool /
_check_jt_tool). Each segment's code image is compared PER SEGMENT against gold
(each relocated from its own base 0, exactly as the gold ExpressLoad file stores
it); inter-segment far pointers resolve as gold does — a reference into a DYNAMIC
(KIND & 0x8000) segment routes through a generated ~JumpTable thunk, a reference
into a STATIC/KIND-0x4000 segment is a direct cINTERSEG. The generated
~JumpTable is verified byte-for-byte against gold (a mismatch raises). Flat-
linking such a tool into one blob is WRONG — it makes every intra-segment reloc
look "off by the segment base" (see work/tool016_diag.py). The simpler per-
segment `_check_multiseg` ('segments' TOOLMAP form) remains for tools that need
no inter-segment reference resolution.

Known remaining residuals (per-module levers, not a shared blocker):
  * `~JumpTable` segments (Tool015/016) — CLOSED (2026-07-18): gsasm now
    generates them and routes DYNAMIC-segment far pointers through them; both
    tools byte-exact (docs/TODO.md §2). Tool018 (QDAux) also has its 12-entry
    ~JumpTable derived byte-exact but is not mapped — two non-JT blockers remain
    (copybits.asm SEG-section split + one independent seedfill.asm assembly byte;
    see docs/TODO.md §2);
  * Tool023 (StdFile) — CLOSED (2026-07-18): was a `DevName` name collision
    (a PopUpGlobals data-record field vs GetThePrefix's `devName equ ParBlock+02`)
    that (a) let the PROC-local EQU clobber the global data-record label and
    (b) let a stale `with PopUpGlobals` shadow the local EQU in resolve(). Fixed
    in asm.py (keep_prior extended to EQU; resolve() lets a local def shadow WITH).
    Byte-exact 15942/15942; regression guard tests/fixtures/042;
  * Tool020 (LineEdit) — CLOSED (2026-07-18): the 3 formerly-unresolved TheTool
    bytes were a direct cINTERSEG far pointer into TheProc (KIND 0x4000, NOT
    dynamic — no jump table); the jump-table-aware link resolves it. Byte-exact.
The OMF emitter changes (which the byte-exact ROM build depends on) must still be
re-validated with work/buildrom.py + objcheck + linkcheck.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from gsasm import asm, omf, link, linkiigs
from gsasm.expressload import de_express, encode_jumptable, jt_jsl_offset

SRC = 'ref/GSOS_6/IIGS.601.SRC'
TB  = SRC + '/GSToolbox'
FW  = SRC + '/GSFirmware'
BIN = 'ref/GSOS_6/tool_bin'
INCS = [d for d, _, _ in os.walk(TB)] + [d for d, _, _ in os.walk(FW)] + ['work/includes']

# ToolNNN -> (manager subdir, entry).
# entry is either:
#   [files]                    — single-segment flat link; compare against de_express(gold)
#   {'segments': [...], ...}   — multi-segment tool; per-segment comparison
#
# Multi-segment entry keys:
#   'segments': list of dicts, each with:
#       'gold_name':  segment name in the gold ExpressLoad binary (matched by SEGNAME)
#       'srcs':       [relative source files] for this segment's main objects
#       'extern_base': optional int — if set, this segment's symbols are injected as
#                      extern overrides at this base address into PRECEDING segments
#
# Object file lists mirror the MPW makefile link order for each tool.
# This is critical: (a) symbol addresses depend on placement order, and (b) for
# duplicate GLOBAL exports (ENTRY in multiple objects), last-wins in linkiigs
# matches MPW LinkerIIgs behaviour — so the last object's definition prevails.
TOOLMAP = {
    '014': ('WindMgr',    ['windmgr.asm', 'task.asm', 'NewCalls.asm', 'WDefProc.asm',
                           'WCtlDef.asm', 'WMPatch.asm', '../MenuMgr/wcm.asm']),
    # MenuMgr ships a THREE-segment ExpressLoad binary (plus ~ExpressLoad):
    #   MainTool   (KIND 0)      menumgr + wcm — the resident tool
    #   ~JumpTable (KIND 2)      linker-generated (1 entry -> PopUpProc GETPOPUPDEFPROC)
    #   PopUpProc  (KIND 0x8000) DYNAMIC (on-demand) pop-up menu defproc
    # 'jt_segments' drives the jump-table-aware multi-segment link (see
    # _link_jt_tool): each far pointer from MainTool into the DYNAMIC PopUpProc
    # routes through the generated ~JumpTable, exactly as MPW LinkIIgs does.
    '015': ('MenuMgr',    {'jt_segments': [
        ('MainTool',  0x0000, ['menumgr.asm', 'wcm.asm']),
        ('PopUpProc', 0x8000, ['popupproc.asm']),
    ]}),
    # ControlMgr ships a FOUR-segment ExpressLoad binary, not one flat blob:
    #   main     (KIND 0)      — ControlMgr..DummyDrag (the 6 core objects)
    #   StatText (KIND 0)      — StatTextProc.asm (static-text defproc)
    #   ~JumpTable (KIND 2)    — linker-generated inter-segment call thunks
    #   Pics     (KIND 0x8000) — PicProc.asm (DYNAMIC/on-demand picture defproc)
    # The old flat-link entry concatenated all 8 objects into one segment and
    # compared against de_express(gold) (= main|StatText|~JumpTable|Pics). That
    # basis is wrong for a genuinely multi-segment tool: every StatText/Pics
    # intra-segment word reloc came out off by exactly its segment's base in the
    # merged image (0x30c9 / 0x355f), and the 26-byte ~JumpTable gsasm can't emit
    # (linker-generated, see docs/TODO.md §2) shifted all of Pics — 451 "diffs"
    # that were 100% segmentation artifact, NOT value errors (proven in
    # work/tool016_diag.py). Compared the way gold is actually segmented, gsasm
    # is byte-exact: StatText 1174/1174, Pics 358/358, main 12488/12489. The one
    # main byte is a far-pointer operand into the DYNAMIC Pics segment, which gold
    # routes through ~JumpTable+0x12 (cINTERSEG to seg 4); resolving it needs the
    # ~JumpTable gsasm doesn't generate — the same TODO §2 gap, honestly counted.
    '016': ('ControlMgr', {'jt_segments': [
        ('main',     0x0000, ['ControlMgr.asm', 'SuperControl.asm',
                              'NewControl2.asm', 'DefProcs.asm',
                              'CtlPatch.asm', 'DummyDrag.asm']),
        ('StatText', 0x0000, ['StatTextProc.asm']),
        ('Pics',     0x8000, ['PicProc.asm']),
    ]}),
    # LineEdit is two real load segments (TheTool KIND 0 + TheProc KIND 0x4000).
    # TheProc is KIND 0x4000 — NOT dynamic (0x8000) — so there is NO ~JumpTable:
    # TheTool's far pointer to TheProc's GETLEDEFPROC is a DIRECT cINTERSEG
    # (stores [routine_off_lo, routine_off_hi, TheProc_segnum]). The jump-table-
    # aware link resolves it (the 3 formerly-unresolved TheTool bytes) exactly as
    # for the static targets in 016; no jump table is generated.
    '020': ('LineEdit',   {'jt_segments': [
        ('TheTool', 0x0000, ['le.asm', 'common.asm']),
        ('TheProc', 0x4000, ['LineEditProc.asm']),
    ]}),
    # QDAux ships a SIX-load-segment ExpressLoad binary (plus ~ExpressLoad and a
    # linker-generated ~JumpTable), per QDAux/MakeFile's -lseg groups:
    #   MAINPart     (KIND 0)      qdaux, faces, icon, special.slabs, common,
    #                              copybits.asm(@MAINPart)   -- resident tool
    #   CopyBits     (KIND 0)      copybits.asm(@CopyBits)   -- static defproc
    #   ~JumpTable   (KIND 2)      linker-generated (12 thunks into the 3 dynamics)
    #   Pictures     (KIND 0x8000) pics, pixel, text, slabs  -- DYNAMIC
    #   SeedFill     (KIND 0x8000) seedfill                  -- DYNAMIC
    #   PixelMap2Rgn (KIND 0x8000) PixelMap2Rgn.aii          -- DYNAMIC
    # copybits.asm is ONE assembled object split across TWO load segments by SEG
    # section: `SEG 'MAINPart'` (ISTDPIXELS) joins MAINPart, `SEG 'CopyBits'`
    # (COPYBITS/STRETCHBITS/FORCECOPYBITLOAD/...) joins CopyBits.  The
    # ('copybits.asm', 'MAINPart'/'CopyBits') source-spec tuples select the
    # matching sections while keeping the full object's symbols, so MAINPart's
    # references to a CopyBits-section routine resolve to its real placed address.
    # Segments are listed in MAKEFILE source order; _link_jt_tool reorders them to
    # the gold file layout (non-dynamic block, ~JumpTable, dynamic block).
    '018': ('QDAux',      {'jt_segments': [
        ('MAINPart', 0x0000, ['qdaux.asm', 'faces.asm', 'icon.asm',
                              'special.slabs.asm', 'common.asm',
                              ('copybits.asm', 'MAINPart')]),
        ('Pictures', 0x8000, ['pics.asm', 'pixel.asm', 'text.asm', 'slabs.asm']),
        ('CopyBits', 0x0000, [('copybits.asm', 'CopyBits')]),
        ('SeedFill', 0x8000, ['seedfill.asm']),
        ('PixelMap2Rgn', 0x8000, ['PixelMap2Rgn.aii']),
    ]}),
    '021': ('DialogMgr',  ['dialog.asm']),
    '022': ('Scrap',      ['scrap.asm', 'common.asm']),
    # StdFile: single-segment, no -lseg in makefile (matches
    # diskbuilders/expressload_files.py::_build_tool023's link order). BYTE-EXACT
    # (15942/15942) since the 2026-07-18 `DevName` collision fix (see the "Known
    # remaining residuals" note above and tests/fixtures/042). The `DevName`
    # name is BOTH a PopUpGlobals data-record field and a GetThePrefix PROC-local
    # `equ` — the local EQU must neither clobber the global field label nor be
    # shadowed by the (stale, never-ENDWITH'd) `with PopUpGlobals`.
    '023': ('StdFile',    ['sfmain.asm', 'sf.asm']),
    # PrintMgr: two-object flat link per PrintMgr/makefile
    # (linkiigs printmgr.asm.obj dialogdata.asm.obj -t TOL -o Tool019).
    # Builds BYTE-EXACT (5080/5080) against the de-ExpressLoad'd gold once the
    # pure-literal high-word shift is resolved at link time (linkiigs
    # _defer_shifts). The archived source in IIGS.601.SRC IS the shipping
    # revision -- there is no source/binary disagreement.
    '019': ('PrintMgr',   ['printmgr.asm', 'dialogdata.asm']),
    '027': ('FontMgr',    ['fm.asm', 'common.asm', 'scale.asm']),
    '028': ('ListMgr',    ['ListMgr.asm']),
}


def flat(seg):
    """Segment-relative code image of one gsasm segment."""
    out = bytearray()
    for it in seg.items:
        if it[0] == 'code':
            out += it[2]
        elif it[0] == 'ds':
            out += b'\x00' * it[1]
    return bytes(out)


def _open_gold(tool):
    """Return raw bytes of the gold binary for this tool, or None."""
    for cand in (f'{BIN}/Tool{tool}#BA0000', f'{BIN}/Tool{tool}'):
        if os.path.exists(cand):
            return open(cand, 'rb').read()
    return None


def golden(tool):
    """Return flat de_express'd code image for simple single-segment tools."""
    raw = _open_gold(tool)
    if raw is None:
        return None
    return de_express(raw)


def _gold_segment(raw_bytes, gold_name):
    """Extract the LCONST image of one named segment from an ExpressLoad binary."""
    off = 0
    while off < len(raw_bytes):
        h = omf.parse_header(raw_bytes[off:])
        bc = h['BYTECNT']
        if bc == 0:
            break
        nm = h['SEGNAME'].decode('mac_roman', 'replace').strip().rstrip('\x00')
        if nm == gold_name:
            recs, _ = omf.parse_records(raw_bytes[off:off + bc], h['DISPDATA'],
                                        h.get('NUMLEN', 4), h.get('LABLEN', 0))
            return b''.join(r[2] for r in recs if r[1] in ('CONST', 'LCONST'))
        off += bc
    return None


def _assemble_objects(srcs, subdir):
    """Assemble a list of source paths (relative to TB/subdir) into OMF objects."""
    objects = []
    for r in srcs:
        a = asm.assemble(f'{TB}/{subdir}/{r}', INCS)
        obj = omf.emit(a)
        objects.append((obj, a))
    return objects


# One assembled OMF object per source, cached: a source that feeds TWO load
# segments via a SEG-section split (QDAux copybits.asm -> MAINPart + CopyBits)
# is assembled ONCE and placed twice, selecting a different SEG section each
# time (see _norm_src / _link_jt_tool).  Keeps the FULL Asm alongside the object
# so _build_symtab publishes each placed section's labels at its placed base.
_ASM_CACHE: dict = {}


def _assemble_source(subdir, fname):
    key = (subdir, fname)
    if key not in _ASM_CACHE:
        a = asm.assemble(f'{TB}/{subdir}/{fname}', INCS)
        _ASM_CACHE[key] = (omf.emit(a), a)
    return _ASM_CACHE[key]


def _norm_src(spec):
    """Normalise one jt_segments source entry to ``(filename, section_or_None)``.

    A plain ``'file.asm'`` string is the whole object (all its OMF segments).
    A ``('file.asm', 'CopyBits')`` tuple selects ONLY that object's segments
    whose SEG-section name (gsasm stamps it as the OMF LOADNAME) matches — the
    MPW makefile ``copybits.asm.obj(@CopyBits)`` idiom, where one assembled
    object feeds two load segments."""
    if isinstance(spec, tuple):
        return spec[0], spec[1]
    return spec, None


def _seg_place_order(srcs, subdir):
    """Assemble a load segment's sources and return ``(objs, order)``.

    ``objs`` is ``[(obj_bytes, Asm), ...]``; ``order`` is the ``_place`` /
    ``seg_order`` placement list ``[(obj_idx, seg_idx), ...]`` selecting which
    OMF segments of each object join this load segment.  ``order`` is ``None``
    (natural full order, byte-identical to no order) unless a source is
    SEG-section-filtered, in which case only that object's matching-LOADNAME
    segments are placed — but the FULL Asm is kept so cross-section symbol
    references still resolve to their real placed addresses."""
    objs, order, filtered = [], [], False
    for spec in srcs:
        fname, section = _norm_src(spec)
        obj, a = _assemble_source(subdir, fname)
        oi = len(objs)
        objs.append((obj, a))
        parsed = linkiigs._parse_obj(obj)
        if section is None:
            sel = range(len(parsed))
        else:
            filtered = True
            sel = [si for si, s in enumerate(parsed)
                   if s['loadname'].lower() == section.lower()]
        order += [(oi, si) for si in sel]
    return objs, (order if filtered else None)


def _compute_externs(srcs, subdir, base):
    """Assemble srcs and compute their exported symbol addresses at given base."""
    asm_segs_list = []
    for r in srcs:
        a = asm.assemble(f'{TB}/{subdir}/{r}', INCS)
        asm_segs_list.append(a)

    externs = {}
    cur_base = base
    for a in asm_segs_list:
        asm_segs = [s for s in a.segs if s.items or s.name]
        seg_bases = []
        for seg in asm_segs:
            seg_bases.append(cur_base)
            sz = 0
            for it in seg.items:
                if it[0] == 'code':
                    sz += len(it[2])
                elif it[0] == 'ds' and isinstance(it[1], int):
                    sz += it[1]
            cur_base += sz
        for lab, v in a.symbols.items():
            sg_idx = a.symseg.get(lab)
            if sg_idx is None or not isinstance(v, int):
                continue
            if sg_idx < 0 or sg_idx >= len(asm_segs):
                continue
            seg_base = seg_bases[sg_idx]
            seg_org = asm_segs[sg_idx].org or 0
            abs_val = (v & 0xFFFFFF) if seg_org else ((seg_base + v) & 0xFFFFFF)
            externs[lab.upper()] = abs_val
    return externs


def _lconst_image(linked_bytes):
    """Extract the flat LCONST code image from a merged linkiigs result."""
    img = bytearray()
    off = 0
    while off < len(linked_bytes):
        h = omf.parse_header(linked_bytes[off:])
        bc = h['BYTECNT']
        if bc == 0:
            break
        recs, _ = omf.parse_records(linked_bytes[off:off + bc], h['DISPDATA'],
                                    h.get('NUMLEN', 4), h.get('LABLEN', 0))
        for r in recs:
            if r[1] in ('CONST', 'LCONST'):
                img += r[2]
        off += bc
    return bytes(img)


def link_module(roots):
    """Assemble each object to OMF (cross-segment/-object references become
    relocation records), place every segment sequentially into one load image,
    and resolve each segment's relocations against a FULL symbol table built
    from gsasm's own symbols (segment names + every label at base+offset).

    Thin wrapper over gsasm.linkiigs.link — all linking logic lives there.
    Returns the concatenated, relocated code image."""
    objects = []
    for r in roots:
        a = asm.assemble(f'{TB}/{r}', INCS)
        obj = omf.emit(a)
        objects.append((obj, a))

    # linkiigs.link builds the full symbol table and resolves all relocs
    result = linkiigs.link(objects, opts={'merge': True})
    return _lconst_image(result)


def _seg_symbols(objs, order=None):
    """Merged symbol table (label_upper -> base-0 offset) for one load segment's
    objects, i.e. every symbol's offset WITHIN the linked load segment.
    ``order`` (a ``_place`` placement list) selects which OMF segments join this
    load segment — a SEG-section-filtered object only publishes symbols for its
    placed sections (an omitted section's labels resolve elsewhere, cross-seg)."""
    placed, osb, poi = linkiigs._place(objs, 0, order=order)
    sym, _ = linkiigs._build_symtab(objs, placed, osb, poi, {})
    return sym


def _scan_refs(objs, order=None):
    """Yield (abs_off, size, primary_symbol_upper) for every EXPR-family record
    in a load segment's placed objects, in body order.  abs_off is the byte
    offset within the (base-0) load segment; primary_symbol is the first symbol
    referenced by the expression (the far-pointer target for the single-symbol
    inter-segment references we rewrite).  ``order`` selects the placed OMF
    segments (SEG-section split), matching the load segment's own body."""
    placed, _osb, _poi = linkiigs._place(objs, 0, order=order)
    for _sn, recs, sb, _hdr, _a in placed:
        boff = 0
        for _at, nm, d in recs:
            if nm in ('CONST', 'LCONST'):
                boff += len(d)
            elif nm in ('LEXPR', 'BEXPR', 'EXPR'):
                size, ops = d[0], d[1]
                for op in ops:
                    if isinstance(op, tuple) and str(op[0]).startswith('sym'):
                        yield sb + boff, size, op[1].upper()
                        break
                boff += size
            elif nm == 'RELEXPR':
                boff += d[0]
            elif nm == 'DS':
                boff += d


def _link_jt_tool(subdir, segs):
    """Jump-table-aware multi-segment link of one ExpressLoad tool.

    ``segs`` is ``[(gold_name, kind, [srcs]), ...]`` — the load segments in
    source order (KIND & 0x8000 = a DYNAMIC/on-demand segment).  Reproduces the
    MPW LinkIIgs multi-segment placement + jump-table generation:

      * File segment numbers (1-based; ~ExpressLoad is 1): all NON-dynamic
        segments first in source order, then ~JumpTable (only if any dynamic
        segment exists), then the dynamic segments in source order — exactly the
        gold file layout (main/StatText/~JumpTable/Pics for Tool016, etc.).
      * Each far pointer from one load segment into ANOTHER is an inter-segment
        reference.  A reference into a DYNAMIC segment is routed through a
        ~JumpTable entry (one 14-byte thunk per referenced routine, allocated in
        reference-scan order); the caller's field is rewritten to
        ~JumpTable + jt_jsl_offset(entry) with the ~JumpTable's file segnum in
        its bank byte.  A reference into a STATIC/KIND-0x4000 segment stays a
        DIRECT cINTERSEG: the routine's own offset + that segment's file segnum.
      * The seeded externs give each cross-segment symbol its target OFFSET only
        (jump-table JSL offset for dynamic, routine offset for static); the file
        segnum is written into the field's 3rd byte afterwards (a size>=3 field
        only). Passing those names as ``abs_extra`` makes any shift on the
        reference resolve at link time (cINTERSEG shift semantics), while genuine
        intra-segment `lda #^label` bank refs still defer to a SUPER type-27.

    Returns ``(images, jt_entries, jt_segnum, segnum)`` where ``images`` maps
    gold_name -> resolved base-0 code image, ``jt_entries`` is the list of
    ``(target_segnum, routine_offset)`` for the generated ~JumpTable (empty when
    no dynamic segment is referenced), ``jt_segnum`` is its file segment number
    (or None), and ``segnum`` maps gold_name -> file segment number."""
    nondyn = [s for s in segs if not (s[1] & 0x8000)]
    dyn    = [s for s in segs if (s[1] & 0x8000)]
    jt_segnum = (2 + len(nondyn)) if dyn else None

    # File segment numbers: non-dynamic block, then ~JumpTable, then dynamic block.
    segnum, kind_of = {}, {}
    n = 2
    for name, kind, _srcs in nondyn:
        segnum[name] = n; kind_of[name] = kind; n += 1
    if dyn:
        n += 1                      # ~JumpTable occupies this slot
    for name, kind, _srcs in dyn:
        segnum[name] = n; kind_of[name] = kind; n += 1

    # Assemble each segment's objects and record its merged symbol offsets.
    # seg_order[name] is the _place/seg_order placement list (SEG-section split):
    # a source that feeds two load segments (copybits.asm -> MAINPart+CopyBits)
    # is assembled once and placed once per segment, selecting its matching
    # SEG section each time.  None = natural full placement (byte-identical).
    seg_objs, seg_sym, seg_order = {}, {}, {}
    for name, _kind, srcs in segs:
        objs, order = _seg_place_order(srcs, subdir)
        seg_objs[name] = objs
        seg_order[name] = order
        seg_sym[name] = _seg_symbols(objs, order)

    # Global export map: SYMBOL_upper -> (owning_gold_name, offset_in_segment).
    expmap = {}
    for name, _kind, _srcs in segs:
        for _ob, a in seg_objs[name]:
            for e in list(a.exports) + list(a.entries):
                v = seg_sym[name].get(e.upper())
                if isinstance(v, int):
                    expmap.setdefault(e.upper(), (name, v))

    def _cross_target(name, symu):
        """(owning_name, offset) if symu is an inter-segment reference from
        segment ``name`` (defined in a DIFFERENT segment and not shadowed by a
        local definition), else None."""
        tgt = expmap.get(symu)
        if tgt is None or tgt[0] == name or symu in seg_sym[name]:
            return None
        return tgt

    # Allocate ~JumpTable entries: scan every segment's references in source
    # order; a reference into a dynamic segment claims one entry per distinct
    # (target_segnum, routine_offset), first-seen order (entry index -> JSL offset).
    jt_entries, jt_index = [], {}
    for name, _kind, _srcs in segs:
        for _aoff, _size, symu in _scan_refs(seg_objs[name], seg_order[name]):
            tgt = _cross_target(name, symu)
            if tgt and (kind_of[tgt[0]] & 0x8000):
                key = (segnum[tgt[0]], tgt[1])
                if key not in jt_index:
                    jt_index[key] = len(jt_entries)
                    jt_entries.append(key)

    # Build each segment's code image with the inter-segment externs applied.
    images = {}
    for name, _kind, _srcs in segs:
        externs = {}
        for symu, (tname, toff) in expmap.items():
            if tname == name or symu in seg_sym[name]:
                continue
            if kind_of[tname] & 0x8000:
                key = (segnum[tname], toff)
                if key not in jt_index:
                    continue
                externs[symu] = jt_jsl_offset(jt_index[key])
            else:
                externs[symu] = toff
        objs = seg_objs[name]
        result = linkiigs.link(objs, opts={'merge': True, 'extern': externs,
                                           'abs_extra': list(externs.keys()),
                                           'seg_order': seg_order[name]})
        img = bytearray(_lconst_image(result))
        # Write the file segnum into the bank byte of each size>=3 inter-segment
        # field (cINTERSEG convention: [off_lo, off_hi, segnum]); dynamic targets
        # carry the ~JumpTable's segnum, static/0x4000 targets their own.
        for aoff, size, symu in _scan_refs(objs, seg_order[name]):
            tgt = _cross_target(name, symu)
            if tgt and size >= 3 and aoff + 2 < len(img):
                img[aoff + 2] = (jt_segnum if (kind_of[tgt[0]] & 0x8000)
                                 else segnum[tgt[0]]) & 0xFF
        images[name] = bytes(img)

    return images, jt_entries, jt_segnum, segnum


def _check_jt_tool(tool, subdir, segs, verbose=False):
    """Check a jump-table multi-segment tool: each real load segment's code image
    is compared per-segment against gold (exactly the segments gold ships, so the
    corpus denominator is unchanged), and the GENERATED ~JumpTable is verified
    byte-for-byte against gold as a hard gate: on a mismatch (or a missing gold
    ~JumpTable) the check returns an error result (res=None), which main() drops
    from the corpus good-count so the gate FAILS — the JT is genuinely gated even
    though the failure is a returned error tuple, not a raised exception."""
    raw = _open_gold(tool)
    if raw is None:
        return tool, subdir, None, "no golden binary"

    try:
        images, jt_entries, jt_segnum, _segnum = _link_jt_tool(subdir, segs)
    except Exception as e:
        return tool, subdir, None, f"{type(e).__name__}: {e}"

    # Gate the generated ~JumpTable byte-for-byte against gold.  A tool that
    # produces jump-table entries MUST have a matching '~JumpTable' segment in the
    # gold file; if the exact-name lookup misses (a rename / extraction issue), do
    # NOT silently skip the gate — fail loudly, else a bypassed check could read
    # 100%.
    if jt_entries:
        gold_jt = _gold_segment(raw, '~JumpTable')
        if gold_jt is None:
            return tool, subdir, None, (
                "gold '~JumpTable' segment not found, but gsasm generated "
                f"{len(jt_entries)} entr{'y' if len(jt_entries) == 1 else 'ies'}")
        mine_jt = encode_jumptable(jt_entries)
        if mine_jt != gold_jt:
            return tool, subdir, None, (
                f"~JumpTable mismatch: gsasm {mine_jt.hex()} vs gold {gold_jt.hex()}")

    tot_m = tot_n = tot_mine = tot_gold = 0
    first_diff_info = None
    for name, _kind, _srcs in segs:
        g_seg = _gold_segment(raw, name)
        if g_seg is None:
            continue
        mine_seg = images[name]
        n = min(len(mine_seg), len(g_seg))
        diffs_i = [i for i in range(n) if mine_seg[i] != g_seg[i]]
        tot_m += n - len(diffs_i)
        tot_n += n
        tot_mine += len(mine_seg)
        tot_gold += len(g_seg)
        if verbose and diffs_i and first_diff_info is None:
            i = diffs_i[0]
            first_diff_info = (name, i, mine_seg[i], g_seg[i],
                               mine_seg[max(0, i - 4):i + 8], g_seg[max(0, i - 4):i + 8])

    pct = (100 * tot_m // tot_n) if tot_n else 0
    if verbose:
        jt_note = (f"  ~JumpTable {len(jt_entries)} entr"
                   f"{'y' if len(jt_entries) == 1 else 'ies'} byte-exact"
                   if jt_entries else "  (no ~JumpTable)")
        print(f"Tool{tool} ({subdir}): gsasm={tot_mine} gold={tot_gold} "
              f"match {tot_m}/{tot_n} ({pct}%){jt_note}")
        if first_diff_info:
            gn, i, mi, gi, m_ctx, g_ctx = first_diff_info
            print(f"  first diff in {gn!r} @ {i:#06x}: gsasm={mi:02x} gold={gi:02x}")
            print(f"    gsasm {m_ctx.hex()}")
            print(f"    gold  {g_ctx.hex()}")
    return tool, subdir, (pct, tot_m, tot_n, tot_mine, tot_gold), None


def _check_multiseg(tool, subdir, seg_specs, verbose=False):
    """Check a multi-segment tool: each segment compared independently."""
    raw = _open_gold(tool)
    if raw is None:
        return tool, subdir, None, "no golden binary"

    tot_m = tot_n = 0
    tot_mine = tot_gold = 0
    first_diff_info = None

    for seg_spec in seg_specs:
        gold_name = seg_spec['gold_name']
        srcs = seg_spec['srcs']
        extern_specs = seg_spec.get('extern_srcs', [])

        g_seg = _gold_segment(raw, gold_name)
        if g_seg is None:
            continue

        # Build extern overrides from any declared extern segments
        externs = {}
        for _xname, xbase, xsrcs in extern_specs:
            externs.update(_compute_externs(xsrcs, subdir, xbase))

        try:
            objs = _assemble_objects(srcs, subdir)
            result = linkiigs.link(objs, opts={'merge': True, 'extern': externs})
            mine_seg = _lconst_image(result)
        except Exception as e:
            return tool, subdir, None, f"{type(e).__name__}: {e}"

        n = min(len(mine_seg), len(g_seg))
        diffs_i = [i for i in range(n) if mine_seg[i] != g_seg[i]]
        m = n - len(diffs_i)
        tot_m += m
        tot_n += n
        tot_mine += len(mine_seg)
        tot_gold += len(g_seg)

        if verbose and diffs_i and first_diff_info is None:
            i = diffs_i[0]
            first_diff_info = (gold_name, i, mine_seg[i], g_seg[i],
                               mine_seg[max(0,i-4):i+8], g_seg[max(0,i-4):i+8])

    pct = (100 * tot_m // tot_n) if tot_n else 0
    if verbose:
        print(f"Tool{tool} ({subdir}): gsasm={tot_mine} gold={tot_gold} "
              f"match {tot_m}/{tot_n} ({pct}%)")
        if first_diff_info:
            gn, i, mi, gi, m_ctx, g_ctx = first_diff_info
            print(f"  first diff in {gn!r} @ {i:#06x}: gsasm={mi:02x} gold={gi:02x}")
            print(f"    gsasm {m_ctx.hex()}")
            print(f"    gold  {g_ctx.hex()}")
    return tool, subdir, (pct, tot_m, tot_n, tot_mine, tot_gold), None


def check(tool, verbose=False):
    entry = TOOLMAP[tool]
    subdir, spec = entry
    if isinstance(spec, dict):
        if 'jt_segments' in spec:
            return _check_jt_tool(tool, subdir, spec['jt_segments'], verbose=verbose)
        return _check_multiseg(tool, subdir, spec['segments'], verbose=verbose)

    roots = spec
    g = golden(tool)
    if g is None:
        return tool, subdir, None, "no golden binary"
    try:
        mine = link_module([f'{subdir}/{r}' for r in roots])
    except Exception as e:
        return tool, subdir, None, f"{type(e).__name__}: {e}"
    n = min(len(mine), len(g))
    m = sum(1 for i in range(n) if mine[i] == g[i]) if n else 0
    pct = (100 * m // n) if n else 0
    if verbose:
        print(f"Tool{tool} ({subdir}): gsasm={len(mine)} gold={len(g)} "
              f"match {m}/{n} ({pct}%)")
        for i in range(n):
            if mine[i] != g[i]:
                print(f"  first diff @ {i:#06x}: gsasm={mine[i]:02x} gold={g[i]:02x}")
                print(f"    gsasm {mine[max(0,i-4):i+8].hex()}")
                print(f"    gold  {g[max(0,i-4):i+8].hex()}")
                break
    return tool, subdir, (pct, m, n, len(mine), len(g)), None


def main():
    if len(sys.argv) > 1:
        t = sys.argv[1].lstrip('Tool').zfill(3)
        if t not in TOOLMAP:
            print(f"unknown/unmapped tool {t}; mapped: {', '.join(sorted(TOOLMAP))}")
            return
        check(t, verbose=True)
        return
    print(f"{'Tool':7} {'Manager':12} {'match':>7}  {'bytes (gsasm/gold)':>20}")
    tot_m = tot_n = 0
    for t in sorted(TOOLMAP):
        _, sub, res, err = check(t)
        if res is None:
            print(f"Tool{t}  {sub:12} {'--':>7}  {err}")
            continue
        pct, m, n, lg, lo = res
        tot_m += m; tot_n += n
        print(f"Tool{t}  {sub:12} {pct:>6}%  {lg:>8}/{lo:<8}  ({m}/{n} bytes)")
    if tot_n:
        print(f"\nCORPUS raw code-image match: {tot_m}/{tot_n} ({100*tot_m//tot_n}%)")


if __name__ == '__main__':
    main()
