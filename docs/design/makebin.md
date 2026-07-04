# Design: MakeBin / Overlay / catenate packager (M3)

**Replaces:** MPW `MakeBinIIgs`, `OverlayIIgs`, `catenate`, and the `setfile`/
`Rez -t -c` filetype stamping. **Unlocks:** GS/OS kernel binaries (M6), flat
device drivers (M5), GSBug ROM, BASIC.SYSTEM, ProDOS boot. Read `README.md` first.

These are all mechanical byte-shuffling steps that run *after* the linker (M2).
Put them in `gsasm/makebin.py`.

## 1. MakeBinIIgs — OMF load file → raw binary at an ORG
Flatten a linked load file to a flat memory image as it would appear loaded at a
given origin, with relocations applied for that origin.

```
makebin(load_file_bytes, org) -> flat_bytes
  parse segments; for each, walk records:
    CONST/LCONST -> copy bytes
    DS           -> zero-fill
    RELOC/EXPR/…  -> resolve at (org + position) and store   # reuse linkrom eval
  concatenate segment images in order -> flat_bytes
```
Real invocations to match (from the makefiles):
- `makebiniigs -org $2000` over `Boot/ProBoot.src`'s link → **`prodos`** (P8 boot).
- `makebiniigs -org $F80000` over the debugger link → **`debug.rom`** (GSBug ROM).
- BASIC.SYSTEM: org $2000, filetype $FF.
Reuse `work/linkrom.py`'s relocation-at-base logic (it already flattens OMF to a
bank image at a fixed base) — MakeBin is the single-segment / arbitrary-ORG case.

## 2. OverlayIIgs — patch driver images into a host binary at fixed offsets
`System/P8` is `mlisrc` (the MLI kernel) with ~12 drivers (`/RAM`, clocks,
Quit/GQuit, Disk ][) laid into reserved regions.

```
overlay(host_bytes, [(driver_bytes, offset), ...]) -> host_bytes'
  for each driver: host[offset:offset+len] = driver_bytes
```
Get the offsets from `GS.OS/MakeFiles/make.p8` and the `P8/*.n` driver order.

## 3. catenate — join named segment images in order
The kernel link (`GS.OS/Scripts/linkOS`) splits `scm.lnk` into `scm.bin.1..17`
then joins subsets:
```
GS.OS       = Loader.bin  ++  scm.bin.{1..7,12..17}
Start.GS.OS = scm.bin.{8..11}     # GQuit's 4 segments
```
```
catenate(parts: list[bytes]) -> b''.join(parts)
```
Trivial, but the **segment split** is the subtlety: after M2 links `scm.lnk`, you
must be able to address individual output segments by index to select {1–7,12–17}
vs {8–11}. So M2's segmented output mode must preserve/emit per-segment images that
catenate can pick. Transcribe the exact index groupings from `linkOS`.

## 4. Filetype stamping
Shipping files carry a ProDOS filetype/auxtype (e.g. `GS.OS` = type $B0 aux
$70f90000; `P8` = $FF; `prodos` = PSYS; `ToolNNN` = TOL/$BA). This is *metadata* on
the disk file, not part of the content we byte-compare — but a full "build the disk"
step (future) needs it. Record type/aux per output; the byte comparison itself
ignores forks. `cadius` preserves the `#BA0000` suffix = type/aux.

## Integration
- `gsasm/makebin.py`: `makebin(load, org)`, `overlay(host, patches)`,
  `catenate(parts)`, plus a small `stamp(path, filetype, auxtype)` helper.
- `work/*check.py` harnesses call these after `linkiigs.link`.

## Validation & acceptance
- **`prodos`** (P8 boot): assemble `Boot/ProBoot.src` → link → `makebin(org=$2000)`
  → byte-compare vs the `prodos` file from the disk. Smallest end-to-end M3 proof.
- **A flat driver** (e.g. `RAM5`, `Slinky`): link → makebin → compare vs
  `System/Drivers/<name>`.
- **`P8`**: mlisrc link → overlay drivers → compare vs `System/P8`.
- ROM unaffected (new code).
- **Done when:** `prodos` (or one flat driver) byte-matches end-to-end.

## Gotchas
- ORG-relative vs relocatable: MakeBin applies relocations for the ORG; a
  self-referencing label resolves to `org + offset`. Match `linkrom`'s convention.
- Overlay offsets and catenate index groups come from the makefiles — do not guess.
- Zero-fill (`DS`) between the last real byte and a bank/region boundary is
  structural padding (the ROM's 767-byte tail was exactly this) — include it only
  where the golden file does.
