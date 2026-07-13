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

---

## RUN RESULTS (2026-07-13, executed)

**Disk north star moved: 14 → 15 byte-exact (Resource.Mgr flipped).**

### 1.1 GS.OS external floor — SETTLED (floor is real)
- Fixed a general, byte-neutral bug first: the Layout-A header `DC.W
  seg_end-seg_start` (b00segr/be0segr/cache/init) baked `0 - seg_org` because
  `seg_end` (IMPORTed from the content group's trailing end-marker proc) was
  unresolved in kernelcheck's isolated header link. Seeding the header link with
  the content group's placed export table (+ init's `content_full` interior
  symtab) resolved it. **cache/scm.bin.12 now byte-EXACT; GS.OS SCM mismatch
  100 → 94; kernel_bytes 61815 → 61821.** (commit "resolve Layout-A header DC.W")
- Enumerated the remaining GS.OS SCM residual (94 bytes). The largest class —
  the cross-bank `000000/020000/ffffff → $E1Dxxx/$E0Dxxx` refs in scm.bin.3/.4/
  .13 — are references to `E1_MSG_ADDRESS`, `E1_VOLNAME`, `E1_GET_REF_INFO`,
  `E1_CURRENT_ID`, … **These are defined/exported in NO file anywhere in
  IIGS.601.SRC** (grepped the whole tree) — genuine bank-$E1 externals outside
  the kernel build. **Since these are unresolvable from any component we build,
  GS.OS can never go byte-exact — the floor is now PROVEN, not assumed.** The
  diskcheck GS.OS flip is blocked on this external floor, full stop.
- Two smaller sub-classes remain but are moot given the floor: init1/init3
  header length (4B; `sym_kind` prefers a same-named local label over the
  Import, collapsing `end-start` to a constant — a real but low-value gsasm
  quirk, not worth a risky core change) and b00segr's `STY/LDA $AC2E` interior
  refs (20B; group-link base, entangled — zero disk value now).

### 3.1 SCSIHD — CLOSED (source-revision skew, unwinnable)
gsasm builds type=0 (direct_acc/HD) to 13842B matching the source; golden is
15690B. No type config reproduces it (0/1/2/3 = 13842/13442/17257/8354). The
divergence is **pervasive** (only 211-byte prefix + 37-byte suffix match; the
command-table pointers are uniformly larger in golden → code inserted
throughout). The archived `SCSI.Drivers` source does not correspond to the
shipping SCSIHD.Driver binary. Document and close.

### 3.2 &Sysdate/&SysTime sweep — CLEAN
Only two source files embed a build timestamp: A.U.G Installer (not gated) and
P8's MliSrc (already handled). Every gated driver is byte-exact except SCSIHD
(a device-class skew, not a timestamp). RAM5's injection verified working. No
gated file is silently short by a blank timestamp field.

### 1.2 Disk builders
- **Resource.Mgr — WIRED, byte-exact FLIP (11798/11798).** The kernel_setup.py
  "489B bank-byte gap" note was stale (predated the case-A cRELOC / SUPER-ization
  work). Built via `expressload([(obj, asm)])` from GSToolbox/ResourceMgr with
  `-d debug=0 -d JimsExperiment=1`. diskcheck logical-exact **14 → 15**, wired
  26 → 27. (commit "wire Resource.Mgr")
- **Tool.Setup — investigated, tractability now KNOWN: code-byte-exact, blocked
  on the case-B reloc wall (NOT wired).** All 9 constituents assemble with zero
  errors; the multi-object, segment-name-filtered, 2-`-lseg` (`main` $3000 +
  `patches`) + ExpressLoad build reproduces **both segments' code LENGTHs
  exactly (1078 + 16402)**. The only residual (300B) is relocation-record
  ENCODING: gsasm SUPER-izes everything, but golden keeps 31 standalone
  cINTERSEG (main) + 11 standalone cRELOC (patches). This is the SAME
  ExpressLoad converter case-B wall as Tool014/023/027/**TS2/TS3** (its
  System.Setup siblings) — standalone-vs-SUPER is the converter-internal choice
  proven not source-derivable. NOT wired (a non-exact builder would regress the
  diskcheck attempted-but-residual count). Probe:
  scratchpad/toolsetup_probe.py.

### Net
Gate: `disk_logical_exact 14→15`, `kernel_bytes 61815→61821`, all others
unchanged. Two questions the project wanted settled are now settled with proof:
the GS.OS floor IS external (1.1), and SCSIHD IS a skew (3.1). Tool.Setup's code
is exact — only the ExpressLoad reloc encoding (the known wall) stands between
it and a 16th image.
