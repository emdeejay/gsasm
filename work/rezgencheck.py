#!/usr/bin/env python3
"""Validate gsasm/rez/gen.py against the golden Sys.Resources fork (packet R5).

Parses the archive `sys.resources.r` corpus (same source/include path as
work/rezparsecheck.py; predefines `RezIIGS=1` — see gen.py / lexer.py's
`_Preprocessor.__init__` docstring for why: real RezIIgs predefines this so
`#if RezIIGS == 1` guards fire, adding the null-longint array terminator
`rControlList`/`rMenu`/`rMenuBar` need), runs `gen.generate()`, and for
EVERY non-`read` resource in the golden fork (139 = 138 source resource
statements + 1 synthesized rResName) byte-compares the generated data
against `work/rezcheck.py`'s golden bytes, matched by (type, id).

Usage: python3 work/rezgencheck.py
"""
import collections
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)
sys.path.insert(0, HERE)

from gsasm.rez import lexer, parser, gen  # noqa: E402
import rezcheck as rc  # noqa: E402

SRC = 'ref/GSOS_6/IIGS.601.SRC/GSToolbox/Sys.Resources/sys.resources.r'
INCS = ['work/rincludes']


def _hexctx(data, offset, width=16):
    lo = max(0, offset - width)
    hi = min(len(data), offset + width)
    return data[lo:hi].hex()


def main():
    os.chdir(REPO)
    for path in ('work/rincludes/TypesIIGS.r', SRC):
        if not os.path.exists(path):
            print(f'FAIL: corpus file missing: {path}')
            return 1

    try:
        stmts = parser.parse(SRC, include_dirs=INCS, predefined={'RezIIGS': 1})
    except (lexer.LexError, parser.ParseError) as exc:
        print(f'FAIL: parse error: {exc}')
        return 1

    try:
        entries = gen.generate(stmts)
    except gen.GenError as exc:
        print(f'FAIL: generate() raised: {exc}')
        return 1

    kinds = collections.Counter(e.kind for e in entries)
    print(f'generate() produced {len(entries)} entries: '
          f'{kinds["resource"]} resource, {kinds["read"]} read, '
          f'{kinds["resname"]} resname')

    # Build (type, id) -> data for every non-read entry.
    built = {}
    dupes = []
    for e in entries:
        if e.kind == 'read':
            continue
        key = (e.rtype, e.rid)
        if key in built:
            dupes.append(key)
        built[key] = e.data
    if dupes:
        print(f'WARNING: duplicate (type, id) among generated non-read '
              f'entries: {dupes}')

    sysres_path = next(p for p in rc.REZ_FILES if p.endswith('Sys.Resources'))
    golden = rc.golden_fork(sysres_path)

    golden_nonread_types = {
        0x800C,   # rCtlDefProc (the 3 `read` statements)
        0x8017,   # rCodeResource (the 1 `read` statement)
    }
    # The 4 `read`-statement entries in `entries` are excluded from `built`
    # (their kind is 'read', not 'resource'); the golden fork's own index
    # entries for those (type, id) keys are the ones whose generation is
    # this packet's job to NOT attempt -- so we exclude precisely the
    # golden entries whose (type, id) matches one of our own `read` entries
    # (rather than matching on type alone, in case some other resource type
    # coincidentally reused 0x800C/0x8017 -- it doesn't in this corpus, but
    # matching by exact key is the more correct exclusion).
    read_keys = {(e.rtype, e.rid) for e in entries if e.kind == 'read'}

    n_pass = n_fail = n_missing = 0
    fails = []
    expected_total = 0
    for entry in golden.used:
        key = (entry.type, entry.id)
        if key in read_keys:
            continue
        expected_total += 1
        gdata = golden.raw[entry.offset:entry.offset + entry.size]
        bdata = built.get(key)
        if bdata is None:
            n_missing += 1
            fails.append((key, 'missing', None))
            continue
        if bdata == gdata:
            n_pass += 1
        else:
            n_fail += 1
            first_diff = next((i for i in range(min(len(gdata), len(bdata)))
                                if gdata[i] != bdata[i]),
                               min(len(gdata), len(bdata))
                               if len(gdata) != len(bdata) else None)
            fails.append((key, 'diff', first_diff))

    print(f'expected (golden, non-read) resources: {expected_total}')
    print(f'PASS: {n_pass}  FAIL: {n_fail}  MISSING: {n_missing}')

    if fails:
        print()
        print('Failures:')
        for key, status, first_diff in fails:
            rtype, rid = key
            if status == 'missing':
                print(f'  MISSING  type={rtype:#06x} id={rid:#010x}  '
                      f'(not produced by generate() at all)')
            else:
                entry = next(e for e in golden.used
                             if (e.type, e.id) == key)
                gdata = golden.raw[entry.offset:entry.offset + entry.size]
                bdata = built[key]
                print(f'  DIFF     type={rtype:#06x} id={rid:#010x}  '
                      f'golden_size={len(gdata)} built_size={len(bdata)} '
                      f'first_diff={first_diff}')
                if first_diff is not None:
                    print(f'    golden ...{_hexctx(gdata, first_diff)}...')
                    print(f'    built  ...{_hexctx(bdata, first_diff)}...')

    # Extra entries generate() produced that the golden fork doesn't have
    # (shouldn't happen for this corpus -- flagged as a diagnostic).
    golden_keys = {(e.type, e.id) for e in golden.used}
    extra = sorted(set(built) - golden_keys)
    if extra:
        print()
        print(f'EXTRA (generated but not in golden fork): {extra}')

    also_check_reads_absent_from_data = kinds['read'] == 4
    ok = (n_fail == 0 and n_missing == 0 and not extra
          and expected_total == 139 and also_check_reads_absent_from_data)

    print()
    print(f'{n_pass}/{expected_total} non-read golden resources reproduced '
          f'byte-exact' + ('' if ok else ' -- SEE FAILURES ABOVE'))
    print('PASS' if ok else 'FAIL')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
