"""65816 instruction encoding.

OPTABLE maps each mnemonic to {addressing-mode: opcode-byte}. `encode()` parses
an operand, selects the addressing mode (honouring LONGA/LONGI and dp/abs/long
rules), and returns the encoded bytes plus a description of any operand value
that still needs resolving (a "fixup"). Pass 1 uses this for sizing and opcode
selection; unresolved operand values are patched afterwards from the final
symbol table.

Addressing-mode keys:
  imp acc imm
  dp dpx dpy  abs absx absy  abl ablx
  ind indx indy indl indly        ( (dp) (dp,x) (dp),y [dp] [dp],y )
  aind aindx aindl                ( (abs) (abs,x) [abs] )
  rel rell  sr sriy  bmv
"""

IMM_A = {'ADC', 'AND', 'BIT', 'CMP', 'EOR', 'LDA', 'ORA', 'SBC'}
IMM_X = {'CPX', 'CPY', 'LDX', 'LDY'}
IMM_1 = {'REP', 'SEP', 'BRK', 'COP', 'WDM'}

BRANCH8 = {'BCC', 'BCS', 'BEQ', 'BMI', 'BNE', 'BPL', 'BRA', 'BVC', 'BVS',
           'BLT', 'BGE', 'BLE', 'BGT'}
BRANCH16 = {'BRL', 'PER'}
BLOCKMOVE = {'MVN', 'MVP'}

# Branch aliases -> canonical
ALIAS = {'BLT': 'BCC', 'BGE': 'BCS', 'INA': 'INC', 'DEA': 'DEC', 'CPA': 'CMP'}

OPTABLE = {
    'ADC': {'imm': 0x69, 'dp': 0x65, 'dpx': 0x75, 'abs': 0x6D, 'absx': 0x7D,
            'absy': 0x79, 'abl': 0x6F, 'ablx': 0x7F, 'ind': 0x72, 'indx': 0x61,
            'indy': 0x71, 'indl': 0x67, 'indly': 0x77, 'sr': 0x63, 'sriy': 0x73},
    'AND': {'imm': 0x29, 'dp': 0x25, 'dpx': 0x35, 'abs': 0x2D, 'absx': 0x3D,
            'absy': 0x39, 'abl': 0x2F, 'ablx': 0x3F, 'ind': 0x32, 'indx': 0x21,
            'indy': 0x31, 'indl': 0x27, 'indly': 0x37, 'sr': 0x23, 'sriy': 0x33},
    'CMP': {'imm': 0xC9, 'dp': 0xC5, 'dpx': 0xD5, 'abs': 0xCD, 'absx': 0xDD,
            'absy': 0xD9, 'abl': 0xCF, 'ablx': 0xDF, 'ind': 0xD2, 'indx': 0xC1,
            'indy': 0xD1, 'indl': 0xC7, 'indly': 0xD7, 'sr': 0xC3, 'sriy': 0xD3},
    'EOR': {'imm': 0x49, 'dp': 0x45, 'dpx': 0x55, 'abs': 0x4D, 'absx': 0x5D,
            'absy': 0x59, 'abl': 0x4F, 'ablx': 0x5F, 'ind': 0x52, 'indx': 0x41,
            'indy': 0x51, 'indl': 0x47, 'indly': 0x57, 'sr': 0x43, 'sriy': 0x53},
    'LDA': {'imm': 0xA9, 'dp': 0xA5, 'dpx': 0xB5, 'abs': 0xAD, 'absx': 0xBD,
            'absy': 0xB9, 'abl': 0xAF, 'ablx': 0xBF, 'ind': 0xB2, 'indx': 0xA1,
            'indy': 0xB1, 'indl': 0xA7, 'indly': 0xB7, 'sr': 0xA3, 'sriy': 0xB3},
    'ORA': {'imm': 0x09, 'dp': 0x05, 'dpx': 0x15, 'abs': 0x0D, 'absx': 0x1D,
            'absy': 0x19, 'abl': 0x0F, 'ablx': 0x1F, 'ind': 0x12, 'indx': 0x01,
            'indy': 0x11, 'indl': 0x07, 'indly': 0x17, 'sr': 0x03, 'sriy': 0x13},
    'SBC': {'imm': 0xE9, 'dp': 0xE5, 'dpx': 0xF5, 'abs': 0xED, 'absx': 0xFD,
            'absy': 0xF9, 'abl': 0xEF, 'ablx': 0xFF, 'ind': 0xF2, 'indx': 0xE1,
            'indy': 0xF1, 'indl': 0xE7, 'indly': 0xF7, 'sr': 0xE3, 'sriy': 0xF3},
    'STA': {'dp': 0x85, 'dpx': 0x95, 'abs': 0x8D, 'absx': 0x9D, 'absy': 0x99,
            'abl': 0x8F, 'ablx': 0x9F, 'ind': 0x92, 'indx': 0x81, 'indy': 0x91,
            'indl': 0x87, 'indly': 0x97, 'sr': 0x83, 'sriy': 0x93},
    'ASL': {'acc': 0x0A, 'dp': 0x06, 'dpx': 0x16, 'abs': 0x0E, 'absx': 0x1E},
    'LSR': {'acc': 0x4A, 'dp': 0x46, 'dpx': 0x56, 'abs': 0x4E, 'absx': 0x5E},
    'ROL': {'acc': 0x2A, 'dp': 0x26, 'dpx': 0x36, 'abs': 0x2E, 'absx': 0x3E},
    'ROR': {'acc': 0x6A, 'dp': 0x66, 'dpx': 0x76, 'abs': 0x6E, 'absx': 0x7E},
    'DEC': {'acc': 0x3A, 'dp': 0xC6, 'dpx': 0xD6, 'abs': 0xCE, 'absx': 0xDE},
    'INC': {'acc': 0x1A, 'dp': 0xE6, 'dpx': 0xF6, 'abs': 0xEE, 'absx': 0xFE},
    'BIT': {'imm': 0x89, 'dp': 0x24, 'dpx': 0x34, 'abs': 0x2C, 'absx': 0x3C},
    'CPX': {'imm': 0xE0, 'dp': 0xE4, 'abs': 0xEC},
    'CPY': {'imm': 0xC0, 'dp': 0xC4, 'abs': 0xCC},
    'LDX': {'imm': 0xA2, 'dp': 0xA6, 'dpy': 0xB6, 'abs': 0xAE, 'absy': 0xBE},
    'LDY': {'imm': 0xA0, 'dp': 0xA4, 'dpx': 0xB4, 'abs': 0xAC, 'absx': 0xBC},
    'STX': {'dp': 0x86, 'dpy': 0x96, 'abs': 0x8E},
    'STY': {'dp': 0x84, 'dpx': 0x94, 'abs': 0x8C},
    'STZ': {'dp': 0x64, 'dpx': 0x74, 'abs': 0x9C, 'absx': 0x9E},
    'TRB': {'dp': 0x14, 'abs': 0x1C},
    'TSB': {'dp': 0x04, 'abs': 0x0C},
    'JMP': {'abs': 0x4C, 'aind': 0x6C, 'aindx': 0x7C, 'abl': 0x5C, 'aindl': 0xDC},
    'JML': {'abl': 0x5C, 'aindl': 0xDC},
    'JSR': {'abs': 0x20, 'aindx': 0xFC},
    'JSL': {'abl': 0x22},
    'PEA': {'abs': 0xF4},
    'PEI': {'dp': 0xD4},
    'PER': {'rell': 0x62},
    'REP': {'imm': 0xC2},
    'SEP': {'imm': 0xE2},
    'BRK': {'imm': 0x00},
    'COP': {'imm': 0x02},
    'WDM': {'imm': 0x42},
    'MVN': {'bmv': 0x54},
    'MVP': {'bmv': 0x44},
    # branches
    'BCC': {'rel': 0x90}, 'BCS': {'rel': 0xB0}, 'BEQ': {'rel': 0xF0},
    'BNE': {'rel': 0xD0}, 'BMI': {'rel': 0x30}, 'BPL': {'rel': 0x10},
    'BVC': {'rel': 0x50}, 'BVS': {'rel': 0x70}, 'BRA': {'rel': 0x80},
    'BRL': {'rell': 0x82},
    # implied
    'CLC': {'imp': 0x18}, 'CLD': {'imp': 0xD8}, 'CLI': {'imp': 0x58},
    'CLV': {'imp': 0xB8}, 'SEC': {'imp': 0x38}, 'SED': {'imp': 0xF8},
    'SEI': {'imp': 0x78}, 'DEX': {'imp': 0xCA}, 'DEY': {'imp': 0x88},
    'INX': {'imp': 0xE8}, 'INY': {'imp': 0xC8}, 'NOP': {'imp': 0xEA},
    'TAX': {'imp': 0xAA}, 'TAY': {'imp': 0xA8}, 'TXA': {'imp': 0x8A},
    'TYA': {'imp': 0x98}, 'TSX': {'imp': 0xBA}, 'TXS': {'imp': 0x9A},
    'TXY': {'imp': 0x9B}, 'TYX': {'imp': 0xBB}, 'TCD': {'imp': 0x5B},
    'TCS': {'imp': 0x1B}, 'TDC': {'imp': 0x7B}, 'TSC': {'imp': 0x3B},
    'XBA': {'imp': 0xEB}, 'XCE': {'imp': 0xFB},
    'PHA': {'imp': 0x48}, 'PHP': {'imp': 0x08}, 'PHX': {'imp': 0xDA},
    'PHY': {'imp': 0x5A}, 'PHB': {'imp': 0x8B}, 'PHD': {'imp': 0x0B},
    'PHK': {'imp': 0x4B}, 'PLA': {'imp': 0x68}, 'PLP': {'imp': 0x28},
    'PLX': {'imp': 0xFA}, 'PLY': {'imp': 0x7A}, 'PLB': {'imp': 0xAB},
    'PLD': {'imp': 0x2B}, 'RTI': {'imp': 0x40}, 'RTL': {'imp': 0x6B},
    'RTS': {'imp': 0x60}, 'STP': {'imp': 0xDB}, 'WAI': {'imp': 0xCB},
}

MNEMONICS = set(OPTABLE) | set(ALIAS)


class Fixup:
    """An operand value that must be resolved from the final symbol table."""
    __slots__ = ('expr', 'nbytes', 'kind', 'pc', 'shift')

    def __init__(self, expr, nbytes, kind, pc, shift=0):
        self.expr = expr      # expression text to evaluate
        self.nbytes = nbytes  # operand byte count
        self.kind = kind      # 'val' | 'rel8' | 'rel16' | 'byte'
        self.pc = pc          # location of the instruction (for branch math)
        self.shift = shift    # for 'byte': right-shift before masking to 1 byte


def _unpfx(e):
    """Strip a leading size/dp prefix (< > | !) from an inner expression."""
    e = e.strip()
    return e[1:].lstrip() if e[:1] in '<>|!' else e


def _strip_index(core):
    """Return (base, index) where index in (None,'x','y','s'), depth-0 suffix."""
    low = core.lower()
    for suf, idx in ((',x', 'x'), (',y', 'y'), (',s', 's')):
        if _ends_depth0(core, suf):
            return core[:-len(suf)].rstrip(), idx
    return core, None


def _ends_depth0(text, suf):
    if not text.lower().endswith(suf):
        return False
    depth = 0
    in_str = False
    for c in text:
        if c == "'":
            in_str = not in_str
        elif not in_str:
            if c in '([':
                depth += 1
            elif c in ')]':
                depth -= 1
    return depth == 0


def _width(expr, evaluate, forced, reloc=None, pc=0):
    if forced == '<':
        return 1
    if forced in ('|', '!'):
        return 2
    if forced == '>':
        return 3
    # A relocatable label / import reference is absolute (never direct page);
    # its final address is link-assigned.
    if reloc is not None and reloc(expr):
        return 2
    v = evaluate(expr)
    if v is None:
        return 2
    v &= 0xFFFFFF
    if v < 0x100:
        return 1
    if v < 0x10000:
        return 2
    # 24-bit address: long only when in a different bank than the PC; a same-bank
    # access uses a 16-bit absolute operand.
    return 3 if (v >> 16) != ((pc >> 16) & 0xFF) else 2


def _immwidth(m, longa, longi):
    if m in IMM_1:
        return 1
    if m in IMM_X:
        return 2 if longi else 1
    return 2 if longa else 1  # IMM_A and default


def encode(mnem, operand, longa, longi, evaluate, pc, reloc=None):
    """Return (bytes, fixup_or_None). `evaluate(expr)->int|None`.
    `reloc(expr)->bool` flags relocatable references (forced to absolute).
    `pc` is the location of this instruction (segment-relative)."""
    m = mnem.upper()
    m = ALIAS.get(m, m)
    tab = OPTABLE.get(m)
    if tab is None:
        return None, None

    # implied-only mnemonics take no operand; any trailing text is a comment
    if set(tab) <= {'imp'}:
        return bytes([tab['imp']]), None

    op = operand.strip()
    # accumulator / implied
    if op == '' or op.upper() == 'A':
        if 'acc' in tab:
            return bytes([tab['acc']]), None
        if 'imp' in tab:
            return bytes([tab['imp']]), None

    # block move: MVN src,dst -> opcode, dstbank, srcbank. Operands are 24-bit
    # addresses; the block-move banks are their bank bytes (bits 16-23).
    if m in BLOCKMOVE:
        parts = op.split(',')
        s = evaluate(parts[0]) if parts else None
        d = evaluate(parts[1]) if len(parts) > 1 else None
        bank = lambda v: ((v >> 16) if v and v >= 0x10000 else (v or 0)) & 0xFF
        return bytes([tab['bmv'], bank(d), bank(s)]), None

    # PEI is dp-indirect; PEA pushes an absolute word. Both may be written with
    # a leading '#'. Handle before the generic immediate case.
    if m == 'PEI':
        inner = op[1:-1] if op.startswith('(') else op.lstrip('#')
        base, _ = _strip_index(inner)
        return _emit(tab['dp'], _unpfx(base), 1, 'val', evaluate, pc)
    if m == 'PEA':
        inner = op.lstrip('#')
        # `pea #^X` / `#>X` / `#<X` push the bank / high / low part of X (2-byte
        # immediate), same byte-extraction the generic immediate path applies —
        # PEA previously dropped it, so `pea #^Loader_Entry` evaluated `^X` as a
        # bitwise op (-> $ffff) instead of X>>16. Same double-'#' quirk as the
        # generic immediate case below applies here too (`pea #^#N` bakes
        # $FFFF; see that block's comment — unverified against the corpus).
        if inner[:1] in '<>^':
            shift = {'<': 0, '>': 8, '^': 16}[inner[0]]
            return _emit(tab['abs'], _unpfx(inner[1:].strip()), 2, 'byte',
                         evaluate, pc, shift)
        return _emit(tab['abs'], _unpfx(inner), 2, 'val', evaluate, pc)

    # single-byte-immediate mnemonics (BRK/COP/REP/SEP/WDM) take a 1-byte
    # operand, with or without a leading '#'
    if m in IMM_1:
        return _emit(tab['imm'], op.lstrip('#').strip() or '0', 1, 'val', evaluate, pc)

    # immediate
    if op.startswith('#'):
        expr = op[1:].strip()
        w = _immwidth(m, longa, longi)
        # < > ^ select the low / high / bank part; the operand still occupies the
        # full immediate width (e.g. 2 bytes under LONGA ON), low part = the byte.
        #
        # DIALECT QUIRK, UNVERIFIED AGAINST THE ORACLE (task #15 investigation,
        # 2026-07): a DOUBLE immediate marker over a numeric literal --
        # `#^#0`/`#^#N` (as opposed to the ordinary `#^Label`/`#^0`) -- only
        # strips the OUTER '#' here (`expr[1:]` below); the leftover inner '#'
        # makes `expr.tokenize` raise Unresolved (see gsasm/expr.py's "unknown
        # char" case), so the fixup never resolves and asm.py's
        # apply_fixups/relink fallback bakes all-FF bytes: `pea #^#0` assembles
        # to PEA $FFFF, while `pea #^0` (single marker) correctly assembles to
        # PEA $0000. This surfaced via system-settings-gs's `PushLong` macro
        # (`pea #^&val`) called as `PushLong #N` -- the caller's own '#' landed
        # right where the macro's already nests one.
        #   A 97K-line sweep of this repo's byte-exact-validated MPW corpus
        # (ref/GSOS_6/IIGS.601.SRC + work/romsrc) found ZERO literal `#^#` (or
        # `#<#`/`#>#`) occurrences -- real AsmIIgs sources never exercise this
        # shape, so there is no captured .lst to confirm what real MPW AsmIIgs
        # does with it. Indirect (non-conclusive) evidence points the same
        # way real assemblers usually go with an ambiguous nested marker: at
        # least two independent MPW macro libraries in the corpus
        # (A.U.G/Finder/all.macros and GS.OS/FSTs/DOS3.3/my.all.macros, the
        # `add4`/`add8` 32/64-bit-add macros) explicitly test whether a
        # caller's own argument already starts with '#' and, if so, SLICE IT
        # OFF (`&a1[2:255]`) before re-prefixing with their own `#^`/`#<` --
        # i.e. real MPW macro authors engineered around ever emitting a literal
        # double marker, rather than relying on the assembler to tolerate one.
        # Do not change this fallback behavior without golden .lst evidence.
        if expr[:1] in '<>^':
            shift = {'<': 0, '>': 8, '^': 16}[expr[0]]
            return _emit(tab['imm'], expr[1:].strip(), w, 'byte', evaluate, pc, shift)
        return _emit(tab['imm'], expr, w, 'val', evaluate, pc)

    # branch
    if m in BRANCH8:
        return _emit(tab['rel'], op, 1, 'rel8', evaluate, pc)
    if m in BRANCH16:
        return _emit(tab['rell'], op, 2, 'rel16', evaluate, pc)

    forced = None
    core = op
    # long-indirect [..]
    if core.startswith('['):
        inner = core[1:]
        rb = inner.rfind(']')
        expr = _unpfx(inner[:rb])
        rest = inner[rb+1:].strip().lower()
        if rest == ',y':
            return _emit(tab['indly'], expr, 1, 'val', evaluate, pc)
        if m in ('JMP', 'JML'):
            return _emit(tab['aindl'], expr, 2, 'val', evaluate, pc)
        return _emit(tab['indl'], expr, 1, 'val', evaluate, pc)
    # ( .. ) indirect
    if core.startswith('('):
        inner = core[1:]
        rb = inner.rfind(')')
        head = inner[:rb]
        rest = inner[rb+1:].strip().lower()
        base, idx = _strip_index(head)
        base = _unpfx(base)
        if rest == ',y':
            if idx == 's':
                return _emit(tab['sriy'], base, 1, 'val', evaluate, pc)
            return _emit(tab['indy'], base, 1, 'val', evaluate, pc)
        if idx == 'x':
            if m in ('JMP', 'JSR'):
                return _emit(tab['aindx'], base, 2, 'val', evaluate, pc)
            return _emit(tab['indx'], base, 1, 'val', evaluate, pc)
        # plain (expr)
        if m in ('JMP', 'JML'):
            return _emit(tab['aind'], base, 2, 'val', evaluate, pc)
        return _emit(tab['ind'], base, 1, 'val', evaluate, pc)

    # size-forcing prefix
    if core[:1] in '<>|!':
        forced = core[0]
        core = core[1:].lstrip()
    base, idx = _strip_index(core)

    # control flow: never dp. A target in another bank (known value > 16 bits,
    # and not a relocatable same-segment label) promotes JMP->JML and JSR->JSL.
    def _crossbank():
        if forced == '>':
            return True
        if reloc is not None and reloc(base):
            return False
        v = evaluate(base)
        if v is None:
            return False
        v &= 0xFFFFFF
        # 16-bit target stays absolute (same-bank assumption); a 24-bit target
        # in a different bank than the PC promotes to a long transfer.
        if v < 0x10000:
            return False
        return (v >> 16) != ((pc >> 16) & 0xFF)

    if m == 'JSR':
        if idx == 'x':
            return _emit(tab['aindx'], base, 2, 'val', evaluate, pc)
        if _crossbank():
            return _emit(OPTABLE['JSL']['abl'], base, 3, 'val', evaluate, pc)
        return _emit(tab['abs'], base, 2, 'val', evaluate, pc)
    if m == 'JSL':
        return _emit(tab['abl'], base, 3, 'val', evaluate, pc)
    if m == 'JML':
        return _emit(tab['abl'], base, 3, 'val', evaluate, pc)
    if m == 'JMP':
        if _crossbank():
            return _emit(tab['abl'], base, 3, 'val', evaluate, pc)
        return _emit(tab['abs'], base, 2, 'val', evaluate, pc)

    w = _width(base, evaluate, forced, reloc, pc)
    fam = {'x': 'x', 'y': 'y', 's': 's', None: ''}[idx]
    mode = _pick_mode(tab, w, fam)
    if mode is None:
        # fall back to the widest available variant
        mode = _pick_mode(tab, 2, fam) or _pick_mode(tab, 1, fam)
    if mode is None:
        return bytes([0x00]) + b'\x00' * 1, None
    nb = {'dp': 1, 'dpx': 1, 'dpy': 1, 'sr': 1,
          'abs': 2, 'absx': 2, 'absy': 2,
          'abl': 3, 'ablx': 3}[mode]
    return _emit(tab[mode], base, nb, 'val', evaluate, pc)


def _pick_mode(tab, width, fam):
    if fam == 's':
        return 'sr' if 'sr' in tab else None
    order = {
        ('', 1): ['dp'], ('', 2): ['abs'], ('', 3): ['abl'],
        ('x', 1): ['dpx'], ('x', 2): ['absx'], ('x', 3): ['ablx'],
        ('y', 1): ['dpy'], ('y', 2): ['absy'], ('y', 3): ['absy'],
    }.get((fam, width), [])
    for k in order:
        if k in tab:
            return k
    # promote dp->abs if dp form missing
    if width == 1:
        return _pick_mode(tab, 2, fam)
    if width == 3:
        return _pick_mode(tab, 2, fam)
    return None


def _emit(opcode, expr, nbytes, kind, evaluate, pc, shift=0):
    val = None
    if kind in ('val', 'byte'):
        val = evaluate(expr)
    out = bytearray([opcode])
    if val is None:
        out += b'\x00' * nbytes          # placeholder; recorded as a fixup
        return bytes(out), Fixup(expr, nbytes, kind, pc, shift)
    if kind == 'byte':
        vv = (val >> shift) & ((1 << (8 * nbytes)) - 1)
        out += bytes((vv >> (8 * i)) & 0xFF for i in range(nbytes))
        return bytes(out), None
    if kind == 'rel8':
        rel = (val - (pc + 2)) & 0xFF
        out.append(rel)
    elif kind == 'rel16':
        rel = (val - (pc + 3)) & 0xFFFF
        out += bytes([rel & 0xFF, (rel >> 8) & 0xFF])
    else:
        v = val & ((1 << (8 * nbytes)) - 1)
        for i in range(nbytes):
            out.append((v >> (8 * i)) & 0xFF)
    return bytes(out), None


def instr_length(mnem, operand, longa, longi, evaluate):
    b, _ = encode(mnem, operand, longa, longi, evaluate, 0)
    return len(b) if b else 1
