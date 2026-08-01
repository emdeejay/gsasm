#!/usr/bin/env python3
"""The `nonpurgeable` resource attribute keyword (Rez dialect).

Golden evidence: A.U.G/ADU/adu.rii's
`read rSCSIDrvr (0x00000001, preload, nonpurgeable) "mac.driver";` — the
shipped Adv.Disk.Util resource fork carries attr word $0040 (preload only)
for that resource, so `nonpurgeable` must be RECOGNIZED (not an unknown-
attribute error) and must contribute 0x0000: it names the explicit all-zero
value of the same 2-bit purge field purgeable1-3 occupy (gsasm/rez/gen.py
ATTR_BITS).  Corpus-free guard for the 2026-08-01 ADU dialect discovery —
without it, reverting the keyword would only surface in the golden-corpus
rezforkcheck, which a corpus-free regression pass never runs.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gsasm.rez import gen  # noqa: E402


def run():
    ok = True
    bits = gen.ATTR_BITS
    if 'nonpurgeable' not in bits:
        print('FAIL: nonpurgeable missing from ATTR_BITS (unknown-attribute '
              'regression: adu.rii would no longer parse)')
        ok = False
    elif bits['nonpurgeable'] != 0x0000:
        print(f'FAIL: nonpurgeable contributes {bits["nonpurgeable"]:#06x}, '
              f'expected 0x0000 (explicit purge-level-0; golden ADU attr '
              f'word is $0040 = preload alone)')
        ok = False
    else:
        # combined with preload the attr word must equal preload's bit alone
        combined = bits['nonpurgeable'] | bits['preload']
        if combined != bits['preload']:
            print(f'FAIL: preload|nonpurgeable = {combined:#06x}, expected '
                  f'{bits["preload"]:#06x} (golden $0040)')
            ok = False
    print(f'{1 if ok else 0}/1 passed')
    return ok


if __name__ == '__main__':
    sys.exit(0 if run() else 1)
