# Execution plan (2026-07-07)

Derived from `ARCHITECTURE_REVIEW.md` (+ §7 amendments) and
`ARCH_REVIEW_SECOND_CHAIR.md`. Sequenced work packages toward the goal —
**more byte-exact System-Disk files (10/26 now) while the core stays general** —
with each WP's files, gate, acceptance, risk, effort, and dependency.

## Sacrosanct gate (every WP, no exceptions)
`buildrom` byte-identical · `objcheck` 36/61 · `linkcheck` 61 · `toolcheck`
102588 · `fstcheck` 50234 · `drivercheck` 47827 · `kernelcheck` 51905 ·
`diskcheck` ≥10/26 PHYSICAL 100%. Plus the WP's own oracle. Revert on any regress.

## Sequencing principle
Guaranteed/in-flight wins before speculative ones; time-box the high-fan-out wall;
generalise the engine only where it needs no D2; defer everything D2-blocked. The
second chair's "reloc-tail first" is right on *fan-out* but it is the parked
case-B wall — so it is **time-boxed B**, not the opener.

---

## Phase 1 — finish the kernel link (Start.GS.OS → byte-exact)  [IN FLIGHT, highest confidence]

Already 70→36 diff bytes this session (WP-K0/K1). The remaining 36 are known
causes, not a wall. Flipping Start.GS.OS is the OS loader — high value — and it
completes the kernel-link work.

- **WP-1.1 — remaining cross-module imports.** Extend `kernelcheck._placed_symtab`
  to place **bank0** (`b00segr`) and **device.dispatcher** (`be0segr`) content
  groups (base = their header PAD ORG, same as SCM); resolve the last GQuit
  imports (`FORCE_GET_INFO`, `CALL_LAUNCHER`, the `E1_*`).  Files: `work/
  kernelcheck.py`.  Oracle: `work/startgsos_diag.py`.  Acceptance: those imports
  resolve; Start.GS.OS < 36 diffs.  Risk: LOW.  Effort: S.
- **WP-1.2 — cause C `#^Label` bank-word (@0x1475/0x2c4c).** gold `0100` / ours
  `ffff`. The second chair ties this to the `_defer_shifts` resolved-path fix
  (RATIONALISE P0/L1). Verify: is it a `linkiigs` resolved-shift bug or a GQuit
  data const?  Files: `gsasm/linkiigs.py`/`gsasm/link.py` (ROM-GATED) or
  `kernelcheck`.  Acceptance: 0x1475/0x2c4c match.  Risk: MED (ROM-shared).  Effort: S–M.
- **WP-1.3 — cause B GQuit `load_app tempOrg $1010` (@0x2b4x, ~13B).** Un-gate
  temporg *inside* the placed link (session-11 flow-gate ignores it; the placed
  context is where it's correct).  Files: `gsasm/asm.py` (the flow-gate) +
  `kernelcheck`.  Acceptance: 0x2b4x cluster matches; Start.GS.OS = 0 diffs →
  **diskcheck 11/26**.  Risk: MED (flow interaction — gate ROM+kernel).  Effort: M.

## Phase 2 — §3-kernel: lift the placement algorithm into the core  [generality win, no D2]

Once Phase 1 proves the recipe, promote the base+offset placement out of the
harness so it is general engine, not `kernelcheck` bespoke.

- **WP-2.1 — `linkiigs.link_placed(objects, lsegs, defer_shifts)`.** Move the
  `_placed_symtab`/group-base+offset logic into `linkiigs`; `kernelcheck` calls it
  with the recipe (recipe stays config).  Retires `_make_groups`/`_placed_symtab`.
  Files: `gsasm/linkiigs.py`, `work/kernelcheck.py`.  Acceptance: kernelcheck
  byte-identical output via the core helper; ExpressLoad/tool paths unchanged
  (they share `_place`/`_build_symtab`).  Risk: MED (linkiigs is tool-shared —
  gate toolcheck/fst/driver).  Effort: M.  Dep: Phase 1.

## Phase 3 — ExpressLoad reloc-tail as a CLASS  [HIGHEST fan-out, HIGH risk — TIME-BOXED]

> **OUTCOME (2026-07-08): STOPPED at the STOP condition.** WP-3.1 (survey) + WP-3.2
> (converter source) ran; the case-B standalone-RELOC flag is **PROVEN not
> source-derivable** — the ExpressLoad *converter* source is absent from the GS.OS
> 6.0.1 archive (only the runtime loader ships), and 0x80 vs 0xc0 has no structural
> predictor across the 30-record survey. WP-3.3 NOT implemented (would be per-tool
> bespokery). Oracle `work/reloc_survey.py`; full writeup in `expressload.md`.
> Dropped to Phase 4.

13/16 disk misses are `len < EOF`; Tool014 is 100% code-exact yet 20B short — the
residual is the ExpressLoad wrapper (standalone RELOC/cRELOC + HET tail). Case A
(`>>8` cRELOC) is done; case B (far-pointer pair, `0x80000000`/`0xc0000000`
relOffset flag) is parked as un-derived. Attack it as a **class**, not per-tool.

- **WP-3.1 — systematic reloc-tail survey.** Extend `work/reloc_diag.py` to dump
  EVERY standalone RELOC/cRELOC across the `len<EOF` files (Tool014/023/027/034,
  TS2/TS3) with (size, shift, offset, relOffset, flag) + the source construct at
  each site. Tabulate: what determines standalone-vs-SUPER, and the flag value.
  Files: `work/reloc_diag.py` (read-only).  Acceptance: a table + a hypothesis for
  the flag.  Risk: LOW (analysis).  Effort: S.
- **WP-3.2 — read the converter source.** `ref/GSOS_6/…/GS.OS/Loader/ExpressLoad/
  ExpressLoad.a` GENERATES these records — derive the flag/standalone rule from
  it, not by reverse-engineering bytes.  Acceptance: rule stated or "genuinely not
  in source".  Risk: LOW.  Effort: S–M.
- **WP-3.3 — implement (only if 3.1/3.2 crack it).** Emit the standalone records +
  flag in `gsasm/expressload.py`.  Acceptance: **Tool014 + Tool027 byte-exact**
  (→ diskcheck +2), Tool023 reduced, TS2/TS3/Tool034 helped.  Risk: MED.  Effort: M.
- **STOP condition:** if 3.1+3.2 don't yield a derivable rule, document precisely
  and drop to Phase 4 — do NOT reverse-engineer per-tool magic (bespokery).

## Phase 4 — GS.OS / GS.OS.Dev length + guardrails  [steady value]

- **WP-4.1 — GS.OS.**  Fix `Loader.bin` (missing toolbox includes M16/E16.*,
  `AError` pseudo-op; −204B) + apply WP-2.1 placed link to scm.bin.1-7,12-17.
  Files: `gsasm/asm.py` (AError), `work/diskbuilders/kernel_os.py`, `kernelcheck`.
  Acceptance: GS.OS len==EOF (55395) → **diskcheck +1**.  Risk: MED.  Effort: M.  Dep: 2.1.
- **WP-4.2 — GS.OS.Dev** (−132B): NewDispatcher missing code + SUPER records.
  Effort: S–M.
- **WP-4.3 — CI drift-check (the §3a downgrade).** Wire `work/mpwmake_probe.py`
  into a gate: assert TOOLMAP/FSTMAP/DRIVERMAP == parsed makefiles; fail on drift.
  Captures ~all §3a value at a fraction of the parser cost.  Files: `work/
  mpwmake_probe.py` (+ a check mode).  Risk: LOW.  Effort: S.  **Do anytime.**
- **WP-4.4 — generality gate.** CI grep of `gsasm/*.py` for source-symbol/address
  literals (like the audit) + document the §7 smell-test clause ("proxy for a
  gsasm-internal representational choice", e.g. Tool025 case-folding).  Risk: LOW.
  Effort: S.  **Do anytime.**

---

## Deferred (blocked or out of scope) — with unblock condition

- **§3-ROM (retire `linkrom` via `link_placed`)** — BLOCKED on **D2**. linkrom's
  `entry_seg` re-routing (`linkrom.py:136-141`) and local-yields-to-export
  precedence have no `linkiigs` representation. Unblock: build D2's per-reference
  scope model, then fold. Note: `linkrom.parse_map()` already reads
  `ref/gsrom3/tools.map.doc` (the recipe as data) — the reader half is nearly free
  once the engine can consume it.
- **D2 — symbol model with per-reference scope** — large; also unblocks
  ControlMgr L2/L4 (RATIONALISE). Do when a byte-exact target actually demands it
  (ControlMgr's remaining ~26 code bytes), not speculatively.
- **D1 — unify the four omf.py reloc detectors** — refactor, byte-neutral (proven
  by `p3_oracle`). Do opportunistically when next touching `omf.py`.
- **Full MPW-Make recipe parser** — beyond WP-4.3's drift-check; only if new
  components are added or the maps start drifting.
- **Drivers `AppleDisk3.5/5.25`** (−657/−258) — structural sizing drift; a Pro.FST-
  style dig, medium value.  **`~JumpTable` tools (Tool015/016/018)** — MPW-linker-
  generated cross-bank stub, not reproducible from source; OUT OF REACH.
  **Tool019** (@0x95c) — likely a source discrepancy; confirm then park.  **P8**
  (@0xc9) — M/X-flag + `$BFxx` cross-module; messy, low priority.

---

## Recommended order to work through
1. **WP-1.1 → 1.2 → 1.3** — flip Start.GS.OS (diskcheck 11/26). In flight, highest confidence.
2. **WP-2.1** — lift placement into `linkiigs` (the generality win; rides on Phase 1).
3. **WP-3.1 → 3.2** — time-boxed reloc-tail crack; **3.3** only if it cracks (else STOP).
4. **WP-4.1/4.2** — GS.OS / GS.OS.Dev length (diskcheck +1–2).
5. **WP-4.3/4.4** — guardrails; interleave anytime (they're cheap and lock the discipline).
6. Then reassess Deferred against whatever residual remains.

Success metric per phase = diskcheck logical-exact count up, all sacrosanct gates
green, and no new `gsasm/*.py` symbol/address literal (WP-4.4).
