#!/usr/bin/env python3
"""rez_types_diag.py — T1 oracle harness for the clean-room TypesIIGS.r
replacement (docs/REZ_TYPES_PLAN.md).

For every resource in the Sys.Resources corpus source, gens its body AST
against a CANDIDATE type template (from the committed include)
and byte-diffs the result against the golden fork's per-resource data slice
(work/rezcheck.py Fork index).  This is the per-template inner loop: a
template is DONE when every corpus instance of it round-trips byte-exact.

Include path note: since T3 landed, `_common.rincludes()` already points at
the committed clean-room include, so this harness no longer touches the
recovered Apple file at all — the corpus parse AND the candidate decls both
come from `gsasm/rez/include/TypesIIGS.r`.  (During the original
derivation the corpus was parsed against the recovered include for its
`#define` substitutions only — corpus-dictated interface facts; template
structure was derived from the golden byte pairs below.)

    python3 work/rez_types_diag.py            # per-template scoreboard
    python3 work/rez_types_diag.py rPString   # detail: per-resource diffs
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import ensure_repo_on_path, rincludes, sysresources_rez, work_abs
ensure_repo_on_path()

import rezcheck as rc
import rezbuildcheck as rb
from gsasm.rez import parser as P
from gsasm.rez import gen as G

CANDIDATE = os.path.join('gsasm', 'rez', 'include', 'TypesIIGS.r')

# Names for the scoreboard (type number -> conventional template name).
# These are the corpus-dictated identifiers (docs/REZ_TYPES_PLAN.md,
# "Measured contract").
TYPE_NAMES = {
    0x8001: 'rIcon',           0x8003: 'rControlList',
    0x8004: 'rControlTemplate', 0x8006: 'rPString',
    0x8009: 'rMenu',           0x800A: 'rMenuItem',
    0x800B: 'rTextForLETextBox2', 0x800E: 'rWindParam1',
    0x8010: 'rWindColor',      0x8015: 'rAlertString',
    0x8020: 'rErrorString',    0x8029: 'rVersion',
    0x802A: 'rComment',
    0x8027: 'rMyCursor (corpus-local decl)',
}


def _corpus_statements():
    """Parse the corpus source (bootstrap include path, see module doc).
    NB: RezIIGS must be the INT 1 (as rezbuildcheck passes it) — a string
    '1' flips an #if in the include and drops the rControlList/rMenu
    trailing zero-long terminator (measured 2026-07-19)."""
    return P.parse(sysresources_rez(), include_dirs=list(rincludes()),
                   predefined={'RezIIGS': 1})


def _candidate_decls():
    """TypeDecls from the committed candidate include (empty if absent)."""
    if not os.path.exists(CANDIDATE):
        return {}
    stmts = P.parse(CANDIDATE, include_dirs=[os.path.dirname(CANDIDATE)],
                    predefined={'RezIIGS': '1'})
    return {s.typeid: s for s in stmts if isinstance(s, P.TypeDecl)}


def _golden_slices():
    """{(type, id): data_bytes} from the golden Sys.Resources fork."""
    fork = rc.golden_fork(rb.SYSRES_DISK_PATH)
    return {(e.type, e.id): fork.raw[e.offset:e.offset + e.size]
            for e in fork.used}


def _show_pairs(name, limit=4):
    """Derivation view: body AST vs golden bytes for instances of one type."""
    tnum = next((t for t, nm in TYPE_NAMES.items() if nm.split()[0] == name), None)
    if tnum is None:
        print(f'unknown template name {name}'); return
    stmts = _corpus_statements()
    gold = _golden_slices()

    def render(v, d=0):
        tn = type(v).__name__
        pad = '  ' * d
        if tn == 'Num': return f'{pad}Num {v.value:#x}'
        if tn == 'StrLit': return f'{pad}Str {v.value!r}'
        if tn == 'HexLit': return f'{pad}Hex <{len(v.value)}B> {v.value[:12].hex()}...'
        if tn == 'Name': return f'{pad}Name {v.name}'
        if tn == 'CaseValue':
            return f'{pad}Case {v.name}:\n' + '\n'.join(render(x, d+1) for x in v.values)
        if tn == 'GroupValue':
            return f'{pad}Group{{\n' + '\n'.join(render(x, d+1) for x in v.values) + f'\n{pad}}}'
        return f'{pad}{tn} {vars(v)}'

    shown = 0
    for s in stmts:
        if not isinstance(s, P.ResourceStmt) or s.typeid != tnum: continue
        # evaluate id via a throwaway gen against ANY decl? just show AST id expr
        print(f'--- {name} @ {s.file}:{s.line}')
        for v in s.values:
            print(render(v, 1))
        # golden: find by scanning gold keys of this type in stmt order — print all ids
        shown += 1
        if shown >= limit: break
    print(f'\n(golden slices for type {tnum:#x}:)')
    for (t, rid), g in sorted(gold.items()):
        if t == tnum:
            print(f'  id={rid:#010x} {len(g):4}B: {g[:48].hex()}{"..." if len(g)>48 else ""}')


def main():
    if len(sys.argv) > 2 and sys.argv[1] == '--pairs':
        _show_pairs(sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 4)
        return
    want = sys.argv[1] if len(sys.argv) > 1 else None
    stmts = _corpus_statements()
    cand = _candidate_decls()
    # corpus-LOCAL decls only (rMyCursor): a decl pulled in from the Apple
    # include must NOT satisfy the scoreboard — the whole point is that the
    # candidate replaces it.
    src_file = os.path.basename(sysresources_rez()).lower()
    local = {s.typeid: s for s in stmts if isinstance(s, P.TypeDecl)
             and os.path.basename(getattr(s, 'file', '') or '').lower() == src_file}
    gold = _golden_slices()

    per = {}   # typeid -> [ok, bad, nogen]
    details = []
    for s in stmts:
        if not isinstance(s, P.ResourceStmt):
            continue
        t = s.typeid
        decl = cand.get(t) or local.get(t)
        row = per.setdefault(t, [0, 0, 0])
        if decl is None:
            row[2] += 1
            continue
        try:
            entries = G.generate([decl, s])
            ent = entries[0]
            data = ent.data
            rid = ent.rid
        except Exception as e:
            row[1] += 1
            details.append((t, '?', f'gen error: {e}'))
            continue
        g = gold.get((ent.rtype, rid))
        if g is None:
            details.append((t, rid, 'no golden slice (id not in fork index)'))
            row[1] += 1
        elif data == g:
            row[0] += 1
        else:
            row[1] += 1
            i = next((k for k in range(min(len(data), len(g)))
                      if data[k] != g[k]), min(len(data), len(g)))
            details.append((t, rid,
                            f'built {len(data)}B gold {len(g)}B; first diff '
                            f'@{i:#x}: built {bytes(data[max(0,i-4):i+8]).hex()} '
                            f'gold {g[max(0,i-4):i+8].hex()}'))

    total_ok = total = 0
    print(f"{'template':<34} {'exact':>7} {'bad':>5} {'no-tmpl':>8}")
    for t in sorted(per):
        ok, bad, nogen = per[t]
        nm = TYPE_NAMES.get(t, f'${t:04X}')
        src = ' [candidate]' if t in cand else (' [local]' if t in local else '')
        print(f"{nm:<34} {ok:>7} {bad:>5} {nogen:>8}{src}")
        total_ok += ok; total += ok + bad + nogen
    print(f"\n{total_ok}/{total} resources byte-exact against candidate templates")
    if want:
        wt = [t for t, nm in TYPE_NAMES.items() if nm.split()[0] == want]
        for t, rid, msg in details:
            if not wt or t in wt:
                print(f"  {TYPE_NAMES.get(t, hex(t))} id={rid}: {msg}")


if __name__ == '__main__':
    main()
