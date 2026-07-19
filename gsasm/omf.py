"""OMF v2.0 object-file parser (for understanding/validating AsmIIgs output)
and emitter. Object records are decoded so we can reproduce them byte-exactly.
"""
from __future__ import annotations
import struct
import re
from . import expr as _expr

# A data operand is relocatable only if it is a single symbol with an optional
# constant addend; complex arithmetic (X-Y, X/4, ...) is a computed literal.
_SIMPLE_REF = re.compile(r'^([A-Za-z_~@?.][\w~@?.$]*)\s*([+-]\s*\$?[0-9A-Fa-f]+)?$')

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


def iter_segments(data: bytes, *, records: bool = True):
    """Yield parsed OMF segments from a concatenated object/load byte string.

    Each yielded dict contains:
      'name': SEGNAME decoded as mac_roman and stripped, preserving case
      'raw' : the complete segment byte string
      'hdr' : parse_header() output
      'recs': parse_records() output when records=True, otherwise None
      'off' : byte offset of the segment in *data*
    """
    off = 0
    while off < len(data):
        h = parse_header(data[off:])
        bc = h['BYTECNT']
        if bc == 0:
            break
        raw = data[off:off + bc]
        recs = None
        if records:
            recs, _ = parse_records(
                raw,
                h['DISPDATA'],
                h.get('NUMLEN', 4),
                h.get('LABLEN', 0),
            )
        yield {
            'name': h['SEGNAME'].decode('mac_roman', 'replace').strip(),
            'raw': raw,
            'hdr': h,
            'recs': recs,
            'off': off,
        }
        off += bc


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
    # Collect all identifiers in the expression (avoiding hex-literal false positives)
    idents = list(dict.fromkeys(
        re.findall(r'(?<![0-9A-Fa-f$])[A-Za-z_~@?.][\w~@?.$]*', text)))

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
            u = asm._fold(n)
            if u == asm._fold(_name):
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


def _reloc_target_key(asm, ident):
    """Relocation-GROUP key for one identifier, or None if it is a constant.
    Two identifiers share a key iff they relocate against the same base, so a
    linear combination that nets coefficient +1 on a single key is a single
    relocation:
      * a plain relocatable label keys on its home segment -- SAME-SEGMENT labels
        share a key, so `us_end-us_start` (a same-seg constant length) cancels and
        leaves the leftover `user_path+2` as one SEGNAME+offset reference;
      * an equ_alias'd WITH-instance/import field keys on its alias BASE -- an
        import (`my_f_info` -> MYDATA) or the base label's segment -- so
        `my_f_info-tOpt.f_info` relocates against MYDATA (tOpt.f_info is a pure
        template-offset constant, alias-less);
      * a declared-but-undefined import / implicit external keys on its own name.
    ORG'd / temporg segment labels are absolute literals (like needs_reloc treats
    them) and return None."""
    u = asm._symkey(ident)
    alias = getattr(asm, 'equ_alias', {}).get(u)
    if alias is not None:
        base = asm._symkey(alias[0])
        if base in asm.imports and asm.resolve(base) is None:
            return ('import', base)
        bs = asm.symseg.get(base)
        # `org is None` — NOT truthiness: a segment with an explicit `ORG 0`
        # is absolute (org == 0), and `0 or temporg` is falsy, which would
        # wrongly classify it as relocatable.  Matches needs_reloc/_equ_alias_of.
        if bs is not None and bs < len(asm.segs) \
                and asm.segs[bs].org is None and asm.segs[bs].temporg is None:
            return ('seg', bs)
        return None
    if u in asm.imports and asm.resolve(u) is None:
        return ('import', u)
    if _undef_external(asm, ident):
        return ('ext', u)
    if asm.sym_kind(ident) == 'label':
        s = asm.symseg.get(u)
        if s is not None and s < len(asm.segs) \
                and asm.segs[s].org is None and asm.segs[s].temporg is None:
            return ('seg', s)
    return None


def _grouped_linear_reloc(asm, text):
    """Generalise _linear_reloc to a multi-term expression whose relocatable
    terms COLLAPSE to a single relocation with net coefficient +1.  _linear_reloc
    misses two AppleShare `WITH`-scoped idioms:
      (a) an equ_alias'd field minus a template offset -- `my_f_info-tOpt.f_info`
          -- because linear_decompose counts only label/import/undef terms, not
          equ-kind alias fields, so the field folds into K and the reloc is lost
          (gsasm bakes the direct-page offset $60 where gold links MYDATA+$60);
      (b) three SAME-SEGMENT labels that net to +1 -- `user_path+2-us_start+us_end`
          -- which linear_decompose keeps as three separate terms (len != 1).
    Returns (representative_name, addend) so _expr_for's existing equ_alias/label
    emit path relocates it (the representative is a +1 term of the single group;
    its own equ_alias, if any, is re-applied downstream), else None.  Scoped to a
    SINGLE relocation target with net coeff exactly +1 -- a pure same-seg
    difference (net 0) or a cross-target difference (>1 group) is left to
    _diff_reloc / literal baking, unchanged."""
    idents = list(dict.fromkeys(
        re.findall(r'(?<![0-9A-Fa-f$])[A-Za-z_~@?.][\w~@?.$]*', text)))
    V = _expr.try_eval(text, asm.resolve, asm.loc)
    if V is None:
        return None
    if _expr.try_eval(text, asm.resolve, asm.loc + 0x100) != V:
        return None                       # a PC (`*`) term -> not a plain reloc
    # A declared IMPORT / implicit external that this classifier would fold into
    # the constant (its key is None because it also has a LOCAL ORG'd value) must
    # instead be emitted BY NAME as a difference — leave it to _diff_reloc /
    # _extern_diff_expr.  Fixture 035 `my_end-my_start`: my_start is an ORG'd pad
    # PROC that is ALSO IMPORTed, so the linker resolves both sides by name.
    for ident in idents:
        if _reloc_target_key(asm, ident) is None and (
                asm._symkey(ident) in asm.imports or _undef_external(asm, ident)):
            return None
    groups = {}                           # target key -> net coefficient
    coeffs = {}                           # ident -> coefficient
    for ident in idents:
        key = _reloc_target_key(asm, ident)
        if key is None:
            continue
        val = asm.resolve(ident)
        val = 0 if val is None else val

        def bumped(n, _i=ident, _v=val):
            return _v + 0x100 if asm._fold(n) == asm._fold(_i) else asm.resolve(n)
        V2 = _expr.try_eval(text, bumped, asm.loc)
        if V2 is None:
            return None
        c = (V2 - V) // 0x100
        if c:
            coeffs[ident] = c
            groups[key] = groups.get(key, 0) + c
    if len(groups) != 1:
        return None
    (key, net), = groups.items()
    if net != 1:
        return None
    repr_name = next((i for i, c in coeffs.items()
                      if c == 1 and _reloc_target_key(asm, i) == key), None)
    if repr_name is None:
        return None
    rv = asm.resolve(repr_name)
    rv = 0 if rv is None else rv
    return (repr_name, V - rv)


def _mul_reloc_expr(asm, text, segname):
    """Try to decompose `text` as (SEGNAME + rel) * N + K for a single label in
    the current ORG segment with coefficient N != 0,1. Returns expression ops
    bytes (without the end-of-expr 0x00) or None."""
    # Classifier over linear_decompose — keeps same scope tests and emit bytes.
    # Scope: exactly one relocatable symbol (label/import/equ), coeff > 1,
    # symbol value in the current ORG'd segment.
    if asm._rseg is None:
        return None
    # Candidate: single identifier with sym_kind in ('label', 'equ')
    # (equates in an ORG segment alias absolute addresses and must be treated
    # as potentially relocatable — linear_decompose excludes equates from terms
    # since they are constants, so we handle them here with finite difference).
    idents = list(dict.fromkeys(
        re.findall(r'(?<![0-9A-Fa-f$])[A-Za-z_~@?.][\w~@?.$]*', text)))
    reloc = [i for i in idents if asm.sym_kind(i) in ('label', 'equ')]
    if len(reloc) != 1:
        return None
    L = reloc[0]
    Lval = (asm.resolve(L) or 0) & 0xFFFFFF
    # Two cases for the SEGNAME the multiply rides on:
    #  (a) L is in the CURRENT ORG'd segment -> segname + (Lval - seg_org).
    #  (b) L is a relocatable label in ANOTHER (non-ORG) segment -> its OWN
    #      SEGNAME + offset.  (b) covers a shifted CROSS-segment label plus a
    #      constant, e.g. GS.OS SCM `lda #((common_int_ent<<8)+$5c)`, which packs
    #      the entry's low byte as the high byte of a JML operand — a link-time
    #      value.  Without it the expression bakes the assembly-time literal ($5c).
    lseg = asm.symseg.get(asm._symkey(L))
    if _in_org_seg(asm, Lval):
        target_seg, seg_org = segname, (asm.segs[asm._rseg].org or 0)
    elif (asm.sym_kind(L) == 'label' and lseg is not None
          and lseg < len(asm.segs) and not (asm.segs[lseg].org or 0)):
        target_seg, seg_org = asm._fold(asm.segs[lseg].name or ''), 0
    else:
        return None
    # Coefficient via finite difference (same as original)
    def _res(n, bump=0):
        return (Lval + bump) if asm._fold(n) == asm._fold(L) else asm.resolve(n)
    V = _expr.try_eval(text, lambda n: _res(n, 0), asm.loc)
    V1 = _expr.try_eval(text, lambda n: _res(n, 1), asm.loc)
    if V is None or V1 is None:
        return None
    N = V1 - V                                   # coefficient of L in expr
    if N <= 1:                                   # +1 handled by _linear_reloc
        return None
    K = V - N * Lval
    rel = Lval - seg_org
    ops = bytearray()
    ops += bytes([0x83]) + _omfstr(target_seg)
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
    once the linker places the segments apart (e.g. `DC.W getfstname-jump_table`).

    A difference is final ONLY when BOTH segments are ORG'd (both absolute).  A
    MIXED case — one label in an ORG'd (absolute) segment, the other in a
    relocatable one — is NOT final: the relocatable side moves at link, so it must
    still emit the expression.  This is the GS/OS Init-manager header idiom
    `DC.W init_N_end-init_N_start`, where init_N_start is an ORG'd pad PROC
    (absolute) and init_N_end is a relocatable end-bracket PROC that follows a data
    segment (so its assembly-time value is 0-based and the baked literal is wrong);
    the linker computes the real segment length.  locops already emits each side as
    SEGNAME+offset, and an ORG'd segment resolves to its ORG, so the same emission
    is correct for the absolute side too.

    Classifier over linear_decompose: 2 terms with coefficients +1/-1, both
    symseg-known labels, in different segments (not both ORG'd), both defined."""
    dec = linear_decompose(asm, text)
    if dec is None:
        return None
    terms, K, pc_coeff = dec
    # exactly 2 relocatable symbols, coefficients +1 and -1, no PC term
    if len(terms) != 2 or pc_coeff != 0:
        return None
    plus_ones = [(n, c) for n, c in terms.items() if c == 1]
    minus_ones = [(n, c) for n, c in terms.items() if c == -1]
    if len(plus_ones) != 1 or len(minus_ones) != 1:
        return None
    A = plus_ones[0][0]
    B = minus_ones[0][0]
    # Scope tests (same as original): both must be labels with known symseg,
    # in different segments, neither ORG'd, both defined.
    if asm.sym_kind(A) != 'label' or asm.sym_kind(B) != 'label':
        return None
    sa = asm.symseg.get(asm._symkey(A))
    sb = asm.symseg.get(asm._symkey(B))
    if sa is None or sb is None:
        return None
    if sa == sb:                                   # same segment: literal is final
        return None
    if (asm.segs[sa].org or 0) and (asm.segs[sb].org or 0):
        return None                                # BOTH ORG'd (absolute) diff is final
    av, bv = asm.resolve(A), asm.resolve(B)
    if av is None or bv is None:                   # both must be defined
        return None

    def locops(name):
        nu = asm._symkey(name)
        seg = asm.segs[asm.symseg[nu]]
        off = ((asm.resolve(nu) or 0) & 0xFFFFFF) - (seg.org or 0)
        o = bytes([0x83]) + _omfstr(asm._fold(seg.name or ''))
        if off:
            o += bytes([0x81]) + _num(off & 0xFFFFFFFF) + bytes([0x01])
        return o
    # K from linear_decompose = V - (+1)*av - (-1)*bv = V - av + bv
    # Original: K = (v - (av&0xFFFFFF - bv&0xFFFFFF)) & 0xFFFFFFFF — same mod 2^32
    K_m = K & 0xFFFFFFFF
    ops = bytearray()
    ops += locops(A)
    ops += locops(B)
    ops += bytes([0x02])                           # SUB: A - B
    if K_m:
        ops += bytes([0x81]) + _num(K_m) + bytes([0x01])
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


def _extern_diff_expr(asm, text):
    """`A - B [+ K]` where A and B are two EXTERNALS (declared IMPORT or implicit
    undefined, each with no local value) and every other term is an absolute
    equate -> OMF by-name difference expression (0x83 A, 0x83 B, SUB, +K) the
    LINKER evaluates.  E.g. the SCSI driver's `#lst_rslt_scode+2-lst_rslt_ec`, a
    difference of two imported data labels: unknown at assembly, but a link-time
    constant.  (linear_decompose can't handle this — it needs the symbols to
    resolve; externals don't — so coefficients are found by zeroing the externals,
    the same trick as _ext_plus_const.)  Returns ops bytes (no trailing 0x00) or
    None."""
    ids = list(dict.fromkeys(
        re.findall(r'(?<![0-9A-Fa-f$])[A-Za-z_~@?.][\w~@?.$]*', text)))

    def _is_ext(i):
        return _undef_external(asm, i) or (
            asm._symkey(i) in asm.imports and asm.resolve(asm._symkey(i)) is None)

    ext = [i for i in ids if _is_ext(i)]
    if len(ext) != 2:
        return None
    for i in ids:                          # every non-external term must be a const
        if i not in ext and asm.sym_kind(i) != 'equ':
            return None

    def _res(vals):
        folds = {asm._fold(e): vals[e] for e in ext}

        def r(n):
            return folds.get(asm._fold(n), asm.resolve(n))
        return r

    base = {e: 0 for e in ext}
    V0 = _expr.try_eval(text, _res(base), asm.loc)   # externals=0 -> constant part
    if V0 is None:
        return None
    coeff = {}
    for e in ext:
        b = dict(base); b[e] = 0x100
        Ve = _expr.try_eval(text, _res(b), asm.loc)
        if Ve is None:
            return None
        coeff[e] = (Ve - V0) // 0x100
    plus = [e for e in ext if coeff[e] == 1]
    minus = [e for e in ext if coeff[e] == -1]
    if len(plus) != 1 or len(minus) != 1:            # only ±1 differences
        return None
    ops = bytearray()
    ops += bytes([0x83]) + _omfstr(asm._fold(plus[0]))
    ops += bytes([0x83]) + _omfstr(asm._fold(minus[0]))
    ops += bytes([0x02])                             # SUB: A - B
    K_m = V0 & 0xFFFFFFFF
    if K_m:
        ops += bytes([0x81]) + _num(K_m) + bytes([0x01])
    return bytes(ops)


def _expr_for(asm, text, segname, as_data=False, ref_off=None):
    """Build an OMF load-time expression for an operand reference.
    Local labels -> SEGNAME + offset; imports -> name; equates -> literal.
    `as_data` (DC address tables): a same-segment ENTRY referenced by a BACKWARD
    reference (defined before this point, ref_off given) is SEGNAME+offset; a
    FORWARD reference (entry defined later) is by name (the assembler hadn't seen
    the definition yet). For code/branch refs, same-segment ENTRY is by name."""
    text = text.strip()
    # < > ^ select low/high/bank: the linker computes (sym >> shift)
    shift = 0
    if text[:1] in '<>^':
        shift = {'<': 0, '>': 8, '^': 16}[text[0]]
        text = text[1:].strip()
    # explicit trailing shift: sym>>N (right) or sym<<N (left), e.g. #ListProc>>16
    ms = re.match(r'^(.*?)\s*(>>|<<)\s*(\d+)$', text)
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
    m = re.match(r'^([A-Za-z_~@?.][\w~@?.$]*)\s*([+\-]\s*\$?[0-9A-Fa-f]+)?$', text)
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
        if dec is None:
            # a multi-term expression that collapses to ONE reloc, net coeff +1:
            # an equ_alias'd WITH-instance field minus a template offset, or
            # several same-segment labels that net to +1 (AppleShare send_option
            # `my_f_info-tOpt.f_info`, Specific `user_path+2-us_start+us_end`).
            dec = _grouped_linear_reloc(asm, text)
        if dec:
            name, addend = dec
        elif not as_data:
            # instruction operand linear in ONE external + a constant, e.g.
            # `lda >arrowMap-UP_ARROW,x` (arrowMap external, UP_ARROW=8 equ)
            # or HFS btree's `lda |cat_buffer+cat_type` (cat_buffer a declared
            # IMPORT, cat_type an equ): resolve the external by name + addend.
            # A declared IMPORT counts only while UNDEFINED locally — an
            # import that a local EQU satisfies keeps the local value
            # (Pro.FST Max_call).  (Scoped to instructions; DC tables resolve
            # undefined symbols differently.)
            ids = list(dict.fromkeys(
                re.findall(r'(?<![0-9A-Fa-f$])[A-Za-z_~@?.][\w~@?.$]*', text)))
            ext = [i for i in ids
                   if _undef_external(asm, i)
                   or (asm._symkey(i) in asm.imports
                       and asm.resolve(asm._symkey(i)) is None)]
            if len(ext) == 1:
                Lname = ext[0]
                def _res0(n, _L=Lname):
                    return 0 if asm._fold(n) == asm._fold(_L) else asm.resolve(n)
                add = _expr.try_eval(text, _res0, asm.loc)
                if add is not None:
                    name, addend = Lname, add
        if name is None and as_data:
            # a DC field linear in one external (declared IMPORT or implicit
            # undefined) + an absolute-EQU constant — e.g. GSHeader's segment-length
            # `DC.W zloader_end-zloader_start`: emit the external by name + addend so
            # the linker resolves it (gsasm otherwise bakes an unresolved 0xffff).
            ed = _ext_plus_const(asm, text)
            if ed is not None:
                name, addend = ed
    ops = bytearray()
    if name is not None:
        # An EQU aliasing a relocatable label (asm.equ_alias) is a second name for
        # that address: emit it AS the target label + addend so it relocates
        # (SEGNAME+offset) instead of baking the snapshot value as a constant. The
        # target's symtype is 'label', so the label paths below fire naturally; the
        # alias's own symtype stays 'equ' (operand sizing is untouched).
        alias = getattr(asm, 'equ_alias', {}).get(asm._symkey(name))
        if alias is not None:
            name = alias[0]
            addend = (addend or 0) + alias[1]
        # A reference to a temporg-segment label is an ABSOLUTE literal (the code
        # runs at `temporg` after being copied there), not a SEGNAME/by-name
        # relocation — emit the value directly so the linker's placement of that
        # segment (its flow/relocatable base) cannot override it (GQuit's cross-
        # segment `ldy #load_app_begin`).  Any <>^ / >>N shift applies to the value.
        if _temporg_label(asm, name):
            v = ((asm.resolve(name) or 0) + (addend or 0)) & 0xFFFFFF
            if shift > 0:
                v >>= shift
            elif shift < 0:
                v = (v << -shift) & 0xFFFFFF
            return bytes(bytes([0x81]) + _num(v & 0xFFFFFF) + bytes([0x00]))
        kind = asm.sym_kind(name)
        if kind in ('label', None):           # local/relocatable label
            nu = asm._symkey(name)            # scoped key (@-labels -> scope+name)
            # a label local to the current segment is same-seg even if the name
            # is also defined elsewhere (symseg is global/last-wins for dups)
            local_here = asm._rseg is not None and nu in asm.seg_local.get(asm._rseg, {})
            same_seg = local_here or (asm.symseg.get(nu) is not None and
                        asm._fold(asm.segs[asm.symseg[nu]].name or '') == segname)
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
            # a DUPLICATE entry name (defined in more than one segment) cannot
            # be referenced by name from a segment that has its OWN definition:
            # the linker would resolve the name to the entry-owner segment's
            # GLOBAL, but MPW scoping gives the same-segment definition
            # precedence (AppleDisk5.25 format16's `jsr wexit` → its own wexit,
            # not write16's).  Same rule as the branch detector (_branch_xseg).
            if entry_byname and local_here and asm.defcount.get(nu, 0) > 1:
                entry_byname = False
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
                # A backward-ORG overlay label's GLOBAL record sits at the
                # item-stream position, NOT at the label's (earlier, patched)
                # address — a positional GLOBAL cannot represent it, so a
                # by-name reference would resolve wrong.  Use SEGNAME+offset.
                if other_seg is not None and (
                        getattr(other_seg, 'is_data', False)
                        or _global_stream_mismatch(asm, nu, other_idx)):
                    other_base = other_seg.org or 0
                    other_off = ((asm.resolve(nu) or 0) & 0xFFFFFF) + addend - other_base
                    ops += bytes([0x83]) + _omfstr(asm._fold(other_seg.name or ''))
                    if other_off:
                        ops += bytes([0x81]) + _num(other_off) + bytes([0x01])
                else:
                    ops += bytes([0x83]) + _omfstr(asm._fold(name))
                    if addend:
                        ops += bytes([0x81]) + _num(addend) + bytes([0x01])
        elif kind == 'import':
            ops += bytes([0x83]) + _omfstr(asm._fold(name))
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
        if diff is None:
            diff = _extern_diff_expr(asm, text)  # two-external difference
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
    prefixed = False
    if not immediate and s[:1] in '<>|!':
        s = s[1:]
        prefixed = True
    # for a non-immediate operand, leading ( or [ is indirection — strip it and
    # its matching close. For an immediate, parens are arithmetic (e.g.
    # #(muReturn-1)>>8) and must be left for _expr_for.  After an explicit
    # size prefix the operand is direct by definition, so its parens are
    # arithmetic grouping too: TextEdit fastdraw's `pea |(returnHere-1)>>8`
    # must keep the >>8 (truncating at the close paren silently dropped it,
    # losing the site's shift reloc).
    if not immediate and not prefixed and (s.startswith('[') or s.startswith('(')):
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
    u = asm._fold(m.group(1))
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
    # a temporg segment's labels are absolute literals (addr+offset), so a ref from
    # another segment is a literal too, not a relocation.
    return (si is not None and si != cur_seg and asm.segs[si].org is None
            and asm.segs[si].temporg is None)


def _global_stream_mismatch(asm, nu, segidx):
    """True if *nu*'s GLOBAL item sits at an item-stream position that differs
    from the label's value — a backward-ORG overlay label (the bytes were
    patched in place, so the positional GLOBAL marker landed at the segment's
    high-water mark instead of the label's address).  Only meaningful for
    plain relocatable segments, where a label's value IS its stream offset."""
    seg = asm.segs[segidx]
    if seg.org is not None or seg.temporg is not None:
        return False
    cache = getattr(asm, '_gstream_cache', None)
    if cache is None:
        cache = {}
        for si, s in enumerate(asm.segs):
            pos = 0
            for it in s.items:
                if it[0] == 'code':
                    pos += len(it[2])
                elif it[0] == 'ds':
                    pos += it[1]
                elif it[0] == 'global':
                    cache[(si, it[1])] = pos
        asm._gstream_cache = cache
    sp = cache.get((segidx, nu))
    if sp is None:
        return False
    return sp != ((asm.resolve(nu) or 0) & 0xFFFFFF)


def _temporg_label(asm, name):
    """True if *name* resolves to a label in a temporg segment.  Such labels are
    absolute literals (the code is copied to `temporg` at runtime), so any
    reference to them — instruction operand OR a `DC.W label` table entry — is a
    literal, never a SEGNAME+offset relocation."""
    u = asm._symkey(name)
    si = asm.symseg.get(u)
    return si is not None and si < len(asm.segs) and asm.segs[si].temporg is not None


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


def _ext_plus_const(asm, text):
    """Decompose `text` into (external_name, const_addend) when it is linear in
    exactly ONE external — a declared IMPORT or an implicit undefined symbol —
    plus a constant, every OTHER identifier being an absolute equate.  E.g. the
    GS.OS Loader header `DC.W zloader_end-zloader_start` (zloader_end is IMPORTed,
    zloader_start an absolute EQU) -> ('zloader_end', -zloader_start).  The value
    is unknown until the import is placed, so the caller emits it as a by-name OMF
    expression the LINKER computes, not an assembly-time literal (which gsasm bakes
    as an unresolved 0xffff).  None when there isn't exactly one external, a
    non-external term is relocatable, or the constant part can't be evaluated."""
    ids = list(dict.fromkeys(
        re.findall(r'(?<![0-9A-Fa-f$])[A-Za-z_~@?.][\w~@?.$]*', text)))
    ext = [i for i in ids
           if _undef_external(asm, i) or asm._symkey(i) in asm.imports]
    if len(ext) != 1:
        return None
    for i in ids:                          # every other term must be a constant
        if i != ext[0] and asm.sym_kind(i) != 'equ':
            return None
    Lname = ext[0]
    def _res0(n, _L=Lname):
        return 0 if asm._fold(n) == asm._fold(_L) else asm.resolve(n)
    add = _expr.try_eval(text, _res0, asm.loc)
    if add is None:
        return None
    return Lname, add


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
    segname = asm._fold(seg.name or 'main')
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
    nocut = bytearray()   # parallel to lit: nocut[k]=1 forbids a record cut at
                          #   boundary k (k is INTERIOR to an instruction's
                          #   operand field).  MPW AsmIIgs keeps each operand
                          #   field contiguous within one CONST/LCONST record
                          #   (it is the backpatch unit); the record may split
                          #   between an opcode and its operand, but never
                          #   inside the operand (TextState/le/misc.tools:
                          #   golden LCONST is 253/254 where a greedy 255
                          #   would strand operand bytes in the next record).

    def _lit_ins(barr):
        # instruction line: opcode byte, then the operand as an atomic field
        for j in range(len(barr)):
            lit.append(barr[j])
            nocut.append(1 if j >= 2 else 0)

    def _lit(bs):
        lit.extend(bs)
        nocut.extend(bytes(len(bs)))

    def flush():
        # Chunk literal runs at 0xFF bytes, backing a cut off to the nearest
        # allowed boundary (never inside an operand field).  LCONST (0xF2) for
        # chunks > 0xDF (223); plain CONST (op = count byte) for chunks ≤ 0xDF.
        # (Use body.extend, NOT `body +=`, which would make `body` a local and
        # break the closure.)
        i = 0
        while i < len(lit):
            end = min(i + 0xFF, len(lit))
            if end < len(lit):
                while end > i and nocut[end]:
                    end -= 1
                if end == i:                       # >255-byte field: forced cut
                    end = min(i + 0xFF, len(lit))
            chunk = lit[i:end]
            if len(chunk) > 0xDF:
                body.extend(bytes([0xF2]) + _num(len(chunk)) + bytes(chunk))
            else:
                body.append(len(chunk)); body.extend(chunk)
            i = end
        del lit[:]
        del nocut[:]

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
                _lit(barr[:1]); flush()              # branch opcode -> CONST
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

            def _bank_reloc(p):
                return bool(re.fullmatch(r'[A-Za-z_~@?.][\w~@?.$]*', p)) and (
                    asm.needs_reloc(p) or _undef_external(asm, p))

            # all-literal block move: the two bank bytes are one operand field
            # and must not split across CONST/LCONST records (same invariant as
            # the generic mnemonic path below).
            if not any(_bank_reloc(p) for p in order):
                _lit_ins(barr)                           # operand field is cut-atomic
                continue
            _lit(barr[:1])                               # opcode -> literal
            for k, p in enumerate(order):
                if _bank_reloc(p):
                    flush()
                    body += bytes([0xF3, 1]) + _expr_for(asm, p + '>>16', segname)
                else:
                    _lit(barr[1 + k:2 + k])              # constant bank byte
            continue
        if u in m65816.MNEMONICS and len(barr) > 1 and not is_branch:
            core = _core(ln.operand or '')
            _idm = re.match(r'^[<>^]?\s*([A-Za-z_~@?.][\w~@?.$]*)', core) if core else None
            # evaluate the address ignoring any leading byte-extraction operator
            _ev = (asm.resolve(_idm.group(1)) if _idm
                   else asm.evaluate(core[1:] if core[:1] in '<>^' else core))
            if core and (asm.needs_reloc(core) or _ctl_external(asm, u, core)
                         or (_idm and _in_org_seg(asm, _ev))
                         or (_idm and _undef_external(asm, _idm.group(1)))
                         or (_idm and _cross_seg_label(asm, _idm.group(1)))):
                nb = len(barr) - 1
                _lit(barr[:1]); flush()
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
                # a `DC.W label` to a temporg-segment label is an absolute literal
                # (the temporg address), NOT a SEGNAME+offset reloc — must precede
                # the _linear_reloc check, which treats any single label as a coeff-1
                # relocatable (GQuit load_app's `DC.W p8_setpfx_list` parameter table).
                if m and _temporg_label(asm, m.group(1)):
                    return False
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
                    ids = re.findall(r'[A-Za-z_~@?.][\w~@?.$]*', it)
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
                # a DC field linear in one external (declared IMPORT or implicit
                # undefined) + an absolute-EQU constant, e.g. GSHeader's
                # `DC.W zloader_end-zloader_start` -> a LINK-time value, emit by name.
                if _ext_plus_const(asm, it) is not None:
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
                        _lit(barr[k*w:(k+1)*w])
                continue
        if u in m65816.MNEMONICS and len(barr) > 1:
            _lit_ins(barr)               # operand field is cut-atomic
        else:
            _lit(barr)
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
    _nm = asm._fold(seg.name or '')
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
    hdr[28:32] = _num(getattr(seg, 'align', 0) or 0)  # ALIGN (`PROC align N`)
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
