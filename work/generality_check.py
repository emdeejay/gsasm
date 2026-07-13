"""generality_check.py — gate: no source-symbol / address literals in gsasm/*.py.

The project's central claim: `gsasm/*.py` is a GENERAL
AsmIIgs/LinkIIgs reimplementation — no branch keyed on a real corpus symbol
name, no module-specific address baked into logic.  Module-specific build
config belongs in the `work/` harnesses (recipes, like a makefile).

THE SMELL TEST (docs/design/ARCH_REVIEW_SECOND_CHAIR.md §7): a fix is general
iff keyed on a PROPERTY (a directive / operator / syntax / structural
relationship), bespoke iff keyed on a specific NAME / ADDRESS / FILE.  Extra
clause: also ask "is the property a proxy for a gsasm-INTERNAL
representational choice?" (e.g. the Tool025 case-collision fix repairs
gsasm's own case-folding, which MPW may not exhibit — a false-negative of the
base test).

MECHANISM: AST-scan every gsasm/*.py for
  - identifier-like string literals (len >= 4), and
  - int literals >= 0x2000 (address-sized)
in CODE (docstrings / comments are ignored by construction).  Each must be in
the whitelist below — the audited 2026-07-10 population, all of which are
AsmIIgs directives, OMF record/field names, 65816 addressing modes, or
structural constants.  A NEW literal fails this gate until a human confirms
it is structural (then adds it here) — the point is the conscious step, not
the list.

Run: python3 work/generality_check.py    (exit 1 on any unlisted literal)
"""
import ast
import glob
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Audited string-literal population (2026-07-10) — AsmIIgs directives &
# builtins, OMF record/field names, 65816 addressing-mode keys, dict keys /
# python-isms.  NO corpus symbol names.
ALLOWED_STRS = {
    '.filetype', '.obj', '.out', '0123456789abcdefABCDEF',
    'AERROR', 'ALIGN', 'ANOP', 'ASIS', 'ASSERT', 'BANKSIZE', 'BEXPR',
    'BLANKS', 'BYTE', 'BYTECNT', 'CASE', 'CONCAT', 'CONST', 'CSTRING', 'DCB.',
    'DSECT',       # MPW dummy-section directive (record-template conversion)
    'DECR', 'DECREMENT', 'DEFAULT', 'DISPDATA', 'DISPNAME', 'DOWNCASE',
    'EJECT', 'ELSE', 'ELSEIF', 'ENDF', 'ENDIF', 'ENDM', 'ENDP', 'ENDPROC',
    'ENDR', 'ENDWHILE', 'ENDWITH', 'ENTRY', 'ERRIF', 'EVAL', 'EXPORT',
    'EXPR', 'FILE', 'FINDSYM', 'FUNC', 'GBLA', 'GBLB', 'GBLC', 'GEQU',
    'GLOBAL', 'GOTO', 'IMPORT', 'INCLUDE', 'INCR', 'INCREMENT', 'INTERSEG',
    'INTTOSTR', 'ISINT', 'KEEP', 'KIND', 'LABLEN', 'LCLA', 'LCLB', 'LCLC',
    'LCONST', 'LENGTH', 'LEXPR', 'LIST', 'LOADNAME', 'LOCAL', 'LONG', 'LONGA',
    'LONGI', 'LONGTABLE', 'M65816', 'MACHINE', 'MACRO', 'MEND', 'MEXIT',
    'NEEDS', 'NOGEN', 'NOTE', 'NUMLEN', 'NUMSEX', 'PAGE', 'PAGESIZE',
    'PASCAL', 'PRINT', 'PROC', 'RECORD', 'RELEXPR', 'RELOC', 'RESSPC',
    'SEGNAME', 'SEGNUM', 'SETA', 'SETB', 'SETC', 'SETTING', 'SPACE',
    'STRING', 'SUBSTR', 'SUPER', 'SYSDATE', 'SYSGLOBAL', 'SYSLOCAL',
    'SYSTIME', 'TEMPORG', 'THEN', 'TITLE', 'TRIM', 'TYPE',
    'UNDEFINED',   # MPW &TYPE() return value for an unknown symbol
    'UNHANDLED',
    'UPCASE', 'UPPERCASE', 'VERSION', 'WHILE', 'WITH', 'WORD', 'WRITELN',
    'ZEXPR',
    '__LOC__', '__fspath__', '__main__',
    'ablx', 'absx', 'absy', 'aind', 'aindl', 'aindx', 'append', 'base',
    'body', 'byte', 'cINTERSEG', 'cRELOC', 'code', 'comment', 'decrement',
    'defer_shifts', 'defines', 'equ_alias', 'expr', 'extern', 'global',
    '_gstream_cache',   # omf: memo attr for GLOBAL item-stream positions
    'align',            # asm Segment attr (`PROC align N`), via getattr
    'gsasm', 'gslink', 'import', 'incdirs', 'increment', 'indl', 'indly',
    'indx', 'indy', 'is_data', 'kind', 'label', 'length', 'little',
    'loadname', 'mac_roman', 'main', 'merge', 'multiseg', 'name', 'nbytes',
    'noskip', 'operand', 'output', 'priv', 'read', 'recs', 'rel16', 'rel8',
    'rell', 'reloc_size', 'replace', 'seg_bytes', 'segkinds', 'segname',
    'segnames', 'shift', 'skip', 'source', 'sriy', 'super', 'type',
    'seg_order',        # linkiigs opts key: explicit cross-object placement
                        #   order (library extraction) — structural, no corpus name
}

# Audited int-literal population (>= 0x2000): masks, bank size, OMF KIND
# 0x8001 (ExpressLoad dynamic), reloc flag bits, 2_000_000 numeric-literal
# guard.  NO module addresses.
ALLOWED_INTS = {
    0x4000, 0x8001, 0xFFFF, 0x10000, 0x1E8480, 0xFFFFFF,
    0x80000000, 0xFFFFFFFF, 0x100000000,
}


def _code_literals(path):
    """Yield (lineno, value) for string/int Constant nodes in code (not
    docstrings / bare-string statements)."""
    tree = ast.parse(open(path).read())
    bare = set()
    for node in ast.walk(tree):
        for fld in ('body', 'orelse', 'finalbody'):
            stmts = getattr(node, fld, None)
            if not isinstance(stmts, list):      # e.g. Lambda.body is an expr
                continue
            for stmt in stmts:
                if (isinstance(stmt, ast.Expr)
                        and isinstance(stmt.value, ast.Constant)
                        and isinstance(stmt.value.value, str)):
                    bare.add(id(stmt.value))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and id(node) not in bare:
            yield node.lineno, node.value


def main():
    bad = []
    for p in sorted(glob.glob(os.path.join(ROOT, 'gsasm', '*.py'))):
        rel = os.path.relpath(p, ROOT)
        for lineno, v in _code_literals(p):
            if isinstance(v, str):
                if (len(v) >= 4 and v.replace('_', '').replace('.', '').isalnum()
                        and v not in ALLOWED_STRS):
                    bad.append(f'{rel}:{lineno}: string literal {v!r}')
            elif isinstance(v, int) and not isinstance(v, bool):
                if v >= 0x2000 and v not in ALLOWED_INTS:
                    bad.append(f'{rel}:{lineno}: int literal {hex(v)}')
    if bad:
        print('generality_check: NEW literal(s) in gsasm/*.py — apply the '
              'smell test (property vs name/address; see module docstring):')
        for b in bad:
            print('  ', b)
        print('If structural, whitelist it here WITH justification; if it '
              'names a corpus symbol / module address, move it to a work/ '
              'harness recipe.')
        return 1
    print('generality_check: OK — no unlisted symbol/address literals in '
          'gsasm/*.py.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
