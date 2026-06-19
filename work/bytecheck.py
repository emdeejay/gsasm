#!/usr/bin/env python3
"""Round-trip byte validation: compare the engine's emitted instruction bytes
against the listing's Object Code column, aligned by source text via difflib.

Reports opcode mismatches (addressing-mode errors) and operand mismatches
(value errors), ignoring relocatable operands (listing shows all-FF)."""
import sys, os, glob, re, difflib, collections
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from gsasm import asm
from gsasm import m65816

ROOT = 'work/romsrc/GS_ROM'
INCS = ['work/includes'] + [d for d, _, _ in os.walk(ROOT)]
MN = set(x.lower() for x in m65816.MNEMONICS)


def norm(s):
    s, _ = asm.strip_comment(s)
    return re.sub(r'\s+', ' ', s.strip().lower())


def listing_instrs(lst):
    """[(opcode, operand_value_or_None, nbytes, normsrc)] for instruction lines."""
    rows = []
    for ln in asm.read_text(lst).split('\n'):
        m = re.match(r'^([0-9A-Fa-f]{5}) ([0-9A-Fa-f]{4}) (.{0,22})', ln)
        if not m:
            continue
        objfield = m.group(3)
        src = ln.split('\t', 1)[1] if '\t' in ln else ln[34:]
        n = norm(src)
        toks = n.split()
        op = toks[0] if toks else ''
        if op not in MN and (len(toks) < 2 or toks[1] not in MN):
            continue
        hexs = objfield.split()
        if not hexs or not re.fullmatch(r'[0-9A-Fa-f]{2}', hexs[0]):
            continue
        opcode = int(hexs[0], 16)
        operand = None
        nb = 0
        if len(hexs) > 1 and re.fullmatch(r'[0-9A-Fa-f]{2,6}', hexs[1]) and len(hexs[1]) in (2, 4, 6):
            operand = int(hexs[1], 16)
            nb = len(hexs[1]) // 2
        rows.append((opcode, operand, nb, n))
    return rows


def engine_instrs(a):
    rows = []
    for loc, ln, b in a.emitted:
        if (ln.op or '').upper() not in m65816.MNEMONICS:
            continue
        opcode = b[0]
        operand = int.from_bytes(b[1:], 'little') if len(b) > 1 else None
        text = ((ln.label + ' ') if ln.label else '') + ln.op + ' ' + (ln.operand or '')
        rows.append((opcode, operand, len(b) - 1, norm(text)))
    return rows


def main():
    op_ok = op_bad = opd_ok = opd_bad = 0
    badops = collections.Counter()
    examples = {}
    perfect = 0
    total = 0
    for lst in sorted(glob.glob(ROOT + '/**/*.lst', recursive=True)):
        src = lst[:-4]
        if not os.path.exists(src):
            continue
        total += 1
        try:
            a = asm.assemble(src, INCS)
        except Exception:
            continue
        R = listing_instrs(lst)
        M = engine_instrs(a)
        sm = difflib.SequenceMatcher(a=[r[3] for r in R], b=[m[3] for m in M], autojunk=False)
        mod_opbad = 0
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag != 'equal':
                continue
            for k in range(i2 - i1):
                ro, rv, rnb, rsrc = R[i1 + k]
                mo, mv, mnb, _ = M[j1 + k]
                if ro == mo:
                    op_ok += 1
                else:
                    op_bad += 1
                    mod_opbad += 1
                    key = rsrc.split()[0] if rsrc.split()[0] in MN else (rsrc.split()[1] if len(rsrc.split()) > 1 else '?')
                    badops[key] += 1
                    examples.setdefault(key, (rsrc, ro, mo))
                # operand: skip relocatable (all-FF) and unresolved
                if rv is not None and mv is not None and rnb == mnb:
                    allf = (rv == (1 << (8 * rnb)) - 1)
                    if not allf:
                        if rv == mv:
                            opd_ok += 1
                        else:
                            opd_bad += 1
        if R and mod_opbad == 0:
            perfect += 1
    print(f"modules: {total}   modules with 0 opcode errors: {perfect}")
    print(f"OPCODE bytes:  {op_ok} ok / {op_bad} bad  ({100*op_ok//max(1,op_ok+op_bad)}%)")
    print(f"OPERAND values (resolved, non-reloc): {opd_ok} ok / {opd_bad} bad  ({100*opd_ok//max(1,opd_ok+opd_bad)}%)")
    print("\ntop opcode-mismatch sources:")
    for k, c in badops.most_common(12):
        ex, ro, mo = examples[k]
        print(f"  {c:4d}  {k:6s} listing-op={ro:02X} engine-op={mo:02X}  e.g. {ex[:46]}")


if __name__ == '__main__':
    main()
