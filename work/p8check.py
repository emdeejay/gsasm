"""work/p8check.py — P8 (ProDOS-8 compatibility file) byte-exactness gate.

Builds the full 17128-byte /System.Disk/System/P8 from GS.OS/P8/MliSrc.aii plus
the P8.Drivers via the OverlayIIgs recipe in GS.OS/MakeFiles/make.p8 (see
work/diskbuilders/p8_driver.py) and compares it byte-for-byte to the golden P8
extracted from the shipping GS/OS 6 disk (ref/GSOS_6/os_bin/P8#FF0000).

This is a CLEAN acceptance gate: the builder raises on any reached assembler
error and on a wrong output size, so a green result means the whole P8 — all four
MLI PROC segments (linked at $2000/$BF00/$DE00/$FF9B) and every overlaid driver
(cclock, tclock, ram1/2/3, sel, sel.alt, xrwtot, quitcode) — assembled, linked,
and packaged to the exact shipping bytes with no waived residual.

Output line (parsed by work/gate.py):
    P8 raw code-image match: <m>/<n> (<pct>%)

Exit status: 0 iff byte-exact (m == n == 17128), else 1.

Usage:
    python3 work/p8check.py [--diff]
"""
import os
import sys

from _common import (
    ROOT,
    byte_match_against_golden_len,
    ensure_repo_on_path,
    mismatch_offsets,
)
ensure_repo_on_path()

from diskbuilders import p8_driver  # noqa: E402

_GOLD = os.path.join(ROOT, 'ref/GSOS_6/os_bin/P8#FF0000')


def build_and_compare(show_diff=False):
    """Return (match, total). Prints the gate line and (optionally) the diffs."""
    if not os.path.exists(_GOLD):
        print(f'golden P8 not found: {_GOLD}', file=sys.stderr)
        print('P8 raw code-image match: 0/0 (0%)')
        return 0, 0

    gold = open(_GOLD, 'rb').read()
    built = p8_driver._build_p8()          # raises on assembler error / bad size

    m, n = byte_match_against_golden_len(built, gold)
    if len(built) != n:
        print(f'SIZE MISMATCH: built {len(built)} vs golden {n}', file=sys.stderr)

    print(f'P8 raw code-image match: {m}/{n} ({100 * m // n if n else 0}%)')

    if show_diff and m != n:
        shown = 0
        for i in mismatch_offsets(built, gold):
            print(f'  first diff @ {i:#06x}: gsasm={built[i]:02x} gold={gold[i]:02x}')
            print(f'    gsasm {bytes(built[max(0, i - 4):i + 8]).hex()}')
            print(f'    gold  {gold[max(0, i - 4):i + 8].hex()}')
            shown += 1
            if shown >= 8:
                break
    return m, n


def main():
    show_diff = '--diff' in sys.argv[1:]
    m, n = build_and_compare(show_diff=show_diff)
    return 0 if (n and m == n) else 1


if __name__ == '__main__':
    sys.exit(main())
