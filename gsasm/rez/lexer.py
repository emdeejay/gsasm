r"""Rez preprocessor + lexer (work packet R3).

Turns a `.r` source file, plus everything it `#include`s, into a single flat
list of `Token`s for packet R4's recursive-descent parser to consume.  This
module owns two jobs that a real Rez/DeRez toolchain also fuses together:
a small C-style preprocessor (`#include`, `#define`, `#if`/`#elif`/`#else`/
`#endif`/`#ifdef`/`#ifndef`) and the lexical scan of what's left (numbers,
strings, hex-strings, identifiers, punctuation).

Scope is deliberately the subset the two corpus files under `work/` exercise
(see `docs/design/rez.md` packet R3); grow it via `work/rezlexcheck.py`
discoveries the same way `tests/` grows AsmIIgs fixtures.

Source encoding
----------------
Rez sources are read as raw bytes and decoded 1:1 with latin-1 (never
`mac_roman`/utf-8): a byte value must round-trip unchanged so that string
literals carrying non-ASCII bytes (MacRoman high bytes, or — as observed in
the `Sys.Resources` working copy — raw UTF-8 sequences) pass through
verbatim.  Nothing after the raw byte read ever re-encodes text; identifier/
number/punctuation recognition only look at the ASCII subset, so arbitrary
high bytes are inert everywhere they can legally occur (inside string and
hex-string literals).

Line endings: CR (classic Mac), CRLF, and bare LF are all accepted and
normalized to `\n` before anything else happens (this never touches bytes
inside a line, only the terminators between lines). A backslash immediately
followed by a line terminator is
a C-style continuation: the backslash and the terminator are both deleted
and the two physical lines become one logical line (this is what lets
`TypesIIGS.r`'s multi-line `#define Region verUS, verFrance, ... verThailand`
work) — matching real cpp behavior, no whitespace is inserted at the splice
point.

Token shape (the contract packet R4 builds on)
-----------------------------------------------
`tokenize(path, include_dirs)` returns a flat `list[Token]` ending in one
`Token(kind=EOF)`.  Each `Token` has exactly these fields:

    kind   one of the module-level kind constants: IDENT, NUMBER, STRING,
           HEXSTRING, PUNCT, EOF, ERROR.
    value  kind-specific decoded payload (see below).
    text   the verbatim source text the token was scanned from (quotes/`$`/
           `0x` prefixes included). For a token that arrived via macro
           expansion, `text` is still the *replacement-list* token's own
           original text (i.e. what appeared after the `#define`), not the
           invocation site's text.
    file   path of the source file charged for this token's location. For
           an expanded macro token this is the *invocation* site's file
           (not the `#define`'s file) — the useful choice for diagnostics
           tied to the resource being compiled.
    line   1-based physical source line, post backslash-continuation
           splicing, charged the same way as `file` above.

Per kind, `value` is:
    IDENT      the identifier text, case preserved (case-sensitivity
               decisions belong to the parser).
    NUMBER     a plain `int`. Sign is never folded in here — a Rez
               `-1` is the two tokens PUNCT('-'), NUMBER(1); the radix
               the literal was written in (if the parser cares) can be
               read back off `text[:1] in '$'` / `text[:2].lower()=='0x'`
               / `text[:2].lower()=='0b'` (decimal, `$hex`, `0xhex`, and
               `0b`-binary are the four numeric forms the corpus uses).
    STRING     `bytes`: the RAW, UNDECODED content between the double
               quotes (backslash escapes, `\$XX` hex-byte escapes, `\n`,
               etc. included verbatim) — escape *decoding* is left to a
               later phase (R4/R5), per design-doc scope. A backslash still
               escapes the following character for the purpose of finding
               the closing quote (so `\"` doesn't end the literal early),
               it just isn't interpreted.
    HEXSTRING  `bytes`: the DECODED byte string a `$"..."` literal denotes
               (whitespace between byte-pairs is allowed and already
               stripped, since there's no escape ambiguity to defer here).
    PUNCT      the single punctuation character, as a length-1 `str`.
    EOF        `None`.
    ERROR      the single offending character (`str`) that didn't match any
               token grammar; scanning continues past it. A well-formed
               corpus file must produce zero of these — `rezlexcheck.py`
               asserts that.

There is no separate token for macro-expanded text: expansion happens
before a token is ever appended to the output stream, so R4 never sees a
macro name it needs to look up — by the time it sees the stream, `rIcon`
usages have already become `NUMBER($8001)`.  Newlines and comments are
trivia consumed entirely within this module; they never appear as tokens
in the returned list.
"""

import os

# --------------------------------------------------------------------------
# Token kinds
# --------------------------------------------------------------------------
IDENT = 'IDENT'
NUMBER = 'NUMBER'
STRING = 'STRING'
HEXSTRING = 'HEXSTRING'
PUNCT = 'PUNCT'
EOF = 'EOF'
ERROR = 'ERROR'

# Internal-only kind: a bare, uncommented, unspliced newline. Used to find
# preprocessor-directive line boundaries; never appears in tokenize()'s
# returned list.
_NEWLINE = 'NEWLINE'

# Punctuation the corpus (TypesIIGS.r + sys.resources.r) actually contains,
# scanned as single-character tokens: '{ } ( ) [ ] ; , : = * + -  /  # !'.
# '#' only ever appears as a directive introducer (consumed by the
# preprocessor) and '!' only inside a `#if` expression, but both are cheap
# to recognize uniformly here; anything else falls through to ERROR.
_PUNCT_CHARS = '(){}[];,:=*+-/#!'

_HEXDIGITS = '0123456789abcdefABCDEF'


class Token:
    """One lexical token; see the module docstring for the field contract."""
    __slots__ = ('kind', 'value', 'text', 'file', 'line')

    def __init__(self, kind, value, text, file, line):
        self.kind = kind
        self.value = value
        self.text = text
        self.file = file
        self.line = line

    def __repr__(self):
        return f"Token({self.kind}, {self.value!r}, {self.file}:{self.line})"


class LexError(Exception):
    """Fatal, unrecoverable preprocessing/lexing failure (unterminated
    string/comment/#if, missing #include file, malformed hex-string, ...).
    Message is pre-formatted with `file:line:`."""


# --------------------------------------------------------------------------
# Stage 1+2: line-ending normalization + backslash-continuation splicing
# --------------------------------------------------------------------------
def _splice_continuations(data):
    """bytes -> (text, charlines).

    `text` is `data` with CR/CRLF/LF all normalized to `\\n` and every
    backslash-newline pair deleted (line splicing); `charlines` is a
    parallel list giving the 1-based *original* physical source line each
    character of `text` came from.
    """
    data = data.replace(b'\r\n', b'\n').replace(b'\r', b'\n')
    out = bytearray()
    charlines = []
    line = 1
    i, n = 0, len(data)
    while i < n:
        b = data[i]
        if b == 0x5C and i + 1 < n and data[i + 1] == 0x0A:  # '\' + '\n'
            line += 1
            i += 2
            continue
        out.append(b)
        charlines.append(line)
        if b == 0x0A:
            line += 1
        i += 1
    return out.decode('latin-1'), charlines


# --------------------------------------------------------------------------
# Stage 3: raw tokenizer (comments are trivia; strings/hex-strings/numbers/
# identifiers/punctuation become Tokens; bare newlines become _NEWLINE
# markers the preprocessor uses to find directive-line boundaries)
# --------------------------------------------------------------------------
def _raw_tokenize(text, charlines, filename):
    toks = []
    n = len(text)

    def line_at(pos):
        if not charlines:
            return 1
        return charlines[pos] if pos < n else charlines[-1]

    i = 0
    while i < n:
        c = text[i]

        if c in ' \t\f\v':
            i += 1
            continue

        if c == '\n':
            toks.append(Token(_NEWLINE, None, '\n', filename, line_at(i)))
            i += 1
            continue

        if c == '/' and i + 1 < n and text[i + 1] == '*':
            start_line = line_at(i)
            j = text.find('*/', i + 2)
            if j == -1:
                raise LexError(f"{filename}:{start_line}: unterminated /* comment")
            i = j + 2
            continue

        if c == '/' and i + 1 < n and text[i + 1] == '/':
            j = text.find('\n', i + 2)
            i = n if j == -1 else j
            continue

        if c == '"':
            start, start_line = i, line_at(i)
            i += 1
            buf_start = i
            while True:
                if i >= n or text[i] == '\n':
                    raise LexError(f"{filename}:{start_line}: unterminated string literal")
                if text[i] == '\\' and i + 1 < n and text[i + 1] != '\n':
                    i += 2
                    continue
                if text[i] == '"':
                    break
                i += 1
            content = text[buf_start:i]
            i += 1  # closing quote
            raw = text[start:i]
            toks.append(Token(STRING, content.encode('latin-1'), raw, filename, start_line))
            continue

        if c == '$' and i + 1 < n and text[i + 1] == '"':
            start, start_line = i, line_at(i)
            i += 2
            buf_start = i
            while True:
                if i >= n or text[i] == '\n':
                    raise LexError(f"{filename}:{start_line}: unterminated hex string")
                if text[i] == '"':
                    break
                i += 1
            digits = text[buf_start:i]
            i += 1  # closing quote
            raw = text[start:i]
            try:
                value = bytes.fromhex(digits)
            except ValueError as exc:
                raise LexError(f"{filename}:{start_line}: malformed hex string {raw!r}: {exc}")
            toks.append(Token(HEXSTRING, value, raw, filename, start_line))
            continue

        # `$$Word(...)`, `$$CountOf(...)`, `$$ArrayIndex(...)`, ... — Rez's
        # field-reference/meta-function syntax (design-doc: "$$Word/$$Byte/
        # $$Long field references"; the corpus also uses $$CountOf,
        # $$optionalCount and $$ArrayIndex, all seen with inconsistent
        # casing, e.g. both `$$Countof` and `$$countOf` — so this is lexed
        # as one opaque identifier token carrying both dollar signs
        # (`$$Word`, `$$countOf`, ...) and left for the parser to match
        # case-insensitively against its builtin-function table).
        if c == '$' and i + 1 < n and text[i + 1] == '$':
            start, start_line = i, line_at(i)
            j = i + 2
            while j < n and (text[j].isalnum() or text[j] == '_'):
                j += 1
            raw = text[start:j]
            toks.append(Token(IDENT, raw, raw, filename, start_line))
            i = j
            continue

        if c == '$':
            start, start_line = i, line_at(i)
            j = i + 1
            while j < n and text[j] in _HEXDIGITS:
                j += 1
            if j == i + 1:
                toks.append(Token(ERROR, c, c, filename, start_line))
                i += 1
                continue
            raw = text[start:j]
            toks.append(Token(NUMBER, int(raw[1:], 16), raw, filename, start_line))
            i = j
            continue

        if (c == '0' and i + 2 < n and text[i + 1] in 'xX'
                and text[i + 2] in _HEXDIGITS):
            start, start_line = i, line_at(i)
            j = i + 2
            while j < n and text[j] in _HEXDIGITS:
                j += 1
            raw = text[start:j]
            toks.append(Token(NUMBER, int(raw[2:], 16), raw, filename, start_line))
            i = j
            continue

        # `0b…`/`0B…` binary integer literal (e.g. `0b0000111100000000`,
        # used by rWindColor resources in the sys.resources.r corpus).  Not
        # called out in the R3 design-doc scope note alongside `$…`/`0x…`/
        # decimal, so this was a genuine gap: without it, `0b0000...1111`
        # silently mis-tokenized as NUMBER(0) followed by a bogus IDENT
        # `b0000...1111` (both '0' and 'b' individually scan fine, so no
        # ERROR token was ever produced to flag it).
        if (c == '0' and i + 2 < n and text[i + 1] in 'bB'
                and text[i + 2] in '01'):
            start, start_line = i, line_at(i)
            j = i + 2
            while j < n and text[j] in '01':
                j += 1
            raw = text[start:j]
            toks.append(Token(NUMBER, int(raw[2:], 2), raw, filename, start_line))
            i = j
            continue

        if c.isdigit():
            start, start_line = i, line_at(i)
            j = i
            while j < n and text[j].isdigit():
                j += 1
            raw = text[start:j]
            toks.append(Token(NUMBER, int(raw, 10), raw, filename, start_line))
            i = j
            continue

        if c.isalpha() or c == '_':
            start, start_line = i, line_at(i)
            j = i
            while j < n and (text[j].isalnum() or text[j] == '_'):
                j += 1
            raw = text[start:j]
            toks.append(Token(IDENT, raw, raw, filename, start_line))
            i = j
            continue

        if c in _PUNCT_CHARS:
            toks.append(Token(PUNCT, c, c, filename, line_at(i)))
            i += 1
            continue

        # Unrecognized character: emit an ERROR token (rather than raising)
        # so a caller can collect every problem area in one pass, then
        # resume scanning right after it.
        toks.append(Token(ERROR, c, c, filename, line_at(i)))
        i += 1

    toks.append(Token(EOF, None, '', filename, line_at(n - 1) if n else 1))
    return toks


def _raw_tokenize_file(path):
    with open(path, 'rb') as f:
        data = f.read()
    text, charlines = _splice_continuations(data)
    return _raw_tokenize(text, charlines, path)


# --------------------------------------------------------------------------
# Stage 4: preprocessor (macro table, #include, conditionals) — a single
# left-to-right walk so that `#define`/`#if` visibility is correctly
# forward-only, matching real cpp semantics.
# --------------------------------------------------------------------------
class _CondFrame:
    __slots__ = ('active', 'taken', 'file', 'line')

    def __init__(self, active, taken, file, line):
        self.active = active   # is *this* branch currently the live one
        self.taken = taken     # has any branch in this #if..#endif group fired
        self.file = file
        self.line = line


class _Preprocessor:
    def __init__(self, include_dirs, predefined=None):
        self.include_dirs = list(include_dirs or [])
        self.macros = {}        # name -> list[Token] (replacement list, unexpanded)
        if predefined:
            # Seed the macro table exactly as `#define NAME <int>` would, so
            # `#if NAME == ...` conditionals see it. Needed for packet R5
            # (gsasm/rez/gen.py): the real RezIIgs tool predefines `RezIIGS`
            # (as opposed to DeRezIIGS) so that `#if RezIIGS == 1` guards in
            # TypesIIGS.r — which gate the null-longint array terminator in
            # rControlList/rMenu/rMenuBar — fire; this parser has no other
            # way to express that predefined-macro fact since `tokenize()`
            # only ever sees one source file's own `#define`s. Confirmed
            # required by byte-comparing generated rControlList/rMenu data
            # against the golden Sys.Resources fork (both are 4 bytes
            # short — missing the trailing `longint = 0;` — without it).
            for name, value in predefined.items():
                tok = Token(NUMBER, value, str(value), '<predefined>', 0)
                self.macros[name] = [tok]
        self.output = []
        self._include_depth = 0

    def run(self, path):
        self._process_file(path)
        return self.output

    # -- macro expansion, shared by the main stream and #if expressions ----
    def _expand_tokens(self, tokens, active):
        out = []
        for t in tokens:
            if t.kind == IDENT and t.value in self.macros and t.value not in active:
                body = self.macros[t.value]
                # Retag with the invocation site's location (see module
                # docstring: expanded tokens are charged to where they're
                # used, not where the macro was #defined).
                retagged = [Token(b.kind, b.value, b.text, t.file, t.line) for b in body]
                out.extend(self._expand_tokens(retagged, active | {t.value}))
            else:
                out.append(t)
        return out

    # -- #include resolution (case-insensitive filename match) -------------
    def _resolve_include(self, name, cur_dir):
        lname = name.lower()
        for d in [cur_dir] + self.include_dirs:
            if not d:
                continue
            try:
                entries = os.listdir(d)
            except OSError:
                continue
            for e in entries:
                if e.lower() == lname:
                    return os.path.join(d, e)
        return None

    # -- one source file: raw-tokenize, then walk left to right ------------
    def _process_file(self, path):
        self._include_depth += 1
        if self._include_depth > 50:
            raise LexError(f"{path}: #include nested too deeply (possible cycle)")
        toks = _raw_tokenize_file(path)
        n = len(toks)
        stack = []
        at_line_start = True
        i = 0
        while i < n:
            t = toks[i]
            if t.kind == _NEWLINE:
                at_line_start = True
                i += 1
                continue
            if t.kind == EOF:
                break
            if at_line_start and t.kind == PUNCT and t.value == '#':
                i += 1
                if i >= n or toks[i].kind != IDENT:
                    raise LexError(f"{path}:{t.line}: '#' not followed by a directive name")
                dname = toks[i].value.lower()
                dline = t.line
                i += 1
                args = []
                while i < n and toks[i].kind not in (_NEWLINE, EOF):
                    args.append(toks[i])
                    i += 1
                self._directive(dname, args, path, dline, stack)
                at_line_start = True
                continue
            at_line_start = False
            if self._enabled(stack):
                self.output.extend(self._expand_tokens([t], frozenset()))
            i += 1
        if stack:
            top = stack[-1]
            raise LexError(f"{path}: #if opened at line {top.line} has no matching #endif")
        self._include_depth -= 1

    @staticmethod
    def _enabled(stack):
        return all(f.active for f in stack)

    # -- directive dispatch --------------------------------------------------
    def _directive(self, name, args, path, dline, stack):
        enabled = self._enabled(stack)

        if name == 'include':
            if not enabled:
                return
            if not args or args[0].kind != STRING:
                raise LexError(f"{path}:{dline}: #include expects a quoted filename")
            fname = args[0].value.decode('latin-1')
            resolved = self._resolve_include(fname, os.path.dirname(path))
            if resolved is None:
                raise LexError(f"{path}:{dline}: #include file not found "
                                f"(case-insensitively) in search path: {fname!r}")
            self._process_file(resolved)
            return

        if name == 'define':
            if not enabled:
                return
            if not args or args[0].kind != IDENT:
                raise LexError(f"{path}:{dline}: #define expects a macro name")
            self.macros[args[0].value] = args[1:]
            return

        if name in ('if', 'ifdef', 'ifndef'):
            if not enabled:
                cond = False
            elif name == 'if':
                cond = bool(self._eval_expr(args, path, dline))
            else:
                target = self._single_ident(args, path, dline)
                cond = (target in self.macros) == (name == 'ifdef')
            stack.append(_CondFrame(active=cond, taken=cond, file=path, line=dline))
            return

        if name == 'elif':
            if not stack:
                raise LexError(f"{path}:{dline}: #elif without an opening #if")
            frame = stack[-1]
            parent_enabled = all(f.active for f in stack[:-1])
            if not parent_enabled or frame.taken:
                frame.active = False
            else:
                frame.active = bool(self._eval_expr(args, path, dline))
                frame.taken = frame.taken or frame.active
            return

        if name == 'else':
            if not stack:
                raise LexError(f"{path}:{dline}: #else without an opening #if")
            frame = stack[-1]
            parent_enabled = all(f.active for f in stack[:-1])
            frame.active = parent_enabled and not frame.taken
            frame.taken = True
            return

        if name == 'endif':
            if not stack:
                raise LexError(f"{path}:{dline}: #endif without an opening #if")
            stack.pop()
            return

        raise LexError(f"{path}:{dline}: unsupported preprocessor directive #{name}")

    def _single_ident(self, args, path, dline):
        if len(args) != 1 or args[0].kind != IDENT:
            raise LexError(f"{path}:{dline}: expected a single macro name")
        return args[0].value

    # -- '#if'/'#elif' expression evaluation: defined(NAME)/defined NAME,
    #    '!', '==', integer/hex literals, macro-valued identifiers;
    #    an identifier that isn't a defined, single-NUMBER macro is 0
    #    (C-style: undefined names in #if expressions evaluate as 0). ----
    def _eval_expr(self, args, path, dline):
        p = _ExprParser(args, self, path, dline)
        v = p.parse()
        p.expect_end()
        return v


class _ExprParser:
    def __init__(self, toks, pp, path, dline):
        self.toks = toks
        self.pp = pp
        self.path = path
        self.dline = dline
        self.i = 0

    def _peek(self):
        return self.toks[self.i] if self.i < len(self.toks) else None

    def _advance(self):
        t = self.toks[self.i]
        self.i += 1
        return t

    def parse(self):
        return self._equality()

    def _equality(self):
        v = self._unary()
        while True:
            t = self._peek()
            if (t is not None and t.kind == PUNCT and t.value == '='
                    and self.i + 1 < len(self.toks)
                    and self.toks[self.i + 1].kind == PUNCT
                    and self.toks[self.i + 1].value == '='):
                self._advance(); self._advance()
                v = 1 if v == self._unary() else 0
            else:
                return v

    def _unary(self):
        t = self._peek()
        if t is not None and t.kind == PUNCT and t.value == '!':
            self._advance()
            return 0 if self._unary() else 1
        return self._primary()

    def _primary(self):
        t = self._peek()
        if t is None:
            raise LexError(f"{self.path}:{self.dline}: incomplete #if expression")
        if t.kind == NUMBER:
            self._advance()
            return t.value
        if t.kind == PUNCT and t.value == '(':
            self._advance()
            v = self._equality()
            self._expect_punct(')')
            return v
        if t.kind == IDENT and t.value == 'defined':
            self._advance()
            has_paren = (self._peek() is not None and self._peek().kind == PUNCT
                         and self._peek().value == '(')
            if has_paren:
                self._advance()
                name = self._expect_ident()
                self._expect_punct(')')
            else:
                name = self._expect_ident()
            return 1 if name in self.pp.macros else 0
        if t.kind == IDENT:
            self._advance()
            body = self.pp.macros.get(t.value)
            if body is None:
                return 0
            expanded = self.pp._expand_tokens(body, frozenset({t.value}))
            if len(expanded) == 1 and expanded[0].kind == NUMBER:
                return expanded[0].value
            return 0
        raise LexError(f"{self.path}:{self.dline}: unexpected token in "
                        f"#if expression: {t.text!r}")

    def _expect_ident(self):
        t = self._peek()
        if t is None or t.kind != IDENT:
            raise LexError(f"{self.path}:{self.dline}: expected an identifier "
                            f"in #if expression")
        self._advance()
        return t.value

    def _expect_punct(self, ch):
        t = self._peek()
        if t is None or t.kind != PUNCT or t.value != ch:
            raise LexError(f"{self.path}:{self.dline}: expected {ch!r} in "
                            f"#if expression")
        self._advance()

    def expect_end(self):
        if self.i != len(self.toks):
            t = self.toks[self.i]
            raise LexError(f"{self.path}:{self.dline}: unexpected trailing "
                            f"token in #if expression: {t.text!r}")


# --------------------------------------------------------------------------
# Public entry point
# --------------------------------------------------------------------------
def tokenize(path, include_dirs=None, predefined=None):
    """Preprocess and tokenize `path` (plus everything it `#include`s).

    `include_dirs` is a list of directories searched (in order, after the
    including file's own directory) for `#include "name"`; matching is
    case-insensitive. Returns a flat `list[Token]` ending with one
    `Token(kind=EOF)`; see the module docstring for the token field
    contract. Raises `LexError` on anything unrecoverable (unterminated
    string/comment/#if, an unresolvable `#include`, a malformed hex
    string). A single unrecognized character does *not* raise — it becomes
    an `ERROR`-kind token so a caller can collect every such spot in one
    pass (a well-formed file should produce zero of them).

    `predefined`: optional `{macro_name: int}` mapping seeded into the
    macro table before any file is read, as if each were `#define NAME
    <int>` on an invisible line before `path`. Default `None` (no
    predefined macros) preserves prior behavior exactly for every existing
    caller. See `_Preprocessor.__init__` for why packet R5 needs this
    (`RezIIGS` must be predefined truthy, mirroring the real Rez tool).
    """
    pp = _Preprocessor(include_dirs, predefined=predefined)
    pp.run(path)
    last_line = pp.output[-1].line if pp.output else 1
    pp.output.append(Token(EOF, None, '', path, last_line))
    return pp.output
