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
| M1 | `System/Tools/ToolNNN` mapped code images (12 toolsets) | gsasm + M2 + M4 | ✅ **byte-exact** (`work/toolcheck.py`, 186,110/186,110 incl. Tool034/TextEdit); full on-disk ExpressLoad files ALSO byte-exact — diskcheck logical-exact is 30/30 (E0–E3 closed Tool015/016/018, TS2/TS3, Tool034) |
| M2 | general OMF load-file linker | `gsasm/linkiigs.py` | ✅ **done** — tools, FSTs, drivers and the kernel all link through it |
| M3 | MakeBin/Overlay/catenate | `gsasm/makebin.py` | ✅ **done** — `prodos` byte-exact (`work/probootcheck.py`) |
| M4 | ExpressLoad relinker | `gsasm/expressload.py` | ✅ **done for the gated code-image corpus** — byte-exact mapped tools/FSTs/drivers; remaining full-file ExpressLoad residuals are tracked by `work/diskcheck.py` |
| M5 | `System/FSTs/*`, `System/Drivers/*` | gsasm + M2 (+M3) | ✅ **done** — all 8 buildable FSTs and all 12 mapped drivers byte-exact |
| M6 | `GS.OS`, `Start.GS.OS`, `P8`, `prodos`, `ERROR.MSG` | gsasm + M2 + M3 + M4 | ✅ byte-exact, including GS.OS SCM, Loader, Start.GS.OS, P8, prodos, and Error.Msg |
| M7 | Finder, Installer, asm CDEVs/NDAs (resource forks) | gsasm + M2 + **Rez** | 🟡 first target done: `design/rez.md` |
| — | Pascal/C desktop (Ctl-Panel CDEVs, GSCalc, ADU, Teach, Logon) | PascalIIgs / C | ❌ out of scope |

## Per-milestone detail

### M0 — ROM 03 firmware ✅ (baseline / reference)
`python3 work/buildrom.py` reconstructs the 262,144-byte ROM byte-identical to
the real chip. This is the proof that gsasm + a linker + a bank packager
reproduces real shipping bytes, and it anchors everything after it: every
change to the core is gated on the ROM staying byte-exact (`work/gate.py`).

### M1 — Toolbox `ToolNNN` mapped code images ✅
`work/toolcheck.py` assembles each manager from `GSToolbox`, links, and
byte-compares against the shipping (de-ExpressLoad'd) `ToolNNN`. The
cross-segment dispatch-table problem, source-level ExpressLoad case-B flags,
`~JumpTable` routing, Tool018's QDAux segmentation, Tool019's pure-literal
shift, and Tool034/TextEdit's LOAD/DUMP + record-ORG + shift-defer classes are
all closed: 12 tools, 186,110 bytes. The full on-disk ExpressLoad files are
byte-exact too — `work/diskcheck.py` logical-exact is 30/30 (E0–E3, 2026-07-19).

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
relocation dictionaries). The gated code-image corpus is byte-exact; the old
case-B "not a function of input" claim was overturned by source-level flagged
addends. Full on-disk ExpressLoad mismatches that remain in `work/diskcheck.py`
are tracked separately from the code-image gate.

### M5 — FSTs + Drivers ✅
`work/fstcheck.py` / `work/drivercheck.py`. All eight buildable FSTs with source
in the archive reproduce byte-exact, including AppleShare.FST. All twelve
mapped shipping drivers reproduce byte-exact, including SCSIHD.Driver.

### M6 — GS/OS kernel and boot files ✅
`work/kernelcheck.py`, following the tree's own `linkOS` recipe: link the OS
objects, split into `scm.bin.N` segments, catenate segments into `GS.OS` and
`Start.GS.OS`. `GS.OS` SCM, Loader, `Start.GS.OS`, `prodos`, `Error.Msg`, and
the full OverlayIIgs-built P8 image are byte-exact. An earlier "94-byte
external floor" was overturned: the bank-$E1 vectors blamed for it are
`EXPORT`ed `DS` globals in `GQuit.src`, resolved by the whole-OS link (see
RESULTS.md), and the remaining assembler/linker classes are now closed.

### M7 — Rez + asm desktop 🟡 first target done (Sys.Resources byte-exact)
Finder, Installer, and the asm-only CDEVs/NDAs assemble with gsasm but need a
**Rez** pass to build the resource fork of the shipping file. A clean-room
Rez compiler (`gsasm/rez/{lexer,parser,gen,convert,emit}.py`) plus a `gsrez`
CLI now reproduce the first (and done-gate) target, `Sys.Resources`
(24,337-byte resource fork; 143 resources across 17 types; local `type`
declarations, `$$Word()` expressions, `read`+`Convert`, arrays, switch
templates), byte-exact from the archived `.r`/`.aii` sources —
`work/rezbuildcheck.py`, gated via `gate.py`'s `rez_sysresources_bytes_exact`
metric. `work/diskcheck.py` builds and overlays Sys.Resources' resource fork
into the reconstructed System Disk image the same way it already does BUILD
files' data forks. EasyMount, the General CDEV, and Finder (the 52 KB prize)
remain as follow-on targets — mostly more breadth over the same `type`-
template grammar, plus Finder's multi-file include structure; the Pascal
CDEVs/NDA stay out of scope (their code resources are Pascal-compiled).
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
