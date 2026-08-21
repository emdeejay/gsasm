"""Cross-check that the FOUR restatements of "is this symbol shadowed here"
agree — the enforcement half of docs/CONTRACT_SYMBOL_PRECEDENCE.md.

The 2026-08-02 architecture review's finding #1: one scoping rule is
independently restated in four places, and *nothing tests that they agree*:

    asm.resolve()      gsasm/asm.py   — WHICH definition binds (the VALUE)
    asm.sym_kind()     gsasm/asm.py   — WHAT that definition is ('label' /
                                        'equ' / 'import' / None) -> operand
                                        SIZING, via asm.is_reloc()
    asm.needs_reloc()  gsasm/asm.py   — does the reference need an OMF
                                        relocation record at all
    omf._expr_for()    gsasm/omf.py   — WHAT the relocation record says
                                        (by-name / SEGNAME+offset / literal)

They answer four different questions about ONE decision, so "agree" needs a
predicate.  The contract states two:

    INVARIANT A (kind <-> emission)
        sym_kind(n) == 'equ'  <=>  _expr_for emits a pure literal push,
        and resolve(n) is the value that literal carries.

    INVARIANT B (relocatability <-> emission)
        needs_reloc(n)  <=>  _expr_for emits a symbolic reference
        (a 0x83 label push: by-name or SEGNAME+offset).

Both invariants have DOCUMENTED exceptions — cells where the four legitimately
differ because they answer different questions, or where a caller bridges the
gap.  Those cells are not skipped: ``_DIVERGENCES`` lists every one of them
with its reason, the sweep asserts that each listed cell *still* diverges (so
the register cannot rot), and a named test below pins each one's exact shape.

TWO OF THOSE CELLS ARE LIVE DISAGREEMENTS, NOT DESIGN — see the two
``test_disagreement_*`` tests.  Both have the same root cause: ``needs_reloc``
restates the precedence ladder WITHOUT two branches that ``resolve`` and
``sym_kind`` both have (the exact-spelling EQU variant, and the "no current
segment -> use the last one" fallback).  They are unobservable in the corpus
today only because of which phase each function is called from.  They are
PINNED here, deliberately not fixed: this is a byte-exact system and a fix is
a behaviour change that must be gate-measured on its own commit.

These tests are CORPUS-FREE (synthetic sources in a tempdir): they run in CI
with no ``ref/`` tree.

Run either as:
    python3 -m pytest tests/test_symbol_precedence_agreement.py
    python3 tests/test_symbol_precedence_agreement.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from gsasm import asm, omf                                    # noqa: E402


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------

_ASM_CACHE: dict = {}


def assemble(source: str, **kw):
    """Assemble *source* from a temp dir and return the Assembler (memoised)."""
    key = (source, tuple(sorted((k, tuple(sorted(v)) if isinstance(v, set)
                                 else v) for k, v in kw.items())))
    a = _ASM_CACHE.get(key)
    if a is None:
        d = tempfile.mkdtemp()
        path = os.path.join(d, 't.aii')
        with open(path, 'w') as fh:
            fh.write(source)
        a = asm.assemble(path, [d], **kw)
        assert not a.errors, a.errors[:3]
        _ASM_CACHE[key] = a
    return a


def in_seg(a, name):
    """Point the assembler's emit-time cursor at segment *name* (what
    ``emit_segment`` does before calling any of the four) and return the
    folded SEGNAME ``_expr_for`` expects as its ``segname`` argument."""
    folded = a._fold(name)
    a._rseg = next(i for i, s in enumerate(a.segs)
                   if a._fold(s.name or '') == folded)
    a.loc = 0
    a._rlg = a._rlg2 = a._rwith = None
    return folded


def emission(a, name, segname, ref_off=None):
    """Classify what ``_expr_for`` emits for a bare symbol reference.

    Returns ``('literal', value)`` when the expression is a pure constant
    push, or ``('symbolic', PUSHED_NAME, addend)`` when it pushes a label
    (0x83) — the linker-resolved forms, i.e. a relocation.
    """
    ops = omf._expr_for(a, name, segname, ref_off=ref_off)
    pushed = None
    lits = []
    i = 0
    while i < len(ops) and ops[i] != 0x00:
        op = ops[i]
        if op == 0x81:                       # push 4-byte literal
            lits.append(int.from_bytes(ops[i + 1:i + 5], 'little'))
            i += 5
        elif op == 0x83:                     # push label by name
            n = ops[i + 1]
            pushed = ops[i + 2:i + 2 + n].decode('ascii')
            i += 2 + n
        else:                                # ADD / SUB / SHIFT opcode
            i += 1
    if pushed is None:
        return ('literal', lits[0] if lits else 0)
    return ('symbolic', pushed, lits[0] if lits else 0)


def answers(a, name, segname, ref_off=None):
    """The four restatements' answers for one matrix cell."""
    return {
        'value': a.resolve(name),
        'kind': a.sym_kind(name),
        'reloc': a.needs_reloc(name),
        'emits': emission(a, name, segname, ref_off),
    }


def cell(a, segname, name, ref_off=None):
    """Point the cursor at *segname*, then answer for *name*."""
    sg = in_seg(a, segname)
    return answers(a, name, sg, ref_off)


# ---------------------------------------------------------------------------
# Fixtures.  Each names the dimension it adds to the matrix.
# ---------------------------------------------------------------------------

# local-vs-global x EQU-vs-label x exported-vs-not, everything relocatable.
#   ALPHA (public, EXPORT):  ALAB=0  AENTRY=2 (ENTRY)  SHARED=4
#   BETA:                    BLAB=4, and a PROC-local `Shared equ $30` whose
#                            folded name collides with ALPHA's SHARED label
#   GAMMA:                   no definitions at all — the "no local shadow"
#                            control segment
SRC_MAIN = (
    '\tIMPORT\tExtSym\n'
    'FileEqu\tequ\t$40\n'
    'Alpha\tPROC\n'
    '\tEXPORT\tAlpha\n'
    '\tENTRY\tAEntry\n'
    'ALab\tdc.w\t0\n'
    'AEntry\tdc.w\t0\n'
    'Shared\tdc.w\t0\n'
    '\tENDP\n'
    'Beta\tPROC\n'
    '\tds.b\t4\n'
    'BLab\tdc.w\t0\n'
    'Shared\tequ\t$30\n'
    '\tENDP\n'
    'Gamma\tPROC\n'
    '\tdc.w\t0\n'
    '\tENDP\n'
    '\tEND\n'
)

# ORG flows forward, so ABS1 and REL are both absolute; TMP is a TEMPORG PROC
# (seg.org stays None, its labels are absolute literals).
SRC_ORG = (
    'Abs1\tPROC\tORG $FF0000\n'
    'O1\tanop\n'
    '\tdc.w\t0\n'
    'O1b\tanop\n'
    '\tdc.w\t0\n'
    '\tENDP\n'
    'Tmp\tPROC\tTEMPORG $2000\n'
    'T1\tanop\n'
    '\tdc.w\t0\n'
    '\tENDP\n'
    'Rel\tPROC\n'
    'R1\tanop\n'
    '\tdc.w\t0\n'
    '\tENDP\n'
    '\tEND\n'
)

# An EQU that ALIASES a relocatable label (`devName equ ParBlock+2`) — kind
# 'equ', but a second NAME for a relocatable address.
SRC_ALIAS = (
    'Data\tPROC\n'
    'ParBlock\tds.b\t8\n'
    'devName\tequ\tParBlock+2\n'
    '\tENDP\n'
    'Code\tPROC\n'
    '\tlda\tdevName\n'
    '\trts\n'
    '\tENDP\n'
    '\tEND\n'
)

# A SET whose name is already a storage LABEL elsewhere: MPW keeps the label
# module-visible and the SET proc-local (CloseView Core.aii `v set h+2`).
SRC_SET = (
    'Store\tPROC\n'
    'v\tdc.w\t0\n'
    '\tENDP\n'
    'Code\tPROC\n'
    'h\tequ\t2\n'
    'v\tset\th+2\n'
    '\tdc.w\tv\n'
    '\tENDP\n'
    '\tEND\n'
)

# An exact-spelling file-scope EQU variant (opt-in `case_equ_variants`, the
# Finder DP handle/Ptr collision) whose FOLDED name is a relocatable label.
SRC_CASE = (
    'Handle\tequ\t$10\n'
    'Store\tPROC\n'
    'HANDLE\tdc.w\t0\n'
    '\tENDP\n'
    'Code\tPROC\n'
    '\tdc.w\t0\n'
    '\tENDP\n'
    '\tEND\n'
)
CASE_KW = {'case_equ_variants': {'HANDLE'}}

# A WITH-active RECORD template field vs a real label of the same bare name.
SRC_WITH = (
    'Frame\tRECORD\t0\n'
    'fptr\tds.w\t1\n'
    'fcount\tds.w\t1\n'
    '\tENDR\n'
    'Data\tPROC\n'
    'fcount\tdc.w\t0\n'
    '\tENDP\n'
    'Code\tPROC\n'
    '\tlda\tfptr\n'
    '\trts\n'
    '\tENDP\n'
    '\tEND\n'
)


# ---------------------------------------------------------------------------
# The generated case matrix, and the register of documented differences.
#
# Every (fixture, current segment, name) triple below is swept against both
# invariants.  A triple listed in _DIVERGENCES is expected to BREAK the named
# invariant — and the sweep asserts it still does, so a silently-closed gap
# fails this file just as loudly as a silently-opened one.
# ---------------------------------------------------------------------------

_MATRIX = [
    # (fixture key, source, kwargs, [segments], [names])
    ('main', SRC_MAIN, {}, ['Alpha', 'Beta', 'Gamma'],
     ['ALab', 'AEntry', 'Shared', 'BLab', 'FileEqu', 'ExtSym', 'NeverSeen']),
    ('org', SRC_ORG, {}, ['Abs1', 'Rel'], ['O1', 'O1b', 'T1', 'R1']),
    ('alias', SRC_ALIAS, {}, ['Data', 'Code'], ['ParBlock', 'devName']),
    ('set', SRC_SET, {}, ['Store', 'Code'], ['v', 'h']),
    ('case', SRC_CASE, CASE_KW, ['Store', 'Code'], ['Handle', 'HANDLE']),
    ('with', SRC_WITH, {}, ['Data', 'Code'], ['fptr', 'fcount']),
]

# (fixture, segment, name) -> (broken invariant, reason).  '*' matches any
# segment.  See docs/CONTRACT_SYMBOL_PRECEDENCE.md part II, "documented
# differences" (D1-D4) and "live disagreements" (X1-X2).
_DIVERGENCES = {
    ('main', '*', 'NeverSeen'): (
        'B', 'D1: an undefined symbol is an IMPLICIT EXTERNAL.  needs_reloc '
             'returns False for it (its docstring says otherwise); every '
             'caller bridges the gap with `or omf._undef_external(...)`.'),
    ('org', 'Abs1', 'O1'): (
        'B', 'D2: a label in an ORG\'d segment is an absolute literal to '
             'needs_reloc, but _expr_for still encodes it as SEGNAME+offset. '
             'The call site never asks _expr_for, because needs_reloc gates '
             'it.'),
    ('org', 'Abs1', 'O1b'): ('B', 'D2, same cell one offset along.'),
    ('org', 'Rel', 'O1'): ('B', 'D2, seen from another ORG\'d segment.'),
    ('org', 'Abs1', 'R1'): ('B', 'D2, ORG flows forward: REL is absolute too.'),
    ('org', 'Rel', 'R1'): ('B', 'D2, same-segment form.'),
    ('org', 'Rel', 'O1b'): ('B', 'D2, cross-segment form.'),
    ('org', '*', 'T1'): (
        'A', 'D3: a TEMPORG segment\'s labels are absolute literals — kind '
             '\'label\' (so they still SIZE absolute) but emitted as a baked '
             'value, because the code runs at `temporg` after being copied '
             'there and the linker must not re-place it.'),
    ('alias', '*', 'devName'): (
        'A', 'D4: an EQU that ALIASES a relocatable label is kind \'equ\' but '
             'must relocate; needs_reloc and _expr_for both consult '
             'asm.equ_alias directly, and asm.is_reloc() re-checks it so '
             'SIZING agrees too.'),
    # NOTE the asymmetry: from STORE, which defines the folded label locally,
    # the segment-local branch fires FIRST in resolve() and sym_kind() and all
    # four agree on the label.  The disagreement needs a segment with no local
    # shadow, where the exact-spelling EQU is the winning definition.
    ('case', 'Code', 'Handle'): (
        'B', 'X1 (LIVE DISAGREEMENT): needs_reloc has no exact-spelling-EQU '
             'branch — see test_disagreement_case_exact_equ_...'),
}


def _divergence(fix, seg, name):
    return (_DIVERGENCES.get((fix, seg, name))
            or _DIVERGENCES.get((fix, '*', name)))


def _sweep():
    """Yield ``(fixture, segment, name, answers, divergence)`` for every cell."""
    for fix, src, kw, segs, names in _MATRIX:
        a = assemble(src, **kw)
        for segname in segs:
            for name in names:
                yield (fix, segname, name, cell(a, segname, name),
                       _divergence(fix, segname, name))


def test_matrix_invariant_b_relocatability_matches_emission():
    """INVARIANT B over the whole generated matrix.

    ``needs_reloc(n)`` is what decides whether the emitter calls ``_expr_for``
    at all (omf.py's mnemonic path: ``if core and (asm.needs_reloc(core) or
    ...)``).  So wherever ``_expr_for`` would emit a SYMBOLIC reference and
    ``needs_reloc`` says False, the reference is silently baked as a literal —
    and wherever the reverse holds, a constant travels inside an EXPR record.
    Every such cell is either a documented difference or a bug.
    """
    broken = []
    for fix, seg, name, ans, div in _sweep():
        agrees = ans['reloc'] == (ans['emits'][0] == 'symbolic')
        if div and div[0] == 'B':
            assert not agrees, (
                'STALE REGISTER: %s/%s/%s no longer diverges — %s'
                % (fix, seg, name, div[1]))
        elif not agrees:
            broken.append((fix, seg, name, ans))
    assert not broken, 'invariant B broken in undocumented cells: %r' % (broken,)


def test_matrix_invariant_a_kind_matches_emission_and_value():
    """INVARIANT A over the whole generated matrix.

    kind 'equ' means "a link-time CONSTANT" — the same word ``SymTab.kinds``
    uses at link time (tests/test_linkiigs_symtab_units.py R6).  An 'equ' must
    therefore emit a pure literal carrying exactly ``resolve()``'s value, and
    a 'label' / 'import' must not.
    """
    broken = []
    for fix, seg, name, ans, div in _sweep():
        is_lit = ans['emits'][0] == 'literal'
        agrees = (ans['kind'] == 'equ') == is_lit
        if agrees and ans['kind'] == 'equ':
            # ... and the literal carries resolve()'s value.
            agrees = ans['emits'][1] == (ans['value'] & 0xFFFFFF)
        if div and div[0] == 'A':
            assert not agrees, (
                'STALE REGISTER: %s/%s/%s no longer diverges — %s'
                % (fix, seg, name, div[1]))
        elif not agrees:
            broken.append((fix, seg, name, ans))
    assert not broken, 'invariant A broken in undocumented cells: %r' % (broken,)


def test_matrix_covers_every_registered_divergence():
    """The register may not name a cell the sweep never visits (a typo in
    ``_DIVERGENCES`` would otherwise silently disable an exception)."""
    seen = {(f, s, n) for f, s, n, _a, _d in _sweep()}
    for (fix, seg, name) in _DIVERGENCES:
        if seg == '*':
            assert any(f == fix and n == name for f, _s, n in seen), \
                (fix, seg, name)
        else:
            assert (fix, seg, name) in seen, (fix, seg, name)


# ---------------------------------------------------------------------------
# The ordinary cells, named one by one (the sweep proves agreement; these
# state WHAT the agreed answer is).
# ---------------------------------------------------------------------------

def test_cell_local_label_in_the_current_segment_is_segname_plus_offset():
    """local x label x current-segment: all four say "my own segment"."""
    a = assemble(SRC_MAIN)
    ans = cell(a, 'Alpha', 'ALab')
    assert ans == {'value': 0, 'kind': 'label', 'reloc': True,
                   'emits': ('symbolic', 'ALPHA', 0)}, ans
    ans = cell(a, 'Beta', 'BLab')
    assert ans == {'value': 4, 'kind': 'label', 'reloc': True,
                   'emits': ('symbolic', 'BETA', 4)}, ans


def test_cell_label_from_a_sibling_segment_is_by_name():
    """global x label x no-local-shadow: the same four answers, except that
    the emitted reference is BY NAME (the linker resolves it), because the
    definition is not in the segment being emitted."""
    a = assemble(SRC_MAIN)
    ans = cell(a, 'Gamma', 'ALab')
    assert ans == {'value': 0, 'kind': 'label', 'reloc': True,
                   'emits': ('symbolic', 'ALAB', 0)}, ans


def test_cell_local_label_shadows_a_same_named_foreign_proc_equ():
    """shadowed x label: ALPHA's own ``Shared`` label beats BETA's PROC-local
    ``Shared equ $30`` — which is the binding everywhere else in the file
    (asm.symbols is last-definition-wins WITHIN one assembly).  resolve,
    sym_kind, needs_reloc and _expr_for all take the local."""
    a = assemble(SRC_MAIN)
    assert a.symtype['SHARED'] == 'equ', a.symtype    # the global binding...
    ans = cell(a, 'Alpha', 'Shared')                  # ...loses here
    assert ans == {'value': 4, 'kind': 'label', 'reloc': True,
                   'emits': ('symbolic', 'ALPHA', 4)}, ans


def test_cell_proc_local_equ_shadows_a_same_named_label():
    """shadowed x EQU: the mirror image — inside BETA the PROC-local equate
    wins and the reference is an absolute constant, no relocation."""
    a = assemble(SRC_MAIN)
    ans = cell(a, 'Beta', 'Shared')
    assert ans == {'value': 0x30, 'kind': 'equ', 'reloc': False,
                   'emits': ('literal', 0x30)}, ans


def test_cell_unshadowed_name_binds_the_same_from_every_segment():
    """no-local-shadow control: GAMMA defines nothing, so every name there
    binds its file-wide definition — including ``Shared``, whose file-wide
    binding is BETA's PROC-local equate."""
    a = assemble(SRC_MAIN)
    assert cell(a, 'Gamma', 'Shared') == {
        'value': 0x30, 'kind': 'equ', 'reloc': False,
        'emits': ('literal', 0x30)}
    assert cell(a, 'Gamma', 'FileEqu') == {
        'value': 0x40, 'kind': 'equ', 'reloc': False,
        'emits': ('literal', 0x40)}


def test_cell_import_is_relocatable_and_always_by_name():
    """A declared IMPORT: sym_kind's own vocabulary ('import', not 'label')
    is the one legitimate KIND difference among the four — needs_reloc and
    _expr_for both treat it exactly as a relocatable reference, and
    asm.is_reloc() folds 'import' into 'label' for sizing."""
    a = assemble(SRC_MAIN)
    ans = cell(a, 'Gamma', 'ExtSym')
    assert ans == {'value': None, 'kind': 'import', 'reloc': True,
                   'emits': ('symbolic', 'EXTSYM', 0)}, ans
    assert a.is_reloc('ExtSym') is True


def test_cell_entry_is_by_name_forward_and_segname_plus_offset_backward():
    """exported x label, same segment: the ONE cell where _expr_for's answer
    depends on something none of the other three can see — where the
    reference sits relative to the definition.  The kind/value/reloc answers
    are identical for both directions; only the encoding changes."""
    a = assemble(SRC_MAIN)
    fwd = cell(a, 'Alpha', 'AEntry', ref_off=0)      # ref before the def
    bwd = cell(a, 'Alpha', 'AEntry', ref_off=8)      # ref after the def
    assert fwd['emits'] == ('symbolic', 'AENTRY', 0), fwd
    assert bwd['emits'] == ('symbolic', 'ALPHA', 2), bwd
    for k in ('value', 'kind', 'reloc'):
        assert fwd[k] == bwd[k], (k, fwd, bwd)


def test_cell_with_active_template_field_beats_a_same_named_label():
    """WITH x shadowed: a WITH-active RECORD TEMPLATE field is an absolute
    OFFSET and outranks a same-named real label — in all four.  Drop the
    WITH and the label wins again, in all four."""
    a = assemble(SRC_WITH)
    sg = in_seg(a, 'Code')
    a._rwith = [['FRAME']]                            # emit-time WITH frame
    assert answers(a, 'fcount', sg) == {
        'value': 2, 'kind': 'equ', 'reloc': False, 'emits': ('literal', 2)}
    a._rwith = None
    assert answers(a, 'fcount', sg) == {
        'value': 0, 'kind': 'label', 'reloc': True,
        'emits': ('symbolic', 'FCOUNT', 0)}


def test_cell_set_variable_in_the_current_segment_is_an_absolute_constant():
    """A SET that does NOT own its name (a storage label of the same name
    keeps the module-visible binding) is still the binding for references in
    its OWN segment — in all four."""
    a = assemble(SRC_SET)
    assert a.symtype['V'] == 'label' and a.setvar_seg['V'] == 1, a.symtype
    assert cell(a, 'Code', 'v') == {
        'value': 4, 'kind': 'equ', 'reloc': False, 'emits': ('literal', 4)}
    # ...and from any other segment the storage label is the binding.
    assert cell(a, 'Store', 'v') == {
        'value': 0, 'kind': 'label', 'reloc': True,
        'emits': ('symbolic', 'STORE', 0)}


# ---------------------------------------------------------------------------
# The documented differences (D1-D4): cells where the four legitimately give
# different answers because they answer different questions.  The difference
# IS the contract, so it is asserted, not skipped.
# ---------------------------------------------------------------------------

def test_difference_d1_undefined_symbol_is_bridged_by_undef_external():
    """D1.  ``needs_reloc``'s docstring claims an undefined symbol returns
    True ("an implicit external — MPW lets you reference externals without
    IMPORT").  The CODE returns False: with no symtype and no seed_type the
    identifier falls off the end of the loop.  ``_expr_for`` meanwhile emits
    it by name.  Every caller closes the gap itself, with an explicit
    ``or omf._undef_external(asm, ...)`` beside the needs_reloc call
    (omf.py's mnemonic, block-move, DC and branch paths).

    So the contract is: the implicit-external rule lives in
    ``omf._undef_external``, NOT in needs_reloc — a fifth restatement in all
    but name, and the reason the four still produce correct bytes.
    """
    a = assemble(SRC_MAIN)
    ans = cell(a, 'Gamma', 'NeverSeen')
    assert ans == {'value': None, 'kind': None, 'reloc': False,
                   'emits': ('symbolic', 'NEVERSEEN', 0)}, ans
    assert omf._undef_external(a, 'NeverSeen') is True
    # the bridge, spelled as the call sites spell it
    assert (a.needs_reloc('NeverSeen') or omf._undef_external(a, 'NeverSeen'))


def test_difference_d2_org_segment_label_is_kind_label_but_never_relocates():
    """D2.  In an ORG'd segment a label's value is already absolute, so
    ``needs_reloc`` returns False and the emitter bakes the literal.
    ``sym_kind`` still answers 'label' (it types the DEFINITION, and the kind
    drives operand SIZING — an absolute address must not size direct-page),
    and ``_expr_for``, if it is called anyway, still encodes SEGNAME+offset.

    The routing rule for a future change: needs_reloc is the gate, _expr_for
    is the encoder.  Never infer relocatability from what _expr_for emits.
    """
    a = assemble(SRC_ORG)
    ans = cell(a, 'Abs1', 'O1b')
    assert ans == {'value': 0xFF0002, 'kind': 'label', 'reloc': False,
                   'emits': ('symbolic', 'ABS1', 2)}, ans
    assert a.is_reloc('O1b') is True, 'kind still drives absolute SIZING'


def test_difference_d3_temporg_label_is_kind_label_but_emits_a_literal():
    """D3.  A TEMPORG segment's labels are absolute literals (the code runs
    at ``temporg`` after being copied there), so needs_reloc AND _expr_for
    both refuse to relocate — they agree — while sym_kind still says 'label'.
    Same principle as D2, opposite emission: the difference is between
    "what kind of thing is this" and "does it need a relocation record"."""
    a = assemble(SRC_ORG)
    ans = cell(a, 'Rel', 'T1')
    assert ans == {'value': 0x2000, 'kind': 'label', 'reloc': False,
                   'emits': ('literal', 0x2000)}, ans


def test_difference_d4_equ_alias_is_kind_equ_but_relocates():
    """D4.  ``devName equ ParBlock+2`` is kind 'equ' — an absolute value at
    assembly time — yet it is a second NAME for a relocatable address, so it
    MUST relocate.  needs_reloc and _expr_for both special-case
    ``asm.equ_alias`` before anything else; ``asm.is_reloc`` re-checks it so
    that SIZING agrees too.  This is the cell that proves kind alone is not
    a relocation decision.
    """
    a = assemble(SRC_ALIAS)
    assert a.equ_alias['DEVNAME'] == ('PARBLOCK', 2), a.equ_alias
    ans = cell(a, 'Code', 'devName')
    assert ans == {'value': 2, 'kind': 'equ', 'reloc': True,
                   'emits': ('symbolic', 'PARBLOCK', 2)}, ans
    assert a.is_reloc('devName') is True
    # ...and from the DEFINING segment the same alias emits SEGNAME+offset.
    assert cell(a, 'Data', 'devName')['emits'] == ('symbolic', 'DATA', 2)


# ---------------------------------------------------------------------------
# LIVE DISAGREEMENTS — pinned, deliberately NOT fixed.
#
# Both are the same structural fault: needs_reloc restates the precedence
# ladder without two branches resolve() and sym_kind() both carry.  Neither
# moves a golden byte TODAY, because of which phase each function is called
# from — which is exactly the review's point about agreement being untested.
# If a later packet fixes one, it is a BEHAVIOUR change: gate it on its own
# commit with predicted movement, and update
# docs/CONTRACT_SYMBOL_PRECEDENCE.md part II.
# ---------------------------------------------------------------------------

def test_disagreement_case_exact_equ_is_invisible_to_needs_reloc():
    """X1.  An exact-spelling file-scope EQU variant (the opt-in
    ``case_equ_variants`` mechanism, Finder's DP handle/Ptr collision) whose
    FOLDED name is also a relocatable label:

        resolve('Handle')      -> $10      the case-exact EQU
        sym_kind('Handle')     -> 'equ'    the case-exact EQU
        _expr_for('Handle')    -> LIT $10  the case-exact EQU
        needs_reloc('Handle')  -> True     the FOLDED LABEL   <-- dissents

    ``needs_reloc`` folds every identifier through ``_symkey`` and has no
    ``case_symbols`` branch, so it sees only the label.  The emitter asks
    needs_reloc first, so this shape emits an EXPR record whose contents are
    a constant — the resolved BYTES are right, the object record stream is
    not.  Unobservable in the corpus because the one build that opts into
    case_equ_variants has no relocatable label colliding with the variant.
    """
    a = assemble(SRC_CASE, **CASE_KW)
    assert a.case_symbols == {'Handle': 0x10}, a.case_symbols
    assert a.symtype['HANDLE'] == 'label', a.symtype
    ans = cell(a, 'Code', 'Handle')
    assert ans['value'] == 0x10 and ans['kind'] == 'equ', ans
    assert ans['emits'] == ('literal', 0x10), ans
    assert ans['reloc'] is True, \
        'X1 FIXED? needs_reloc now honours the exact-spelling EQU — that is a ' \
        'behaviour change; re-gate it and update the contract'
    # the folded spelling is unambiguous and all four agree on it
    assert cell(a, 'Code', 'HANDLE') == {
        'value': 0, 'kind': 'label', 'reloc': True,
        'emits': ('symbolic', 'HANDLE', 0)}


def test_disagreement_needs_reloc_has_no_current_segment_fallback():
    """X2.  ``resolve`` and ``sym_kind`` both do:

        seg = self._rseg
        if seg is None and self.emit_enabled and self.segs:
            seg = len(self.segs) - 1

    ``needs_reloc`` does only ``seg = self._rseg``.  So with no emit cursor —
    which sym_kind's own comment calls the normal state of the main assembly
    pass ("During the main assembly pass _rseg is None") — resolve and
    sym_kind consult the LAST segment's local tables and needs_reloc consults
    none:

        resolve('v')      -> 4       the segment-local SET
        sym_kind('v')     -> 'equ'   the segment-local SET
        needs_reloc('v')  -> True    the masking storage label  <-- dissents

    Today nothing calls needs_reloc with ``_rseg`` unset (it is reached only
    from omf.py's emit paths), while ``asm.is_reloc`` — which DOES run in the
    main pass — reads sym_kind.  So the two halves of one decision already
    use different scopes; only call-site phase keeps them from meeting.
    """
    a = assemble(SRC_SET)
    a._rseg = None
    assert a.emit_enabled and len(a.segs) == 2, (a.emit_enabled, len(a.segs))
    assert a.resolve('v') == 4, a.resolve('v')
    assert a.sym_kind('v') == 'equ', a.sym_kind('v')
    assert a.needs_reloc('v') is True, \
        'X2 FIXED? needs_reloc grew the current-segment fallback — that is a ' \
        'behaviour change; re-gate it and update the contract'
    # ...and with the cursor set, the same three agree again.
    in_seg(a, 'Code')
    assert (a.resolve('v'), a.sym_kind('v'), a.needs_reloc('v')) == \
        (4, 'equ', False)


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
