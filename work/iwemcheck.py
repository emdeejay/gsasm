#!/usr/bin/env python3
"""iwemcheck.py — the Disk 4 IWEM driver (ImageWriter Emulator PostScript
prolog), rebuilt byte-exact by replaying the MPW build script.

`/SystemTools2/System/Drivers/IWEM` (29,185 B, file type $04 ASCII) is NOT
assembled 65816 code: it is the ImageWriter-Emulator PostScript proc set,
produced from `GSToolbox/PrinterDrivers/IWEm/IWEm.Src` by the checked-in MPW
shell script `BuildIWEm` (Ver 1.5, Feb-1992) — a text "squeeze" pipeline of
MPW editor Replace commands (strip %-comments, collapse whitespace, drop
spaces/CRs around PostScript delimiters) plus three inserted identifiers
(the `%!PS-Adobe-2.0` header, a `%%Begin ExitServer` marker after the first
`setfont`, and an `%%End ExitServer`/`%%EndProcSet` footer).

`build_iwem_disk4()` below replays that pipeline verbatim (rules transcribed
in the script's order; Loop-wrapped rules run to fixed point; newline is CR).
Result: byte-exact 29,185/29,185 first try (2026-08-01).

History note: the census had this file as `no-source-substitute` with a
VERIFY-NEGATIVE claim ("diverges after 78 bytes ... the matching IWEm.Src
version is not present").  That was WRONG — the earlier attempt compared the
golden against the tree's PREBUILT `IWEm` artifact (28,523 B, the stripped
variant that also ships as Disk 7's `/IWEm`, proven by disk7check), not
against a replay of `BuildIWEm`.  The shipped Disk-4 file is
`prebuilt[:78] + 662-byte version-guard/ExitServer block + prebuilt[78:]`,
and that guard block sits UNCOMMENTED in the current IWEm.Src — BuildIWEm
keeps it; the prebuilt artifact predates it or was built with the section
elided.  One source, both variants accounted for.

Gate line: `IWEM_BYTES_EXACT good/total`; exit status is 0 only when fully
exact (gate.py treats nonzero exits as hard failures).
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import ROOT, ensure_a2til_on_path, ensure_repo_on_path  # noqa: E402
ensure_repo_on_path()

SRC = os.path.join(ROOT, 'ref', 'GSOS_6', 'IIGS.601.SRC', 'GSToolbox',
                   'PrinterDrivers', 'IWEm', 'IWEm.Src')
DISK4 = os.path.join(ROOT, 'ref', 'GSOS_6', 'System601_disks',
                     'System 6.0.1', 'Disk 4 of 7 SystemTools2.2mg')
GOLD_PATH = '/SystemTools2/System/Drivers/IWEM'


def build_iwem_disk4():
    """Replay BuildIWEm (MPW Ver 1.5) over IWEm.Src; return the file bytes."""
    t = open(SRC, 'rb').read()

    # step 8: remove comments — ONE pass (not Loop-wrapped in the script),
    # all occurrences: `%≈∂n` (percent through end-of-line, CR included) -> " "
    t = re.sub(rb'%[^\r]*\r', b' ', t)

    def loop(pat, rep):
        """A `Loop ... Replace -c ∞ ... End` pair: replace-all to fixed point."""
        nonlocal t
        while True:
            new = t.replace(pat, rep)
            if new == t:
                return
            t = new

    loop(b'\t', b' ')          # 7: tabs -> spaces
    loop(b'  ', b' ')          # 6: duplicate spaces
    loop(b'\r ', b' ')         # 5: CR+space -> space, then space+CR -> CR
    loop(b' \r', b'\r')
    for pat, rep in [          # 4: spaces next to special characters
        (b' (', b'('), (b') ', b')'),
        (b' <', b'<'), (b'< ', b'<'),
        (b' >', b'>'), (b'> ', b'>'),
        (b' [', b'['), (b'[ ', b'['),
        (b' ]', b']'), (b'] ', b']'),
        (b' {', b'{'), (b'{ ', b'{'),
        (b' }', b'}'), (b'} ', b'}'),
        (b' /', b'/'),         # (the `/ `-after-slash rule is commented out)
    ]:
        loop(pat, rep)
    for pat, rep in [          # 3: CRs next to special characters
        (b')\r', b')'), (b'\r)', b')'),
        (b'\r(', b'('),
        (b'>\r', b'>'), (b'\r>', b'>'),
        (b'<\r', b'<'), (b'\r<', b'<'),
        (b'[\r', b'['), (b'\r[', b'['),
        (b']\r', b']'), (b'\r]', b']'),
        (b'}\r', b'}'), (b'\r}', b'}'),
        (b'{\r', b'{'), (b'\r{', b'{'),
    ]:
        loop(pat, rep)
    loop(b'\r\r', b'\r')       # 2: duplicate CRs

    # step 1: insert PostScript identifiers (find • / first match / find ∞)
    t = b'%!PS-Adobe-2.0\r%%BeginProcSet "IWEM"\r' + t
    t = t.replace(b'setfont ', b'setfont\r%%Begin ExitServer\r', 1)
    t = t + b'\r\r%%End ExitServer\r%%EndProcSet \r'
    return t


def golden():
    ensure_a2til_on_path('iwemcheck')
    from a2til.prodos import Volume
    return Volume(open(DISK4, 'rb').read()).read_file(GOLD_PATH)


def run():
    gold = golden()
    built = build_iwem_disk4()
    total = len(gold)
    good = total if built == gold else sum(
        1 for a, b in zip(built, gold) if a == b)
    if built != gold:
        n = min(len(built), len(gold))
        fd = next((i for i in range(n) if built[i] != gold[i]), n)
        print(f'  DIFF: built {len(built)}B vs gold {total}B, '
              f'first diff at {fd:#x}')
    print(f'IWEM_BYTES_EXACT {good}/{total}')
    return good, total


if __name__ == '__main__':
    good, total = run()
    sys.exit(0 if good == total else 1)
