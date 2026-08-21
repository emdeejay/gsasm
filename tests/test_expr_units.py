"""Direct unit tests for gsasm/expr.py — the MPW AsmIIgs expression evaluator.

Until now `expr.py` had no direct coverage at all: every one of its behaviours
was exercised only through whole-pipeline golden-byte diffing, so a regression
in (say) the truncating-division rule surfaced as "byte 0x0e5d of Tool014
differs" and had to be diagnosed backwards through the assembler, the linker
and MakeBinIIgs.  These tests pin the evaluator's semantics at the source.

Everything here is CORPUS-FREE: the inputs are expression strings we write
ourselves, so the file runs in CI with no ref/ tree present.

Each test asserts what the evaluator ACTUALLY does today, including the places
where that is surprising (`**` is AND not exponentiation; `--` is XOR; shifts
bind looser than addition).  Those are marked "PINNED (surprising)" and are NOT
statements about what MPW ought to do — they are a tripwire so that any future
change to them is a deliberate, visible act rather than a golden-byte mystery.

Run either as:
    python3 -m pytest tests/test_expr_units.py
    python3 tests/test_expr_units.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from gsasm import expr  # noqa: E402


DOLLAR = chr(36)        # '$' spelled out where it would fight with shell/f-string habits


def ev(text, **kw):
    return expr.evaluate(text, **kw)


def raises_unresolved(text, **kw):
    """True iff evaluating *text* raises expr.Unresolved."""
    try:
        expr.evaluate(text, **kw)
    except expr.Unresolved:
        return True
    return False


# --------------------------------------------------------------------------
# Division: MPW truncates toward zero (Do-Not-Touch registry: "expr.py
# division/*-PC/MSB semantics ... MPW truncating division")
# --------------------------------------------------------------------------
def test_division_truncates_toward_zero():
    # Python's // floors: -7 // 2 == -4.  MPW (and hence gsasm) truncates.
    assert ev('7/2') == 3
    assert ev('-7/2') == -3
    assert ev('7/-2') == -3
    assert ev('-7/-2') == 3
    # the case named in the source comment
    assert ev('-32767/2') == -16383


def test_division_is_exact_when_it_divides_evenly():
    assert ev('-8/2') == -4
    assert ev('8/-2') == -4


def test_div_keyword_is_the_same_operator_as_slash():
    for a, b in (('7', '2'), ('-7', '2'), ('7', '-2'), ('-7', '-2')):
        assert ev(a + ' DIV ' + b) == ev(a + '/' + b)
    assert ev('-7 div 2') == -3          # keywords are case-insensitive


def test_division_by_zero_yields_zero_and_does_not_raise():
    # `q = abs(v) // abs(d) if d else 0` — a zero divisor is swallowed.
    assert ev('5/0') == 0
    assert ev('-5/0') == 0
    assert ev('5 DIV 0') == 0


def test_mod_is_floored_not_truncated():
    # PINNED (surprising): `//` / MOD delegates to Python's %, which floors,
    # while `/` truncates.  C-style truncation would give -7 MOD 2 == -1.
    assert ev('7//2') == 1
    assert ev('-7//2') == 1
    assert ev('-5 MOD 3') == 1
    assert ev('5 MOD 3') == 2
    assert ev('5//-3') == -1


def test_mod_by_zero_yields_zero_like_division_by_zero():
    # DOCUMENTED (Asm Ref p.30): "Division by 0 yields 0 as the result", and
    # Table 2-2 (p.29) / the index class `//` / MOD as "Modulus division" — so
    # the documented rule covers this operator too.  This ASSERTION CHANGED in
    # 0.6.0: it used to pin a raw ZeroDivisionError escaping through try_eval.
    assert ev('5 MOD 0') == 0
    assert ev('5//0') == 0
    assert ev('-5 MOD 0') == 0
    assert expr.try_eval('5//0') == 0
    # ...and it agrees with the sibling operator, which already did this.
    assert ev('5 MOD 0') == ev('5/0')


# --------------------------------------------------------------------------
# `*` — the program counter (and the `**` collision)
# --------------------------------------------------------------------------
def test_star_at_term_start_is_the_program_counter():
    assert ev('*', pc=0x2000) == 0x2000
    assert ev('*+2', pc=0x2000) == 0x2002
    assert ev('*-*', pc=0x2000) == 0            # `*` after a binary op is a PC too


def test_star_between_terms_is_multiplication():
    assert ev('2*3', pc=0x2000) == 6
    # ...and a PC may be the right operand of a multiply: `2* *` is 2 x PC.
    assert ev('2* *', pc=0x10) == 0x20


def test_pc_of_zero_is_a_location_not_a_missing_one():
    # The guard is `if self.pc is None`, not a falsiness test: origin $0000 is
    # a perfectly good location.
    assert ev('*', pc=0) == 0
    assert ev('*+1', pc=0) == 1


def test_star_without_a_location_is_unresolved():
    assert raises_unresolved('*')
    assert raises_unresolved('*+1', pc=None)
    assert expr.try_eval('*') is None


def test_double_star_is_bitwise_and_not_exponentiation():
    # PINNED: '**' is lexed as one token (bitwise AND).  `3**2` is 3 AND 2 == 2,
    # NOT 9, and NOT "3 times PC".
    assert ev('3**2', pc=0x1234) == 2
    assert ev('6**3') == 2
    assert ev('6**3') == ev('6 AND 3')


# --------------------------------------------------------------------------
# Character literals: Mac Roman bytes, not Unicode code points
# --------------------------------------------------------------------------
def test_ascii_character_literal():
    assert ev("'A'") == 0x41
    assert ev('"A"') == 0x41              # double quotes are equivalent


def test_high_characters_use_the_mac_roman_byte():
    # Do-Not-Touch registry: `pea '“'` in GS.OS Init2 must push $00D2.
    # ord('“') would be 0x201C; the Mac Roman byte is 0xD2.
    assert ev("'“'") == 0xD2
    assert ev("'”'") == 0xD3
    assert ev("'é'") == 0x8E          # e-acute is Mac Roman 0x8E, not 0xE9


def test_unencodable_character_falls_back_to_low_byte_of_code_point():
    # No Mac Roman mapping exists: `ord(c) & 0xFF`.  U+4E2D -> 0x2D.
    assert ev("'中'") == 0x2D


def test_multi_character_literal_packs_big_endian():
    assert ev("'AB'") == 0x4142
    assert ev("'ABCD'") == 0x41424344


def test_doubled_quote_is_an_escaped_quote():
    assert ev("''''") == 0x27              # four apostrophes -> one apostrophe
    assert ev("'a''b'") == 0x612762        # a, ', b
    assert ev('"a""b"') == 0x612262


def test_unterminated_character_literal_still_yields_its_bytes():
    # PINNED (surprising): running off the end of the string is not an error.
    assert ev("'A") == 0x41
    assert ev("'AB") == 0x4142


def test_msb_flag_sets_the_high_bit_of_every_character():
    # MSB ON (hi-ASCII / screen text) ORs 0x80 into each character byte...
    assert ev("'A'", msb=True) == 0xC1
    assert ev("'AB'", msb=True) == 0xC1C2
    # ...and touches nothing else: numeric literals are unaffected.
    assert ev('65', msb=True) == 65
    assert ev(DOLLAR + '41', msb=True) == 0x41
    assert ev("'A'", msb=False) == 0x41


# --------------------------------------------------------------------------
# Radix forms
# --------------------------------------------------------------------------
def test_radix_prefixes():
    assert ev(DOLLAR + 'FF') == 255
    assert ev(DOLLAR + 'ff') == 255
    assert ev('%1010') == 10
    assert ev('255') == 255


def test_bare_radix_prefix_is_zero():
    assert ev(DOLLAR) == 0
    assert ev('%') == 0


def test_radix_scan_stops_at_the_first_out_of_range_digit():
    # PINNED: '%12' is binary 1 followed by the decimal literal 2 — and the
    # trailing 2 is then silently dropped (see the trailing-token test below).
    assert ev('%12') == 1
    assert expr.tokenize('%12') == [('num', 1), ('num', 2), ('end', None)]
    # hex stops at 'g', which starts a symbol
    assert expr.tokenize(DOLLAR + '1Ag') == [('num', 0x1A), ('sym', 'g'),
                                             ('end', None)]


def test_values_are_unbounded_python_ints_not_masked_to_32_bits():
    # PINNED: expr does no width masking; callers (asm/omf) mask at the store.
    assert ev(DOLLAR + 'FFFFFFFF') == 0xFFFFFFFF
    assert ev('1<<40') == 1 << 40
    assert ev('~0') == -1


# --------------------------------------------------------------------------
# Precedence and associativity
# --------------------------------------------------------------------------
def test_multiplicative_binds_tighter_than_additive():
    assert ev('1+2*3') == 7
    assert ev('1+6/3') == 3


def test_shifts_bind_LOOSER_than_addition():
    # PINNED: the MPW ladder puts << >> BELOW + -, so `1<<2+3` is 1<<5 == 32,
    # not (1<<2)+3 == 7.  A C programmer's instinct is wrong here.
    assert ev('1<<2+3') == 32
    assert ev('16>>1+1') == 4


def test_bitwise_and_binds_looser_than_shifts_and_addition():
    assert ev('3**1+1') == 2               # 3 AND (1+1)
    assert ev('12**1<<3') == 8             # 12 AND (1<<3)


def test_bitwise_or_binds_looser_than_and():
    assert ev('1++2**3') == 3              # 1 OR (2 AND 3) == 1|2
    assert ev('1|2**3') == 3


def test_comparisons_sit_at_the_bottom_of_the_ladder():
    assert ev('1=1+1') == 0                # 1 = (1+1)
    assert ev('3=1++2') == 1               # 3 = (1 OR 2)
    assert ev('4=1<<2') == 1               # 4 = (1<<2)
    assert ev('1=2**3') == 0               # 1 = (2 AND 3) == 1=2


def test_comparison_yields_one_or_zero():
    assert ev('1=1') == 1
    assert ev('1=2') == 0
    assert ev('1<>2') == 1
    assert ev('1<>1') == 0
    assert ev('1<2') == 1 and ev('2<1') == 0
    assert ev('2>1') == 1 and ev('1>2') == 0
    assert ev('1<=1') == 1 and ev('2<=1') == 0
    assert ev('1>=1') == 1 and ev('1>=2') == 0


def test_binary_operators_are_left_associative():
    assert ev('10-3-2') == 5               # (10-3)-2, not 10-(3-2)
    assert ev('100/10/2') == 5
    assert ev('1<<2<<3') == 32             # (1<<2)<<3
    assert ev('8>>1>>1') == 2
    assert ev('2>1=1') == 1                # (2>1) = 1


def test_parentheses_override_the_ladder():
    assert ev('(1+2)*3') == 9
    assert ev('(1<<2)+3') == 7
    assert ev('(1=1)+1') == 2


# --------------------------------------------------------------------------
# The bitwise/logical operator zoo (symbol and keyword spellings)
# --------------------------------------------------------------------------
def test_and_or_eor_spellings_agree():
    assert ev('6 AND 3') == 2 and ev('6**3') == 2
    assert ev('6 OR 3') == 7 and ev('6++3') == 7 and ev('6|3') == 7
    assert ev('6 EOR 3') == 5 and ev('6 XOR 3') == 5 and ev('6--3') == 5


def test_double_minus_lexes_as_xor_not_as_two_unary_minuses():
    # PINNED (surprising): '--' is a single token, so `6--3` is 6 EOR 3 == 5,
    # NOT 6-(-3) == 9.  Spacing rescues the arithmetic reading.
    assert ev('6--3') == 5
    assert ev('6- -3') == 9


def test_operator_keywords_are_case_insensitive():
    assert ev('6 and 3') == 2
    assert ev('6 Eor 3') == 5
    assert ev('6 xor 3') == 5
    assert ev('7 mod 4') == 3
    assert expr.tokenize('and Or eOr xor mod div not') == [
        ('kw', 'AND'), ('kw', 'OR'), ('kw', 'EOR'), ('kw', 'XOR'),
        ('kw', 'MOD'), ('kw', 'DIV'), ('kw', 'NOT'), ('end', None)]


# --------------------------------------------------------------------------
# Unary operators
# --------------------------------------------------------------------------
def test_unary_minus_and_plus():
    assert ev('-5') == -5
    assert ev('+5') == 5
    assert ev('- -5') == 5                 # spaced: two unary minuses
    assert ev('-(2+3)') == -5


def test_tilde_is_ones_complement():
    assert ev('~5') == -6
    assert ev('~0') == -1


def test_approx_sign_is_the_ones_complement_operator():
    # MPW AsmIIgs spells one's complement '≈'; the tokenizer folds it to '~'.
    assert ev('≈5') == -6
    assert ev('≈5') == ev('~5')
    assert expr.tokenize('≈1') == ['~', ('num', 1), ('end', None)]


def test_NOT_is_logical_not_bitwise():
    # Do-Not-Touch: `if NOT Version6x` with Version6x=1 must be FALSE.  The
    # bitwise complement is '≈' / '~', a different operator.
    assert ev('NOT 1') == 0
    assert ev('NOT 0') == 1
    assert ev('NOT 5') == 0
    assert ev('not 0') == 1
    assert ev('NOT 1') != ev('~1')


def test_unary_binds_tighter_than_multiplication():
    assert ev('-2*3') == -6
    assert ev('~1*2') == -4                # (~1)*2 == -2*2


# --------------------------------------------------------------------------
# Symbols and the resolve callback
# --------------------------------------------------------------------------
def test_symbol_is_passed_to_resolve_verbatim_preserving_case():
    seen = []

    def res(name):
        seen.append(name)
        return {'Foo': 9}.get(name)

    assert ev('Foo', resolve=res) == 9
    assert seen == ['Foo']                 # NOT upper-cased by expr


def test_dollar_inside_a_symbol_is_a_name_character():
    # The SCSI driver's `cmd_$8028` labels: '$' starts a hex literal only at a
    # term start, never mid-identifier.
    name = 'cmd_' + DOLLAR + '8028'
    seen = []

    def res(n):
        seen.append(n)
        return 0x28

    assert ev(name + '+1', resolve=res) == 0x29
    assert seen == [name]


def test_symbol_start_characters():
    tbl = {'_a': 1, '.b': 2, '@c': 4, '?d': 8, 'e.f$g': 16}
    res = tbl.get
    assert ev('_a+.b+@c+?d+e.f' + DOLLAR + 'g', resolve=res) == 31


def test_undefined_symbol_is_unresolved_and_try_eval_returns_none():
    assert raises_unresolved('BAR')
    assert expr.try_eval('BAR') is None
    assert expr.try_eval('1+2') == 3
    # the default resolve callback answers None for everything
    assert expr.try_eval('anything') is None


def test_unary_and_binary_operators_apply_to_resolved_symbols():
    res = {'FIVE': 5}.get
    assert ev('~FIVE', resolve=res) == -6
    assert ev('FIVE*FIVE', resolve=res) == 25
    assert ev('*-FIVE', resolve=res, pc=0x2000) == 0x1FFB


# --------------------------------------------------------------------------
# Error paths and the tokenizer's tolerances
# --------------------------------------------------------------------------
def test_unknown_character_is_unresolved_not_a_python_error():
    assert raises_unresolved('1 # 2')
    assert raises_unresolved('1,2')
    assert raises_unresolved('1;2')
    assert expr.try_eval('1 # 2') is None


def test_truncated_expression_is_unresolved():
    assert raises_unresolved('')
    assert raises_unresolved('1+')
    assert raises_unresolved('2**')
    assert raises_unresolved('NOT')
    assert raises_unresolved('(')


def test_trailing_tokens_are_silently_ignored():
    # PINNED (surprising): parse() never asserts it reached ('end', None), so
    # junk after a complete expression is dropped rather than diagnosed.
    assert ev('2 3') == 2
    assert ev('1)') == 1
    assert ev('5 BAR') == 5                # ...even an undefined symbol


def test_missing_close_paren_is_tolerated():
    # `if self.peek() == ')'` — a missing ')' is simply not consumed.
    assert ev('(1+2') == 3
    assert ev('(1+2*3') == 7


def test_whitespace_is_insignificant():
    assert ev('  1  +  2  *  3  ') == 7
    assert ev('1\t+\t2') == 3
    assert ev(' ' + DOLLAR + 'FF ') == 255


def test_tokenize_reports_the_offending_string_in_the_message():
    try:
        expr.tokenize('1 # 2')
    except expr.Unresolved as exc:
        assert '#' in str(exc) and '1 # 2' in str(exc)
    else:
        raise AssertionError('tokenize accepted a bad character')


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
