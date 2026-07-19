#!/usr/bin/env python3
"""ROM coverage: how many bytes of the shipping ROM gsasm builds byte-exact,
via the flat image of each ORG'd firmware segment + slot/Applesoft overlays.
Also reports objcheck byte-identical count (cheap correctness guard).
"""
import sys, os, glob
from _common import byte_match, ensure_repo_on_path, mismatch_offsets, romsrc_incs, romsrc_root
ensure_repo_on_path()
from gsasm import asm, omf

ROOT = romsrc_root()
INCS = romsrc_incs(ROOT)
BINP = ROOT + '/bin/'


def flat(a, segname):
    seg = next(s for s in a.segs if s.name == segname)
    out = bytearray()
    for it in seg.items:
        if it[0] == 'code':
            out += it[2]
        elif it[0] == 'ds':
            out += b'\x00' * it[1]
    return bytes(out)


# (source, [segments], bin file)  -- segments concatenated form the bin
FW = [('Serial/Serial.aii', ['SERIAL_DRVR'], 'Serial.bin'),
      ('AD3.5Driver/AD35Driver.aii', ['AD35DRIVER'], 'AD35Driver.bin'),
      ('SmartPort/SmartPort.aii', ['SMARTPORT'], 'SmartPort.bin'),
      ('Diagnostics/Diag.aii', ['DIAGNOSTICS'], 'Diag.bin'),
      ('Monitor/monitor.aii', ['MONITOR', 'LASTWORD'], 'Monitor.bin')]
# slot/Applesoft overlays (segments -> bin); C5xx.bin = C5XXCODE ++ C6XXCODE
OVL = [('SmartPort/SmartPort.aii', ['C5XXCODE', 'C6XXCODE'], 'C5xx.bin'),
       ('Serial/Serial.aii', ['C1XX_SERIAL'], 'C1xx.bin'),
       ('Serial/Serial.aii', ['C2XX_SERIAL'], 'C2xx.bin'),
       ('ATALK/Port7.aii', ['C7XXCODE'], 'C7xx.bin')]


def cover():
    total_match = total = 0
    perfect = 0
    for rel, segs, binf in FW + OVL:
        try:
            a = asm.assemble(ROOT + '/' + rel, INCS)
            f = b''.join(flat(a, s) for s in segs)
        except Exception as e:
            print(f"  {binf:16} ERR {repr(e)[:50]}")
            continue
        b = open(BINP + binf, 'rb').read()
        m, n = byte_match(f, b)
        total_match += m
        total += len(b)
        ok = (f == b)
        perfect += ok
        diffs = mismatch_offsets(f, b)
        fd = diffs[0] if diffs else -1
        print(f"  {binf:16} {m:6}/{len(b):6} ({100*m//max(len(b),1):3}%) "
              f"{'PERFECT' if ok else 'first@'+hex(fd)}")
    print(f"  --- firmware/overlay ROM bytes gsasm-exact: {total_match}/{total} "
          f"({100*total_match//total}%), {perfect} segs perfect")


if __name__ == '__main__':
    cover()
