"""loader_residual.py — categorize the Loader placed-link residual by symbol.

Determines whether the 448-byte operand-resolution residual (after the cracked
placement in loader_placed.py) is BOUNDED (a few distinct symbols/patterns,
fixable) or genuinely DIFFUSE.
"""
import sys, os
sys.path[:0] = ['.', 'work', 'work/diskbuilders']
import kernel_os as k
import loader_placed as lp
from gsasm import linkiigs as LI, link as L
from collections import Counter


def main():
    g = lp.golden()
    lb, _ = lp.build(['loader', 'loader_lc'])
    n = min(len(lb), len(g))
    diff = set(i for i in range(n) if lb[i] != g[i])

    objs = [k._assemble(os.path.join(k._GS, 'Loader', s))
            for s in ('GSHeader.a', 'Loader.a', 'GSFooter.a')]
    info = {}
    for oi, (obj, asm) in enumerate(objs):
        parsed = LI._parse_obj(obj)
        cur = None
        for ei, sd in enumerate(parsed):
            l = sd['loadname'].lower()
            if l != 'main':
                cur = l
            info[(oi, ei)] = {'ln': l if l != 'main' else (cur or 'main'),
                              'len': L._body_length(sd['recs']),
                              'recs': sd['recs']}
    order = ['loader', 'loader_lc']
    keys = sorted(info, key=lambda kk: (order.index(info[kk]['ln'])
                                        if info[kk]['ln'] in order else 99, kk))
    flat = 0
    for kk in keys:
        info[kk]['flat'] = flat
        flat += info[kk]['len']

    sym_hist = Counter()
    const_diffs = 0
    ff = 0
    for kk in keys:
        off = info[kk]['flat']
        for _, nm, d in info[kk]['recs']:
            if nm in ('CONST', 'LCONST'):
                ln = len(d)
            elif nm == 'DS':
                ln = d
            elif nm in ('LEXPR', 'BEXPR', 'EXPR', 'RELEXPR'):
                ln = d[0]
            else:
                ln = 0
            hit = any((off + j) in diff for j in range(max(ln, 1)))
            if hit:
                if nm in ('LEXPR', 'BEXPR', 'EXPR', 'RELEXPR'):
                    ops = d[1]
                    syms = [x[1] for x in ops if isinstance(x, tuple) and x[0] == 'sym83']
                    if syms:
                        for s in syms:
                            sym_hist[s.split('.')[0] if '.' in s else s] += 1
                    else:
                        sym_hist['<no-sym expr>'] += 1
                elif nm in ('CONST', 'LCONST'):
                    # is it an ffff run?
                    if all(b == 0xff for b in d):
                        ff += 1
                    else:
                        const_diffs += 1
            off += ln

    print(f'diff bytes: {len(diff)}')
    print(f'CONST-record diffs (non-ffff): {const_diffs}   ffff CONST records: {ff}')
    print('referenced-symbol histogram (base name) for reloc-record diffs:')
    for s, c in sym_hist.most_common(25):
        print(f'  {c:4d}  {s}')
    print(f'distinct base symbols in residual: {len(sym_hist)}')


if __name__ == '__main__':
    main()
