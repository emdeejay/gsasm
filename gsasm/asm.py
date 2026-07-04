"""MPW IIgs assembler — pass 1 / macro engine (prototype).

Reads the original .aii/.asm sources (and AIIGSIncludes), expands macros and
conditional assembly, tracks the location counter and symbol table, and emits
a flat stream of expanded primitive lines. The output is what the object
emitter will later consume; for now it lets us validate against the .lst
`Loc` column.
"""
import os
import re

from . import expr
from . import m65816


def read_text(path):
    d = open(path, 'rb').read()
    return d.replace(b'\r\n', b'\n').replace(b'\r', b'\n').decode('mac_roman')


# --------------------------------------------------------------------------
# Line model
# --------------------------------------------------------------------------
class Line:
    __slots__ = ('label', 'op', 'operand', 'raw', 'comment')

    def __init__(self, label, op, operand, raw, comment=''):
        self.label = label
        self.op = op
        self.operand = operand
        self.raw = raw
        self.comment = comment

    def __repr__(self):
        return f"Line(lbl={self.label!r} op={self.op!r} opd={self.operand!r})"


def strip_comment(s):
    """Remove a trailing ;-comment that isn't inside a quoted string."""
    out = []
    in_str = False
    quote = ''
    i = 0
    while i < len(s):
        c = s[i]
        if in_str:
            out.append(c)
            if c == quote:
                in_str = False
        else:
            if c in "'\"":
                in_str = True; quote = c; out.append(c)
            elif c == ';':
                return ''.join(out), s[i:]
            else:
                out.append(c)
        i += 1
    return ''.join(out), ''


def parse_line(raw):
    """Parse a raw (already &-substituted) source line into fields."""
    text = raw.rstrip('\n')
    # Full-line comment: '*' or ';' in column 0
    if text[:1] in ('*', ';') or text.strip() == '':
        return Line(None, None, '', raw, text)
    body, comment = strip_comment(text)
    if body.strip() == '':
        return Line(None, None, '', raw, comment)
    # label present iff column 0 is non-blank
    label = None
    rest = body
    if body[:1] not in (' ', '\t'):
        m = re.match(r'\S+', body)
        label = m.group(0)
        if label.endswith(':'):
            label = label[:-1]
        rest = body[m.end():]
    else:
        # an INDENTED label is allowed when explicitly terminated by a colon,
        # e.g. a macro loop counter `\t&Counter: SETA &Counter+1` (the colon
        # marks it as a label so SETA's target isn't &-substituted to a value)
        ms = re.match(r'[ \t]*([&@?.A-Za-z_][\w&@?.]*):(?!:)', body)
        if ms:
            label = ms.group(1)
            rest = body[ms.end():]
    rest = rest.lstrip(' \t')
    if rest == '':
        return Line(label, None, '', raw, comment)
    m = re.match(r'\S+', rest)
    op = m.group(0)
    rest2 = rest[m.end():].lstrip(' \t').rstrip()
    # Operands have no internal whitespace (except quoted strings / multi-token
    # directives); anything past the first field is an unmarked comment.
    if op.upper() in _MULTI_TOKEN_OPS:
        operand = rest2
    else:
        operand = first_field(rest2)
    return Line(label, op, operand, raw, comment)


# Directives whose operand legitimately contains spaces.
_MULTI_TOKEN_OPS = {'IF', 'ELSEIF', 'WHILE', 'AIF', 'PROC', 'ERRIF', 'DO',
                    'ASSERT', 'PRINT', 'TITLE', 'LIST'}


def first_field(s):
    """Leading operand token: stops at the first whitespace that is at paren/
    bracket depth 0 and outside a quoted string. Whitespace ADJACENT to a comma
    is part of a comma-separated list (e.g. `DC.W Flag, 0`), not a comment
    boundary, so the operand continues across it."""
    depth = 0
    in_str = False
    quote = ''
    i, n = 0, len(s)
    while i < n:
        c = s[i]
        if in_str:
            if c == quote:
                in_str = False
        elif c in "'\"":
            in_str = True; quote = c
        elif c in '([':
            depth += 1
        elif c in ')]':
            depth -= 1
        elif c in ' \t' and depth == 0:
            prev = s[:i].rstrip()
            j = i
            while j < n and s[j] in ' \t':
                j += 1
            # a comma immediately BEFORE the whitespace means a list element
            # follows (`DC.W Flag, 0`). (We do NOT treat a comma AFTER the space
            # as a continuation: a comment can start with a comma, e.g.
            # `sta foo,x , put it back`.)
            if prev and prev[-1] == ',':
                i = j; continue
            return s[:i]
        i += 1
    return s


# --------------------------------------------------------------------------
# Macro definitions
# --------------------------------------------------------------------------
class Segment:
    """One OMF segment (per PROC). Items are ('code', sline, bytes) or
    ('ds', count); reloc-ness of code operands is decided at emit time."""
    def __init__(self, name, loadname, org, segnum):
        self.name = name              # SEGNAME (PROC name)
        self.loadname = loadname      # LOADNAME (SEG directive, or 'main')
        self.org = org                # explicit ORG address, or None
        self.segnum = segnum
        self.private = False          # KIND 0x4000 (PROC without EXPORT)
        self.is_data = False          # data segment (KIND data bit 0x01) — a
        self.items = []               #   no-operand RECORD..ENDR
        self.exports = []             # (name, kind, value)

    def length(self):
        n = 0
        for it in self.items:
            if it[0] == 'code':
                n += len(it[2])
            elif it[0] == 'ds':
                n += it[1]
        return n


class Macro:
    def __init__(self, name, label_var, suffix_var, params, body):
        self.name = name              # upper-case base name
        self.label_var = label_var    # &name that receives the call's label
        self.suffix_var = suffix_var  # &name receiving the ".X" suffix, or None
        self.params = params          # list of &param names (without &)
        self.body = body              # list of raw body lines


# --------------------------------------------------------------------------
# Assembler state
# --------------------------------------------------------------------------
class Asm:
    def __init__(self, include_paths, seed=None, seed_type=None, seg_seed=None,
                 sysdate=None, systime=None):
        self.include_paths = include_paths
        self.seed = seed or {}        # symbol values from a prior pass
        # &sysdate / &systime builtins: the assembler's build date/time strings.
        # When None the builtins return ''. Pass the original build date/time to
        # reproduce byte-exact golden binaries (e.g. P8: sysdate='06-May-93').
        self.sysdate = sysdate or ''
        self.systime = systime or ''
        self.seed_type = seed_type or {}   # symbol kinds from a prior pass
        self.symtype = {}             # name -> 'equ' | 'label' | 'import'
        self.symseg = {}              # label name -> defining segment index
        # per-segment code labels: a plain (non-exported) label is LOCAL to its
        # PROC/segment, so the same name (loop/done/error/SigError) may recur in
        # several PROCs. seg_local[segidx][NAME]=value; seg_seed = prior pass.
        self.seg_local = {}
        self.seg_seed = seg_seed or {}
        # PROC-local EQUATES: an EQU/SET inside a module is local to that module
        # and shadows a same-named code label defined in another PROC. seg_equ
        # [segidx][NAME]=value. (e.g. dialog `nextItem equ output`=$14 shadows the
        # `NextItem` routine label.)
        self.seg_equ = {}
        # @-labels can recur within one scope (reused local labels): track ALL
        # definition locs so a reference resolves to the NEXT-forward one.
        self.at_defs = {}             # @-label scope key -> [seg-relative offsets]
        self.at_seg = {}              # ...parallel [segment index] (segment-local)
        self.at_seed = {}             # prior pass's at_defs / at_seg
        self.at_seg_seed = {}
        self._ref_loc = None
        self._rseg = None             # current resolution segment (None=global)
        self._rlg = None              # last_global captured for a deferred fixup
        self._rlg2 = None             # enclosing global scope (macro @-ref fallback)
        self._defining = False        # True while define_label keys a new symbol
        self.globals = {}             # macro variable name -> value (int|str)
        self.gkind = {}               # name -> 'A'|'C'|'B'
        self.localstack = []          # list of (vars, kind) dicts
        self.macros = {}              # NAME -> Macro
        self.symbols = {}             # asm symbol -> int value
        self.defcount = {}            # asm symbol -> times defined
        self.entry_seg = {}           # ENTRY/EXPORT name -> seg name of its directive
        self.link_bases = None        # link mode: seg index -> final base address
        self.extern = {}              # link mode: cross-module symbol -> final addr
        self.imports = set()
        self.loc = 0
        self.emit_enabled = True      # False inside RECORD (offsets only)
        self.fixups = []              # (bytearray, offset, Fixup) to patch later
        self.record_stack = []        # saved (loc, emit, name) per RECORD..ENDR
        self.cur_record = None        # current RECORD name (for qualified fields)
        self._record_dec = False      # current RECORD allocates fields downward
        self.with_stack = []          # active WITH record names (field namespace)
        self.last_global = ''         # most recent global label (@-local scope)
        self.local_ctx = ''           # current macro-expansion context id
        self.macro_uid = 0
        self.macro_at = []            # stack of {@LABEL: (ctx,lg)} for @-labels
                                      # passed as macro params (retain caller scope)
        self.in_proc = False
        self.proc_depth = 0           # PROC/ENDP nesting (nested PROC != new seg)
        self.exports = set()          # names exported (EXPORT / ENTRY)
        self.entries = set()          # ENTRY labels
        self.seg_name = None          # first PROC name (OMF segment name)
        self.segs = [Segment(None, 'main', None, 1)]   # OMF segments by PROC
        self.pending_loadname = None  # from a SEG directive
        # MPW IIgs assembler defaults to 16-bit accumulator/index (toolbox is
        # 16-bit native); 8-bit code sets LONGA/LONGI OFF explicitly.
        self.longa = True
        self.longi = True
        self.string_mode = 'ASIS'
        self.msb = 'OFF'
        self.out = []                 # expanded primitive lines (text)
        self.emitted = []             # (loc, sline, bytes) for byte validation
        self.labels = []              # (name, loc) in order, for validation
        self.errors = []
        self._cur_file = '<unknown>'
        self._cur_line = 0
        self.ended = False
        self.dirstack = []            # current directory per active file unit

    # ---- diagnostics ----
    def _err(self, msg):
        self.errors.append(f"{self._cur_file}:{self._cur_line}: error: {msg}")

    # ---- macro variable scope ----
    def declare(self, name, kind, local):
        name = name.lower()
        store, kstore = self._store(local)
        if kind == 'A':
            store.setdefault(name, 0)
        elif kind == 'B':
            store.setdefault(name, 0)
        else:
            store.setdefault(name, '')
        kstore[name] = kind

    def _store(self, local):
        if local and self.localstack:
            top = self.localstack[-1]
            return top[0], top[1]
        return self.globals, self.gkind

    def setvar(self, name, value):
        name = name.lower()
        # assign to nearest existing scope, else global
        for vars_, _ in reversed(self.localstack):
            if name in vars_:
                vars_[name] = value
                return
        self.globals[name] = value

    def getvar(self, name):
        name = name.lower()
        for vars_, _ in reversed(self.localstack):
            if name in vars_:
                return vars_[name]
        return self.globals.get(name)

    def hasvar(self, name, where):
        name = name.lower()
        if where == 'GLOBAL':
            return name in self.globals
        if self.localstack and name in self.localstack[-1][0]:
            return True
        return name in self.globals

    # ---- symbol resolution for expressions ----
    def _symkey(self, name):
        # @-labels are LOCAL to the enclosing non-@ label (or, inside a macro
        # expansion, to THAT expansion's unique local_ctx). During deferred fixup
        # resolution / OMF emit, use the scope captured when the line was emitted
        # (_rlg) rather than the stale end-of-file one.
        if name.startswith('@'):
            caller = None
            if self.macro_at:
                nu = name.upper()
                for fr in reversed(self.macro_at):
                    if nu in fr:
                        caller = fr[nu]; break
            if caller is not None:        # @-label passed as a macro param
                primary, enclosing = caller
            elif self._rlg is not None:
                primary, enclosing = self._rlg, (self._rlg2 or self._rlg)
            else:
                primary = self.local_ctx or self.last_global
                enclosing = self.last_global
            key = (primary + name).upper()
            # While DEFINING a label, always key it in its own scope. When
            # REFERENCING, a macro body may name a @-label defined in the calling
            # routine: if the macro-local key is undefined, fall back to the
            # enclosing scope.
            if self._defining or self._defined(key) or enclosing == primary:
                return key
            alt = (enclosing + name).upper()
            return alt if self._defined(alt) else key
        return name.upper()

    def _defined(self, key):
        return (key in self.at_defs or key in self.at_seed
                or key in self.symbols or key in self.seed)

    def resolve(self, name):
        u = self._symkey(name)        # @-label scope fallback handled in _symkey
        lb = self.link_bases          # link mode: add a segment's final base to
        seg = self._rseg              # relocatable label values (else None = no-op)
        if seg is None and self.emit_enabled and self.segs:
            seg = len(self.segs) - 1

        def based(v, sgi):            # add the final base of segment sgi (link mode)
            return v + (lb.get(sgi, 0) if lb is not None else 0)

        if name.startswith('@'):
            # Use the COMPLETE def list (prior pass's at_seed) when available so a
            # @-ref sees its FORWARD definitions too — at assembly time the current
            # pass's at_defs only holds the backward defs seen so far, which would
            # bind a forward `jsr @2` to a nearer backward @2. The prior pass's
            # positions are stable on a converged 2-pass.
            if u in self.at_seed:
                defs, segs = self.at_seed[u], self.at_seg_seed.get(u, [])
            else:
                defs, segs = self.at_defs.get(u), self.at_seg.get(u, [])
            if defs:
                # @-labels are SEGMENT-LOCAL: a reused enclosing label name (e.g.
                # `GoReallyFast` in both FastSlabCopy and FastSlabXOR) collides on
                # the scope key, so restrict candidates to the current segment.
                pairs = list(zip(defs, segs)) if len(segs) == len(defs) else \
                    [(d, None) for d in defs]
                same = [d for d, sg in pairs if sg == seg]
                cand = same or defs
                if len(cand) > 1:
                    ref = self._ref_loc if self._ref_loc is not None else self.loc
                    # nearest definition by distance (ties -> backward/preceding)
                    return based(min(cand, key=lambda d: (abs(d - ref), d > ref)), seg)
                if same:
                    return based(cand[0], seg)
        # WITH record context: an unqualified field name resolves to the active
        # record's field (offsets, NOT relocatable -> no base added)
        if self.with_stack and '.' not in name:
            for recs in reversed(self.with_stack):
                for rec in recs:
                    q = rec + '.' + u
                    if q in self.symbols:
                        return self.symbols[q]
                    if q in self.seed:
                        return self.seed[q]
        # a local label in the current segment shadows a same-named label
        # defined in another PROC/segment
        if seg is not None:
            loc = self.seg_local.get(seg)
            if loc and u in loc:
                return based(loc[u], seg)
            # a PROC-local equate shadows a same-named code label in another PROC
            eq = self.seg_equ.get(seg)
            if eq and u in eq:
                return eq[u]                          # equate -> absolute value
            sd = self.seg_seed.get(seg)
            if sd and u in sd:
                return based(sd[u], seg)
        if u in self.symbols:
            v = self.symbols[u]
            if lb is not None and self.symtype.get(u) == 'label':
                return based(v, self.symseg.get(u, seg))   # label in its own seg
            return v                                        # equate -> absolute
        if lb is not None:                                  # link mode fallbacks
            s = self.seed.get(u)
            if s is not None:
                if self.seed_type.get(u) == 'label':
                    return based(s, self.symseg.get(u, seg))
                return s
            return self.extern.get(name.upper())            # cross-module symbol
        return self.seed.get(u)        # forward reference resolved from prior pass

    def evaluate(self, text, pc=None):
        # `*` resolves to `pc` (defaults to the live location). Deferred fixups
        # must pass the fixup's own pc so `*`-relative operands (e.g. `bcc *+8`)
        # resolve against the instruction's location, not the end of assembly.
        # MSB ON sets the high bit of character constants ('A' -> $C1).
        return expr.try_eval(text, self.resolve, self.loc if pc is None else pc,
                             msb=(self.msb == 'ON'))

    # ----------------------------------------------------------------
    # & substitution
    # ----------------------------------------------------------------
    def subst(self, text):
        if '&' not in text:
            return text
        out = []
        i, n = 0, len(text)
        while i < n:
            c = text[i]
            if c != '&':
                out.append(c); i += 1; continue
            # parse &NAME possibly NAME(args) or NAME[slice]
            j = i + 1
            while j < n and (text[j].isalnum() or text[j] == '_'):
                j += 1
            name = text[i+1:j]
            if name == '':
                out.append('&'); i += 1; continue
            # function call?
            if j < n and text[j] == '(':
                args, j2 = self._read_args(text, j)
                val = self.call_builtin(name, args)
                out.append(val)
                i = j2
                continue
            # variable, with optional [slice]
            val = self._var_str(name)
            if j < n and text[j] == '[':
                sl, j = self._read_bracket(text, j)
                val = self._slice(val, sl)
            else:
                # consume a single separator dot
                if j < n and text[j] == '.':
                    j += 1
            out.append(val)
            i = j
        return ''.join(out)

    def _var_str(self, name):
        if name.upper() == 'SYSGLOBAL':
            return 'GLOBAL'
        if name.upper() == 'SYSLOCAL':
            return 'LOCAL'
        # &sysdate and &systime are assembler built-in variables (no parens)
        if name.upper() == 'SYSDATE':
            return self.sysdate
        if name.upper() == 'SYSTIME':
            return self.systime
        v = self.getvar(name)
        if v is None:
            # undefined macro var -> empty string (MPW behaviour)
            return ''
        return str(v)

    def _read_args(self, text, jopen):
        """text[jopen]=='(' -> (list_of_substituted_args, index_after_close)."""
        depth = 0
        i = jopen
        args = []
        cur = []
        in_str = False
        quote = ''
        while i < len(text):
            c = text[i]
            if in_str:
                cur.append(c)
                if c == quote:
                    in_str = False
            elif c in "'\"":
                in_str = True; quote = c; cur.append(c)
            elif c == '(':
                depth += 1
                if depth > 1:
                    cur.append(c)
                i += 1
                continue
            elif c == ')':
                depth -= 1
                if depth == 0:
                    args.append(''.join(cur))
                    i += 1
                    break
                cur.append(c)
            elif c == ',' and depth == 1:
                args.append(''.join(cur)); cur = []
            else:
                cur.append(c)
            i += 1
        # no-argument call: empty parens
        if len(args) == 1 and args[0].strip() == '':
            return [], i
        # recursively substitute each arg
        args = [self.subst(a.strip()) for a in args]
        return args, i

    def _read_bracket(self, text, jopen):
        depth = 0
        i = jopen
        cur = []
        while i < len(text):
            c = text[i]
            if c == '[':
                depth += 1
                if depth > 1:
                    cur.append(c)
            elif c == ']':
                depth -= 1
                if depth == 0:
                    i += 1
                    break
                cur.append(c)
            else:
                cur.append(c)
            i += 1
        return self.subst(''.join(cur)), i

    def _slice(self, s, spec):
        # spec is "start:len" or "start"
        s = _unquote(s)
        if ':' in spec:
            a, b = spec.split(':', 1)
            start = self.evaluate(a) or 0
            length = self.evaluate(b) or 0
            return s[start-1:start-1+length]
        start = self.evaluate(spec) or 0
        return s[start-1:start]

    # ----------------------------------------------------------------
    # Builtins
    # ----------------------------------------------------------------
    def call_builtin(self, name, args):
        u = name.upper()
        if u == 'EVAL':
            v = self.evaluate(args[0]) if args else 0
            return str(v if v is not None else 0)
        if u == 'CONCAT':
            return ''.join(_unquote(a) for a in args)
        if u == 'TRIM':
            return _unquote(args[0]).strip() if args else ''
        if u == 'LEN':
            return str(len(_unquote(args[0]))) if args else '0'
        if u in ('UC', 'UPCASE', 'UPPERCASE'):
            return _unquote(args[0]).upper() if args else ''
        if u in ('LC', 'DOWNCASE'):
            return _unquote(args[0]).lower() if args else ''
        if u == 'SUBSTR':
            s = _unquote(args[0])
            start = self.evaluate(args[1]) or 0
            length = self.evaluate(args[2]) if len(args) > 2 else len(s)
            return s[start-1:start-1+length]
        if u in ('I2S', 'INTTOSTR'):
            v = self.evaluate(args[0]) or 0
            # &I2S(value [, minwidth [, fmt]]): fmt==1 -> hex (zero-padded to
            # minwidth); otherwise decimal. (1-arg form is decimal.)
            if len(args) >= 3:
                width = self.evaluate(args[1]) or 0
                fmt = self.evaluate(args[2]) or 0
                if fmt == 1 or fmt == 16:
                    s = format(v & 0xFFFFFFFF, 'X')
                    return s.rjust(width, '0') if width else s
            return str(v)
        if u == 'S2I':
            return str(self.evaluate(args[0]) or 0)
        if u == 'FINDSYM':
            where = _unquote(args[0]).upper() if args else 'GLOBAL'
            nm = _unquote(args[1]) if len(args) > 1 else ''
            return '1' if self.hasvar(nm, where) else '0'
        if u == 'SETTING':
            key = _unquote(args[0]).upper() if args else ''
            if key == 'LONGA':
                return 'ON' if self.longa else 'OFF'
            if key == 'LONGI':
                return 'ON' if self.longi else 'OFF'
            if key == 'STRING':
                return self.string_mode
            if key == 'MSB':
                return self.msb
            if key == 'MACHINE':
                return 'M65816'
            return ''
        if u == 'DEFAULT':
            a = _unquote(args[0]) if args else ''
            return a if a != '' else (_unquote(args[1]) if len(args) > 1 else '')
        if u == 'ISINT':
            return '1' if (args and self.evaluate(args[0]) is not None) else '0'
        if u == 'TYPE':
            return 'INT'
        # &sysdate / &systime: the assembler's build date / time. AsmIIgs
        # formats these as dd-Mon-yy / hh:mm:ss.  The exact value is a
        # module-level constant (set at Asm construction time) so harnesses
        # can inject the original build date for byte-exact reproduction.
        if u == 'SYSDATE':
            return self.sysdate
        if u == 'SYSTIME':
            return self.systime
        # unknown builtin -> empty
        self._err(f"unknown builtin &{name}")
        return ''

    # ----------------------------------------------------------------
    # Includes
    # ----------------------------------------------------------------
    def resolve_include(self, spec, curdir):
        """Resolve an MPW include path. Colon is the path separator; a leading
        run of N colons means "current dir" (N=1) or up (N-1) levels (N>=2)."""
        name = spec.strip().strip("'\"")
        parts = name.split(':')
        lead = 0
        while lead < len(parts) and parts[lead] == '':
            lead += 1
        comps = [p for p in parts[lead:] if p != '']
        rel = '/'.join(comps)
        leaf = comps[-1] if comps else name

        if lead >= 1 and curdir:
            base = curdir
            for _ in range(lead - 1):
                base = os.path.dirname(base)
            p = _find_ci(base, rel)
            if p:
                return p

        # lead == 0 (or relative miss): current dir first, then search paths
        search = ([curdir] if curdir else []) + list(self.include_paths)
        for base in search:
            for cand in (rel, leaf):
                p = _find_ci(base, cand)
                if p:
                    return p
        return None

    def do_include(self, spec):
        curdir = self.dirstack[-1] if self.dirstack else None
        p = self.resolve_include(spec, curdir)
        if not p:
            self._err(f"include not found: {spec}")
            return
        self.run_unit(read_text(p).split('\n'), os.path.dirname(p), filepath=p)

    # ----------------------------------------------------------------
    # Symbol / location helpers
    # ----------------------------------------------------------------
    def define_label(self, name, value, kind='label'):
        if name:
            # ANY label not beginning with @ delimits @-local-label scope (MPW
            # Asm Ref, "@-labels": scope extends both directions to the nearest
            # non-@ label) — code labels AND equates (e.g. `NAME EQU *`), but not
            # RECORD field definitions (those live in the record's namespace).
            if not name.startswith('@') and not self.cur_record:
                self.last_global = name.upper()
            self._defining = True         # key @-labels in their own scope
            u = self._symkey(name)
            self._defining = False
            # A RECORD field is NOT a global symbol — it is reachable only as
            # RecordName.field or (bare) inside WITH RecordName. Defining its bare
            # name globally would let a later record's field clobber a real equate
            # of the same name (e.g. PopUpCtlRecord.titleWidth=64 vs the menu
            # `titleWidth EQU 14`). So inside a RECORD, define ONLY the qualified
            # name (unless the bare name is otherwise undefined — harmless).
            field = self.cur_record and '.' not in name
            if field:
                q = (self.cur_record + '.' + name).upper()
                self.symbols[q] = value
                self.symtype[q] = 'equ'
                if u not in self.symbols:             # don't clobber a real symbol
                    self.symbols[u] = value
                    self.symtype[u] = kind
                self.defcount[u] = self.defcount.get(u, 0) + 1
                self.labels.append((name, value))
                return
            self.symbols[u] = value
            self.symtype[u] = kind
            self.defcount[u] = self.defcount.get(u, 0) + 1
            self.labels.append((name, value))
            if kind == 'label':
                seg = len(self.segs) - 1
                self.symseg[u] = seg                  # defining segment index
                self.seg_local.setdefault(seg, {})[u] = value
            # an EQU/SET inside a module (PROC) is local to that module — record it
            # so a reference within the module resolves to it (as a literal),
            # shadowing any same-named code label defined in another PROC
            elif kind == 'equ' and self.in_proc and not name.startswith('@'):
                self.seg_equ.setdefault(len(self.segs) - 1, {})[u] = value
            # record @-label positions (label OR `@x EQU *`) for nearest-forward,
            # with the defining segment so resolution stays segment-local
            if name.startswith('@'):
                self.at_defs.setdefault(u, []).append(value)
                self.at_seg.setdefault(u, []).append(len(self.segs) - 1)

    def needs_reloc(self, expr):
        """True if an operand reference needs an OMF relocation record: an import,
        a label in a relocatable (non-ORG) segment, or an undefined symbol (an
        implicit external — MPW lets you reference externals without IMPORT)."""
        seg = self._rseg
        for ident in re.findall(r'[A-Za-z_~@?.][\w~@?.]*', expr):
            u = self._symkey(ident)
            if u in self.imports:
                return True
            # a label local to the current emit segment (seg_local only holds
            # 'label' defs) — shadows a same-named global equate, e.g. a dp
            # equate `frame` vs a code label `frame` inside this segment
            if seg is not None and u in self.seg_local.get(seg, {}):
                if self.segs[seg].org is None:
                    return True
                continue
            # a PROC-local equate is an absolute value -> never relocated
            if seg is not None and u in self.seg_equ.get(seg, {}):
                continue
            if self.symtype.get(u) == 'label':
                si = self.symseg.get(u)
                if si is not None and self.segs[si].org is None:
                    return True
        return False

    def sym_kind(self, name):
        u = self._symkey(name)
        # a label local to the current emit segment shadows a same-named global
        # equate (e.g. dp equate vs in-segment code label of the same name)
        seg = self._rseg
        if seg is not None and u in self.seg_local.get(seg, {}):
            return 'label'
        # a PROC-local equate shadows a same-named code label in another PROC
        if seg is not None and u in self.seg_equ.get(seg, {}):
            return 'equ'
        # a local definition overrides an IMPORT declaration of the same name
        # (modules sometimes IMPORT a symbol they also define locally)
        if self.symtype.get(u) == 'label':
            return 'label'
        # a local EQUATE likewise overrides an IMPORT: an equate is an absolute
        # value, so its width/relocation is fixed, not link-assigned (e.g. a dp
        # equate `ctlPart EQU $21` that the module also IMPORTs must size direct-
        # page, not absolute).
        if self.symtype.get(u) == 'equ':
            return 'equ'
        if u in self.imports:
            return 'import'
        return self.symtype.get(u) or self.seed_type.get(u)

    def is_reloc(self, expr):
        """True if the expression references a relocatable label or import
        (such an operand must use absolute/long, never direct page)."""
        for ident in re.findall(r'[A-Za-z_~@?.][\w~@?.]*', expr):
            if self.sym_kind(ident) in ('label', 'import'):
                return True
        return False

    # ---- emission (per-line, self-contained) ----
    def emit_line(self, ln, data, fixups):
        """Record an emitted line: (loc, source line, mutable bytes).
        `fixups` is a list of (offset_in_line, Fixup). Inside a RECORD we only
        advance the location (fields are offsets, not stored bytes)."""
        at = self.loc
        barr = bytearray(data)
        if self.emit_enabled:
            self.emitted.append((at, ln, barr))
            seg = len(self.segs) - 1
            atscope = self.local_ctx or self.last_global    # @-label scope
            # also capture the enclosing global (for a macro body that references
            # a @-label defined in the calling routine)
            self.segs[-1].items.append(('code', ln, barr, atscope, self.last_global))
            for off, fx in fixups:
                self.fixups.append((barr, off, fx, seg, atscope, self.last_global))
        self.loc += len(barr)

    def reserve(self, n):
        if self.emit_enabled and n > 0:
            self.segs[-1].items.append(('ds', n, None))
        self.loc += n

    def apply_fixups(self):
        for barr, off, fx, seg, lg, lg2 in self.fixups:
            self._rseg = seg          # resolve local labels in the fixup's segment
            self._rlg = lg            # ...and @-labels in the fixup's @-scope
            self._rlg2 = lg2          # ...enclosing scope (macro @-ref fallback)
            self._ref_loc = fx.pc     # ...resolving @-labels relative to this ref
            v = self.evaluate(fx.expr, pc=fx.pc)   # `*` -> this instruction's loc
            if v is None:
                barr[off:off+fx.nbytes] = b'\xFF' * fx.nbytes
                continue
            if fx.kind == 'byte':
                vv = (v >> fx.shift) & ((1 << (8 * fx.nbytes)) - 1)
                barr[off:off+fx.nbytes] = bytes((vv >> (8 * i)) & 0xFF
                                                for i in range(fx.nbytes))
            elif fx.kind == 'rel8':
                barr[off] = (v - (fx.pc + 2)) & 0xFF
            elif fx.kind == 'rel16':
                rel = (v - (fx.pc + 3)) & 0xFFFF
                barr[off:off+2] = bytes([rel & 0xFF, (rel >> 8) & 0xFF])
            else:
                vv = v & ((1 << (8 * fx.nbytes)) - 1)
                barr[off:off+fx.nbytes] = bytes((vv >> (8 * i)) & 0xFF
                                                for i in range(fx.nbytes))
        self._rseg = None
        self._rlg = None
        self._rlg2 = None

    def relink(self, seg_bases, extern):
        """LINK pass: re-resolve every fixup to its FINAL address. `seg_bases`
        maps a segment index to its final base address (placed by the linker);
        `extern` maps cross-module symbols to their final addresses. Patches the
        segment byte arrays in place (overwriting the seg-relative values from
        the assembly-time apply_fixups). `*` and branch math use the final pc."""
        self.link_bases = seg_bases
        self.extern = extern
        for barr, off, fx, seg, lg, lg2 in self.fixups:
            self._rseg = seg
            self._rlg = lg
            self._rlg2 = lg2
            base = seg_bases.get(seg, 0)
            self._ref_loc = fx.pc       # @-nearest-def vs seg-relative at_defs
            final_pc = base + fx.pc      # `*` and branch math in final address space
            v = self.evaluate(fx.expr, pc=final_pc)
            if v is None:
                continue                        # unresolved -> leave assembly bytes
            if fx.kind == 'byte':
                vv = (v >> fx.shift) & ((1 << (8 * fx.nbytes)) - 1)
                barr[off:off+fx.nbytes] = bytes((vv >> (8 * i)) & 0xFF
                                                for i in range(fx.nbytes))
            elif fx.kind == 'rel8':
                barr[off] = (v - (final_pc + 2)) & 0xFF
            elif fx.kind == 'rel16':
                rel = (v - (final_pc + 3)) & 0xFFFF
                barr[off:off+2] = bytes([rel & 0xFF, (rel >> 8) & 0xFF])
            else:
                vv = v & ((1 << (8 * fx.nbytes)) - 1)
                barr[off:off+fx.nbytes] = bytes((vv >> (8 * i)) & 0xFF
                                                for i in range(fx.nbytes))
        self.link_bases = None
        self._rseg = self._rlg = self._ref_loc = None

    # ----------------------------------------------------------------
    # Conditionals
    # ----------------------------------------------------------------
    def eval_cond(self, text, raw=False):
        # raw=True: `text` is UN-substituted. We split on the operator FIRST then
        # substitute each side, so a value that expands to an operator char (e.g.
        # &addr[1:1] -> '<') can't merge with the following '=' into a spurious
        # '<=' (which broke PushWord/PushLong with a '<'/'>' operand).
        t = text.strip()
        if t.upper().endswith(' THEN'):
            t = t[:-5].strip()
        elif t.upper().endswith(' DO'):
            t = t[:-3].strip()
        elif t.upper() in ('THEN', 'DO'):
            return True
        t = t.replace('≠', '<>').replace('≤', '<=').replace('≥', '>=')
        return self._cond_or(t, raw)

    def _cond_or(self, t, raw=False):
        parts = _split_kw(t, 'OR')
        if len(parts) > 1:
            return any(self._cond_and(p, raw) for p in parts)
        return self._cond_and(t, raw)

    def _cond_and(self, t, raw=False):
        parts = _split_kw(t, 'AND')
        if len(parts) > 1:
            return all(self._cond_leaf(p, raw) for p in parts)
        return self._cond_leaf(t, raw)

    def _cond_leaf(self, t, raw=False):
        t = t.strip()
        if t[:1] == '(' and t[-1:] == ')':
            return self._cond_or(t[1:-1], raw)
        for opref in ('<>', '<=', '>=', '=', '<', '>'):
            idx = _find_op(t, opref)
            if idx is not None:
                lhs = t[:idx].strip()
                rhs = t[idx+len(opref):].strip()
                if raw:
                    lhs = self.subst(lhs); rhs = self.subst(rhs)
                return _compare(self, lhs, rhs, opref)
        return bool(self.evaluate(self.subst(t) if raw else t))

    # ----------------------------------------------------------------
    # Main loop over a unit (file or macro body)
    # ----------------------------------------------------------------
    def run_unit(self, lines, basedir=None, filepath=None, track_lines=True):
        pushed = False
        if basedir is not None:
            self.dirstack.append(basedir); pushed = True
        saved_file = self._cur_file
        saved_line = self._cur_line
        if filepath is not None:
            self._cur_file = filepath
            self._cur_line = 0
        try:
            self._run_unit(lines, track_lines=track_lines)
        finally:
            if pushed:
                self.dirstack.pop()
            self._cur_file = saved_file
            self._cur_line = saved_line

    def _run_unit(self, lines, track_lines=True):
        cond = []  # list of [emit_now, any_taken, parent_emit]

        # sequence-label map for GOTO/AGO/AIF (macro-time control flow)
        seqmap = {}
        while_end = {}      # WHILE line idx -> matching ENDWHILE idx
        endwhile_start = {}  # ENDWHILE line idx -> matching WHILE idx
        wstack = []
        for idx, ln in enumerate(lines):
            pl = parse_line(ln)
            if pl.label:
                seqmap.setdefault(pl.label.upper(), idx)
            o = (pl.op or '').upper()
            if o == 'WHILE':
                wstack.append(idx)
            elif o == 'ENDWHILE' and wstack:
                w = wstack.pop()
                while_end[w] = idx
                endwhile_start[idx] = w

        def emitting():
            return cond[-1][0] if cond else True

        def goto(target):
            t = first_field(target.strip()).upper()   # strip leading ws ('GOTO .a')
            return seqmap.get(t)

        i = 0
        n = len(lines)
        steps = 0
        while i < n and not self.ended:
            steps += 1
            if steps > 2_000_000:           # runaway GOTO/WHILE guard
                self._err("aborted: too many macro-time steps")
                break
            if track_lines:                 # macro bodies keep the call-site loc
                self._cur_line = i + 1
            raw = lines[i]
            i += 1
            pre = parse_line(raw)
            op = (pre.op or '').upper()

            # ---- MEXIT: terminate the current macro expansion ----
            if op == 'MEXIT':
                if emitting():
                    break
                continue

            # ---- macro-time control transfer ----
            if op in ('GOTO', 'AGO'):
                if emitting():
                    j = goto(self.subst(pre.operand))
                    if j is not None:
                        i = j
                continue
            if op == 'AIF':
                # AIF <cond> <label>  (label is the last whitespace field)
                if emitting():
                    rest = self.subst(pre.operand)
                    toks = rest.rsplit(None, 1)
                    if len(toks) == 2 and self.eval_cond(toks[0]):
                        j = goto(toks[1])
                        if j is not None:
                            i = j
                continue

            # ---- WHILE..ENDWHILE macro-time loop ----
            if op == 'WHILE':
                if emitting():
                    cond = re.sub(r'\bDO\s*$', '', pre.operand, flags=re.I)
                    if not self.eval_cond(cond, raw=True):
                        i = while_end.get(i - 1, i - 1) + 1   # skip the loop body
                continue
            if op == 'ENDWHILE':
                if emitting():
                    i = endwhile_start.get(i - 1, i - 1)      # back to the WHILE
                continue

            # ---- conditional structure (always processed) ----
            if op == 'IF':
                # "IF <cond> GOTO <label>" is a conditional jump, not a block
                gi = re.search(r'\bGOTO\b', pre.operand, re.I)
                if gi:
                    if emitting():
                        target = self.subst(pre.operand[gi.end():])
                        if self.eval_cond(pre.operand[:gi.start()], raw=True):
                            j = goto(target)
                            if j is not None:
                                i = j
                    continue
                parent = emitting()
                c = self.eval_cond(pre.operand, raw=True) if parent else False
                cond.append([parent and c, parent and c, parent])
                continue
            if op == 'ELSEIF':
                top = cond[-1]
                parent = top[2]
                c = self.eval_cond(pre.operand, raw=True) if (parent and not top[1]) else False
                en = parent and (not top[1]) and c
                cond[-1] = [en, top[1] or en, parent]
                continue
            if op == 'ELSE':
                top = cond[-1]
                parent = top[2]
                en = parent and not top[1]
                cond[-1] = [en, True, parent]
                continue
            if op == 'ENDIF':
                if cond:
                    cond.pop()
                continue

            if not emitting():
                # skip, but consume macro bodies wholesale
                if op == 'MACRO':
                    depth = 1
                    while i < n and depth:
                        o2 = (parse_line(lines[i]).op or '').upper()
                        if o2 == 'MACRO':
                            depth += 1
                        elif o2 in ('MEND', 'ENDM'):
                            depth -= 1
                        i += 1
                continue

            # ---- macro definition ----
            if op == 'MACRO':
                body = []
                proto = None
                depth = 1
                while i < n:
                    l2 = lines[i]; i += 1
                    o2 = (parse_line(l2).op or '').upper()
                    if o2 == 'MACRO':
                        depth += 1
                    elif o2 in ('MEND', 'ENDM'):
                        depth -= 1
                        if depth == 0:
                            break
                    if proto is None and l2.strip() != '' and not l2.lstrip().startswith((';', '*')):
                        proto = l2
                        continue
                    body.append(l2)
                if proto is not None:
                    self._define_macro(proto, body)
                continue

            if op in ('MEND', 'ENDM'):
                continue

            # ---- control directives needing no & in op ----
            if op == 'INCLUDE':
                self.do_include(pre.operand)
                continue
            if op == 'END':
                self.ended = True
                break

            # ---- declarations / assignments: target name must NOT be & substituted
            if op in ('GBLA', 'GBLC', 'GBLB', 'LCLA', 'LCLC', 'LCLB',
                      'SETA', 'SETB', 'SETC'):
                self.handle_var(op, pre)
                continue

            # ---- normal line: substitute, parse, dispatch ----
            sline = parse_line(self.subst(raw))
            # record the expanded primitive line (skip macro-call markers; their
            # expansion is recorded as it is processed)
            if sline.op is not None and self.find_macro(sline.op)[0] is None:
                self.out.append((self.loc, sline))
            self.dispatch(sline)

        return

    def handle_var(self, u, pre):
        if u in ('GBLA', 'GBLC', 'GBLB'):
            for nm in _split_commas(pre.operand or ''):
                nm = nm.strip().lstrip('&')
                if nm:
                    self.declare(nm, u[3], local=False)
            return
        if u in ('LCLA', 'LCLC', 'LCLB'):
            for nm in _split_commas(pre.operand or ''):
                nm = nm.strip().lstrip('&')
                if nm:
                    self.declare(nm, u[3], local=True)
            return
        name = (pre.label or '').lstrip('&')
        if not name:
            return
        if u in ('SETA', 'SETB'):
            self.setvar(name, self.evaluate(self.subst(pre.operand)) or 0)
        else:  # SETC
            self.setvar(name, _unquote(self.subst(pre.operand)))

    def _define_macro(self, proto_raw, body):
        pl = parse_line(proto_raw)
        label_var = pl.label[1:] if pl.label and pl.label.startswith('&') else None
        opname = pl.op or ''
        suffix_var = None
        base = opname
        if '.&' in opname:
            base, suf = opname.split('.&', 1)
            suffix_var = suf
        elif '.' in opname and opname.split('.', 1)[1].startswith('&'):
            base, suf = opname.split('.', 1)
            suffix_var = suf[1:]
        params = []
        if pl.operand:
            for tok in _split_commas(pl.operand):
                tok = tok.strip()
                if tok.startswith('&'):
                    params.append(tok[1:])
        self.macros[base.upper()] = Macro(base.upper(), label_var, suffix_var, params, body)

    def find_macro(self, op):
        u = op.upper()
        if u in self.macros and self.macros[u].suffix_var is None:
            return self.macros[u], None
        if '.' in u:
            base, suf = u.split('.', 1)
            m = self.macros.get(base)
            if m and m.suffix_var:
                return m, op.split('.', 1)[1]
        m = self.macros.get(u)
        if m:
            return m, None
        return None, None

    def expand_macro(self, macro, suffix, line):
        scope = ({}, {})
        self.localstack.append(scope)
        at_map = {}
        if macro.label_var:
            scope[0][macro.label_var.lower()] = line.label or ''
            # an @-label passed as the macro's LABEL parameter retains the scope it
            # had at the CALL site (MPW Asm Ref: "@-labels passed as macro
            # parameters retain the scope they had when the macro was called"), so
            # a call-site `@x _Macro` defines @x in the caller, where the caller's
            # own `bcc @x` can reach it — not in the expansion's private scope.
            if (line.label or '').startswith('@'):
                at_map[line.label.upper()] = (self.local_ctx or self.last_global,
                                              self.last_global)
        if macro.suffix_var:
            scope[0][macro.suffix_var.lower()] = suffix or ''
        argvals = _split_commas(line.operand) if line.operand else []
        for k, pname in enumerate(macro.params):
            scope[0][pname.lower()] = argvals[k].strip() if k < len(argvals) else ''
        # give the expansion its own @-local-label scope context
        self.macro_uid += 1
        saved_ctx, saved_lg = self.local_ctx, self.last_global
        self.local_ctx = 'M%d' % self.macro_uid
        self.macro_at.append(at_map)
        try:
            # a macro body has no source file of its own; keep the diagnostic
            # location pinned to the call site rather than the body-line index
            self.run_unit(macro.body, track_lines=False)
        finally:
            self.localstack.pop()
            self.macro_at.pop()
            self.local_ctx, self.last_global = saved_ctx, saved_lg

    # ----------------------------------------------------------------
    # Directive / instruction dispatch (line already &-substituted)
    # ----------------------------------------------------------------
    def dispatch(self, ln):
        op = (ln.op or '')
        u = op.upper()

        if u == '':
            # label-only line defines a label at the current location.
            # A leading '.' marks a macro-time sequence label (GOTO target),
            # not a real symbol.
            if ln.label and not ln.label.startswith('.'):
                self._maybe_global(ln.label)
                self.define_label(ln.label, self.loc)
            return

        # macro variable declarations / assignment
        if u in ('GBLA', 'GBLC', 'GBLB'):
            for nm in _split_commas(ln.operand):
                nm = nm.strip().lstrip('&')
                if nm:
                    self.declare(nm, u[3], local=False)
            return
        if u in ('LCLA', 'LCLC', 'LCLB'):
            for nm in _split_commas(ln.operand):
                nm = nm.strip().lstrip('&')
                if nm:
                    self.declare(nm, u[3], local=True)
            return
        if u == 'SETA':
            self.setvar(ln.label.lstrip('&'), self.evaluate(ln.operand) or 0)
            return
        if u == 'SETB':
            self.setvar(ln.label.lstrip('&'), self.evaluate(ln.operand) or 0)
            return
        if u == 'SETC':
            self.setvar(ln.label.lstrip('&'), _unquote(ln.operand))
            return

        # DCI (Define Constant, Inverted): a string with the high bit set on the
        # LAST byte. Handle as a directive BEFORE macro expansion — the firmware
        # DCI macro reimplements this with &LEN/substring/&CONCAT tricks that
        # depend on quote-retaining macro-string semantics gsasm doesn't share.
        if u == 'DCI':
            self._lbl(ln)
            opd = (ln.operand or '').strip()
            data = b''
            if len(opd) >= 2 and opd[0] in "'\"" and opd[-1] == opd[0]:
                q = opd[0]
                inner = opd[1:-1].replace(q + q, q)   # '' inside '...' = one '
                data = _mac_bytes(inner)              # raw ASCII (DCI body MSB off)
            if data:
                data = data[:-1] + bytes([data[-1] | 0x80])
            self.emit_line(ln, data, [])
            return

        # macro invocation?
        macro, suffix = self.find_macro(op)
        if macro is not None:
            if ln.label and macro.label_var is None:
                self._maybe_global(ln.label)      # ENTRY/EXPORT label on a macro call
                self.define_label(ln.label, self.loc)
            self.expand_macro(macro, suffix, ln)
            return

        # equates (SET is a redefinable equate)
        if u in ('EQU', 'GEQU', '=', 'SET'):
            self.define_label(ln.label, self.evaluate(ln.operand) or 0, kind='equ')
            return

        # state directives
        if u == 'LONGA':
            self.longa = ln.operand.strip().upper() == 'ON'; self._lbl(ln); return
        if u == 'LONGI':
            self.longi = ln.operand.strip().upper() == 'ON'; self._lbl(ln); return
        if u == 'STRING':
            self.string_mode = ln.operand.strip().upper() or 'ASIS'; return
        if u == 'MSB':
            self.msb = ln.operand.strip().upper(); return

        # record (structure) templates: fields are offsets, emit no bytes
        if u == 'RECORD':
            # `Name RECORD <offset>` = a field-offset TEMPLATE (no emission).
            # `Name RECORD` (no operand) = a named DATA SEGMENT that emits its
            # contents (e.g. RomDataMgr ROMDataArea / TranslateTable); its labels
            # are real data labels, KIND = data.
            if ln.operand and ln.operand.strip():
                op = ln.operand.strip()
                dec = False
                if ',' in op:                      # `base,increment|decrement`
                    base_txt, mod = op.split(',', 1)
                    modl = mod.strip().lower()
                    if 'decrement' in modl or 'increment' in modl:
                        dec = 'decrement' in modl
                        op = base_txt.strip()
                self.record_stack.append((self.loc, self.emit_enabled,
                                          self.cur_record, False, self._record_dec))
                self.emit_enabled = False
                base = self.evaluate(op) or 0
                self.loc = base
                self._record_dec = dec             # fields allocate downward
                if ln.label:
                    self.define_label(ln.label, base, kind='equ')
                self.cur_record = ln.label
            else:
                self.record_stack.append((self.loc, self.emit_enabled,
                                          self.cur_record, True, self._record_dec))
                self._record_dec = False
                self.loc = 0                       # new segment starts at 0
                name = (ln.label or '').upper()
                cur = self.segs[-1]
                if cur.name is None and not cur.items:
                    cur.name = name; cur.loadname = 'main'; cur.is_data = True
                    cur.private = True
                else:
                    seg = Segment(name, 'main', None, len(self.segs) + 1)
                    seg.is_data = True; seg.private = True
                    self.segs.append(seg)
                if ln.label:
                    self.define_label(ln.label, self.loc)
            return
        if u == 'ENDR':
            data_rec = self.record_stack[-1][3] if self.record_stack else False
            if ln.label:
                self.define_label(ln.label, self.loc,
                                  kind='label' if data_rec else 'equ')
            if self.record_stack:
                (self.loc, self.emit_enabled, self.cur_record, _,
                 self._record_dec) = self.record_stack.pop()
            if data_rec:
                # finalize: trailing content goes to a fresh segment (next PROC
                # reuses it if still empty/unnamed)
                self.loc = 0
                self.segs.append(Segment(None, 'main', None, len(self.segs) + 1))
            return
        if u == 'WITH':
            # WITH RecA[,RecB] establishes a record field namespace: unqualified
            # field names resolve to RecA.field (innermost WITH wins)
            self._lbl(ln)
            recs = [r.strip().upper() for r in (ln.operand or '').split(',') if r.strip()]
            self.with_stack.append(recs)
            return
        if u == 'ENDWITH':
            self._lbl(ln)
            if self.with_stack:
                self.with_stack.pop()
            return

        # segment / proc
        if u == 'PROC':
            self._proc(ln); return
        if u == 'ENDP':
            self.proc_depth = max(0, self.proc_depth - 1)
            self.in_proc = self.proc_depth > 0
            return
        if u == 'END':
            self.in_proc = False; return
        if u == 'SEG':
            if ln.operand:
                self.pending_loadname = _unquote(ln.operand)
            return
        if u == 'ORG':
            v = self.evaluate(ln.operand)
            if v is not None:
                self.loc = v
            self._lbl(ln)
            return
        if u in ('ENTRY',):
            self._lbl(ln)                         # `label ENTRY` defines the label
            # `ENTRY name[,name]` only DECLARES entries; the labels are defined
            # at their real positions elsewhere (do NOT define them here).
            for tok in _split_commas(ln.operand or ''):
                nm = tok.split(':')[0].strip()
                if nm:
                    self.entries.add(nm.upper())
                    self._note_entry_seg(nm.upper())
            if ln.label:
                self.entries.add(ln.label.upper())
                self._note_entry_seg(ln.label.upper())
            return
        if u == 'EXPORT':
            self._lbl(ln)
            if ln.operand:
                for tok in _split_commas(ln.operand):
                    nm = tok.split(':')[0].strip()
                    if nm:
                        self.exports.add(nm.upper())
                        self._note_entry_seg(nm.upper())
            if ln.label:
                self._note_entry_seg(ln.label.upper())
            return
        if u == 'IMPORT':
            nm = ln.operand.split(':')[0].strip() if ln.operand else ''
            if nm:
                self.imports.add(nm.upper())
            self._lbl(ln); return
        if u == 'ALIGN':
            a = self.evaluate(ln.operand) or 1
            if a > 1 and self.loc % a:
                self.loc += a - (self.loc % a)
            self._lbl(ln); return
        if u == 'ANOP':
            self._lbl(ln); return

        # data
        if u == 'DC' or u.startswith('DC.'):
            self._lbl(ln)
            data, fixups = self._dc_bytes(u, ln.operand)
            self.emit_line(ln, data, fixups); return
        if u == 'DS' or u.startswith('DS.'):
            size = self._ds_size(u, ln.operand)
            if self._record_dec:                   # decrement record: field grows
                self.loc -= size                   # downward; label at the new loc
                self._lbl(ln)
            else:
                self._lbl(ln); self.reserve(size)
            return
        if u in ('DCB',) or u.startswith('DCB.'):
            self._lbl(ln)
            data, fixups = self._dcb_bytes(u, ln.operand)
            # a zero fill is stored as reserved space (DS), not literal bytes
            if data and not any(data):
                self.reserve(len(data))
            else:
                self.emit_line(ln, data, fixups)
            return

        # listing / diagnostics: ignore (define a label if present)
        if u in ('TITLE', 'PRINT', 'LIST', 'PAGE', 'EJECT', 'SPACE', 'NOGEN',
                 'GEN', 'MACHINE', 'WRITELN', 'ERR', 'ERRIF', 'CASE', 'NEEDS',
                 'BLANKS', 'LONGTABLE', 'KEEP', 'NOTE', 'WHILE', 'MEXIT'):
            self._lbl(ln); return

        # instruction?
        if u in m65816.MNEMONICS:
            self._lbl(ln)
            try:
                data, fx = m65816.encode(op, ln.operand, self.longa, self.longi,
                                         self.evaluate, self.loc, self.is_reloc)
            except Exception as e:
                self._err(f"encode error {op} {ln.operand!r}: {e}")
                data, fx = b'\x00', None
            if data is None:
                data = b'\x00'
            self.emit_line(ln, data, [(1, fx)] if fx else [])
            return

        # unknown
        self._lbl(ln)
        self._err(f"unknown op {op!r} operand={ln.operand!r}")

    def _note_entry_seg(self, name):
        """Record the segment in which an ENTRY/EXPORT directive appears. For a
        DUPLICATE entry/export name (defined in multiple segments) the GLOBAL
        record is emitted only in the segment owning the directive; an in-segment
        directive wins over a top-level forward declaration (last-write wins)."""
        if self.emit_enabled and self.segs:
            self.entry_seg[name] = (self.segs[-1].name or '').upper()

    def _maybe_global(self, label):
        """Record an ENTRY/EXPORT code label's position so the OMF emitter can
        place a GLOBAL record there (these may sit on label-only lines). EXPORT
        labels are public (priv 0); ENTRY labels are private (priv 1)."""
        if not (label and self.emit_enabled):
            return
        u = label.upper()
        if u in self.exports:                      # explicit EXPORT -> public
            self.segs[-1].items.append(('global', u, 0))
        elif u in self.entries:                    # ENTRY only -> private
            self.segs[-1].items.append(('global', u, 1))

    def _lbl(self, ln):
        if ln.label:
            self._maybe_global(ln.label)
            # inside a RECORD, labels are field offsets (equate-like), not
            # relocatable code/data labels
            self.define_label(ln.label, self.loc,
                              kind='equ' if not self.emit_enabled else 'label')

    def _proc(self, ln):
        # NOTE: nested-PROC -> shared-segment merging is NOT done here; the exact
        # MPW PROC/ENDP -> OMF segment grouping rule is still TBD (a depth model
        # over-merges because PROC/ENDP are unbalanced in some modules). For now
        # every PROC is its own segment (correct for most modules; over-splits
        # MenuMgr/WindMgr/dialog/fm — see memory).
        self.proc_depth += 1
        self.in_proc = True
        if self.seg_name is None and ln.label:
            self.seg_name = ln.label
        toks = ln.operand.split() if ln.operand else []
        up = [t.upper() for t in toks]
        # Each PROC is a separate OMF segment whose location restarts at 0,
        # unless an explicit ORG gives it an absolute base.
        org = None
        if 'ORG' in up:
            org_expr = ' '.join(toks[up.index('ORG')+1:])
            # Strip trailing `,skip` or `,noskip` modifier (MPW AsmIIgs range-check
            # sentinel; the modifier affects overflow checking only, not the address).
            if ',' in org_expr:
                base_part, mod_part = org_expr.split(',', 1)
                if mod_part.strip().lower() in ('skip', 'noskip'):
                    org_expr = base_part.strip()
            org = self.evaluate(org_expr)
        self.loc = org if org is not None else 0
        name = (ln.label or '').upper()
        loadname = self.pending_loadname or 'main'
        self.pending_loadname = None
        private = 'EXPORT' not in up         # PROC without EXPORT is private
        # `Name PROC EXPORT` publicly exports the segment name (a global symbol at
        # offset 0). Register it so cross-file by-name refs (IMPORT) resolve to it
        # and the linker classifies it as an export, not a plain local. (`PROC` /
        # `PROC ENTRY` stay assembly-private.)
        if not private and name:
            self.exports.add(name)
        cur = self.segs[-1]
        if cur.name is None and not cur.items:
            cur.name = name; cur.loadname = loadname; cur.org = org
            cur.private = private
        else:
            seg = Segment(name, loadname, org, len(self.segs) + 1)
            seg.private = private
            self.segs.append(seg)
        if ln.label:
            self.define_label(ln.label, self.loc)

    # ---- data sizing ----
    def _width(self, u):
        if u.endswith('.W'):
            return 2
        if u.endswith('.L'):
            return 4
        if u.endswith('.A') or u.endswith('.I'):
            return 3
        return 1  # .B or bare

    def _dc_bytes(self, u, operand):
        from .m65816 import Fixup
        w = self._width(u)
        out = bytearray()
        fixups = []
        for item in _split_commas(operand):
            item = item.strip()
            if len(item) >= 2 and item[0] in "'\"" and item[-1] == item[0]:
                # a doubled quote inside the string is an escaped literal quote
                # (`'won''t'` -> won't), per AsmIIgs; collapse it to one.
                q = item[0]
                s = _mac_bytes(item[1:-1].replace(q * 2, q))
                if w == 1:
                    # MSB ON sets the high bit of the CONTENT characters only —
                    # NOT a Pascal length prefix or a C null terminator
                    if self.msb == 'ON':
                        s = bytes(b | 0x80 for b in s)
                    if self.string_mode == 'PASCAL':
                        s = bytes([len(s) & 0xFF]) + s
                    elif self.string_mode in ('C', 'CSTRING'):
                        s = s + b'\x00'
                    out += s
                else:
                    out += b'\x00' * w
            elif item:
                v = self.evaluate(item)
                if v is None:
                    fixups.append((len(out), Fixup(item, w, 'val', self.loc)))
                    out += b'\x00' * w
                else:
                    out += bytes((v >> (8 * i)) & 0xFF for i in range(w))
        return bytes(out), fixups

    def _ds_size(self, u, operand):
        w = self._width(u)
        cnt = self.evaluate(operand)
        return (cnt or 0) * w

    def _dcb_bytes(self, u, operand):
        w = self._width(u)
        parts = _split_commas(operand)
        cnt = self.evaluate(parts[0]) if parts else 0
        val = self.evaluate(parts[1]) if len(parts) > 1 else 0
        cnt = cnt or 0
        val = val or 0
        unit = bytes((val >> (8 * i)) & 0xFF for i in range(w))
        return unit * cnt, []


def _unquote(s):
    s = s.strip()
    if len(s) >= 2 and s[0] in "'\"" and s[-1] == s[0]:
        return s[1:-1]
    return s


def _mac_bytes(s):
    """Encode a string literal to bytes using the Mac Roman code page."""
    try:
        return s.encode('mac_roman')
    except UnicodeEncodeError:
        return s.encode('mac_roman', 'replace')


def _split_commas(s):
    """Split on commas at paren/bracket depth 0, respecting quotes."""
    out = []
    cur = []
    depth = 0
    in_str = False
    quote = ''
    for c in s:
        if in_str:
            cur.append(c)
            if c == quote:
                in_str = False
        elif c in "'\"":
            in_str = True; quote = c; cur.append(c)
        elif c in '([':
            depth += 1; cur.append(c)
        elif c in ')]':
            depth -= 1; cur.append(c)
        elif c == ',' and depth == 0:
            out.append(''.join(cur)); cur = []
        else:
            cur.append(c)
    out.append(''.join(cur))
    return out


def _split_kw(s, kw):
    """Split on a whole-word keyword (AND/OR), case-insensitive, at paren/quote
    depth 0."""
    out = []
    cur = []
    depth = 0
    in_str = False
    quote = ''
    i = 0
    n = len(s)
    kl = len(kw)
    while i < n:
        c = s[i]
        if in_str:
            cur.append(c)
            if c == quote:
                in_str = False
            i += 1
            continue
        if c in "'\"":
            in_str = True; quote = c; cur.append(c); i += 1; continue
        if c == '(':                 # only parens group; [ ] are literal values
            depth += 1
        elif c == ')':
            depth -= 1
        if (depth == 0 and s[i:i+kl].upper() == kw
                and (i == 0 or s[i-1] in ' \t')
                and (i+kl >= n or s[i+kl] in ' \t')):
            out.append(''.join(cur)); cur = []; i += kl; continue
        cur.append(c); i += 1
    out.append(''.join(cur))
    return out


def _find_op(s, opref):
    """Find opref at top level (not in quotes/parens), avoiding <= >= overlap."""
    depth = 0
    in_str = False
    quote = ''
    i = 0
    while i < len(s):
        c = s[i]
        if in_str:
            if c == quote:
                in_str = False
        elif c in "'\"":
            in_str = True; quote = c
        elif c == '(':               # only parens group; [ ] are literal values
            depth += 1
        elif c == ')':
            depth -= 1
        elif depth == 0 and s[i:i+len(opref)] == opref:
            # for single '<'/'>' / '=' don't match a 2-char operator
            if opref in ('<', '>') and s[i:i+2] in ('<>', '<=', '>='):
                i += 1; continue
            if opref == '=' and s[i-1:i] in ('<', '>'):
                i += 1; continue
            return i
        i += 1
    return None


def _compare(asm, lhs, rhs, op):
    # If either operand is a quoted literal, this is a string comparison
    # (so a bare '*' on the other side is the literal text, not the PC).
    lq = lhs.strip()[:1] in "'\""
    rq = rhs.strip()[:1] in "'\""
    if lq or rq:
        a, b = _unquote(lhs), _unquote(rhs)
    else:
        lv = asm.evaluate(lhs)
        rv = asm.evaluate(rhs)
        if lv is not None and rv is not None:
            a, b = lv, rv
        elif lv is not None or rv is not None:
            # one side is numeric, the other an undefined symbol: MPW defaults an
            # undefined symbol to 0 in a numeric condition (e.g. IF RAMVersion=0)
            a = lv if lv is not None else 0
            b = rv if rv is not None else 0
        else:
            a, b = _unquote(lhs), _unquote(rhs)
    if op == '=':
        return a == b
    if op == '<>':
        return a != b
    if op == '<':
        return a < b
    if op == '>':
        return a > b
    if op == '<=':
        return a <= b
    if op == '>=':
        return a >= b
    return False


def _find_ci(base, relpath):
    """Case-insensitive path resolution under base (HFS was case-insensitive)."""
    parts = [p for p in relpath.replace('\\', '/').split('/') if p not in ('', '.')]
    cur = base
    for part in parts:
        if not os.path.isdir(cur):
            return None
        match = None
        try:
            entries = os.listdir(cur)
        except OSError:
            return None
        for e in entries:
            if e.lower() == part.lower():
                match = e; break
        if match is None:
            return None
        cur = os.path.join(cur, match)
    return cur if os.path.isfile(cur) else None


def _run_once(path, include_paths, seed, seed_type, seg_seed=None, defines=None,
              at_seed=None, at_seg_seed=None, sysdate=None, systime=None):
    asm = Asm(include_paths, seed=seed, seed_type=seed_type, seg_seed=seg_seed,
              sysdate=sysdate, systime=systime)
    # the prior pass's COMPLETE @-label positions must be available DURING this
    # pass (a forward @-ref is resolved while assembling, before its definition)
    asm.at_seed = at_seed or {}
    asm.at_seg_seed = at_seg_seed or {}
    src_dir = os.path.dirname(os.path.abspath(path))
    if src_dir not in asm.include_paths:
        asm.include_paths = [src_dir] + asm.include_paths
    # command-line `-d NAME=VALUE` defines (asmiigs), as absolute equates
    for nm, val in (defines or {}).items():
        u = nm.upper()
        asm.symbols[u] = val
        asm.symtype[u] = 'equ'
    asm.run_unit(read_text(path).split('\n'), src_dir, filepath=path)
    asm.apply_fixups()
    return asm


def assemble(path, include_paths, passes=2, defines=None, sysdate=None,
             systime=None):
    """Multi-pass assembly: later passes seed symbol values AND kinds from
    earlier ones so forward references size correctly. Symbol kinds make this
    safe: only equates drive direct-page sizing; relocatable labels stay
    absolute regardless of their (link-relative) value.
    `defines` supplies asmiigs `-d NAME=VALUE` command-line equates.
    `sysdate`/`systime` override the &sysdate/&systime builtins (used by
    source that embeds the original build date for byte-exact reproduction)."""
    a = _run_once(path, include_paths, seed=None, seed_type=None, defines=defines,
                  sysdate=sysdate, systime=systime)
    for _ in range(passes - 1):
        prev = a
        a = _run_once(path, include_paths, seed=prev.symbols, seed_type=prev.symtype,
                      seg_seed=prev.seg_local, defines=defines,
                      at_seed=prev.at_defs, at_seg_seed=prev.at_seg,
                      sysdate=sysdate, systime=systime)
    return a


if __name__ == '__main__':
    import sys
    src = sys.argv[1]
    incs = sys.argv[2:]
    a = assemble(src, incs)
    for name, val in a.labels:
        print(f"{val & 0xFFFFFF:06X}  {name}")
    print(f"--- {len(a.errors)} errors ---", file=sys.stderr)
    for e in a.errors[:40]:
        print("  " + e, file=sys.stderr)
