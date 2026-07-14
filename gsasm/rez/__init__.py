"""Rez resource-compiler subpackage (design/rez.md, milestone M7).

Replaces MPW `RezIIgs`.  `lexer` (packet R3) turns a `.r` source file plus its
`#include` closure into a single flat token stream; `parser` (packet R4)
turns that stream into an AST; `gen` (packet R5) evaluates resource bodies
against type templates into bytes; `emit` (packet R2) packs `(type, id,
attr, data)` tuples into a resource fork.
"""

from .lexer import (
    Token,
    LexError,
    tokenize,
    IDENT,
    NUMBER,
    STRING,
    HEXSTRING,
    PUNCT,
    EOF,
    ERROR,
)
from .parser import (
    ParseError,
    parse,
    TypeDecl,
    ResourceStmt,
    ReadStmt,
    Label,
    NamedValue,
    TypedField,
    ArrayField,
    OptionalField,
    SwitchCase,
    SwitchField,
    GroupField,
    FillField,
    AlignField,
    Num,
    Name,
    Subscript,
    UnaryOp,
    BinOp,
    Call,
    StrLit,
    HexLit,
    GroupValue,
    CaseValue,
)
from .gen import (
    GenError,
    GenEntry,
    generate,
    to_emit_tuples,
    RESNAME_TYPE,
    RESNAME_ID,
)

__all__ = [
    'Token', 'LexError', 'tokenize',
    'IDENT', 'NUMBER', 'STRING', 'HEXSTRING', 'PUNCT', 'EOF', 'ERROR',
    'ParseError', 'parse',
    'TypeDecl', 'ResourceStmt', 'ReadStmt',
    'Label', 'NamedValue', 'TypedField', 'ArrayField', 'OptionalField',
    'SwitchCase', 'SwitchField', 'GroupField', 'FillField', 'AlignField',
    'Num', 'Name', 'Subscript', 'UnaryOp', 'BinOp', 'Call',
    'StrLit', 'HexLit', 'GroupValue', 'CaseValue',
    'GenError', 'GenEntry', 'generate', 'to_emit_tuples',
    'RESNAME_TYPE', 'RESNAME_ID',
]
