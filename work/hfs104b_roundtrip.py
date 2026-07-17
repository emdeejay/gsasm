#!/usr/bin/env python3
"""hfs104b_roundtrip.py — prove the recovered 1.04b patch by reproduction.

The subtraction (work/hfs104b_analysis.py) *isolates* the 1.04b changes.  This
script *proves* them: it applies the three recovered edits to the 6.0.1 HFS.FST
source, reassembles + relinks + re-ExpressLoads with gsasm, and byte-compares
the resulting code image against the real 1.04b binary.

If the recovered patch is exactly right, the rebuilt image is byte-identical to
1.04b — the same standard by which gsasm reproduces the 6.0.1 original.

Run:  python3 work/hfs104b_roundtrip.py
"""
import sys, os, shutil, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from gsasm import asm, omf, linkiigs
from gsasm.expressload import de_express

SRC  = 'ref/GSOS_6/IIGS.601.SRC'
GSOS = SRC + '/GS.OS'
CMN  = GSOS + '/Common'
HFS  = GSOS + '/FSTs/HFS'
INCS = [CMN] + [d for d, _, _ in os.walk(GSOS)] + ['work/includes']
TARGET = 'tmp/hfs104b/hfs.1.04b.fst#BD0000'


def read_cr(path):
    """Read a CR-terminated 1994 source file as a list of lines."""
    return open(path, 'rb').read().decode('iso-8859-1').split('\r')


def write_cr(path, lines):
    open(path, 'wb').write('\r'.join(lines).encode('iso-8859-1'))


def patch_main(lines):
    """Version string + WORD_MULTIPLY carry-bug deletion."""
    # 1a. numeric version field in the FST header:  $0101 -> $0104
    v = next(k for k, l in enumerate(lines)
             if l == '\t\tDC.W\t$0101\t\t\t;Version 1.01 final')
    lines[v] = '\t\tDC.W\t$0104\t\t\t;Version 1.04 beta'

    # 1b. version string  v01.01 -> v01.04 Beta (same 28-char length)
    i = next(k for k, l in enumerate(lines)
             if l.startswith('start_comment') and 'v01.01' in l)
    lines[i] = lines[i].replace("'HFS FST               v01.01'",
                                "'HFS FST          v01.04 Beta'")
    assert 'v01.04 Beta' in lines[i]

    # 2. delete the stray  bcc align / inc a  in the 16x16 multiply loop
    j = next(k for k, l in enumerate(lines)
             if l == '\t\tbcc\talign\t\t\t;branch if no overflow')
    assert lines[j + 1] == '\t\tinc\ta\t\t\t;add in carry bit', repr(lines[j + 1])
    del lines[j:j + 2]
    return lines


def patch_btree(lines):
    """ET_LOG_2_PHYS @ok: stop folding the uninitialized high word of d1 into
    the extent pointer; add the beta carry trap."""
    # find the @ok block:  sta <a1 ; lda <a1+2 ; adc |d1+2
    for k, l in enumerate(lines):
        if l == '\t\t\tsta  <a1' and lines[k + 1] == '\t\t\tlda  <a1+2' \
                and lines[k + 2] == '\t\t\tadc  |d1+2':
            break
    else:
        raise SystemExit('@ok block not found')
    # sta <a1
    # bcc @hiw            <-- inserted
    # brk $69             <-- inserted
    # @hiw lda <a1+2      (label added)
    # adc #0              <-- was: adc |d1+2
    # sta <a1+2
    lines[k + 1:k + 3] = [
        '\t\t\tbcc  @hiw',
        '\t\t\tbrk  $69',
        '@hiw\t\tlda  <a1+2',
        '\t\t\tadc  #0',
    ]
    return lines


def build(hfs_dir):
    objects = []
    for src in ('hfs.fst.main', 'hfs.fst.btree'):
        a = asm.assemble(f'{hfs_dir}/{src}', [hfs_dir] + INCS,
                         defines={'DEBUGSYMBOLS': 0})
        objects.append((omf.emit(a), a))
    result = linkiigs.link(objects, opts={'merge': True})
    img = bytearray()
    off = 0
    while off < len(result):
        h = omf.parse_header(result[off:])
        bc = h['BYTECNT']
        if bc == 0:
            break
        recs, _ = omf.parse_records(result[off:off + bc], h['DISPDATA'],
                                    h.get('NUMLEN', 4), h.get('LABLEN', 0))
        img += b''.join(r[2] for r in recs if r[1] in ('CONST', 'LCONST'))
        off += bc
    return bytes(img)


def main():
    tmp = tempfile.mkdtemp(prefix='hfs104b_')
    try:
        dst = os.path.join(tmp, 'HFS')
        shutil.copytree(HFS, dst)
        write_cr(f'{dst}/hfs.fst.main',  patch_main(read_cr(f'{dst}/hfs.fst.main')))
        write_cr(f'{dst}/hfs.fst.btree', patch_btree(read_cr(f'{dst}/hfs.fst.btree')))
        rebuilt = build(dst)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    target = de_express(TARGET)
    print(f'rebuilt (patched 6.0.1 source) : {len(rebuilt)} bytes')
    print(f'real 1.04b binary (de-express) : {len(target)} bytes')
    if rebuilt == target:
        print('\n  *** BYTE-EXACT — recovered patch reproduces 1.04b ***')
        return 0
    diffs = [(i, rebuilt[i], target[i])
             for i in range(min(len(rebuilt), len(target)))
             if rebuilt[i] != target[i]]
    print(f'\n  NOT byte-exact: {len(diffs)} differing bytes, '
          f'len delta {len(rebuilt) - len(target):+d}')
    for pos, a, b in diffs[:12]:
        print(f'    @ {pos:#06x}: rebuilt={a:02x} target={b:02x}')
    return 1


if __name__ == '__main__':
    sys.exit(main())
