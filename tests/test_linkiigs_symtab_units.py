"""Direct unit tests for the linker's symbol machinery — the composite truth
table of ``linkiigs._build_symtab`` (plus ``SymTab`` and the reloc scan).

The 2026-08-02 architecture review's finding #1: ``_build_symtab`` now
composes SIX binding rules "whose composite truth table exists nowhere but
in the corpus itself".  This file writes that table down as executable
assertions.  Every test is named ``test_ruleN_...`` (one rule in isolation)
or ``test_interaction_...`` (which rule wins when two could both apply), so
a reader can map test -> rule.

The six rules, as ``_build_symtab``'s docstring names them:

  R1  first-wins            — ``_kind_setdefault``; the first definition a
                              pass sees keeps the binding (MPW 3.0 Ref
                              Vol.1 p.291, 68K-family evidence).
  R2  ENTRY-vs-EXPORT       — an ENTRY is a PRIVATE entry point: if ANY
                              object EXPORTs the name, the ENTRY does not
                              reach the global table (Finder GetFileInfo).
  R3  combo setdefault      — a pre-concatenated object (``asm is None``)
                              merges GLOBALs into its per-object map with
                              setdefault, not override (TS2 TLBootInit).
  R4  case-collision repair — when a folded interior label has clobbered a
                              PUBLIC segment's own entry in ``asm.symbols``,
                              pass (a) publishes the segment's placement
                              base instead (notesynth ``UpDate``).
  R5  module privacy        — a plain interior label is module-LOCAL; a
                              by-name reference binds the program-wide
                              EXPORT even from a sibling module of the same
                              object.  ENTRYs, unexported names and segment
                              names are exempt.  (MPW Asm Ref p.63, verbatim
                              — docs/GROUNDING_2026-08-02.md.)
  R6  symbol KINDs          — ``SymTab.kinds``: 'equ' = link-time constant
                              (GEQU / exported EQU), 'label' = relocatable.
                              Drives reloc suppression
                              (docs/SCSI_RELOC_DIAGNOSIS_2026-08-01.md).

THE OUTER KEY of the whole table is not object order but PASS order.
``_build_symtab`` runs, in this order:

    (a) segment names, per object      [setdefault]
    (b) interior labels, per object    [setdefault]
    (c) GLOBAL records, all objects    [setdefault if 1 object or combo,
                                        OVERRIDE if multi-object]
    (c) GEQU records, all objects      [setdefault]
    (d) caller extern                  [OVERRIDE — always last]

so "first-wins" is *within* a pass; a later pass with an override policy
beats every earlier pass.  Several tests below pin exactly that.

These tests are CORPUS-FREE (synthetic sources + hand-built OMF record
streams) and must stay so: they run in GitHub CI with no ``ref/`` tree.

This packet is a *pin*, not a fix.  Where a behaviour looks surprising the
test asserts what the code does TODAY; see the module-level notes marked
"SUSPICIOUS (pinned, not fixed)".

Run either as:
    python3 -m pytest tests/test_linkiigs_symtab_units.py
    python3 tests/test_linkiigs_symtab_units.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from gsasm import asm, omf, linkiigs                # noqa: E402
from gsasm import expressload as E                  # noqa: E402


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------

def _assemble(sources):
    """Assemble each source text; return ``[(obj_bytes, Asm), ...]``."""
    out = []
    with tempfile.TemporaryDirectory() as tmp:
        for i, text in enumerate(sources):
            path = os.path.join(tmp, 'u%d.aii' % i)
            with open(path, 'w') as fh:
                fh.write(text)
            a = asm.assemble(path, [tmp])
            assert not a.errors, (i, a.errors[:3])
            out.append((omf.emit(a), a))
    return out


def _symtab(objects, extern=None):
    """Run passes 1+2 exactly as ``link()`` does; return the three tables."""
    placed, bases, pidx = linkiigs._place(objects, 0)
    sym, obj_globals = linkiigs._build_symtab(objects, placed, bases, pidx,
                                              extern)
    return placed, sym, obj_globals


def _link_syms(sources, extern=None):
    return _symtab(_assemble(sources), extern)


def _seg_base(placed, segname):
    for name, _recs, base, _hdr, _asm in placed:
        if name == segname:
            return base
    raise AssertionError('segment %r not placed: %r'
                         % (segname, [p[0] for p in placed]))


def _combo(sources):
    """Fuse N assembled objects into ONE pre-concatenated blob with no Asm —
    the TS2/TS3 ``-lseg`` group shape that rule R3 is about."""
    parts = _assemble(sources)
    return (b''.join(ob for ob, _a in parts), None)


# ---------------------------------------------------------------------------
# Sources.  Every PROC gets a distinct body length so a bound VALUE identifies
# which definition won without ambiguity.
# ---------------------------------------------------------------------------

# R1/R2: the same name ENTRYed by both objects (no EXPORT anywhere).
SRC_ENTRY_A = ('Aseg\tPROC\n\tENTRY\tent\n\tds.b\t4\nent\tdc.w\t$1111\n'
               '\tENDP\n\tEND\n')
SRC_ENTRY_B = ('Bseg\tPROC\n\tENTRY\tent\n\tds.b\t16\nent\tdc.w\t$2222\n'
               '\tENDP\n\tEND\n')

# R2: ENTRY here, EXPORT there.
SRC_ENTRY_ONLY = ('Aseg\tPROC\n\tENTRY\tboth\n\tds.b\t4\nboth\tdc.w\t$1111\n'
                  '\tENDP\n\tEND\n')
SRC_EXPORT_ONLY = ('Bseg\tPROC\n\tEXPORT\tboth\n\tds.b\t16\n'
                   'both\tdc.w\t$2222\n\tENDP\n\tEND\n')

# R1/R6: the same name EXPORTed as an EQU by both objects (GEQU records).
SRC_EQU_11 = ('\tEXPORT\tkonst\nkonst\tequ\t$11\nEaseg\tPROC\n\trts\n'
              '\tENDP\n\tEND\n')
SRC_EQU_22 = ('\tEXPORT\tkonst\nkonst\tequ\t$22\nEbseg\tPROC\n\trts\n'
              '\tENDP\n\tEND\n')

# R5: a plain interior label whose name another object EXPORTs, plus an
# interior label nobody exports (the exemption control).
SRC_PRIVATE_LABEL = ('Aseg\tPROC\n\tEXPORT\tAseg\n\tds.b\t4\n'
                     'priv\tdc.w\t$1111\nhelper\tdc.w\t$3333\n\tENDP\n\tEND\n')
SRC_EXPORTS_PRIV = ('Bseg\tPROC\n\tEXPORT\tpriv\n\tds.b\t16\n'
                    'priv\tdc.w\t$2222\n\tENDP\n\tEND\n')

# R4: a PUBLIC PROC named `update`, and a LATER proc holding an interior
# label `UPDATE` that folds to the same key and clobbers asm.symbols.  The
# second PROC (`Other`) is a public segment name that is NOT clobbered — the
# control for the same test.
SRC_CASE_CLOBBER = ('update\tPROC\n\tEXPORT\tupdate\n\tdc.w\t$5678\n\tENDP\n'
                    'Other\tPROC\n\tds.b\t8\nUPDATE\tdc.w\t$1234\n\trts\n'
                    '\tENDP\n\tEND\n')
# ...and an object that EXPORTs the same name as a real label, far away.
SRC_EXPORTS_UPDATE = ('Xseg\tPROC\n\tEXPORT\tupdate\n\tds.b\t32\n'
                      'update\tdc.w\t$9999\n\tENDP\n\tEND\n')

# R6/R1 interaction: same name as an exported EQU in one object and an
# exported relocatable LABEL in another.
SRC_CLASH_EQU = ('\tEXPORT\tclash\nclash\tequ\t$77\nEseg\tPROC\n\trts\n'
                 '\tENDP\n\tEND\n')
SRC_CLASH_LABEL = ('Lseg\tPROC\n\tEXPORT\tclash\n\tds.b\t16\n'
                   'clash\tdc.w\t$2222\n\tENDP\n\tEND\n')

# R3: two combo constituents EXPORTing the same name at different offsets.
SRC_DUAL_1 = ('Combo1\tPROC\n\tEXPORT\tdual\n\tds.b\t4\ndual\tdc.w\t$1111\n'
              '\tENDP\n\tEND\n')
SRC_DUAL_2 = ('Combo2\tPROC\n\tEXPORT\tdual\n\tds.b\t20\ndual\tdc.w\t$2222\n'
              '\tENDP\n\tEND\n')
# R2 inside a combo: an ENTRY-only constituent (priv GLOBAL record).
SRC_COMBO_ENTRY = ('Eseg\tPROC\n\tENTRY\tpent\n\tds.b\t4\npent\tdc.w\t$1111\n'
                   '\tENDP\n\tEND\n')
SRC_COMBO_EXPORT = ('Xseg\tPROC\n\tEXPORT\txpub\n\tds.b\t2\n'
                    'xpub\tdc.w\t$2222\n\tENDP\n\tEND\n')

# A plain unrelated object, so a link is genuinely multi-object.
SRC_OTHER = ('Zseg\tPROC\n\trts\n\tENDP\n\tEND\n')


# ---------------------------------------------------------------------------
# R1 — first-wins
# ---------------------------------------------------------------------------

def test_rule1_first_wins_for_entry_only_name_across_objects():
    """Pass (b) is a setdefault: the FIRST object's ENTRY keeps the binding.

    An ENTRY-only name (nobody EXPORTs it) is published by pass (b) and
    never re-touched by pass (c) — its GLOBAL record is priv=1 and skipped —
    so this is first-wins in its purest observable form.
    """
    placed, sym, _og = _link_syms([SRC_ENTRY_A, SRC_ENTRY_B])
    first = _seg_base(placed, 'ASEG') + 4
    later = _seg_base(placed, 'BSEG') + 16
    assert first != later, (first, later)
    assert sym['ENT'] == first, (hex(sym['ENT']), hex(first), hex(later))


def test_rule1_first_wins_for_exported_equ_geq_records():
    """The GEQU arm of pass (c) is a setdefault: the FIRST GEQU wins.

    Both objects EXPORT ``konst equ`` with different values; the link takes
    the first placed object's $11 and never the second's $22.
    """
    _placed, sym, _og = _link_syms([SRC_EQU_11, SRC_EQU_22])
    assert sym['KONST'] == 0x11, hex(sym['KONST'])
    assert sym.kinds['KONST'] == 'equ', sym.kinds


def test_rule1_public_export_globals_are_last_wins_not_first_wins():
    """The one arm of the table that is NOT first-wins, pinned deliberately.

    For a MULTI-object link, pass (c) uses ``_kind_override`` for public
    EXPORT GLOBALs so the canonical library module (linked last, e.g.
    wcm.asm's PUSHRECT) wins over earlier duplicates — the direct opposite
    of R1, on the same table.  A single-object link keeps setdefault.
    """
    placed, sym, _og = _link_syms([SRC_DUAL_1, SRC_DUAL_2])
    first = _seg_base(placed, 'COMBO1') + 4
    last = _seg_base(placed, 'COMBO2') + 20
    assert first != last, (first, last)
    assert sym['DUAL'] == last, (hex(sym['DUAL']), hex(first), hex(last))


# ---------------------------------------------------------------------------
# R2 — ENTRY-vs-EXPORT precedence
# ---------------------------------------------------------------------------

def test_rule2_entry_is_demoted_when_another_object_exports_the_name():
    """Finder ``Misc.aii ENTRY GetFileInfo`` vs ``GSOS.aii EXPORT GetFileInfo``.

    The ENTRY is a PRIVATE entry point: with an EXPORT of the same name
    anywhere in the link, pass (b) refuses to publish it and the global
    table binds the EXPORT.  The ENTRY's own object still sees its own
    definition (see the R2xR5 interaction test).
    """
    placed, sym, _og = _link_syms([SRC_ENTRY_ONLY, SRC_EXPORT_ONLY])
    entry_addr = _seg_base(placed, 'ASEG') + 4
    export_addr = _seg_base(placed, 'BSEG') + 16
    assert sym['BOTH'] == export_addr, (hex(sym['BOTH']), hex(entry_addr))


def test_rule2_entry_only_name_stays_globally_visible():
    """The complement: a name that is ONLY ever ENTRYed is link-visible."""
    placed, sym, _og = _link_syms([SRC_ENTRY_ONLY, SRC_OTHER])
    assert sym['BOTH'] == _seg_base(placed, 'ASEG') + 4, hex(sym['BOTH'])


def test_rule2_private_entry_global_record_is_skipped_in_pass_c():
    """The pass-(c) arm of R2, reachable only through a combo object.

    A combo (``asm is None``) has no ``.entries`` for pass (b) to consult,
    so the ``priv`` bit on the GLOBAL record itself is the whole signal: a
    priv=1 (ENTRY) record never enters the global table, while the priv=0
    (EXPORT) record from a sibling constituent does.  Both land in the
    combo's per-object map.
    """
    combo = _combo([SRC_COMBO_ENTRY, SRC_COMBO_EXPORT])
    placed, sym, og = _symtab([combo] + _assemble([SRC_OTHER]))
    assert 'PENT' not in sym, dict(sym)
    assert sym['XPUB'] == _seg_base(placed, 'XSEG') + 2, hex(sym['XPUB'])
    assert og[0]['PENT'] == _seg_base(placed, 'ESEG') + 4, dict(og[0])
    assert og[0]['XPUB'] == sym['XPUB'], dict(og[0])


# ---------------------------------------------------------------------------
# R3 — combo setdefault
# ---------------------------------------------------------------------------

def test_rule3_combo_per_object_map_uses_setdefault_for_globals():
    """TS2 ``-lseg`` shape: inside ONE fused blob, first constituent wins.

    A pre-concatenated object has no per-FILE scoping left, so its
    per-object map must not let a later constituent's GLOBAL clobber an
    earlier one.  The SAME two records override each other in the global
    table — the contrast is the rule.
    """
    combo = _combo([SRC_DUAL_1, SRC_DUAL_2])
    placed, sym, og = _symtab([combo] + _assemble([SRC_OTHER]))
    first = _seg_base(placed, 'COMBO1') + 4
    last = _seg_base(placed, 'COMBO2') + 20
    assert og[0]['DUAL'] == first, (hex(og[0]['DUAL']), hex(first), hex(last))
    assert sym['DUAL'] == last, (hex(sym['DUAL']), hex(first), hex(last))


def test_rule3_real_object_per_object_map_uses_override_for_globals():
    """The control: with real Asm objects each object's map takes its OWN
    GLOBAL (the windmgr/WDefProc PUSHRECT preference), so the two maps
    disagree — which is exactly what pass 3's ``{**sym, **og}`` exploits."""
    placed, _sym, og = _link_syms([SRC_DUAL_1, SRC_DUAL_2])
    assert og[0]['DUAL'] == _seg_base(placed, 'COMBO1') + 4, dict(og[0])
    assert og[1]['DUAL'] == _seg_base(placed, 'COMBO2') + 20, dict(og[1])


# ---------------------------------------------------------------------------
# R4 — case-collision repair
# ---------------------------------------------------------------------------

def test_rule4_case_collision_repair_publishes_the_segment_base():
    """notesynth ``UpDate`` shape.

    gsasm folds label case, so the interior label ``UPDATE`` inside the
    ``Other`` PROC has clobbered ``asm.symbols['UPDATE']`` (its symseg now
    points at ``Other``, not at the ``update`` segment).  Pass (a) detects
    that and publishes the segment's authoritative placement base into the
    GLOBAL table — even in a multi-object link, where an uncollided public
    segment name is deliberately kept object-private.
    """
    placed, sym, _og = _link_syms([SRC_CASE_CLOBBER, SRC_OTHER])
    assert sym['UPDATE'] == _seg_base(placed, 'UPDATE'), hex(sym['UPDATE'])
    # ...and NOT the interior label that clobbered it.
    assert sym['UPDATE'] != _seg_base(placed, 'OTHER') + 8, hex(sym['UPDATE'])


def test_rule4_uncollided_public_segname_stays_out_of_the_global_table():
    """The control, from the same fixture: ``Other`` is an ordinary public
    PROC name whose asm.symbols entry was NOT clobbered, so pass (a) leaves
    it out of the multi-object global table (a PROC name must not shadow a
    cross-object EXPORT).  It is still in its own object's map."""
    _placed, sym, og = _link_syms([SRC_CASE_CLOBBER, SRC_OTHER])
    assert 'OTHER' not in sym, dict(sym)
    assert 'OTHER' in og[0], dict(og[0])
    assert 'ZSEG' not in sym, dict(sym)


# ---------------------------------------------------------------------------
# R5 — module privacy (MPW Asm Ref p.63, verbatim)
# ---------------------------------------------------------------------------

def test_rule5_plain_interior_label_is_module_private_when_name_is_exported():
    """ATP1.ATROM ``CloseSkt`` shape.

    Object A's plain interior label ``priv`` is neither EXPORTed nor
    ENTRYed, and object B EXPORTs that name — so A's label is dropped from
    A's OWN per-object map, and a by-name reference from a sibling module
    of A binds B's program-wide EXPORT.
    """
    placed, sym, og = _link_syms([SRC_PRIVATE_LABEL, SRC_EXPORTS_PRIV])
    assert 'PRIV' not in og[0], dict(og[0])
    assert sym['PRIV'] == _seg_base(placed, 'BSEG') + 16, hex(sym['PRIV'])


def test_rule5_unexported_interior_label_still_resolves_intra_object():
    """The exemption control: a name nobody EXPORTs is NOT module-private —
    it stays in its own object's map (and out of the global table)."""
    placed, sym, og = _link_syms([SRC_PRIVATE_LABEL, SRC_OTHER])
    assert og[0]['HELPER'] == _seg_base(placed, 'ASEG') + 6, dict(og[0])
    assert 'HELPER' not in sym, dict(sym)


def test_rule5_does_not_apply_to_a_single_object_link():
    """Single-object links keep the original behaviour: every interior label
    is published to BOTH tables, module privacy never engages (there is no
    sibling object whose EXPORT could win)."""
    placed, sym, og = _link_syms([SRC_PRIVATE_LABEL])
    base = _seg_base(placed, 'ASEG')
    assert sym['PRIV'] == base + 4, hex(sym['PRIV'])
    assert sym['HELPER'] == base + 6, hex(sym['HELPER'])
    assert og[0]['PRIV'] == base + 4, dict(og[0])


# ---------------------------------------------------------------------------
# R6 — symbol KINDs
# ---------------------------------------------------------------------------

def test_rule6_exported_equ_is_kind_equ_and_labels_are_kind_label():
    """The GEQU-vs-GLOBAL structural signal that drives reloc suppression."""
    _placed, sym, og = _link_syms([SRC_EQU_11, SRC_ENTRY_A])
    assert sym.kinds['KONST'] == 'equ', sym.kinds
    assert sym.kinds['ENT'] == 'label', sym.kinds
    # Segment names are always 'label' (a relocatable address).
    assert og[1].kinds['ASEG'] == 'label', og[1].kinds
    # The seeded origin marker is a label too.
    assert sym.kinds['__LOC__'] == 'label', sym.kinds


def test_rule6_a_non_exported_equ_never_reaches_either_table():
    """The narrowness of the 'equ' kind, pinned.

    Only an EXPORTed EQU emits a GEQU record and so becomes kind 'equ'; a
    proc-local EQU (which may alias a relocatable address, ``devName equ
    ParBlock+2``) has no ``symseg`` at all, so pass (b) skips it and it
    never appears in any table.  That is what keeps constant-kinds out of
    the multiseg fallback union (the TS2 0x88a regression shape).
    """
    src = ('Aseg\tPROC\n\tEXPORT\tAseg\nParBlock\tds.b\t8\n'
           'devName\tequ\tParBlock+2\n\tlda\tdevName\n\trts\n\tENDP\n\tEND\n')
    objects = _assemble([src, SRC_OTHER])
    a = objects[0][1]
    assert a.symtype['DEVNAME'] == 'equ', a.symtype
    assert a.symseg.get('DEVNAME') is None, a.symseg
    _placed, sym, og = _symtab(objects)
    assert 'DEVNAME' not in sym, dict(sym)
    assert 'DEVNAME' not in og[0], dict(og[0])
    assert og[0].kinds.get('PARBLOCK') == 'label', og[0].kinds


def test_rule6_caller_extern_is_always_kind_label():
    """An extern has no GEQU behind it, so reloc suppression for an absolute
    extern stays with ``_scan_relocs``'s value-range fallback — even when
    the name it overrides WAS an 'equ'."""
    _placed, sym, _og = _link_syms([SRC_EQU_11, SRC_OTHER],
                                   extern={'konst': 0x999})
    assert sym['KONST'] == 0x999, hex(sym['KONST'])
    assert sym.kinds['KONST'] == 'label', sym.kinds


# ---------------------------------------------------------------------------
# INTERACTIONS — which rule wins when two could both apply
# ---------------------------------------------------------------------------

def test_interaction_rule4_beats_rule1b_within_one_object():
    """R4 (pass a) vs R1-on-pass-(b), same object, same folded name.

    ``update`` is BOTH a public segment head (repaired by R4) and an
    EXPORTed interior label of the same folded key.  Pass (a) runs before
    pass (b) and both are setdefaults, so the SEGMENT BASE wins and the
    interior label's address never reaches the global table.
    """
    src = ('update\tPROC\n\tEXPORT\tupdate\n\tdc.w\t$5678\n\tENDP\n'
           'SetUserUpdateRtn\tPROC\n\tEXPORT\tSetUserUpdateRtn\n\tds.b\t8\n'
           'UpDate\tdc.w\t$1234\n\trts\n\tENDP\n\tEND\n')
    placed, sym, _og = _link_syms([src, SRC_OTHER])
    seg_base = _seg_base(placed, 'UPDATE')
    interior = _seg_base(placed, 'SETUSERUPDATERTN') + 8
    assert seg_base != interior, (seg_base, interior)
    assert sym['UPDATE'] == seg_base, (hex(sym['UPDATE']), hex(interior))


def test_interaction_export_global_pass_c_beats_rule4_in_the_global_table():
    """R4 (pass a) vs the multi-object OVERRIDE arm of pass (c).

    Pass order decides: the repaired segment base is a setdefault in pass
    (a), and pass (c) later OVERRIDES it with the sibling object's public
    EXPORT GLOBAL.  The repair survives only in the defining object's own
    per-object map — which is what pass 3 layers on top, so the defining
    object still sees its own segment.
    """
    placed, sym, og = _link_syms([SRC_CASE_CLOBBER, SRC_EXPORTS_UPDATE])
    exported = _seg_base(placed, 'XSEG') + 32
    repaired = _seg_base(placed, 'UPDATE')
    assert sym['UPDATE'] == exported, (hex(sym['UPDATE']), hex(repaired))
    assert og[0]['UPDATE'] == repaired, dict(og[0])


def test_interaction_rule2_exempts_the_entry_from_rule5_module_privacy():
    """R2 x R5: an ENTRY demoted from the global table is STILL its own
    object's binding.

    R2 keeps A's ENTRY out of the global table because B EXPORTs the name;
    R5 would drop a *plain* interior label from A's per-object map for the
    same reason — but an ENTRY is explicitly exempt.  So A's own references
    bind A's ENTRY while everyone else's bind B's EXPORT.
    """
    placed, sym, og = _link_syms([SRC_ENTRY_ONLY, SRC_EXPORT_ONLY])
    entry_addr = _seg_base(placed, 'ASEG') + 4
    export_addr = _seg_base(placed, 'BSEG') + 16
    assert og[0]['BOTH'] == entry_addr, dict(og[0])
    assert sym['BOTH'] == export_addr, hex(sym['BOTH'])
    assert og[1]['BOTH'] == export_addr, dict(og[1])


def test_interaction_exported_label_beats_exported_equ_in_either_order():
    """R6 x R1: pass order, not object order, decides.

    Pass (b) publishes every EXPORTed relocatable label before pass (c)
    looks at a single GEQU, and the GEQU arm is a setdefault — so an
    exported LABEL beats an exported EQU of the same name whichever object
    is linked first, and the surviving KIND is 'label' both ways.
    """
    for order in ([SRC_CLASH_EQU, SRC_CLASH_LABEL],
                  [SRC_CLASH_LABEL, SRC_CLASH_EQU]):
        placed, sym, _og = _link_syms(order)
        label_addr = _seg_base(placed, 'LSEG') + 16
        assert sym['CLASH'] == label_addr, (order[0][:12], hex(sym['CLASH']))
        assert sym['CLASH'] != 0x77, hex(sym['CLASH'])
        assert sym.kinds['CLASH'] == 'label', sym.kinds


def test_interaction_extern_overrides_every_earlier_rule():
    """R-extern beats R1/R2/R4/R5/R6: it is the last pass and it overrides.

    One link in which a case-repaired segment name, an ENTRY-only name and
    an exported EQU are all present — the caller's extern replaces all
    three values and flattens all three kinds to 'label'.
    """
    sources = [SRC_CASE_CLOBBER, SRC_ENTRY_ONLY, SRC_EQU_11]
    placed, plain, _og = _link_syms(sources)
    assert plain['UPDATE'] == _seg_base(placed, 'UPDATE'), hex(plain['UPDATE'])
    assert plain['BOTH'] == _seg_base(placed, 'ASEG') + 4, hex(plain['BOTH'])
    assert plain['KONST'] == 0x11, hex(plain['KONST'])
    _placed, sym, _og = _link_syms(
        sources, extern={'update': 0xE10000, 'both': 0xE10004,
                         'konst': 0xE10008})
    assert sym['UPDATE'] == 0xE10000, hex(sym['UPDATE'])
    assert sym['BOTH'] == 0xE10004, hex(sym['BOTH'])
    assert sym['KONST'] == 0xE10008, hex(sym['KONST'])
    assert all(sym.kinds[n] == 'label' for n in ('UPDATE', 'BOTH', 'KONST')), \
        sym.kinds


def test_interaction_rule5_module_privacy_beats_rule6_equ_lookup_source():
    """R5 x R6, on the KIND rather than the value.

    A's plain interior label is module-private (R5), so A's own map has no
    entry for the name at all — which means the KIND that A's reloc
    classification sees is the one attached to B's EXPORT-EQU, i.e. 'equ'.
    Module privacy therefore silently re-KINDs a reference inside A.
    (The reloc consequence of this is covered end-to-end by
    tests/test_expressload_export_equ.py; here it is pinned at the table.)
    """
    src_priv = ('Aseg\tPROC\n\tEXPORT\tAseg\n\tlda\t#small_const\n\trts\n'
                '\tENDP\nAdat\tPROC\nsmall_const\tdc.w\t0\n\tENDP\n\tEND\n')
    src_equ = ('\tEXPORT\tsmall_const\nsmall_const\tequ\t3\nBseg\tPROC\n'
               '\trts\n\tENDP\n\tEND\n')
    _placed, sym, og = _link_syms([src_priv, src_equ])
    assert 'SMALL_CONST' not in og[0], dict(og[0])
    assert sym['SMALL_CONST'] == 3, hex(sym['SMALL_CONST'])
    assert sym.kinds['SMALL_CONST'] == 'equ', sym.kinds


# ---------------------------------------------------------------------------
# SymTab itself — the dict-with-attribute, and its known latent gap
# ---------------------------------------------------------------------------

def test_symtab_is_a_plain_dict_with_an_empty_kinds_sidecar():
    t = linkiigs.SymTab({'A': 1})
    assert isinstance(t, dict) and t['A'] == 1
    # The sidecar is NOT populated by construction — only by the
    # _kind_setdefault/_kind_override helpers.
    assert t.kinds == {}, t.kinds


def test_symtab_kind_setdefault_is_first_wins_in_lockstep():
    t = linkiigs.SymTab()
    linkiigs._kind_setdefault(t, 'N', 10, 'equ')
    linkiigs._kind_setdefault(t, 'N', 20, 'label')
    assert t['N'] == 10 and t.kinds['N'] == 'equ', (dict(t), t.kinds)


def test_symtab_kind_override_is_last_wins_in_lockstep():
    t = linkiigs.SymTab()
    linkiigs._kind_setdefault(t, 'N', 10, 'equ')
    linkiigs._kind_override(t, 'N', 20, 'label')
    assert t['N'] == 20 and t.kinds['N'] == 'label', (dict(t), t.kinds)


def test_symtab_dict_splat_merge_silently_drops_the_kinds_sidecar():
    """PINNED, NOT FIXED — architecture review 2026-08-02, supervisor's
    chapter: ``SymTab`` was made a dict-with-attribute to avoid touching six
    call sites, and the tax is that ``{**a, **b}`` yields a bare ``dict``
    with no ``.kinds`` at all.  ``linkiigs.py``'s pass 3 builds its
    ``local_sym`` exactly that way, which is the latent gap the review names:
    a future kinds consumer reading ``local_sym.kinds`` gets an
    AttributeError, and one calling ``getattr(..., 'kinds', {})`` gets an
    EMPTY table (every symbol silently re-classified as not-an-equ).

    ``gsasm/expressload.py`` works around this by merging the two ``.kinds``
    dicts by hand at every merge point.  A later packet redesigns SymTab;
    if this assertion starts failing, the semantics changed — check every
    hand-rolled kinds merge before blessing it.
    """
    a = linkiigs.SymTab()
    linkiigs._kind_setdefault(a, 'A', 1, 'equ')
    b = linkiigs.SymTab()
    linkiigs._kind_setdefault(b, 'B', 2, 'label')
    merged = {**a, **b}
    assert merged == {'A': 1, 'B': 2}
    assert type(merged) is dict, type(merged)
    assert not hasattr(merged, 'kinds')
    assert getattr(merged, 'kinds', {}) == {}
    # The hand-rolled merge every kinds consumer must perform instead:
    assert {**a.kinds, **b.kinds} == {'A': 'equ', 'B': 'label'}


def test_symtab_kinds_survive_a_real_link_but_not_a_dict_copy():
    """The same gap, reached through the real ``_build_symtab`` output."""
    _placed, sym, _og = _link_syms([SRC_EQU_11, SRC_OTHER])
    assert sym.kinds['KONST'] == 'equ'
    assert getattr(dict(sym), 'kinds', {}) == {}


# ---------------------------------------------------------------------------
# _scan_relocs — the record-stream walk
#
# Hand-built OMF record streams (no assembler, no corpus).  The reloc
# CLASSIFICATION rules (net-zero weight, absolute-target drop, EXPORT-EQU
# suppression, super-class selection per toolchain, SUPER type 26 vs 27) are
# already pinned by tests/test_expressload_{reloc_weight,absolute_target,
# export_equ,super_classes}.py and tests/test_linkiigs_super_type26.py; what
# follows pins the WALK — offset accounting, termination, and which
# (size, shift) pairs have a SUPER class at all.
# ---------------------------------------------------------------------------

_SHIFT16 = ('lit', 0xFFFFFFF0)          # -16, the OMF encoding of `>>16`

_WALK_RECS = [
    ('', 'LCONST', b'\x01\x02\x03\x04'),                       # off 0..3
    ('', 'EXPR', (2, [('sym', 'L'), 'end'])),                  # off 4  -> t0
    ('', 'DS', 3),                                             # off 6..8
    ('', 'LEXPR', (3, [('sym', 'L'), 'end'])),                 # off 9  -> t1
    ('', 'EXPR', (2, [('lit', 5), 'end'])),                    # off 12 literal
    ('', 'EXPR', (2, [('sym', 'L'), _SHIFT16, ('op', 7), 'end'])),  # 14 -> t27
    ('', 'EXPR', (1, [('sym', 'L'), 'end'])),                  # off 16 size 1
    ('', 'RELEXPR', (2, [('sym', 'L'), 'end'])),               # off 17..18
    ('', 'EXPR', (4, [('sym', 'L'), 'end'])),                  # off 19 -> t1
    ('', 'END', None),
    ('', 'EXPR', (2, [('sym', 'L'), 'end'])),                  # after END
]
_WALK_BASE = 0x2000
_WALK_PLACED = [('walk', _WALK_RECS, _WALK_BASE, {}, None)]


def test_scan_relocs_offsets_are_segment_base_plus_running_body_offset():
    """LCONST/CONST advance by their byte length, DS by its count, every
    EXPR-family record by its size field — and the reported offset is
    ``seg_base + body_off``, not the record index."""
    relocs = E._scan_relocs(_WALK_PLACED)
    assert relocs == {0: [_WALK_BASE + 4],
                      1: [_WALK_BASE + 9, _WALK_BASE + 19],
                      27: [_WALK_BASE + 14]}, relocs


def test_scan_relocs_skips_pure_literal_expressions():
    """The size-2 literal at offset 12 has no symbol, so it is a link-time
    constant and gets no record — its bytes still advance the offset (proved
    by the offsets asserted above)."""
    relocs = E._scan_relocs(_WALK_PLACED)
    assert _WALK_BASE + 12 not in [o for lst in relocs.values() for o in lst]


def test_scan_relocs_stops_at_the_end_record():
    """A record stream may carry trailing records after END (the tail
    records a load segment appends); the scan must not walk into them."""
    relocs = E._scan_relocs(_WALK_PLACED)
    flat = sorted(o for lst in relocs.values() for o in lst)
    assert flat == [_WALK_BASE + 4, _WALK_BASE + 9,
                    _WALK_BASE + 14, _WALK_BASE + 19], flat


def test_scan_relocs_has_no_super_class_for_a_one_byte_reference():
    """``_SUPER_TYPE`` has no size-1 entry at ANY shift: a 1-byte patch field
    can never hold a 16/24-bit offset, so it is routed to
    ``_scan_standalone_relocs`` instead of a SUPER page list."""
    assert not any((1, s) in E._SUPER_TYPE for s in (0, 8, 16)), E._SUPER_TYPE
    relocs = E._scan_relocs(_WALK_PLACED)
    assert _WALK_BASE + 16 not in [o for lst in relocs.values() for o in lst]
    standalone = E._scan_standalone_relocs(_WALK_PLACED)
    assert (_WALK_BASE + 16, 1, 0) in [(o, sz, sh)
                                       for o, sz, sh, _ops, _i in standalone], \
        standalone


def test_scan_relocs_super_classes_argument_filters_by_size_and_shift():
    """The per-build class set (the 30-Apr-93 encoder folds only (2,0)) is
    applied at the scan, and the excluded classes vanish from the reloc
    dictionary entirely rather than moving to another SUPER type."""
    relocs = E._scan_relocs(_WALK_PLACED, E.SUPER_CLASSES_APR93)
    assert relocs == {0: [_WALK_BASE + 4]}, relocs


def test_scan_relocs_merges_segments_and_sorts_each_class():
    """Two placed segments at non-monotonic bases: offsets from both land in
    the same per-type list, and every list comes back sorted ascending."""
    recs_a = [('', 'EXPR', (2, [('sym', 'L'), 'end'])),
              ('', 'LCONST', b'\x00' * 4),
              ('', 'EXPR', (2, [('sym', 'L'), 'end'])),
              ('', 'END', None)]
    recs_b = [('', 'EXPR', (2, [('sym', 'L'), 'end'])), ('', 'END', None)]
    placed = [('hi', recs_a, 0x400, {}, None), ('lo', recs_b, 0x100, {}, None)]
    relocs = E._scan_relocs(placed)
    assert relocs == {0: [0x100, 0x400, 0x406]}, relocs


def test_scan_relocs_empty_stream_returns_empty_dictionary():
    assert E._scan_relocs([('e', [('', 'END', None)], 0, {}, None)]) == {}


_TESTS = [(n, f) for n, f in sorted(globals().items())
          if n.startswith('test_') and callable(f)]

if __name__ == '__main__':
    failed = 0
    for name, fn in _TESTS:
        try:
            fn()
        except AssertionError as exc:
            failed += 1
            print(f'FAIL {name}: {exc}')
        else:
            print(f'ok   {name}')
    print(f'{len(_TESTS) - failed}/{len(_TESTS)} passed')
    sys.exit(1 if failed else 0)
