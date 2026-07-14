"""Hand-authored unit tests for gsasm/rez/lexer.py (work packet R3).

These are original snippets (NOT derived from Apple sources) each pinning one
lexer/preprocessor behavior discovered while tokenizing the real corpus
(work/rezlexcheck.py runs the corpus check itself; that harness lives under
work/ because the corpus it reads is gitignored Apple material — this file
only ever needs small strings we write ourselves).

Run either as:
    python3 -m pytest tests/test_rez_lexer.py
    python3 tests/test_rez_lexer.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from gsasm.rez import lexer  # noqa: E402


def _toks(data, name='t.r', include_dirs=None):
    """Write `data` (str, encoded latin-1, or bytes) to a temp file named
    `name` and return its non-EOF token list."""
    if isinstance(data, str):
        data = data.encode('latin-1')
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, name)
        with open(path, 'wb') as f:
            f.write(data)
        toks = lexer.tokenize(path, include_dirs=include_dirs)
    assert toks[-1].kind == lexer.EOF
    return toks[:-1]


def _kinds_values(toks):
    return [(t.kind, t.value) for t in toks]


# --------------------------------------------------------------------------
# CR line endings (classic Mac)
# --------------------------------------------------------------------------
def test_cr_line_endings():
    src = b'integer;\rlongint;\r'
    toks = _toks(src)
    assert _kinds_values(toks) == [
        (lexer.IDENT, 'integer'), (lexer.PUNCT, ';'),
        (lexer.IDENT, 'longint'), (lexer.PUNCT, ';'),
    ]
    assert toks[0].line == 1
    assert toks[2].line == 2  # second statement is on line 2, not glued


def test_crlf_line_endings():
    src = b'foo;\r\nbar;\r\n'
    toks = _toks(src)
    assert [t.value for t in toks] == ['foo', ';', 'bar', ';']
    assert toks[0].line == 1 and toks[2].line == 2


# --------------------------------------------------------------------------
# Comments: both styles
# --------------------------------------------------------------------------
def test_block_and_line_comments():
    src = (
        b'/* a block\r'
        b'   comment spanning lines */ foo /* inline */ bar // trailing\r'
        b'baz;\r'
    )
    toks = _toks(src)
    assert [t.value for t in toks] == ['foo', 'bar', 'baz', ';']
    # `baz` must be charged to line 3: the block comment's internal newline
    # doesn't advance any *token's* line past what surrounds it, and the
    # `//` comment eats to end of line 2 without swallowing line 3.
    assert toks[2].line == 3


# --------------------------------------------------------------------------
# #define with an empty replacement list (TypesIIGS.r's `_mybase_` idiom)
# --------------------------------------------------------------------------
def test_define_empty_body():
    src = b'#define _mybase_\r_mybase_ hex integer;\r'
    toks = _toks(src)
    # _mybase_ expands to nothing, so only `hex integer ;` remain.
    assert [t.value for t in toks] == ['hex', 'integer', ';']


def test_define_with_body_and_recursive_expansion():
    # a macro whose body itself invokes another macro (as TypesIIGS.r's
    # `#define KeyEquiv ... _mybase_ word ...` does): expansion must
    # rescan the substituted tokens for further macro names.
    src = (
        b'#define BASE hex\r'
        b'#define PAIR BASE integer, BASE integer\r'
        b'PAIR;\r'
    )
    toks = _toks(src)
    assert [t.value for t in toks] == [
        'hex', 'integer', ',', 'hex', 'integer', ';',
    ]


# --------------------------------------------------------------------------
# #if defined() branch selection (with an undefined-else-defined pair, like
# TypesIIGS.r's `#if !defined(_mybase_) / #if X==1 / #define _mybase_ hex /
# #else / #define _mybase_ / #endif / #endif`)
# --------------------------------------------------------------------------
def test_if_defined_branch_selection():
    src = (
        b'#if !defined(_mybase_)\r'
        b'  #if FOO==1\r'
        b'    #define _mybase_ hex\r'
        b'  #else\r'
        b'    #define _mybase_\r'
        b'  #endif\r'
        b'#endif\r'
        b'_mybase_ integer;\r'
    )
    toks = _toks(src)
    # FOO is never #defined, so `FOO==1` is false (undefined == 0) and the
    # #else branch (empty _mybase_) wins.
    assert [t.value for t in toks] == ['integer', ';']


def test_if_true_branch_taken_when_macro_defined_to_1():
    src = (
        b'#define FOO 1\r'
        b'#if FOO==1\r'
        b'A;\r'
        b'#else\r'
        b'B;\r'
        b'#endif\r'
    )
    toks = _toks(src)
    assert [t.value for t in toks] == ['A', ';']


# --------------------------------------------------------------------------
# Case-insensitive #include (sys.resources.r writes "typesiigs.r" for the
# real, differently-cased TypesIIGS.r)
# --------------------------------------------------------------------------
def test_case_insensitive_include():
    with tempfile.TemporaryDirectory() as d:
        inc_dir = os.path.join(d, 'incs')
        os.mkdir(inc_dir)
        with open(os.path.join(inc_dir, 'MyTypes.r'), 'wb') as f:
            f.write(b'#define rFoo $8001\r')
        main = os.path.join(d, 'main.r')
        with open(main, 'wb') as f:
            f.write(b'#include "mytypes.r"\rrFoo;\r')
        toks = lexer.tokenize(main, include_dirs=[inc_dir])[:-1]
    assert _kinds_values(toks) == [(lexer.NUMBER, 0x8001), (lexer.PUNCT, ';')]
    # the expanded token is charged to the includER's file/line (see the
    # module docstring), not to MyTypes.r where it was #defined.
    assert toks[0].file == main
    assert toks[0].line == 2


# --------------------------------------------------------------------------
# $"48 65" hex string, with embedded whitespace between byte-pairs
# --------------------------------------------------------------------------
def test_hex_string_with_embedded_whitespace():
    toks = _toks(b'$"48 65";\r')
    assert toks[0].kind == lexer.HEXSTRING
    assert toks[0].value == b'He'
    assert toks[0].text == '$"48 65"'


# --------------------------------------------------------------------------
# Numbers: $ hex, 0x hex, decimal, negative
# --------------------------------------------------------------------------
def test_numbers_hex_dollar_0x_decimal_negative():
    toks = _toks(b'$FF, 0xFF, 255, -1;\r')
    kv = _kinds_values(toks)
    assert kv[0] == (lexer.NUMBER, 255)
    assert kv[1] == (lexer.PUNCT, ',')
    assert kv[2] == (lexer.NUMBER, 255)
    assert kv[3] == (lexer.PUNCT, ',')
    assert kv[4] == (lexer.NUMBER, 255)
    assert kv[5] == (lexer.PUNCT, ',')
    # negative numbers are PUNCT('-') followed by a NUMBER (unary minus is
    # left for the parser; see the module docstring)
    assert kv[6] == (lexer.PUNCT, '-')
    assert kv[7] == (lexer.NUMBER, 1)
    assert kv[8] == (lexer.PUNCT, ';')


# --------------------------------------------------------------------------
# String with a MacRoman/high-byte character embedded (fixture 020's '≈' is
# MacRoman byte $C5, per tests/README.md; used here the same way)
# --------------------------------------------------------------------------
def test_string_with_macroman_high_byte():
    src = b'"Bad disk \xc5 label";\r'   # 0xC5 = MacRoman '\xe2\x89\x88'
    toks = _toks(src)
    assert toks[0].kind == lexer.STRING
    assert toks[0].value == b'Bad disk \xc5 label'


def test_adjacent_string_literals_stay_separate_tokens():
    # concatenation of adjacent literals is the parser's job, not the
    # lexer's (design-doc scope note)
    toks = _toks(b'"abc"\r"def";\r')
    assert _kinds_values(toks) == [
        (lexer.STRING, b'abc'), (lexer.STRING, b'def'), (lexer.PUNCT, ';'),
    ]


# --------------------------------------------------------------------------
# `$$Word(...)`-style field-reference tokens (discovered beyond the design
# doc's $$Word/$$Byte/$$Long list: the corpus also has $$CountOf,
# $$optionalCount, $$ArrayIndex, with inconsistent casing)
# --------------------------------------------------------------------------
def test_dollar_dollar_field_reference():
    toks = _toks(b'hex string[2*$$Word(height)];\r')
    values = [t.value for t in toks]
    assert '$$Word' in values


# --------------------------------------------------------------------------
# Zero ERROR tokens on well-formed input; an actually bad character does
# surface as one.
# --------------------------------------------------------------------------
def test_unrecognized_character_becomes_error_token_not_an_exception():
    toks = _toks(b'foo @ bar;\r')
    assert [(t.kind, t.value) for t in toks] == [
        (lexer.IDENT, 'foo'), (lexer.ERROR, '@'), (lexer.IDENT, 'bar'),
        (lexer.PUNCT, ';'),
    ]


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
