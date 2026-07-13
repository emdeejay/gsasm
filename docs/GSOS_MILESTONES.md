# Reproducing GS/OS System 6.0.1 — Milestones

Goal: extend gsasm from "byte-exact ROM 03" to "byte-exact reproduction of the
shipping System 6.0.1 images, from the original source, using clean-room
reimplementations of the MPW IIgs cross-development tools."

Everything system-critical in the 6.0.1 source tree is **AsmIIgs assembly** built
with the MPW IIgs toolchain (`AsmIIgs` → `LinkIIgs` → `MakeBinIIgs`/`OverlayIIgs`/
`catenate`, with `ExpressLoad` for load files). gsasm reimplements all of them.
Pascal/C/Rez cover only the desktop GUI shell and are out of scope (except a Rez
stretch, M7).

This document is the roadmap; **outcomes and the proven limits are in
[`RESULTS.md`](RESULTS.md)**. See `design/README.md` for the shared context the
individual tool designs assume (OMF primer, golden-binary layout, gotchas).

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
   ToolNNN               System/{FSTs,      GS.OS, Start.GS.OS,
                         Drivers}/*         P8, prodos, ERROR.MSG
                                │
                                ▼
                    M7 Rez → Finder / Installer / asm CDEVs (stretch)
```

## Milestone table

| # | Target images | Tools needed | Status |
|---|---|---|---|
| M0 | ROM 03 firmware (256K, 3 banks) | gsasm + `linkrom` + ROM makebin | ✅ **byte-exact** (`work/buildrom.py`); objcheck 40/61 obj-identical, linkcheck 61/61 link-identical |
| M1 | `System/Tools/ToolNNN` (13 toolsets) | gsasm + M2 + M4 | 🟡 **99.5%** (`work/toolcheck.py`); residual = the ExpressLoad case-B encoding, linker-generated `~JumpTable` segments, and a Tool019 source discrepancy — see RESULTS.md |
| M2 | general OMF load-file linker | `gsasm/linkiigs.py` | ✅ **done** — tools, FSTs, drivers and the kernel all link through it |
| M3 | MakeBin/Overlay/catenate | `gsasm/makebin.py` | ✅ **done** — `prodos` byte-exact (`work/probootcheck.py`) |
| M4 | ExpressLoad relinker | `gsasm/expressload.py` | ✅ **done** — byte-exact vs Tool022/021/028; one documented encoding limit (case B) |
| M5 | `System/FSTs/*`, `System/Drivers/*` | gsasm + M2 (+M3) | ✅ **done** — all 7 buildable FSTs byte-exact; 11/12 drivers byte-exact (SCSIHD golden is a later source revision) |
| M6 | `GS.OS`, `Start.GS.OS`, `P8`, `prodos`, `ERROR.MSG` | gsasm + M2 + M3 + M4 | ✅ **at the proven floor** — prodos/Start.GS.OS/Error.Msg/Loader byte-exact; GS.OS 99.76% (94-byte external floor); P8 out of scope |
| M7 | Finder, Installer, asm CDEVs/NDAs (resource forks) | gsasm + M2 + **Rez** | ⬜ stretch: `design/rez.md` |
| — | Pascal/C desktop (Ctl-Panel CDEVs, GSCalc, ADU, Teach, Logon) | PascalIIgs / C | ❌ out of scope |

## Per-milestone detail

### M0 — ROM 03 firmware ✅ (baseline / reference)
`python3 work/buildrom.py` reconstructs the 262,144-byte ROM byte-identical to
the real chip. This is the proof that gsasm + a linker + a bank packager
reproduces real shipping bytes, and it anchors everything after it: every
change to the core is gated on the ROM staying byte-exact (`work/gate.py`).

### M1 — Toolbox `ToolNNN` 🟡 99.5%
`work/toolcheck.py` assembles each manager from `GSToolbox`, links, and
byte-compares against the shipping (de-ExpressLoad'd) `ToolNNN`. The
cross-segment dispatch-table problem and the sizing-drift class were both
solved; what remains is bounded by things outside the source archive
(RESULTS.md): the ExpressLoad case-B relocation encoding, `~JumpTable`
segments the MPW linker generated into three tools, and one tool whose
archived source disagrees with its binary.

### M2 — General `LinkIIgs` ✅ (`gsasm/linkiigs.py`)
The general OMF v2 load-file linker: N input objects (multi-segment, APW/OMF),
libraries (`-lib`), segment naming/placement (`-lseg`), the `-apw` recipe used
by the GS/OS build scripts, per-object symbol scoping, and deferred high-word
shifts. Everything downstream (M1, M5, M6) links through it.
Design record: `design/linkiigs.md`.

### M3 — MakeBin / Overlay / catenate ✅ (`gsasm/makebin.py`)
The post-link packaging steps: flatten an OMF load file to a raw binary at an
ORG, overlay driver images, catenate segment images. Proven end-to-end by the
byte-exact `prodos` boot file. Design record: `design/makebin.md`.

### M4 — ExpressLoad relinker ✅ (`gsasm/expressload.py`)
Converts a plain OMF load file into the ExpressLoad fast-load format (the
`~ExpressLoad` directory segment, reorganized segments, compressed `SUPER`
relocation dictionaries). Byte-exact against the golden Tool022/021/028. The
one limit — the converter's standalone-vs-SUPER choice for a handful of
relocations ("case B") is internal state of the original tool, not a function
of its input — is analysed in `design/expressload.md`.

### M5 — FSTs + Drivers ✅
`work/fstcheck.py` / `work/drivercheck.py`. All seven FSTs with source in the
archive reproduce byte-exact (AppleShare's source is absent). Eleven of twelve
drivers reproduce byte-exact; the shipping SCSIHD.Driver was built from a
later source revision than the archived one (RESULTS.md has the evidence).

### M6 — GS/OS kernel ✅ at the proven floor
`work/kernelcheck.py`, following the tree's own `linkOS` recipe: link the OS
objects, split into `scm.bin.N` segments, catenate segments into `GS.OS` and
`Start.GS.OS`. `prodos`, `Start.GS.OS`, `Error.Msg` and the Loader are
byte-exact. `GS.OS` stops 94 bytes short: those bytes reference bank-$E1
vectors defined nowhere in the source archive, so the gap is unclosable from
these sources — the floor is proven, not assumed. P8 needs the OverlayIIgs
driver-overlay build plus include files not in the GS/OS tree, and is
documented out of scope.

### M7 — Rez + asm desktop ⬜ (stretch)
Finder, Installer, and the asm-only CDEVs/NDAs assemble with gsasm but need a
**Rez** pass to build the resource fork of the shipping file.
Design: `design/rez.md`.

### Out of scope
Pascal (`.pii/.p`) and C (`.c`) desktop pieces — Control-Panel CDEVs, GSCalc,
VideoMix, ADU, Teach, LogonCDEV/FolderPriv. Reproducing these would require
reimplementing PascalIIgs / a C compiler, which is a different project. They
are the outer GUI shell, not the system core.

## Future: linker consolidation

Three linking paths exist — `gsasm/link.py` (shipped single-file `gslink`),
`work/linkrom.py` (ROM bank build), and `gsasm/linkiigs.py` (the general
linker). With M4–M6 complete, they could be collapsed onto `linkiigs`:

- `link.py` → make `gslink` call `linkiigs.link(..., merge=True)` and retire
  the duplicate top-level `link()`.
- `linkrom.py` → express the bank build as `linkiigs.link` with per-bank `org`
  + the `BANKS` segment ordering; keep only the ROM-specific
  multiply-defined-label scoping `linkiigs` doesn't have.

**Guardrail:** `link.py` (proven by linkcheck 61/61) and `linkrom.py` (proven
by the byte-exact ROM) are the validated references. This is a pure refactor,
gated on `work/gate.py` staying green at every step.

## Validation discipline (all milestones)

1. Golden binaries come from the real shipping artifacts (ROM image, disk
   `ToolNNN`/FST/driver/OS files), never from the source tree.
2. Every component gets a `*check.py` harness in `work/` modeled on
   `toolcheck.py`: assemble → link → (package) → byte-compare vs golden.
3. Any change to the core is gated on `python3 work/gate.py` holding its
   committed baseline (the ROM must stay byte-exact). Revert on regression.
4. Ship linker/packager code under `gsasm/` (reusable) with thin `work/*.py`
   harnesses; keep copyrighted golden data under `ref/` (gitignored).
5. Behavioral discoveries get a corpus-free fixture in `tests/` so they stay
   pinned on machines without the golden refs.
