r"""Rez recursive-descent parser (work packet R4).

Turns the flat `Token` stream `gsasm/rez/lexer.py` (packet R3) produces into a
full-fidelity AST for packet R5 (the data generator) to walk.  Scope is,
again, exactly the subset of Rez grammar the two corpus files exercise (see
`docs/design/rez.md` packet R4); every construct below was confirmed present
in `work/rincludes/TypesIIGS.r` and
`ref/GSOS_6/IIGS.601.SRC/GSToolbox/Sys.Resources/sys.resources.r` by reading
both files end to end, not guessed from the general Rez language.

Public API
----------
    parse(path, include_dirs=None) -> list[Statement]

Tokenizes+preprocesses `path` (via `lexer.tokenize`, so `#include`/`#define`/
`#if` have already run and macro names never reach this module — a macro
like `rIcon` or `rMyCursor` arrives as `NUMBER(0x8001)`/`NUMBER(0x8027)`
before the parser ever sees it) and parses the result into a flat
`list[Statement]` **in source order** (R5 needs source order to lay out
resource data the way the golden fork does — see design-doc "Golden fork
format" notes: resource data is contiguous in *source-statement* order, not
index order). Raises `ParseError` (message pre-formatted `file:line: ...`)
on malformed input.

Case sensitivity
----------------
Every Rez keyword this module recognizes (`type`/`resource`/`read`, field
type keywords, modifiers, `array`/`switch`/`case`/`key`/`optional`/`fill`/
`align`/`wide`) is matched **case-insensitively** — the corpus mixes casing
freely (`integer`/`Integer`, `string`/`String`, `rect`/`Rect`, `longint`/
`LongInt`, `array`/`Array`, `key`/`Key`, and the `$$Word`/`$$CountOf`/
`$$countOf` family lexer already folds to opaque IDENT text but which this
module also matches case-insensitively). Identifiers that are *not*
keywords (type/field/case/symbolic-constant names) keep their original
case — case sensitivity for *those* is a semantic question R5 owns.

AST shape
=========
Every node is a `dataclasses.dataclass` and carries `file`/`line` (the
statement/token it started at) for error reporting, following the
`Node` base class below. Fields use plain Python containers (`list`,
`Optional`, `int`, `str`, `bytes`) — no cross-references or symbol
resolution happen here; R5 walks the tree with its own type-name/symbol
tables.

Top level
---------
    Statement = TypeDecl | ResourceStmt | ReadStmt

    TypeDecl(typeid, id_range, fields)
        `type <typeid> [(<first>[, <second>])] { <fields> };`
        typeid    int (post-macro NUMBER, the overwhelmingly common case
                  in this corpus — every type name in both corpus files
                  is `#define`d) or str (a literal, never-`#define`d IDENT;
                  supported because the design doc calls it out, even
                  though the corpus never exercises it).
        id_range  None, or (first_expr, second_expr_or_None) for the
                  `(<id-range/specific-id>)` suffix — grammar-supported
                  per the design doc; NOT exercised anywhere in either
                  corpus file (no `type` declaration there is followed by
                  parentheses), so this is speculative/forward-looking.
        fields    list[Field] (see "Fields" below).

    ResourceStmt(typeid, id, name, attrs, values)
        `resource <typeid> (<id>[, "<name>"][, <attrs>...]) { <values> };`
        typeid  same shape as TypeDecl.typeid.
        id      Expr (almost always a Num after macro expansion; kept as
                a general Expr for robustness).
        name    Optional[bytes]: the concatenated raw bytes of the name
                string, when the 2nd header argument is a STRING literal
                (must be the *first* comma-separated argument after `id`;
                that's the only position the corpus ever uses it in).
        attrs   list[Expr]: remaining header arguments — bare identifiers
                (`locked`, `fixed`, `preload`, `nospecialmemory`,
                `Convert`, ...) parse as `Name`, bare numeric attributes
                (e.g. `$8000`) parse as `Num`. RezIIgs attribute keywords
                are not resolved to their bit values here (design-doc:
                "Attribute keywords are RezIIgs built-ins" — that mapping
                is R5/emit's job).
        values  list[Value] (see "Values" below) — the resource's data,
                comma/semicolon-separated (see note on separators below).

    ReadStmt(typeid, id, name, attrs, filename)
        `read <typeid> (<id>[, <attrs>...]) "<filename>";`
        Same header shape as ResourceStmt (name is supported for
        generality but the corpus's 4 `read` statements never use it).
        filename  bytes: concatenated raw string bytes (a filename could
                  in principle be split across adjacent STRING literals
                  the same way any other Rez string can; none in the
                  corpus are, but the run is parsed generically anyway).

Value-list separators (`,` vs `;`) — a corpus quirk
----------------------------------------------------
Rez value lists (a resource body, or any nested `{ ... }` group value)
are documented as comma-separated with no trailing comma before the
closing `}`. The corpus doesn't actually follow that cleanly: in >10
places (e.g. `rMenu`'s trailing `{ $07ff1001, $07ff1002 };` array, or
every `rIcon`'s final `mask` hex-string run, or `rControlList`'s nested
`{ CTLTMP_... , ... , };`) the **last** value in a list is followed by a
stray `;` before the list's closing `}`, in addition to the resource
statement's own mandatory closing `};`. Rather than special-case this,
`parse_value_list` treats `,` and `;` as fully interchangeable list
separators, with an optional trailing separator absorbed right before
`}` — this parses every observed form (plain trailing comma, plain
comma-separated with no trailing separator, and this "trailing
semicolon before `}`" pattern) uniformly with no ambiguity, since `}`
can never itself start a value.

Values (resource/array data — inside a `resource`/`read` body or any
nested `{ ... }` group)
----------------------------------------------------------------------
    Value = Expr | StrLit | HexLit | GroupValue | CaseValue

    StrLit(value: bytes)
        One or more adjacent STRING tokens, concatenated (raw bytes,
        still undecoded per the lexer contract — escape decoding is
        R5's job).
    HexLit(value: bytes)
        One or more adjacent HEXSTRING tokens, concatenated (already
        decoded to bytes by the lexer).
    GroupValue(values: list[Value])
        A bare `{ <values> }` — a nested array/struct literal, e.g. the
        `{ 6,0,1,release,$00 }` ReverseBytes-group value in `rVersion(1)`,
        or `rControlTemplate`'s `{ 6, 92, 46, 405}` rect value.
    CaseValue(name: str, values: list[Value])
        `<IDENT> { <values> }` immediately adjacent (no token between
        the identifier and `{`) — selects a `switch` case in the
        resource's type template by name and supplies that case's own
        (nested) value list, e.g. `statTextControl {{ $0003, $1002, ...
        }}` (outer `{}` from this construct, inner `{}` from the case's
        own `optional Fields {...}` group — hence the doubled brace).
        The name is stored uninterpreted; matching it against the
        type's declared `case` names is R5's job.

Fields (inside a `type` body, or any nested field-list: `array`/
`optional`/`switch case`/a bare named group)
----------------------------------------------------------------------
    Field = Label | TypedField | ArrayField | OptionalField
          | SwitchField | GroupField | FillField | AlignField

    Label(name: str)
        A bare `<ident>:` marker (e.g. `height:`, `mask:`, `end:`).
        Labels attach to whatever field follows (their declared name
        becomes usable in `$$Word(name)`/`name[$$ArrayIndex(...)]`-style
        expressions elsewhere in the same type), but a label need not be
        followed by anything — `end:` in `rBundle` sits immediately
        before the enclosing array's closing `}` with no field after it
        at all, so `Label` is its own field-list entry, not a wrapper
        around the next field.

    TypedField(key, modifiers, basetype, size, default, named_values)
        A single scalar/sized field: `[key] [modifier...] basetype
        [[size]] ( = default | namelist )? ;`
        key            bool: `key` prefix present (marks a `switch`
                       case's discriminator field, e.g.
                       `key integer = 0;`).
        modifiers      list[str], lowercased, in source order — every
                       modifier keyword seen before `basetype`. Corpus
                       only ever uses `hex` and `unsigned` (in either
                       order, e.g. `unsigned hex word` -> `integer`
                       post-macro); `binary`/`literal`/`decimal`/`octal`
                       are accepted too (real-Rez radix/display
                       modifiers the design doc calls out) even though
                       unused here — R5 decides what (if anything) they
                       affect.
        basetype       str, lowercased: one of `byte`, `integer`,
                       `longint`, `word` (kept as an accepted synonym
                       for forward-compat/hand tests, even though the
                       corpus's own `#define word integer` means the
                       literal token `word` never actually reaches this
                       module), `char`, `boolean` (accepted per the
                       design doc; never actually used in the corpus —
                       see the R4 packet report), `string`, `pstring`,
                       `cstring`, `wstring`, `point`, `rect`, `bitstring`.
        size           Optional[Expr]: the `[expr]` suffix, when present
                       (sized strings `string[2*$$Word(h)*$$Word(w)]`,
                       fixed pstrings `pstring[15]`, bitfield widths
                       `bitstring[6]`/`bitstring[4]`). None otherwise.
        default        Optional[Expr]: a bare `= expr` default, when
                       given with no named-value list (`longint = 0;`,
                       `integer = $$Countof(StringArray);`).
        named_values   list[NamedValue]: a comma-separated
                       `name (= expr)?` list, when the field declares
                       symbolic value names instead of/alongside a bare
                       default (`integer leftJust, centerJust, fullJust,
                       rightJust = -1;` — only the last name has an
                       explicit value; `hex byte development = 0x20,
                       alpha = 0x40, ..., release = 0xA0;` — every name
                       explicit; `longint behind=0, infront=-1;`).
                       Mutually exclusive with `default` (a field has at
                       most one of the two; both empty/None means a
                       plain field with no default at all, e.g.
                       `integer;`). Each `NamedValue.value` is `None`
                       when that particular name has no explicit `=`
                       expr — real Rez then resolves it C-enum-style
                       (0, incrementing, reset by the previous explicit
                       value); R4 does not compute this, only preserves
                       the (name, expr-or-None) pairs in declaration
                       order for R5 to resolve. (`#define Region
                       verUS, verFrance, ..., verFrBelgiumLux = 6, ...`
                       in TypesIIGS.r expands, by the time this module
                       sees it, into exactly this same shape: a bare
                       `integer` field followed by a long named-value
                       list with occasional explicit resets — no special
                       handling needed for it at all.)

    ArrayField(wide, name, bound, fields)
        `wide? array <name>? ([<bound>])? { <fields> } ;`
        wide    bool: `wide` prefix present (affects the on-disk
                element-count field's width per real Rez; irrelevant to
                this module's structure).
        name    Optional[str]: the array's name, when given (needed for
                `$$Countof(name)`/`$$ArrayIndex(name)`/`name[...]`
                elsewhere); None for anonymous arrays (`array { ... }`,
                by far the more common form in this corpus for
                variable-length trailing data).
        bound   Optional[Expr]: the `[expr]` element-count bound
                (`array [1] { ... }`, `array[32] { ... }`,
                `array[160] { ... }`); None for open/unbounded arrays
                that repeat until the enclosing data ends.
        fields  list[Field]: the one-iteration element field-list.

    OptionalField(name, fields)
        `optional <name> { <fields> } ;` — a 0-or-1-repetition field
        group (`optional Fields { ... }` throughout `rControlTemplate`'s
        switch cases; `optional Stuff { ... }`/`optional Results { ...
        }` in `rFinderPath`/`rBundle`). Structurally identical to
        `ArrayField` minus `wide`/`bound`; kept distinct because it's a
        distinct Rez keyword with distinct (0-or-1, not N-times) R5
        semantics.

    SwitchField(cases: list[SwitchCase])
        `switch { (case <name>: <fields>)+ } ;`
        SwitchCase(name, fields) — `fields[0]` is conventionally the
        `key`-flagged discriminator TypedField (`key longint = ...;` /
        `key integer = ...;`), followed by whatever else the case
        declares (often exactly one `optional <Name> { ... }` group;
        sometimes plain fields directly, as in `rStyleBlock`/`rTERuler`;
        sometimes nothing more at all, as in every switch's `case
        empty: key integer = 0x0;`). Not enforced structurally here —
        R5 decides how to interpret a case's field list.

    GroupField(keyword, fields)
        `<ident> { <fields> } ;` where `<ident>` is *not* one of the
        recognized keywords above and is immediately followed by `{`
        (no colon — that's a `Label` instead). Generalizes the single
        corpus occurrence of `ReverseBytes { ... };` in `rVersion` (a
        real-Rez construct that packs its nested bit/byte fields in
        reversed bit order — R5's problem, not this module's) without
        hard-coding that one name, so any future same-shaped keyword
        this corpus doesn't happen to exercise still parses.

    FillField(unit, count)
        `fill (bit|byte|word|long) ([<count>])? ;` — emits `count`
        zero-filled units (`fill long[3];` in `rWindParam1`, the
        corpus's only occurrence; `count` is `None` when the bracket is
        omitted, meaning a single unit — real Rez's default).
        unit   str, lowercased, one of `bit`/`byte`/`word`/`long`.

    AlignField(unit)
        `align (bit|byte|word|long) ;` — pads to the given boundary.
        Grammar-supported per the design doc's field-kind list; **not
        exercised anywhere in either corpus file** (see the R4 packet
        report — flagged as anticipated-but-absent, like `boolean` and
        the `binary`/`literal` modifiers).

Expressions (`Expr`, used for field sizes/defaults, resource ids/attrs,
and every value list element that isn't a string/hex-string/group)
----------------------------------------------------------------------
    Expr = Num | Name | Subscript | UnaryOp | BinOp | Call

    Num(value: int)              an integer literal (already decoded by
                                  the lexer; radix is not preserved here
                                  — `text` on the original token is gone
                                  by this point, matching the design
                                  doc's "PRESERVE modifiers, R5 decides"
                                  stance only for *field* modifiers, not
                                  for numeric-literal radix, which nothing
                                  in the corpus needs preserved).
    Name(name: str)               a bare identifier: a symbolic constant
                                  (`verUS`, `release`, `infront`, `NIL`
                                  when not `#define`d away already) or a
                                  label reference (`height` in
                                  `$$Word(height)`).
    Subscript(name, index: Expr)  `<name>[<index>]` — an indexed label
                                  reference, e.g.
                                  `end[$$ArrayIndex(OneDocs)]` in
                                  `rBundle` (the byte offset of label
                                  `end` within array-iteration `OneDocs`
                                  at position `index`). Only ever seen
                                  with a name that is itself a plain
                                  label, never combined with unary/binary
                                  operators inside the brackets other
                                  than through a nested `$$ArrayIndex`
                                  call.
    UnaryOp(op: '-', operand)     unary minus (the lexer never folds
                                  sign into NUMBER; `-1` is
                                  `PUNCT('-')` `NUMBER(1)`, reassembled
                                  here).
    BinOp(op, left, right)        `op` is one of `'+' '-' '*' '/'` — the
                                  only binary operators either corpus
                                  file's expressions use (confirmed by
                                  scanning both files for any other
                                  punctuation character; none of
                                  `< > % & | ^ ~` ever appear outside
                                  string literals). Standard precedence
                                  (`*`/`/` above `+`/`-`), left
                                  associative, parenthesization via
                                  `'(' expr ')'`.
    Call(func, args: list[Expr])  a `$$Func(...)` field-reference/meta-
                                  function invocation. `func` is the
                                  lexer's opaque IDENT text verbatim
                                  (e.g. `'$$Word'`, `'$$countOf'`,
                                  `'$$ArrayIndex'`) — matching it
                                  case-insensitively against a builtin
                                  table is R5's job, not this module's
                                  (mirroring the lexer's own docstring
                                  note). Every occurrence in the corpus
                                  passes exactly one argument, but the
                                  grammar accepts a general
                                  comma-separated list for robustness.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Union

from gsasm.rez import lexer
from gsasm.rez.lexer import (
    IDENT, NUMBER, STRING, HEXSTRING, PUNCT, EOF,
)


class ParseError(Exception):
    """Fatal, unrecoverable parse failure. Message is pre-formatted with
    `file:line:`, mirroring `lexer.LexError`."""


# ==========================================================================
# AST node definitions (see the module docstring for the full shape guide)
# ==========================================================================
@dataclass
class Node:
    file: str
    line: int


# -- Expressions -----------------------------------------------------------
@dataclass
class Num(Node):
    value: int


@dataclass
class Name(Node):
    name: str


@dataclass
class Subscript(Node):
    name: str
    index: 'Expr'


@dataclass
class UnaryOp(Node):
    op: str
    operand: 'Expr'


@dataclass
class BinOp(Node):
    op: str
    left: 'Expr'
    right: 'Expr'


@dataclass
class Call(Node):
    func: str
    args: List['Expr']


Expr = Union[Num, Name, Subscript, UnaryOp, BinOp, Call]


# -- Values (resource/array data) ------------------------------------------
@dataclass
class StrLit(Node):
    value: bytes


@dataclass
class HexLit(Node):
    value: bytes


@dataclass
class GroupValue(Node):
    values: List['Value']


@dataclass
class CaseValue(Node):
    name: str
    values: List['Value']


Value = Union[Expr, StrLit, HexLit, GroupValue, CaseValue]


# -- Fields (type-template bodies) -----------------------------------------
@dataclass
class Label(Node):
    name: str


@dataclass
class NamedValue:
    name: str
    value: Optional[Expr]


@dataclass
class TypedField(Node):
    key: bool
    modifiers: List[str]
    basetype: str
    size: Optional[Expr]
    default: Optional[Expr]
    named_values: List[NamedValue]


@dataclass
class ArrayField(Node):
    wide: bool
    name: Optional[str]
    bound: Optional[Expr]
    fields: List['Field']


@dataclass
class OptionalField(Node):
    name: str
    fields: List['Field']


@dataclass
class SwitchCase(Node):
    name: str
    fields: List['Field']


@dataclass
class SwitchField(Node):
    cases: List[SwitchCase]


@dataclass
class GroupField(Node):
    keyword: str
    fields: List['Field']


@dataclass
class FillField(Node):
    unit: str
    count: Optional[Expr]


@dataclass
class AlignField(Node):
    unit: str


Field = Union[Label, TypedField, ArrayField, OptionalField, SwitchField,
              GroupField, FillField, AlignField]


# -- Top-level statements ---------------------------------------------------
@dataclass
class TypeDecl(Node):
    typeid: Union[int, str]
    id_range: Optional[Tuple[Expr, Optional[Expr]]]
    fields: List[Field]


@dataclass
class ResourceStmt(Node):
    typeid: Union[int, str]
    id: Expr
    name: Optional[bytes]
    attrs: List[Expr]
    values: List[Value]


@dataclass
class ReadStmt(Node):
    typeid: Union[int, str]
    id: Expr
    name: Optional[bytes]
    attrs: List[Expr]
    filename: bytes


Statement = Union[TypeDecl, ResourceStmt, ReadStmt]


# ==========================================================================
# Keyword tables (all matched case-insensitively against IDENT.value.lower())
# ==========================================================================
BASETYPES = frozenset({
    'byte', 'integer', 'longint', 'word', 'char', 'boolean',
    'string', 'pstring', 'cstring', 'wstring', 'point', 'rect', 'bitstring',
})
MODIFIERS = frozenset({'hex', 'unsigned', 'binary', 'literal', 'decimal', 'octal'})
FILL_UNITS = frozenset({'bit', 'byte', 'word', 'long'})


# ==========================================================================
# The parser
# ==========================================================================
class _Parser:
    def __init__(self, tokens):
        self.toks = tokens
        self.i = 0

    # -- token-stream primitives --------------------------------------------
    def peek(self, k=0):
        j = self.i + k
        if j < len(self.toks):
            return self.toks[j]
        return self.toks[-1]  # EOF sentinel

    def advance(self):
        t = self.toks[self.i]
        if t.kind != EOF:
            self.i += 1
        return t

    def check(self, kind, value=None):
        t = self.peek()
        if t.kind != kind:
            return False
        return value is None or t.value == value

    def check_punct(self, ch):
        return self.check(PUNCT, ch)

    def check_ident_ci(self, word):
        t = self.peek()
        return t.kind == IDENT and t.value.lower() == word

    def expect(self, kind, what=None):
        t = self.peek()
        if t.kind != kind:
            raise ParseError(f"{t.file}:{t.line}: expected {what or kind}, "
                              f"found {t.text!r}")
        return self.advance()

    def expect_punct(self, ch):
        t = self.peek()
        if not (t.kind == PUNCT and t.value == ch):
            raise ParseError(f"{t.file}:{t.line}: expected {ch!r}, "
                              f"found {t.text!r}")
        return self.advance()

    def expect_ident_ci(self, word):
        t = self.peek()
        if not (t.kind == IDENT and t.value.lower() == word):
            raise ParseError(f"{t.file}:{t.line}: expected {word!r}, "
                              f"found {t.text!r}")
        return self.advance()

    def _peek_next_is_brace(self):
        n = self.peek(1)
        return n.kind == PUNCT and n.value == '{'

    def _peek_next_is_colon(self):
        n = self.peek(1)
        return n.kind == PUNCT and n.value == ':'

    # -- top level ------------------------------------------------------------
    def parse_program(self):
        stmts = []
        while not self.check(EOF):
            t = self.peek()
            if t.kind == IDENT:
                low = t.value.lower()
                if low == 'type':
                    stmts.append(self.parse_type_decl())
                    continue
                if low == 'resource':
                    stmts.append(self.parse_resource_stmt())
                    continue
                if low == 'read':
                    stmts.append(self.parse_read_stmt())
                    continue
            raise ParseError(f"{t.file}:{t.line}: expected 'type', "
                              f"'resource', or 'read', found {t.text!r}")
        return stmts

    def parse_typeid(self):
        t = self.peek()
        if t.kind == NUMBER:
            self.advance()
            return t.value
        if t.kind == IDENT:
            self.advance()
            return t.value
        raise ParseError(f"{t.file}:{t.line}: expected a type id "
                          f"(number or identifier), found {t.text!r}")

    def parse_type_decl(self):
        tok = self.advance()  # 'type'
        typeid = self.parse_typeid()
        id_range = None
        if self.check_punct('('):
            self.advance()
            first = self.parse_expr()
            second = None
            if self.check_punct(','):
                self.advance()
                second = self.parse_expr()
            self.expect_punct(')')
            id_range = (first, second)
        self.expect_punct('{')
        fields = self.parse_field_list()
        self.expect_punct('}')
        self.expect_punct(';')
        return TypeDecl(file=tok.file, line=tok.line, typeid=typeid,
                         id_range=id_range, fields=fields)

    def parse_res_header(self):
        """`( <id> [, "<name>"] [, <attr>]* )` — shared by resource/read."""
        self.expect_punct('(')
        id_expr = self.parse_expr()
        name = None
        attrs = []
        first = True
        while self.check_punct(','):
            self.advance()
            if first and self.check(STRING):
                name = self.parse_string_run().value
            else:
                attrs.append(self.parse_expr())
            first = False
        self.expect_punct(')')
        return id_expr, name, attrs

    def parse_resource_stmt(self):
        tok = self.advance()  # 'resource'
        typeid = self.parse_typeid()
        id_expr, name, attrs = self.parse_res_header()
        self.expect_punct('{')
        values = self.parse_value_list()
        self.expect_punct('}')
        self.expect_punct(';')
        return ResourceStmt(file=tok.file, line=tok.line, typeid=typeid,
                             id=id_expr, name=name, attrs=attrs, values=values)

    def parse_read_stmt(self):
        tok = self.advance()  # 'read'
        typeid = self.parse_typeid()
        id_expr, name, attrs = self.parse_res_header()
        filename = self.parse_string_run().value
        self.expect_punct(';')
        return ReadStmt(file=tok.file, line=tok.line, typeid=typeid,
                         id=id_expr, name=name, attrs=attrs, filename=filename)

    # -- field lists (type bodies, array/optional/switch-case/group bodies) --
    def parse_field_list(self):
        return self.parse_fields_until(lambda: self.check_punct('}'))

    def parse_fields_until(self, stop):
        fields = []
        while not stop():
            if self.check(IDENT) and self._peek_next_is_colon():
                t = self.advance()
                self.expect_punct(':')
                fields.append(Label(file=t.file, line=t.line, name=t.value))
                continue
            fields.append(self.parse_field())
        return fields

    def parse_field(self):
        t = self.peek()
        if t.kind != IDENT:
            raise ParseError(f"{t.file}:{t.line}: expected a field, "
                              f"found {t.text!r}")
        low = t.value.lower()
        if low == 'fill':
            return self.parse_fill()
        if low == 'align':
            return self.parse_align()
        if low == 'switch':
            return self.parse_switch()
        if low == 'optional':
            return self.parse_optional()
        if low == 'wide':
            wide_tok = self.advance()
            return self.parse_array(wide=True, tok=wide_tok)
        if low == 'array':
            return self.parse_array(wide=False)
        return self.parse_typed_or_group()

    def parse_typed_or_group(self):
        start = self.peek()
        key = False
        if self.check_ident_ci('key'):
            self.advance()
            key = True
        modifiers = []
        while self.check(IDENT) and self.peek().value.lower() in MODIFIERS:
            modifiers.append(self.advance().value.lower())
        cur = self.peek()
        if cur.kind == IDENT and cur.value.lower() in BASETYPES:
            bt_tok = self.advance()
            basetype = bt_tok.value.lower()
            size = None
            if self.check_punct('['):
                size = self.parse_bracket_expr()
            default = None
            named_values = []
            if self.check_punct('='):
                self.advance()
                default = self.parse_expr()
            elif self.check(IDENT):
                named_values = self.parse_named_values()
            self.expect_punct(';')
            return TypedField(file=start.file, line=start.line, key=key,
                               modifiers=modifiers, basetype=basetype,
                               size=size, default=default,
                               named_values=named_values)
        if not key and not modifiers and cur.kind == IDENT and self._peek_next_is_brace():
            name_tok = self.advance()
            self.expect_punct('{')
            fields = self.parse_field_list()
            self.expect_punct('}')
            self.expect_punct(';')
            return GroupField(file=name_tok.file, line=name_tok.line,
                               keyword=name_tok.value, fields=fields)
        raise ParseError(f"{cur.file}:{cur.line}: expected a field type, "
                         f"'key', a modifier, or a named group, "
                         f"found {cur.text!r}")

    def parse_named_values(self):
        values = []
        while True:
            name_tok = self.expect(IDENT, 'a value name')
            val = None
            if self.check_punct('='):
                self.advance()
                val = self.parse_expr()
            values.append(NamedValue(name_tok.value, val))
            if self.check_punct(','):
                self.advance()
                continue
            break
        return values

    def parse_array(self, wide, tok=None):
        if tok is None:
            tok = self.peek()
        self.expect_ident_ci('array')
        name = None
        if self.check(IDENT):
            name = self.advance().value
        bound = None
        if self.check_punct('['):
            bound = self.parse_bracket_expr()
        self.expect_punct('{')
        fields = self.parse_field_list()
        self.expect_punct('}')
        self.expect_punct(';')
        return ArrayField(file=tok.file, line=tok.line, wide=wide, name=name,
                           bound=bound, fields=fields)

    def parse_optional(self):
        tok = self.advance()  # 'optional'
        name_tok = self.expect(IDENT, 'an optional-group name')
        self.expect_punct('{')
        fields = self.parse_field_list()
        self.expect_punct('}')
        self.expect_punct(';')
        return OptionalField(file=tok.file, line=tok.line,
                              name=name_tok.value, fields=fields)

    def parse_switch(self):
        tok = self.advance()  # 'switch'
        self.expect_punct('{')
        cases = []
        while self.check(IDENT) and self.peek().value.lower() == 'case':
            case_tok = self.advance()
            name_tok = self.expect(IDENT, 'a case name')
            self.expect_punct(':')
            fields = self.parse_fields_until(
                lambda: self.check_punct('}')
                or (self.check(IDENT) and self.peek().value.lower() == 'case'))
            cases.append(SwitchCase(file=case_tok.file, line=case_tok.line,
                                     name=name_tok.value, fields=fields))
        self.expect_punct('}')
        self.expect_punct(';')
        return SwitchField(file=tok.file, line=tok.line, cases=cases)

    def parse_fill(self):
        tok = self.advance()  # 'fill'
        unit_tok = self.expect(IDENT, 'a fill unit (bit/byte/word/long)')
        unit = unit_tok.value.lower()
        if unit not in FILL_UNITS:
            raise ParseError(f"{unit_tok.file}:{unit_tok.line}: unknown fill "
                              f"unit {unit_tok.text!r}")
        count = None
        if self.check_punct('['):
            count = self.parse_bracket_expr()
        self.expect_punct(';')
        return FillField(file=tok.file, line=tok.line, unit=unit, count=count)

    def parse_align(self):
        tok = self.advance()  # 'align'
        unit_tok = self.expect(IDENT, 'an align unit (bit/byte/word/long)')
        unit = unit_tok.value.lower()
        if unit not in FILL_UNITS:
            raise ParseError(f"{unit_tok.file}:{unit_tok.line}: unknown align "
                              f"unit {unit_tok.text!r}")
        self.expect_punct(';')
        return AlignField(file=tok.file, line=tok.line, unit=unit)

    # -- values (resource/array data) ----------------------------------------
    def parse_value_list(self):
        values = []
        if self.check_punct('}'):
            return values
        values.append(self.parse_value())
        while self.check_punct(',') or self.check_punct(';'):
            self.advance()
            if self.check_punct('}'):
                break  # trailing separator absorbed (see module docstring)
            values.append(self.parse_value())
        return values

    def parse_value(self):
        t = self.peek()
        if t.kind == STRING:
            return self.parse_string_run()
        if t.kind == HEXSTRING:
            return self.parse_hexstring_run()
        if t.kind == PUNCT and t.value == '{':
            return self.parse_group_value()
        if t.kind == IDENT and self._peek_next_is_brace():
            name_tok = self.advance()
            group = self.parse_group_value()
            return CaseValue(file=name_tok.file, line=name_tok.line,
                              name=name_tok.value, values=group.values)
        return self.parse_expr()

    def parse_string_run(self):
        t = self.peek()
        parts = []
        while self.check(STRING):
            parts.append(self.advance().value)
        if not parts:
            raise ParseError(f"{t.file}:{t.line}: expected a string literal, "
                              f"found {t.text!r}")
        return StrLit(file=t.file, line=t.line, value=b''.join(parts))

    def parse_hexstring_run(self):
        t = self.peek()
        parts = []
        while self.check(HEXSTRING):
            parts.append(self.advance().value)
        if not parts:
            raise ParseError(f"{t.file}:{t.line}: expected a hex-string "
                              f"literal, found {t.text!r}")
        return HexLit(file=t.file, line=t.line, value=b''.join(parts))

    def parse_group_value(self):
        tok = self.expect_punct('{')
        values = self.parse_value_list()
        self.expect_punct('}')
        return GroupValue(file=tok.file, line=tok.line, values=values)

    # -- expressions ----------------------------------------------------------
    def parse_bracket_expr(self):
        self.expect_punct('[')
        e = self.parse_expr()
        self.expect_punct(']')
        return e

    def parse_expr(self):
        return self.parse_additive()

    def parse_additive(self):
        left = self.parse_multiplicative()
        while self.check_punct('+') or self.check_punct('-'):
            op_tok = self.advance()
            right = self.parse_multiplicative()
            left = BinOp(file=left.file, line=left.line, op=op_tok.value,
                         left=left, right=right)
        return left

    def parse_multiplicative(self):
        left = self.parse_unary()
        while self.check_punct('*') or self.check_punct('/'):
            op_tok = self.advance()
            right = self.parse_unary()
            left = BinOp(file=left.file, line=left.line, op=op_tok.value,
                         left=left, right=right)
        return left

    def parse_unary(self):
        if self.check_punct('-'):
            tok = self.advance()
            operand = self.parse_unary()
            return UnaryOp(file=tok.file, line=tok.line, op='-',
                            operand=operand)
        return self.parse_primary()

    def parse_primary(self):
        t = self.peek()
        if t.kind == NUMBER:
            self.advance()
            return Num(file=t.file, line=t.line, value=t.value)
        if t.kind == PUNCT and t.value == '(':
            self.advance()
            e = self.parse_expr()
            self.expect_punct(')')
            return e
        if t.kind == IDENT:
            if t.value.startswith('$$'):
                self.advance()
                self.expect_punct('(')
                args = []
                if not self.check_punct(')'):
                    args.append(self.parse_expr())
                    while self.check_punct(','):
                        self.advance()
                        args.append(self.parse_expr())
                self.expect_punct(')')
                return Call(file=t.file, line=t.line, func=t.value, args=args)
            self.advance()
            if self.check_punct('['):
                idx = self.parse_bracket_expr()
                return Subscript(file=t.file, line=t.line, name=t.value,
                                  index=idx)
            return Name(file=t.file, line=t.line, name=t.value)
        raise ParseError(f"{t.file}:{t.line}: expected an expression, "
                          f"found {t.text!r}")


# ==========================================================================
# Public entry point
# ==========================================================================
def parse(path, include_dirs=None, predefined=None):
    """Preprocess+tokenize `path` (via `lexer.tokenize`) and parse the
    result into a `list[Statement]`, in source order. Raises
    `lexer.LexError` for lexical/preprocessor failures, `ParseError` for
    grammar failures; both carry a pre-formatted `file:line:` message.

    `predefined`: optional `{macro_name: int}` seed passed straight through
    to `lexer.tokenize` (see its docstring); default `None` changes nothing
    for existing callers."""
    tokens = lexer.tokenize(path, include_dirs=include_dirs, predefined=predefined)
    return _Parser(tokens).parse_program()
