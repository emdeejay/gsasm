"""Human-readable dump of an OMF v2 object/load file.

Used by the fixture suite to produce reviewable `expected.dump` files and
readable diffs on failure. The byte comparison is authoritative; the dump is
for humans. Output must be deterministic: same bytes in, same text out.
"""
import sys

sys.path.insert(0, __file__.rsplit('/', 2)[0])  # repo root, for `import gsasm`
from gsasm import omf


def _hx(b, limit=32):
    h = b[:limit].hex()
    out = ' '.join(h[i:i + 2] for i in range(0, len(h), 2))
    if len(b) > limit:
        out += f' ... (+{len(b) - limit} bytes)'
    return out


def _expr_str(e):
    parts = []
    for t in e:
        if t == 'end':
            break
        kind, val = t
        if kind == 'lit':
            parts.append(f'${val:X}' if isinstance(val, int) else repr(val))
        elif kind == 'op':
            parts.append(f'op{val}')
        else:
            parts.append(f'{kind}:{val}')
    return ' '.join(parts)


def dump(data):
    """Return the textual dump of every segment in `data`."""
    lines = []
    seg_count = 0
    for seg_count, seg in enumerate(omf.iter_segments(data), start=1):
        h = seg['hdr']
        seg_name = h['SEGNAME'].decode('mac_roman', 'replace')
        load = h['LOADNAME'].decode('mac_roman', 'replace').rstrip()
        lines.append(f'SEGMENT {seg_count}: {seg_name!r}')
        lines.append(f"  LOADNAME={load!r} LENGTH={h['LENGTH']} KIND=${h['KIND']:04X}"
                     f" ORG={h['ORG']} ALIGN={h['ALIGN']}"
                     f" LABLEN={h['LABLEN']} NUMLEN={h['NUMLEN']}"
                     f" BYTECNT={h['BYTECNT']}")
        for at, name, detail in seg['recs']:
            if name in ('CONST', 'LCONST'):
                lines.append(f'  +{at:05x} {name:9s} len={len(detail):<4d} {_hx(detail)}')
            elif name == 'DS':
                lines.append(f'  +{at:05x} DS        {detail} zero bytes')
            elif name in ('RELOC', 'cRELOC'):
                size, shift, o, ref = detail
                lines.append(f'  +{at:05x} {name:9s} size={size} shift={shift}'
                             f' off=${o:x} ref=${ref:x}')
            elif name in ('INTERSEG', 'cINTERSEG'):
                size, shift, o, fileno, sn, so = detail
                lines.append(f'  +{at:05x} {name:9s} size={size} shift={shift}'
                             f' off=${o:x} file={fileno} seg={sn} segoff=${so:x}')
            elif name in ('EXPR', 'ZEXPR', 'BEXPR', 'LEXPR'):
                size, e = detail
                lines.append(f'  +{at:05x} {name:9s} size={size} [{_expr_str(e)}]')
            elif name == 'RELEXPR':
                size, origin, e = detail
                lines.append(f'  +{at:05x} RELEXPR   size={size} origin=${origin:x}'
                             f' [{_expr_str(e)}]')
            elif name in ('GLOBAL', 'GEQU', 'LOCAL', 'EQU', 'ENTRY'):
                d = dict(detail)
                extra = ''
                if 'expr' in d:
                    extra = f" expr=[{_expr_str(d['expr'])}]"
                lines.append(f"  +{at:05x} {name:9s} {d['label']!r} len={d['len']}"
                             f" type={d['type']} priv={d['priv']}{extra}")
            elif name in ('ORG', 'ALIGN'):
                lines.append(f'  +{at:05x} {name:9s} {detail}')
            elif name == 'END':
                lines.append(f'  +{at:05x} END')
            else:
                lines.append(f'  +{at:05x} {name} {detail!r}')
    lines.append(f'TOTAL {len(data)} bytes, {seg_count} segment(s)')
    return '\n'.join(lines) + '\n'


if __name__ == '__main__':
    with open(sys.argv[1], 'rb') as fh:
        sys.stdout.write(dump(fh.read()))
