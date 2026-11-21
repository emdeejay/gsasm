"""gsmake — run the original MPW IIgs makefiles with the gsasm toolchain.

The System 6.0.1 source tree carries ~200 MPW ``make`` files (MacRoman, CR
line endings, ``ƒ`` as the dependency operator, ``∂`` as line
continuation/escape).  gsmake parses that dialect and executes the recipe
commands against gsasm in-process, so the ORIGINAL makefile drives the
build:

    gsmake -C ref/.../GSToolbox/PrinterDrivers/LW -I work/includes

Dialect covered:

    target... ƒ dep...          rules (multiple targets share the recipe);
                                recipe lines are the indented lines after;
                                ``ƒƒ`` marks an always-rebuild rule
    .obj ƒ .aii                 MPW default (suffix) rules: a target
                                ``X.obj`` with no explicit rule builds from
                                ``X.aii`` with ``{Default}`` = ``X``
    NAME = value                variable assignment; ``{NAME}`` expands,
                                case-insensitively, like MPW's
    ∂ at end of line            continuation; mid-line ∂X escapes X
    # comment                   to end of line (outside quotes)
    :Mac:paths                  converted (``:`` separator, leading ``:``
                                relative, ``::`` parent); files resolve
                                case-insensitively, like ProDOS/HFS
    If / Else / End             MPW shell conditionals in recipes; the
                                expression forms the tree uses ({var}
                                truthiness, ==, !=) are evaluated, with an
                                undefined {var} reading as empty
    > file, >> file             output redirection (honored by Echo and
                                Catenate; listing/map redirects on other
                                commands are dropped)

Recipe commands:

    asmiigs     gsasm.asm.assemble + omf.emit; flags -o, -i DIR,
                -d/-define N=V honored, several SRC [-o OUT] units per
                line; listing/warning flags ignored.  Each Asm object is
                CACHED with the written .obj, so a later linkiigs line
                gets full symbol metadata even though the makefile names
                .obj files (required for -lseg:Dynamic).
    linkiigs    gsasm.linkcli (the MPW-syntax gslink mode) with that
                object cache; ``-lib`` links through linkiigs.link_lib.
    reziigs     gsasm's gsrez CLI (--read-dir defaults to the build dir).
    makebiniigs gsasm.makebin (OMF load file -> flat binary image).
    catenate    concatenates files into the redirect target.
    echo, directory, duplicate/duplicateiigs, delete, set/unset, export
                interpreted; setfile and other MPW shell commands are
                reported and skipped.

A ``-t``/``-at`` on a link line also writes gsasm's ``<out>.filetype``
sidecar (see gsasm.makebin.stamp) so a disk-image packager can apply the
ProDOS metadata gsmake cannot.  Rebuilds are mtime-based like make
(``--always`` forces).
"""
from __future__ import annotations

import os
import sys

DEP_CHAR = 'ƒ'      # ƒ  (MacRoman 0xC4)
CONT_CHAR = '∂'     # ∂  (MacRoman 0xB6)
GE_CHAR = '≥'       # ≥  (MacRoman 0xB3; MPW's "stderr" redirect)


class MakeError(SystemExit):
    def __init__(self, msg: str):
        super().__init__(f"gsmake: error: {msg}")


# ---------------------------------------------------------------------------
# Text / path helpers
# ---------------------------------------------------------------------------

def read_makefile(path: str) -> str:
    with open(path, 'rb') as fh:
        data = fh.read()
    try:
        text = data.decode('utf-8')
    except UnicodeDecodeError:
        text = data.decode('mac_roman')
    return text.replace('\r\n', '\n').replace('\r', '\n')


def strip_comment(line: str) -> str:
    """Cut an unquoted ``#`` comment; honor ∂-escapes and both quote kinds."""
    return _strip_comment_ex(line)[0]


def _strip_comment_ex(line: str) -> tuple[str, bool]:
    """(content before any unquoted ``#``, continuation-in-comment flag).

    The flag is True when a trailing comment itself ends with ``∂`` — the
    tree writes ``-x # no need for this ∂`` inside multi-line link rules,
    where the comment runs to end of PHYSICAL line but the continuation
    must survive it."""
    out = []
    quote = None
    i = 0
    while i < len(line):
        c = line[i]
        if c == CONT_CHAR and i + 1 < len(line):
            out.append(c); out.append(line[i + 1]); i += 2
            continue
        if quote:
            if c == quote:
                quote = None
            out.append(c); i += 1
            continue
        if c in ('"', "'"):
            quote = c
            out.append(c); i += 1
            continue
        if c == '#':
            return ''.join(out), line.rstrip().endswith(CONT_CHAR)
        out.append(c); i += 1
    return ''.join(out), False


def logical_lines(text: str) -> list[str]:
    """Comment-strip, then join ∂-continued lines.  A ``∂`` at the end of a
    stripped trailing comment still continues, and a comment-only line whose
    comment ends with ``∂`` is transparent inside a continuation chain."""
    out: list[str] = []
    pending = ''
    in_chain = False
    for raw in text.split('\n'):
        line, cont_in_comment = _strip_comment_ex(raw)
        s = line.rstrip()
        if s.endswith(CONT_CHAR):
            pending += s[:-1] + ' '
            in_chain = True
            continue
        if cont_in_comment and (in_chain or s.strip()):
            # '#...∂': content (if any) joins; the chain continues.  A
            # comment-only line like this OUTSIDE a chain is just a comment.
            pending += s + ' '
            in_chain = True
            continue
        if in_chain and not s.strip():
            # Comment-only/blank line mid-chain without its own ∂ ends it.
            out.append(pending.rstrip())
            pending = ''
            in_chain = False
            continue
        out.append(pending + line)
        pending = ''
        in_chain = False
    if pending:
        out.append(pending.rstrip())
    return out


def split_tokens(line: str) -> list[str]:
    """MPW-ish tokenizer: whitespace-separated, quote-aware, ∂ escapes."""
    toks: list[str] = []
    cur = ''
    started = False
    quote = None
    i = 0
    while i < len(line):
        c = line[i]
        if c == CONT_CHAR and i + 1 < len(line):
            cur += line[i + 1]; started = True; i += 2
            continue
        if quote:
            if c == quote:
                quote = None
            else:
                cur += c
            i += 1
            continue
        if c in ('"', "'"):
            quote = c; started = True; i += 1
            continue
        if c.isspace():
            if started:
                toks.append(cur)
            cur = ''; started = False; i += 1
            continue
        cur += c; started = True; i += 1
    if started:
        toks.append(cur)
    return toks


def mac_to_posix(p: str) -> str:
    """Convert an MPW ``:``-separated path to a POSIX relative path.
    Paths already containing ``/`` (or with no ``:``) pass through."""
    if '/' in p or ':' not in p:
        return p
    if not p.startswith(':'):
        raise MakeError(f"absolute Mac path {p!r} is not supported — "
                        "it names an MPW shell volume; define the variable "
                        "that held it instead")
    fields = p.split(':')[1:]         # drop the leading empty field
    if fields and fields[-1] == '':
        fields.pop()                  # trailing ':' is only a dir marker
    # Each remaining empty field came from a '::' pair: up one level.
    return '/'.join('..' if f == '' else f for f in fields) or '.'


def ci_resolve(path: str, cwd: str) -> str | None:
    """Case-insensitive resolution of *path* (relative to *cwd*), one
    component at a time — ProDOS/HFS filenames are case-preserving but
    case-insensitive, and the makefiles rely on it (``Lw.asm`` names
    ``lw.asm``)."""
    base = cwd if not os.path.isabs(path) else '/'
    cur = base
    for comp in path.split('/'):
        if comp in ('', '.'):
            continue
        if comp == '..':
            cur = os.path.dirname(cur) or '/'
            continue
        cand = os.path.join(cur, comp)
        if os.path.exists(cand):
            cur = cand
            continue
        if not os.path.isdir(cur):
            return None
        lc = comp.lower()
        match = next((e for e in sorted(os.listdir(cur))
                      if e.lower() == lc), None)
        if match is None:
            return None
        cur = os.path.join(cur, match)
    return cur


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

class Rule:
    __slots__ = ('targets', 'deps', 'recipe', 'always', 'stem')

    def __init__(self, targets, deps, always=False):
        self.targets = targets
        self.deps = deps
        self.recipe: list[str] = []
        self.always = always
        self.stem = None            # {Default} value on a synthesized rule

    @property
    def is_suffix(self) -> bool:
        """An MPW default rule: ``.obj ƒ .aii`` (or ``.aii.obj ƒ .aii``) —
        every target and dep is a bare extension."""
        exts = self.targets + self.deps
        return bool(exts) and all(
            t.startswith('.') and len(t) > 1 and '/' not in t
            and ':' not in t and '{' not in t for t in exts)


# APW/MPW-convention default rules, used only when the makefile itself has
# no rule (its own suffix rules are tried first): assemble X.<src> into the
# exact object name asked for.
_BUILTIN_SUFFIX = [('.aii.obj', '.aii'), ('.asm.obj', '.asm'),
                   ('.oii', '.aii'), ('.obj', '.aii'), ('.obj', '.asm')]


import re as _re
_ASSIGN_RE = _re.compile(r'^([A-Za-z_][\w.]*)\s*=(.*)$')


def parse_makefile(text: str) -> tuple[list[Rule], dict[str, str]]:
    rules: list[Rule] = []
    assigns: dict[str, str] = {}
    cur: Rule | None = None
    for line in logical_lines(text):
        if not line.strip():
            continue
        if line[0] in (' ', '\t'):
            if cur is None:
                raise MakeError(
                    f"recipe line outside any rule: {line.strip()!r}")
            cur.recipe.append(line.strip())
            continue
        if DEP_CHAR in line:
            tpart, _, dpart = line.partition(DEP_CHAR)
            always = dpart.startswith(DEP_CHAR)
            if always:
                dpart = dpart[1:]
            cur = Rule(split_tokens(tpart), split_tokens(dpart), always)
            if not cur.targets:
                raise MakeError(f"rule with no target: {line.strip()!r}")
            rules.append(cur)
            continue
        m = _ASSIGN_RE.match(line)
        if m:
            assigns[m.group(1).lower()] = m.group(2).strip()
            cur = None
            continue
        raise MakeError(f"cannot parse makefile line: {line.strip()!r}")
    return rules, assigns


def expand(s: str, variables: dict[str, str], *, soft: bool = False,
           missing: set | None = None) -> str:
    out = s
    for _ in range(10):
        if '{' not in out:
            return out
        prev = out
        res = []
        i = 0
        while i < len(out):
            c = out[i]
            if c == '{':
                end = out.find('}', i)
                if end < 0:
                    raise MakeError(f"unterminated {{var}} in {s!r}")
                name = out[i + 1:end]
                key = name.lower()
                if key in variables:
                    res.append(variables[key])
                elif soft:
                    # MPW: an unset shell variable expands empty.
                    if missing is not None:
                        missing.add(name)
                else:
                    raise MakeError(
                        f"undefined makefile variable {{{name}}} — define "
                        f"it with -D {name}=value (MPW builds set it in "
                        "the shell)")
                i = end + 1
                continue
            res.append(c); i += 1
        out = ''.join(res)
        if out == prev:
            return out
    return out


# ---------------------------------------------------------------------------
# MPW shell conditional expressions (the forms the 6.0.1 tree uses)
# ---------------------------------------------------------------------------

def _cond_value(tok: str):
    t = tok.strip().strip('"').strip("'")
    try:
        return int(t[1:], 16) if t.startswith('$') else int(t, 0)
    except ValueError:
        return t.lower()


def eval_condition(expr: str) -> bool:
    """Evaluate an (already soft-expanded) MPW If expression.  Covers what
    the tree actually writes: a bare value (number/word truthiness, empty =
    false) and binary ``==`` / ``!=`` comparisons."""
    s = expr.strip()
    for op in ('==', '!='):
        if op in s:
            l, _, r = s.partition(op)
            eq = _cond_value(l) == _cond_value(r)
            return eq if op == '==' else not eq
    if not s:
        return False
    v = _cond_value(s)
    return bool(v) if isinstance(v, int) else True


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

_ASM_IGNORE0 = {'-unsafe', '-wi', '-w', '-wt', '-l', '-m', '-t', '-f', '-h'}
_ASM_IGNORE1 = {'-lo', '-font', '-print', '-pagesize'}
_SKIP_CMDS = {'setfile', 'rename', 'move', 'newfolder', 'files', 'date',
              'beep', 'open', 'close', 'save', 'alert', 'confirm', 'eject',
              'backup', 'help', 'flush', 'eval', 'execute', 'begin',
              'quote', 'mark', 'print', 'search'}


class Maker:
    def __init__(self, makefile: str, *, includes=None, defines=None,
                 always=False, verbose=True, strict_vars=False):
        self.makefile = os.path.abspath(makefile)
        self.cwd = os.path.dirname(self.makefile)
        text = read_makefile(self.makefile)
        self.rules, assigns = parse_makefile(text)
        self.variables: dict[str, str] = dict(assigns)
        self.includes = [os.path.abspath(d) for d in (includes or [])]
        self.defines = dict(defines or {})
        for k, v in self.defines.items():
            self.variables[k.lower()] = v
        self.always = always
        self.verbose = verbose
        self.strict_vars = strict_vars
        self.missing_vars: set[str] = set()
        self.objcache: dict[str, tuple[bytes, object]] = {}
        self.built: set[str] = set()
        self._generated_scripts: set[str] = set()

    def _expand(self, s: str, variables: dict | None = None) -> str:
        """Expand with the MPW shell's semantics: an unset variable reads
        as empty (collected in ``missing_vars`` and reported), unless
        ``strict_vars`` asks for the hard error."""
        return expand(s, variables if variables is not None
                      else self.variables,
                      soft=not self.strict_vars, missing=self.missing_vars)

    # -- helpers ----------------------------------------------------------
    def _say(self, msg: str):
        if self.verbose:
            print(msg)

    def _mac(self, name: str) -> str:
        """Makefile path token -> POSIX.  Strips MPW quoting, converts
        ``:`` paths, and maps an MPW VOLUME path (``Slinky:Slinky.aii``) to
        a directory of that name found beside or above the build dir —
        the GS.OS MakeFiles mount each component as its own volume."""
        t = name.strip().strip('"').strip("'")
        if '/' in t or ':' not in t:
            return t
        if t.startswith(':'):
            return mac_to_posix(t)
        vol, _, rest = t.partition(':')
        restp = mac_to_posix(':' + rest) if rest else '.'
        base = self.cwd
        for _ in range(6):
            if os.path.basename(base).lower() == vol.lower():
                return os.path.join(base, restp)
            hit = ci_resolve(vol, base)
            if hit and os.path.isdir(hit):
                return os.path.join(hit, restp)
            up = os.path.dirname(base)
            if up == base:
                break
            base = up
        raise MakeError(
            f"MPW volume {vol!r} (path {name!r}) not found beside or above "
            f"{self.cwd} — check the tree layout or use -D to repoint it")

    def _mac_soft(self, name: str) -> str:
        try:
            return self._mac(name)
        except SystemExit:
            return name

    def _norm_key(self, target: str) -> str:
        return os.path.normpath(self._mac_soft(target)).lower()

    def _path(self, name: str) -> str:
        """Expanded, Mac-converted path relative to the build dir."""
        p = self._mac(name)
        return p if os.path.isabs(p) else os.path.join(self.cwd, p)

    def _find_rule(self, target: str) -> Rule | None:
        tl = target.lower()
        # Path-normalized comparison: ':obj:x.obj' names the same thing as
        # 'x.obj' written with an unset {ObjDir} — MPW matched these through
        # the shell's directory context.
        tn = os.path.normpath(self._mac_soft(target)).lower()
        tb = os.path.basename(tn)
        base_hit = None
        for r in self.rules:
            if r.is_suffix:
                continue
            for t in r.targets:
                x = self._expand(t).lower()
                if x == tl:
                    return r
                xn = os.path.normpath(self._mac_soft(x)) if ':' in x or '/' in x else x
                if xn == tn:
                    return r
                if base_hit is None and os.path.basename(xn) == tb:
                    base_hit = r
        return base_hit

    def _suffix_rule(self, target: str) -> Rule | None:
        """Synthesize a concrete rule for *target* from an MPW default rule
        (``.obj ƒ .aii``): the source with the dep's extension must exist (or
        itself have a rule); ``{Default}`` is the stem."""
        for r in self.rules:
            if not r.is_suffix:
                continue
            for text in r.targets:
                if not target.lower().endswith(text.lower()):
                    continue
                stem = target[:-len(text)]
                for dext in r.deps:
                    dep = stem + dext
                    if (self._find_rule(dep) is not None
                            or ci_resolve(self._mac(dep), self.cwd)):
                        c = Rule([target], [dep], r.always)
                        c.recipe = list(r.recipe)
                        c.stem = stem
                        self._say(f"gsmake: {target!r} via default rule "
                                  f"{text} {DEP_CHAR} {dext} "
                                  f"(Default={stem!r})")
                        return c
        # APW convention fallback: the tree leans on rules its shell
        # environment provided (CtlPanel.aii.obj with no rule in sight).
        for text, dext in _BUILTIN_SUFFIX:
            if not target.lower().endswith(text):
                continue
            stem = target[:-len(text)]
            dep = stem + dext
            if ci_resolve(self._mac(dep), self.cwd):
                c = Rule([target], [dep])
                c.recipe = [f"asmiigs '{dep}' -o '{target}'"]
                c.stem = stem
                self._say(f"gsmake: {target!r} via built-in default rule "
                          f"{text} {DEP_CHAR} {dext}")
                return c
        return None

    def default_target(self) -> str:
        for r in self.rules:
            if not r.is_suffix:
                return self._expand(r.targets[0])
        raise MakeError("makefile has no non-suffix rules")

    # -- build ------------------------------------------------------------
    def build(self, target: str, _stack=()):
        target = self._expand(target)
        key = self._norm_key(target)
        if key in self.built:
            return
        if key in _stack:
            raise MakeError(f"circular dependency on {target!r}")
        rule = self._find_rule(target) or self._suffix_rule(target)
        if rule is None:
            p = ci_resolve(self._mac(target), self.cwd)
            if p is None:
                if self._build_in_sibling(target):
                    self.built.add(key)
                    return
                raise MakeError(f"no rule to make {target!r} and no such file")
            return                      # a plain source file
        # A dependency written as one {VAR} may expand to a whole file
        # LIST (CloseView's {INIT_CODE}) — re-tokenize after expansion.
        deps = [t for d in rule.deps for t in split_tokens(self._expand(d))]
        for d in deps:
            if self._norm_key(d) == key:
                # MPW idiom: a rule may list its own target (or the folder
                # of the same name) among the deps — a no-op, not a cycle.
                continue
            self.build(d, _stack + (key,))
        self.built.add(key)
        if not rule.recipe:
            return
        if (not self.always and not rule.always
                and self._up_to_date(target, deps)):
            self._say(f"gsmake: {target!r} is up to date")
            return
        self.run_recipe(rule.recipe,
                        default=self._default_stem(rule, target),
                        targ=target, deps=deps)

    def _default_stem(self, rule: Rule, target: str) -> str | None:
        """{Default} value: target minus the suffix-rule extension — only
        rules synthesized by _suffix_rule qualify (their single target IS
        the concrete file)."""
        if rule.stem is not None:
            return rule.stem
        if len(rule.targets) == 1 and rule.targets[0] == target \
                and len(rule.deps) == 1:
            dep = rule.deps[0]
            # Concrete pair like X.obj <- X.aii sharing a stem.
            t_stem, _, _ = target.rpartition('.')
            d_stem, _, _ = dep.rpartition('.')
            if t_stem and t_stem.lower() == d_stem.lower():
                return t_stem
        return None

    def _build_in_sibling(self, target: str, _depth: int = 0) -> bool:
        """A target living in ANOTHER directory ('::qd:qdalone:strip.asm.obj')
        is that directory's makefile's business — the original build ran the
        tree's makefiles from master scripts.  Run a sub-make there for the
        file's basename, sharing this run's object cache.  True on success."""
        if _depth > 4:
            return False
        rel = self._mac_soft(target)
        if '/' not in rel:
            return False
        tdir = os.path.normpath(os.path.join(self.cwd, os.path.dirname(rel)))
        want = os.path.basename(rel)
        # The obj may be filed under the sibling's :obj:/:objs: dir — the
        # sibling MAKEFILE lives at the component root above it.
        probe = tdir
        mf = None
        for _ in range(3):
            mf = ci_resolve('makefile', probe) if os.path.isdir(probe) else None
            if mf and os.path.isfile(mf):
                break
            mf = None
            probe = os.path.dirname(probe)
        if mf is None:
            return False
        self._say(f"gsmake: {target!r}: sub-make in "
                  f"{os.path.relpath(os.path.dirname(mf), self.cwd)}")
        sub = Maker(mf, includes=self.includes, defines=self.defines,
                    always=False, verbose=self.verbose,
                    strict_vars=self.strict_vars)
        sub.objcache = self.objcache          # shared: links see the Asms
        sub._generated_scripts = self._generated_scripts
        try:
            sub.build(want)
        except SystemExit:
            return False
        finally:
            self.missing_vars |= sub.missing_vars
        return ci_resolve(rel, self.cwd) is not None

    @staticmethod
    def _ensure_parent(path: str):
        d = os.path.dirname(path)
        if d and not os.path.isdir(d):
            os.makedirs(d, exist_ok=True)

    def _up_to_date(self, target: str, deps: list[str]) -> bool:
        tp = ci_resolve(self._mac(target), self.cwd)
        if tp is None or not os.path.isfile(tp):
            return False
        tm = os.path.getmtime(tp)
        for d in deps:
            dp = ci_resolve(self._mac(d), self.cwd)
            if dp is None or os.path.getmtime(dp) > tm:
                return False
        return True

    # -- recipe running (with conditionals) -------------------------------
    def run_recipe(self, recipe: list[str], default: str | None = None,
                   targ: str | None = None, deps: list[str] | None = None):
        # MPW make's built-in rule variables, layered over the shell vars:
        # {Default} (suffix-rule stem), {Targ}, {Deps} / {NewerDeps}.
        variables = dict(self.variables)
        if default is not None:
            variables['default'] = default
        if targ is not None:
            variables['targ'] = targ
        if deps is not None:
            variables['deps'] = ' '.join(deps)
            variables['newerdeps'] = ' '.join(deps)
        i = 0
        while i < len(recipe):
            line = recipe[i]
            first = (line.split() or [''])[0].lower()
            if first == 'if':
                cond = eval_condition(
                    expand(line.split(None, 1)[1] if ' ' in line else '',
                           variables, soft=True, missing=self.missing_vars))
                if cond:
                    i += 1
                    continue
                i = self._skip_block(recipe, i, stop_at_else=True)
                continue
            if first == 'else':
                # We executed the If arm; skip to End.
                i = self._skip_block(recipe, i, stop_at_else=False)
                continue
            if first == 'end':
                i += 1
                continue
            self.run_line(self._expand(line, variables), variables)
            i += 1

    @staticmethod
    def _skip_block(recipe: list[str], i: int, *, stop_at_else: bool) -> int:
        """Index just past the matching End (or at the Else arm's first line
        when *stop_at_else* and a same-level Else is found)."""
        depth = 0
        i += 1
        while i < len(recipe):
            first = (recipe[i].split() or [''])[0].lower()
            if first == 'if':
                depth += 1
            elif first == 'end':
                if depth == 0:
                    return i + 1
                depth -= 1
            elif first == 'else' and depth == 0 and stop_at_else:
                return i + 1
            i += 1
        return i

    # -- recipe commands --------------------------------------------------
    def run_line(self, line: str, variables: dict | None = None):
        toks = split_tokens(line)
        # Pull out shell redirects: ">file" / ">>file" (and MPW's ≥ forms,
        # which redirect diagnostics — dropped), attached or detached.
        clean: list[str] = []
        redirect: tuple[str, str] | None = None     # (mode, path)
        i = 0
        while i < len(toks):
            t = toks[i]
            if t in ('>', '>>'):
                i += 1
                if i < len(toks):
                    redirect = ('a' if t == '>>' else 'w', toks[i])
                i += 1
                continue
            if t.startswith('>>'):
                redirect = ('a', t[2:]); i += 1
                continue
            if t.startswith('>'):
                redirect = ('w', t[1:]); i += 1
                continue
            if t.startswith(GE_CHAR):
                if t in (GE_CHAR, GE_CHAR * 2):
                    i += 1                      # skip its filename too
                i += 1
                continue
            clean.append(t); i += 1
        if not clean:
            return
        cmd, args = clean[0].lower(), clean[1:]
        if cmd == 'asmiigs':
            return self._cmd_asmiigs(args)
        if cmd in ('linkiigs', 'link'):
            return self._cmd_linkiigs(args)
        if cmd in ('reziigs', 'rez'):
            return self._cmd_reziigs(args)
        if cmd == 'makebiniigs':
            return self._cmd_makebin(args)
        if cmd == 'overlayiigs':
            return self._cmd_overlay(args)
        if cmd == 'makelibiigs':
            return self._cmd_makelib(args)
        if cmd == 'make':
            # MPW make EMITS build commands; the tree's idiom is
            # ``MAKE target > cmds`` then running the cmds file.  gsmake
            # builds the target directly and stubs the script out.
            targets = [a for a in args if not a.startswith('-')]
            for t in targets:
                self.build(t)
            if redirect:
                p = self._path(redirect[1])
                with open(p, 'w') as fh:
                    fh.write('# built directly by gsmake\n')
                self._generated_scripts.add(os.path.abspath(p).lower())
            return
        if cmd == 'catenate':
            return self._cmd_catenate(args, redirect)
        if cmd == 'echo':
            text = ' '.join(args)
            if redirect:
                outp = self._path(redirect[1])
                self._ensure_parent(outp)
                with open(outp, redirect[0]) as fh:
                    fh.write(text + '\n')
            else:
                print(text)
            return
        if cmd == 'directory':
            if args:
                p = self._path(args[0])
                if not os.path.isdir(p):
                    raise MakeError(f"Directory {args[0]!r}: no such dir")
                self.cwd = p
            else:
                print(self.cwd)
            return
        if cmd in ('duplicate', 'duplicateiigs', 'dup'):
            return self._cmd_duplicate(args)
        if cmd == 'delete':
            for a in args:
                if a.startswith('-'):
                    continue
                p = ci_resolve(self._mac(a), self.cwd)
                if p and os.path.isfile(p):
                    os.remove(p)
            return
        if cmd == 'set':
            if len(args) >= 2:
                (variables if variables is not None
                 else self.variables)[args[0].lower()] = args[1]
                self.variables[args[0].lower()] = args[1]
            return
        if cmd == 'unset':
            for a in args:
                self.variables.pop(a.lower(), None)
            return
        if cmd in ('export', 'unexport'):
            return                      # variables are already global here
        if cmd in _SKIP_CMDS:
            self._say(f"gsmake: skipping MPW shell command: {line}")
            return
        # Running a command file that a MAKE line above generated (and
        # gsmake stubbed): nothing left to do.
        p = ci_resolve(self._mac(clean[0]), self.cwd)
        if p and os.path.abspath(p).lower() in self._generated_scripts:
            self._say(f"gsmake: skipping generated command file {clean[0]}")
            return
        raise MakeError(f"unknown recipe command {clean[0]!r} in: {line}")

    def _cmd_asmiigs(self, args: list[str]):
        units: list[tuple[str, str | None]] = []    # (src, out)
        pending_out: str | None = None
        incs: list[str] = []
        defines: dict[str, int] = {}
        it = iter(args)
        for t in it:
            tl = t.lower()
            if tl == '-o':
                out = next(it, None)
                if units and units[-1][1] is None:
                    units[-1] = (units[-1][0], out)
                else:
                    pending_out = out
            elif tl == '-i':
                for d in (next(it, '') or '').split(','):
                    if d:
                        incs.append(self._path(d))
            elif tl in ('-d', '-define'):
                kv = next(it, '')
                name, _, val = kv.partition('=')
                try:
                    defines[name] = int(val, 0) if val else 1
                except ValueError:
                    defines[name] = 1
            elif tl in _ASM_IGNORE1:
                next(it, None)
            elif tl in _ASM_IGNORE0:
                pass
            elif t.startswith('-'):
                raise MakeError(f"asmiigs flag {t!r} not understood")
            else:
                units.append((t, pending_out))
                pending_out = None
        if not units:
            raise MakeError("asmiigs: no source file")
        from gsasm import asm as _asm, omf as _omf
        for spelled, out in units:
            src = ci_resolve(self._mac(spelled), self.cwd)
            if src is None or os.path.isdir(src):
                raise MakeError(f"asmiigs: source not found: {spelled!r}")
            outp = self._path(out) if out else src + '.obj'
            if os.path.isdir(outp):
                # MPW `-o :obj:` names a DIRECTORY: default name inside it.
                outp = os.path.join(outp, os.path.basename(src) + '.obj')
            self._say(f"gsmake: asmiigs {os.path.basename(src)} "
                      f"-> {os.path.basename(outp)}")
            all_defs = dict(self.defines, **defines) \
                if defines or self.defines else None
            incpaths = ([os.path.dirname(src)] + incs + self.includes
                        + [self.cwd])
            try:
                a = _asm.assemble(src, incpaths, defines=all_defs)
            except MakeError:
                raise
            except Exception as e:
                # Surface assembler-internal failures (a dialect corner the
                # corpus never exercised, a missing include...) as a build
                # error naming the source, not a traceback.
                raise MakeError(
                    f"asmiigs {spelled}: {type(e).__name__}: {e}")
            if a.errors:
                raise MakeError(f"asmiigs {spelled}:\n" + "\n".join(a.errors))
            ob = _omf.emit(a)
            self._ensure_parent(outp)
            with open(outp, 'wb') as fh:
                fh.write(ob)
            self.objcache[os.path.abspath(outp).lower()] = (ob, a)

    def _cmd_linkiigs(self, args: list[str]):
        from gsasm import linkcli
        argv: list[str] = []
        inputs: list[tuple[str, str]] = []      # (makefile spelling, path)
        any_dynamic = False
        it = iter(args)
        for t in it:
            tl = t.lower()
            if tl.startswith('-lseg'):
                any_dynamic = any_dynamic or 'dynamic' in tl
                argv += [t, next(it, '')]
            elif tl == '-lib':
                lib = next(it, '')
                p = ci_resolve(self._mac(lib), self.cwd)
                if p is None:
                    raise MakeError(f"linkiigs: library not found: {lib!r}")
                argv += ['-lib', p]
            elif tl in ('-o', '-t', '-at', '-org'):
                argv += [tl, next(it, '')]
            elif tl == '-x':
                argv.append('-x')
            elif tl in ('-l', '-s', '-c', '-a', '-sym', '-mf', '-lo',
                        '-apw') or tl.startswith('-w'):
                pass
            elif t.startswith('-'):
                raise MakeError(f"linkiigs flag {t!r} not understood")
            else:
                sel = ''
                if '(' in t and t.endswith(')'):
                    t, _, s = t[:-1].partition('(')
                    sel = f'({s})'
                p = ci_resolve(self._mac(t), self.cwd)
                if p is None and self._build_in_sibling(t):
                    p = ci_resolve(self._mac(t), self.cwd)
                if p is None:
                    raise MakeError(f"linkiigs: input not found: {t!r}")
                inputs.append((t, p))
                argv.append(p + sel)
        # A -lseg:Dynamic link resolves through the assemblers' symbol
        # tables, which live in this run's object cache — an up-to-date
        # .obj skipped by the mtime check isn't there, so re-run its
        # producing rule for the metadata (cheap, and byte-neutral: the
        # recipe rewrites the same object).
        if any_dynamic:
            for spelled, p in inputs:
                if os.path.abspath(p).lower() in self.objcache:
                    continue
                rule = self._find_rule(spelled) or self._suffix_rule(spelled)
                if rule is None:
                    continue            # a real .obj with no rule: let
                                        # linkcli report what it needs
                self._say(f"gsmake: re-assembling up-to-date {spelled!r} "
                          "for its symbol table (-lseg:Dynamic link)")
                self.run_recipe(rule.recipe,
                                default=self._default_stem(
                                    rule, self._expand(rule.targets[0])))
        spec = linkcli.parse(argv)
        spec['out'] = self._path(spec['out'])
        spec['includes'] = spec['includes'] + self.includes
        spec['objcache'] = self.objcache
        self._say(f"gsmake: linkiigs -> {os.path.basename(spec['out'])}")
        load = linkcli.build(spec)
        self._ensure_parent(spec['out'])
        with open(spec['out'], 'wb') as fh:
            fh.write(load)
        for n in spec['notes']:
            self._say(f"gsmake: note: {n}")
        if spec['filetype'] is not None or spec['auxtype'] is not None:
            from gsasm import makebin as _mb
            ft = spec['filetype'] or 0
            at = spec['auxtype'] or 0
            _mb.stamp(spec['out'], ft, at)
            self._say(f"gsmake: wrote {os.path.basename(spec['out'])}"
                      f".filetype sidecar (type=${ft:02X} aux=${at:04X})")

    def _cmd_reziigs(self, args: list[str]):
        argv: list[str] = []
        src = None
        filetype = auxtype = None
        out = None
        it = iter(args)
        for t in it:
            tl = t.lower()
            if tl == '-o':
                out = self._path(next(it, ''))
                self._ensure_parent(out)
                argv += ['-o', out]
            elif tl == '-t':
                v = next(it, '').strip()
                # "C7  " is a 2-hex-digit type; "$70D80003" is type+aux.
                try:
                    if v.startswith('$') and len(v) > 3:
                        filetype = int(v[1:3], 16)
                        auxtype = int(v[3:], 16) if len(v) > 3 else None
                        argv += ['-t', f'{filetype:02X}']
                    else:
                        argv += ['-t', v]
                        filetype = int(v, 16)
                except ValueError:
                    filetype = None
            elif tl == '-at':
                v = next(it, '').strip()
                try:
                    auxtype = int(v[1:], 16) if v.startswith('$') \
                        else int(v, 0)
                except ValueError:
                    raise MakeError(f"reziigs -at: bad value {v!r}")
            elif tl == '-c':
                argv += ['-c', next(it, '').strip()]
            elif tl in ('-rd',):
                pass
            elif tl in ('-d', '-define'):
                argv += ['-d', next(it, '')]
            elif t.startswith('-'):
                raise MakeError(f"reziigs flag {t!r} not understood")
            else:
                src = ci_resolve(self._mac(t), self.cwd)
                if src is None:
                    raise MakeError(f"reziigs: source not found: {t!r}")
        if src is None:
            raise MakeError("reziigs: no source file")
        argv = [src] + argv + ['--read-dir', self.cwd]
        for d in self.includes:
            argv += ['-I', d]
        self._say(f"gsmake: reziigs {os.path.basename(src)}")
        from gsasm.__main__ import rez_main
        old = sys.argv
        try:
            sys.argv = ['gsrez'] + argv
            rez_main()
        finally:
            sys.argv = old
        if out and (filetype is not None or auxtype is not None):
            from gsasm import makebin as _mb
            _mb.stamp(out, filetype or 0, auxtype or 0)

    def _cmd_makebin(self, args: list[str]):
        from gsasm import makebin as _mb
        src = out = None
        org = 0
        filetype = auxtype = None
        it = iter(args)
        for t in it:
            tl = t.lower()
            if tl == '-o':
                out = self._path(next(it, ''))
            elif tl == '-org':
                v = next(it, '0').strip()
                org = int(v[1:], 16) if v.startswith('$') else int(v, 0)
            elif tl in ('-t', '-at'):
                v = next(it, '0').strip()
                n = int(v[1:], 16) if v.startswith('$') else int(v, 0)
                if tl == '-t':
                    filetype = n
                else:
                    auxtype = n
            elif t.startswith('-'):
                raise MakeError(f"makebiniigs flag {t!r} not understood")
            else:
                src = ci_resolve(self._mac(t), self.cwd)
                if src is None:
                    raise MakeError(f"makebiniigs: input not found: {t!r}")
        if src is None:
            raise MakeError("makebiniigs: no input file")
        if out is None:
            out = src                   # MPW MakeBin converts in place
        with open(src, 'rb') as fh:
            load = fh.read()
        self._say(f"gsmake: makebiniigs {os.path.basename(src)} "
                  f"-> {os.path.basename(out)} (org={org:#x})")
        flat = _mb.makebin(load, org)
        self._ensure_parent(out)
        with open(out, 'wb') as fh:
            fh.write(flat)
        if filetype is not None or auxtype is not None:
            _mb.stamp(out, filetype or 0, auxtype or 0)

    def _cmd_overlay(self, args: list[str]):
        """OverlayIIGS SRC DST -a $OFFSET — lay SRC into DST at the offset,
        growing DST and zero-filling gaps (gsasm.makebin.overlay, whose
        model was proven against this very make.p8 recipe)."""
        from gsasm import makebin as _mb
        paths, off = [], 0
        it = iter(args)
        for t in it:
            if t.lower() == '-a':
                v = next(it, '0').strip()
                off = int(v[1:], 16) if v.startswith('$') else int(v, 0)
            elif t.startswith('-'):
                raise MakeError(f"overlayiigs flag {t!r} not understood")
            else:
                paths.append(t)
        if len(paths) != 2:
            raise MakeError(f"overlayiigs: expected SRC DST, got {paths!r}")
        src = ci_resolve(self._mac(paths[0]), self.cwd)
        dst = ci_resolve(self._mac(paths[1]), self.cwd) \
            or self._path(paths[1])
        if src is None:
            raise MakeError(f"overlayiigs: source not found: {paths[0]!r}")
        host = b''
        if os.path.isfile(dst):
            with open(dst, 'rb') as fh:
                host = fh.read()
        with open(src, 'rb') as fh:
            patch = fh.read()
        self._say(f"gsmake: overlayiigs {os.path.basename(src)} -> "
                  f"{os.path.basename(dst)} @ {off:#x}")
        with open(dst, 'wb') as fh:
            fh.write(_mb.overlay(host, [(patch, off)]))

    def _cmd_makelib(self, args: list[str]):
        """MakeLibIIGS -l LIB -r member.obj... — an MPW object library is
        its members' OMF segments; concatenating the member objects gives a
        file linkiigs -lib consumes (the MSDOS.FST harness links against
        exactly this: the member objects as the library)."""
        out = None
        members = []
        it = iter(args)
        for t in it:
            tl = t.lower()
            if tl == '-l':
                out = self._path(next(it, ''))
            elif tl == '-r':
                pass                    # replace-members: we always rebuild
            elif t.startswith('-'):
                raise MakeError(f"makelibiigs flag {t!r} not understood")
            else:
                members.append(t)
        if out is None or not members:
            raise MakeError("makelibiigs: need -l LIB and member objects")
        parts = []
        for m in members:
            p = ci_resolve(self._mac(m), self.cwd)
            if p is None:
                raise MakeError(f"makelibiigs: member not found: {m!r}")
            with open(p, 'rb') as fh:
                parts.append(fh.read())
        self._say(f"gsmake: makelibiigs -> {os.path.basename(out)} "
                  f"({len(members)} members)")
        self._ensure_parent(out)
        with open(out, 'wb') as fh:
            fh.write(b''.join(parts))

    def _cmd_catenate(self, args: list[str], redirect):
        parts = []
        for a in args:
            p = ci_resolve(self._mac(a), self.cwd)
            if p is None:
                raise MakeError(f"catenate: input not found: {a!r}")
            with open(p, 'rb') as fh:
                parts.append(fh.read())
        data = b''.join(parts)
        if redirect is None:
            sys.stdout.buffer.write(data)
            return
        mode, path = redirect
        outp = self._path(path)
        self._ensure_parent(outp)
        with open(outp, 'ab' if mode == 'a' else 'wb') as fh:
            fh.write(data)

    def _cmd_duplicate(self, args: list[str]):
        import shutil
        paths = [a for a in args if not a.startswith('-')]
        if len(paths) < 2:
            raise MakeError(f"Duplicate: expected SRC... DST, got {paths!r}")
        dst = self._path(paths[-1])
        srcs = paths[:-1]
        if len(srcs) > 1 and not os.path.isdir(dst):
            raise MakeError(
                f"Duplicate: several sources need a directory target: {dst}")
        for s in srcs:
            sp = ci_resolve(self._mac(s), self.cwd)
            if sp is None:
                raise MakeError(f"Duplicate: source not found: {s!r}")
            d = os.path.join(dst, os.path.basename(sp)) \
                if os.path.isdir(dst) else dst
            self._ensure_parent(d)
            shutil.copyfile(sp, d)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str]) -> int:
    import argparse
    p = argparse.ArgumentParser(
        prog='gsmake',
        description="Run an original MPW IIgs makefile with the gsasm "
                    "toolchain (asmiigs/linkiigs/reziigs/makebiniigs "
                    "interpreted in-process).")
    p.add_argument('targets', nargs='*',
                   help='targets to build (default: the first rule)')
    p.add_argument('-f', dest='makefile',
                   help='makefile (default: ./makefile, case-insensitive)')
    p.add_argument('-C', dest='chdir', metavar='DIR',
                   help='build directory (where the makefile lives)')
    p.add_argument('-I', dest='includes', action='append', default=[],
                   metavar='DIR', help='assembler include directory')
    p.add_argument('-D', dest='defines', action='append', default=[],
                   metavar='NAME=VAL',
                   help='makefile variable / assembler define')
    p.add_argument('--always', action='store_true',
                   help='rebuild everything, ignore timestamps')
    p.add_argument('--strict-vars', action='store_true',
                   help='error on undefined {var} instead of the MPW '
                        'shell behavior (expand empty, report at the end)')
    p.add_argument('-q', '--quiet', action='store_true')
    args = p.parse_args(argv)

    base = os.path.abspath(args.chdir or '.')
    mf = args.makefile
    if mf is None:
        mf = ci_resolve('makefile', base)
        if mf is None:
            raise MakeError(f"no makefile in {base}")
    elif not os.path.isabs(mf):
        mf = os.path.join(base, mf)

    defines = {}
    for kv in args.defines:
        k, _, v = kv.partition('=')
        defines[k] = v if v else '1'

    maker = Maker(mf, includes=args.includes, defines=defines,
                  always=args.always, verbose=not args.quiet,
                  strict_vars=args.strict_vars)
    targets = args.targets or [maker.default_target()]
    for t in targets:
        maker.build(t)
    if maker.missing_vars:
        print("gsmake: note: these makefile variables were unset and "
              "expanded empty (the MPW shell would have Set them): "
              + ', '.join(sorted(maker.missing_vars, key=str.lower))
              + " — override with -D NAME=VAL", file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
