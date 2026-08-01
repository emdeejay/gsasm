# Disk 1 (Install) overlay wiring — builder-complete -> RECONSTRUCTED

## Summary

Wired `DISK_BUILDER_REGISTRY['Disk 1 of 7 Install.2mg']` in `work/diskcheck.py`
covering **37 of the census's 39 'built' forks**. Two forks
(`SCSI.Manager`, `SCSIHD.Driver`) are documented residuals, left OUT of the
registry after investigation (see Residuals below) — their DE-ExpressLoad'd
code images are proven byte-exact (`work/drivercheck.py`, closed 2026-07-18,
which is what backs the census's 'built' classification), but the FULL
on-disk ExpressLoad'd file — a surface never gated before this task — is not.

`python3 work/diskcheck.py --disk 'Disk 1 of 7 Install.2mg'` now exits 0:
`logical-exact: 37/37`, `PHYSICAL image byte-match: 819264/819264 (100%)`.

Also added `('diskcheck1', ...)` to `work/gate.py` FULL_CHECKS, and `'Disk 1'`
to `work/manifestcheck.OVERLAID_DISKS`. `work/diskmanifest._wired_builders()`
auto-merged the new registry with **no census edits** — verified directly
(37 `(path, fork)` CallableProof keys for `/Install/...`, matching the
registry exactly, no collisions). Install disk now reports `[RECONSTRUCTED]`
in `manifestcheck.py`'s scoreboard.

## Schema change (needed for dual-fork paths)

The existing `DISK_BUILDER_REGISTRY` schema (Disk 5/6) only supported one
`(fork, builder)` per path. Disk 1 has two DUAL-FORK files needing both data
AND rsrc builders on the same path (`ControlPanel`, `Installer`). Generalized
`reconstruct()` and `diskmanifest._wired_builders()` to accept either a
single `(fork, builder)` tuple or a **list** of them per path, via a new
`diskcheck._iter_registry()` helper. Disk 5/6 entries are unaffected (still
single tuples) — re-verified both still pass unchanged (1/1, 2/2, physical
100% each).

## Registry table (path -> builder source)

| Disk 1 path | fork | Builder source | Reuse? |
|---|---|---|---|
| `/Install/ProDOS` | data | `SOURCE_BUILDERS[V+'/ProDOS']` (probootcheck) | reused (Disk 2) |
| `/Install/System/GS.OS` | data | `SOURCE_BUILDERS[...]` (diskbuilders/kernel_os.py) | reused |
| `/Install/System/GS.OS.Dev` | data | `SOURCE_BUILDERS[...]` (kernel_os.py) | reused |
| `/Install/System/Start.GS.OS` | data | `SOURCE_BUILDERS[...]` (kernel_setup.py) | reused |
| `/Install/System/Error.Msg` | data | `SOURCE_BUILDERS[...]` (kernel_setup.py) | reused |
| `/Install/System/P8` | data | `SOURCE_BUILDERS[...]` (diskbuilders/p8_driver.py) | reused |
| `/Install/System/FSTs/Pro.FST` | data | `SOURCE_BUILDERS[...]` (expressload_files.py) | reused |
| `/Install/System/FSTs/Char.FST` | data | `SOURCE_BUILDERS[...]` (expressload_files.py) | reused |
| `/Install/System/Drivers/AppleDisk3.5` | data | `SOURCE_BUILDERS[...]` (expressload_files.py) | reused |
| `/Install/System/Drivers/AppleDisk5.25` | data | `SOURCE_BUILDERS[...]` (expressload_files.py) | reused |
| `/Install/System/Drivers/Console.Driver` | data | `SOURCE_BUILDERS[...]` (expressload_files.py) | reused |
| `/Install/System/Drivers/UniDisk3.5` | data | new `_build_unidisk35_fullfile()` — Disk-1-only driver, generic `expressload(objects)` recipe over `drivercheck.DRIVERMAP['UniDisk3.5']` (same shape as `expressload_files._build_driver`, just no existing Disk-2 entry to reuse since this driver never ships on Disk 2) | new (thin wrapper) |
| `/Install/System/System.Setup/Tool.Setup` | data | `SOURCE_BUILDERS[...]` (diskbuilders/toolsets.py, cracked 2026-08-01) | reused |
| `/Install/System/System.Setup/TS2` | data | `SOURCE_BUILDERS[...]` (toolsets.py) | reused |
| `/Install/System/System.Setup/TS3` | data | `SOURCE_BUILDERS[...]` (toolsets.py) | reused |
| `/Install/System/System.Setup/Resource.Mgr` | data | `SOURCE_BUILDERS[...]` (expressload_files.py) | reused |
| `/Install/System/System.Setup/Sys.Resources` | rsrc | `REZ_BUILDERS[...]` (rezbuildcheck) | reused |
| `/Install/System/CDevs/SetStart` | rsrc | new `_build_setstart_rsrc()` — `cdevcheck.build_cdev_fork('SetStart')`; Install-only CDEV, not in Disk-2 `REZ_BUILDERS` | new (thin wrapper) |
| `/Install/System/CDevs/General` | rsrc | `REZ_BUILDERS[...]` (cdevcheck) | reused |
| `/Install/System/CDevs/RAM` | rsrc | `REZ_BUILDERS[...]` (cdevcheck) | reused |
| `/Install/System/Desk.Accs/ControlPanel` | data | new `_build_controlpanel_data()` — `appdatacheck.build_app_data('ControlPanel')` | new (thin wrapper) |
| `/Install/System/Desk.Accs/ControlPanel` | rsrc | `REZ_BUILDERS[...]` (cdevcheck, same callable Disk 2 uses) | reused |
| `/Install/System/Start` | data | new `_build_install_start()` — `expressloadcheck.build_start()`; NOT the Finder (Disk 2's `/System/Start` is a completely different file/recipe) — the 565B SetStart-generated launcher | new (thin wrapper) |
| `/Install/System/Tools/Tool{014,015,016,018,019,020,021,022,023,027,028,034}` (12) | data | `SOURCE_BUILDERS[...]` (expressload_files.py) | reused |
| `/Install/Installer` | data | new `_build_installer_data()` — `installerdatacheck.build_installer_data()` | new (thin wrapper) |
| `/Install/Installer` | rsrc | new `_build_installer_rsrc()` — `installercheck.build_installer_fork()` | new (thin wrapper) |

37 entries total (25 reused Disk-2 callables + 12 more of the same reused
Tool builders + 6 genuinely new thin lazy-import wrappers for Disk-1-only
artifacts). All wrapper functions follow the existing lazy-import discipline
(`_build_cdev`, `_build_fonts_readme_rsrc`, etc.) to avoid module-load-time
import cycles.

## Residuals: SCSI.Manager, SCSIHD.Driver full-file wrapper

Both are in `drivercheck.DRIVERMAP` as plain (subdir, sources, defines)
tuples, same shape as `UniDisk3.5`. Built the same generic
`expressload(objects)` recipe used for `UniDisk3.5` (which DOES come out
byte-exact) and compared against Disk 1's actual pre-overlay fork:

- `SCSI.Manager`: built 10158B vs gold 10150B (+8B), first diff @ offset
  0x64 (100, within the `~ExpressLoad` directory's forward-pointer fields —
  two pointer fields each off by exactly +8, consistent with a slightly
  longer reloc dictionary elsewhere in the file).
- `SCSIHD.Driver`: built 17358B vs gold 17344B (+14B), same pattern (first
  diff also @ offset 100).

Deeper look at `SCSI.Manager`'s actual reloc-dictionary bytes (offset ~3893)
shows a delta-encoding difference: gold's run is `[000,000,000,059]`
(address-delta triplets) vs built's `[000,000,059,059]` — i.e. a reloc
weight/grouping value landing in the wrong dictionary slot when
`expressload()`'s default single-group merge processes this driver's 11
(SCSI.Manager) / 13 (SCSIHD.Driver, shared SCSI files) separately-assembled
source files. This is a genuine, unexplored-until-now surface: `drivercheck.py`
only ever validated the DE-ExpressLoad'd code image (`_extract_img` after
`linkiigs.link(..., opts={'merge': True})`), never the full ExpressLoad'd
wrapper+reloc-dictionary this overlay needs. Per the task's discipline, this
was left OUT of the registry rather than force-wired — the two files stay on
disk as their original (already-correct) bytes, so the physical image match
is unaffected; only `disk1_logical_exact`'s denominator is 37, not 39.
Root-causing the reloc-dictionary encoding for multi-file (>2 object) driver
merges is future work, not in scope here.

## Predicted vs actual

| Metric | Predicted | Actual |
|---|---|---|
| `disk1_logical_exact` | NEW, revised to `[37, 0]` after the SCSI residual investigation (task's illustrative `[39,0]` guess did not hold) | `[37, 0]` ✓ |
| `disk1_physical_exact` | NEW `[819264, 0]` (confirmed Disk 1 image size = 819264 bytes, same as Disk 2/5/6) | `[819264, 0]` ✓ |
| `manifest_physical_exact` | good 3 -> 4, bad 4 -> 3 | `[4, 3]` (was `[3, 4]`) ✓ |
| everything else | unchanged | unchanged (confirmed via `--full` run before `--update`: every prior metric showed `(baseline good=X bad=Y)` matching exactly) |

`python3 work/diskcheck.py --disk 'Disk 1 of 7 Install.2mg'` exits 0.
`python3 work/gate.py --full` (pre-update) showed only the two new metrics
as unbacked (`NEW, no baseline` — expected first-run state, same as when
diskcheck5/6 were first added) and zero regressions elsewhere.
`python3 work/gate.py --full --update` wrote 44 metrics.
`git diff work/gate_baseline.json` is exactly the predicted 3-metric change
(two new keys + the manifest_physical_exact flip) — confirmed above.

## Files touched (all under `work/`, none under `gsasm/`, no census edits)

- `/Users/mdj/src/gsasm/work/diskcheck.py` — 6 new lazy-import wrapper
  functions, the Disk 1 registry entry (37 forks, 2 dual-fork lists), and the
  `_iter_registry()` generalization of `reconstruct()`.
- `/Users/mdj/src/gsasm/work/diskmanifest.py` — `_wired_builders()` now uses
  `dc._iter_registry()` instead of assuming one `(fork, builder)` per path.
- `/Users/mdj/src/gsasm/work/gate.py` — new `diskcheck1` FULL_CHECKS entry.
- `/Users/mdj/src/gsasm/work/manifestcheck.py` — `'Disk 1'` added to
  `OVERLAID_DISKS`.
- `/Users/mdj/src/gsasm/work/gate_baseline.json` — updated via `--update`
  (diff confirmed above).

No git commit was made; all changes are left in the working tree as
requested.
