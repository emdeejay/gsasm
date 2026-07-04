"""OMF v2.0 object-file parser (for understanding/validating AsmIIgs output)
and emitter. Object records are decoded so we can reproduce them byte-exactly.
"""
import struct
import re

# A data operand is relocatable only if it is a single symbol with an optional
# constant addend; complex arithmetic (X-Y, X/4, ...) is a computed literal.
_SIMPLE_REF = re.compile(r'^([A-Za-z_~@?.][\w~@?.]*)\s*([+-]\s*\$?[0-9A-Fa-f]+)?$')

# OMF segment-header field offsets (v2.0). Verified against AsmIIgs .obj output.
def parse_header(d):
    h = {}
    h['BYTECNT'] = struct.unpack('<I', d[0:4])[0]
    h['RESSPC'] = struct.unpack('<I', d[4:8])[0]
    h['LENGTH'] = struct.unpack('<I', d[8:12])[0]
    # d[12] undefined
    h['LABLEN'] = d[13]
    h['NUMLEN'] = d[14]
    h['VERSION'] = d[15]
    h['BANKSIZE'] = struct.unpack('<I', d[16:20])[0]
    h['KIND'] = struct.unpack('<H', d[20:22])[0]
    h['ORG'] = struct.unpack('<I', d[24:28])[0]
    h['ALIGN'] = struct.unpack('<I', d[28:32])[0]
    h['NUMSEX'] = d[32]
    h['SEGNUM'] = struct.unpack('<H', d[34:36])[0]
    h['ENTRY'] = struct.unpack('<I', d[36:40])[0]
    h['DISPNAME'] = struct.unpack('<H', d[40:42])[0]
    h['DISPDATA'] = struct.unpack('<H', d[42:44])[0]
    dn = h['DISPNAME']
    h['LOADNAME'] = d[dn:dn+10]
    sl = d[dn+10]
    h['SEGNAME'] = d[dn+11:dn+11+sl]
    return h


REC = {0xE0: 'ALIGN', 0xE1: 'ORG', 0xE2: 'RELOC', 0xE3: 'INTERSEG',
       0xE6: 'GLOBAL', 0xE7: 'GEQU', 0xEB: 'EXPR', 0xEC: 'ZEXPR',
       0xED: 'BEXPR', 0xEE: 'RELEXPR', 0xEF: 'LOCAL', 0xF0: 'EQU',
       0xF1: 'DS', 0xF2: 'LCONST', 0xF3: 'LEXPR', 0xF4: 'ENTRY',
       0xF5: 'cRELOC', 0xF6: 'cINTERSEG', 0xF7: 'SUPER', 0x00: 'END'}


def parse_records(d, start, numlen=4, lablen=0):
    """Yield (offset, opcode_name, detail) for each body record."""
    i = start
    n = len(d)
    out = []
    while i < n:
        op = d[i]
        at = i
        i += 1
        if op == 0x00:
            out.append((at, 'END', None)); break
        if 1 <= op <= 0xDF:                     # CONST: op literal bytes
            out.append((at, 'CONST', d[i:i+op])); i += op; continue
        name = REC.get(op, f'?{op:02X}')
        if op == 0xF2:                          # LCONST: numlen count + bytes
            cnt = int.from_bytes(d[i:i+numlen], 'little'); i += numlen
            out.append((at, 'LCONST', d[i:i+cnt])); i += cnt; continue
        if op == 0xF1:                          # DS: numlen count of zeros
            cnt = int.from_bytes(d[i:i+numlen], 'little'); i += numlen
            out.append((at, 'DS', cnt)); continue
        if op == 0xE1:                          # ORG
            out.append((at, 'ORG', int.from_bytes(d[i:i+numlen], 'little'))); i += numlen; continue
        if op == 0xE0:                          # ALIGN
            out.append((at, 'ALIGN', int.from_bytes(d[i:i+numlen], 'little'))); i += numlen; continue
        if op in (0xE2, 0xF5):                  # RELOC / cRELOC
            if op == 0xE2:
                size = d[i]; shift = d[i+1]
                off = int.from_bytes(d[i+2:i+2+numlen], 'little')
                ref = int.from_bytes(d[i+2+numlen:i+2+2*numlen], 'little')
                i += 2 + 2*numlen
            else:                               # cRELOC: 1+1+2+2
                size = d[i]; shift = d[i+1]
                off = int.from_bytes(d[i+2:i+4], 'little')
                ref = int.from_bytes(d[i+4:i+6], 'little')
                i += 6
            out.append((at, name, (size, shift, off, ref))); continue
        if op in (0xE3, 0xF6):                  # INTERSEG / cINTERSEG
            if op == 0xE3:
                size = d[i]; shift = d[i+1]
                off = int.from_bytes(d[i+2:i+2+numlen], 'little')
                fileno = int.from_bytes(d[i+2+numlen:i+4+numlen], 'little')
                segno = int.from_bytes(d[i+4+numlen:i+6+numlen], 'little')
                segoff = int.from_bytes(d[i+6+numlen:i+6+2*numlen], 'little')
                i += 6 + 2*numlen
            else:                               # cINTERSEG: 1+1+2+1+2
                size = d[i]; shift = d[i+1]
                off = int.from_bytes(d[i+2:i+4], 'little')
                segno = d[i+4]
                segoff = int.from_bytes(d[i+5:i+7], 'little')
                fileno = 1
                i += 7
            out.append((at, name, (size, shift, off, fileno, segno, segoff))); continue
        if op == 0xEE:                          # RELEXPR: size(1) + origin(numlen) + expr
            size = d[i]; i += 1
            origin = int.from_bytes(d[i:i+numlen], 'little'); i += numlen
            expr, i = _read_expr(d, i, numlen)
            out.append((at, name, (size, origin, expr))); continue
        if op in (0xEB, 0xEC, 0xED, 0xF3):      # EXPR-family: 1 size byte + expr
            size = d[i]; i += 1
            expr, i = _read_expr(d, i, numlen)
            out.append((at, name, (size, expr))); continue
        if op in (0xE6, 0xE7, 0xEF, 0xF0, 0xF4):   # symbol records
            ln = d[i]; lab = d[i+1:i+1+ln]; i += 1+ln
            length = struct.unpack('<H', d[i:i+2])[0]  # LENGTH attribute (2)
            typ = d[i+2]; priv = d[i+3]; i += 4
            detail = {'label': lab.decode('mac_roman'), 'len': length,
                      'type': typ, 'priv': priv}
            if op in (0xE7, 0xF0):              # GEQU/EQU carry an expression
                expr, i = _read_expr(d, i, numlen)
                detail['expr'] = expr
            out.append((at, name, detail)); continue
        out.append((at, name, 'UNHANDLED')); break
    return out, i


def _read_expr(d, i, numlen):
    """Decode an OMF expression (sequence of operators terminated by 0x00)."""
    ops = []
    while i < len(d):
        o = d[i]; i += 1
        if o == 0x00:
            ops.append('end'); break
        if o == 0x81:                            # push numlen literal
            v = int.from_bytes(d[i:i+numlen], 'little'); i += numlen
            ops.append(('lit', v)); continue
        if o in (0x83, 0x84, 0x85, 0x86, 0x87):  # push label-ish (weak/value/len)
            ln = d[i]; lab = d[i+1:i+1+ln]; i += 1+ln
            ops.append((f'sym{o:02X}', lab.decode('mac_roman'))); continue
        if o == 0x82:
            ops.append('loc'); continue
        ops.append(('op', o))
    return ops, i


def _num(v, n=4):
    return bytes((v >> (8 * i)) & 0xFF for i in range(n))


def _omfstr(s):
    b = s.encode('mac_roman')
    return bytes([len(b)]) + b


def _linear_reloc(asm, text):
    """Decompose `text` into (reloc_label, const_addend) when it is linear in
    exactly ONE relocatable label with coefficient +1 — e.g.
    `Purgemask-ZombieRetry-1` -> ('Purgemask', -4) when ZombieRetry is a constant
    equate. Returns None when there isn't exactly one reloc label, the value can't
    be computed, or the label's coefficient isn't +1 (subtraction of the label).

    Classifier over linear_decompose: exactly one term, coeff +1, no PC term."""
    dec = linear_decompose(asm, text)
    if dec is None:
        return None
    terms, K, pc_coeff = dec
    # exactly one relocatable symbol, coefficient +1, no PC term
    if len(terms) != 1 or pc_coeff != 0:
        return None
    L, coeff = next(iter(terms.items()))
    if coeff != 1:
        return None
    # Undefined externals: linear_decompose assigns them value 0, so K = V.
    # But _linear_reloc requires the label to have a known value (Lval is not None).
    Lval = asm.resolve(L)
    if Lval is None:
        return None
    # addend = K (linear_decompose already accounts for Lval in K computation)
    return (L, K)


def _mul_reloc_expr(asm, text, segname):
    """Try to decompose `text` as (SEGNAME + rel) * N + K for a single label in
    the current ORG segment with coefficient N != 0,1. Returns expression ops
    bytes (without the end-of-expr 0x00) or None."""
    # Classifier over linear_decompose — keeps same scope tests and emit bytes.
    # Scope: exactly one relocatable symbol (label/import/equ), coeff > 1,
    # symbol value in the current ORG'd segment.
    import re as _re
    from . import expr as _expr
    if asm._rseg is None:
        return None
    # Candidate: single identifier with sym_kind in ('label', 'equ')
    # (equates in an ORG segment alias absolute addresses and must be treated
    # as potentially relocatable — linear_decompose excludes equates from terms
    # since they are constants, so we handle them here with finite difference).
    idents = list(dict.fromkeys(
        _re.findall(r'(?<![0-9A-Fa-f$])[A-Za-z_~@?.][\w~@?.]*', text)))
    reloc = [i for i in idents if asm.sym_kind(i) in ('label', 'equ')]
    if len(reloc) != 1:
        return None
    L = reloc[0]
    Lval = (asm.resolve(L) or 0) & 0xFFFFFF
    if not _in_org_seg(asm, Lval):
        return None
    # Coefficient via finite difference (same as original)
    def _res(n, bump=0):
        return (Lval + bump) if n.upper() == L.upper() else asm.resolve(n)
    V = _expr.try_eval(text, lambda n: _res(n, 0), asm.loc)
    V1 = _expr.try_eval(text, lambda n: _res(n, 1), asm.loc)
    if V is None or V1 is None:
        return None
    N = V1 - V                                   # coefficient of L in expr
    if N <= 1:                                   # +1 handled by _linear_reloc
        return None
    K = V - N * Lval
    seg_org = asm.segs[asm._rseg].org or 0
    rel = Lval - seg_org
    ops = bytearray()
    ops += bytes([0x83]) + _omfstr(segname)
    if rel:
        ops += bytes([0x81]) + _num(rel & 0xFFFFFFFF) + bytes([0x01])
    ops += bytes([0x81]) + _num(N & 0xFFFFFFFF) + bytes([0x03])
    K_m = K & 0xFFFFFFFF
    if K_m:
        ops += bytes([0x81]) + _num(K_m) + bytes([0x01])
    return bytes(ops)


def _diff_reloc(asm, text):
    """Two-relocatable-label difference `A - B` (coefficients +1/-1, both DEFINED,
    and in DIFFERENT segments) -> OMF expression ops computing the LINK-TIME layout
    difference (SEGNAME_A+offA) - (SEGNAME_B+offB) [+ K]. Returns ops bytes (without
    the trailing 0x00) or None.

    Scoped to CROSS-segment differences only: within one segment the assembly-time
    value is already final (and correct as a baked literal), so those are left
    alone to avoid perturbing the byte-exact ROM. Cross-segment diffs otherwise
    bake to the assembly-time value (both labels segment-relative), which is wrong
    once the linker places the segments apart (e.g. `DC.W getfstname-jump_table`)."""
    import re as _re
    from . import expr as _expr
    idents = list(dict.fromkeys(
        _re.findall(r'(?<![0-9A-Fa-f$])[A-Za-z_~@?.][\w~@?.]*', text)))
    reloc = [i for i in idents if asm.sym_kind(i) == 'label'
             and asm.symseg.get(asm._symkey(i)) is not None]
    if len(reloc) != 2:
        return None
    A, B = reloc
    sa, sb = asm.symseg.get(asm._symkey(A)), asm.symseg.get(asm._symkey(B))
    if sa == sb:                                   # same segment: literal is final
        return None
    if (asm.segs[sa].org or 0) or (asm.segs[sb].org or 0):
        return None                                # ORG'd (absolute) diff is final
    av, bv = asm.resolve(A), asm.resolve(B)
    if av is None or bv is None:                   # both must be defined
        return None

    def bumped(da, db):
        def r(n):
            u = n.upper()
            if u == A.upper():
                return (asm.resolve(A) or 0) + da
            if u == B.upper():
                return (asm.resolve(B) or 0) + db
            return asm.resolve(n)
        return _expr.try_eval(text, r, asm.loc)
    v = bumped(0, 0)
    if v is None:
        return None
    if bumped(0x100, 0) != v + 0x100:              # coefficient of A must be +1
        return None
    if bumped(0, 0x100) != v - 0x100:              # coefficient of B must be -1
        return None

    def locops(name):
        nu = asm._symkey(name)
        seg = asm.segs[asm.symseg[nu]]
        off = ((asm.resolve(nu) or 0) & 0xFFFFFF) - (seg.org or 0)
        o = bytes([0x83]) + _omfstr((seg.name or '').upper())
        if off:
            o += bytes([0x81]) + _num(off & 0xFFFFFFFF) + bytes([0x01])
        return o
    K = (v - (((av & 0xFFFFFF) - (bv & 0xFFFFFF)))) & 0xFFFFFFFF  # residual constant
    ops = bytearray()
    ops += locops(A)
    ops += locops(B)
    ops += bytes([0x02])                           # SUB: A - B
    if K:
        ops += bytes([0x81]) + _num(K) + bytes([0x01])
    return bytes(ops)


def _pc_rel_const(asm, text):
    """True if `text` is a same-segment, PC-relative CONSTANT — e.g. `label-*`
    (an offset-table entry: the byte distance from here to `label`). It references
    `*` (the current PC) and the segment base cancels (both `label` and `*` shift
    with it), so the value is fixed at assembly time and must be emitted as a
    LITERAL, not a relocation. gsasm already bakes the correct value; without this
    guard _linear_reloc would relocate it as `label + (-*)` and re-evaluate `*` at
    end-of-assembly (the wrong PC), producing a wrong offset.

    Classifier over linear_decompose: the base cancels iff the sum of all
    same-segment label coefficients plus pc_coeff is zero."""
    if '*' not in text:                            # only PC-relative expressions
        return False
    seg = asm._rseg
    if seg is None:
        return False
    dec = linear_decompose(asm, text)
    if dec is None:
        # Fall back to original bump-based check when decompose fails
        from . import expr as _expr
        def res(n, d):
            u = asm._symkey(n)
            v = asm.resolve(n)
            if v is not None and asm.symseg.get(u) == seg:
                return v + d
            return v
        pc = asm.loc
        v0 = _expr.try_eval(text, lambda n: res(n, 0), pc)
        v1 = _expr.try_eval(text, lambda n: res(n, 0x1000), pc + 0x1000)
        return v0 is not None and v0 == v1
    terms, K, pc_coeff = dec
    # Base cancels iff: sum of same-segment label coefficients + pc_coeff == 0
    same_seg_sum = pc_coeff
    for name, coeff in terms.items():
        nu = asm._symkey(name)
        if asm.symseg.get(nu) == seg:
            same_seg_sum += coeff
    return same_seg_sum == 0


def linear_decompose(asm, text):
    """Decompose `text` into a linear combination of relocatable symbols plus
    a constant, using finite difference.

    Returns (terms, K, pc_coeff) where:
        terms      dict {name: coeff}  for each RELOCATABLE symbol (label /
                   import / undef-external); coefficient by finite difference
                   (resolve, then bump by 0x100).  Constants and equates fold
                   into K.
        K          residual constant  (V − sum(coeff_i * val_i) at assembly time)
        pc_coeff   coefficient of the current PC `*` (bump asm.loc by 0x100).

    Returns None if the expression cannot be evaluated with current symbol values.
    """
    import re as _re
    from . import expr as _expr

    # Collect all identifiers in the expression (avoiding hex-literal false positives)
    idents = list(dict.fromkeys(
        _re.findall(r'(?<![0-9A-Fa-f$])[A-Za-z_~@?.][\w~@?.]*', text)))

    # Partition into relocatable vs constant symbols
    reloc_names = [i for i in idents
                   if asm.sym_kind(i) in ('label', 'import') or _undef_external(asm, i)]

    # Base value at current symbol values
    def base_res(n):
        return asm.resolve(n)

    V = _expr.try_eval(text, base_res, asm.loc)
    if V is None:
        return None

    # Determine pc_coeff by bumping asm.loc
    pc_orig = asm.loc
    V_pc = _expr.try_eval(text, base_res, pc_orig + 0x100)
    pc_coeff = 0
    if V_pc is not None:
        pc_coeff = (V_pc - V)  # should be 0, 0x100, or -0x100

    # Compute coefficient of each relocatable symbol by finite difference
    terms = {}
    for name in reloc_names:
        val = asm.resolve(name)
        if val is None:
            # undef-external: treat its value as 0 for coeff computation
            val = 0

        def bumped_res(n, _name=name, _val=val):
            u = n.upper()
            if u == _name.upper():
                return _val + 0x100
            return asm.resolve(n)

        V2 = _expr.try_eval(text, bumped_res, asm.loc)
        if V2 is None:
            return None
        coeff = (V2 - V)  # should be a multiple of 0x100
        if coeff != 0:
            terms[name] = coeff

    # K = V - sum(coeff_i * val_i)  (the residual constant)
    K = V
    for name, coeff in terms.items():
        val = asm.resolve(name) or 0
        # coeff is in units of 0x100 (raw finite-difference), convert back
        K -= (coeff // 0x100) * val
    # Normalise coefficients from finite-difference units to actual units
    terms = {name: coeff // 0x100 for name, coeff in terms.items()}
    # Recompute K with normalised coefficients
    K = V
    for name, coeff in terms.items():
        K -= coeff * (asm.resolve(name) or 0)

    return (terms, K, pc_coeff // 0x100 if pc_coeff else 0)


def _expr_for(asm, text, segname, as_data=False, ref_off=None):
    """Build an OMF load-time expression for an operand reference.
    Local labels -> SEGNAME + offset; imports -> name; equates -> literal.
    `as_data` (DC address tables): a same-segment ENTRY referenced by a BACKWARD
    reference (defined before this point, ref_off given) is SEGNAME+offset; a
    FORWARD reference (entry defined later) is by name (the assembler hadn't seen
    the definition yet). For code/branch refs, same-segment ENTRY is by name."""
    import re as _re
    text = text.strip()
    # < > ^ select low/high/bank: the linker computes (sym >> shift)
    shift = 0
    if text[:1] in '<>^':
        shift = {'<': 0, '>': 8, '^': 16}[text[0]]
        text = text[1:].strip()
    # explicit trailing shift: sym>>N (right) or sym<<N (left), e.g. #ListProc>>16
    ms = _re.match(r'^(.*?)\s*(>>|<<)\s*(\d+)$', text)
    if ms:
        text = ms.group(1).strip()
        shift += int(ms.group(3)) if ms.group(2) == '>>' else -int(ms.group(3))
    # a single fully-enclosing paren pair is arithmetic grouping: #(muReturn-1)
    if text.startswith('(') and text.endswith(')'):
        depth = 0
        enclosing = True
        for k, ch in enumerate(text):
            if ch == '(':
                depth += 1
            elif ch == ')':
                depth -= 1
                if depth == 0 and k != len(text) - 1:
                    enclosing = False
                    break
        if enclosing:
            text = text[1:-1].strip()
    # single symbol, optionally  symbol+const
    m = _re.match(r'^([A-Za-z_~@?.][\w~@?.]*)\s*([+\-]\s*\$?[0-9A-Fa-f]+)?$', text)
    name = addend = None
    if m:
        name = m.group(1)
        extra = m.group(2)
        addend = 0
        if extra:
            addend = int(extra.replace(' ', '').replace('$', ''),
                         16 if '$' in extra else 10)
    else:
        dec = _linear_reloc(asm, text)        # one reloc label + constant
        if dec:
            name, addend = dec
        elif not as_data:
            # instruction operand linear in ONE undefined external + a constant,
            # e.g. `lda >arrowMap-UP_ARROW,x` (arrowMap external, UP_ARROW=8 equ):
            # resolve arrowMap by name with addend -8. (Scoped to instructions;
            # DC tables resolve undefined symbols differently.)
            ids = list(dict.fromkeys(
                _re.findall(r'(?<![0-9A-Fa-f$])[A-Za-z_~@?.][\w~@?.]*', text)))
            ext = [i for i in ids if _undef_external(asm, i)]
            if len(ext) == 1:
                from . import expr as _expr
                Lname = ext[0]
                def _res0(n, _L=Lname):
                    return 0 if n.upper() == _L.upper() else asm.resolve(n)
                add = _expr.try_eval(text, _res0, asm.loc)
                if add is not None:
                    name, addend = Lname, add
    ops = bytearray()
    if name is not None:
        kind = asm.sym_kind(name)
        if kind in ('label', None):           # local/relocatable label
            nu = asm._symkey(name)            # scoped key (@-labels -> scope+name)
            # a label local to the current segment is same-seg even if the name
            # is also defined elsewhere (symseg is global/last-wins for dups)
            local_here = asm._rseg is not None and nu in asm.seg_local.get(asm._rseg, {})
            same_seg = local_here or (asm.symseg.get(nu) is not None and
                        (asm.segs[asm.symseg[nu]].name or '').upper() == segname)
            base = (asm.segs[asm._rseg].org or 0) if asm._rseg is not None else 0
            def_off = ((asm.resolve(nu) or 0) & 0xFFFFFF) - base
            # a ref to a same-seg GLOBAL (ENTRY or EXPORT) is by-name only when
            # FORWARD (defined after this point — the assembler emitted it by
            # name before seeing the definition); backward refs use SEGNAME+
            # offset. When ref_off is unknown (e.g. branches via RELEXPR) keep
            # by-name.
            is_global = nu in asm.entries or nu in asm.exports
            entry_byname = (is_global and
                            (ref_off is None or def_off > ref_off))
            if same_seg and entry_byname:
                # a same-segment ENTRY is referenced by name; an EXPORT-only
                # label is still referenced as SEGNAME+offset internally
                ops += bytes([0x83]) + _omfstr(nu)
                if addend:
                    ops += bytes([0x81]) + _num(addend) + bytes([0x01])
            elif same_seg:                     # purely-local label: SEGNAME + offset
                # in an ORG'd segment the label's value is absolute; the OMF
                # offset is segment-relative, so subtract the segment ORG
                base = (asm.segs[asm._rseg].org or 0) if asm._rseg is not None else 0
                off = ((asm.resolve(nu) or 0) & 0xFFFFFF) + addend - base
                ops += bytes([0x83]) + _omfstr(segname)
                if off:
                    ops += bytes([0x81]) + _num(off) + bytes([0x01])
            else:                              # label in another segment
                # Labels in data segments (RECORD) are not exposed by name to
                # other segments' linker resolution — emit as SEGNAME + offset.
                # Labels in code segments (PROC) are resolvable by name.
                other_idx = asm.symseg.get(nu)
                other_seg = asm.segs[other_idx] if other_idx is not None else None
                if other_seg is not None and getattr(other_seg, 'is_data', False):
                    other_base = other_seg.org or 0
                    other_off = ((asm.resolve(nu) or 0) & 0xFFFFFF) + addend - other_base
                    ops += bytes([0x83]) + _omfstr((other_seg.name or '').upper())
                    if other_off:
                        ops += bytes([0x81]) + _num(other_off) + bytes([0x01])
                else:
                    ops += bytes([0x83]) + _omfstr(name.upper())
                    if addend:
                        ops += bytes([0x81]) + _num(addend) + bytes([0x01])
        elif kind == 'import':
            ops += bytes([0x83]) + _omfstr(name.upper())
            if addend:
                ops += bytes([0x81]) + _num(addend) + bytes([0x01])
        else:                                  # equate / absolute
            label_v = (asm.resolve(name) or 0) & 0xFFFFFF
            v = label_v + addend
            # Encode as SEGNAME+offset when the label itself lands in the ORG'd
            # segment, even if the addend shifts the sum outside the byte range.
            if _in_org_seg(asm, label_v) or _in_org_seg(asm, v):
                off = v - asm.segs[asm._rseg].org
                ops += bytes([0x83]) + _omfstr(segname)
                if off:
                    ops += bytes([0x81]) + _num(off) + bytes([0x01])
            else:
                ops += bytes([0x81]) + _num(v)
    else:
        diff = _diff_reloc(asm, text)          # cross-seg two-label difference
        if diff is not None:
            ops += diff
        else:
            v = asm.evaluate(text) or 0
            if _in_org_seg(asm, v):            # numeric address into this segment
                off = v - asm.segs[asm._rseg].org
                ops += bytes([0x83]) + _omfstr(segname)
                if off:
                    ops += bytes([0x81]) + _num(off) + bytes([0x01])
            else:
                mul_ops = _mul_reloc_expr(asm, text, segname)
                if mul_ops is not None:
                    ops += mul_ops
                else:
                    ops += bytes([0x81]) + _num(v)
    if shift:                                  # (sym) >> shift  ==  << (-shift)
        ops += bytes([0x81]) + _num((-shift) & 0xFFFFFFFF) + bytes([0x07])
    ops += bytes([0x00])                       # end of expression
    return bytes(ops)


def _core(operand):
    """Reduce an operand to its core address expression (strip #, size prefix,
    indirection and indexing). For an IMMEDIATE operand a leading < > ^ is a
    byte-extraction operator (low/high/bank), NOT a size prefix — keep it so
    _expr_for can emit the proper shift."""
    s = operand.strip()
    immediate = s.startswith('#')
    s = s.lstrip('#')
    if not immediate and s[:1] in '<>|!':
        s = s[1:]
    # for a non-immediate operand, leading ( or [ is indirection — strip it and
    # its matching close. For an immediate, parens are arithmetic (e.g.
    # #(muReturn-1)>>8) and must be left for _expr_for.
    if not immediate and (s.startswith('[') or s.startswith('(')):
        s = s[1:]
        for c in ')]':
            j = s.rfind(c)
            if j >= 0:
                s = s[:j]
    for suf in (',x', ',y', ',s'):
        if s.lower().endswith(suf):
            s = s[:-2]
    s = s.strip()
    if not immediate and s[:1] in '<>|!':   # prefix inside the brackets, e.g. [<data]
        s = s[1:].strip()
    return s


def _in_org_seg(asm, value):
    """An operand whose resolved value lands inside the current ORG'd segment is
    a self-reference the linker relocates as SEGNAME+offset (ROM firmware)."""
    seg = asm._rseg
    if seg is None or value is None:
        return False
    s = asm.segs[seg]
    return s.org is not None and s.org <= value < s.org + s.length()


def _branch_xseg(asm, core, cur_seg, ref_off=None):
    """A relative branch whose target is in a DIFFERENT (relocatable) segment
    can't be a fixed offset — the linker computes it via a RELEXPR record."""
    m = _SIMPLE_REF.match(core)
    if not m:
        return False
    u = m.group(1).upper()
    # a branch to an ENTRY is relocated by name (RELEXPR) — but a BACKWARD branch
    # to a same-segment ENTRY (already defined) is a fixed offset; only a FORWARD
    # same-seg branch (or a cross-segment one) needs a RELEXPR.
    if u in asm.entries:
        local = u in asm.seg_local.get(cur_seg, {})
        if local and ref_off is not None:
            base = asm.segs[cur_seg].org or 0
            def_off = ((asm.resolve(u) or 0) & 0xFFFFFF) - base
            if def_off <= ref_off:        # backward same-seg -> fixed literal
                return False
            # a forward branch to a DUPLICATE entry name (defined in more than
            # one segment) can't relocate by name (ambiguous) -> fixed literal
            if asm.defcount.get(u, 0) > 1:
                return False
        return True
    # a label local to THIS segment is a fixed offset, even if the same name is
    # (also) defined in another segment (symseg is global/last-wins)
    if u in asm.seg_local.get(cur_seg, {}):
        return False
    if u in asm.imports:                   # branch to a declared IMPORT (external)
        return True
    if _undef_external(asm, u):            # branch to an undefined external
        return True
    si = asm.symseg.get(u)
    return (si is not None and si != cur_seg and asm.segs[si].org is None)


def _cross_seg_label(asm, name):
    """True if name is a label defined in a different segment from the current one.
    Such references need LEXPR even when both segments are ORG'd (e.g., slot firmware
    ENTRY labels that the linker must resolve via INTERSEG reloc for slot independence)."""
    u = asm._symkey(name)
    si = asm.symseg.get(u)
    return (si is not None and si != asm._rseg
            and asm.symtype.get(u) == 'label')


def _undef_external(asm, name):
    """A symbol that is undefined everywhere in this assembly is an implicit
    external reference (MPW resolves it at link time by name)."""
    u = asm._symkey(name)
    return (u not in asm.symbols and u not in asm.seed and u not in asm.imports
            and asm.symtype.get(u) is None and asm.seed_type.get(u) is None)


def _ctl_external(asm, mnem, core):
    """A control-flow target (JSR/JMP/JSL/JML) that is a single undefined symbol
    is an implicit external reference (MPW resolves it at link time by name)."""
    if mnem not in ('JSR', 'JMP', 'JSL', 'JML'):
        return False
    m = _SIMPLE_REF.match(core)
    return bool(m) and _undef_external(asm, m.group(1))


def emit_segment(asm, seg, exports):
    """Emit one OMF v2.0 segment object (header + body)."""
    from . import m65816
    segname = (seg.name or 'main').upper()
    try:
        asm._rseg = asm.segs.index(seg)   # resolve local labels in this segment
    except ValueError:
        asm._rseg = None

    body = bytearray()
    for name in sorted(exports):
        if asm.symtype.get(name) == 'equ' and name in asm.symbols:
            body += bytes([0xE7]) + _omfstr(name) + _num(0, 2) + bytes([0x4D, 0x00])
            body += bytes([0x81]) + _num(asm.symbols[name]) + bytes([0x00])

    lit = bytearray()

    def flush():
        # Chunk literal runs at 0xFF bytes. LCONST (0xF2) for chunks > 0xDF (223);
        # plain CONST (op = count byte) for chunks ≤ 0xDF. (Use body.extend,
        # NOT `body +=`, which would make `body` a local and break the closure.)
        i = 0
        while i < len(lit):
            chunk = lit[i:i+0xFF]
            if len(chunk) > 0xDF:
                body.extend(bytes([0xF2]) + _num(len(chunk)) + bytes(chunk))
            else:
                body.append(len(chunk)); body.extend(chunk)
            i += len(chunk)
        del lit[:]

    # image offset of each item (for forward/backward entry-ref decisions)
    item_img = []
    _o = 0
    for it in seg.items:
        item_img.append(_o)
        if it[0] == 'code':
            _o += len(it[2])
        elif it[0] == 'ds':
            _o += it[1]

    for ii, it in enumerate(seg.items):
        if it[0] == 'ds':
            flush()
            body += bytes([0xF1]) + _num(it[1])           # DS record
            continue
        if it[0] == 'global':                              # GLOBAL at entry/export label
            # a DUPLICATE entry/export name emits its GLOBAL only in the segment
            # that owns its ENTRY/EXPORT directive (others reference it by offset)
            if (asm.defcount.get(it[1], 0) > 1 and
                    asm.entry_seg.get(it[1], segname) != segname):
                continue
            flush()
            priv = it[2] if len(it) > 2 else 1
            body += bytes([0xE6]) + _omfstr(it[1]) + _num(0, 2) + bytes([0x4D, priv])
            continue
        ln, barr = it[1], it[2]
        asm._rlg = it[3] if len(it) > 3 else None   # @-label scope for this line
        asm._rlg2 = it[4] if len(it) > 4 else None  # enclosing scope (macro fallback)
        u = (ln.op or '').upper()
        # branches are PC-relative; a same-segment target is a fixed offset
        # (literal), a cross-segment target needs a RELEXPR (linker computes it)
        is_branch = u in m65816.BRANCH8 or u in m65816.BRANCH16
        if is_branch and len(barr) > 1:
            core = _core(ln.operand or '')
            if core and _branch_xseg(asm, core, asm._rseg, ref_off=item_img[ii]):
                nb = len(barr) - 1
                lit.extend(barr[:1]); flush()        # branch opcode -> CONST
                body += bytes([0xEE, nb]) + _num(nb) + _expr_for(asm, core, segname)
                continue
        # block move (MVN/MVP): the two operand bytes are BANK bytes, each
        # `operand >> 16`. A relocatable operand (e.g. `mvn main,databank` moving
        # ROM->RAM) needs its bank byte relocated, not baked. Image byte order is
        # opcode, bank(parts[1]), bank(parts[0]) (see m65816 block-move encoding).
        if u in m65816.BLOCKMOVE and len(barr) == 3:
            parts = [p.strip() for p in (ln.operand or '').split(',')]
            order = [parts[1] if len(parts) > 1 else '0',
                     parts[0] if parts else '0']
            lit.append(barr[0])                          # opcode -> literal
            for k, p in enumerate(order):
                if (re.fullmatch(r'[A-Za-z_~@?.][\w~@?.]*', p) and
                        (asm.needs_reloc(p) or _undef_external(asm, p))):
                    flush()
                    body += bytes([0xF3, 1]) + _expr_for(asm, p + '>>16', segname)
                else:
                    lit.append(barr[1 + k])              # constant bank byte
            continue
        if u in m65816.MNEMONICS and len(barr) > 1 and not is_branch:
            core = _core(ln.operand or '')
            _idm = re.match(r'^[<>^]?\s*([A-Za-z_~@?.][\w~@?.]*)', core) if core else None
            # evaluate the address ignoring any leading byte-extraction operator
            _ev = (asm.resolve(_idm.group(1)) if _idm
                   else asm.evaluate(core[1:] if core[:1] in '<>^' else core))
            if core and (asm.needs_reloc(core) or _ctl_external(asm, u, core)
                         or (_idm and _in_org_seg(asm, _ev))
                         or (_idm and _undef_external(asm, _idm.group(1)))
                         or (_idm and _cross_seg_label(asm, _idm.group(1)))):
                nb = len(barr) - 1
                lit.extend(barr[:1]); flush()
                opd = (ln.operand or '').strip()
                indirect = '(' in opd or '[' in opd
                immediate = opd.startswith('#')
                # indexed abs (LDA abs,X / LDA abs,Y) -> LEXPR; plain abs (JSR, JMP,
                # LDA abs without index) -> BEXPR bank-checked.
                indexed = bool(re.search(r',\s*[XxYy]\s*$', opd))
                # AsmIIgs uses BEXPR (bank-checked) only for JSR/JMP absolute;
                # all other instructions (LDA abs, STA abs, etc.) use LEXPR.
                rec = (0xED if (u in ('JSR', 'JMP') and nb == 2
                                and not indirect and not indexed)
                       else 0xF3)
                body += bytes([rec, nb]) + _expr_for(asm, core, segname,
                                                     ref_off=item_img[ii])
                continue
        if u.startswith('DC') and len(barr) > 0:
            from .asm import _split_commas
            opd = (ln.operand or '').strip()
            items = [x.strip() for x in _split_commas(opd)]

            def _reloc_elem(it):
                # `label - *` (same-segment) is a PC-relative CONSTANT: the base
                # cancels, so it is a literal, not a relocation.  Must precede the
                # _linear_reloc check below, which would otherwise treat it as
                # `label + (-*)` and relocate it (re-evaluating `*` at end-of-
                # assembly -> a wrong offset).
                if _pc_rel_const(asm, it):
                    return False
                m = _SIMPLE_REF.match(it)
                if m and (asm.needs_reloc(m.group(1))
                          or _undef_external(asm, m.group(1))
                          or _in_org_seg(asm, asm.evaluate(it))
                          or _cross_seg_label(asm, m.group(1))):
                    return True
                # a complex expr that is linear in one reloc label, e.g.
                # `EndAddr-(0*3)` (a macro-generated jump table)
                if _linear_reloc(asm, it) is not None:
                    return True
                # a single reloc label with a SHIFT/byte-extraction, e.g. a
                # far-pointer bank word `(Mouse)>>16` — _expr_for emits the shift.
                # (Require the shift so a plain label-difference constant like
                # `A-B` stays a literal.)
                if '>>' in it or '<<' in it or it.lstrip('(')[:1] in '<>^':
                    ids = re.findall(r'[A-Za-z_~@?.][\w~@?.]*', it)
                    rel = [x for x in ids
                           if asm.needs_reloc(x) or _undef_external(asm, x)
                           or _in_org_seg(asm, asm.resolve(x))]
                    return len(rel) == 1
                # a CROSS-segment difference of two relocatable labels (`A-B`, both
                # defined, in different relocatable segments) is a LINK-TIME layout
                # constant, not an assembly-time one -> emit it as an expression so
                # the linker computes it (a same-segment/ORG'd diff stays a literal).
                if _diff_reloc(asm, it) is not None:
                    return True
                return False
            w = asm._width(u)
            no_str = not any(it[:1] in "'\"" for it in items if it)
            # element-wise relocation for a DC address table: each fixed-width
            # element is either a literal (CONST) or a SEGNAME+offset/import ref
            # (LEXPR). Only when bytes divide evenly into w-sized elements.
            if (no_str and w and len(barr) == w * len(items)
                    and any(_reloc_elem(it) for it in items)):
                for k, it in enumerate(items):
                    if _reloc_elem(it):
                        flush()
                        body += bytes([0xF3, w]) + _expr_for(
                            asm, it, segname, as_data=True,
                            ref_off=item_img[ii] + k * w)
                    else:
                        lit.extend(barr[k*w:(k+1)*w])
                continue
        lit.extend(barr)
    flush()
    body += bytes([0x00])                                 # END

    seglen = seg.length()
    dispname = 44
    loadname = (seg.loadname or 'main').encode('mac_roman')[:10].ljust(10)
    segn = _omfstr(segname)
    dispdata = dispname + 10 + len(segn)
    # PRIVATE (0x4000) unless the segment is EXPORT'd (public). An ENTRY-only
    # segment stays PRIVATE. The EXPORT may be a separate directive, not on the
    # PROC line.
    _nm = (seg.name or '').upper()
    _public = (not seg.private) or _nm in asm.exports
    kind = 0x0000 if _public else 0x4000
    if getattr(seg, 'is_data', False):          # data segment (no-operand RECORD)
        kind |= 0x0001                          # KIND data type bit

    hdr = bytearray(44)
    hdr[8:12] = _num(seglen)                   # LENGTH
    hdr[14] = 4                                 # NUMLEN
    hdr[15] = 2                                 # VERSION
    # data segments (RECORD) don't span banks, so no bank-size constraint.
    _banksize = 0 if getattr(seg, 'is_data', False) else 0x10000
    hdr[16:20] = _num(_banksize)                # BANKSIZE
    hdr[20:22] = _num(kind, 2)                  # KIND
    hdr[24:28] = _num(seg.org or 0)             # ORG
    hdr[34:36] = _num(seg.segnum, 2)            # SEGNUM
    hdr[40:42] = _num(dispname, 2)
    hdr[42:44] = _num(dispdata, 2)
    out = bytearray()
    out += hdr + loadname + segn + body
    out[0:4] = _num(len(out))                    # BYTECNT
    return bytes(out)


def emit(asm):
    """Emit an OMF v2.0 object file (one segment per PROC)."""
    out = bytearray()
    segs = [s for s in asm.segs if s.items or s.name]
    # renumber segments 1..N in order
    for i, seg in enumerate(segs):
        seg.segnum = i + 1
        exports = asm.exports if i == 0 else set()
        out += emit_segment(asm, seg, exports)
    return bytes(out)


if __name__ == '__main__':
    import sys
    d = open(sys.argv[1], 'rb').read()
    h = parse_header(d)
    print(f"size={len(d)} BYTECNT={h['BYTECNT']} LENGTH={h['LENGTH']} "
          f"NUMLEN={h['NUMLEN']} VER={h['VERSION']} KIND={h['KIND']} "
          f"ORG={h['ORG']} ALIGN={h['ALIGN']} SEGNUM={h['SEGNUM']} "
          f"DISPNAME={h['DISPNAME']} DISPDATA={h['DISPDATA']}")
    print(f"LOADNAME={h['LOADNAME']!r} SEGNAME={h['SEGNAME']!r}")
    recs, end = parse_records(d, h['DISPDATA'], h['NUMLEN'], h['LABLEN'])
    for at, name, detail in recs:
        if name in ('CONST', 'LCONST'):
            print(f"  {at:04X} {name}({len(detail)}) {detail[:24].hex()}")
        else:
            print(f"  {at:04X} {name} {detail}")
    print(f"end at {end:04X} / {len(d)}")
