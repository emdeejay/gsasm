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

class Unresolved(Exception):
    """Raised when an expression references a symbol with no known value."""


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
                # MSB ON sets the high bit of each character (screen/hi-ASCII)
                val = (val << 8) | (ord(s[j]) | (0x80 if msb else 0)); j += 1
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


class _Parser:
    def __init__(self, toks, resolve, pc):
        self.t = toks
        self.i = 0
        self.resolve = resolve
        self.pc = pc

    def peek(self):
        return self.t[self.i]

    def next(self):
        tok = self.t[self.i]; self.i += 1; return tok

    def parse(self):
        v = self.cmp()
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
                # (e.g. -32767/2 = -16383), unlike Python's floor //
                self.next(); d = self.unary()
                q = abs(v) // abs(d) if d else 0
                v = -q if (v < 0) != (d < 0) else q
            elif t == '//' or t == ('kw', 'MOD'):
                self.next(); v = v % self.unary()
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
            if self.peek() == ')':
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
    """Evaluate `text` -> int. Raises Unresolved if a symbol/PC is unknown."""
    toks = tokenize(text.strip(), msb)
    return _Parser(toks, resolve, pc).parse()


def try_eval(text, resolve=lambda n: None, pc=None, msb=False):
    """Like evaluate but returns None instead of raising Unresolved."""
    try:
        return evaluate(text, resolve, pc, msb)
    except Unresolved:
        return None
