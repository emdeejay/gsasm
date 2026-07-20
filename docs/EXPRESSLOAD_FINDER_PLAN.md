# Finder DATA-fork byte-exact rebuild — implementation plan

> Produced 2026-07-20 by a read-only multi-agent reverse-engineering workflow
> (7 decode agents -> synthesize -> 3 adversarial critics -> finalize, Opus 4.8/1M).
> Status: PLAN ONLY, not implemented. The code images + ~JumpTable are already
> byte-exact (work/finderdatacheck.py, FINDER_DATA_CODE_BYTES 135444/135444);
> this plan closes the per-segment RELOCATION DICTIONARIES + full-fork packaging.

---

# HARDENED FINAL PLAN — Finder DATA fork byte-exact rebuild (relocation dictionaries)

## EXECUTIVE SUMMARY

**Root cause (one sentence):** The 6 failing segments diverge because LinkIIGS omits the *low-word (size-2, shift-0) relocation whenever its target segment is bank-aligned* — and the FINDER main segment is the file's only bank-aligned segment (KIND 0x1100), so both its own same-segment low words and every other segment's low-word references *to* it must be suppressed, which the current builder does not do.

**Derived rule (one paragraph):** Cross-segment record type is a *pure* function of `(size,shift)`: `(2,0)→INTERSEG2`, `(2,16)→INTERSEG2^`, `(3,0)→INTERSEG3 (SUPER-2)`, `(4,0)→standalone cINTERSEG (image zeroed)`. Same-segment is the same mapping to SUPER subtypes `0/25+S/1`, **except** flag-bearing "case-B" references (`+$80000000`/`+$C0000000`) become standalone RELOC/E2. Overlaid on both is one unifying suppression: **a `(size-2, shift-0)` low-word fixup whose *target* segment is bank-aligned (`KIND & 0x0100`) is load-invariant and is dropped entirely** — same-segment (kills subtype-0 and the case-B low half) and cross-segment (kills the would-be INTERSEG2 subtype `13+T`). Size-3/size-4 and all bank/high-word (`25+T`, shift-240) fixups to a bank-aligned target are *kept*.

**Consistency verdict:** The classification rule is **identical** for the byte-exact tools (015/016/018/020) and the Finder — not version-flagged. Verified this session: link_finder's site enumeration is *complete* (missing cross sites = **0** on every segment) and the entire cross-site discrepancy is 54 phantom low-word-to-FINDER refs, all removed by the one target-BankRel rule. No new version flag is required; the BankRel behavior is a KIND-bit rule.

**Scoping:** All new behavior is **opt-gated** and reaches only the Finder builder. The tools' `expressload()` path is byte-identical by construction (they pass none of the new opts). The single exception is `_het_entries` (the ExpressLoad directory), which the tools share — every edit there is fenced by tool-body fixtures + `toolcheck 015/016/018/020`.

**Confidence:** **HIGH** on the reloc rule — it is now empirically closed (subtype histograms, missing=0, all 54 phantoms one class, case-B pairing observed). The **single biggest remaining unknown is the ExpressLoad directory's `_het_entries` entry-body spill recurrence at N=13** (MEDIUM): the draft's "pointer-accumulation" fix is a proven no-op; the real defect is entry-body *sizing*, which is un-derived and shared with the tools. That is SPIKE-3 below and gates Stage 4 only; it does not touch the reloc work.

---

## WHAT THIS SESSION RE-VERIFIED (facts the plan now rests on)

Every number below was reproduced live (`scratchpad/finalize_spike.py`, `finalize_spike2.py`, `invariant.py`, `decode_reloc.py`).

1. **Combo scoreboard (baseline to beat):** the paste-ready recipe yields **151,444 B, EXACT 5/14** (BUFFERS, CONTROL, DATA, ~JumpTable, FIFIFIONE). ABOUT/Help are `reloc=ok` but `LCONST DIFF`. So the *task brief's* "8 exact / 6 reloc-only-diff" is **false** — 8 segments have wrong LCONST through the combo path. The plan is architected around this.
2. **link_finder produces byte-exact LCONST images for all 12 segments** (`FINDER_DATA_CODE_BYTES 135444/135444`) and its cross-site enumeration is **complete**: missing=0 on every segment; the only discrepancy is **54 phantom cross sites, all `size-2 shift-0 → FINDER`** (C1_PATHNAME×19, C1_FILENAME×17, TICONOBJ×10, AUXTYPE×2, C1_DEVICENAME×2, C1_TEMPPATH×2, EVENTREC×1, FILESYSID×1). Gold encodes **nothing** at those offsets (spot-checked: absolute/invariant). *This is the cross half of the BankRel rule, not a symbol-scoping problem.*
3. **Gold FINDER SUPER histogram** = `{1:255, 2:548, 16:38, 17:4, 19:1, 21:2, 22:10, 23:76, 24:10, 27:320, 28:38, 29:4, 31:1, 33:2, 35:52, 36:2}` — **subtype-0 absent, subtype-1 KEPT (255), subtype-27 own-bank KEPT (320)**. The draft's §A.4 "suppress subtype 0 **and** 1" was wrong. No segment anywhere emits subtype-15 (INTERSEG2 → seg 2), confirming cross low words to FINDER are dropped.
4. **Classification is NOT single-valued for same-segment** (`invariant.py`): same `(2,0)` splits `{SUPER-RELOC2:3289, RELOC:19}`; `(2,16)` splits `{INTERSEG2^:654, RELOC:21}`; `(4,0)` splits `{RELOC3:283, RELOC:1}`. The discriminator is **case-B** (flag addend). Cross-segment *is* single-valued per `(size,shift)`.
5. **case-B/E2 details:** VERIFY/CODE/ABOUT case-B come in **hi/lo pairs** (offset+0 shift-240, offset+3 shift-0, **both storing the identical full flagged value** e.g. `0xc0000433`). **INFO has one size-4 case-B** (`off=0xb3 size=4 shift=0 refoff=0x800010c5`) that the current `_scan_case_b` structurally cannot emit (guarded to `(2,0)/(2,16)` at line 505). **FINDER's 2 E2 are shift-240 only (no shift-0 partners)** — its case-B low halves were suppressed by the same BankRel rule.
6. **ExpressLoad directory:** gold `~ExpressLoad` carries `LOADNAME='Finder    '` at header[44:54] (confirmed); its own reloc dict is empty; the combo DIFF is entirely in header + LCONST (the HET entry table). The 13 gold entry pointers are `[130,187,245,302,357,415,471,527,582,637,698,754,809]` (deltas 57,58,57,55,58,56,56,55,55,61,56,55 — **not** flat), and these pointers are running sums of the emitted entry-body lengths.

---

## A. RELOC-HEURISTIC SPEC (the exact derived rule)

Segment numbering: `1`=~ExpressLoad, `2`=FINDER, `3`=BUFFERS, `4`=VERIFY, `5`=INFO, `6`=CONTROL, `7`=MATCH, `8`=ALERT, `9`=CODE, `10`=DATA, `11`=~JumpTable, `12`=ABOUT, `13`=Help, `14`=FIFIFIONE. `S`=site's own segnum, `T`=target segnum.

### A.1 SUPER ($F7) record format (confirmed — do not change)
```
+0  1  0xF7
+1  4  TOTAL (LE u32) = 1 + len(page_list)
+5  1  SUBTYPE (0..37; loader rejects >=38)
+6  N  page_list (N = TOTAL-1)
```
Page-list codec (`_encode_page_list`/`_decode_page_list`, already byte-exact): running 16-bit `PatchLoc` from 0; byte bit7=1 skips `(b&0x7F)` pages (no +1); byte bit7=0 gives `(b&0x7F)+1` one-byte offsets in the current page, then page auto-advances. **SUPER addresses offsets `< 0x10000` only** (16-bit PatchLoc). Max Finder LENGTH = FINDER's 0xF9BF (63,935), so no segment needs the ≥64K standalone path (see A.7); keep the existing `offset < 0x10000` gate anyway.

### A.2 Subtype formula (verified against every gold subtype this session)
```
0        RELOC2      size 2  shift 0     same-seg low word
1        RELOC3      size 3  shift 0     same-seg 3-byte pointer
2..13    INTERSEG3   size 3  shift 0     cross 3-byte; target segnum in image byte[2]
14..25   INTERSEG2   size 2  shift 0     cross low word;  target segnum = SUBTYPE-13
26..37   INTERSEG2^  size 2  shift -16   cross/own bank;  target segnum = SUBTYPE-25
```
Own-bank fixups ride `25+S` (FINDER→27, VERIFY→29, INFO→30, CONTROL→31, MATCH→32, ALERT→33, CODE→34, ABOUT→37 — all confirmed in the histograms). For a single-file link, all 3-byte cross-refs fold into ONE subtype-2 record (target segnum rides in image byte[2]).

### A.3 CLASSIFICATION RULE (cross is pure; same has a case-B split)
```
DETERMINE target class first:
  resolve site's symbol via link_finder's expmap (EXPORT-only scoping, =equ absolutes).
  '=equ' or nsyms>1  -> NO RECORD (link-time constant).
  dynamic target (KIND & 0x8000) -> route through ~JumpTable: T := jt_segnum,
      value := jt_jsl_offset(jt_index[(seg,off+addend)]); then apply CROSS rule.

CROSS-SEGMENT, STATIC (T != S, KIND & 0x8000 == 0):
  (2,0)   -> SUPER 13+T         [SUPPRESSED if target bank-aligned — see A.4]
  (2,16)  -> SUPER 25+T
  (3,0)   -> SUPER 2            (target segnum in image byte[2])
  (4,0)   -> standalone cINTERSEG($F6) size=4 shift=0, IMAGE BYTES ZEROED   *** the crux ***
  other   -> standalone cINTERSEG($F6)

SAME-SEGMENT (T == S), NON-flagged:
  (2,0)   -> SUPER 0            [SUPPRESSED if own seg bank-aligned — see A.4]
  (3,0)   -> SUPER 1
  (4,0)   -> SUPER 1            (4-byte rides a 3-byte patch; image byte[3]=0)
  (2,16)  -> SUPER 25+S         (own bank)

SAME-SEGMENT, case-B flagged (+$80000000/+$C0000000, value>0xFFFF):
  -> standalone RELOC/E2 (see A.6), NOT SUPER.

compressed vs full: use $F5/$F6 iff every stored field < 0x10000; else $E2/$E3.
(For the Finder, all targets < 64K -> only $F5/$F6/$E2 appear; $E3 is never exercised, A.7.)
```
**Crux (uncontested, confirmed):** there is no 4-byte SUPER-INTERSEG, so a `dc.l` cross pointer has no SUPER home → standalone cINTERSEG with a **zeroed** 4-byte image field. `link_finder()` already zero-fills those sites (finderdatacheck.py:270-271), so record and image agree automatically.

### A.4 THE UNIFIED BANKREL RULE (rewritten — this is the load-bearing correction)
> **A `(size-2, shift-0)` low-word relocation whose TARGET segment is bank-aligned (`KIND & 0x0100`) is load-invariant and is EMITTED AS NO RECORD** — applied to *same-segment* (would-be SUPER-0 and the case-B low half) **and** *cross-segment* (would-be INTERSEG2 subtype `13+T`).
> **Everything else to a bank-aligned target is kept:** SUPER-1 (subtype-1, 3-byte, bank byte relocates), INTERSEG3 (subtype-2, 3-byte cross), the bank/high word (`25+S` / `25+T`, shift-16), size-4 cInterseg, and case-B **hi** halves (shift-240).

FINDER (KIND 0x1100) is the only bank-aligned segment. This one rule, verified this session, simultaneously:
- makes FINDER emit **zero** subtype-0 while keeping subtype-1=255 and subtype-27=320 (the ~+4874 gap and its true cause);
- removes exactly the **54 cross phantoms** (all `size-2 shift-0 → FINDER`), after which `missing=0` — i.e. gold's cross set is reproduced exactly;
- drops FINDER's case-B **low** halves (its 2 E2 are shift-240 only), while VERIFY/CODE/ABOUT (non-bank targets) keep both halves.

**Do NOT** implement the draft's "suppress subtype 0 **and** 1" — gold keeps 255 subtype-1.

### A.6 case-B / standalone RELOC-E2 spec (ADDED — was missing from the draft §A)
41 same-segment E2 records span 6 segments (FINDER 2, VERIFY 4, INFO 1, CODE 8, ABOUT 24, Help 2). Rules, all confirmed:
- **Trigger:** the source reference carries a flag addend in the `{0x80000000, 0xC0000000}` family (NOT small negatives like `0xFFFFFFFF`/`0xFFFFFFFE` = `-1`/`-2`, which are ordinary relocatable refs — see the false-positive trap in SPIKE-2), and the resolved value `> 0xFFFF`.
- **Encoding:** E2 stores `refoff = the full flagged value` (e.g. `0xc0000433`), not `value>>16`.
- **Pairing (size-2 case-B):** each `dc.l`-width case-B emits **two** E2 — `(off, shift=240/-16)` for the hi word and `(off+3, shift=0)` for the lo word — both storing the identical full flagged value.
- **BankRel interaction:** if the target segment is bank-aligned, the shift-0 **lo** half is suppressed (FINDER keeps only the shift-240 hi halves).
- **size-4 case-B (INFO only):** one record `size=4 shift=0` storing the flag|offset (`0x800010c5`). The existing scanner cannot emit this — SPIKE-2 / §B change required.
- Ordering: standalone RELOC/E2 sort by ascending offset, interleaved with cINTERSEG (A.5).

### A.5 Record ORDER within a segment dictionary (already correct in gsasm)
```
LCONST ($F2, one record)
  -> ALL standalone records (cRELOC/RELOC/cINTERSEG/INTERSEG), ascending patch-site offset, interleaved
  -> ALL SUPER records ($F7), ascending SUBTYPE
  -> single END (0x00)
```
Verified on all 14 gold segments; `expressload.py:1961-1966` implements it.

### A.7 Dead branches for this artifact (state, don't validate)
- **$E3 (full INTERSEG)** and the **≥64K standalone** path are never exercised (all targets < 64K). The "compressed iff fields <0x10000" claim is *assumed*, not proven here.
- **cross `(2,8)` >>8 high-byte** is unexercised (zero such sites). Mark the A.3 "other → cINTERSEG" clause inert for the Finder.

### A.8 CONSISTENCY VERDICT
Rule is **identical** for tools and Finder — not version-flagged. `prove.py`/`tools.py` prove the **codec + ordering** round-trip on both corpora; the *classification* is validated end-to-end this session by link_finder's `missing=0` cross set plus the exact same-seg subtype histograms. The size-4-cross branch and the BankRel rule are simply *first exercised* by the Finder (no tool has a size-4 cross-ref or a bank-aligned target). The pre-existing `SUPER_CLASSES_APR93` flag (expressload.py:355) governs a *different* artifact (MountImageGS) and is not needed here.

---

## B. CODE CHANGES (dependency order)

### B.0 ARCHITECTURE — derive each dict from link_finder's site enumeration, inject via opts (RECOMMENDED)

The reloc dictionary is a deterministic function of **link_finder's per-segment site enumeration**, which this session proved *complete* (missing=0) and correctly-targeted (it produces byte-exact images). Build each segment's `(lconst_image, reloc_dict)` in `finderdatacheck` and hand them to `expressload()` through two new opts that bypass classification but reuse the proven framing / JT insertion / directory cascade:

- `opts['seg_images']  = {segname: bytes}` — pre-resolved LCONST body (overrides `_omf._build_body`).
- `opts['reloc_dicts'] = {segname: bytes}` — the complete per-segment record stream **including the trailing END** (overrides the entire scan+classification block).

When both are present, `expressload()` skips body-build and classification and calls `_make_output_seg(name, kind, segnum, seg_images[name], reloc_dicts[name], align)` directly, then runs its existing `~JumpTable` insertion + two-pass HET directory tail (2003-2049). **Tools pass neither opt → byte-identical path.**

**Where the records come from (single pass over link_finder's site list):** extend `link_finder()`'s in-image patch loop (finderdatacheck.py:247-282) to *record* each site as `(aoff, size, shift, target_class, T, flag)`, then classify per §A.3/A.4/A.6:
- **same-seg non-flagged** → `emit_super` subtype `0`(dropped if own seg bank-aligned)/`1`/`25+S`;
- **cross non-flagged** → `emit_super` subtype `13+T`(dropped if T bank-aligned)/`2`/`25+T`, or `emit_cinterseg` for size-4/other;
- **case-B flagged** → standalone `emit_reloc` per A.6 — **reuse `expressload._scan_case_b`** (extended to size-4, B.1a) for the *discriminator*, since the addend flag alone over-detects small negatives (SPIKE-2);
- **dynamic** → JT-route then cross rule with `T'=jt_segnum` (`jt_index`/`jt_jsl_offset` already computed at 196-204/267);
- assemble each dict: standalone (offset-sorted, interleaved) → SUPER (ascending subtype) → END.

**Why Option A over editing the combo classifier:** deriving records from the *same* enumeration that produces byte-exact images guarantees LCONST/record agreement (esp. zeroed size-4 sites) and reuses link_finder's proven EXPORT-only scoping — the combo classifier's resolution is weaker. **Fallback (Option B, G8):** inject `seg_images` only and fix the three classifier gaps in place (size-4-cross gate B.4; target-BankRel low-word suppression; size-4 case-B). Lower new-code surface (the classifier already emits byte-exact reloc for 8/14 incl. ABOUT/Help), but depends on the combo classifier having correct target segnums once LCONST is injected — **unproven**; that is exactly what SPIKE-1 decides.

### B.1 gsasm/expressload.py — injection hook (new, opt-gated)
- Near line ~1174 (where `super_classes` is read): add `seg_images = opts.get('seg_images')`, `reloc_dicts = opts.get('reloc_dicts')`.
- In the multiseg group loop (1493-2001): at the top of each iteration, if `reloc_dicts is not None`, look up this group's segment by `segnames_opt`, set `merged = seg_images[name]`, `super_records = reloc_dicts[name]`, and **skip** the body-build (§3b.1) and the whole classification block (1560-1957). Downstream (`_make_output_seg`, `_het_seg_meta`, JT insertion, directory) unchanged.
- Scope guard: strictly `if reloc_dicts is not None:` — tools pass neither opt.

### B.1a gsasm/expressload.py — `_scan_case_b` size-4 extension (447-506; guard at 505)
The current guard `_SUPER_TYPE.get((size,shift)) in (0,27)` excludes size-3/4 deliberately (to dodge the `0xFFFFFFFF` dispatch idiom). Extend to accept `size==4, shift==0` **only** when the flag is a genuine `0x80000000`/`0xC0000000` with a valid in-segment low offset (INFO `0x800010c5`), and **reject** small negatives (`0xFFFFFFFE`/`0xFFFFFFFF`) and the all-ones dispatch idiom. This is SPIKE-2; gate with the §F case-B fixture. Emits INFO's single size-4 E2.

### B.2 gsasm/expressload.py — directory bug A: `_het_entries` entry-body sizing at N≥7 (658-804) — SHARED CODE
**Reframed per critique (draft's diagnosis was a no-op):** the extra_block pointers *are* `body_start_offsets` = running sums of emitted body lengths (960; `cur_offset += len(entry_i)` at 752/777). So pointers cannot drift while bodies are exact — the drift means the **entry-body sizing** (the `partial1`/`entry_size`/spill formula at 697-723) is wrong for N=13, which also corrupts body *content*. The formula is empirically fit to the tools (comment 688-696: N=2/3/4/6) and the Finder is a new regime (13 entries, KIND-0x0002 `~JumpTable` firing *mid-chain* at 719, 0x8000 dynamics).
- **Action:** re-derive the N>1 suffix-spill / `entry_size` recurrence, validated at N=13 (SPIKE-3). Do **not** "fix pointer accumulation."
- **Shared-code fence (mandatory):** this is the *only* code path where a Finder change reaches the byte-exact tools. Fixture-lock the **full entry-body bytes** of all four tools 015/016/018/020 before/after (not just the Finder pointer list), and keep `toolcheck 015/016/018/020` + `tool_bytes 186110` green around every edit.

### B.3 gsasm/expressload.py — directory bug B: `~ExpressLoad` LOADNAME (`_build_express_seg`, ~981)
Gold directory carries `LOADNAME='Finder    '` at header[44:54] (confirmed); code hardcodes `b'\x00'*10`. Add opt `opts['loadfile_name']` threaded to `_build_express_seg`, space-padded (`b'%-10s' % name.encode()`). Load segments keep zero LOADNAME; tools pass no `loadfile_name` → default `b'\x00'*10` (unchanged).

### B.4 (NOT on the recommended path) size-4 cross gate — expressload.py:1747
Under Option A the classifier at 1747 is bypassed for the Finder → this edit is **not required**. It is proven **safe for the tools** (opening `if not jt_enabled and field_size>=4` to unconditional keeps 015/016/018/020 byte-exact — no tool has a size-4 cross-ref), so it is a valid *independent* cleanup, but it does **not** help the Finder on the combo path (resolution still wrong). Do not sequence it into the Finder work; do not call it "the fix."

### B.5 work/finderdatacheck.py
- **`build_finder_data() -> bytes`** returning the 146,924-B fork: assemble once, `_finder_import_wins`, `link_finder()` for images + `jt_entries`, build per-segment `reloc_dicts` (B.0), call `expressload(objs, opts={'multiseg':True,'segnames':…,'segkinds':…,'jt_entries':jte,'seg_images':images,'reloc_dicts':dicts,'loadfile_name':'Finder'})`.
- **dual-golden `GOLDENS`** (mirror findercheck.py:48-51): read **both** data forks — Start (`/System.Disk/System/Start`) and Disk-3 Finder (`{dc.DISKS}/Disk 3 of 7 SystemTools1.2mg`, path `/SystemTools1/System/Finder`, `fork='data'`) — and **assert `startA == finderB` directly** (loud failure on future divergence), then assert `build_finder_data()` equals each.
- **`main()`:** after the per-segment loop, `built=build_finder_data()`; assert `len==146924` and `built==g` for each golden; print `FINDER_DATA_BYTES_EXACT {good}/{total}` (→ `293848/293848`). Keep `FINDER_DATA_CODE_BYTES` as the code-image ratchet.
- **`--segdiff` harness** (D.2): per-segment `end2end/hdr/lconst/reloc` + reloc byte-delta, using the manual `$F7` walk (D.2/F6).

### B.6 work/diskcheck.py — Start dual-fork wiring (mirror EasyMount 251-256) — **wire LAST (Stage 5)**
```python
def _build_finder_data():
    import finderdatacheck            # lazy
    return finderdatacheck.build_finder_data()
SOURCE_BUILDERS[f'{V}/System/Start'] = _build_finder_data
```
Start is already `owner==REZ` with a live rsrc build; the dual-fork branch (340-347) fires additively, `n_wireable`/counter (352-362) +1. Disk-3 Finder is not in diskcheck's manifest; its equality is carried by B.5's dual-golden. **Landmine (F7):** the REZ/SOURCE branch does `built_ok += 1` unconditionally — wiring this *before* the fork is byte-exact yields `37/38` → **bad 0→1 = regression**. Do not land B.6 until Stage 4 is green.

### B.7 work/gate.py — metric registration
- In the `finderdatacheck` block (101-103) add `('finder_data_bytes_exact', r'FINDER_DATA_BYTES_EXACT\s+(\d+)/(\d+)', 'frac')`.
- `disk_logical_exact` (112-114) needs no code change; reads `38/38` after B.6.
- Baseline bumps (only when green, via the sanctioned update): `disk_logical_exact [37,0]→[38,0]`; add `finder_data_bytes_exact [293848,0]`. **Never run any check with `--update` during development.**

---

## C. STAGING (implement + validate in this order)

Baseline to beat: **combo 5/14 EXACT, 151,444 vs 146,924.** Every per-segment gate is **absolute** ("reloc byte-exact AND content match") — the combo deltas (`+4874`, `-68`, …) are artifacts of the abandoned classifier and must NOT be used as targets (F5).

### Stage 0 — Architecture go/no-go spike (SPIKE-1) — decides Option A vs B *before* build-out
- **Change:** `build_finder_data()` skeleton (B.5) + injection hook (B.1) + `--segdiff` harness. Emit reloc dicts from link_finder's site list (B.0) for **three HARD segments only**.
- **Verify (the real gate — not CONTROL):** reproduce byte-exact, from the injection source, the gold reloc dicts of **INFO** (crux + size-4 case-B + low-word-to-FINDER phantoms), **ALERT** (crux + phantoms, no case-B), and **FINDER** (BankRel suppression + case-B hi-only). Also keep the 5 already-EXACT segments EXACT and reproduce **CONTROL** (pure-SUPER control).
- **Decision:** if the three hard dicts reproduce → Option A validated, proceed. If the case-B or same-seg folding cannot be driven from link_finder's list → fall back to Option B (seg_images-only + in-place gap fixes) and re-run this same three-segment gate.
- **Expected:** architecture chosen; no full-fork byte change yet.

### Stage 1 — Resolution injection: all 12 LCONSTs byte-exact in the assembled fork
- **Change:** feed `seg_images = link_finder().images` through the hook.
- **Verify:** `--segdiff` shows `lconst=ok` for **all 14**; the LCONST-only failures (ABOUT, Help) and the 5 clean segments go/stay `reloc=ok`.
- **Expected:** EXACT 5 → **7** clean + ABOUT/Help now LCONST-ok (their reloc was already ok) → **9 EXACT**; remaining: FINDER, VERIFY, INFO, MATCH, ALERT, CODE (reloc), ~ExpressLoad (directory).

### Stage 2 — Apply the UNIFIED BankRel rule (§A.4) across ALL segments at once
This is one rule, not a FINDER-only late stage — it fixes FINDER's same-seg subtype-0 **and** every segment's low-word-to-FINDER phantoms simultaneously.
- **Change:** in the dict builder, drop `(size-2, shift-0)` records (same-seg subtype-0, cross subtype `13+T`, and case-B lo half) when the target segment has `KIND & 0x0100`.
- **Verify:** `--segdiff` — **FINDER** goes EXACT (subtype-0 `→0`, subtype-1 stays 255, subtype-27 stays 320; +4874 gap closed); the 54 phantoms vanish across VERIFY/INFO/MATCH/ALERT/CODE (`missing` stays 0). Confirm FINDER's full 16-subtype histogram matches gold (necessary, since a subtype-0-only check would pass even if subtype-1 were wrongly deleted).
- **Expected:** FINDER EXACT; the remaining 5 close to gold except their case-B / size-4 residue.

### Stage 3 — Cross crux + case-B: MATCH → ALERT → VERIFY → CODE → INFO
- **MATCH, ALERT** (crux only, no E2): with size-4-cross→cINTERSEG (A.3) + Stage-2 suppression → **EXACT**.
- **VERIFY, CODE** (crux + size-2 case-B pairs): reuse `_scan_case_b`; assert exact E2 counts (VERIFY 4, CODE 8) and pairing → **EXACT**.
- **INFO** (crux + **size-4 case-B**): land B.1a; assert the single `off=0xb3` size-4 E2 emits and no size-4 false positives from `-1/-2` addends → **EXACT**.
- **Verify:** each segment `--segdiff` EXACT; cross-record offset sets equal gold exactly (not "close").
- **Expected:** EXACT 9 → **13** (all load segments); only ~ExpressLoad remains.

### Stage 4 — ExpressLoad directory (SPIKE-3 + LOADNAME) — reloc-DEPENDENT, so LAST
- **Change:** B.3 (`loadfile_name='Finder'`), then B.2 (`_het_entries` N=13 entry-body recurrence). The directory content cascades from every prior segment's BYTECNT (= header+LCONST+**reloc**), so it can only close once all 13 reloc dicts are exact (G7).
- **Verify:** the **binding gate is the full `~ExpressLoad` byte-compare** (header+LCONST), not just the pointer list; plus the tool-body fixtures for `_het_entries` (B.2). `finderdatacheck.py` → `FINDER_DATA_BYTES_EXACT 293848/293848`, `built==gold`, `len==146924`.
- **Expected:** 14/14; full fork byte-exact.

### Stage 5 — Diskcheck + gate wiring (only after Stage 4 green)
- **Change:** B.6 + B.7.
- **Verify:** `diskcheck.py` → `logical-exact: 38/38`; `gate.py --full` all green.
- **Expected:** `disk_logical_exact 37 → 38`.

---

## D. VERIFICATION (the green-gate contract)

### D.1 Full green-gate contract — all pass, zero regressions
Run from `/Users/mdj/src/gsasm`:
```
python3 work/gate.py --full        # MANDATORY: only --full runs diskcheck
python3 work/buildrom.py           # rom == real (structural tripwire)
python3 work/diskcheck.py          # "logical-exact: 38/38"
python3 work/diskcheck.py --selftest
python3 work/easymountcheck.py     # PASS 9221B  (single-seg; unchanged)
python3 work/mountimagecheck.py    # 5750/5750   (single-seg; unchanged)
python3 work/toolcheck.py 015 016 018 020   # shared multiseg jt path + shared _het_entries
python3 work/finderdatacheck.py    # FINDER_DATA_CODE_BYTES 135444/135444 AND FINDER_DATA_BYTES_EXACT 293848/293848
```
Must-not-regress baselines: `tool_bytes 186110/0`, `fst_bytes 111584/0`, `driver_bytes 94948/0`, `disk_logical_exact` (37→38), `rez_easymount_data_bytes_exact 9221/0`, `mountimage_data_bytes_exact 5750/0`, `finder_data_code_bytes 135444/0`, `kernel_bytes 59049`, `p8_bytes 17128`, plus all obj/link/opcode/operand/rez/cdev/finder-rsrc metrics. Gate is direction-aware; **do not `--update` to clear it.**

### D.2 `--segdiff` harness (add to finderdatacheck.py)
Per segment print `end2end/hdr/lconst/reloc` + reloc-byte delta. Split via `header[:DISPDATA] + F2/len + LCONST[DISPDATA+5:+5+lcsz] + reloc[…]` (confirmed: each gold body is a single $F2 LCONST). Because each load segment carries its own BYTECNT, `iter_segments` walks the built fork even when the directory is wrong → load-segment reloc (Stages 1-3) is gate-checkable **independent of** the directory (Stage 4). Reuse `scratchpad/finalize_spike.py`'s `split_seg`.

### D.3 Manual $F7 walk for histograms (F6 — mandatory)
`omf.iter_segments(records=True)` **lumps** SUPER (reports 1 record for FINDER's 16). Any SUPER/subtype histogram or tool before/after diff MUST use a manual walk: `$F7; total=LE-u32@+1; subtype@+5; page_list=seg[+6:+5+total]` → `_decode_page_list` (as in `scratchpad/decode_reloc.py`). Add an assertion that the harness's per-record count equals the manual walk on a known gold segment.

### D.4 Shared-path regression guard
Injection is opt-gated ⇒ tools' path unchanged by construction; confirm empirically: decode Tool015/016/018/020 SUPER-2 page-lists before/after (identical histograms). The **only** shared-code hazard is `_het_entries` (B.2) — its guard is the tool-body byte fixtures (§F.7) + `toolcheck` + `tool_bytes 186110`.

---

## E. RISKS / UNKNOWNS / FALLBACKS

**E.1 [RESOLVED this session] The reloc rule.** The unified BankRel rule (A.4) + size-4 crux (A.3) + case-B (A.6) close the cross set exactly (missing=0, all 54 phantoms one class) and match FINDER's full subtype histogram. Residual: only one bank-aligned segment exists, so "target bank-aligned ⇒ drop low word" is inferred from N=1 — but it is triple-confirmed (same-seg subtype-0 absent, cross subtype-15 never appears, case-B lo halves absent) and structurally grounded (bank-aligned ⇒ 16-bit low words load-invariant). Confidence HIGH; no further spike needed.

**E.2 [SPIKE-1, Stage 0] Architecture: can the whole dict be driven from link_finder's site list?** Same-seg SUPER folding + case-B must reproduce byte-exact from link_finder's enumeration (which is a *superset* of gold fixups — CONTROL 225=225 exact, others carry extra absolute/suppressed sites). *Spike:* reproduce **INFO, ALERT, FINDER** (not CONTROL) byte-exact before build-out. *Fallback:* Option B (seg_images-only + in-place gap fixes).

**E.3 [SPIKE-2, Stage 3] size-4 case-B discriminator.** The addend flag alone over-detects: FINDER has size-4 sites with addend `0xFFFFFFFE` (`C1_PATHNAME-2`, ordinary cInterseg) that must NOT become E2, while INFO's `0x80000000` (pure flag) must. *Spike:* extend `_scan_case_b` to `size==4` accepting only `{0x80000000,0xC0000000}`-family flags with a valid in-seg low offset; assert INFO emits exactly its one `off=0xb3` E2 and FINDER's size-4 `-2` sites stay cInterseg. Fixture in §F.

**E.4 [SPIKE-3, Stage 4] `_het_entries` N=13 entry-body recurrence — the single biggest remaining unknown.** The draft's "pointer accumulation" fix is a no-op (pointers = running body sums); the defect is entry-body *sizing*. *Spike:* decode all **13 gold entry bodies** (whole `~ExpressLoad` LCONST) and derive the `partial_i`/`entry_size` rule (analogous to `partial1 = 29+len(SEGNAME)`) that reproduces the varying body lengths (deltas 57,58,57,55,58,56,56,55,55,61,56,55) — noting the mid-chain KIND-0x0002 `~JumpTable` entry (the 61-delta) and 0x8000 dynamics; also emit the N-3 pre-section SEGNUM table `[2..11]` (881). *Gate:* full `~ExpressLoad` byte-compare **plus** tool-body fixtures (shared code). *Fallback:* if the closed form resists derivation, compute each pointer from actual emitted body lengths and derive body content directly from the segment metadata table (still needs the correct suffix-template split — validate against the 13 gold bodies).

**E.5 [contingency] Version-dependence.** Not expected (A.8). If any Finder reloc behavior proved version-specific, gate it behind a per-build opt on the `SUPER_CLASSES_APR93` precedent (read once at ~1174, passed only by the Finder builder) so `disk_logical_exact` provably cannot touch 015/016/018/020.

---

## F. FIXTURES & DOCS (corpus-free `tests/test_*.py`, run first by the gate)

1. **SUPER subtype formula (A.2):** table-driven `(size,shift,same/cross,T)`→subtype for `{0,1,2,13+T,25+T}`, incl. `(4,0)`-same→1 and `(2,16)`-same→25+S.
2. **size-4 cross → standalone cINTERSEG, image zeroed (A.3 crux):** synthetic 2-seg `dc.l` cross-pointer; assert one `$F6` size-4, image `00000000`, no SUPER-2.
3. **Unified BankRel low-word suppression (A.4):** two synthetic segments — a bank-aligned (0x1100) target and a plain (0x1000) target — with same-seg `(2,0)`, cross `(2,0)`, cross `(3,0)`, cross `(2,16)` refs to each. Assert: bank target drops same-seg subtype-0 AND cross subtype `13+T`, **keeps** subtype-1, subtype-2, and `25+T`; plain target keeps all. This is the load-bearing rule — its fixture is the primary guard.
4. **case-B / E2 (A.6) — NEW:** (a) size-2 hi/lo pair storing identical flagged value; (b) size-4 single E2 for `0x80000000`; (c) **negative-addend rejection**: `LABEL-2` (`0xFFFFFFFE`) and the `0xFFFFFFFF` dispatch idiom emit ordinary records, not E2; (d) bank-aligned target drops the lo half.
5. **Record ordering (A.5):** mixed standalone + SUPER → LCONST → offset-sorted-interleaved standalone → ascending-subtype SUPER → single END.
6. **Page-list codec (A.1):** round-trip incl. a 127-page skip chain and a max-count page.
7. **`~ExpressLoad` LOADNAME (B.3):** `loadfile_name='Finder'` → header[44:54]==`b'Finder    '`; default → `b'\x00'*10`.
8. **`_het_entries` N=13 (B.2) — SHARED CODE, two guards:** (a) hard-code the gold pointer list `[130,187,245,302,357,415,471,527,582,637,698,754,809]` **and** assert each of the 13 entry *bodies* byte-for-byte (pointers alone don't pin the suffix-template split); (b) **tool-body immutability**: lock the full entry-body bytes of Tools 015/016/018/020 before/after — the one place a Finder-only change can regress byte-exact tools.
9. **Injection opts inert when unset (B.1):** `expressload()` output byte-identical with vs without `seg_images`/`reloc_dicts` unset (tool-path immutability).

**Docs:** record in a new `docs/EXPRESSLOAD_FINDER_PLAN.md` (or extend the `REZ_TYPES_PLAN` phase log): the unified BankRel low-word rule and its same/cross/case-B unification; the subtype formula; the corrected "combo premise false / resolution + 3 reloc behaviors" finding; the size-4 case-B discriminator; and the two directory bugs (LOADNAME + N=13 entry-body sizing). Update the `gsasm-handoff` memory once green (`disk_logical_exact 37→38`, new `finder_data_bytes_exact`).

---

## Files of record (absolute)
- `/Users/mdj/src/gsasm/gsasm/expressload.py` — injection hook (~1174; 1493-2001 top-of-loop); `_scan_case_b` size-4 (447-506, guard 505); `_het_entries` N=13 body sizing (658-804; extra_block pointers 960; SEGNUM table 881); `_build_express_seg` LOADNAME (~981); `_make_output_seg` (1013); rule anchors `_SUPER_TYPE`(289), size-4 gate(1747), SUPER-2(1767-1794), 13+T(1952), ordering(1961-1966); `SUPER_CLASSES_APR93`(355).
- `/Users/mdj/src/gsasm/work/finderdatacheck.py` — `build_finder_data()`, dual-golden `GOLDENS` (assert `startA==finderB`), `--segdiff`, `FINDER_DATA_BYTES_EXACT`; extend `link_finder()` patch loop (247-282) to record + classify sites.
- `/Users/mdj/src/gsasm/work/diskcheck.py` — `_build_finder_data` + `SOURCE_BUILDERS['{V}/System/Start']` (mirror 251-256; dual-fork branch 340-347) — wire LAST.
- `/Users/mdj/src/gsasm/work/gate.py` (101-103, 112-114) + `work/gate_baseline.json`.
- Precedents: `work/findercheck.py` (dual-golden 48-51), `work/easymountcheck.py` (dual-fork builder).
- Primary source: `/Users/mdj/src/gsasm/ref/GSOS_6/IIGS.601.SRC/GS.OS/Loader/Relocation.a` (`Do_SUPER`).
- Verified spikes (read-only, reuse): `scratchpad/finalize_spike.py` (combo scoreboard + true link_finder cross test + E2 details + HET header), `finalize_spike2.py` (site-completeness + case-B flag visibility), `decode_reloc.py` (per-segment gold histograms + `$F7` walk), `invariant.py` (classification split), `probe_phantom.py`/`xref.py` (mirror), `prove.py`/`tools.py` (codec round-trip), `final_verify.py`.
