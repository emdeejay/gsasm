#!/usr/bin/env python3
"""Differential-linking provability oracle.

Links BOTH the original AsmIIgs .obj and gsasm's emitted .obj with the SAME
linker and compares the load files.  Two linker backends are supported:

  default   iix link  (Golden Gate / ORCA-M)
  --gs      gsasm's own Python OMF linker (fully standalone)

If both outputs match, gsasm's object is *semantically* correct even when its
bytes differ from the original (cosmetic OMF encoding choices the linker
collapses).
"""
import sys, os, glob, subprocess, struct, re
from _common import ensure_repo_on_path, romsrc_incs, romsrc_root, work_rel
ensure_repo_on_path()
from gsasm import asm, omf
from gsasm import link as _gs_link

ROOT = romsrc_root()
INCS = romsrc_incs(ROOT)
LINKDIR = work_rel('link')

# FinderInfo for ProDOS type OBJ ($B1), creator 'pdos'
FINFO = bytes([0x70, 0xB1, 0x00, 0x00]) + b'pdos' + b'\x00' * 24


def gg_link(obj_bytes, base):
    os.makedirs(LINKDIR, exist_ok=True)
    root = os.path.join(LINKDIR, base + '.root')
    out = os.path.join(LINKDIR, base + '.out')
    for f in (root, out):
        if os.path.exists(f):
            os.remove(f)
    with open(root, 'wb') as fh:
        fh.write(obj_bytes)
    # set FinderInfo so Golden Gate sees a ProDOS OBJ file (macOS: xattr CLI)
    subprocess.run(['xattr', '-wx', 'com.apple.FinderInfo', FINFO.hex(), root],
                   check=True)
    r = subprocess.run(['iix', 'link', base, 'keep=' + base + '.out', '+P'],
                       cwd=LINKDIR, capture_output=True, text=True)
    if not os.path.exists(out):
        return None, r.stdout + r.stderr
    return open(out, 'rb').read(), r.stdout


def srcfor(o):
    import glob as _glob
    stem = o[:-4]                                  # drop .obj
    if stem.endswith(('.asm', '.aii')) and os.path.exists(stem):
        return stem
    for ext in ('.asm', '.aii'):
        if os.path.exists(stem + ext):
            return stem + ext
    # case-insensitive .aii/.asm in the dir (obj name may differ in case/ext)
    base = os.path.basename(stem).lower()
    for f in _glob.glob(os.path.dirname(o) + '/*'):
        if os.path.basename(f).lower() in (base + '.aii', base + '.asm'):
            return f
    if os.path.exists(stem) and not stem.endswith('.obj'):
        return stem
    return None


def _makefile_defines(src):
    """Extract -d KEY=VALUE defines from the makefile rule that builds <src>.obj."""
    mf = os.path.join(os.path.dirname(src), 'makefile')
    if not os.path.exists(mf):
        return {}
    obj_name = os.path.basename(src) + '.obj'  # e.g. RomDataMgr.asm.obj
    text = open(mf, encoding='mac_roman', errors='replace').read()
    defines = {}
    # A MPW make rule has the TARGET as the first token on the line (before the
    # dependency separator). Only match lines where obj_name is the leftmost token
    # (i.e. appears before any whitespace that is NOT preceded by obj_name).
    in_rule = False
    for line in text.splitlines():
        stripped = line.strip()
        # Check if this line's first token is obj_name (the build target for our obj)
        first_token = stripped.split('\t')[0].split(' ')[0].strip()
        if first_token.lower() == obj_name.lower():
            in_rule = True
            continue
        if in_rule:
            if 'smiigs' in stripped.lower():
                for m in re.finditer(r'-d\s+([A-Za-z_]\w*)=(\S+)', stripped):
                    val = m.group(2)
                    try:
                        val = int(val)
                    except ValueError:
                        pass
                    defines[m.group(1)] = val
                break
            if stripped and not line.startswith('\t') and not line.startswith(' '):
                in_rule = False  # new rule started without Asmiigs
    return defines


def gs_link(obj_bytes):
    """Link obj_bytes with the built-in Python OMF linker; return body bytes."""
    linked = _gs_link.link(obj_bytes)
    body = b''
    for seg in omf.iter_segments(linked):
        body += b''.join(d for _, nm, d in seg['recs'] if nm == 'LCONST')
    return body, ''


def check(src, objf, use_gs=False):
    base = os.path.basename(src).replace('.', '_')
    orig_obj = open(objf, 'rb').read()
    # Use makefile defines only when needed: if assembly without defines already
    # produces the same obj as orig, the defines are irrelevant (or wrong).
    defs = _makefile_defines(src)
    a = asm.assemble(src, INCS, defines={})
    mine_obj = omf.emit(a)
    if defs and mine_obj != orig_obj:
        a = asm.assemble(src, INCS, defines=defs)
        mine_obj = omf.emit(a)
    byte_id = (mine_obj == orig_obj)
    if use_gs:
        o_out, o_log = gs_link(orig_obj)
        m_out, m_log = gs_link(mine_obj)
        if not o_out:
            return 'ORIG_LINK_FAIL', byte_id
        if not m_out:
            return 'MINE_LINK_FAIL', byte_id
        return ('LINK_IDENTICAL' if o_out == m_out else 'LINK_DIFF'), byte_id
    o_out, o_log = gg_link(orig_obj, base + '_o')
    m_out, m_log = gg_link(mine_obj, base + '_m')
    if o_out is None:
        return 'ORIG_LINK_FAIL', byte_id
    if m_out is None:
        return 'MINE_LINK_FAIL', byte_id
    return ('LINK_IDENTICAL' if o_out == m_out else 'LINK_DIFF'), byte_id


def main():
    use_gs = '--gs' in sys.argv
    args = [a for a in sys.argv[1:] if a != '--gs']
    if args:
        src = args[0]
        objf = src.rsplit('.', 1)[0] + '.obj' if not os.path.exists(src + '.obj') else src + '.obj'
        print(src, check(src, objf, use_gs=use_gs))
        return
    import collections
    linker_tag = 'gslink' if use_gs else 'orca/m'
    cat = collections.Counter()
    prov = []
    for objf in sorted(glob.glob(ROOT + '/**/*.obj', recursive=True)):
        src = srcfor(objf)
        if not src:
            continue
        try:
            status, byte_id = check(src, objf, use_gs=use_gs)
        except Exception as e:
            status, byte_id = 'ERR:' + repr(e)[:30], False
        cat[status] += 1
        if status == 'LINK_IDENTICAL' and not byte_id:
            prov.append(os.path.relpath(src, ROOT))
    print(f"=== differential link results [{linker_tag}] ===")
    for k, c in cat.most_common():
        print(f"  {c:4d}  {k}")
    print(f"\nprovably-correct WITHOUT byte-identical obj ({len(prov)}):")
    for p in prov[:30]:
        print("   " + p)


if __name__ == '__main__':
    main()
