# linkOS — the full kernel link (Start.GS.OS / GS.OS byte-exact) — 2026-07-07

Scoping of the M6 keystone: a **single** placed link of all GS.OS kernel
objects with a global symbol table, replacing kernelcheck's per-group links.
Unlocks Start.GS.OS (99.5%), GS.OS, GS.OS.Dev.

**Oracle: `python3 work/startgsos_diag.py`** — builds the current Start.GS.OS
residual, maps it, lists GQuit's imports, and tests a global-symtab seed.

## The authoritative recipe (`GS.OS/Scripts/linkOS`)

ONE `linkiigs -apw` call with 17 `-lseg` load segments, then `makebiniigs`
splits into `scm.bin.N`, then `catenate`:

    -lseg scm_seg_0  scm.obj(@start_seg0) scm.obj(@oscall_seg) scm.obj(@end_seg0)   # scm.bin(1)
    -lseg scm_seg_1  scm.obj(@start_seg1) scm.obj(@misc_seg)   scm.obj(@end_seg1)   # .2
    -lseg scm_seg_2  scm.obj(@start_seg2) scm.obj(@scm_main)   scm.obj(@end_seg2)   # .3
    -lseg scm_seg_3  scm.obj(@start_seg3) scm.obj(@system_svc) scm.obj(@end_seg3)   # .4
    -lseg scm_seg_4  scm.obj(@start_seg4) scm.obj(@bank_e1)    scm.obj(@end_seg4)   # .5
    -lseg b00segr    b00segr.s.obj bank0.obj b00segr.e.obj                          # .6
    -lseg be0segr    be0segr.s.obj device.dispatcher.obj be0segr.e.obj              # .7
    -lseg gquit.1    gquit.obj(@seg_gldr)                                           # .8  ┐
    -lseg gquit.2    gquit.obj(@seg_b0)                                             # .9  │ Start.GS.OS
    -lseg gquit.3    gquit.obj(@seg_e1)                                             # .10 │ = cat(8..11)
    -lseg gquit.4    gquit.obj(@seg_e0)                                             # .11 ┘
    -lseg cache      cache.obj                                                      # .12
    -lseg init.1..4  init1..4.obj                                                   # .13-.16
    -lseg terminator scm.obj(@terminator)                                          # .17

GS.OS = Loader.bin ++ cat(scm.bin, .2..7, .12..17).  Start.GS.OS = cat(.8..11).

## Placement mechanism (verified)

Kernel modules assemble to **org=0 relocatable** segments EXCEPT the ORG'd
header/pad anchors: `SEG_0_HEADER=$99d0 / SEG_0_PAD=$9a00 … SEG_2_HEADER=$cfd0
(→ scm_seg_2 content ≈ $d000) … SEG_4=$e1d950`.  Each `-lseg` group's header
ORG sets its base; the following content segments accumulate.  So a content
label's final address = its group's header-ORG + offset within the placed group.

`linkiigs._place` already jumps `base` to a segment's ORG when set and
accumulates otherwise; `_build_symtab` already computes `placed_base+offset`
across all objects and builds one global table (improved session 11).  **The
core machinery exists.** The gap is the *grouping/order*.

## Why kernelcheck's Start.GS.OS is 70 bytes off (3 causes — evidence)

Baseline: `startgsos_diag` → gold 13169B, ours 13169B, **70 diff bytes / 32 runs**.

- **(A) cross-module imports — the bulk.** GQuit `IMPORT`s 17 names (INIT_SCM,
  ADD_FST, DEALLOCATE, OS_EVENT, SET_PREFIX_33, CLOSE_ALL_FILES, SHUTDOWN_SCM,
  RESTART_SYSTEM, V_PTR1, …) defined in scm/bank0/device.  kernelcheck links each
  `-lseg` group in isolation (`_link_groups` + `gq_extern=_full_symtab(gquit)`
  which only covers GQuit's *own* symbols), so these resolve to 0/garbage.
  Evidence: `@0x027c gold 08d4 (=$d408 INIT_SCM) ours 0000`.  A global PLACED
  symtab is the fix.  **Naive union of standalone symtabs does NOT work** — a
  standalone scm.obj gives INIT_SCM=0 (segment-relative); it needs the value
  AFTER placement (scm_seg_2 header-ORG + offset ≈ $d408).
- **(B) GQuit's own `load_app PROC tempOrg $1010`.** Cluster `@0x2b46..0x2b8b`
  (gold `$10xx`, ours `$d8xx`).  Session-11's temporg flow-gate IGNORES temporg
  inside an ORG-flow region (it regressed Start.GS.OS −191 when applied naively
  in the *isolated* link).  In the *proper* placed link, load_app's labels must
  be `$1010+offset`.  Re-enabling temporg must be done together with (A), not
  before.
- **(C) ~5 CONST/reloc diffs.** `@0x1475 / @0x2c4c gold 0100 ours ffff`
  (a `#^Label`/`-1`-vs-`1` bank-word), a couple more.  Smallest; chase last.

## The build — linkOS driver + WPs

A new `linkOS` (likely `gsasm/linkos.py` + a `work/kernelcheck` rewrite of
`_build_scm_segments`) that:

1. **Assemble** all kernel objects (scm, bank0, device.dispatcher, gquit,
   cache, init1-4, the b00segr/be0segr header wrappers, terminator).  (Several
   have assembler gaps — SCM.src 135 `unknown op 'write'`, Loader.a IF/WHILE,
   Init1 Record/EndR — but the SYMBOLS GQuit needs must still be defined; verify.)
2. **Regroup** every segment into the 17 `-lseg` load segments per the recipe's
   `@loadname` selectors, IN ORDER.  ★ **CRUX — SOLVED, and it's a known general
   gap (Tier-2 #5).** INIT_SCM's gsasm LOADNAME is `'main'` (→ lands nowhere / at
   $136f) but must be `'scm_main'` (→ scm_seg_2 → $d408).  Root cause: gsasm's
   `SEG 'name'` is **one-shot** (sets loadname for only the NEXT PROC) but MPW's
   `SEG` **persists until the next `SEG`**.  Proof in SCM.src: `SEG 'scm_main'`
   @4882, `init_scm PROC` @5684, next `SEG 'system_svc'` @18879 — so INIT_SCM (and
   everything 4882-18878) is `scm_main` in MPW, `main` in gsasm.  **Fix = make the
   pending SEG loadname persist across PROCs until the next SEG/ENDSEG.**  This is
   the FOUNDATION of linkOS (correct `-lseg` grouping falls out of correct
   LOADNAMEs) AND retires kernelcheck's hand-built `_make_groups`.
   ⚠ BLAST RADIUS: `SEG` is used by the ExpressLoad tools (copybits.asm
   @MAINPart/@CopyBits, MenuMgr PopUpProc, etc.) — persisting the loadname changes
   their segment→load-group assignment, so it MUST be gated on the whole
   tool/FST/driver corpus (same discipline as WP1's equ-alias).  Check whether the
   tools rely on the one-shot behaviour (they may already emit an explicit SEG per
   group, in which case persistence is a no-op for them).
3. **Place** each group at its header ORG (reuse `linkiigs._place`; segments in
   group order so ORG jumps + content flow give correct bases).
4. **One global symtab** (`linkiigs._build_symtab`) across ALL groups →
   placed addresses; `defer_shifts=False` (kernel is fully resolved, no
   ExpressLoad).
5. **Resolve** every ref against it → GQuit's imports get $d408 etc.
6. **Split** into scm.bin.N (makebin gap-fill/headers already in kernelcheck's
   Layout A/B/C helpers — reuse).  Start.GS.OS = cat(8..11).

### Work packages
- **WP-K0 (foundation):** make `SEG 'name'` loadname PERSIST until the next
  `SEG` (the one-shot fix above).  General (Tier-2 #5); gate the whole corpus.
  Verify: standalone scm.obj now tags INIT_SCM's segment LOADNAME `scm_main`.
- **WP-K1 (core, the bulk of A):** on top of WP-K0, regroup by the 17 `-lseg`
  selectors + place + global-symtab so GQuit's cross-module imports resolve
  (INIT_SCM→$d408).  Retires kernelcheck `_make_groups`/`gq_extern` hacks.
  Target: Start.GS.OS 70→~10 diff bytes.
- **WP-K2 (B):** un-gate GQuit `load_app` temporg within the placed link
  (careful — see session-11 flow-gate; the placed link is the right context).
- **WP-K3 (C):** the residual `#^Label`/CONST bank-word diffs.
- **WP-K4 (GS.OS):** same global symtab for scm.bin.1-7,12-17 + fix Loader.bin
  (missing toolbox includes/AError, −204B).  GS.OS.Dev: NewDispatcher −132B.

## Gates (every WP)

    buildrom 1 / objcheck 36/61 / linkcheck 61   (ROM — linkos is NOT ROM-shared,
      but re-verify; a linkiigs change would ripple)
    toolcheck 102588 / fstcheck 50229 / drivercheck 47827   (unchanged)
    kernelcheck TOTAL ≥ 51871, Start.GS.OS ↑ from 13098/13169
    diskcheck logical-exact ≥ 10/26, PHYSICAL 100%
    work/startgsos_diag.py  — the per-cause oracle (70 → 0)

## Risk / notes
- linkiigs is shared by tools/FSTs/drivers (ExpressLoad path) — a placement or
  symtab change must keep those green (defer_shifts default True there).
- The `-apw` mode + `main`-loadname grouping is the reverse-engineering risk;
  the ORG map is derivable (header ORGs are in-source, gsasm evaluates them).
- kernelcheck's Layout A/B/C gap-fill + header logic is reusable as-is; linkOS
  changes only the *symbol resolution* (isolated → global placed), not the
  flat-image assembly.
