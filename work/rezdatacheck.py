#!/usr/bin/env python3
"""rezdatacheck.py — rebuild the template-free `data`-statement resource
forks byte-exact through the clean-room Rez pipeline
(`gsasm.rez.parser` + `gen` + `emit`), the SAME pipeline
rezforkcheck.py/cdevcheck.py/teachcheck.py exercise.

These 14 forks are built ENTIRELY from `data <typeID> (<id>[, <attrs>]) {
$"hex..." }` statements — a resource whose brace body is raw hex emitted
VERBATIM, with no type template consulted (exactly what MPW `DeRezIIgs`
emits and what `data` compiles straight back to).  Adding that one
statement to the parser/gen (this packet, R1) is what makes all 14
buildable; before it they were manifest substitutes (golden-carried).

    10 System Sounds  — /SystemTools2/System/Sounds/{Ahh,Doorbell,Droplet,
                        Eastern,PipeOrgan,Quack,SimpleBeep,Sosumi,Swish,
                        Trumpets} on Disk 4.  Each fork is two `data`
                        statements: a leading `data $8014(...)` rResName
                        (name-holder) plus a `data $8024(...)` sampled-sound
                        resource.  Source: A.U.G/CtlPanel/SoundCDEV/Sounds/*.r
    3 TeachText docs  — /SystemTools2/{Read.Me,Shortcuts,Whats.New} on
                        Disk 4.  Two `data` statements: a `data 0x7001(...)`
                        TE record + a `data rStyleBlock(...)` style block.
                        Source: ToolBoxMisc/ReadMeFiles/*.r
    1 Fonts Read.Me   — /Fonts/Goodies/Read.Me on Disk 5.  Same two-statement
                        TeachText shape.  Source: A.U.G/Apple.Bowl/Read.Me.r

Two facts these forks pinned down (both now handled by the shared library,
not this harness):
  * Data-region ordering: the rResName-type ($8014) resource is laid out
    LAST in the data region even when it is the FIRST `data` statement in
    source (every Sound puts $8014 first in source, last on disk) — see
    `gen.to_emit_tuples`.
  * Memo FInfo tail + post-tail field: these host-side File-Manager metadata
    bytes (zero in the 9 RezIIgs forks first decoded) carry real values
    here — now settable `finfo_tail`/`memo_tail2` in `gsasm.rez.emit`,
    recovered from the golden fork by `rezemitcheck._meta_from_golden`
    (pure decode; nothing in the .r source dictates them).

Deliberately NOT wired into work/diskcheck.py: the Fonts Read.Me is on
Disk 5, the others on Disk 4 (not the System Disk diskcheck walks).
Standalone runner + the gate's rez_data_bytes_exact metric source, same
footing as rezforkcheck/cdevcheck/teachcheck.

    python3 work/rezdatacheck.py            # summary over all 14 targets
    python3 work/rezdatacheck.py Ahh        # one target, verbose diff
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import ensure_repo_on_path, gate_result
ensure_repo_on_path()

import rezcheck as rc
import diskcheck as dc
import rezemitcheck as rec
from gsasm.rez import parser, gen, emit

INC = ['gsasm/rez/include']
SRC_ROOT = 'ref/GSOS_6/IIGS.601.SRC'

D4 = f'{dc.DISKS}/Disk 4 of 7 SystemTools2.2mg'
D5 = f'{dc.DISKS}/Disk 5 of 7 Fonts.2mg'

_SND = 'A.U.G/CtlPanel/SoundCDEV/Sounds'

# name -> (disk image, on-disk path, source path relative to SRC_ROOT).
# Sound on-disk names differ in case from a couple of source filenames
# (on-disk "Doorbell" vs source "DoorBell.r"), so both are spelled out.
REZMAP = {
    'Ahh':        (D4, '/SystemTools2/System/Sounds/Ahh',        f'{_SND}/Ahh.r'),
    'Doorbell':   (D4, '/SystemTools2/System/Sounds/Doorbell',   f'{_SND}/DoorBell.r'),
    'Droplet':    (D4, '/SystemTools2/System/Sounds/Droplet',    f'{_SND}/Droplet.r'),
    'Eastern':    (D4, '/SystemTools2/System/Sounds/Eastern',    f'{_SND}/Eastern.r'),
    'PipeOrgan':  (D4, '/SystemTools2/System/Sounds/PipeOrgan',  f'{_SND}/PipeOrgan.r'),
    'Quack':      (D4, '/SystemTools2/System/Sounds/Quack',      f'{_SND}/Quack.r'),
    'SimpleBeep': (D4, '/SystemTools2/System/Sounds/SimpleBeep', f'{_SND}/SimpleBeep.r'),
    'Sosumi':     (D4, '/SystemTools2/System/Sounds/Sosumi',     f'{_SND}/Sosumi.r'),
    'Swish':      (D4, '/SystemTools2/System/Sounds/Swish',      f'{_SND}/Swish.r'),
    'Trumpets':   (D4, '/SystemTools2/System/Sounds/Trumpets',   f'{_SND}/Trumpets.r'),
    'Read.Me':    (D4, '/SystemTools2/Read.Me',   'ToolBoxMisc/ReadMeFiles/Read.Me.r'),
    'Shortcuts':  (D4, '/SystemTools2/Shortcuts', 'ToolBoxMisc/ReadMeFiles/Shortcuts.r'),
    'Whats.New':  (D4, '/SystemTools2/Whats.New', 'ToolBoxMisc/ReadMeFiles/Whats.New.r'),
    'Fonts.Read.Me': (D5, '/Fonts/Goodies/Read.Me', 'A.U.G/Apple.Bowl/Read.Me.r'),
}


def golden(name):
    disk, path, _src = REZMAP[name]
    return rc.golden_fork(path, disk)


def build_rez_fork(name):
    """Build one target's full resource fork; returns bytes."""
    gold = golden(name)
    src = os.path.join(SRC_ROOT, REZMAP[name][2])
    stmts = parser.parse(src, include_dirs=INC, predefined={'RezIIGS': 1})
    entries = gen.generate(stmts)
    # None of the 14 sources declare a `read`; keep the gold-feed generic
    # anyway (mirrors rezforkcheck) so a future target that does won't break.
    read_types = {e.rtype for e in entries if e.kind == 'read'}
    read_data = {(e.type, e.id): gold.raw[e.offset:e.offset + e.size]
                 for e in gold.used if e.type in read_types}
    tuples = gen.to_emit_tuples(entries, read_data)
    meta = rec._meta_from_golden(gold)
    return emit.emit_fork(tuples, meta)


def check(name, verbose=False):
    gold = golden(name)
    try:
        built = build_rez_fork(name)
    except Exception as e:                                   # noqa: BLE001
        return name, None, f'{type(e).__name__}: {e}'
    ok = built == gold.raw
    if verbose and not ok:
        n = min(len(built), len(gold.raw))
        for i in range(n):
            if built[i] != gold.raw[i]:
                print(f'  first diff at {i}: built={built[i]:#04x} '
                      f'gold={gold.raw[i]:#04x} '
                      f'(data_start={140 + (gold.header.mapsize or 0)})')
                break
        if len(built) != len(gold.raw):
            print(f'  length differs: built={len(built)} gold={len(gold.raw)}')
    return name, (len(built), len(gold.raw), ok), None


def main():
    if len(sys.argv) > 1:
        want = sys.argv[1]
        name, res, err = check(want, verbose=True)
        if err:
            print(f'{name}: {err}')
        else:
            b, g, ok = res
            print(f'{name}: built={b} gold={g} '
                  f'{"BYTE-EXACT" if ok else "DIFFERS"}')
        return
    tot = good = 0
    good_bytes = bad_bytes = 0
    for name in sorted(REZMAP):
        _, res, err = check(name)
        tot += 1
        if err:
            print(f'FAIL {name:14} {err}')
            continue
        b, g, ok = res
        if ok:
            good += 1
            good_bytes += g
            print(f'PASS {name:14} {g} bytes byte-exact (rsrc fork)')
        else:
            bad_bytes += g
            print(f'FAIL {name:14} built={b} gold={g} differs')
    print(f'\nrezdatacheck: {good}/{tot} resource forks byte-exact '
          f'REZ_DATA_BYTES_EXACT {good_bytes}/{good_bytes + bad_bytes}')
    # Nothing accepted: all 14 forks are byte-exact.  The fork count catches the
    # build-failure case, which adds no bad BYTES (see cdevcheck).
    return gate_result(rez_data_bytes_exact=bad_bytes,
                       rez_data_forks_not_exact=tot - good)


if __name__ == '__main__':
    sys.exit(main())
