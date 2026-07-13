# FINAL_RUN — the reachable, worthwhile remaining work

Status snapshot (2026-07-13). ROM 03 byte-exact; all 7 FSTs byte-exact; 11/12
drivers byte-exact; toolcheck 99%; **north star = byte-exact shipping disk
images (M8), at 14/26.** This doc is the decks-cleared worklist for one last
run: only the items that are *both* reachable from these sources *and* worth
the tokens. The walls (blocked/unreachable) are listed at the end so the run
does not waste effort re-litigating them.

Gate everything: `python3 work/gate.py` (fast) / `--full` (adds a2til
diskcheck). Baseline in `work/gate_baseline.json`. Never regress a gate.

---

## Tier 1 — the only prize that moves a disk image

### 1.1 GS.OS external floor — can the "missing" externals be supplied?
**Value: highest (a byte-exact GS.OS flips a diskcheck image).** **Risk: long shot.**

kernelcheck sits at 61815/74211; the residual **164 bytes** are cross-refs to
symbols the kernel build treats as unresolved externals — Console.Driver
(`CALL_ALLOC`, …) and toolbox entries. The handoff calls this a HARD FLOOR
"not in the kernel build at all."

BUT: **we already build Console.Driver byte-exact.** The open question for the
run: can the kernel link consume the *built* Console.Driver's (and/or the
toolbox stubs') exported symbol table to resolve those 164 bytes, instead of
leaving them 0/ffff? If yes, GS.OS goes byte-exact and diskcheck 14→15.

- Entry points: `work/kernelcheck.py` (reads cached
  `ref/GSOS_6/os_bin/GS.OS#F90000`, no a2til), `docs/design/LINKOS.md`,
  the `gextern`/`_placed_exports` machinery in kernel_os.
- Method: enumerate the 164 residual bytes per part (init3 −58, scm_main −42,
  b00segr −22, init4 −12, init1 −10, init2 −8, be0segr −7, sys_svc −3,
  cache −2). Classify each as (a) interior of a multi-file relocatable group
  we *do* build, or (b) a genuine external we build elsewhere
  (Console.Driver/toolbox). For (b), feed that component's exports into the
  content link and see if the byte resolves.
- Decision gate: if after enumerating, the 164 are provably symbols that exist
  in NO component we build (pure toolbox ROM entries), declare the floor final
  and stop — this is the "is it truly a wall" confirmation the project needs.

### 1.2 Wire the two un-attempted disk builders
**Value: medium (each could be a disk-image flip). Risk: unknown until tried.**

`Tool.Setup` and `Resource.Mgr` are listed as UNWIRED — the diskcheck harness
never builds them, so their tractability is simply unknown. Wire each into
`work/diskbuilders/` and run diskcheck; the diff will say whether it is an easy
flip, a known-class residual, or a new wall.

- Entry points: `work/diskcheck.py` (auto-discovers `work/diskbuilders/*.py`),
  an existing builder as a template.
- Needs a2til intact (`/Users/mdj/src/a2til`).

---

## Tier 2 — fidelity, not disk progress (objcheck 40/61)

**Framing, read first:** all 21 non-byte-identical objects are **link-identical
(provably correct)** — the linked ROM is already byte-exact. Fixing objcheck
improves OMF-*encoding* fidelity and robustness; it does **not** flip a disk
image. Worth doing only for completeness, or when a fix generalises (this
session's SCSI bugs each surfaced first as a "sizing drift"). Prioritise by
likelihood of a *shared, general* root cause.

Current worklist (`python3 work/objcheck.py <file>` for a per-record diff;
method = de-express/diff, group runs, map merged offset → segment → source,
verify arithmetic both directions):

| class | files (Δlen) | note |
|---|---|---|
| **small-delta** (likely one findable bug each) | Serial +5, SmartPort +6, MM +7 | best value/effort; start here |
| **sizing-drift cluster** (survey for a *common* cause) | StartStop −20, adb −21, ControlMgr −24, DialogMgr +24, MenuMgr −28, WindMgr −33, DefProcs −34, NDACalls −40, sane −49 | the SCSI lesson: several may share ONE bug |
| **large** (macro/data heavy) | WCM −193, text.tools −268, RomDataMgr −398, fm −954 | bigger digs; defer unless a cluster fix cascades here |
| **D2 — OUT OF SCOPE** | Monitor +131, Applesoft +35 | per-reference symbol scope; explicitly deprioritised |

Run plan: fix the 3 small-delta first (fast, isolated). Then survey the
sizing-drift cluster for a shared root cause *before* fixing individually —
gate after each. Stop when the marginal file needs a bespoke fix (that's the
fidelity floor).

---

## Tier 3 — quick confirmations / sweeps

### 3.1 SCSIHD — settle skew vs bug (~30 min)
The one non-byte-exact driver (42%). gsasm matches the *source* exactly for a
hard disk (verified `block_dvc=1`, `character_dvc=0`), yet the golden binary
includes character-device code. Confirm whether the captured golden
`SCSIHD.Driver` binary was built from a different source revision than
`ref/…/SCSI.Drivers`. If skew: document and close (unwinnable). If a real
gsasm bug: it's a driver flip. Entry: `python3 work/drivercheck.py SCSIHD`,
diff onset inside `wait_status` (SCSI Filter status:1174).

### 3.2 `&Sysdate`/`&SysTime` sweep
RAM5 needed its captured build timestamp injected (`DRIVER_BUILD_TIME`). Grep
the whole corpus for `&Sysdate`/`&SysTime`/`&Sysyear` embeds and check no
other gated file is silently short by a blank timestamp field. Cheap; likely
already clean outside RAM5.

---

## OUT OF SCOPE — the walls (do NOT spend the run here)

- **ExpressLoad reloc-tail case B** (Tool014/023/027/TS2/TS3) — PROVEN not
  source-derivable (converter source absent from the archive). See
  `docs/design/expressload.md`, oracle `work/reloc_survey.py`. Do not
  reverse-engineer per-tool.
- **~JumpTable tools** (Tool015/016/018) — MPW-linker-generated cross-bank
  stubs, not in source.
- **Tool019** — source discrepancy. **P8** — $BFxx cross-module + M/X-flag mess.
- **AppleShare.FST** — sources absent from the tree.
- **D2 / §3-ROM / D1** — deprioritised debt (see `RATIONALISE.md`).

## Infra note (not disk progress, flagged for honesty)
Every gate depends on gitignored copyrighted golden refs — a fresh clone has
no tests. If the run has spare budget, a small corpus-free fixture suite
(tiny `.asm` → asserted OMF bytes) would make the toolchain trustworthy to
ship/contribute to. Out of the disk-image critical path.

---

### One-run recommendation
1. **1.1 first** — enumerate the 164 GS.OS residual bytes and *settle* whether
   the floor is truly external. This is the single highest-value question left;
   even a negative answer is worth having definitively.
2. **3.1 + 3.2** — cheap confirmations, close SCSIHD and the timestamp sweep.
3. **1.2** — wire Tool.Setup / Resource.Mgr; take any easy flip.
4. **Tier 2 small-delta** — 3 quick objcheck wins if budget remains.
Everything else is a documented wall.
