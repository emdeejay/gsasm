#!/usr/bin/env python3
"""mountimagecheck.py — rebuild the MountImageGS NDA data fork from source.

MountImage never shipped on the seven 6.0.1 disks (checked 1-7 + the
French/German sets), and the archive preserved no resource-fork sidecar
for the built binary — so `MountImage.r` has NO byte oracle and stays a
non-target (house rule).  What DID survive is the built binary's DATA
fork: `MountImageGS` in the source directory, a 5,750-byte ExpressLoad'd
NDA whose `MountImageGS.makeout` records the real 30-Apr-93 build
(`AsmIIGS MountImage.aii` + `LinkIIGS -t NDA`).  That is a full assembler
oracle, wired here like the drivers' captured-timestamp builds.

Two per-build facts are required for byte-exactness (both recorded in the
golden bytes themselves):
  - sysdate/systime '30-Apr-93' / '18:33:59' (embedded version string);
  - `super_classes=SUPER_CLASSES_APR93`: the Apr-93 LinkIIGS's integrated
    ExpressLoad encoder folds only the (2,0) low-word reloc class into
    SUPER records — its size-4 and bank-byte relocs are standalone $F5
    cRELOCs (see gsasm/expressload.py's SUPER_CLASSES_APR93 comment; an
    attempted content-based rule was falsified by EasyMount's golden).

    python3 work/mountimagecheck.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import ensure_repo_on_path
ensure_repo_on_path()

import easymountcheck as em
from gsasm import asm, omf
from gsasm.expressload import expressload, SUPER_CLASSES_APR93

SRC = 'ref/GSOS_6/IIGS.601.SRC/MountImageGS/MountImage.aii'
GOLD = 'ref/GSOS_6/IIGS.601.SRC/MountImageGS/MountImageGS'
BUILD_DATE, BUILD_TIME = '30-Apr-93', '18:33:59'


def build_mountimage_data() -> bytes:
    a = asm.assemble(SRC, em.ASM_INCS, defines={},
                     sysdate=BUILD_DATE, systime=BUILD_TIME)
    if a.errors:
        raise RuntimeError(f'MountImage.aii: {len(a.errors)} assembly '
                           f'errors; first: {a.errors[0]}')
    return expressload([(omf.emit(a), a)],
                       opts={'super_classes': SUPER_CLASSES_APR93})


def main():
    gold = open(GOLD, 'rb').read()
    try:
        built = build_mountimage_data()
    except Exception as e:                                   # noqa: BLE001
        print(f'FAIL build: {type(e).__name__}: {e}')
        sys.exit(1)
    if built == gold:
        print(f'PASS MountImageGS {len(gold)} bytes byte-exact (data fork)')
        good, bad = len(gold), 0
    else:
        n = min(len(built), len(gold))
        d = next((i for i in range(n) if built[i] != gold[i]), n)
        print(f'FAIL MountImageGS built={len(built)} gold={len(gold)} '
              f'first diff at {d:#x}')
        good, bad = 0, len(gold)
    print(f'\nmountimagecheck: MOUNTIMAGE_DATA_BYTES_EXACT {good}/{good + bad}')


if __name__ == '__main__':
    main()
