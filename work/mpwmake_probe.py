"""mpwmake_probe.py — READ-ONLY probe: parse the shipping MPW makefiles' LinkIIGS
invocations and diff the object lists against the hand-transcribed harness maps
(toolcheck.TOOLMAP / fstcheck.FSTMAP / drivercheck.DRIVERMAP).

Answers, with data, the architecture question: how much of the remaining harness
recipe is a faithful copy of the makefile vs. a transcription error?  Nothing is
wired or changed — this only reports.

Run: python3 work/mpwmake_probe.py
"""
import os, re, sys, glob
sys.path.insert(0, '.'); sys.path.insert(0, 'work')

_SRC = 'ref/GSOS_6/IIGS.601.SRC'


# ---------------------------------------------------------------------------
# minimal MPW-make link-line parser
# ---------------------------------------------------------------------------

def _logical_lines(path):
    """Read a mac_roman MPW makefile; join ∂-continued lines."""
    txt = open(path, 'rb').read().decode('mac_roman', 'replace')
    out, buf = [], ''
    for raw in re.split(r'\r\n|\r|\n', txt):
        if raw.rstrip().endswith('∂'):
            buf += raw.rstrip()[:-1] + ' '
        else:
            buf += raw
            out.append(buf)
            buf = ''
    if buf:
        out.append(buf)
    return out


def _tokens(s):
    """Split respecting 'single-quoted names with spaces' (MPW quoting).

    A quote can sit MID-token (`:HD.Obj:'SCSIHD Driver main.obj'`), so a token
    is any run of non-space/non-quote chars and quoted spans; the quotes are
    then removed (MPW quoting, like shell quote-removal)."""
    return [t.replace("'", '')
            for t in re.findall(r"(?:[^\s']+|'[^']*')+", s)]


def _srcname(obj_token):
    """Map a LinkIIGS object arg to its source basename, lowercased.

    Handles MPW paths (`::menumgr:wcm.asm.obj`, `:objs:qdaux.asm.obj`,
    `:HD.Obj:'SCSIHD Driver main.obj'`), a trailing `(@loadname)` filter, and the
    `.obj` suffix.  Returns e.g. 'wcm.asm' / 'scsihd driver main'.
    """
    t = obj_token
    t = re.sub(r'\(@[^)]*\)$', '', t)          # strip (@loadname) filter
    t = t.rsplit(':', 1)[-1]                    # MPW path -> basename
    t = re.sub(r'\.obj$', '', t, flags=re.I)    # strip .obj
    return t.strip().lower()


def parse_targets(path):
    """{target_lower: [obj_srcname,...]} from MPW dependency lines `TARGET ƒ deps`.

    The dependency line is the AUTHORITATIVE object list: the shipping ControlMgr /
    LineEdit have their LinkIIGS *rule* half-commented with `#`, but the target's
    prerequisites list the full set (and match the shipping binary).
    """
    out = {}
    for line in _logical_lines(path):
        if 'ƒ' not in line:
            continue
        left, right = line.split('ƒ', 1)
        tgt = left.strip().split()
        if not tgt:
            continue
        tname = tgt[0].lower()
        objs = [_srcname(t) for t in _tokens(right.split('#', 1)[0])
                if re.search(r'\.obj$', t, re.I)]
        if objs:
            out.setdefault(tname, objs)
    return out


_LINK_RE = re.compile(r'^\s*linkiigs\b', re.I)
_SKIP_VAL_FLAGS = {'-o', '-t', '-at', '-c', '-i', '-d'}   # flags that consume the next token


def parse_link_lines(path):
    """Return [ {output, filetype, objects:[srcname], lsegs:[(name,attrs,[srcname])],
    truncated_by_hash:bool} ] for each LinkIIGS invocation in *path*."""
    invs = []
    for line in _logical_lines(path):
        if not _LINK_RE.match(line):
            continue
        had_hash = '#' in line
        line = line.split('#', 1)[0]            # MPW '#' = end-of-line comment
        toks = _tokens(line)[1:]                # drop 'linkiigs'
        out = {'output': None, 'filetype': None, 'objects': [], 'lsegs': [],
               'truncated_by_hash': had_hash}
        cur_group = None                        # None = default (main) group
        i = 0
        while i < len(toks):
            t = toks[i]
            low = t.lower()
            if low == '-o' and i + 1 < len(toks):
                out['output'] = toks[i+1]; i += 2; continue
            if low == '-t' and i + 1 < len(toks):
                out['filetype'] = toks[i+1]; i += 2; continue
            if low in _SKIP_VAL_FLAGS and i + 1 < len(toks):
                i += 2; continue
            if low.startswith('>') or low == '-l' or low == '-x' or low == '-apw':
                i += 1; continue
            if low.startswith('-lseg'):
                attrs = t.split(':', 1)[1] if ':' in t else ''
                name = toks[i+1] if i + 1 < len(toks) else '?'
                cur_group = {'name': name, 'attrs': attrs, 'objects': []}
                out['lsegs'].append(cur_group); i += 2; continue
            if low.startswith('-'):             # unknown flag, skip it alone
                i += 1; continue
            if t.startswith('>'):
                i += 1; continue
            # otherwise: an object argument
            sn = _srcname(t)
            if cur_group is not None:
                cur_group['objects'].append(sn)
            else:
                out['objects'].append(sn)
            i += 1
        if out['output'] or out['objects'] or out['lsegs']:
            invs.append(out)
    return invs


def all_objects(inv):
    objs = list(inv['objects'])
    for g in inv['lsegs']:
        objs += g['objects']
    return objs


# ---------------------------------------------------------------------------
# harness maps
# ---------------------------------------------------------------------------

def harness_tool_srcs(entry):
    """Flatten a toolcheck.TOOLMAP value to a set of source basenames."""
    _name, spec = entry
    out = []
    if isinstance(spec, list):
        out = spec
    elif isinstance(spec, dict) and 'segments' in spec:
        for seg in spec['segments']:
            out += seg.get('srcs', [])
            for _n, _org, ex in seg.get('extern_srcs', []):
                out += ex
    return {os.path.basename(s).lower() for s in out}


def norm(s):
    return {os.path.basename(x).lower() for x in s}


# ---------------------------------------------------------------------------
# probe
# ---------------------------------------------------------------------------

def index_makefiles(root):
    """Merge parse_targets + LinkIIGS -o over every makefile under root, keyed by
    output/target name (lower).  Value: (path, obj_srcnames, source: 'dep'|'link')."""
    idx = {}
    for dp, _dn, fs in os.walk(root):
        for f in fs:
            if not (f.lower() == 'makefile' or f.lower().endswith('.make')
                    or 'makefile' in f.lower()):
                continue
            p = os.path.join(dp, f)
            try:
                # LinkIIGS -o (the link command) — recorded but secondary
                for inv in parse_link_lines(p):
                    if inv['output']:
                        idx.setdefault(inv['output'].lower(),
                                       (p, norm(all_objects(inv)), 'link'))
                # dependency targets (authoritative object list) — override
                for tname, objs in parse_targets(p).items():
                    idx[tname] = (p, norm(objs), 'dep')
            except Exception as exc:
                print(f'  parse error {p}: {exc}', file=sys.stderr)
    return idx


_ASM_RE = re.compile(r'^\s*asmiigs\b', re.I)


def _strip_var(tok):
    """Strip a leading MPW `{Variable}` (optionally double-quoted) prefix."""
    return re.sub(r'^"?\{[^}]*\}"?', '', tok).strip()


def parse_component(path):
    """For a single-component make.<x> file: return (output_name, {src_basenames},
    {defines}).  output = the `{SDfsts}X`/`{SDdrivers}X`/link `-o X` target; sources
    = every `asmiigs <src>` arg; defines = every `-d NAME=VAL`.

    A component whose objects are built by the generic `.obj ƒ .aii` suffix rule
    (e.g. MSDos.FST) has no per-source asmiigs line — its sources are recovered
    from the target's `.obj` dependency list (one level of `.lib` indirection),
    mapped obj -> src via that suffix rule."""
    output = None
    srcs, defines = set(), {}
    deps = {}          # target basename (lower) -> [dep tokens]
    for line in _logical_lines(path):
        body = line.split('#', 1)[0]
        low = body.lower()
        # output target: `{SDfsts}Pro.FST ƒ ...` or link `-o {object}Pro.FST`
        if 'ƒ' in body and ('{sdfsts}' in low or '{sddrivers}' in low):
            tgt = body.split('ƒ', 1)[0].strip()
            output = _strip_var(tgt)
        if 'ƒ' in body:
            left, right = body.split('ƒ', 1)
            ltoks = [_strip_var(t) for t in _tokens(left)]
            for lt in ltoks:
                if lt:
                    deps.setdefault(lt.lower(), []).extend(
                        _strip_var(t) for t in _tokens(right))
        m = re.search(r'-o\s+(\S+)', body)
        if _LINK_RE.match(body) and m and output is None:
            output = _strip_var(m.group(1))
        if _ASM_RE.match(body):
            toks = _tokens(body)[1:]
            src = None
            i = 0
            while i < len(toks):
                t = toks[i]
                if t.lower() == '-d' and i + 1 < len(toks):
                    kv = toks[i+1].split('=')
                    val = kv[1] if len(kv) > 1 else '1'
                    # `-d &type,type=0` defines a comma-list of names
                    for nm in kv[0].split(','):
                        defines[nm.lstrip('&')] = val
                    i += 2; continue
                if t.lower() in _SKIP_VAL_FLAGS:
                    i += 2; continue
                if t.startswith('-'):
                    i += 1; continue
                # first real positional (strip {Var} prefix + MPW path; skip pure
                # {Variable} tokens like {AOptions}) = the assembled source.
                # Sources may be extensionless ('SCSI Driver main').
                if src is None:
                    name = _strip_var(t).rsplit(':', 1)[-1].lower()
                    # an unresolved {var} (e.g. the suffix rule's {default})
                    # is not a concrete source
                    if name and '{' not in name:
                        src = re.sub(r'\.obj$', '', name).strip('"')
                i += 1
            if src:
                srcs.add(src)
    # suffix-rule fallback: no asmiigs-derived sources -> walk the output
    # target's .obj deps (expanding one level of .lib) and map obj -> .aii
    if output and not srcs:
        pend = list(deps.get(output.lower(), []))
        for t in pend:
            base = t.rsplit(':', 1)[-1].strip().lower()
            if base.endswith('.lib'):
                pend.extend(deps.get(base, []))
            elif base.endswith('.obj'):
                srcs.add(re.sub(r'\.obj$', '.aii', base))
    return output, srcs, defines


def diff_components(map_obj, roots, label):
    """Diff FSTMAP/DRIVERMAP {name:(subdir,[srcs],{defines})} against the
    make.<component> files under roots."""
    # index components by output name
    comps = {}
    for root in roots:
        for dp, _dn, fs in os.walk(root):
            for f in fs:
                if 'make' not in f.lower():
                    continue
                out, srcs, defs = parse_component(os.path.join(dp, f))
                if out:
                    comps[out.lower()] = (f, srcs, defs)
    print(f'=== {label}: make.<component> sources vs harness map ===')
    exact = 0
    for name, (_sub, hsrcs, hdefs) in map_obj.items():
        c = comps.get(name.lower())
        H = {os.path.basename(s).lower() for s in hsrcs}
        if not c:
            print(f'  {name:16s}: no make.<component> output matched')
            continue
        _f, M, mdefs = c
        miss, extra = M - H, H - M
        tag = 'EXACT' if not miss and not extra else 'DIFF'
        exact += tag == 'EXACT'
        dtag = '' if {k: str(v) for k, v in hdefs.items()} == mdefs else \
               f'  defines mk={mdefs} harness={hdefs}'
        print(f'  {name:16s}: {tag}  mk={len(M)} harness={len(H)}{dtag}')
        if miss:
            print(f'       only in MAKEFILE : {sorted(miss)}')
        if extra:
            print(f'       only in HARNESS  : {sorted(extra)}')
    print(f'  --> {exact}/{len(map_obj)} {label} EXACT match the shipping makefile')
    return exact, len(map_obj)


def diff_tools():
    from toolcheck import TOOLMAP
    idx = index_makefiles(f'{_SRC}/GSToolbox')
    print('=== TOOLS: shipping makefile object list vs toolcheck.TOOLMAP ===')
    exact = 0
    for num, entry in sorted(TOOLMAP.items()):
        found = idx.get(f'tool{num}')
        hs = harness_tool_srcs(entry)
        if not found:
            print(f'  Tool{num} {entry[0]:12s}: NO makefile target/-o tool{num} found')
            continue
        _path, mk, src = found
        miss = mk - hs          # in makefile, not in harness
        extra = hs - mk         # in harness, not in makefile
        tag = 'EXACT' if not miss and not extra else 'DIFF'
        if tag == 'EXACT':
            exact += 1
        print(f'  Tool{num} {entry[0]:12s}: {tag}  makefile={len(mk)}({src}) '
              f'harness={len(hs)}')
        if miss:
            print(f'       only in MAKEFILE : {sorted(miss)}')
        if extra:
            print(f'       only in HARNESS  : {sorted(extra)}')
    print(f'  --> {exact}/{len(TOOLMAP)} tools EXACT match the shipping makefile')
    return exact, len(TOOLMAP)


def main(check=False):
    """Report mode prints the diff; --check mode (WP-4.3 drift gate) exits 1
    unless EVERY harness map entry EXACTLY matches its shipping makefile.
    Baseline: 8/8 tools, 7/7 FSTs, 12/12 drivers (2026-07-10)."""
    results = []
    results.append(diff_tools())
    print()
    from fstcheck import FSTMAP
    results.append(diff_components(
        FSTMAP, [f'{_SRC}/GS.OS/MakeFiles', f'{_SRC}/GS.OS/FSTs'], 'FSTs'))
    print()
    from drivercheck import DRIVERMAP
    results.append(diff_components(
        DRIVERMAP, [f'{_SRC}/GS.OS/MakeFiles', f'{_SRC}/GS.OS/Drivers'],
        'Drivers'))
    if check:
        bad = [(e, t) for e, t in results if e != t]
        if bad:
            print('\nDRIFT: harness map(s) no longer match the shipping '
                  'makefiles — fix the map or the parser, do not ship drift.')
            return 1
        print('\nOK: all harness maps match the shipping makefiles.')
    return 0


if __name__ == '__main__':
    sys.exit(main(check='--check' in sys.argv[1:]))
