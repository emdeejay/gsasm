# gsasm — Statement of Work: Path to "Complete"

> Draft 2026-07-30. Purpose: define what **Complete** means for this project as a
> single machine-checkable target, then lay out an execution plan structured so
> the bulk of it can run **largely automated** (gate-oracled agent/workflow loops)
> with humans only at policy gates.

---

## 1. Baseline (what "done" already covers, at v0.4.0)

- **Disk 2 (System Disk): 100% physical byte-match** (819,264/819,264),
  `disk_logical_exact` 39/39, `oos:0` — 39 files source-built + 13 carried
  verbatim as documented substitutes.
- **Everything assembler/Rez-derived is byte-exact**: ROM 03, GS.OS, P8,
  BASIC.System, 14/14 tools, 12/12 drivers, 8/8 FSTs, 19/19 CDEVs, the Finder
  (both forks), Installer, Teach, Sys.Resources, EasyMount, MountImage data,
  4 app data forks, 5 misc resource forks.
- **The whole-disk reconstruction machinery is already disk-agnostic**:
  `work/diskcheck.py::check(disk_path=…)` builds → overlays → physically
  byte-matches *any* `.2mg`. Builders register via `diskbuilders.load(V)` →
  `{disk_path: callable}` (SOURCE_BUILDERS + REZ_BUILDERS). Only Disk 2 has a
  builder registry + substitute manifest wired.

The canonical target set (`ref/GSOS_6/System601_disks/System 6.0.1/`):

| # | Disk | Whole-image status | Notable forks already byte-exact |
|---|------|--------------------|----------------------------------|
| 1 | Install | not reconstructed | Installer rsrc; SetStart CDEV |
| 2 | System Disk | **100% physical ✅** | (everything) |
| 3 | SystemTools1 | not reconstructed | Finder (both forks); DirectConnect/Keyboard/Modem/Monitor/Sound CDEVs; CDRemote data; FindFile rsrc |
| 4 | SystemTools2 | not reconstructed | Teach rsrc; AppleShare/FolderPriv/Namer/NetPrinter/Network/MediaControl CDEVs; Pioneer2000/EasyAccess/Pioneer4200 data; MediaControl/VideoMix/Pioneer4200 rsrc |
| 5 | Fonts | not reconstructed | Apple.Bowl rsrc (mostly bitmap fonts → substitutes) |
| 6 | synthLAB | not reconstructed | NoteSeq + VideoMix tools; MIDI CDEV |
| 7 | Apple II Setup | not reconstructed | **HFS net-boot disk** (not ProDOS — see A.2); Basic.System, p8, ProDOS16 boot blocks/image |

So the honest current claim is *"Disk 2 reconstructed whole-image; on the other
six disks a scattered set of file forks is proven, but the disks themselves are
not reconstructed end-to-end."*

---

## 2. Definition of Complete (the acceptance predicate)

> **CHOSEN SCOPE (locked 2026-07-30): Tier A + Tier C.** Complete =
> all 7 English disks at 100% physical byte-match (`oos:0`) **and** the refactor
> quality backlog closed (R10 + deep-dive D1–D8). Tiers B (localized) and D
> (self-hosting) are out of scope for "complete" but remain future options.

> **Core completion:** every disk `D` in the canonical 7-disk English System
> 6.0.1 set satisfies `diskcheck.check(D)` = **100% physical byte-match**, where
> every file on `D` is classified as exactly one of:
> - **built** — reconstructed byte-exact from archived source, or
> - **substitute** — no archived source exists (verified, not assumed), carried
>   verbatim from the golden image with a documented reason,
>
> and **`oos` (unclassified/out-of-scope) = 0** on every disk.

This is deliberately a **single boolean an agent can evaluate**: `gate.py` green
**and** `diskcheck.check(D)` physical == 100% with `oos:0` for all `D ∈ 1..7`.
Non-targets (Pascal/C code forks, static runtime data, no-source data/fonts) are
*compatible* with 100% physical match — Disk 2 already proves it (13 substitutes
inside a 100% image). Completion is not "everything is source-built"; it is
"every image is reproduced, and every file is honestly accounted for."

### Completion tiers (pick the bar in §8)
- **Tier A — Core:** the 7 English disks, 100% physical, `oos:0`. *(recommended target)*
- **Tier B — Localized:** + German/French variants (`…/German/`, `…/French/`).
- **Tier C — Quality:** + refactor backlog closed (R10 + deep-dive D1–D8).
- **Tier D — Capstone:** self-hosting (`gsasm816` assembles gsasm; fixed-point proof).

### Explicit non-goals (permanent, documented)
Pascal/C-compiled code & data forks (the three-bucket breakdown in **A.4** — 7
whole-fork Pascal apps/DAs/NDAs whose resource forks *are* byte-exact, plus the
extraction-fed CDEV `rCDEVCode` payloads); `MountImage.r` resource fork (no
oracle); static runtime data with no producing source; localized disks under
Tier A. Each such file is a **substitute**, never an `oos`.

---

## 3. Why this is largely automatable

Three properties make autopilot realistic here:

1. **Exact machine oracle.** `diskcheck.check(D)` and `gate.py` give a
   deterministic pass/fail per file and per disk. No human judgment needed to
   know whether a unit is done.
2. **Independent, parallelizable units.** Each file is its own byte-exact
   problem; failures don't couple. Fan-out is natural.
3. **A proven hard-nut workflow.** The decode → synthesize → adversarial-verify
   multi-agent pattern already cracked the hardest cases (the ExpressLoad
   BankRel rule, the Finder data fork). Genuinely new dialect/reloc/layout rules
   have a repeatable engine, not a research gamble.

Humans are needed only at **policy gates**: (a) confirming a "no source →
substitute" classification is genuine (negative claims rot — this repo's core
lesson), and (b) tier/scope decisions.

---

## 4. The autonomous unit loop (the thing that runs itself)

Per disk `D`, per file `f`:

```
CENSUS(D)            -> enumerate every file; classify f as
                        {known-fork | source-buildable | no-source | unknown}
for each f:
  BUILD(f)           -> known-fork: reuse builder
                        source-buildable: generate builder from makefile recipe
                        no-source: mark substitute (see VERIFY-NEGATIVE)
  CHECK              -> diskcheck.check(D) reports byte-match for f
  if mismatch:
     CRACK(f)        -> multi-agent workflow: N decode agents diff built-vs-gold,
                        synthesize the missing dialect/reloc/layout rule,
                        adversarially verify, land gate-guarded fix
  VERIFY-NEGATIVE    -> before any "no source" substitute is accepted, a
                        source-search agent must fail to find source across ALL
                        trees (IIGS.601.SRC, "ROM Source Code", system500.hfv);
                        a found source flips f back to source-buildable
until diskcheck.check(D) == 100% physical AND oos(D) == 0
```

**Guardrails (non-negotiable, enforced in every automated step):**
- Every code-touching change must keep `gate.py` stdout **byte-identical to
  baseline** (byte-exact discipline; a metric that *improves* means behavior
  changed — stop).
- **Never `--bless` to make red green.** Re-derive against gold.
- Every **new** behavior gains a corpus-free fixture in the same commit.
- Every **"non-target / no-source"** claim is adversarially verified (source
  search) before acceptance — this is the one place the project has historically
  been wrong, so it is a hard gate, not a comment.

---

## 5. Workstreams

- **W1 — Multi-disk harness generalization.** Turn Disk-2's implicit
  registry into a per-disk manifest system: `diskmanifest/D{n}.py` declaring
  `{path: builder | SUBSTITUTE(reason)}`, and a `gate` metric
  `disk_physical_exact` fractional over all 7 disks. *(one-time infra; ~1 session)*
- **W2 — Per-disk completion (the bulk).** Run the §4 loop for disks
  1,3,4,5,6,7. Each disk is an independent sub-project. *(the automated mass)*
- **W3 — Residual single-file gaps.** Notably `Tool.Setup` (code-exact,
  blocked on case-B reloc encoding). Attempt via the CRACK workflow; if it
  resists, document as the one deliberate exception (already is).
- **W4 — Quality/refactor (Tier C).** R10 cache; deep-dive D1 (`_common.py`),
  D3 (multiseg phase-split), D4 (OMF classifier), D5 (asm internals). All
  gate-identical.
- **W5 — Release & hygiene.** Per-milestone version bumps (the 0.4.0 release
  path is proven); optional copyright history scrub decision.

---

## 6. Phased execution plan

Each phase is sized to a supervised automated run: a workflow (or agent fan-out)
does the work, the orchestrator gate-checks and commits between phases. Effort =
rough wall-clock of automated sessions, not human days.

| Phase | Goal | Automation | Human gate | Acceptance |
|-------|------|------------|------------|------------|
| **P0** | W1 infra: per-disk manifest + `disk_physical_exact` gate metric over 7 disks; **incl. an HFS whole-image overlay path for Disk 7** (see A.2) | scripted (mechanical) | review the metric wiring | gate green; Disk 2 still 100% |
| **P1** | ✅ **DONE** — evidence-based census (Appendix A): 355 files classified, 57 buildable, 8 Pascal/C, 183 substitute, 2 needs-investigation | (workflow wf_986133b2-1c2) | confirm substitute lists | every file classified; 0 unknown |
| **P2** | Wire all **already-proven** forks into their disk manifests (105 built files: Finder, 19 CDEVs, Installer, Teach, drivers, FSTs, kernel, app/misc forks) | mechanical wiring agent per disk | — | those files flip to byte-exact on their disks |
| **P3** | Disks 5 (Fonts) & 6 (synthLAB) to 100% — data disks, ~28/30 and ~23/25 substitute + 1 buildable each (A.3) | one loop pass | confirm the data files are genuinely no-source | Disks 5,6 100% physical, oos:0 |
| **P4** | Disks 1, 3, 4 to 100% — wire the ~48 buildable files; **most are new instances of proven builder types** (printer/AppleTalk/MIDI drivers, Tool025/029/032/038, Printer/Slots/Time CDEVs, 12 Sound rez) | per-disk loop; CRACK only for genuinely-new dialects | confirm substitutes + the 8 Pascal/C non-targets (A.4) | Disks 1,3,4 100% |
| **P5** | Disk 7 (Apple II Setup) to 100% — **HFS net-boot disk** (A.2); 7 buildable (Basic.System, p8, ProDOS16 boot blocks + image, IWEm), 5 substitute | HFS overlay loop + CRACK for boot infra | confirm substitutes | Disk 7 100% |
| **P6** | ✅ **DONE** — needs-investigation resolved: both → buildable-asm (A.6); `drivercheck` "Slinky not shipped" stale claim fixed | — | — | census 0 unknown |
| **P7** | W3 residual: retry `Tool.Setup` case-B via CRACK; finalize the one documented exception | CRACK workflow | accept exception if it resists | Tool.Setup byte-exact OR documented |
| **P8** | **Tier A COMPLETE**: `disk_physical_exact` 7/7, tag a release | scripted | approve release (outward-facing) | all 7 disks 100%, oos:0 |
| **P9** | Tier C: R10 assembly cache + deep-dive D1 (`_common.py`), D5 (asm internals) | gate-identical refactor commits | review each packet | gate byte-identical each step |
| **P10** | Tier C: deep-dive D3 (multiseg phase-split), D4 (OMF classifier) — the high-risk structural pieces | supervised, byte-identity-gated | review | gate byte-identical; **Tier A+C COMPLETE** |

**Sequencing rationale (evidence-driven, per Appendix A):** P3 (Fonts + synthLAB)
first — both are ~90% no-source data, so they validate the P0 machinery for near
pennies. Then P4 (Disks 1/3/4), where the ~48 buildable files are mostly new
instances of already-proven builder types (drivers, tools, CDEVs, Sound rez), so
the CRACK workflow is rarely needed. Disk 7 (P5) is deliberately last: it's the
one genuinely-different image (HFS net-boot, needs the new overlay path + boot
infrastructure).

---

## 7. Risk register

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| A "no source" call is wrong (source exists) → false substitute | medium (historically the #1 error) | VERIFY-NEGATIVE hard gate: source-search across all 3 trees before any substitute is accepted |
| A genuinely new dialect/reloc rule resists the CRACK workflow | low (workflow has cracked every case so far) | escalate to a human-supervised deep-dive session; never bless around it |
| Automated fix silently changes bytes elsewhere | low | gate-stdout-byte-identical discipline catches any drift immediately |
| Localized disks (Tier B) multiply substitute work | n/a unless Tier B chosen | keep Tier A as the definition of "complete"; Tier B explicitly optional |
| Copyright material in `tmp/` history (public) | present | separate decision (history scrub offered/declined); not on the completion path |

---

## 8. Decisions (locked 2026-07-30)

1. **Completion tier → Tier A + C.** Complete = 7 English disks at 100% physical
   (`oos:0`) plus the refactor quality backlog (R10 + D1–D8). B/D deferred.
2. **Autonomy → Supervised workflows.** Each phase runs as agent/workflow
   fan-out; the orchestrator gate-checks and commits between phases and surfaces
   substitute lists + hard-nut decisions at phase boundaries. Human is in the
   loop at phase boundaries, not per file.
3. **`Tool.Setup` → attempt the case-B crack (P7).** If it resists, fall back to
   the documented exception.

**Next action:** P0 (per-disk manifest infra + `disk_physical_exact` gate metric
over 7 disks). **P1 census is DONE** — see Appendix A (evidence-based, not
inference).

---

## Appendix A — Evidence-based census (2026-07-30)

Method: deterministic 7-disk file enumeration (a2til / `work/hfs.py`) + a 6-agent
parallel classification pass, each file grep-verified against the source trees
and the `work/*check.py` harnesses, with adversarial "no-source" checks. Raw
data: workflow `wf_986133b2-1c2`. This **supersedes** the inferences elsewhere
in this doc (notably the synthLAB and Pascal/C guesses).

### A.1 Classification — all 7 disks (354 files)

| Disk | files | built | buildable | Pascal/C | no-source sub | needs-invest |
|------|------:|------:|----------:|---------:|--------------:|-------------:|
| 1 Install | 97 | 33 | 3 | 0 | 60 | 1 |
| 2 System Disk *(done)* | 50 | 38 | 0 | 0 | 12 | 0 |
| 3 SystemTools1 | 79 | 19 | 15 | 3 | 41 | 1 |
| 4 SystemTools2 | 62 | 14 | 30 | 4 | 14 | 0 |
| 5 Fonts | 30 | 0 | 1 | 1 | 28 | 0 |
| 6 synthLAB | 25 | 1 | 1 | 0 | 23 | 0 |
| 7 Apple II Setup | 12 | 0 | 7 | 0 | 5 | 0 |
| **TOTAL** | **355** | **105** | **59** | **8** | **183** | **0** |

*(Updated 2026-07-30: the 2 needs-investigation items resolved to buildable-asm — see A.6. Census now fully classified, 0 unknown.)*

**The remaining reproduction work is 57 buildable files** — and most are new
*instances of already-proven builder types*: printer/AppleTalk/MIDI drivers (the
driver builder already proves 12), Tool025/029/032/035/038 (the tool builder
proves 14), the Printer/Slots/Time CDEVs and 12 Sound resources (the Rez
pipeline proves 19 CDEVs + Sys.Resources). So P4 is largely "point the existing
builder at more of the same," not new dialect cracking.

### A.2 Correction: Disk 7 is HFS-inside-2IMG, not ProDOS

The a2til parse failure was a **filesystem misdiagnosis**: `Disk 7 of 7 Apple II
Setup.2mg` is a valid 800K ProDOS-order 2IMG whose **contents are HFS** (Mac
filesystem — MDB `BD` at image offset 1088), built on a Mac via MPW; it is the
AppleShare **net-boot** disk (recipe `GS.OS/NetBoot/Makefile`). Read with
`work/hfs.py` after stripping the 64-byte header (12 files, 2 dirs). **P0 infra
must add an HFS whole-image overlay path** — `diskcheck.check` currently assumes
a ProDOS `Volume`. This is the one genuinely-different disk.

### A.3 Correction: synthLAB & Fonts are data disks, not Pascal/C

- **synthLAB (Disk 6):** 23/25 files are no-source data (`.bnk`/`.seq`/`.wav`
  instrument/sequence/waveform data, icons, Finder.Data) → substitutes; the
  `synthLAB` app binary has **no source in any tree** (third-party Bogas
  Productions app, copied in by the build, not compiled) → substitute; only
  `Tool035` (MIDISynth, 65816 asm) is buildable. **Zero Pascal/C.**
- **Fonts (Disk 5):** 28/30 no-source (bitmap fonts, Finder.Data) → substitutes;
  Apple.Bowl (rsrc built, code is BASIC-compiled-by-a-Pascal-tool). Trivial disk.

### A.4 Pascal/C breakdown — three buckets (evidence-cited)

Raw source in the archive is Pascal 54 files / ~21.8K lines + C 57 / ~11.9K —
but that count is misleading. Cross-referencing against what actually *ships*
(the disk census) and against dead/stub files splits it three ways. `.pii` is
the real Pascal-IIgs extension (an earlier `.p`-only grep undercounted).

**Bucket A — whole-fork Pascal non-targets (7 shipping apps/DAs/NDAs).** The
entire code/data fork is Pascal; for every one the **resource fork is already
byte-exact**, so only the compiled code/data is a substitute.

| Component | Disk | Pascal lines | rsrc fork |
|-----------|------|-------------:|-----------|
| Adv.Disk.Util (ADU, 11 `.pii`) | 3 | 5,485 | ✅ |
| Teach | 4 | 4,776 | ✅ teachcheck |
| Apple.Bowl | 5 | 3,791 | ✅ rezforkcheck |
| VideoMix NDA | 4 | 2,161 | ✅ rezforkcheck |
| MediaControl NDA | 4 | 2,041 | ✅ rezforkcheck |
| Calculator (GSCalc NDA) | 3 | 1,316 | — |
| FindFile DA | 3 | 626 | ✅ rezforkcheck |

~20,200 Pascal lines. (`CLOCK.PATCH`, loosely tagged Pascal/C by the census, is
actually Applesoft with no source → a plain no-source substitute.)

**Bucket B — CDEV code-resource payloads.** The Rez *shell* is byte-exact from
source; the embedded `rCDEVCode` is compiled Pascal/C, **extraction-fed** from
gold, not source-assembled. Count these as "rsrc-built, code-substituted."

| CDEV | Lang | lines | | CDEV | Lang | lines |
|------|------|------:|-|------|------|------:|
| SetStart | Pascal | 286 | | FolderPriv | C | 709 |
| Slots | Pascal | 332 | | Namer | C | 280 |
| Monitor | Pascal | 98 | | NetPrinter | C | 280 |
| | | | | Network | C | 150 |
| | | | | MIDI (cdev) | C | 132 |
| | | | | DirectConnect | C | 70 |

~716 Pascal + ~1,600 C, plus shared CtlPanel interface units (~1.3K).

**Bucket C — NOT shipping (excluded from the completion scope):**
- **Logon CDEV — 8,665 lines of C** — the single largest Pascal/C component, but
  it is **on no disk** (unused/never-shipped). This is why raw C looked large.
- **7 dead `.pii` stubs** (34 bytes each, literally *"This sourcefile is no
  longer used"*): General / Keyboard / Time / Modem / Printer / RamDisk / Sound
  CDEV — those CDEVs are **not** Pascal.
- **Build-host tools** (~1K C, run on the Mac at build time, never IIgs
  binaries): `NetBoot/AristotlePatch`, `MakeImage`, `GQuit/MakeSource`,
  `NuMustang`, `TABASCO`, `SD.ODDS`.

**Net shipping Pascal/C non-target scope: ~15 artifacts, ~23K lines (~21K Pascal
+ ~1.9K C)** — every Bucket-A one already has a byte-exact resource fork, so what
gets substituted is only the compiled code/data.

### A.6 needs-investigation — RESOLVED (2026-07-30, both → buildable-asm)

- `/Install/System/Start` (Disk 1) — a 565 B asm boot-launcher, **not** the
  Finder (the System Disk's `Start` is the Finder; this one is ~565 B). Source =
  `SetStartCDEV/Startup.Aii` (a 65816 launcher PROC: reads the SetStart boot
  path from MessageCenter → `_quitGS`, Finder fallback); `SetStart.make` "Added
  dependencies for START". → **buildable-asm** (build-verify in P4).
- `/SystemTools1/System/Drivers/A2.RAMCard` (Disk 3) — source =
  `GS.OS/Drivers/Slinky/slinky.aii` ("Slinky (RAM card) Driver", asm v1.01).
  This corrected a **stale wrong claim** in `drivercheck` ("Slinky not shipped on
  6.0.1 disks") — it ships as `A2.RAMCard` on Disk 3. → **buildable-asm**
  (build-verify in P4).
