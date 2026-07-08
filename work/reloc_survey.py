"""reloc_survey.py — WP-3.1 empirical survey of standalone RELOC/cRELOC records.

Loops over all 6 target gold files (Tool014, Tool023, Tool027, Tool034, TS2, TS3)
and tabulates every standalone RELOC (0xE2) and cRELOC (0xF5) record found in the
GOLD version of each file (not our builder output).

For each record, captures: file, segment index, record type, size, shift (stored as
positive right-shift), offset, relOffset (full 32-bit), and relOffset & 0xC0000000.

Then analyzes:
1. Which (size, shift) combos appear standalone vs SUPER-only
2. The high-flag bits on relOffset
3. Correlation with record type (RELOC vs cRELOC), and offset/relOffset magnitudes
"""
import os, sys, struct
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from diskcheck import SYSTEM_DISK, catalog_disk
from diskcheck import _find_a2til
_find_a2til()
from a2til.prodos import Volume

# Reuse helpers from reloc_diag.py
from reloc_diag import dump_records, split_segments, parse_header

TARGET_SUBSTRINGS = ['Tool014', 'Tool023', 'Tool027', 'Tool034', 'TS2', 'TS3']

# SUPER types and their (size, shift) meaning:
#   type 0  -> size=2, shift=0   (16-bit addr)
#   type 1  -> size=3 or 4, shift=0  (24-bit addr)
#   type 27 -> size=2, shift=16  (bank byte)
#   types 16,17,28,29 -> interseg variants
SUPER_COVERED = {(2, 0), (3, 0), (4, 0), (2, 16)}  # (size, positive_shift) covered by SUPER

def parse_shift_stored(stored_shift_byte):
    """Convert stored bitShiftCount (unsigned byte, negative means right-shift)
    to positive right-shift amount."""
    # The stored field is signed; 248 = -8 (shift right 8), 240 = -16 (shift right 16), etc.
    if stored_shift_byte > 127:
        return -(stored_shift_byte - 256)   # e.g. 248 -> 8, 240 -> 16
    return -stored_shift_byte               # e.g. 0 -> 0 (no shift)

def collect_standalones(vol, path):
    """Return list of dicts, one per standalone RELOC/cRELOC in the gold file at path."""
    data = bytes(vol.read_file(path))
    segs = split_segments(data)
    records = []
    for si, seg in enumerate(segs):
        recs = dump_records(seg)
        for op, nm, sz, det in recs:
            if nm not in ('RELOC', 'cRELOC'):
                continue
            # Parse the detail string: "size=N shift=N off=0x... rel=0x..."
            parts = {}
            for token in det.split():
                k, v = token.split('=')
                parts[k] = v
            raw_size = int(parts['size'])
            raw_shift_stored = int(parts['shift'])
            offset = int(parts['off'], 16)

            # relOffset from dump_records:
            # For RELOC: stored as signed 32-bit, printed as unsigned hex (r & 0xffffffff)
            # For cRELOC: stored as unsigned 16-bit
            rel_raw_str = parts['rel']
            rel_raw = int(rel_raw_str, 16)

            # Interpret as full 32-bit for analysis
            if nm == 'RELOC':
                # reloc_diag stored with '<i' (signed) then printed & 0xffffffff
                rel32 = rel_raw  # already masked to 32 bits
            else:
                # cRELOC: 16-bit field, no high bits
                rel32 = rel_raw  # max 0xFFFF

            positive_shift = parse_shift_stored(raw_shift_stored)
            high_flags = rel32 & 0xC0000000
            in_super = (raw_size, positive_shift) in SUPER_COVERED

            records.append({
                'file': path.split('/')[-1],
                'seg': si,
                'type': nm,
                'size': raw_size,
                'shift_stored': raw_shift_stored,
                'shift_pos': positive_shift,
                'offset': offset,
                'relOffset32': rel32,
                'relOffset_raw': rel_raw_str,
                'high_flags': high_flags,
                'in_super': in_super,   # True if (size,shift) has a SUPER type
            })
    return records


def main():
    vol = Volume(bytearray(open(SYSTEM_DISK, 'rb').read()))
    files = catalog_disk(vol)

    all_records = []
    for target_sub in TARGET_SUBSTRINGS:
        matched = [f for f in files if target_sub in f.path]
        if not matched:
            print(f'WARNING: {target_sub} not found on disk')
            continue
        f = matched[0]
        recs = collect_standalones(vol, f.path)
        all_records.extend(recs)
        print(f"\nFILE: {f.path}")
        if not recs:
            print("  (no standalone RELOC/cRELOC records)")
        for r in recs:
            flag_str = f'flags=0x{r["high_flags"]:08x}' if r['high_flags'] else 'no-flag'
            super_str = 'COULD-BE-SUPER' if r['in_super'] else 'no-super-type'
            print(f"  seg{r['seg']} {r['type']:6s} size={r['size']} shift={r['shift_pos']:2d}"
                  f"  off=0x{r['offset']:06x}  rel=0x{r['relOffset32']:08x}"
                  f"  {flag_str}  [{super_str}]")

    # --- Analysis ---
    print("\n" + "="*70)
    print("ANALYSIS")
    print("="*70)

    standalone = all_records
    flagged = [r for r in standalone if r['high_flags'] != 0]
    unflagged = [r for r in standalone if r['high_flags'] == 0]

    print(f"\nTotal standalone RELOC/cRELOC records: {len(standalone)}")
    print(f"  Flagged (relOffset & 0xC0000000 != 0): {len(flagged)}")
    print(f"  Unflagged:                              {len(unflagged)}")

    # Break down by record type
    for nm in ('RELOC', 'cRELOC'):
        subset = [r for r in standalone if r['type'] == nm]
        f_sub = [r for r in subset if r['high_flags'] != 0]
        print(f"\n  {nm}: {len(subset)} total, {len(f_sub)} flagged")
        if subset:
            sizes_shifts = set((r['size'], r['shift_pos']) for r in subset)
            print(f"    (size,shift) combos: {sorted(sizes_shifts)}")
            # How many could have been SUPER-folded?
            could_super = [r for r in subset if r['in_super']]
            print(f"    Could be SUPER-covered: {len(could_super)}")

    # All flagged records detail
    print(f"\nALL FLAGGED RECORDS ({len(flagged)}):")
    for r in flagged:
        flag_hex = f'0x{r["high_flags"]:08x}'
        flag_name = {0x80000000: '0x80000000', 0xC0000000: '0xC0000000'}.get(r['high_flags'], flag_hex)
        # Is relOffset sign-negative as int32?
        rel32_signed = r['relOffset32'] if r['relOffset32'] < 0x80000000 else r['relOffset32'] - 0x100000000
        lower28 = r['relOffset32'] & 0x0FFFFFFF
        print(f"  {r['file']} seg{r['seg']} {r['type']:6s} size={r['size']} shift={r['shift_pos']:2d}"
              f"  off=0x{r['offset']:06x}  rel=0x{r['relOffset32']:08x}"
              f"  flag={flag_name}"
              f"  signed_rel={rel32_signed}"
              f"  lower28=0x{lower28:06x}")

    # Hypothesis testing
    print("\nHYPOTHESIS TESTS:")
    print(f"\n1. Are ALL flagged records RELOC (not cRELOC)?")
    flagged_reloc = [r for r in flagged if r['type'] == 'RELOC']
    flagged_creloc = [r for r in flagged if r['type'] == 'cRELOC']
    print(f"   Flagged RELOC: {len(flagged_reloc)}, Flagged cRELOC: {len(flagged_creloc)}")

    print(f"\n2. Do flagged records have (size,shift) combos covered by SUPER?")
    flagged_in_super = [r for r in flagged if r['in_super']]
    print(f"   Flagged with SUPER-coverable (size,shift): {len(flagged_in_super)}")
    for r in flagged_in_super:
        print(f"     {r['file']} seg{r['seg']} size={r['size']} shift={r['shift_pos']} "
              f"off=0x{r['offset']:x} rel=0x{r['relOffset32']:08x}")

    print(f"\n3. Do UNFLAGGED standalone records have (size,shift) NOT covered by SUPER?")
    unflagged_no_super = [r for r in unflagged if not r['in_super']]
    unflagged_in_super = [r for r in unflagged if r['in_super']]
    print(f"   Unflagged, no-super-type:  {len(unflagged_no_super)}")
    print(f"   Unflagged, has-super-type: {len(unflagged_in_super)}")
    for r in unflagged_in_super:
        print(f"     {r['file']} seg{r['seg']} {r['type']} size={r['size']} shift={r['shift_pos']} "
              f"off=0x{r['offset']:x} rel=0x{r['relOffset32']:08x}")

    print(f"\n4. Is 0x80000000 vs 0xC0000000 distinguished?")
    f80 = [r for r in flagged if r['high_flags'] == 0x80000000]
    fc0 = [r for r in flagged if r['high_flags'] == 0xC0000000]
    print(f"   0x80000000: {len(f80)} records")
    print(f"   0xC0000000: {len(fc0)} records")
    print(f"   other:      {len(flagged) - len(f80) - len(fc0)} records")

    print(f"\n5. For flagged records: shift values present?")
    for r in flagged:
        print(f"   {r['file']} seg{r['seg']} shift={r['shift_pos']} ({r['shift_stored']} stored) "
              f"flag=0x{r['high_flags']:08x}")

    print(f"\n6. Are flagged records always paired (offset, relOffset same between two records)?")
    # Group by (file, relOffset & 0x0FFFFFFF)
    from collections import defaultdict
    by_base_rel = defaultdict(list)
    for r in flagged:
        base_rel = r['relOffset32'] & 0x0FFFFFFF
        by_base_rel[(r['file'], base_rel)].append(r)
    for key, grp in sorted(by_base_rel.items()):
        shifts = [r['shift_pos'] for r in grp]
        flags = [f"0x{r['high_flags']:08x}" for r in grp]
        offs = [f"0x{r['offset']:x}" for r in grp]
        print(f"   {key[0]} base_rel=0x{key[1]:06x}: {len(grp)} records,"
              f" shifts={shifts}, flags={flags}, offsets={offs}")

    print(f"\n7. Flag value vs shift correlation?")
    for r in flagged:
        print(f"   shift={r['shift_pos']} -> flag=0x{r['high_flags']:08x}  size={r['size']}")

    print(f"\n8. What is the offset vs relOffset magnitude for ALL flagged records?")
    for r in flagged:
        print(f"   off=0x{r['offset']:06x} ({r['offset']}) "
              f"rel=0x{r['relOffset32']:08x} ({r['relOffset32']}) "
              f"lower28=0x{r['relOffset32'] & 0x0FFFFFFF:06x} ({r['relOffset32'] & 0x0FFFFFFF})")


if __name__ == '__main__':
    main()
