#!/usr/bin/env python3
"""Validate gsasm/rez/parser.py against the two Rez corpus files (packet R4).

Parses the archive `sys.resources.r` (CR + MacRoman), which pulls in
`work/rincludes/TypesIIGS.r` via `#include "typesiigs.r"` (case-insensitive
match against the real, differently-cased `TypesIIGS.r`).  Corpus-derived
checks live here (never under tests/ — the Apple sources are gitignored and
not redistributable); tests/test_rez_parser.py carries the small
hand-authored grammar fixtures instead.

Usage: python3 work/rezparsecheck.py
"""
import collections
import os
import sys

from _common import ensure_repo_on_path, rincludes, sysresources_rez
ensure_repo_on_path()
from gsasm.rez import lexer, parser

SRC = sysresources_rez()
INCS = rincludes()

# The design doc's packet-R4 acceptance note expects "~139 resource + 4 read
# statements minting the golden fork's 143" and asks us to investigate and
# explain any discrepancy. The source actually contains 138 `resource`
# statements + 4 `read` statements = 142 explicit statements (see below for
# why 139 was an overcount and why the true fork total, 143, is still one
# more than that).
EXPECTED_TYPE_DECLS = 44     # 43 in TypesIIGS.r + 1 (rMyCursor) in sys.resources.r
EXPECTED_RESOURCE_STMTS = 138
EXPECTED_READ_STMTS = 4


def main():
    ok = True

    for path in ('work/rincludes/TypesIIGS.r', SRC):
        if not os.path.exists(path):
            print(f'FAIL: corpus file missing: {path}')
            return 1

    try:
        stmts = parser.parse(SRC, include_dirs=INCS)
    except (lexer.LexError, parser.ParseError) as exc:
        print(f'FAIL: {exc}')
        return 1

    kinds = collections.Counter(type(s).__name__ for s in stmts)
    print(f'total statements: {len(stmts)}')
    print('by kind:')
    for name in ('TypeDecl', 'ResourceStmt', 'ReadStmt'):
        print(f'  {name:14s} {kinds.get(name, 0)}')

    type_decls = [s for s in stmts if isinstance(s, parser.TypeDecl)]
    resources = [s for s in stmts if isinstance(s, parser.ResourceStmt)]
    reads = [s for s in stmts if isinstance(s, parser.ReadStmt)]

    # Distinct type templates declared (by typeid). 43 out of 44, not 44 —
    # sys.resources.r's local `type rMyCursor {...}` (`#define rMyCursor
    # $8027`, right above it) redeclares the *same* typeid TypesIIGS.r
    # already gave a template to (`#define rCursor $8027` / `type rCursor
    # {...}`). This is exactly what the design doc's "`-rd` in the makefile
    # invocation = suppress warnings about redeclared types" gotcha refers
    # to: RezIIgs would otherwise warn about this collision.
    distinct_typeids = {t.typeid for t in type_decls}
    print(f'type declarations: {len(type_decls)} total, '
          f'{len(distinct_typeids)} distinct typeid(s) '
          f'({len(type_decls) - len(distinct_typeids)} redeclaration(s) — '
          f'expected: rCursor/rMyCursor both templating typeid $8027)')

    print(f'resource statements: {len(resources)}')
    print(f'read statements: {len(reads)}')

    # Per-resource (typeid, id) list, in source order (R5 needs source
    # order for data layout -- this *is* that order, since `stmts` is
    # already the parse's flat, source-ordered statement list and we
    # merely filter it here without re-sorting).
    def _const_int(e):
        return e.value if isinstance(e, parser.Num) else None

    res_keys = [(r.typeid, _const_int(r.id)) for r in resources]
    print(f'(typeid, id) pairs recorded for all {len(res_keys)} resource '
          f'statements (first 3: {res_keys[:3]}, last 3: {res_keys[-3:]})')

    if len(type_decls) - len(distinct_typeids) != 1:
        ok = False
        print('FAIL: expected exactly 1 redeclared typeid (rCursor/'
              'rMyCursor, both $8027), got '
              f'{len(type_decls) - len(distinct_typeids)}')

    # Source-order sanity: within each file's own contiguous span of
    # statements, line numbers must be non-decreasing (statements never
    # appear "out of order" relative to their own file — the only
    # reordering possible is *between* files, and #include "typesiigs.r"
    # is a single directive at the very top of sys.resources.r, so its
    # entire statement block must precede all of sys.resources.r's own).
    by_file_lines = collections.defaultdict(list)
    for s in stmts:
        by_file_lines[s.file].append(s.line)
    for fname, lines in by_file_lines.items():
        if lines != sorted(lines):
            ok = False
            print(f'FAIL: statements out of source order within {fname}')
    files_seen = [s.file for s in stmts]
    types_file = 'work/rincludes/TypesIIGS.r'
    if types_file in by_file_lines:
        last_types_idx = max(i for i, f in enumerate(files_seen) if f == types_file)
        first_src_idx = next((i for i, f in enumerate(files_seen) if f == SRC), None)
        if first_src_idx is not None and first_src_idx < last_types_idx:
            ok = False
            print('FAIL: a sys.resources.r statement appears interleaved '
                  'before the end of TypesIIGS.r\'s statement block')

    if len(type_decls) != EXPECTED_TYPE_DECLS:
        ok = False
        print(f'FAIL: expected {EXPECTED_TYPE_DECLS} type declarations, '
              f'got {len(type_decls)}')

    if len(resources) != EXPECTED_RESOURCE_STMTS:
        ok = False
        print(f'FAIL: expected {EXPECTED_RESOURCE_STMTS} resource '
              f'statements, got {len(resources)}')

    if len(reads) != EXPECTED_READ_STMTS:
        ok = False
        print(f'FAIL: expected {EXPECTED_READ_STMTS} read statements, '
              f'got {len(reads)}')

    total = len(resources) + len(reads)
    print(f'resource + read = {total} (design-doc packet note: "~139 '
          f'resource + 4 read... minting the golden fork\'s 143")')
    print(
        "Explanation of the discrepancy (139 expected vs. 138 actual "
        "`resource` statements, and 142 vs. 143 total fork resources):\n"
        "  (1) A naive `grep -c '^resource'` over the source overcounts by\n"
        "      one: sys.resources.r:1286-1296 has a multi-line /* ... */\n"
        "      comment containing a *fully commented-out example* — inside\n"
        "      it, the line 'resource rPString ($07ff10xx) { \"Standard\" };'\n"
        "      itself starts in column 0 (so a text grep for '^resource'\n"
        "      matches it) even though the whole block is inside the open\n"
        "      /* ... */ that began several lines earlier documenting the\n"
        "      $10-$FE menu-item-template range. The lexer correctly\n"
        "      discards block comments, so this text never reaches the\n"
        "      parser and rightly isn't counted; true source count is 138.\n"
        "  (2) The remaining +1 (138+4=142 explicit statements vs. the\n"
        "      golden fork's 143 total resources, confirmed via\n"
        "      `python3 work/rezcheck.py --dump Sys.Resources`) is a\n"
        "      resource with type $8014 (rResName) at id 0x00018001 that\n"
        "      has NO corresponding `resource rResName(...) {...};` (or\n"
        "      `#define`d-typeid equivalent) anywhere in sys.resources.r —\n"
        "      it does not exist as a source statement at all. rResName's\n"
        "      own type template (TypesIIGS.r) is a name-holder format\n"
        "      (`array NAMES { hex longint; pstring; };` — an (id, name)\n"
        "      table), and this corpus has several resources declared\n"
        "      with an explicit \"name\" string (the icons \"Stop\"/\"Note\"/\n"
        "      \"Caution\"/\"Disk\"/\"Disk Swap\", the rPString \"Translation\",\n"
        "      ...). RezIIgs auto-synthesizes this one rResName resource\n"
        "      from those names at build time; it is not parsed from any\n"
        "      literal statement, so packet R4 (a pure parser) correctly\n"
        "      never produces it — synthesizing it is an R5/R7 (build-\n"
        "      time) concern, not a parsing one.\n"
    )

    print('PASS' if ok else 'FAIL')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
