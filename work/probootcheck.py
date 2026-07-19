#!/usr/bin/env python3
"""probootcheck.py — M3 acceptance harness for ProBoot / prodos.

Reproduces the MPW build recipe from GS.OS/MakeFiles/make.proboot:

    asmiigs {GSOSboot}proboot.src -o proboot.obj
    linkiigs proboot.obj -o proboot.lnk          (not needed: makebin works on OBJ)
    makebiniigs -org $2000 proboot.lnk -o prodos
    setfile prodos -t PSYS

Validates the byte-for-byte match of the resulting flat image against the
golden 'prodos' (ProDOS filetype PSYS) extracted from the GS/OS 6.0.1 System
Disk.

Usage:
    python3 work/probootcheck.py          # full report
    python3 work/probootcheck.py --diff   # also dump first-diff context

Expected result: 1668/1668 bytes identical.  The former 2-byte
getfstname-jump_table segment-head difference is closed and this harness keeps
it gated.

Golden extraction (run once, idempotent):
    cadius EXTRACTFILE \\
        "ref/GSOS_6/System601_disks/System 6.0.1/Disk 2 of 7 System Disk.2mg" \\
        "/System.Disk/ProDOS" ref/GSOS_6/os_bin/
"""
import sys
import os

from _common import (
    byte_match,
    ensure_repo_on_path,
    gsos_source_root,
    gsos_tree_incs,
    mismatch_offsets,
)
ensure_repo_on_path()

from gsasm import asm, omf, makebin

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

SRC  = gsos_source_root()
GS   = os.path.join(SRC, 'GS.OS')
BOOT = os.path.join(GS, 'Boot', 'ProBoot.src')
DISK = ('ref/GSOS_6/System601_disks/System 6.0.1/'
        'Disk 2 of 7 System Disk.2mg')
GOLDEN_DIR = 'ref/GSOS_6/os_bin'
GOLDEN     = GOLDEN_DIR + '/ProDOS#FF0000'
ORG        = 0x2000


# ---------------------------------------------------------------------------
# Golden extraction
# ---------------------------------------------------------------------------

def ensure_golden() -> bool:
    """Extract the golden 'prodos' from the System Disk if not already done.

    Returns True if the golden binary is available, False on failure.
    """
    if os.path.exists(GOLDEN):
        return True
    if not os.path.exists(DISK):
        print(f'ERROR: disk image not found: {DISK}', file=sys.stderr)
        return False
    os.makedirs(GOLDEN_DIR, exist_ok=True)
    rc = os.system(
        f'cadius EXTRACTFILE "{DISK}" "/System.Disk/ProDOS" "{GOLDEN_DIR}/"'
    )
    return rc == 0 and os.path.exists(GOLDEN)


# ---------------------------------------------------------------------------
# Build step
# ---------------------------------------------------------------------------

def build_prodos() -> bytes:
    """Assemble ProBoot.src and flatten to a raw image at org=$2000.

    Recipe mirrors make.proboot:
      asmiigs ProBoot.src
      makebiniigs -org $2000 proboot.obj
    """
    # Include paths: every subdirectory of the GS.OS source tree.
    incs = gsos_tree_incs(SRC)

    # Step 1: assemble
    a = asm.assemble(BOOT, incs)
    if a.errors:
        raise RuntimeError(f'Assembly errors: {a.errors}')

    # Step 2: emit OMF object
    obj = omf.emit(a)

    # Step 3: makebin at org=$2000
    return makebin.makebin(obj, ORG)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(show_diff: bool = False) -> int:
    if not ensure_golden():
        print('Cannot locate or extract golden binary — aborting.', file=sys.stderr)
        return 1

    golden = open(GOLDEN, 'rb').read()

    try:
        mine = build_prodos()
    except Exception as exc:
        print(f'Build failed: {exc}', file=sys.stderr)
        raise

    m, n = byte_match(mine, golden)
    pct = (100 * m // n) if n else 0

    print(f'prodos: gsasm={len(mine)} golden={len(golden)} '
          f'match {m}/{n} ({pct}%)  org=${ORG:04X}')

    if m < n and show_diff:
        diffs = mismatch_offsets(mine, golden)
        print(f'  {len(diffs)} mismatched byte(s):')
        for pos in diffs[:20]:
            print(f'    offset {pos:#06x}:  gsasm={mine[pos]:02x}  golden={golden[pos]:02x}')
        if len(diffs) > 20:
            print(f'    ... ({len(diffs) - 20} more)')

    if len(mine) != len(golden):
        print(f'  WARNING: size mismatch  gsasm={len(mine)}  golden={len(golden)}')

    if m == n:
        print('  BYTE-EXACT  ✓')
    else:
        print('  NOT byte-exact; any residual here is a regression or a new bug.')

    return 0 if m == n else 1


if __name__ == '__main__':
    show = '--diff' in sys.argv
    sys.exit(main(show))
