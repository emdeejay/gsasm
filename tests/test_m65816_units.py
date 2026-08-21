"""Direct unit tests for gsasm/m65816.py — the 65816 instruction encoder.

WHY THIS FILE EXISTS (0.6.0 slate item 1, ARCHITECTURE_REVIEW_2026-08-02
finding 5): `m65816.py` is one of the two genuinely clean modules in the
library and it had ZERO direct unit coverage.  Every encoding rule in it was
proven only through whole-pipeline golden-byte diffing, so a regression in
the sizing rules surfaced as "byte 0xe5d differs" in a 59KB kernel image and
had to be diagnosed backward through assemble -> link -> expressload every
time.  These tests convert that archaeology into failures with names.

WHAT THIS FILE IS NOT: it is not a specification, and nothing here is a
proposal.  `docs/REFACTORING.md` §5 lists `OPTABLE` + `encode` +
`_crossbank`/`_width` as Do-Not-Touch ("the sizing rules; 100% opcode
corpus").  Every assertion below was written by OBSERVING what the encoder
does today and pinning it.  Where today's behavior looks questionable the
test still asserts the observed behavior, and says so in its docstring under
the tag SUSPICIOUS — those are notes for a future investigation with golden
.lst evidence in hand, never licence to "fix" the encoder to match a
prettier test.

CORPUS-FREE: all inputs are constructed synthetically (a dict-backed
`evaluate`), so this runs in CI on a machine with no `ref/` tree.

Run either as:
    python3 -m pytest tests/test_m65816_units.py
    python3 tests/test_m65816_units.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from gsasm import m65816                            # noqa: E402
from gsasm.m65816 import (ALIAS, BLOCKMOVE, BRANCH8, BRANCH16, IMM_1, IMM_A,
                          IMM_X, MNEMONICS, OPTABLE, EncodeError, Fixup,
                          encode, instr_length, _emit, _ends_depth0,
                          _immwidth, _pick_mode, _strip_index, _unpfx,
                          _width)  # noqa: E402

# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

#: symbol values used by the synthetic `evaluate` below.
CONSTS = {
    'DPVAL': 0x0010,        # fits direct page
    'ABSVAL': 0x1234,       # fits a 16-bit absolute
    'LONGVAL': 0x030000,    # bank 3
    'BANK2END': 0x02FFFF,   # top of bank 2
}


def ev(expr):
    """Synthetic `evaluate`: named constants, $hex and decimal; else None.

    None is exactly the "not resolved yet" signal the encoder's pass-1 sizing
    path sees for a forward reference.
    """
    e = expr.strip()
    if e in CONSTS:
        return CONSTS[e]
    try:
        if e.startswith('$'):
            return int(e[1:], 16)
        return int(e, 0)
    except ValueError:
        return None


def reloc_for(*names):
    """Synthetic `reloc(expr)->bool` predicate over a fixed name set."""
    s = set(names)
    return lambda e: e.strip() in s


def enc(mnem, operand='', longa=False, longi=False, pc=0, reloc=None):
    """encode(...) -> (hex_string_or_None, fixup)."""
    b, f = encode(mnem, operand, longa, longi, ev, pc, reloc)
    return (None if b is None else b.hex()), f


def enc_b(mnem, operand='', longa=False, longi=False, pc=0, reloc=None):
    """encode(...) -> hex string only (asserts no fixup was produced)."""
    h, f = enc(mnem, operand, longa, longi, pc, reloc)
    assert f is None, f'unexpected fixup for {mnem} {operand!r}: {f.expr}'
    return h


def raises(exc, mnem, operand='', longa=False, longi=False, pc=0, reloc=None):
    """Assert encode(...) raises `exc`; return the message for comparison."""
    try:
        encode(mnem, operand, longa, longi, ev, pc, reloc)
    except exc as e:
        return str(e)
    except Exception as e:                       # noqa: BLE001
        raise AssertionError(
            f'{mnem} {operand!r}: expected {exc.__name__}, got {e!r}')
    raise AssertionError(f'{mnem} {operand!r}: expected {exc.__name__}')


# --------------------------------------------------------------------------
# 1. OPTABLE integrity, as a table
# --------------------------------------------------------------------------

#: The canonical 65816 opcode matrix, written out independently of OPTABLE
#: (row = high nibble, column = low nibble) in this module's mode-key
#: vocabulary.  Two entries are ambiguous by design and carry both spellings:
#: $5C and $DC are reachable as JMP long / JMP [abs] and as JML long /
#: JML [abs].
OPCODE_MATRIX = [
    # $x0        $x1        $x2        $x3        $x4        $x5        $x6        $x7        $x8       $x9        $xA       $xB       $xC        $xD        $xE        $xF
    'BRK:imm  ORA:indx  COP:imm   ORA:sr    TSB:dp    ORA:dp    ASL:dp    ORA:indl  PHP:imp  ORA:imm   ASL:acc  PHD:imp  TSB:abs   ORA:abs   ASL:abs   ORA:abl',
    'BPL:rel  ORA:indy  ORA:ind   ORA:sriy  TRB:dp    ORA:dpx   ASL:dpx   ORA:indly CLC:imp  ORA:absy  INC:acc  TCS:imp  TRB:abs   ORA:absx  ASL:absx  ORA:ablx',
    'JSR:abs  AND:indx  JSL:abl   AND:sr    BIT:dp    AND:dp    ROL:dp    AND:indl  PLP:imp  AND:imm   ROL:acc  PLD:imp  BIT:abs   AND:abs   ROL:abs   AND:abl',
    'BMI:rel  AND:indy  AND:ind   AND:sriy  BIT:dpx   AND:dpx   ROL:dpx   AND:indly SEC:imp  AND:absy  DEC:acc  TSC:imp  BIT:absx  AND:absx  ROL:absx  AND:ablx',
    'RTI:imp  EOR:indx  WDM:imm   EOR:sr    MVP:bmv   EOR:dp    LSR:dp    EOR:indl  PHA:imp  EOR:imm   LSR:acc  PHK:imp  JMP:abs   EOR:abs   LSR:abs   EOR:abl',
    'BVC:rel  EOR:indy  EOR:ind   EOR:sriy  MVN:bmv   EOR:dpx   LSR:dpx   EOR:indly CLI:imp  EOR:absy  PHY:imp  TCD:imp  JMP|JML:abl EOR:absx LSR:absx  EOR:ablx',
    'RTS:imp  ADC:indx  PER:rell  ADC:sr    STZ:dp    ADC:dp    ROR:dp    ADC:indl  PLA:imp  ADC:imm   ROR:acc  RTL:imp  JMP:aind  ADC:abs   ROR:abs   ADC:abl',
    'BVS:rel  ADC:indy  ADC:ind   ADC:sriy  STZ:dpx   ADC:dpx   ROR:dpx   ADC:indly SEI:imp  ADC:absy  PLY:imp  TDC:imp  JMP:aindx ADC:absx  ROR:absx  ADC:ablx',
    'BRA:rel  STA:indx  BRL:rell  STA:sr    STY:dp    STA:dp    STX:dp    STA:indl  DEY:imp  BIT:imm   TXA:imp  PHB:imp  STY:abs   STA:abs   STX:abs   STA:abl',
    'BCC:rel  STA:indy  STA:ind   STA:sriy  STY:dpx   STA:dpx   STX:dpy   STA:indly TYA:imp  STA:absy  TXS:imp  TXY:imp  STZ:abs   STA:absx  STZ:absx  STA:ablx',
    'LDY:imm  LDA:indx  LDX:imm   LDA:sr    LDY:dp    LDA:dp    LDX:dp    LDA:indl  TAY:imp  LDA:imm   TAX:imp  PLB:imp  LDY:abs   LDA:abs   LDX:abs   LDA:abl',
    'BCS:rel  LDA:indy  LDA:ind   LDA:sriy  LDY:dpx   LDA:dpx   LDX:dpy   LDA:indly CLV:imp  LDA:absy  TSX:imp  TYX:imp  LDY:absx  LDA:absx  LDX:absy  LDA:ablx',
    'CPY:imm  CMP:indx  REP:imm   CMP:sr    CPY:dp    CMP:dp    DEC:dp    CMP:indl  INY:imp  CMP:imm   DEX:imp  WAI:imp  CPY:abs   CMP:abs   DEC:abs   CMP:abl',
    'BNE:rel  CMP:indy  CMP:ind   CMP:sriy  PEI:dp    CMP:dpx   DEC:dpx   CMP:indly CLD:imp  CMP:absy  PHX:imp  STP:imp  JMP|JML:aindl CMP:absx DEC:absx CMP:ablx',
    'CPX:imm  SBC:indx  SEP:imm   SBC:sr    CPX:dp    SBC:dp    INC:dp    SBC:indl  INX:imp  SBC:imm   NOP:imp  XBA:imp  CPX:abs   SBC:abs   INC:abs   SBC:abl',
    'BEQ:rel  SBC:indy  SBC:ind   SBC:sriy  PEA:abs   SBC:dpx   INC:dpx   SBC:indly SED:imp  SBC:absy  PLX:imp  XCE:imp  JSR:aindx SBC:absx  INC:absx  SBC:ablx',
]

#: every mode key the module's docstring declares
MODES = {'imp', 'acc', 'imm',
         'dp', 'dpx', 'dpy', 'abs', 'absx', 'absy', 'abl', 'ablx',
         'ind', 'indx', 'indy', 'indl', 'indly',
         'aind', 'aindx', 'aindl',
         'rel', 'rell', 'sr', 'sriy', 'bmv'}


def _canonical_map():
    """OPCODE_MATRIX -> {opcode: {(mnem, mode), ...}}."""
    out = {}
    for hi, row in enumerate(OPCODE_MATRIX):
        cells = row.split()
        assert len(cells) == 16, f'row ${hi:X}0 has {len(cells)} cells'
        for lo, cell in enumerate(cells):
            mnems, mode = cell.split(':')
            out[hi * 16 + lo] = {(m, mode) for m in mnems.split('|')}
    return out


def _optable_map():
    """OPTABLE -> {opcode: {(mnem, mode), ...}}."""
    out = {}
    for mnem, tab in OPTABLE.items():
        for mode, op in tab.items():
            out.setdefault(op, set()).add((mnem, mode))
    return out


def test_optable_entries_are_well_formed():
    for mnem, tab in OPTABLE.items():
        assert isinstance(mnem, str) and mnem.isupper() and mnem, mnem
        assert isinstance(tab, dict) and tab, f'{mnem} has an empty table'
        for mode, op in tab.items():
            assert mode in MODES, f'{mnem}: unknown mode {mode!r}'
            assert isinstance(op, int) and 0 <= op <= 0xFF, f'{mnem}.{mode}'


def test_optable_covers_all_256_opcode_bytes_exactly_once():
    """The "100% opcode corpus" claim, made checkable.

    Every one of the 256 byte values is produced by exactly one (mnemonic,
    mode) pair, with the two deliberate JMP/JML aliases as the sole
    exceptions.  A typo'd opcode byte in OPTABLE therefore shows up here as
    a duplicate + a hole, not as a wrong byte somewhere in the ROM.
    """
    m = _optable_map()
    assert sorted(m) == list(range(256)), (
        'opcode bytes not fully covered; missing: '
        + ' '.join('%02x' % b for b in sorted(set(range(256)) - set(m))))
    multi = {op: v for op, v in m.items() if len(v) > 1}
    assert set(multi) == {0x5C, 0xDC}, (
        f'unexpected duplicate opcode bytes: {sorted(multi)}')
    assert multi[0x5C] == {('JMP', 'abl'), ('JML', 'abl')}
    assert multi[0xDC] == {('JMP', 'aindl'), ('JML', 'aindl')}


def test_optable_matches_the_canonical_65816_opcode_matrix():
    """Full cross-check against an independently written opcode matrix."""
    canon, actual = _canonical_map(), _optable_map()
    diffs = [f'${op:02X}: table={sorted(actual.get(op, set()))} '
             f'canonical={sorted(canon[op])}'
             for op in range(256) if actual.get(op, set()) != canon[op]]
    assert not diffs, 'opcode map disagreements:\n  ' + '\n  '.join(diffs)


def test_isa_required_modes_are_present_for_the_alu_family():
    """The eight ALU/load ops must carry the full 15-mode 65816 set."""
    full = {'imm', 'dp', 'dpx', 'abs', 'absx', 'absy', 'abl', 'ablx',
            'ind', 'indx', 'indy', 'indl', 'indly', 'sr', 'sriy'}
    for mnem in ('ADC', 'AND', 'CMP', 'EOR', 'LDA', 'ORA', 'SBC'):
        assert set(OPTABLE[mnem]) == full, f'{mnem}: {set(OPTABLE[mnem]) ^ full}'
    # STA is the same set minus immediate (there is no "store immediate").
    assert set(OPTABLE['STA']) == full - {'imm'}


def test_isa_required_modes_for_the_shift_rmw_family():
    for mnem in ('ASL', 'LSR', 'ROL', 'ROR'):
        assert set(OPTABLE[mnem]) == {'acc', 'dp', 'dpx', 'abs', 'absx'}
    for mnem in ('INC', 'DEC'):
        assert set(OPTABLE[mnem]) == {'acc', 'dp', 'dpx', 'abs', 'absx'}
    for mnem in ('TRB', 'TSB'):
        assert set(OPTABLE[mnem]) == {'dp', 'abs'}


def test_isa_index_register_asymmetry_is_preserved():
    """LDX/STX index by Y, LDY/STY by X — never the other way round."""
    assert set(OPTABLE['LDX']) == {'imm', 'dp', 'dpy', 'abs', 'absy'}
    assert set(OPTABLE['LDY']) == {'imm', 'dp', 'dpx', 'abs', 'absx'}
    assert set(OPTABLE['STX']) == {'dp', 'dpy', 'abs'}
    assert set(OPTABLE['STY']) == {'dp', 'dpx', 'abs'}
    # STZ has no Y form at all.
    assert set(OPTABLE['STZ']) == {'dp', 'dpx', 'abs', 'absx'}


def test_every_immediate_class_member_has_an_imm_entry():
    for mnem in IMM_A | IMM_X | IMM_1:
        assert 'imm' in OPTABLE[mnem], f'{mnem} has no immediate form'
    assert IMM_A.isdisjoint(IMM_X) and IMM_A.isdisjoint(IMM_1)
    assert IMM_X.isdisjoint(IMM_1)


def test_branch_and_blockmove_classes_agree_with_the_table():
    for mnem in BRANCH8 & set(OPTABLE):
        assert set(OPTABLE[mnem]) == {'rel'}, mnem
    for mnem in BRANCH16:
        assert set(OPTABLE[mnem]) == {'rell'}, mnem
    for mnem in BLOCKMOVE:
        assert set(OPTABLE[mnem]) == {'bmv'}, mnem


def test_every_branch8_name_is_encodable():
    """RESOLVED (was SUSPICIOUS): BRANCH8 no longer lists BLE/BGT.

    BRANCH8's only non-OPTABLE members are BLT and BGE, and both are wired
    through ALIAS to BCC/BCS — so every name in the set encodes.  The old
    two strays, BLE and BGT, were dead entries: the 65816 has no such
    opcodes, and every corpus source that wants them defines them as a
    TWO-INSTRUCTION MACRO (`ble` -> `blt`+`beq`; `bgt` -> `beq @skip`+`bge`;
    see `work/romsrc/GS_ROM/QD/rects.asm:53-66` and six sibling copies).
    They are therefore ordinary user macro names, not mnemonics, and
    `encode` correctly reports them as unknown.
    """
    assert sorted(BRANCH8 - set(OPTABLE)) == ['BGE', 'BLT']
    assert BRANCH8 - MNEMONICS == set()
    assert {'BLE', 'BGT'} & MNEMONICS == set()
    assert encode('BLE', 'Target', False, False, ev, 0) == (None, None)
    assert encode('BGT', 'Target', False, False, ev, 0) == (None, None)


def test_aliases_resolve_into_the_table_and_do_not_shadow_it():
    for src, dst in ALIAS.items():
        assert dst in OPTABLE, f'{src} -> {dst} is not a real mnemonic'
        assert src not in OPTABLE, f'{src} is both an alias and a table entry'
    assert MNEMONICS == set(OPTABLE) | set(ALIAS)
    assert len(MNEMONICS) == len(OPTABLE) + len(ALIAS)


def test_implied_only_mnemonics_have_exactly_one_byte():
    for mnem, tab in OPTABLE.items():
        if set(tab) == {'imp'}:
            assert len(encode(mnem, '', False, False, ev, 0)[0]) == 1, mnem


# --------------------------------------------------------------------------
# 2. encode(): implied, accumulator, and the comment-swallowing rules
# --------------------------------------------------------------------------

def test_implied_encodes_and_ignores_trailing_text():
    """An implied-only mnemonic's "operand" is an unmarked comment."""
    assert enc_b('NOP') == 'ea'
    assert enc_b('NOP', 'this is a comment, not an operand') == 'ea'
    assert enc_b('XCE') == 'fb'
    assert enc_b('PHB') == '8b'
    assert enc_b('RTL') == '6b'


def test_mnemonics_are_case_insensitive():
    assert enc_b('lda', '#$12') == 'a912'
    assert enc_b('Jsr', '$1234') == '203412'
    assert enc_b('nop') == 'ea'


def test_accumulator_mode_from_empty_operand_or_A():
    for op in ('', 'A', 'a', '  a  '):
        assert enc_b('ASL', op) == '0a', op
        assert enc_b('INC', op) == '1a', op
        assert enc_b('DEC', op) == '3a', op
        assert enc_b('ROR', op) == '6a', op


def test_ina_dea_are_accumulator_only_spellings():
    """Fixture 067: INA/DEA never take a memory operand, so trailing text is
    a comment (epson.asm's `ina<tab>skip 50% reduction`)."""
    assert enc_b('INA') == '1a'
    assert enc_b('DEA') == '3a'
    assert enc_b('INA', 'skip 50% reduction') == '1a'
    assert enc_b('DEA', '$1234') == '3a'


def test_cpa_is_an_alias_for_cmp():
    assert enc_b('CPA', '#$12') == 'c912'
    assert enc_b('CPA', '$10') == 'c510'


# --------------------------------------------------------------------------
# 3. encode(): immediate mode and the LONGA/LONGI width rules
# --------------------------------------------------------------------------

def test_immwidth_accumulator_class_follows_longa_only():
    for mnem in sorted(IMM_A):
        assert _immwidth(mnem, False, False) == 1, mnem
        assert _immwidth(mnem, False, True) == 1, mnem     # LONGI must not matter
        assert _immwidth(mnem, True, False) == 2, mnem
        assert _immwidth(mnem, True, True) == 2, mnem


def test_immwidth_index_class_follows_longi_only():
    for mnem in sorted(IMM_X):
        assert _immwidth(mnem, False, False) == 1, mnem
        assert _immwidth(mnem, True, False) == 1, mnem     # LONGA must not matter
        assert _immwidth(mnem, False, True) == 2, mnem
        assert _immwidth(mnem, True, True) == 2, mnem


def test_immwidth_single_byte_class_ignores_both_width_flags():
    for mnem in sorted(IMM_1):
        for la in (False, True):
            for li in (False, True):
                assert _immwidth(mnem, la, li) == 1, mnem


def test_immwidth_default_for_an_unclassified_mnemonic_follows_longa():
    """The `return 2 if longa else 1` fallback: anything not in IMM_X/IMM_1
    is sized by LONGA, even a mnemonic with no immediate form at all."""
    assert _immwidth('STA', True, False) == 2
    assert _immwidth('STA', False, True) == 1


def test_immediate_under_longa_and_longi():
    assert enc_b('LDA', '#$12') == 'a912'
    assert enc_b('LDA', '#$1234', longa=True) == 'a93412'      # little-endian
    assert enc_b('LDA', '#$1234', longa=False) == 'a934'       # truncated to 8
    assert enc_b('LDX', '#$12') == 'a212'
    assert enc_b('LDX', '#$1234', longi=True) == 'a23412'
    assert enc_b('LDX', '#$1234', longa=True) == 'a234'        # LONGA is not LONGI
    assert enc_b('CPY', '#$1234', longi=True) == 'c03412'
    assert enc_b('BIT', '#$1234', longa=True) == '893412'


def test_single_byte_immediate_mnemonics_accept_a_bare_operand():
    """REP/SEP/BRK/COP/WDM take one byte, with or without the '#'."""
    assert enc_b('REP', '#$30') == 'c230'
    assert enc_b('REP', '$30') == 'c230'
    assert enc_b('SEP', '#$30', longa=True, longi=True) == 'e230'
    assert enc_b('COP', '#$7f') == '027f'
    assert enc_b('WDM', '$34') == '4234'
    assert enc_b('BRK', '$12') == '0012'


def test_single_byte_immediate_with_no_operand_defaults_to_zero():
    assert enc_b('BRK', '') == '0000'
    assert enc_b('REP', '#') == 'c200'
    assert enc_b('COP', '') == '0200'


def test_immediate_part_selectors_keep_the_full_operand_width():
    """`#<`/`#>`/`#^` select the low/high/bank part but still occupy the
    whole immediate width (2 bytes under LONGA ON)."""
    assert enc_b('LDA', '#<ABSVAL', longa=True) == 'a93412'    # shift 0
    assert enc_b('LDA', '#>ABSVAL', longa=True) == 'a91200'    # shift 8
    assert enc_b('LDA', '#^LONGVAL', longa=True) == 'a90300'   # shift 16
    assert enc_b('LDA', '#>ABSVAL', longa=False) == 'a912'     # 1-byte width


def test_unresolved_immediate_becomes_a_zero_filled_fixup():
    h, f = enc('LDA', '#Forward', longa=True)
    assert h == 'a90000'
    assert isinstance(f, Fixup)
    assert (f.expr, f.nbytes, f.kind, f.pc, f.shift) == ('Forward', 2, 'val', 0, 0)


def test_unresolved_part_selector_records_the_shift_on_the_fixup():
    for marker, shift in (('<', 0), ('>', 8), ('^', 16)):
        h, f = enc('LDA', f'#{marker}Forward', longa=True)
        assert h == 'a90000'
        assert (f.kind, f.nbytes, f.shift) == ('byte', 2, shift), marker


def test_double_immediate_marker_only_strips_the_outer_hash():
    """DIALECT QUIRK, pinned per the long comment in encode().

    `#^#0` leaves an inner '#' in the fixup expression, which expr.tokenize
    later rejects, so asm.py's fallback bakes $FFFF.  Never exercised by the
    corpus; asserted so the behavior cannot drift unnoticed."""
    h, f = enc('LDA', '#^#0', longa=True)
    assert h == 'a90000'
    assert (f.expr, f.kind, f.shift) == ('#0', 'byte', 16)
    h, f = enc('PEA', '#^#0')
    assert (f.expr, f.kind, f.shift) == ('#0', 'byte', 16)


def test_bare_hash_with_no_expression_is_an_encode_error():
    """RESOLVED (was SUSPICIOUS): a bare '#' reports, it does not IndexError.

    `lda #` gives expr == '', and `'' in '<>^'` is True in Python (substring
    semantics), so the part-selector branch used to be taken and `expr[0]`
    raised a bare IndexError.  The empty case is now rejected up front with
    an EncodeError naming the problem.  A bare '#' does not occur in the
    corpus, so this cannot move a golden byte.
    """
    assert raises(EncodeError, 'LDA', '#', longa=True) == 'LDA: immediate operand is empty'
    assert raises(EncodeError, 'LDA', '#') == 'LDA: immediate operand is empty'
    # a part selector with nothing after it is the same class of typo
    for marker in '<>^':
        assert raises(EncodeError, 'LDA', f'#{marker}') == (
            f"LDA: part selector '{marker}' has no expression")
    assert raises(EncodeError, 'PEA', '#^') == (
        "PEA: part selector '^' has no expression")
    assert raises(EncodeError, 'PEA', '') == 'PEA requires an operand'


def test_a_mnemonic_that_needs_an_operand_says_so_when_it_has_none():
    """RESOLVED (was an IndexError of the same family as the bare '#').

    An empty operand fell through to the size-prefix test, where
    `'' in '<>|!'` is True and `core[0]` raised IndexError.  Mnemonics whose
    signature byte legitimately defaults to zero (BRK/COP/REP/SEP/WDM) are
    unaffected, and so are the accumulator/implied forms.
    """
    assert raises(EncodeError, 'LDA', '') == 'LDA requires an operand'
    assert raises(EncodeError, 'JMP', '   ') == 'JMP requires an operand'
    assert raises(EncodeError, 'STA', '') == 'STA requires an operand'
    # unchanged: implied, accumulator, and the signature-byte immediates
    assert enc_b('NOP', '') == 'ea'
    assert enc_b('INC', '') == '1a'
    assert enc_b('ASL', '') == '0a'
    assert enc_b('BRK', '') == '0000'
    assert enc_b('COP', '') == '0200'


# --------------------------------------------------------------------------
# 4. _width: the dp / abs / long selection rule
# --------------------------------------------------------------------------

def test_width_forced_prefixes_win_over_the_value():
    assert _width('$1234', ev, '<') == 1        # force direct page
    assert _width('$10', ev, '|') == 2          # force absolute
    assert _width('$10', ev, '!') == 2          # '!' is a synonym of '|'
    assert _width('$10', ev, '>') == 3          # force long


def test_width_boundaries_of_the_dp_abs_long_ladder():
    assert _width('$00', ev, None) == 1
    assert _width('$FF', ev, None) == 1
    assert _width('$100', ev, None) == 2
    assert _width('$FFFF', ev, None) == 2
    assert _width('$10000', ev, None) == 3


def test_width_long_only_when_the_bank_differs_from_the_pc():
    """A 24-bit value in the PC's own bank is a 16-bit absolute access."""
    assert _width('$030000', ev, None, None, pc=0x000000) == 3
    assert _width('$030000', ev, None, None, pc=0x030000) == 2
    assert _width('$030000', ev, None, None, pc=0x03FFFF) == 2
    assert _width('$FFFFFF', ev, None, None, pc=0xFF0000) == 2
    assert _width('BANK2END', ev, None, None, pc=0x020000) == 2


def test_width_of_a_relocatable_reference_is_always_absolute():
    """A link-assigned address is never direct page, whatever it evaluates
    to right now."""
    r = reloc_for('DPVAL')
    assert _width('DPVAL', ev, None, None) == 1          # without the predicate
    assert _width('DPVAL', ev, None, r) == 2             # with it
    # ... but an explicit prefix still wins: the reloc test comes after them.
    assert _width('DPVAL', ev, '<', r) == 1
    assert _width('DPVAL', ev, '>', r) == 3


def test_width_of_an_unresolved_expression_is_absolute():
    """Pass-1 sizing of a forward reference assumes 2 bytes."""
    assert _width('Forward', ev, None) == 2


def test_width_masks_the_value_to_24_bits():
    """SUSPICIOUS (pinned, not fixed).

    `v &= 0xFFFFFF` happens BEFORE the ladder, so a value with bits above
    bit 23 wraps rather than erroring: $1000000 sizes as direct page.
    """
    assert _width('$1000000', ev, None) == 1
    assert _width('$1000010', ev, None) == 1


# --------------------------------------------------------------------------
# 5. encode(): dp vs abs vs long selection, indexing, and forced prefixes
# --------------------------------------------------------------------------

def test_dp_abs_long_selection_for_a_plain_operand():
    assert enc_b('LDA', '$10') == 'a510'                       # dp
    assert enc_b('LDA', '$1234') == 'ad3412'                   # abs
    assert enc_b('LDA', '$030000') == 'af000003'               # abl
    assert enc_b('LDA', '$030000', pc=0x030000) == 'ad0000'    # same bank -> abs


def test_forced_prefixes_select_the_mode_and_truncate_the_operand():
    assert enc_b('LDA', '<$1234') == 'a534'        # dp, low byte only
    assert enc_b('LDA', '|$10') == 'ad1000'        # abs, zero-extended
    assert enc_b('LDA', '!$10') == 'ad1000'
    assert enc_b('LDA', '>$10') == 'af100000'      # long, zero-extended


def test_x_indexed_selection_across_all_three_widths():
    assert enc_b('LDA', '$10,x') == 'b510'                     # dpx
    assert enc_b('LDA', '$1234,x') == 'bd3412'                 # absx
    assert enc_b('LDA', '$030000,x') == 'bf000003'             # ablx
    assert enc_b('LDA', '$10,X') == 'b510'                     # case-insensitive


def test_y_indexed_selection_promotes_dp_to_abs_when_no_dpy_form_exists():
    """LDA has no dp,y; the dp value is promoted to a 16-bit absolute,y."""
    assert enc_b('LDA', '$10,y') == 'b91000'                   # absy, not dpy
    assert enc_b('LDA', '$1234,y') == 'b93412'
    # LDX DOES have dp,y, so the same operand stays direct page.
    assert enc_b('LDX', '$10,y') == 'b610'
    assert enc_b('LDY', '$10,x') == 'b410'


def test_y_indexed_long_operand_folds_back_to_absolute_y():
    """DOCUMENTED (was SUSPICIOUS — the suspicion was WRONG).

    The 65816 has no `abs long,y`, so `_pick_mode` maps ('y', 3) to 'absy'
    and `_emit` masks the 24-bit value to 16 bits.  That looks like a silent
    truncation and is not: the dropped byte is the BANK, supplied at run
    time by the Data Bank Register, which is how IIgs firmware reaches bank
    $E1.  Real MPW AsmIIgs does exactly this — from its own captured
    listing, work/romsrc/GS_ROM/Serial/Serial.aii.lst:

        line  336:            00E1 1DD8      QBASE  equ $E11DD8
        line 2624:  F06FF 06FF B9 1DD8      LDA QBase,y

    ($B9 is LDA abs,y; the $E1 is gone) and the listing ends "Assembly
    complete - no errors found."  23 sites in serialdrvr.aii alone, 414
    across the whole gate corpus.  DO NOT make this an error.
    """
    assert enc_b('LDA', '$030000,y') == 'b90000'
    assert enc_b('LDA', '$031234,y') == 'b93412'
    assert _pick_mode(OPTABLE['LDA'], 3, 'y') == 'absy'
    # the Serial.aii case itself, byte for byte
    assert enc_b('LDA', '$E11DD8,y') == 'b9d81d'
    assert enc_b('STA', '$E11DE0,y') == '99e01d'


def test_stx_absolute_y_is_an_encode_error_not_a_stored_low_byte():
    """RESOLVED (was SUSPICIOUS): `stx $1234,y` no longer stores `96 34`.

    STX has only dp,y, so the widest-available fallback ladder stepped DOWN
    to 'dpy' and `_emit` masked $1234 to its low byte — a store to a
    completely different address.  Unlike the long->16-bit fold-back above
    there is no run-time register that supplies the missing half in a
    disciplined way: `_width` has ALREADY ruled a value >= $100 out of
    direct page.  Zero occurrences in the 414 corpus narrowings, so this is
    the truncation with no witness.
    """
    assert raises(EncodeError, 'STX', '$1234,y') == (
        "operand '$1234,y' needs 2 bytes but STX y-indexed has only a "
        "1-byte form (dp,y)")
    assert enc_b('STX', '$34,y') == '9634'         # a real dp,y store is fine


def test_narrowing_to_a_16_bit_form_is_never_refused():
    """The corpus's own shape (see the DOCUMENTED note above), non-indexed.

    A mnemonic with no long form emits the abs form and lets DBR supply the
    bank, exactly as the y-indexed case does.  All 414 corpus narrowings are
    this class, so it must stay silent.
    """
    assert enc_b('TRB', '$030000') == '1c0000'
    assert enc_b('CPX', '$030000') == 'ec0000'
    assert enc_b('STY', '$030000') == '8c0000'
    assert enc_b('LDA', '$030000,y') == 'b90000'


def test_narrowing_is_only_refused_when_the_width_is_definite():
    """A forward reference must not be accused during an early pass.

    `_width` answers 2 for an unresolved expression and for a relocatable
    reference, neither of which is evidence about the operand's real size.
    Only a resolved literal or an explicit size-forcing prefix can trip the
    check — otherwise multi-pass assembly would report a false error on
    every forward-referenced operand in pass 1.
    """
    # unresolved -> sized 2, no accusation, dp,y placeholder + fixup
    h, f = enc('STX', 'Forward,y')
    assert h == '9600' and (f.expr, f.nbytes) == ('Forward', 1)
    # relocatable -> _width's answer is a POLICY ("never direct page"), not a
    # measurement, so it does not accuse either.  KNOWN LIMITATION, kept
    # deliberately conservative: `stx Label,y` still truncates quietly.
    assert enc_b('STX', 'ABSVAL,y', reloc=reloc_for('ABSVAL')) == '9634'
    # resolved literal -> accused
    assert raises(EncodeError, 'STX', 'ABSVAL,y')


def test_dp_only_and_abs_only_mnemonics_use_the_widest_available_form():
    assert enc_b('TRB', '$10') == '1410'
    assert enc_b('TRB', '$1234') == '1c3412'
    assert enc_b('TRB', '$030000') == '1c0000'     # no long form -> abs (DBR)
    assert enc_b('CPX', '$030000') == 'ec0000'
    assert enc_b('STY', '$030000') == '8c0000'


def test_relocatable_operand_is_forced_absolute_even_with_a_dp_value():
    r = reloc_for('DPVAL')
    assert enc_b('LDA', 'DPVAL') == 'a510'                     # no predicate: dp
    assert enc_b('LDA', 'DPVAL', reloc=r) == 'ad1000'          # predicate: abs


def test_unresolved_operand_sizes_absolute_and_defers():
    h, f = enc('LDA', 'Forward')
    assert h == 'ad0000'
    assert (f.expr, f.nbytes, f.kind, f.shift) == ('Forward', 2, 'val', 0)


def test_stack_relative_and_stack_relative_indirect_indexed():
    assert enc_b('LDA', '3,s') == 'a303'
    assert enc_b('STA', '3,s') == '8303'
    assert enc_b('LDA', '(3,s),y') == 'b303'
    assert enc_b('ADC', '$FF,s') == '63ff'
    # ,s is always one byte, so an offset that does not FIT in one is an
    # error rather than a masked-to-$34 access (RESOLVED: used to be 'a334').
    # A stack-relative displacement is 8-bit by construction — no run-time
    # register can supply the missing half, unlike the DBR/bank case.
    assert raises(EncodeError, 'LDA', '$1234,s') == (
        "operand '$1234,s' needs 2 bytes but LDA stack-relative has only a "
        "1-byte form (sr,s)")


def test_pick_mode_stack_family_is_all_or_nothing():
    assert _pick_mode(OPTABLE['LDA'], 1, 's') == 'sr'
    assert _pick_mode(OPTABLE['LDA'], 3, 's') == 'sr'      # width is irrelevant
    assert _pick_mode(OPTABLE['LDX'], 1, 's') is None      # LDX has no sr form


# --------------------------------------------------------------------------
# 6. encode(): indirect forms
# --------------------------------------------------------------------------

def test_direct_page_indirect_forms():
    assert enc_b('LDA', '($10)') == 'b210'         # (dp)
    assert enc_b('LDA', '($10,x)') == 'a110'       # (dp,x)
    assert enc_b('LDA', '($10),y') == 'b110'       # (dp),y
    assert enc_b('STA', '($10,x)') == '8110'
    assert enc_b('STA', '($10),y') == '9110'


def test_long_indirect_forms():
    assert enc_b('LDA', '[$10]') == 'a710'         # [dp]
    assert enc_b('LDA', '[$10],y') == 'b710'       # [dp],y
    assert enc_b('STA', '[$10],Y') == '9710'       # case-insensitive suffix


def test_indirect_operands_are_always_one_byte_even_for_wide_values():
    """The operand inside ( ) or [ ] is a direct-page offset by definition;
    a 16-bit value is truncated rather than promoted."""
    assert enc_b('LDA', '($1234)') == 'b234'
    assert enc_b('LDA', '[$1234]') == 'a734'
    assert enc_b('LDA', '(|$1234)') == 'b234'      # prefix stripped, not honoured
    assert enc_b('LDA', '(<$10),y') == 'b110'
    assert enc_b('LDA', '[|$10]') == 'a710'


def test_absolute_indirect_forms_are_control_flow_only():
    assert enc_b('JMP', '($1234)') == '6c3412'     # (abs)
    assert enc_b('JMP', '($1234,x)') == '7c3412'   # (abs,x)
    assert enc_b('JMP', '[$1234]') == 'dc3412'     # [abs]
    assert enc_b('JML', '[$1234]') == 'dc3412'
    assert enc_b('JSR', '($1234,x)') == 'fc3412'   # (abs,x)
    # ... and the two-byte operand is NOT truncated to a dp offset
    assert enc_b('JMP', '[$10]') == 'dc1000'


def test_pea_pushes_an_absolute_word_with_or_without_a_hash():
    assert enc_b('PEA', '$1234') == 'f43412'
    assert enc_b('PEA', '#$1234') == 'f43412'
    assert enc_b('PEA', '$030000') == 'f40000'     # 2 bytes, bank dropped


def test_pea_honours_the_part_selectors():
    """`pea #^X` pushes the bank part; before the fix it evaluated `^X` as a
    bitwise operator.  The selector shifts, then masks to the 2-byte width."""
    assert enc_b('PEA', '#^LONGVAL') == 'f40300'
    assert enc_b('PEA', '#>LONGVAL') == 'f40003'
    assert enc_b('PEA', '#<LONGVAL') == 'f40000'
    assert enc_b('PEA', '#>ABSVAL') == 'f41200'


def test_pei_is_direct_page_indirect_in_every_spelling():
    assert enc_b('PEI', '($10)') == 'd410'
    assert enc_b('PEI', '$10') == 'd410'
    assert enc_b('PEI', '#$10') == 'd410'
    assert enc_b('PEI', '($10,x)') == 'd410'       # index suffix stripped
    h, f = enc('PEI', 'Forward')
    assert h == 'd400' and (f.nbytes, f.kind) == (1, 'val')


# --------------------------------------------------------------------------
# 7. encode(): relative branches
# --------------------------------------------------------------------------

def test_short_branches_emit_opcode_plus_one_placeholder_byte():
    for mnem, op in (('BCC', '90'), ('BCS', 'b0'), ('BEQ', 'f0'), ('BNE', 'd0'),
                     ('BMI', '30'), ('BPL', '10'), ('BVC', '50'), ('BVS', '70'),
                     ('BRA', '80')):
        h, f = enc(mnem, 'Target')
        assert h == op + '00', mnem
        assert (f.expr, f.nbytes, f.kind) == ('Target', 1, 'rel8'), mnem


def test_branch_aliases_encode_as_their_canonical_opcodes():
    assert enc('BLT', 'Target')[0] == '9000'       # BLT == BCC
    assert enc('BGE', 'Target')[0] == 'b000'       # BGE == BCS


def test_long_relative_branches_emit_two_placeholder_bytes():
    for mnem, op in (('BRL', '82'), ('PER', '62')):
        h, f = enc(mnem, 'Target', pc=0x1000)
        assert h == op + '0000', mnem
        assert (f.expr, f.nbytes, f.kind, f.pc) == ('Target', 2, 'rel16', 0x1000)


def test_branch_targets_are_always_deferred_even_when_resolvable():
    """The load-bearing invariant behind test_branch_range.py.

    `_emit` computes `val` only for kind in ('val', 'byte'), so rel8/rel16
    ALWAYS come back as a Fixup — displacement arithmetic and the
    -128..127 / -32768..32767 range check live in asm.py's apply_fixups /
    relink, where the local-label scope of the reference is available.
    """
    h, f = enc('BEQ', '$1234', pc=0x1000)          # fully resolvable operand
    assert h == 'f000' and f is not None and f.kind == 'rel8'
    h, f = enc('BRL', '$1234', pc=0x1000)
    assert h == '820000' and f is not None and f.kind == 'rel16'


def test_emit_rel_arms_are_dead_code_even_when_called_directly():
    """Same invariant from the other side: _emit never resolves a rel kind,
    so its displacement arithmetic is unreachable by construction."""
    b, f = _emit(0xF0, 'x', 1, 'rel8', lambda e: 0x1234, 0x1000)
    assert b == b'\xf0\x00' and f is not None and f.kind == 'rel8'
    b, f = _emit(0x82, 'x', 2, 'rel16', lambda e: 0x1234, 0x1000)
    assert b == b'\x82\x00\x00' and f is not None and f.kind == 'rel16'


# --------------------------------------------------------------------------
# 8. encode(): block moves (fixtures 025 + 064)
# --------------------------------------------------------------------------

def test_blockmove_operand_order_is_dest_bank_then_src_bank():
    """Fixture 025: written `MVN src,dst`, encoded opcode, dst, src."""
    assert enc_b('MVN', '$010000,$020000') == '540201'
    assert enc_b('MVP', '$7E0000,$7F0000') == '447f7e'


def test_blockmove_bank_byte_is_the_operand_shifted_right_16():
    """Fixture 064: the emitted byte is the operand's BANK (`value >> 16`),
    never its low byte — `mvp $FF,$FF` is `44 00 00` (MIDI's self-modified
    placeholder), and gold ships exactly that."""
    assert enc_b('MVP', '$FF,$FF') == '440000'
    assert enc_b('MVN', '$E10000,$E00000') == '54e0e1'
    assert enc_b('MVP', '$012345,$0067FF') == '440001'
    # the corpus also spells a block move with a blank after the comma --
    # GQuit.src:1068 `mvn 0, $E10000`, gold `54 E1 00` (GQuit006800.asm:205)
    assert enc_b('MVN', '0, $E10000') == '54e100'


def test_blockmove_reports_a_bank_it_cannot_account_for():
    """RESOLVED (was SUSPICIOUS): bank 0 is now only baked for an owner.

    A block move cannot come back as a Fixup — it has two operand fields and
    `encode` returns at most one, at a patch offset asm.py fixes at 1.  So
    an operand `encode` cannot account for used to contribute bank 0 in
    silence.  Wrong arity and unresolvable expressions are now reported;
    bank 0 survives only for the two operands somebody else owns (see
    `_deferred_bank`), which is the case the corpus actually uses.
    """
    assert raises(EncodeError, 'MVN', '$010000') == (
        "MVN takes exactly two operands (source,destination), got '$010000'")
    assert raises(EncodeError, 'MVN', '')
    assert raises(EncodeError, 'MVN', '$010000,')
    assert raises(EncodeError, 'MVN', ',$010000')
    assert raises(EncodeError, 'MVN', '$010000,$020000,$030000')  # no longer ignored
    assert raises(EncodeError, 'MVN', '$010000,$02 0000') == (
        "MVN: cannot resolve bank of '$02 0000'")


def test_blockmove_still_bakes_bank_zero_for_an_operand_the_linker_owns():
    """The two accountable cases, kept exactly as they were.

    omf.py rewrites a relocatable or undefined-external block-move operand
    into an explicit `expr>>16` RELEXPR, and multi-pass assembly resolves a
    not-yet-defined identifier on a later run.  Both must keep their bank-0
    placeholder or `mvn main,databank` (20 corpus uses) would break.
    """
    assert enc_b('MVN', 'Fwd,Fwd') == '540000'                     # identifiers
    assert enc_b('MVN', 'main,databank') == '540000'
    assert enc_b('MVN', 'Fwd,$E10000', reloc=reloc_for('Fwd')) == '54e100'
    # a resolved identifier is not deferred at all — it contributes its bank
    assert enc_b('MVN', 'LONGVAL,BANK2END') == '540203'


# --------------------------------------------------------------------------
# 9. _crossbank: JMP->JML / JSR->JSL promotion
# --------------------------------------------------------------------------

def test_jump_stays_absolute_within_the_pcs_bank():
    assert enc_b('JMP', '$1234') == '4c3412'
    assert enc_b('JSR', '$1234') == '203412'
    assert enc_b('JMP', '$030000', pc=0x030000) == '4c0000'
    assert enc_b('JSR', '$030000', pc=0x030000) == '200000'


def test_jump_promotes_to_long_when_the_target_bank_differs():
    assert enc_b('JMP', '$030000', pc=0) == '5c000003'          # JMP -> JML opcode
    assert enc_b('JSR', '$030000', pc=0) == '22000003'          # JSR -> JSL opcode
    assert OPTABLE['JML']['abl'] == 0x5C and OPTABLE['JSL']['abl'] == 0x22


def test_crossbank_is_forced_by_the_long_prefix():
    assert enc_b('JMP', '>ABSVAL') == '5c341200'
    assert enc_b('JSR', '>ABSVAL') == '22341200'


def test_crossbank_never_promotes_a_relocatable_target():
    """A same-segment label's final address is link-assigned, so its current
    value must not drive a long-transfer promotion."""
    r = reloc_for('LONGVAL')
    assert enc_b('JMP', 'LONGVAL') == '5c000003'               # no predicate
    assert enc_b('JMP', 'LONGVAL', reloc=r) == '4c0000'        # predicate wins
    assert enc_b('JSR', 'LONGVAL', reloc=r) == '200000'


def test_crossbank_never_promotes_an_unresolved_target():
    h, f = enc('JMP', 'Forward')
    assert h == '4c0000' and (f.nbytes, f.kind) == (2, 'val')
    h, f = enc('JSR', 'Forward')
    assert h == '200000' and (f.nbytes, f.kind) == (2, 'val')


def test_crossbank_16_bit_target_stays_absolute_from_a_high_bank():
    """A value below $10000 is a same-bank assumption, not bank 0."""
    assert enc_b('JMP', '$1234', pc=0x030000) == '4c3412'
    assert enc_b('JSR', '$1234', pc=0xFF0000) == '203412'


def test_explicit_long_jumps_never_shrink():
    assert enc_b('JSL', '$1234') == '22341200'
    assert enc_b('JML', '$1234') == '5c341200'
    assert enc_b('JSL', '$030000', pc=0x030000) == '22000003'
    assert enc_b('JML', '$030000', pc=0x030000) == '5c000003'


def test_jsr_indexed_indirect_is_recognised_before_the_crossbank_test():
    assert enc_b('JSR', '$1234,x') == 'fc3412'     # bare ,x -> (abs,x) opcode
    assert enc_b('JSR', '($1234,x)') == 'fc3412'


# --------------------------------------------------------------------------
# 10. operand-text helpers
# --------------------------------------------------------------------------

def test_strip_index_finds_a_depth_zero_suffix_only():
    assert _strip_index('$10') == ('$10', None)
    assert _strip_index('$10,x') == ('$10', 'x')
    assert _strip_index('$10,X') == ('$10', 'x')
    assert _strip_index('$10,y') == ('$10', 'y')
    assert _strip_index('$10,s') == ('$10', 's')
    assert _strip_index('($10,x)') == ('($10,x)', None)     # nested: depth 1
    assert _strip_index('($10,x),y') == ('($10,x)', 'y')
    assert _strip_index('[$10],y') == ('[$10]', 'y')
    assert _strip_index('$10 ,x') == ('$10', 'x')           # base is rstripped


def test_ends_depth0_ignores_indices_inside_brackets_and_quotes():
    assert _ends_depth0('a,x', ',x') is True
    assert _ends_depth0('(a,x)', ',x') is False
    assert _ends_depth0('(a),y', ',y') is True
    assert _ends_depth0('[a],y', ',y') is True
    assert _ends_depth0("'(',x", ',x') is True     # the paren is inside a string
    assert _ends_depth0('a,z', ',x') is False


def test_unpfx_strips_one_leading_size_prefix():
    assert _unpfx('<foo') == 'foo'
    assert _unpfx('>foo') == 'foo'
    assert _unpfx('|foo') == 'foo'
    assert _unpfx('!foo') == 'foo'
    assert _unpfx('  <  foo  ') == 'foo'
    assert _unpfx('foo') == 'foo'
    assert _unpfx('^foo') == '^foo'                # '^' is NOT a size prefix
    assert _unpfx('<<foo') == '<foo'               # only one is stripped


def test_operand_whitespace_is_ignored():
    assert enc_b('LDA', '   $10   ') == 'a510'
    assert enc_b('LDA', ' # $12 ') == 'a912'
    assert enc_b('LDA', ' < $1234 ') == 'a534'


# --------------------------------------------------------------------------
# 11. error paths
# --------------------------------------------------------------------------

def test_unknown_mnemonic_returns_none_none():
    assert encode('XYZZY', '$10', False, False, ev, 0) == (None, None)
    assert encode('', '', False, False, ev, 0) == (None, None)
    assert encode('LDAA', '$10', False, False, ev, 0) == (None, None)


def test_operand_that_fits_no_available_mode_is_an_encode_error():
    """RESOLVED (was SUSPICIOUS): no silent `00 00` placeholder any more.

    When `_pick_mode` exhausts every fallback, `encode` used to return
    `bytes([0x00]) + b'\\x00'` — a two-byte BRK-shaped placeholder, with no
    error and no fixup.  `stz $10,y`, `ldx 3,s` and `ldy $10,y` are not
    65816 instructions; two silent zero bytes in the instruction stream is
    the worst failure class an assembler has (cf. test_branch_range.py), so
    they now raise EncodeError, which asm.py turns into a located
    `a.errors` entry (see tests/test_encoder_diagnostics.py).
    """
    assert raises(EncodeError, 'STZ', '$10,y') == (
        "STZ has no y-indexed addressing mode (operand '$10,y')")
    assert raises(EncodeError, 'LDX', '3,s') == (
        "LDX has no stack-relative addressing mode (operand '3,s')")
    assert raises(EncodeError, 'LDY', '$10,y') == (
        "LDY has no y-indexed addressing mode (operand '$10,y')")
    # the modes that DO exist are untouched
    assert enc_b('STZ', '$10,x') == '7410'
    assert enc_b('LDX', '$10,y') == 'b610'
    assert enc_b('LDA', '3,s') == 'a303'


def test_indirect_form_unsupported_by_the_mnemonic_raises_keyerror():
    """SUSPICIOUS (pinned, not fixed).

    The indirect branches index `tab[...]` directly with no membership
    test, so a syntactically valid but unsupported indirect spelling raises
    KeyError out of encode() instead of reporting an assembly error.  None
    of these shapes occurs in the corpus.
    """
    for mnem, operand, missing in (('JML', '($1234)', 'aind'),
                                   ('JSR', '[$1234]', 'indl'),
                                   ('JMP', '($1234),y', 'indy'),
                                   ('JSL', '($10)', 'ind'),
                                   ('JSL', '[$10]', 'indl'),
                                   ('TRB', '($10),y', 'indy')):
        try:
            encode(mnem, operand, False, False, ev, 0)
        except KeyError as exc:
            assert exc.args[0] == missing, (mnem, operand, exc.args)
        else:
            raise AssertionError(f'expected KeyError for {mnem} {operand}')


def test_encode_never_raises_for_any_table_mnemonic_with_a_plain_operand():
    """Smoke sweep: every mnemonic in the table (plus every alias) encodes a
    bare direct-page operand without blowing up, and returns either bytes or
    the (None, None) unknown-mnemonic signal.  MVN/MVP are excluded: a block
    move needs two operands and now says so rather than inventing a bank."""
    for mnem in sorted(MNEMONICS - BLOCKMOVE):
        b, f = encode(mnem, '$10', False, False, ev, 0)
        assert b is None or (isinstance(b, bytes) and 1 <= len(b) <= 4), mnem
        assert f is None or isinstance(f, Fixup), mnem


# --------------------------------------------------------------------------
# 12. instr_length
# --------------------------------------------------------------------------

def test_instr_length_counts_the_encoded_bytes():
    assert instr_length('NOP', '', False, False, ev) == 1
    assert instr_length('LDA', '#$12', False, False, ev) == 2
    assert instr_length('LDA', '#$12', True, False, ev) == 3
    assert instr_length('LDA', '$1234', False, False, ev) == 3
    assert instr_length('LDA', '$030000', False, False, ev) == 4
    assert instr_length('MVN', '$1,$2', False, False, ev) == 3
    assert instr_length('BRL', 'Target', False, False, ev) == 3


def test_instr_length_reports_one_for_an_unknown_mnemonic():
    assert instr_length('XYZZY', '', False, False, ev) == 1


def test_instr_length_can_be_told_the_pc_and_then_agrees_with_encode():
    """RESOLVED (was SUSPICIOUS): pc/reloc are parameters, not hard-coded 0.

    `instr_length` hard-coded pc=0, so every cross-bank sizing decision was
    made as if the instruction lived in bank 0 — it answered 4 for a target
    `encode` sizes as 3 bytes at the real PC.  The function is kept rather
    than deleted (it is public API of a published package and has no
    underscore), with `pc` and `reloc` added as DEFAULTED parameters so the
    old five-argument call shape is untouched.
    """
    # unchanged when the caller does not say otherwise
    assert instr_length('JMP', '$030000', False, False, ev) == 4
    # ... and now able to agree with encode() at the real PC
    for pc in (0, 0x1234, 0x030000, 0xFE0000):
        assert instr_length('JMP', '$030000', False, False, ev, pc) == \
            len(encode('JMP', '$030000', False, False, ev, pc)[0]), hex(pc)
    # the reloc predicate reaches encode too (a relocatable target never
    # promotes to a long jump)
    r = reloc_for('LONGVAL')
    assert instr_length('JMP', 'LONGVAL', False, False, ev) == 4
    assert instr_length('JMP', 'LONGVAL', False, False, ev, 0, r) == 3


def test_instr_length_propagates_an_unencodable_shape():
    """A shape with no encoding has no length either."""
    assert raises(EncodeError, 'STZ', '$10,y')
    try:
        instr_length('STZ', '$10,y', False, False, ev)
    except EncodeError:
        pass
    else:
        raise AssertionError('instr_length swallowed an EncodeError')


# --------------------------------------------------------------------------
# 13. Fixup shape
# --------------------------------------------------------------------------

def test_fixup_records_the_instruction_pc_not_the_operand_offset():
    for pc in (0, 1, 0x1234, 0x030000):
        _, f = enc('LDA', 'Forward', pc=pc)
        assert f.pc == pc


def test_fixup_is_slotted_and_defaults_shift_to_zero():
    f = Fixup('X', 2, 'val', 0)
    assert f.shift == 0
    assert not hasattr(f, '__dict__'), 'Fixup must stay __slots__-only'
    assert m65816.Fixup.__slots__ == ('expr', 'nbytes', 'kind', 'pc', 'shift')


def test_resolved_operands_are_emitted_little_endian():
    assert enc_b('LDA', '$1234') == 'ad' + '3412'
    assert enc_b('LDA', '$123456', pc=0) == 'af' + '563412'
    assert enc_b('LDA', '#$1234', longa=True) == 'a9' + '3412'


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
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f'ERROR {name}: {exc!r}')
        else:
            print(f'ok   {name}')
    print(f'{len(_TESTS) - failed}/{len(_TESTS)} passed')
    sys.exit(1 if failed else 0)
