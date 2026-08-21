#!/usr/bin/env python3
"""rezforkcheck.py — rebuild eight small A.U.G/ToolBoxMisc resource forks
from their archived Rez sources, byte-exact, through the SAME clean-room
pipeline cdevcheck.py/findercheck.py already exercise: `gsasm.rez.parser`
+ `gen` + `emit`, with the clean-room `gsasm/rez/include/TypesIIGS.r`
providing every template (`RezIIGS: 1` predefined). The first five needed
no gsasm pipeline change; Frog/Whoosh added the `rSoundSample` template and
generalized rResName synthesis to one holder per named resource type (id
0x10000 | type); ADU added the `nonpurgeable` attribute keyword (purge-field
value 0x0000, the field's existing default made explicit — gsasm/rez/gen.py
ATTR_BITS) — see gsasm/rez/gen.py and tests/test_rez_gen.py.

    FindFile     — Desk Accessory (ToolBoxMisc/FindFileGS/Findfile.rez).
                   Ships as /SystemTools1/System/Desk.Accs/FindFile on
                   Disk 3.  Pure-Rez fork: no `read`/code resources.
    Apple.Bowl   — app (A.U.G/Apple.Bowl/Bowl.r).  Ships as
                   /Fonts/Goodies/Apple.Bowl on Disk 5.  rVersion/rIcon/
                   rBundle only — no code resources.
    MediaControl — NDA (A.U.G/MediaCtl/MediaCtlNDA/MediaCtlNDA.rii).
                   Ships as /SystemTools2/System/Desk.Accs/MediaControl
                   on Disk 4.  rVersion/rComment only.
    VideoMix     — NDA (A.U.G/VideoMix/VideoMix.NDA/VideoMixNDA.rii).
                   Ships as /SystemTools2/System/Desk.Accs/VideoMix on
                   Disk 4.  rVersion/rComment only.
    Pioneer4200  — Media.Control driver's RESOURCE fork
                   (A.U.G/MediaCtl/P4200/P4200.r; its DATA fork is already
                   proven byte-exact by work/appdatacheck.py).  Ships as
                   /SystemTools2/System/Drivers/Media.Control/Pioneer4200
                   on Disk 4.  A single rPstring — no code resources.
    Frog         — one named rSoundSample ($8024) Sound CDEV sample.  Ships
                   as /SystemTools2/System/Sounds/Frog on Disk 4.
    Whoosh       — two named rSoundSamples (forward "Whoosh" + reversed
                   "hsoohW"), the source's RezIIGS branch (`#ifdef MacStyle`
                   gates the Mac 'snd ' branch away).  Ships as
                   /SystemTools2/System/Sounds/Whoosh on Disk 4.  (The other
                   10 System Sounds use template-free `data` statements and
                   live in rezdatacheck.py.)
    Adv.Disk.Util — app (A.U.G/ADU/adu.rii).  Ships as
                   /SystemTools1/Adv.Disk.Util on Disk 3 (its DATA fork is
                   Pascal-built and stays a substitute — this is the
                   RESOURCE fork only).  One `read rSCSIDrvr` statement
                   pulls the 6,144-byte SCSI boot-block blob from the
                   CORPUS-LOCAL `A.U.G/ADU/mac.driver` file sitting right
                   next to the .rii — genuinely source-built, not
                   gold-fed (see READ_FILES below). 25 resources: rVersion/
                   rComment, the SCSI read + its rSCSIDescDrvr (custom
                   `reversebytes{longint;}` fields + a wide byte array —
                   both types declared right in adu.rii), one rWindParam1/
                   rControlList dialog, and 9 buttons' rControlTemplate/
                   rpString/rTextForLETextBox2.

None of the first seven sources declare a `read` resource, so — unlike
cdevcheck's rCDEVCode/rCodeResource extraction-feed — no golden bytes need
splicing in for them. `build_rez_fork` DETECTS any `kind == 'read'` entry
generically (matching cdevcheck's rCDEVCode/rCodeResource types plus any
other `read`): a `(type, id)` key listed in READ_FILES is read straight
from its corpus-local file (ADU's `mac.driver`); anything else falls back
to gold-feeding from the golden fork's raw resource data, so the harness
doesn't silently break if a future target needs the CDEV-style fallback.

Deliberately NOT wired into work/diskcheck.py (none of these eight files
are on the System Disk diskcheck walks) — standalone runner + the gate's
rezfork_bytes_exact metric source, same footing as cdevcheck/appdatacheck.

    python3 work/rezforkcheck.py            # summary over all 8 targets
    python3 work/rezforkcheck.py FindFile   # one target, verbose diff
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

D3 = f'{dc.DISKS}/Disk 3 of 7 SystemTools1.2mg'
D4 = f'{dc.DISKS}/Disk 4 of 7 SystemTools2.2mg'
D5 = f'{dc.DISKS}/Disk 5 of 7 Fonts.2mg'

# name -> (disk image, on-disk path, source path relative to SRC_ROOT)
REZMAP = {
    'FindFile': (
        D3, '/SystemTools1/System/Desk.Accs/FindFile',
        'ToolBoxMisc/FindFileGS/Findfile.rez'),
    'Apple.Bowl': (
        D5, '/Fonts/Goodies/Apple.Bowl',
        'A.U.G/Apple.Bowl/Bowl.r'),
    'MediaControl': (
        D4, '/SystemTools2/System/Desk.Accs/MediaControl',
        'A.U.G/MediaCtl/MediaCtlNDA/MediaCtlNDA.rii'),
    'VideoMix': (
        D4, '/SystemTools2/System/Desk.Accs/VideoMix',
        'A.U.G/VideoMix/VideoMix.NDA/VideoMixNDA.rii'),
    'Pioneer4200': (
        D4, '/SystemTools2/System/Drivers/Media.Control/Pioneer4200',
        'A.U.G/MediaCtl/P4200/P4200.r'),
    # Two Sound CDEV samples that use the rSoundSample ($8024) TEMPLATE
    # (the other 10 System Sounds ship as template-free `data` statements
    # and live in rezdatacheck.py).  Frog is one named rSoundSample; Whoosh
    # is two (forward "Whoosh" + reversed "hsoohW"), its source gated behind
    # `#ifdef MacStyle` so the RezIIGS branch compiles.  Each fork's
    # synthesized rResName ($8014) lands at id $00018024 = 0x10000 | $8024.
    'Frog': (
        D4, '/SystemTools2/System/Sounds/Frog',
        'A.U.G/CtlPanel/SoundCDEV/Sounds/Frog.r'),
    'Whoosh': (
        D4, '/SystemTools2/System/Sounds/Whoosh',
        'A.U.G/CtlPanel/SoundCDEV/Sounds/Whoosh.r'),
    'Adv.Disk.Util': (
        D3, '/SystemTools1/Adv.Disk.Util',
        'A.U.G/ADU/adu.rii'),
}

# {target: {(rtype, rid): path relative to SRC_ROOT}} — corpus-local `read`
# payloads to splice in verbatim (no Convert transform declared) instead of
# gold-feeding. adu.rii's `read rSCSIDrvr (0x00000001, preload,
# nonpurgeable) "mac.driver";` names the file but gen.generate()'s GenEntry
# deliberately drops read filenames (module docstring: the placeholder only
# preserves the (rtype, rid) key, "R6 packet's job" to supply the bytes) —
# rtype 0x4D61 = the .rii's `#define rSCSIDrvr $4D61`, id 1 from the header.
READ_FILES = {
    'Adv.Disk.Util': {(0x4D61, 1): 'A.U.G/ADU/mac.driver'},
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
    # Any `read` (kind == 'read') entry is opaque input Rez never
    # generates itself (see gen.to_emit_tuples' docstring). Prefer a
    # corpus-local file (READ_FILES) when this target names one — ADU's
    # `mac.driver` SCSI blob ships right in the source tree, so that's a
    # genuine source-built read, not a gold-feed. Anything else falls back
    # to gold-feeding from the golden fork's raw resource data by (type,
    # id), exactly as cdevcheck.py does for rCDEVCode/rCodeResource — kept
    # generic so the harness doesn't silently break if a future target
    # needs the fallback.
    read_keys = {(e.rtype, e.rid) for e in entries if e.kind == 'read'}
    corpus_files = READ_FILES.get(name, {})
    read_data = {}
    for key in read_keys:
        rel = corpus_files.get(key)
        if rel is not None:
            with open(os.path.join(SRC_ROOT, rel), 'rb') as f:
                read_data[key] = f.read()
    missing_types = {t for (t, i) in read_keys if (t, i) not in read_data}
    if missing_types:
        for e in gold.used:
            if e.type in missing_types and (e.type, e.id) not in read_data:
                read_data[(e.type, e.id)] = gold.raw[e.offset:e.offset + e.size]
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
        rep = rc.compare(gold.raw, built)
        for r in rep.get('resources', []):
            if r['status'] != 'match':
                print(f'  {r}')
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
            print(f'FAIL {name:12} {err}')
            continue
        b, g, ok = res
        if ok:
            good += 1
            good_bytes += g
            print(f'PASS {name:12} {g} bytes byte-exact (rsrc fork)')
        else:
            bad_bytes += g
            print(f'FAIL {name:12} built={b} gold={g} differs')
    print(f'\nrezforkcheck: {good}/{tot} resource forks byte-exact '
          f'REZFORK_BYTES_EXACT {good_bytes}/{good_bytes + bad_bytes}')
    # Nothing accepted: all 8 forks are byte-exact.  The fork count catches the
    # build-failure case, which adds no bad BYTES (see cdevcheck).
    return gate_result(rezfork_bytes_exact=bad_bytes,
                       rezfork_forks_not_exact=tot - good)


if __name__ == '__main__':
    sys.exit(main())
