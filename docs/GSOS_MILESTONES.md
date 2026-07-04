# Reproducing GS/OS System 6.0.1 — Milestones

Goal: extend gsasm from "byte-exact ROM 03" to "byte-exact reproduction of the
shipping System 6.0.1 images, from the original source, using clean-room
reimplementations of the MPW IIgs cross-development tools."

Everything system-critical in the 6.0.1 source tree is **AsmIIgs assembly** built
with the MPW IIgs toolchain (`AsmIIgs` → `LinkIIgs` → `MakeBinIIgs`/`OverlayIIgs`/
`catenate`, with `ExpressLoad` for load files). gsasm already reimplements
`AsmIIgs`. The remaining tools are the deliverables below. Pascal/C/Rez cover only
the desktop GUI shell and are out of scope (except a Rez stretch, M7).

See `docs/design/README.md` for the shared context every milestone/tool design
assumes (OMF primer, golden-binary layout, validation harness, gotchas).

## Dependency graph

```
              gsasm (AsmIIgs)  ── DONE
                    │
        ┌───────────┼─────────────────────────┐
   M2 LinkIIgs   M3 MakeBin/Overlay        M4 ExpressLoad
   (keystone)    /catenate packager        (load-file relinker)
        │            │                          │
        ├────────────┴──────────┬───────────────┤
        ▼                       ▼               ▼
   M1 Toolbox            M5 FSTs+Drivers    M6 GS/OS kernel
   ToolNNN (WIP)         System/{FSTs,      GS.OS, Start.GS.OS,
                         Drivers}/*         P8, prodos, ERROR.MSG
                                │
                                ▼
                    M7 Rez → Finder / Installer / asm CDEVs (stretch)
```

`M2` is the keystone — FSTs, drivers, tools, and the kernel all link with it.
`M1` (tools) is the beachhead already in progress and is what drives `M2`+`M4`.

## Milestone table

| # | Target images | Source | Tools needed | Status |
|---|---|---|---|---|
| M0 | ROM 03 firmware (256K, 3 banks) | `work/romsrc/GS_ROM` (GSFirmware+GSToolbox, ROM-03 back-port) | gsasm + `linkrom` + ROM makebin | ✅ **byte-exact** (`work/buildrom.py`) |
| M1 | `System/Tools/ToolNNN` (13+ toolsets) | `ref/GSOS_6/IIGS.601.SRC/GSToolbox` | gsasm + M2 + **M4** | 🟡 **80%** (`work/toolcheck.py`); dispatch table solved, WindMgr sizing fixed |
| M2 | general OMF load-file linker | — | `gsasm/linkiigs.py` | ✅ **done** (merged; no regression, segmented mode ready for M4) |
| M3 | MakeBin/Overlay/catenate | — | `gsasm/makebin.py` | ✅ **done** — `prodos` **100% byte-exact** (`work/probootcheck.py`) |
| M4 | ExpressLoad relinker | `GS.OS/Loader/ExpressLoad/ExpressLoad.src` (spec!) | — | 🔓 **unblocked** (M2 segmented mode ready); design: `docs/design/expressload.md` |
| M5 | `System/FSTs/*` (8), `System/Drivers/*` (~17) | `GS.OS/FSTs`, `GS.OS/{Drivers,SupervisoryDrivers}` | gsasm + M2 (+M3 for flat drivers) | ⬜ |
| M6 | `GS.OS`, `Start.GS.OS`, `P8`, `prodos`, `ERROR.MSG` | `GS.OS/{OS,Loader,Boot,P8}` | gsasm + M2 + M3 + M4 | ⬜ |
| M7 | Finder, Installer, asm CDEVs/NDAs (resource forks) | `A.U.G` (asm parts) | gsasm + M2 + **Rez** | ⬜ stretch: `docs/design/rez.md` |
| — | Pascal/C desktop (Ctl-Panel CDEVs, GSCalc, ADU, Teach, Logon) | `A.U.G`, `ToolBoxMisc` | PascalIIgs / C | ❌ out of scope |

## Per-milestone detail

### M0 — ROM 03 firmware ✅ (baseline / reference)
Done. `python3 work/buildrom.py` reconstructs the 262,144-byte ROM byte-identical
to the real chip; `objcheck` 36/61 OBJ-identical, `linkcheck` 61/61 LINK_IDENTICAL.
This is the proof that gsasm + a linker (`work/linkrom.py`) + a bank packager
reproduces real shipping bytes. Reuse its patterns; do not regress it — every tool
change that touches `gsasm/`/`omf.py` must re-run buildrom+objcheck+linkcheck.

### M1 — Toolbox `ToolNNN` 🟡 (beachhead, in progress)
`work/toolcheck.py`. Assembles each manager from `GSToolbox`, links, byte-compares
to the shipping `ToolNNN` (de-ExpressLoad'd). Single-object managers at 98–99%
(DialogMgr, ListMgr, Scrap); corpus 78%. The **dispatch table** lever is solved
(route cross-segment refs through OMF emit + link, not `flat()+relink`).
Blockers to 100%: (a) full relocation modeling needs **M4** (ExpressLoad SUPER
records — types 0/1/27); (b) multi-object managers have per-instruction **sizing
drift** (per-module `m65816` fixes, revalidate ROM after each); (c) a symbol-
shadowing case (`$FExx` firmware equate vs local tool def). Feeds M2/M4 design.

### M2 — General `LinkIIgs` (the keystone) ⬜
A clean OMF v2 load-file linker: N input `.obj` (multi-segment, APW/OMF) →
one relocated OMF load segment (or a KIND-typed load file). Generalizes
`gsasm/link.py` (single-file) and `work/linkrom.py` (ROM banks). Drives tools,
FSTs, drivers, and the kernel. **Design: `docs/design/linkiigs.md`.**

### M3 — MakeBin / Overlay / catenate packager ⬜
The post-link steps: `MakeBinIIgs` (flatten an OMF load file to a raw binary at an
ORG), `OverlayIIgs` (lay driver images into P8 at fixed offsets), `catenate` (join
segment images into `GS.OS`/`Start.GS.OS`), plus the MPW `setfile`/`Rez -t/-c`
filetype stamping. All mechanical byte-shuffling. **Design: `docs/design/makebin.md`.**

### M4 — ExpressLoad relinker ⬜
Converts a plain OMF load file into the ExpressLoad "fast-load" format (the
`~ExpressLoad` directory segment + reorganized segments + compressed `SUPER`
relocation dictionary). Needed for byte-exact `ToolNNN` and `Loader2.0`.
**The tool's own source is in-tree** (`GS.OS/Loader/ExpressLoad/ExpressLoad.src`) —
authoritative spec. **Design: `docs/design/expressload.md`.**

### M5 — FSTs + Drivers ⬜
Apply M2 (+M3). Golden binaries: pull `System/FSTs/*` and `System/Drivers/*` from
the System 6.0.1 disk images (`ref/GSOS_6/System601_disks`, extract with `cadius`).
8 FSTs (Pro/HFS/Char/HS/DOS3.3/Pascal/MSDos; AppleShare sources absent), ~17
drivers (AppleDisk/SCSI×4/RAM5/Slinky/AppleTalk stack/SCC+SCSI managers). All pure
AsmIIgs. A `work/fstcheck.py`/`work/drivercheck.py` mirroring `toolcheck.py`.

### M6 — GS/OS kernel ⬜
Apply M2 + M3 + M4. `GS.OS/Scripts/linkOS` is the recipe:
`linkiigs -apw -o scm.lnk` over the OS objects, split into `scm.bin.N` segments,
then catenate segs 1–7,12–17 → `GS.OS`, segs 8–11 (GQuit) → `Start.GS.OS`; P8 via
`make.p8` (mlisrc + `OverlayIIgs`'d drivers); `prodos` boot via
`makebiniigs -org $2000` over `Boot/ProBoot.src`. Golden: `GS.OS`, `Start.GS.OS`,
`P8`, `prodos`, `ERROR.MSG` from the disk. The Loader is itself ExpressLoad'd (M4).

### M7 — Rez + asm desktop ⬜ (stretch)
Finder, Installer, and the asm-only CDEVs/NDAs (CDRemote, CloseView, EasyAccess,
VideoKeyboard, General/Namer/Network CDEVs) assemble with gsasm but need a **Rez**
pass to build the resource fork of the shipping file. **Design: `docs/design/rez.md`.**

### Out of scope
Pascal (`.pii/.p`) and C (`.c`) desktop pieces — Control-Panel CDEVs, GSCalc,
VideoMix, ADU, Teach, LogonCDEV/FolderPriv. Reproducing these would require
reimplementing PascalIIgs / a C compiler, which is a different project. They are
the outer GUI shell, not the system core.

## Future: linker consolidation (after M4–M6)

We currently have three linking paths — `gsasm/link.py` (shipped single-file
`gslink`), `work/linkrom.py` (ROM bank build), and `gsasm/linkiigs.py` (the M2
general linker). Once `linkiigs` has proven it reproduces the ROM banks and
lands the tools/FSTs/drivers (M4–M6), collapse the three onto it:

- `link.py` → its primitives already ARE `linkiigs`'s kernel; make `gslink` call
  `linkiigs.link(..., merge=True)` and retire the duplicate top-level `link()`.
- `linkrom.py` → express its bank build as `linkiigs.link` with `org` per bank +
  the `BANKS` segment ordering + `rommap` as `extern`; keep only the ROM-specific
  multiply-defined-label scope logic that `linkiigs` doesn't yet have.

**Guardrail:** `link.py` (proven by `linkcheck` 61/61) and `linkrom.py` (proven by
`buildrom` byte-exact) are the validated references. This is a pure refactor —
every step gated on those harnesses staying green. Do NOT start it before M4–M6;
collapsing the linkers early risks the one byte-exact result we have for no new
capability.

## Validation discipline (all milestones)

1. Golden binaries come from the real shipping artifacts (ROM image, disk `ToolNNN`/
   FST/driver/OS files), never from the source tree.
2. Every component gets a `*check.py` harness in `work/` modeled on `toolcheck.py`:
   assemble → link → (package) → byte-compare vs golden, report N/M identical.
3. Any change to `gsasm/` or `omf.py` is gated on `buildrom.py` + `objcheck.py` +
   `linkcheck.py` still passing (ROM must stay byte-exact). Revert on regression.
4. Ship linker/packager code under `gsasm/` (reusable) with thin `work/*.py`
   harnesses; keep copyrighted golden data under `ref/` (gitignored).
