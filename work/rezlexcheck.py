#!/usr/bin/env python3
"""Validate gsasm/rez/lexer.py against the two Rez corpus files (packet R3).

Tokenizes the archive `sys.resources.r` (CR + MacRoman), which pulls in
`work/rincludes/TypesIIGS.r` via `#include "typesiigs.r"` (case-insensitive
match against the real, differently-cased `TypesIIGS.r`).  Corpus-derived
checks live here (never under tests/ — the Apple sources are gitignored and
not redistributable); tests/test_rez_lexer.py carries the small
hand-authored fixtures instead.

Usage: python3 work/rezlexcheck.py
"""
import collections
import os
import sys

from _common import ensure_repo_on_path, rincludes, sysresources_rez
ensure_repo_on_path()
from gsasm.rez import lexer

SRC = sysresources_rez()
INCS = rincludes()


def main():
    ok = True

    for path in ('work/rincludes/TypesIIGS.r', SRC):
        if not os.path.exists(path):
            print(f'FAIL: corpus file missing: {path}')
            return 1

    toks = lexer.tokenize(SRC, include_dirs=INCS)

    errors = [t for t in toks if t.kind == lexer.ERROR]
    kinds = collections.Counter(t.kind for t in toks)
    files = collections.Counter(t.file for t in toks)

    print(f'total tokens: {len(toks)}')
    print('by kind:')
    for kind in (lexer.IDENT, lexer.NUMBER, lexer.STRING, lexer.HEXSTRING,
                 lexer.PUNCT, lexer.EOF, lexer.ERROR):
        print(f'  {kind:10s} {kinds.get(kind, 0)}')
    print('by file:')
    for f, n in files.items():
        print(f'  {f:55s} {n}')

    puncts = sorted({t.value for t in toks if t.kind == lexer.PUNCT})
    print(f'punctuation characters seen: {"".join(puncts)!r}')

    if errors:
        ok = False
        print(f'FAIL: {len(errors)} ERROR token(s):')
        for t in errors[:20]:
            print(f'  {t.file}:{t.line}: {t.value!r}')

    if toks[-1].kind != lexer.EOF:
        ok = False
        print('FAIL: stream does not end with an EOF token')

    both_files_present = (
        files.get('work/rincludes/TypesIIGS.r', 0) > 0
        and files.get(SRC, 0) > 0
    )
    if not both_files_present:
        ok = False
        print('FAIL: expected tokens charged to both corpus files')

    print('PASS' if ok else 'FAIL')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
