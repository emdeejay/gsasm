# Results

What the toolchain reproduces, measured against the shipping binaries, and
what it provably cannot — with the evidence for each limit. Numbers are the
committed regression baseline (`work/gate.py`; `work/gate_baseline.json`).

## Reproduced byte-exact

| Target | Size | Verified by |
|---|---|---|
| ROM 03 firmware (all three banks) | 262,144 bytes | `work/buildrom.py` |
| All 7 buildable FSTs (Pro, HFS, Char, HS, DOS3.3, Pascal, MSDos) | 93,759 bytes | `work/fstcheck.py` |
| 11 of 12 drivers (AppleDisk, SCSI CD/Scan/Tape, RAM5, Slinky, AppleTalk stack, …) | 85,119 bytes | `work/drivercheck.py` |
| `prodos` (boot loader) | 1,668 bytes | `work/kernelcheck.py` |
| `Start.GS.OS` | 13,169 bytes | `work/kernelcheck.py` |
| `Error.Msg` | 5,407 bytes | `work/kernelcheck.py` |
| GS/OS Loader | 16,590 bytes | `work/loader_placed.py` |
| 15 of the 27 System 6.0.1 shipping files the disk harness rebuilds | — | `work/diskcheck.py` |

Close but not exact:

- **GS.OS** — 38,757 of 38,805 bytes (99.88%). The former 94-byte "external
  floor" was half wrong: 46 of those bytes were the bank-$E1 vectors, which
  are *defined* in `GQuit.src` and are now resolved; see below. The remaining
  48 bytes are three unrelated placement/length classes.
- **Toolbox toolsets** — 118,524 of 119,080 bytes (99.5%) across 14
  `ToolNNN` files (`work/toolcheck.py`; Tool023/StdFile added in R9 — its
  sources assemble cleanly, see `docs/design/expressload.md`).
- **Object-file encoding** — 40 of 61 ROM objects are byte-identical OMF;
  all 61 are *link-identical* (`work/linkcheck.py`): linking gsasm's object
  and Apple's original produces the same load image, so the remaining
  deltas are record-chunking differences with no effect on any output.

## Proven limits

Each of these was settled by evidence, not fatigue. They bound what any
toolchain could reproduce from this source archive.

**GS.OS: the bank-$E1 "external floor" — OVERTURNED (94 → 48 bytes).** The
old claim held that the dominant residual was cross-bank references to
`E1_MSG_ADDRESS`, `E1_VOLNAME`, `E1_CURRENT_ID`, `E1_APP_FILENAME` and similar
bank-$E1 vectors that "no file in `IIGS.601.SRC` defines." That is false. They
are `EXPORT`ed `DS.B`/`DC` allocations in `GQuit.src`'s `seg_e1` segment
(`GQuit.src` lines ~10490–10620), ORG'd at `e1_obj_pstn` = `$E1D200`, so gsasm
bakes each at its real address (e.g. `E1_MSG_ADDRESS` = `$E1D6F3`,
`E1_CURRENT_ID` = `$E1D679`). The earlier sweep missed them because it searched
for `EQU`-style defs, not `EXPORT`ed DS-in-segment globals. Apple's `linkOS`
resolves the SCM→GQuit reference because it links every kernel object in one
global pass; `GQuit` merely lands in the sibling `Start.GS.OS` output file.
`work/kernelcheck.py` now mirrors that by seeding `GQuit`'s placed exports into
the SCM link's extern table, recovering **46 bytes** (`38,711 → 38,757`).
(`E1_GET_REF_INFO` and `EQ_MSG_ADDRESS` are `Import`ed by SCM but never
referenced, so they emit no bytes and were never part of the residual.)

The remaining **48 bytes** are three unrelated classes, none of them bank-$E1
externals: (a) ~21 bytes of `b00segr`/`be0segr` bank-0 interior references where
gsasm places a dispatcher label 0-based (e.g. `$0019` vs golden `$AC2E`);
(b) ~18 bytes of `init1`/`init3`/`init4` header `DC.W` segment-length words and
length-derived immediates; (c) ~9 bytes of `scm_main` cross-references gsasm
resolves 0-based where the golden build lands them in bank 0
(`$B9D6`/`$B70A`/`$255C`). These are placement/length discrepancies in gsasm's
per-group linking, not missing source.

**ExpressLoad relocation encoding ("case B") — CLOSED for the single-segment
path (R9).** Previously classed as "not a function of the input"; overturned
by a source sweep (`docs/TODO.md`): the case-B standalone-RELOC flag is the
source expression's own out-of-range addend (e.g. `#Label+$80000000` /
`#Label+$C0000000`, the ModalDialog filterProc/hook-pointer convention, bit
31/30), not opaque LinkIIgs state, and the rule (`gsasm/expressload.py::
_scan_case_b`) is now implemented for the single-segment ExpressLoad path.
Measured effect (`work/gate.py --full`'s `disk_logical_exact`, 16/28 ->
17/28): **Tool014 (WindMgr) is now fully byte-exact** (its sole residual was
this flag); Tool027 (FontMgr)'s relocation dictionary is now exact, leaving
only 2 bytes of a separate, pre-existing code-image residual; Tool023
(StdFile) improved but is not byte-exact — one of its two flagged pairs
carries a wrong *value* because of an unrelated, pre-existing linkiigs
symbol-scoping bug (`GETFILTER` resolves unresolved), not a gap in this rule.
TS2/TS3/Tool.Setup build through a separate multi-segment ExpressLoad path
that has never emitted any standalone reloc record (case A or case B) — a
different, still-open gap — so they remain non-byte-exact. See
`docs/design/expressload.md`.

**SCSIHD.Driver: the golden binary does not match the archived source.**
The archived `SCSI.Drivers` source assembles byte-exact for the other three
SCSI drivers, and for SCSIHD it matches no device-type configuration
(the four possible builds yield 13,842/13,442/17,257/8,354 bytes vs the
shipping 15,690). Only a 211-byte prefix and 37-byte suffix agree; command
tables show code inserted throughout. The shipping driver was built from a
later source revision that is not in the archive.

**Absent or non-source material.** `AppleShare.FST` has no source in the
archive. Tool015/016/018 embed `~JumpTable` segments generated by the MPW
linker, not present in any source. Tool019's source disagrees with its
shipping binary. P8 (ProDOS 8) is out of scope: it needs the OverlayIIgs
driver-overlay build and include files not present in the GS/OS tree.

## Method

Everything rests on differential validation against captured artifacts of
the original build: source, `.lst` listings, `.obj` objects, and shipping
binaries. Any byte gsasm produces that differs from the original is a
measurable defect; any target that matches is proven correct, not assumed.

- `work/gate.py` runs every comparison harness and fails if any metric
  drops below the committed baseline. Nothing regresses silently.
- The golden reference material is copyrighted and not distributable
  (gitignored under `ref/`), so the repo also carries a corpus-free test
  suite (`tests/`): original sources pinning each discovered dialect
  behavior, with expected bytes minted only while the full gate passes.
  A fresh clone can run it; CI does, on every push.
- The disk-image harness additionally needs the `a2til` disk-image tools
  (a sibling project; point `A2TIL_PATH` at a checkout).
