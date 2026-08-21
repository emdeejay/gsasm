"""Numeric expression evaluator for the MPW IIgs assembler dialect.

Used by both operand size-selection (pass 1) and the &EVAL macro builtin.
Symbol resolution is delegated to a callback `resolve(name) -> int | None`;
`*` resolves to the current location via `pc`.

Operators (high -> low precedence):
    unary  + - ~ (NOT)
    * / // (MOD)
    + -
    << >>
    **            bitwise AND
    ++  |         bitwise OR
    --            bitwise XOR
    = <> < > <= >=  (comparisons, yield 1/0)
    AND OR EOR    (keyword forms of the bitwise ops)
"""
from __future__ import annotations

class Unresolved(Exception):
    """Raised when an expression references a symbol with no known value."""


class BadExpression(Unresolved):
    """Raised when the expression TEXT is malformed, not merely unresolved.

    Deliberately a subclass of `Unresolved` so that every existing caller
    keeps its present behaviour: `try_eval` and the `except Unresolved` sites
    in asm.py/omf.py still see "no value available" and fall through to their
    fixup/defer paths rather than growing a second failure mode.  What the
    subclass buys is that `Asm.evaluate` can catch this narrower case FIRST
    and file a diagnostic in `a.errors` -- an undefined forward reference must
    stay silent (it is normal on pass 1), a syntactically broken operand
    must not.
    """


_TWO = ('<<', '>>', '**', '++', '--', '<>', '<=', '>=', '//')


def tokenize(s, msb=False):
    toks = []
    i, n = 0, len(s)
    while i < n:
        c = s[i]
        if c in ' \t':
            i += 1
            continue
        two = s[i:i+2]
        if two in _TWO:
            toks.append(two); i += 2; continue
        if c == '≈':          # '≈' = MPW AsmIIgs one's-complement operator
            toks.append('~'); i += 1; continue
        if c in '+-*/<>=()~|':
            toks.append(c); i += 1; continue
        if c == '$':
            j = i + 1
            while j < n and s[j] in '0123456789abcdefABCDEF':
                j += 1
            toks.append(('num', int(s[i+1:j] or '0', 16))); i = j; continue
        if c == '%':
            j = i + 1
            while j < n and s[j] in '01':
                j += 1
            toks.append(('num', int(s[i+1:j] or '0', 2))); i = j; continue
        if c == "'" or c == '"':
            # character constant: 'A' -> 65, multi-char packs big-endian. A
            # doubled quote inside is an escaped literal quote (`''''` -> one ').
            j = i + 1
            val = 0
            while j < n:
                if s[j] == c:
                    if j + 1 < n and s[j+1] == c:        # '' = escaped quote
                        j += 1
                    else:
                        break                            # closing quote
                # A character constant's value is the source BYTE, not the Unicode
                # code point.  gsasm reads sources as Mac Roman, so a high char like
                # '“' decodes to U+201C — `ord` would give 0x201C, but the assembler
                # must use the Mac Roman byte 0xD2 (GS.OS Init2 `pea '“'` pushes
                # $00D2).  Re-encode to recover the byte (identity for ASCII).
                try:
                    cb = s[j].encode('mac_roman')[0]
                except (UnicodeEncodeError, IndexError):
                    cb = ord(s[j]) & 0xFF
                # MSB ON sets the high bit of each character (screen/hi-ASCII)
                val = (val << 8) | (cb | (0x80 if msb else 0)); j += 1
            j += 1  # closing quote
            toks.append(('num', val)); i = j; continue
        if c.isdigit():
            j = i
            while j < n and s[j].isdigit():
                j += 1
            toks.append(('num', int(s[i:j]))); i = j; continue
        if _idstart(c):
            j = i
            while j < n and _idchar(s[j]):
                j += 1
            word = s[i:j]
            up = word.upper()
            if up in ('AND', 'OR', 'EOR', 'XOR', 'MOD', 'NOT', 'DIV'):
                toks.append(('kw', up))
            else:
                toks.append(('sym', word))
            i = j; continue
        # unknown char — stop (caller passes only expression text)
        raise Unresolved("bad expression char %r in %r" % (c, s))
    toks.append(('end', None))
    return toks


def _idstart(c):
    return c.isalpha() or c in '_~@?.'


def _idchar(c):
    # '$' is a hex prefix only at a term START (handled before _idstart in
    # tokenize); WITHIN a symbol it is a name character (MPW allows it, e.g.
    # the SCSI driver's `cmd_$8028` command-block labels).
    return c.isalnum() or c in '_~@?.$'


def _tokstr(tok):
    """Render a token for a diagnostic message."""
    if isinstance(tok, tuple):
        kind, val = tok
        if kind == 'end':
            return 'end of expression'
        if kind == 'num':
            return 'number %d' % val
        return '%s %r' % (kind, val)
    return 'operator %r' % (tok,)


class _Parser:
    def __init__(self, toks, resolve, pc, text=''):
        self.t = toks
        self.i = 0
        self.resolve = resolve
        self.pc = pc
        self.text = text          # original source text, for diagnostics only

    def peek(self):
        return self.t[self.i]

    def next(self):
        tok = self.t[self.i]; self.i += 1; return tok

    def parse(self):
        v = self.cmp()
        t = self.peek()
        if t != ('end', None):
            # The token stream must be fully consumed.  Without this check
            # `2 3` evaluated to 2, `5 BAR` to 5 and `1)` to 1 -- a malformed
            # operand silently produced the value of its first complete
            # subexpression instead of a diagnostic.
            #
            # DOCUMENTED: Asm Ref p.29, rules for writing expressions --
            # "An expression may not contain two terms or two operators
            # (other than parentheses) in succession."  Leftover tokens after
            # a complete expression are exactly that violation, so rejecting
            # them is the manual's rule, not a tightening of our own.
            raise BadExpression("trailing %s in expression %r"
                                % (_tokstr(t), self.text))
        return v

    def cmp(self):
        v = self.orlevel()
        while True:
            t = self.peek()
            if t in ('=', '<>', '<', '>', '<=', '>='):
                self.next(); r = self.orlevel()
                if t == '=':  v = 1 if v == r else 0
                elif t == '<>': v = 1 if v != r else 0
                elif t == '<':  v = 1 if v < r else 0
                elif t == '>':  v = 1 if v > r else 0
                elif t == '<=': v = 1 if v <= r else 0
                else:           v = 1 if v >= r else 0
            else:
                return v

    def orlevel(self):
        v = self.andlevel()
        while True:
            t = self.peek()
            if t in ('++', '|', '--') or t == ('kw', 'OR') or t == ('kw', 'EOR') or t == ('kw', 'XOR'):
                self.next()
                r = self.andlevel()
                if t == '--' or t in (('kw', 'EOR'), ('kw', 'XOR')):
                    v = v ^ r
                else:
                    v = v | r
            else:
                return v

    def andlevel(self):
        v = self.shift()
        while True:
            t = self.peek()
            if t == '**' or t == ('kw', 'AND'):
                self.next(); v = v & self.shift()
            else:
                return v

    def shift(self):
        v = self.add()
        while True:
            t = self.peek()
            if t == '<<':
                self.next(); v = v << self.add()
            elif t == '>>':
                self.next(); v = v >> self.add()
            else:
                return v

    def add(self):
        v = self.mul()
        while True:
            t = self.peek()
            if t == '+':
                self.next(); v = v + self.mul()
            elif t == '-':
                self.next(); v = v - self.mul()
            else:
                return v

    def mul(self):
        v = self.unary()
        while True:
            t = self.peek()
            if t == '*':
                self.next(); v = v * self.unary()
            elif t == '/' or t == ('kw', 'DIV'):
                # the MPW assembler truncates integer division toward zero
                # (e.g. -32767/2 = -16383), unlike Python's floor //.
                # DOCUMENTED: Asm Ref p.30, "Division always yields an integer
                # result; any fractional portion of the result is dropped."
                self.next(); d = self.unary()
                q = abs(v) // abs(d) if d else 0
                v = -q if (v < 0) != (d < 0) else q
            elif t == '//' or t == ('kw', 'MOD'):
                # MOD by zero yields 0, exactly as `/` does two branches up.
                # DOCUMENTED: Asm Ref p.30 "Division by 0 yields 0 as the
                # result", and the manual classes this operator as a division
                # -- Table 2-2 (p.29) labels `//` / MOD "Modulus division", as
                # does the index ("// (modulus division) 29, 148").  Before
                # this, `5 MOD 0` escaped as a raw Python ZeroDivisionError
                # that `try_eval` did not catch, so a malformed operand
                # crashed the assembler instead of producing a diagnostic.
                #
                # EMPIRICAL GAP, DELIBERATELY NOT "FIXED": the SIGN of a MOD
                # result stays Python's FLOORED `%`, so `-7 MOD 2` is 1 where
                # C-style (truncated) remainder would give -1, and `5//-3` is
                # -1 where C gives 2.  This is asymmetric with the truncating
                # `/` above, and the asymmetry is left in place on purpose:
                #   - `/`'s truncation is documented (Asm Ref p.30, quoted
                #     above).  The manual says NOTHING about the sign of a
                #     modulus result -- Table 2-2, the evaluation rules on
                #     p.30, and Appendix D's Table D-6 all name the operator
                #     and stop there.
                #   - The corpus cannot arbitrate either: all 22 MOD/`//`
                #     operator sites in the byte-exact tree (2026-08 sweep)
                #     use non-negative operands, so both definitions agree on
                #     every one of them.
                # Making MOD truncate "for consistency" would encode an
                # undocumented, untestable claim about Apple's assembler into
                # a byte-exact reproduction.  A documented asymmetry beats a
                # plausible guess; if a negative-operand MOD ever turns up in
                # a captured .lst, that listing decides it.
                self.next(); d = self.unary()
                v = v % d if d else 0
            else:
                return v

    def unary(self):
        t = self.peek()
        if t == '-':
            self.next(); return -self.unary()
        if t == '+':
            self.next(); return self.unary()
        if t == '~':
            self.next(); return ~self.unary()
        if t == ('kw', 'NOT'):
            # MPW NOT is LOGICAL (`if NOT Version6x` with Version6x=1 is
            # FALSE); the bitwise one's complement is the ≈ operator.
            self.next(); return 0 if self.unary() else 1
        return self.primary()

    def primary(self):
        t = self.next()
        if t == '(':
            v = self.cmp()
            if self.peek() != ')':
                # `(1+2` used to evaluate to 3: the missing ')' was simply not
                # consumed.  Asm Ref p.29: "Subexpressions are designated by
                # enclosing the subexpression in parentheses" -- an unclosed
                # one is not a subexpression.
                raise BadExpression("missing ')' in expression %r" % (self.text,))
            self.next()
            return v
        if t == '*':
            if self.pc is None:
                raise Unresolved("'*' used with no location")
            return self.pc
        if isinstance(t, tuple):
            kind, val = t
            if kind == 'num':
                return val
            if kind == 'sym':
                r = self.resolve(val)
                if r is None:
                    raise Unresolved("undefined symbol %r" % val)
                return r
        raise Unresolved("unexpected token %r" % (t,))


def evaluate(text, resolve=lambda n: None, pc=None, msb=False):
    """Evaluate `text` -> int.

    Raises `Unresolved` if a symbol/PC is unknown, and its subclass
    `BadExpression` if the text is malformed (leftover tokens, unclosed
    parenthesis).  Callers that only want a value use `try_eval`; callers
    that want a diagnostic (`Asm.evaluate`) catch `BadExpression` first.
    """
    src = text.strip()
    toks = tokenize(src, msb)
    return _Parser(toks, resolve, pc, src).parse()


def try_eval(text, resolve=lambda n: None, pc=None, msb=False):
    """Like evaluate but returns None instead of raising Unresolved.

    `BadExpression` is an `Unresolved` subclass, so a malformed expression
    also returns None here -- probing callers (omf.py's relocation
    classifiers) must not have to grow a second exception handler.
    """
    try:
        return evaluate(text, resolve, pc, msb)
    except Unresolved:
        return None
