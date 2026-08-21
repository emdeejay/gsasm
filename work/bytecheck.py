#!/usr/bin/env python3
"""Round-trip byte validation: compare the engine's emitted instruction bytes
against the listing's Object Code column, aligned by source text via difflib.

Reports opcode mismatches (addressing-mode errors) and operand mismatches
(value errors), ignoring relocatable operands (listing shows all-FF).

The "modules with 0 opcode errors" count is NOT the module total: a module
containing no 65816 instructions (a pure equates file, a DC-only table) has
nothing for this harness to compare and reaches neither the numerator nor the
bad-byte tally.  Those modules are listed by name at the end of the run,
alongside two counters that must stay zero — modules whose assembly raised,
and modules where only one side yields instruction rows."""
import sys, os, glob, re, difflib, collections
from _common import ensure_repo_on_path, gate_result, romsrc_incs, romsrc_root
ensure_repo_on_path()
from gsasm import asm
from gsasm import m65816

ROOT = romsrc_root()
INCS = romsrc_incs(ROOT)
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
    # Why a module can be counted in `total` and still not reach `perfect`
    # WITHOUT contributing a single bad byte.  This used to be invisible: the
    # headline read "modules: 80   modules with 0 opcode errors: 77" next to
    # "OPCODE bytes: ... 0 bad", and the 3 were simply gone, with no way to
    # tell an unassemblable module from one that has nothing to compare.
    unassembled = []      # assembly raised: measured NOTHING, and that is a bug
    no_instructions = []  # both sides agree there are no 65816 instructions
    asymmetric = []       # one side has instruction rows and the other does not
    for lst in sorted(glob.glob(ROOT + '/**/*.lst', recursive=True)):
        src = lst[:-4]
        if not os.path.exists(src):
            continue
        total += 1
        rel = os.path.relpath(lst, ROOT)
        try:
            a = asm.assemble(src, INCS)
        except Exception as exc:  # noqa: BLE001
            unassembled.append(f'{rel}  {type(exc).__name__}: {exc}')
            continue
        R = listing_instrs(lst)
        M = engine_instrs(a)
        if not R and not M:
            no_instructions.append(rel)
        elif not R or not M:
            asymmetric.append(
                f'{rel}  listing-rows={len(R)} engine-rows={len(M)}')
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

    # ---- account for every module the "0 opcode errors" count leaves out ----
    #
    # The three that show up here today are NOT unmeasured code; they are
    # modules with no 65816 instructions in them at all, so both sides of the
    # comparison are correctly empty:
    #
    #   sys.equs.asm      466 EQU lines, nothing else.  A pure equates file:
    #                     it emits no bytes whatsoever.
    #   QD/CallTable.asm  218 DC.L entries — the QuickDraw II call dispatch
    #                     table.  Data, zero mnemonics.
    #   QD/font.asm       536 DC.W + 69 DC.B — the built-in font bitmap.
    #                     Data, zero mnemonics.
    #
    # So this is not a coverage gap in what THIS harness measures (opcode
    # bytes): there are no opcodes to measure.  The two data modules' bytes are
    # covered where data belongs — they assemble into the ROM image that
    # work/buildrom.py verifies byte-identical.  What was wrong was only that
    # the arithmetic 80 = 77 + 3 had no printed explanation, and that the same
    # silence covered two conditions that are NOT benign: a module whose
    # assembly raised, and a module where one side yields instruction rows and
    # the other does not.  Those get counters, and `gate_result` accepts zero
    # of each.  No `accepted=3` is minted for the no-instruction modules: they
    # are not a residual to tolerate, they are a category, and a fourth data
    # module joining them is not a regression.
    print(f"\nmodules with no 65816 instructions "
          f"(nothing for this harness to measure): {len(no_instructions)}")
    for rel in no_instructions:
        print(f"  {rel}")
    print(f"modules whose assembly raised: {len(unassembled)}")
    for line in unassembled:
        print(f"  {line}")
    print(f"modules where only ONE side has instruction rows: {len(asymmetric)}")
    for line in asymmetric:
        print(f"  {line}")

    # 745 accepted operand deltas: known-benign relocation-base differences
    # (the listing's operand is resolved against a different base than the
    # engine's), docs/REFACTORING.md 0.  Opcodes accept nothing.
    # Nothing accepted for the two counters above either: a module that will
    # not assemble measures NOTHING while still counting toward `modules:`,
    # and a one-sided row count means the listing and the engine disagree about
    # whether there is code here — both are regressions, not residuals.
    return gate_result(opcode_bytes=op_bad, operand_values=(opd_bad, 745),
                       opcode_modules_unassembled=len(unassembled),
                       opcode_modules_asymmetric=len(asymmetric))


if __name__ == '__main__':
    sys.exit(main())
