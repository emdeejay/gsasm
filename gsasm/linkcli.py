"""MPW LinkIIgs-style command line for gslink (multi-object mode).

Speaks the vocabulary the original ``linkiigs`` invocations in the System
6.0.1 makefiles use, so a makefile link rule can be copied nearly verbatim:

    gslink -lseg MAIN lw.obj dialogdata.obj \\
           -lseg:Dynamic PREPFILE prepfile.obj \\
           -o laserwriter -t $BB -at $0001

Flag coverage (from a survey of all 239 link invocations in the 6.0.1
source tree — see GitHub issue #2):

    -o FILE            output load file
    -lseg NAME         start a load-segment group; following inputs join it
    -lseg:Dynamic NAME same, KIND |= 0x8000 (on-demand segment, routed
                       through a linker-generated ~JumpTable)
    -x                 ExpressLoad output (multi-segment output is always
                       ExpressLoad here; -x also selects it for a single
                       merged segment)
    -org $ADDR         base placement address (ungrouped links only)
    -t TYPE, -at AUX   ProDOS filetype/auxtype — gsasm writes bytes, not
                       filesystem metadata, so these are REPORTED for the
                       disk-image tool to apply, not written anywhere
    -l -s -c -a -w* -sym -mf
                       listing/map/warning flags: accepted and ignored
    -lib FILE          library object: ungrouped roots link against it with
                       MPW's on-demand member extraction
                       (linkiigs.link_lib); repeatable

gsasm extensions (the original linkiigs linked .obj files only; this CLI
also assembles sources in-process, which preserves the full symbol table
and is required for -lseg:Dynamic):

    -I DIR             include directory for assembled sources (repeatable)
    -d NAME=VAL        assembler command-line equate (repeatable)

An input may carry an MPW object-segment selector — ``file.obj(NAME,...)``
or ``file.obj(@SEGNAME)`` — linking only those segments of that object, in
selector order (matched against the object's OMF segment names,
case-insensitively, leading ``@`` ignored).

Inputs ending in .obj/.o/.root are read as OMF object bytes (linked with
``asm=None`` — GLOBAL/GEQU records only, the pre-concatenated-combo path);
anything else is assembled with ``gsasm.asm.assemble``.

Dynamic segments need the assembler's symbol/export metadata to resolve
cross-segment references, so ``-lseg:Dynamic`` groups must be given SOURCE
files, not .obj files.  The ~JumpTable is allocated by
``expressload(..., jt_entries='auto')``: entries appear at first reference
in resolution order — functionally correct, but not byte-identical to MPW's
reference-scan allocation order (the gold-gated corpus builders pass the
proven list instead and are untouched by this mode).
"""
from __future__ import annotations

import os
import sys


# ProDOS 16 / GS/OS filetype mnemonics seen in the makefiles (-t S16 etc.).
_FILETYPES = {
    'BIN': 0x06, 'SYS': 0xFF, 'S16': 0xB3, 'RTL': 0xB4, 'EXE': 0xB5,
    'PIF': 0xB6, 'TIF': 0xB7, 'NDA': 0xB8, 'CDA': 0xB9, 'TOL': 0xBA,
    'DVR': 0xBB, 'LDF': 0xBC, 'FST': 0xBD,
}

# Standalone flags from the survey that only affect listings/maps/warnings.
_IGNORED_FLAGS = ('-l', '-s', '-c', '-a', '-sym', '-mf', '-lo')

_NEW_MODE_FLAGS = ('-x', '-org', '-t', '-at', '-lib', '-I', '-d')


class LinkCliError(SystemExit):
    def __init__(self, msg: str):
        super().__init__(f"gslink: error: {msg}")


def wants_mpw_mode(argv: list[str]) -> bool:
    """True when *argv* needs the multi-object MPW-style parser: any mode
    flag, any -lseg, or more than one positional input.  A plain
    ``gslink file.obj [-o out]`` keeps the original single-object path."""
    positionals = 0
    it = iter(argv)
    for tok in it:
        if tok.startswith('-lseg') or tok in _NEW_MODE_FLAGS \
                or tok.startswith('-w'):
            return True
        if tok == '-o':
            next(it, None)
            continue
        if not tok.startswith('-'):
            positionals += 1
    return positionals > 1


def _num(tok: str, what: str) -> int:
    t = tok.strip()
    try:
        if t.startswith('$'):
            return int(t[1:], 16)
        if t.lower().startswith('0x'):
            return int(t, 16)
        return int(t, 10)
    except ValueError:
        raise LinkCliError(f"bad {what} value {tok!r}")


def _filetype(tok: str) -> int:
    t = tok.strip()
    if t.upper() in _FILETYPES:
        return _FILETYPES[t.upper()]
    if t.startswith('$') or t.lower().startswith('0x'):
        return _num(t, 'filetype')
    # Makefile spellings like -t "06 " are bare hex.
    try:
        return int(t, 16)
    except ValueError:
        raise LinkCliError(f"unknown filetype {tok!r} (use $hex or a "
                           f"mnemonic: {', '.join(sorted(_FILETYPES))})")


def parse(argv: list[str]) -> dict:
    """Parse MPW LinkIIgs-style *argv* into a spec dict."""
    spec = {
        'out': None, 'express': False, 'org': None,
        'filetype': None, 'auxtype': None,
        'includes': [], 'defines': {},
        'loose': [],            # inputs before any -lseg
        'groups': [],           # [{'name', 'dynamic', 'inputs'}]
        'libs': [],             # -lib files
        'notes': [],
    }
    cur = None                  # current -lseg group, or None
    it = iter(argv)

    def _arg(flag):
        v = next(it, None)
        if v is None:
            raise LinkCliError(f"{flag} needs a value")
        return v

    for tok in it:
        if tok.startswith('-lseg'):
            quals = [q.lower() for q in tok.split(':')[1:]]
            name = _arg('-lseg')
            kind = None
            extra = []
            for q in quals:
                if q == 'dynamic':
                    continue
                if q.startswith('$') or q.startswith('0x'):
                    # -lseg:$1000 — an explicit segment KIND.
                    kind = _num(q, '-lseg kind')
                else:
                    extra.append(q)
            cur = {'name': name, 'dynamic': 'dynamic' in quals,
                   'kind': kind, 'inputs': []}
            if extra:
                spec['notes'].append(
                    f"-lseg qualifiers {extra} ignored (segment {name!r})")
            spec['groups'].append(cur)
        elif tok == '-o':
            spec['out'] = _arg('-o')
        elif tok == '-x':
            spec['express'] = True
        elif tok == '-org':
            if cur is not None:
                raise LinkCliError(
                    "per-segment -org is not supported yet (only a global "
                    "-org before any -lseg, for ungrouped links)")
            spec['org'] = _num(_arg('-org'), '-org')
        elif tok == '-t':
            spec['filetype'] = _filetype(_arg('-t'))
        elif tok == '-at':
            spec['auxtype'] = _num(_arg('-at'), '-at')
        elif tok == '-I':
            spec['includes'].append(_arg('-I'))
        elif tok == '-d':
            kv = _arg('-d')
            name, _, val = kv.partition('=')
            spec['defines'][name] = _num(val, '-d') if val else 1
        elif tok == '-lib':
            spec['libs'].append(_arg('-lib'))
        elif tok in _IGNORED_FLAGS or tok == '-apw' or tok.startswith('-w'):
            spec['notes'].append(f"flag {tok} ignored (listing/map/warning)")
        elif tok.startswith('-'):
            raise LinkCliError(f"unknown flag {tok}")
        else:
            sels = None
            if '(' in tok and tok.endswith(')'):
                # MPW object-segment selector: path.obj(NAME,@SEG,...) —
                # link only those segments of that object, in that order.
                tok, _, sel = tok[:-1].partition('(')
                sels = [s.strip() for s in sel.split(',') if s.strip()]
            entry = (tok, sels)
            (cur['inputs'] if cur is not None else spec['loose']).append(entry)

    if spec['groups'] and spec['loose']:
        # MPW: objects BEFORE the first -lseg form the leading load segment,
        # named 'main' (ControlMgr's makefile links exactly this shape).
        spec['groups'].insert(0, {'name': 'main', 'dynamic': False,
                                  'kind': None, 'inputs': spec['loose']})
        spec['loose'] = []
        spec['notes'].append(
            "inputs before the first -lseg form the leading 'main' segment")
    if not spec['groups'] and not spec['loose']:
        raise LinkCliError("no input files")
    for g in spec['groups']:
        if not g['inputs']:
            raise LinkCliError(f"-lseg {g['name']} has no input files")
    if spec['out'] is None:
        raise LinkCliError("-o OUTPUT is required in multi-object mode")
    return spec


def _seg_indices(obj_bytes: bytes, sels, path: str) -> list[int]:
    """Indices of the segments *sels* names within one object's bytes, in
    selector order (None = every segment).  A name matches a SEGNAME (one
    PROC/module) or, failing that, a LOADNAME — the ``SEG 'Section'``
    directive's load-segment tag, which selects EVERY segment of that
    section in object order (``copybits.asm.obj(@MAINPart)``).  Matching is
    case-insensitive with any leading ``@`` ignored on either side."""
    from gsasm import omf
    segs = list(omf.iter_segments(obj_bytes, records=False))
    if sels is None:
        return list(range(len(segs)))

    def _norm(x) -> str:
        if isinstance(x, bytes):
            x = x.decode('mac_roman', 'replace')
        return x.strip().strip('\x00').lower().lstrip('@')

    segnames = [_norm(s['name']) for s in segs]
    loadnames = [_norm(s['hdr'].get('LOADNAME', b'')) for s in segs]
    idxs: list[int] = []
    for want in sels:
        w = _norm(want)
        if w in segnames:
            idxs.append(segnames.index(w))
            continue
        section = [i for i, ln in enumerate(loadnames) if ln == w]
        if section:
            idxs.extend(section)
            continue
        raise LinkCliError(
            f"{path}: no segment or SEG section named {want!r} (segments: "
            f"{', '.join(sorted(set(segnames)))or 'none'}; sections: "
            f"{', '.join(sorted(set(loadnames))) or 'none'})")
    return idxs


def _load_input(path: str, spec: dict, *, need_asm: bool):
    """(obj_bytes, asm_or_None) for one input file.

    ``spec['objcache']`` (optional, {casefolded-abspath: (obj_bytes, asm)})
    lets a driving tool — gsmake, which just assembled the .obj itself —
    supply the object WITH its Asm, so even a ``-lseg:Dynamic`` group can
    be given .obj paths, exactly as the original makefiles write them.
    Keys are ``os.path.abspath(p).lower()``: the makefiles spell one file
    several ways (``Lw.asm.obj`` / ``lw.asm.obj``) and ProDOS/HFS treat
    them as the same file (darwin's ``normcase`` is the identity, so it
    cannot do this job)."""
    cache = spec.get('objcache')
    if cache:
        hit = cache.get(os.path.abspath(path).lower())
        if hit is not None:
            ob, a = hit
            if need_asm and a is None:
                raise LinkCliError(
                    f"{path}: cached object has no assembler metadata; a "
                    "-lseg:Dynamic link needs sources assembled in-process")
            return ob, a
    from gsasm import asm as _asm, omf as _omf
    if not os.path.exists(path):
        raise LinkCliError(f"input file not found: {path}")
    ext = os.path.splitext(path)[1].lower()
    if ext in ('.obj', '.o', '.root'):
        if need_asm:
            raise LinkCliError(
                f"{path}: a -lseg:Dynamic link needs SOURCE files (the "
                "jump-table resolution uses the assembler's symbol table); "
                "pass the .asm/.aii sources instead of .obj files")
        with open(path, 'rb') as fh:
            return fh.read(), None
    incs = [os.path.dirname(path) or '.'] + spec['includes']
    a = _asm.assemble(path, incs, defines=spec['defines'] or None)
    errs = getattr(a, 'errors', None)
    if errs:
        raise LinkCliError(f"assembly of {path} failed:\n" + "\n".join(errs))
    return _omf.emit(a), a


def build(spec: dict) -> bytes:
    """Run the link described by *spec*; returns the output file bytes."""
    groups = spec['groups']
    if spec['libs'] and groups:
        raise LinkCliError(
            "-lib together with -lseg groups is not supported yet")

    def _load_entries(entries, *, need_asm):
        """-> (objects, order, any_sel): order is the full (obj_idx,
        seg_idx) placement list honoring selectors."""
        objects, order, any_sel = [], [], False
        for path, sels in entries:
            ob, a = _load_input(path, spec, need_asm=need_asm)
            oi = len(objects)
            objects.append((ob, a))
            for si in _seg_indices(ob, sels, path):
                order.append((oi, si))
            any_sel = any_sel or sels is not None
        return objects, order, any_sel

    if not groups:
        # Ungrouped: merge everything into one load segment.
        objects, order, any_sel = _load_entries(spec['loose'],
                                                need_asm=False)
        from gsasm import linkiigs
        opts = {'merge': True, 'super': True}
        if any_sel:
            opts['seg_order'] = order
        if spec['org']:
            opts['org'] = spec['org']
        if spec['libs']:
            libs = [_load_input(p, spec, need_asm=False)
                    for p in spec['libs']]
            return linkiigs.link_lib(objects, libs, opts)
        if spec['express']:
            from gsasm.expressload import expressload
            return expressload(objects,
                               opts={'order': order} if any_sel else None)
        return linkiigs.link(objects, opts)

    # Grouped: multi-segment ExpressLoad (the golden layout requires every
    # non-dynamic group before every dynamic one; reorder like MPW does,
    # keeping relative order within each block).
    any_dyn = any(g['dynamic'] for g in groups)
    ordered = ([g for g in groups if not g['dynamic']]
               + [g for g in groups if g['dynamic']])
    if ordered != groups:
        spec['notes'].append(
            "segments reordered: non-dynamic block first, then dynamic "
            "(the load-file layout MPW LinkIIgs emits)")
    if not spec['express']:
        spec['notes'].append(
            "multi-segment output is ExpressLoad format (as if -x); "
            "GS/OS loads it either way")

    objects, obj_group, order, any_sel = [], [], [], False
    for gi, g in enumerate(ordered):
        for path, sels in g['inputs']:
            ob, a = _load_input(path, spec, need_asm=any_dyn)
            oi = len(objects)
            objects.append((ob, a))
            obj_group.append(gi)
            for si in _seg_indices(ob, sels, path):
                order.append((oi, si))
            any_sel = any_sel or sels is not None

    from gsasm.expressload import expressload
    opts = {
        'multiseg': True,
        'obj_group': obj_group,
        'segnames': [g['name'].encode('mac_roman') for g in ordered],
        'segkinds': [(g.get('kind') or 0)
                     | (0x8000 if g['dynamic'] else 0) for g in ordered],
    }
    if any_sel:
        opts['order'] = order
    if any_dyn:
        opts['jt_entries'] = 'auto'
    return expressload(objects, opts)


def main(argv: list[str]) -> int:
    spec = parse(argv)
    load_bytes = build(spec)

    from gsasm import omf
    for seg in omf.iter_segments(load_bytes, records=False):
        h = seg['hdr']
        print(f"  {seg['name']:24s}  {h['LENGTH']:#8x}  "
              f"({h['LENGTH']} bytes)  KIND={h['KIND']:#06x}")
    with open(spec['out'], 'wb') as fh:
        fh.write(load_bytes)
    print(f"→ {spec['out']}  ({len(load_bytes)} bytes)")

    for n in spec['notes']:
        print(f"note: {n}")
    if spec['filetype'] is not None or spec['auxtype'] is not None:
        ft = spec['filetype'] if spec['filetype'] is not None else 0
        at = spec['auxtype'] if spec['auxtype'] is not None else 0
        print(f"note: set filetype=${ft:02X} auxtype=${at:04X} when copying "
              f"{spec['out']} onto a ProDOS volume (gsasm writes bytes, not "
              f"filesystem metadata)")
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
