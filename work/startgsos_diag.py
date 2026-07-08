"""startgsos_diag.py — diagnose the Start.GS.OS residual and test whether a
GLOBAL kernel symtab (union of scm/bank0/device.dispatcher/... exports) closes
GQuit's cross-module externals.  This is the linkOS scoping experiment.

Run: python3 work/startgsos_diag.py
"""
import os, sys, re
sys.path.insert(0, '.'); sys.path.insert(0, 'work')
from gsasm import asm as _asm, omf as _omf, linkiigs as _lnk

import kernelcheck as kc

GS = kc.GS


def build_start_gsos(gq_extern=None):
    """Build Start.GS.OS = cat(scm.bin.8..11) with an optional extern seed."""
    gquit_obj, gquit_asm = kc._assemble(f'{GS}/OS/GQuit/GQuit.src',
                                        sysdate=kc.BUILD_SYSDATE)
    gq_segs = kc._parse_obj_segs(gquit_obj)
    gq_groups = _lnk.group_load_segments(gq_segs)
    if gq_extern is None:
        gq_extern = kc._full_symtab(gquit_asm)
    parts = []
    for gname in ('seg_gldr', 'seg_b0', 'seg_e1', 'seg_e0'):
        sel = kc._select_group(gq_groups, gname)
        code = kc._link_groups(sel, extern=gq_extern)
        if gname in kc.GQUIT_PADDED_GROUPS:
            code = kc._build_with_end_padding(code, sel[0]['org'], sel[-1]['org'])
        parts.append(code)
    return b''.join(parts), gquit_asm


def gold_start_gsos():
    path = kc._find_golden('Start.GS.OS')
    return open(path, 'rb').read() if path else None


def diff_runs(gold, ours):
    n = min(len(gold), len(ours))
    ds = [i for i in range(n) if gold[i] != ours[i]]
    runs = []
    for i in ds:
        if runs and i <= runs[-1][1] + 3:
            runs[-1][1] = i
        else:
            runs.append([i, i])
    return ds, runs, len(gold), len(ours)


def main():
    kc.ensure_golden()
    gold = gold_start_gsos()
    if not gold:
        print('no golden Start.GS.OS'); return

    # ---- baseline (current kernelcheck) ----
    ours, gquit_asm = build_start_gsos()
    ds, runs, lg, lo = diff_runs(gold, ours)
    print(f'=== BASELINE: gold {lg}B ours {lo}B — {len(ds)} diff bytes in {len(runs)} runs ===')
    for s, e in runs[:40]:
        print(f'  @0x{s:04x}(+{e-s+1}): gold {gold[s:e+3].hex()} ours {ours[s:e+3].hex()}')

    # ---- GQuit imports ----
    imports = sorted(gquit_asm.imports)
    print(f'\n=== GQuit IMPORTs ({len(imports)}) ===')
    print(' ', ', '.join(imports))

    # ---- assemble the other kernel modules, collect their symbol tables ----
    others = {
        'scm':    f'{GS}/OS/SCM/SCM.src',
        'bank0':  f'{GS}/OS/BankZero/Bank0.src',
        'device': f'{GS}/OS/DeviceDispatcher/NewDispatcher.src',
        'cache':  f'{GS}/OS/CacheManager/Cache.Src',
    }
    global_syms = {}
    for tag, path in others.items():
        if not os.path.exists(path):
            # try to locate
            cands = []
            base = os.path.dirname(path)
            for dp, _, fs in os.walk(f'{GS}'):
                for f in fs:
                    if f.lower() == os.path.basename(path).lower():
                        cands.append(os.path.join(dp, f))
            path = cands[0] if cands else path
        if not os.path.exists(path):
            print(f'  [{tag}] source not found: {path}'); continue
        try:
            _obj, a = kc._assemble(path)
            st = kc._full_symtab(a)
            global_syms.update({k: v for k, v in st.items() if k not in global_syms})
            print(f'  [{tag}] {len(st)} symbols  (e.g. INIT_SCM={st.get("INIT_SCM")})')
        except Exception as exc:
            print(f'  [{tag}] assemble FAILED: {exc}')

    # ---- which imports are resolvable from the global symtab? ----
    print(f'\n=== import resolution from global kernel symtab ===')
    resolved = {}
    for imp in imports:
        v = global_syms.get(imp.upper())
        if v is not None:
            resolved[imp.upper()] = v
        print(f'  {imp:22s} -> {("0x%x" % v) if v is not None else "UNRESOLVED"}')

    # ---- experiment: seed GQuit link with GQuit symtab + global kernel exports ----
    seed = dict(kc._full_symtab(gquit_asm))
    seed.update(resolved)                     # cross-module externs win where present
    ours2, _ = build_start_gsos(gq_extern=seed)
    ds2, runs2, _, lo2 = diff_runs(gold, ours2)
    print(f'\n=== WITH GLOBAL SYMTAB SEED: ours {lo2}B — {len(ds2)} diff bytes in {len(runs2)} runs '
          f'(was {len(ds)}) ===')
    for s, e in runs2[:25]:
        print(f'  @0x{s:04x}(+{e-s+1}): gold {gold[s:e+3].hex()} ours {ours2[s:e+3].hex()}')


if __name__ == '__main__':
    main()
