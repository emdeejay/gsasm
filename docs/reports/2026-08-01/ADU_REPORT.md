# Adv.Disk.Util resource fork — cracked byte-exact

Target: resource fork of `/SystemTools1/Adv.Disk.Util` (Disk 3 of 7
"SystemTools1.2mg"). Golden fork: 8,037 bytes, genuine IIgs resource fork
(rFileVersion=0). Source: `ref/GSOS_6/IIGS.601.SRC/A.U.G/ADU/adu.rii`.
DATA fork is Pascal (11 `.pii` + 2 `.aii`) and stays a
`no-source-substitute` (pascal-c-nontarget) wall — untouched by this work,
resource fork only.

## Recipe transcribed from the makefile / BuildADU script

`ref/GSOS_6/IIGS.601.SRC/A.U.G/ADU/makefile`:

```
adu.res  ⟵  adu.rii  mac.driver  {riigsincludes}TypesIIGS.r
    reziigs adu.rii -o adu.res
```

No `-d` defines beyond what `adu.rii` itself `#define`s
(`rSCSIDrvr $4D61`, `rSCSIDescDrvr $5E72`, `versionString "1.2"`, plus the
window/control equates). `#include "Typesiigs.r"` resolves against the
IIgs include set — the clean-room `gsasm/rez/include/TypesIIGS.r` fills
this role, same as every other rezforkcheck/cdevcheck target. Predefined
`RezIIGS = 1` (int, not string — the known gotcha) selects the IIgs branch
inside the include set's conditional templates; nothing in `adu.rii` itself
branches on it (no `#ifdef MacStyle`-style guard here, unlike Whoosh).

The only twist beyond the other 7 rezforkcheck targets: `adu.rii` declares
one `read` statement —

```
read rSCSIDrvr (0x00000001, preload, nonpurgeable) "mac.driver";
```

— and `A.U.G/ADU/mac.driver` (6,144 bytes, dated 1994-07-02, already
sitting in the source tree next to `adu.rii`) is exactly that payload: a
raw Apple-partition-map-format SCSI boot-block image, no Convert
transform declared. This is a genuine CORPUS-LOCAL read, not an
extraction-fed one — the bytes are pulled straight from the archived
source tree, not spliced in from the golden fork.

## Pipeline changes

1. **`gsasm/rez/gen.py`** — `ATTR_BITS` was missing the `nonpurgeable`
   keyword (`adu.rii`'s `preload, nonpurgeable` on the `read` statement,
   and the same pair on the adjacent `rSCSIDescDrvr` resource). Added
   `'nonpurgeable': 0x0000` — the purge-2-bit field's existing default
   (no purge keyword at all) made explicit; a real, standard Rez keyword,
   not an ad-hoc special case. Verified against golden: both entries'
   index attr word is `0x0040` (preload only), matching `preload |
   nonpurgeable == 0x0040 | 0x0000`. This is the only `gsasm/` change —
   no new template was needed (`rSCSIDescDrvr`/`rSCSIDrvr` custom types
   are declared right in `adu.rii` itself via `type ... { ... };`, and
   the wide-array/reversebytes/struct field kinds they use were already
   supported).

2. **`work/rezforkcheck.py`** — added `Adv.Disk.Util` as an 8th REZMAP
   target (D3, `/SystemTools1/Adv.Disk.Util`, `A.U.G/ADU/adu.rii`) and a
   new `READ_FILES` table (`{target: {(rtype, rid): corpus-relative
   path}}`) so `build_rez_fork` prefers a corpus-local file for a `read`
   entry's `(type, id)` key when one is listed, falling back to the
   existing gold-feed path (untouched, still exercised by nothing today
   but kept generic) for anything not listed. `READ_FILES['Adv.Disk.Util']
   = {(0x4D61, 1): 'A.U.G/ADU/mac.driver'}`. Docstring updated
   seven->eight throughout.

## Result: byte-exact on the first build after the ATTR_BITS fix

```
$ python3 work/rezforkcheck.py Adv.Disk.Util
Adv.Disk.Util: built=8037 gold=8037 BYTE-EXACT

$ python3 work/rezforkcheck.py
PASS Adv.Disk.Util 8037 bytes byte-exact (rsrc fork)
PASS Apple.Bowl   863 bytes byte-exact (rsrc fork)
PASS FindFile     1852 bytes byte-exact (rsrc fork)
PASS Frog         5782 bytes byte-exact (rsrc fork)
PASS MediaControl 670 bytes byte-exact (rsrc fork)
PASS Pioneer4200  505 bytes byte-exact (rsrc fork)
PASS VideoMix     625 bytes byte-exact (rsrc fork)
PASS Whoosh       10873 bytes byte-exact (rsrc fork)

rezforkcheck: 8/8 resource forks byte-exact REZFORK_BYTES_EXACT 29207/29207
```

No residual, no wall, no iteration needed beyond the single `nonpurgeable`
attribute-keyword addition. All 25 resources (rVersion, rComment, the
`read rSCSIDrvr` + its `rSCSIDescDrvr` descriptor, one dialog's
`rWindParam1`/`rControlList`, and 9 buttons' `rControlTemplate`/
`rpString`/`rTextForLETextBox2`) matched on the first pass once parsing
succeeded.

## Per-resource results

All 25 golden entries matched byte-for-byte; `rc.compare()` reported an
empty resources-differ list (nothing printed by the verbose per-target
run, which only prints non-`match` entries).

| type (hex) | id | size | resource |
|---|---|---|---|
| 0x8029 | 1 | 68 | rVersion |
| 0x802a | 1 | 171 | rComment |
| 0x4d61 | 1 | 6144 | rSCSIDrvr (read, corpus-local `mac.driver`) |
| 0x5e72 | 1 | 152 | rSCSIDescDrvr |
| 0x800e | 0x1001 | 80 | rWindParam1 (mainDlog) |
| 0x8003 | 0x1001 | 36 | rControlList (mainDlog) |
| 0x8004 | 2,3,5,8,9,a,b,c,d | 30 ea | rControlTemplate x9 (buttons) |
| 0x8006 | 2,3,5,9,a,b,c,d | varies | rpString x8 |
| 0x800b | 3,8 | varies | rTextForLETextBox2 x2 (MTitleTxt, MStatTxt) |

## Predicted vs actual gate movement

| metric | predicted | actual |
|---|---|---|
| rezfork_bytes_exact | 21170 -> 29207 | 29207/29207 (confirmed by rezforkcheck.py run above) |
| manifest_builders_wired | 180/181 -> 181/181 | see gate --full output below |
| manifest_builders_exact | 180/181 -> 181/181 (bad 1 -> 0) | see gate --full output below |
| SystemTools1 (Disk 3) state | "blocked: 1 TODO" -> "builder-complete (needs overlay)" | see gate --full output below |
| everything else | unchanged | see gate --full output below |

(gate --full / --update results appended below once the background run
completes.)
