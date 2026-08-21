# Contract: ExpressLoad relocation semantics (single vs multi-segment)

*Slate item 2 of `docs/ARCHITECTURE_REVIEW_2026-08-02.md` (finding 2).  Written
2026-08-21 against `gsasm/expressload.py`, `gsasm/linkiigs.py`, and — as the
normative anchor — the GS/OS System Loader v4.00 source in
`ref/GSOS_6/IIGS.601.SRC/GS.OS/Loader/`.*

**Who this is for.** You are holding a new relocation discovery: a golden file
disagrees with gsasm in its reloc dictionary or in the code image at a
relocated site, and you have worked out what MPW LinkIIgs/ExpressLoad actually
did.  Before you write the fix you must decide **which of gsasm's reloc
producers it belongs to** — there are three, they encode genuinely different
functions, and applying a rule to the wrong one has already cost this project
one gate-caught regression (TS2, §4 D1) and one month-late diagnosis
(SCSI.Manager, §4 D3).  §5 is the routing rule.  Everything before it is the
model you need for §5 to mean anything; everything after it is the shared
surface you must not fork, and the call graph the review named.

**Status of the claims.** Every statement about the *loader* is quoted or
paraphrased from the source named at that point and marked **[LOADER]** — that
source is the runtime decoder of everything these paths emit, so it is a
specification by construction (`docs/GROUNDING_2026-08-02.md`).  Every
statement about *why gsasm does X* names the golden artifact that forced it and
is marked **[GOLD]**.  Two divergences — D8 and D9 — were forced by nothing at
all and were marked **[UNFORCED]**: hazards, not contract.  Both were **closed
in 0.6.0** and their sections now record what was done and why; no divergence
in this document is unforced today.

---

## 1. The loader's model, which is the only thing that matters

A load file is a sequence of OMF load segments.  The loader gives each segment
its own load address (`CAddress` in `Relocation.a`) and then replays that
segment's relocation records against its own image.  **Every relocation record
is an instruction of the form "take some base address, add a stored offset,
optionally shift, store N bytes here."**  The only variable is *which base*.

### 1.1 The record vocabulary  **[LOADER]**

`Loader.Equates`:

```
END  EQU $00   RELOC EQU $E2   INTERSEG EQU $E3   DS EQU $F1
LCONST EQU $F2   cRELOC EQU $F5   cINTERSEG EQU $F6   SUPER EQU $F7
```

| record | base added | offset source | width of stored offset |
|---|---|---|---|
| `RELOC`/`cRELOC` | this segment's `CAddress` | the **record's own** `Value` field | 4 / 2 bytes |
| `INTERSEG`/`cINTERSEG` | the **named** segment's load address | the record's `SegOffset` field | 4 / 2 bytes |
| `SUPER` type 0/1 | this segment's `CAddress` | **read back out of the code image** | 2 / 3 bytes |
| `SUPER` type 2–13 | file `type-1`, segment named by the image's own 3rd byte | image, 2 bytes | 3 bytes |
| `SUPER` type 14–25 | segment `type-13` | image, 2 bytes | 2 bytes |
| `SUPER` type 26–37 | segment `type-25`, result shifted `-16` | image, 2 bytes | 2 bytes |

The `SUPER` rows are Apple's own comments in `Do_SUPER` (`Relocation.a`),
transcribed with their arithmetic intact — Apple writes the categories in terms
of `n`, the INTERSEG*n* index (`n = type - 1`), but the code branches on the
record **type**:

```
;        RELOC2 and RELOC3 records correspond to types 0 and 1
;        INTERSEG1-36 records correspond to types 2-37
...
;        n is 25-36  --  Number of bytes in patch = 2; File Number = 1;
;                        Segment Number = n-24 (type-25); Shift Count = -16
;        n is 13-24  --  Number of bytes in patch = 2; File Number = 1;
;                        Segment Number = n-12 (type-13); Shift Count = 0
;        n is 1-12   --  Number of bytes in patch = 3; File Number = n (type-1);
;                        Segment Number = in patch; Shift Count = 0
```

with `sec / sbc #25`, `sec / sbc #13` and `dec a` doing exactly that arithmetic
on the type byte.  Hence the two formulas the code writes as
`13 + tgt_segnum` and `25 + tgt_segnum`, and hence the fact worth internalising:

> **`SUPER` type 27 is not "the bank-byte type".  It is `25 + 2`: a bank-word
> relocation against load segment number 2.**  It is universal in
> single-segment output only because a single-segment ExpressLoad file's one
> load segment is always SEGNUM 2 (`_make_output_seg(..., 2, ...)` in
> `_build_single_output_seg`).  The same rule is why `linkiigs.link(super=True)`
> — which numbers its single plain segment 1 — must re-type 27 to 26
> (`tests/test_linkiigs_super_type26.py`).

Two further loader facts that the code depends on and that are easy to lose:

gsasm only ever emits `SUPER` type **2** from that 2–13 band, because
`Common_INTERSEG` special-cases `FileNum == 1` — *"if = 1, use current File
Number instead"* — and every gsasm output is one load file.

- **`SUPER` reads its offset out of the image, `RELOC`/`INTERSEG` carry it in
  the record.**  `Do_SUPER`: *"extract segment offset and segment number (even
  if not there) of patch from memory"* — `lda [TempZero]` → `Offset`,
  `lda [TempZero],y` (y=2) `and #$FF` → `SegNum`.  So a `SUPER`-covered site's
  **code image is load-bearing**: it holds the placeholder, and for the 3-byte
  class its third byte *is* the target segment number.
- **`Do_RELOC` adds the record's `Value` unmasked.**  `lda CAddress / clc / adc
  |Record+Value` — 32-bit, no masking.  That is what makes the case-B flagged
  addend (§3.3) representable in a `RELOC` and *not* representable in a `SUPER`
  page list, whose stored offset is bounded by the image field it lives in.
- **Shift is applied after the base add** (`Common_Reloc`), with `-16`
  special-cased to "take the high word".  A shift-16 record therefore stores the
  *whole* value and lets the loader take its high word — it does not store a
  pre-shifted value.

### 1.2 The page-list codec  **[LOADER]**

`Do_SUPER`'s byte loop, exactly as `_decode_page_list` / `_encode_page_list`
implement it:

- bit 7 set → skip: `and #$FF7F`, then `eloop1: xba / clc / adc PatchLoc` —
  advance `(b & 0x7f)` **pages**, *with no `+1`*.
- bit 7 clear → count: `Counter = b`, then `loop2` runs until `dec Counter /
  bmi`, i.e. `b + 1` one-byte in-page offsets follow; then `lda #1 / xba / adc`
  advances exactly one page.

### 1.3 KIND bits the two paths act on  **[LOADER]**

`Loader.Equates`: `Code_Segment $00`, `Data_Segment $01`, `Jump_Segment $02`,
`Init_Segment $10`, `Direct_Segment $12`, `BankRel_Segment %0000000100000000`
($0100), `Dyn_Segment %1000000000000000` ($8000).  `Common_Pass1_Check` masks
`Header.Kind and #%11111` to get the base type, confirming "low 5 bits = base
kind, high bits = independent flags".

- `$8000` (`Dyn_Segment`) is the *only* KIND bit either output path branches on:
  a reference into a dynamic group cannot name that group (it is not resident),
  so it is routed through the `~JumpTable` thunk instead (§3.4).
- `$0100` (`BankRel_Segment`) is **not** consulted by either output path.  It is
  consulted only by the third producer (§6) — `work/finderdatacheck.py` and
  `work/installerdatacheck.py`, which suppress low-word records for a
  bank-aligned segment.  If your discovery is BankRel-shaped, §5's routing sends
  you there and nowhere else *today*; see the hazard note in §6.

---

## 2. Path A — `_build_single_output_seg`: one segment, one base

**What it produces, in loader terms.** Exactly one load segment (SEGNUM 2)
whose image is every input object's every placed segment concatenated at joint
addresses.  At load time the loader will add exactly one base — `CAddress` —
to every relocated site.  There is therefore no such thing as an inter-segment
reference in this output: a symbol either lives inside this one segment (add
the base) or it does not (bake the value, emit nothing).

**The classification question is binary**: *does the loader need to add my base
here?*  It is answered from the referencing expression alone, before any image
byte is decided, by three layered predicates:

1. `_has_sym_ref` — a pure literal never relocates.
2. `_reloc_weight` — net relocation weight.  Weight 0 means the segment biases
   cancel and the expression is a link-time constant.  The one-or-three-term
   core is **documented algebra** (MPW Asm Ref p.31–33: same-segment
   opposite-sign relocatable terms "cancel the effect of relocation, thus
   producing an absolute value"); the ADD/SUB-chain and shift-riding
   generalisation is gsasm's own, corpus-anchored.
3. **Symbol KIND** — a `sym` whose `kinds` entry is `'equ'` contributes weight
   0, exactly like a literal.  A reference bound to an EXPORT-EQU is a
   link-time constant regardless of its numeric value.

`_scan_relocs` additionally applies a value-range fallback — a net symbol
address outside `[0, len(merged_body)]` is dropped — which predates the KIND
table and is kept for absolute externs with no OMF GEQU behind them.

**The image is immutable.** `merged_body = _merge_bodies(placed, bodies)` is
computed once and never written to.  Every value the loader will need is either
already correct in the image (a base-0 placeholder for a `SUPER` site) or
carried in a standalone record's own field.  This is the deepest structural
difference from Path B and the reason a suppression rule is safe here: dropping
a record cannot starve anything, because nothing downstream writes bytes.

**The vocabulary it can emit** is therefore closed: `SUPER` 0, 1, 27; plus
standalone `cRELOC`/`RELOC` for the two standalone cases (§3.2, §3.3).  It can
never emit `INTERSEG`, `cINTERSEG`, `SUPER` 2, `13+n` or `25+n` for n≠2.

---

## 3. Path B — `_build_multiseg_output`: N segments, N bases

**What it produces, in loader terms.** One load segment per output *group* (one
per input object, or per `opts['obj_group']`), each relocated independently at
its own `CAddress`, plus an optional linker-generated `~JumpTable`
(`Jump_Segment`, KIND `$0002`).  `_place` still lays every input segment out in
one **joint** address space; groups are then rebased to their own base 0.

**The classification question is ternary**: *does the loader add MY base,
ANOTHER group's base, or no base at all?*  KIND cannot answer it — `'equ'` vs
`'label'` says whether a symbol is relocatable, never *which segment* it is
relocatable against.  The answer comes from the target **address**, via:

```python
def _group_of(abs_addr) -> int | None      # group index, or None = absolute
```

three outcomes, three encodings, and — decisively — **two of the three also
rewrite the code image**:

| `_group_of(target)` | record | image mutation |
|---|---|---|
| `== group_g` (mine) | `SUPER` 0 / 1 / `25+own` | none (placeholder already right) |
| another group | `SUPER` 2 / `13+T` / `25+T`, or standalone `cINTERSEG` | **patch** the target-relative offset, and for `SUPER` 2 the target segnum into the image's 3rd byte |
| `None` (absolute) | **no record at all** | **bake** the final absolute value |

That third row is the crux of this whole document.  On Path B, *dropping a
record and finalising the image are the same act*, performed in the same
branch, on a site that must still be in the reloc list when control reaches it.

### 3.1 The six image mutations

`merged_arr` (mutable, unlike Path A's `merged_body`) is written in six places.
**Five** of them are inside the per-stype classification — phase 7,
`_classify_super_relocs`, where dropping a record and finalising the image are
the same act.  The sixth is **not**: case A has no `stype` at all (that is what
makes it case A, §3.2), and its mutation happens in phase 5,
`_emit_case_a_records`, which runs *before* phase 7 and also reads the image
back for its own intra-group `relOffset`.  The relative order of those two
phases is therefore load-bearing.  (This section said "all inside the per-stype
classification" when it was written; item 6 never was.)

1. `stype == 1`, cross-group: bytes 0/1 ← `off_in_tgt`, byte 2 ← `tgt_segnum`
   (the loader will read that segnum back — §1.1).
2. `stype == 1`, cross-group, `field_size >= 4`, no-JT: field zeroed, standalone
   `cINTERSEG`/`INTERSEG` emitted instead.
3. `stype == 0`, cross-group: bytes 0/1 ← `off_in_tgt`, record typed `13+T`.
4. `stype == 27`, `_group_of is None`: bytes 0/1 ← `(sym_joint >> 16) & 0xFFFF`
   — **the deferred `#^Const` shift being resolved**, and the only place on this
   path where that happens (§4 D3).
5. `stype == 27`, cross-group, no-JT: stored word re-based from the calling
   group to the target group.
6. Case-A cross-group (`_scan_standalone_relocs` loop): field zeroed before the
   `cINTERSEG` — *"the pre-patch placeholder is 0 (fully loader-computed from
   the record's own segno/segoff)"*.

### 3.2 Case A — no SUPER encoding exists

`_scan_standalone_relocs` flags any `(size, shift)` absent from `_SUPER_TYPE`:
the `>>8` high byte, the 1-byte `>>16` bank byte, and the plain unshifted
1-byte field.  A 1-byte patch field can never hold a 16/24-bit target offset
in-image regardless of shift, which is why MPW emits an explicit-relOffset
record for all three shapes.  Both paths call this scanner; they disagree about
what to do with the result (§4 D4).

### 3.3 Case B — the flagged addend

`_scan_case_b` flags a relocation whose *unshifted* target carries addend bits
≥ bit 24 — the source-level `#Label+$80000000` / `+$C0000000` filterProc and
hook-pointer conventions.  Such a target cannot ride a page list (the image
field would have to hold the flag), but `Do_RELOC`'s unmasked add carries it
perfectly (§1.1).  Both paths call this scanner, both remove the flagged
offsets from their `SUPER` lists afterwards (a site cannot be both), and both
emit standalone `RELOC`/`cRELOC`.  They disagree about the `relOffset` framing
(§4 D5).

`_scan_case_b`'s `(size, shift) ∈ {(2,0), (2,16)}` gate is **Do-Not-Touch**
(`docs/REFACTORING.md` §5): widening it to the whole `_SUPER_TYPE` table
re-admits the `dc.l routine-1` dispatch idiom, whose `ADD lit=0xFFFFFFFF`
two's-complement encoding is indistinguishable from a deliberate flag once the
symbol is unresolved for an unrelated reason.

### 3.4 `~JumpTable`

Layout is `Loader.Equates`-specified (`JE_UserID 0, JE_FileNum 2, JE_SegNum 4,
JE_Offset 6, JE_jsl 10`, 14-byte entries, 8-byte header, 4-byte trailer) and
already cited at `jt_jsl_offset`/`encode_jumptable`.  Path B routes any
cross-group reference whose target group has KIND `& 0x8000` through the
thunk's JSL.  Path A cannot reach this code and never will.

---

## 4. The divergences, one by one, with the artifact that forced each

`D8`/`D9` were the two marked **[UNFORCED]**: nothing golden demanded them and
nothing golden falsified them.  They were recorded so that the next person did
not mistake them for contract, and both were closed in 0.6.0 — D8 by rejecting
the option on Path B, D9 by giving Path B the same merge.  Their sections keep
the full reasoning, because *why* an unforced divergence was closed the way it
was is the part that does not survive in the diff.

### D1 — Reloc **suppression** mechanism: symbol KIND vs group membership

- **Path A**: `_scan_relocs(placed, super_classes, body_syms, len(merged_body),
  body_kinds=body_kinds)` — kind-aware.  An EXPORT-EQU reference is suppressed
  *at scan time* by `_needs_reloc`.
- **Path B**: `_scan_relocs(group_placed)` — deliberately kind-**blind**.
  Suppression happens *after* classification, as `_group_of(...) is None →
  continue`, in three independent branches (`stype` 1, 27 and 0).

**[GOLD] forcing A**: the SCSI driver family (`SCSIHD`, `SCSICD`, `SCSIScan`,
`SCSITape.Driver`, `SCSI.Manager`) — `MAX_CMD equ 2`-class constants small
enough to land *inside* the merged body's byte range, so the old value-range
proxy could not see them; +8 B / +14 B of spurious `SUPER` offsets and
standalone `cRELOC`s.  `docs/SCSI_RELOC_DIAGNOSIS_2026-08-01.md`, commit
`9d82fba`.

**[GOLD] forbidding the same rule on B**: `TS2`
(`/System.Disk/System/System.Setup/TS2`), body offset `0x88a`.  Threading the
same kind table into Path B's scan was tried *first*, in that same commit, and
regressed TS2 at body level; the gate caught it.  The mechanism is D1 ∧ D3:
`UserDummyTable equ $FE01EF` is referenced as `#^UserDummyTable`, so its site is
a `stype == 27` record whose `_group_of` arm (mutation 4 in §3.1) is the *only*
place the deferred `>>16` gets resolved to `$00FE`.  Kind-suppressing the site
at scan time deletes the record, the branch never runs, and the image keeps the
unshifted low word `$01EF`.  **Suppressing a record on Path B without
performing its bake is not an optimisation; it is data loss.**

### D2 — **Absolute-target** detection: value range vs address-in-group

- **Path A**: `0 <= (target - _addend_of(ops)) <= body_len`, using the *net
  symbol* address so that `dc.l Target-2` and `Target+$80000000` are not
  misread as absolutes.  A belt-and-braces overlap with D1's kind rule,
  retained for absolute externs with no GEQU record behind them.
- **Path B**: `_group_of(target) is None`.

**[GOLD] A**: Tool035 / synthLAB (Disk 6) — MIDISynth's `XSHIFTOUT equ
$E01E8C` reached from `cursor.asm`'s `jsl xShiftOut`; two spurious `SUPER`
type-1 records made the file 4 bytes long.  `tests/test_expressload_absolute_target.py`.
**[GOLD] B**: TS2's `UserDummyTable equ $FE01EF` and `OENDCALL4 equ $feffc2`
(`Patch2` `tl.asm`/`strip.asm`, `export NAME:equ`).  Before the `None` arm
existed, `$FE01EF` classified as "cross-group into the last group" and the site
was patched with `(addr - last_group_base) & 0xFFFF` = the observed `$A5EE`.

### D3 — **Const-shift** resolution (`_defer_shifts`' `abs_syms`)

- **Path A**: `_defer_shifts(recs, equ_names)` where `equ_names` is derived
  from that segment's own resolved kind table.  A right shift over only
  link-time constants resolves *now*.
- **Path B**: `_defer_shifts(recs)` — `abs_syms` defaults to `frozenset()`, so
  the shift always defers and the value is baked later by mutation 4.

**[GOLD] A**: `SCSI.Manager` body `0xe5d`, segment `SAVE_PTR`,
`dc.w work_vars_size>>16`.  Gold bakes `89 >> 16 = $0000`; gsasm stored the
unshifted `$0059` because this path called `_defer_shifts` without the GEQU set
that `linkiigs.link()` had always passed for exactly this expression (its
docstring cites `#work_vars_size>>16` by name).  Commit `4243c03`; this is the
diagnosis whose §6 wrongly blamed a `badmin` ENTRY+EXPORT bug — **there was
never a badmin bug**, and the addendum in
`docs/SCSI_RELOC_DIAGNOSIS_2026-08-01.md` withdraws it.
**[NOT FORCED on B, but load-bearing]**: Path B's omission is *not* an
oversight to be tidied — it is the precondition for mutation 4.  If you pass
`abs_syms` there you must verify that every absolute-target `#^Const` site
still ends with the correct high word, because the bake would then be doing
nothing and the resolution would be happening in `_omf._build_body` instead.
For an *absolute* equate the two mechanisms happen to agree numerically (both
produce `$00FE`); that coincidence is why this is a hazard rather than an
immediate failure.  See §7.

### D4 — Standalone (case-A) record **targeting**

- **Path A**: every case-A site becomes `cRELOC`/`RELOC` against the one
  segment.  `relOffset` is read back out of the merged image when `size >= 2`,
  except the `(2,16)` bank-byte class and the 1-byte class, which are
  re-evaluated *without* the tail shift against the owning segment's own
  object-local table.
- **Path B**: `_group_of(raw_target)` decides — `None` drops the record
  entirely (the image already holds the absolute), same group emits
  `cRELOC`/`RELOC`, another group emits `cINTERSEG`/`INTERSEG` **with the image
  field zeroed**, and a dynamic target routes through the `~JumpTable`.

**[GOLD] A**: `MountImageGS` — `f5 02 f0 0081 00f9`, a `(2,16)` `cRELOC` whose
image word is `0x0000` and whose relOffset is the full unshifted target
`NDAHEADER+249`; and `DES.aii`'s `lda #s1` / `lda #>s1` low/high-byte pointer
pair plus the EasyMount data-fork residual for the size-1 shift-0 shape.
**[GOLD] B**: Tool016 `ControlMgr` — the cross-segment placeholder is 0 and the
target is loader-computed from the record's own segno/segoff; `~JumpTable+0x12`
for the dynamic `Pics` segment.  Ordering: TS3 `INIT` emits size-4 `dc.l`
`cINTERSEG`s at `0x6e..0x106` *before* the `>>8` case-A records at `0x10e+`,
which is why both paths flush standalone records sorted by ascending site
offset rather than grouped by category.

### D5 — Case-B `relOffset` **framing**

- **Path A**: the full 32-bit flagged value verbatim, at merged-segment
  offsets.
- **Path B**: the flag is split off (`flag = val & 0xFF000000`), the clean part
  is rebased to the group (`flag | ((clean - group_base) & 0x00FFFFFF)`), and a
  **cross-group** flagged addend raises `ValueError` rather than guess.

**[GOLD] A**: Tool014 `WindMgr` — the far-pointer PEA pair was the sole
residual; 29,998/30,018 → 30,018/30,018 byte-exact.  Both halves store the same
flagged value; the shift-16 half is *not* the value shifted right 16.
**[GOLD] B**: TS3 `MAIN`, which reassembles `WindMgr/NewCalls.asm`'s
`myEventFilter+$80000000`, at `0x10514` — before that group's `cRELOC`s at
`0x12243+`, hence the shared ordering rule in D4.

### D6 — SUPER subtype **vocabulary**

- **Path A**: `{0, 1, 27}` only, and `27` is `25 + 2` (§1.1).
- **Path B**: `{0, 1}` intra-group; `13 + T` for a cross-group low word;
  `25 + T` for a bank word; `2` for a cross-group 3-byte far pointer (with the
  target segnum body-patched into the image); standalone `cINTERSEG` for the
  4-byte cross-group `dc.l` that cannot ride a 3-byte type-2 patch.

**[GOLD]**: Tool015/016/018 for `13+T` / `25+T` / JT routing; TS3 `INIT`'s 15
`SUPER`-type-28 patch-table entries, each reading `+662` (MAIN's joint base)
over gold until the cross-group store was rebased to the *target* group —
which is exactly what §1.1 says the loader requires, since it adds the
**target** segment's address to the stored word.

### D7 — Code-image **mutability**

Path A's merged body is final the moment it is built.  Path B's is a
`bytearray` under active revision by the classifier.  This is not a stylistic
difference: it is why D1's suppression rule is safe on A and lethal on B.

### D8 — `opts['super_classes']` is a Path A option, and Path B now **rejects** it

`SUPER_CLASSES_APR93` records a *toolchain-version* property: the 30-Apr-93
LinkIIGS that built the archived `MountImageGS` folds only the `(2,0)` class
into `SUPER` records and leaves the size-4 and `(2,16)` relocs as standalone
`cRELOC`s.  `_build_single_output_seg` threads `super_classes` into both of its
scanners; `_build_multiseg_output` calls `_scan_relocs(group_placed)` and
`_scan_standalone_relocs(group_placed)` with the default full set.  No
multi-segment target in the corpus was produced by that encoder, so nothing
forces or falsifies an Apr-93 *encoding* on this path.

Until 0.6.0 a caller passing `{'multiseg': True, 'super_classes':
SUPER_CLASSES_APR93}` got its `super_classes` **silently ignored**.  It is now
a `ValueError`, and the reason it is a rejection rather than a thread-through
is the §3.1 mutation table:

> Narrowing the class set moves a `(size, shift)` class **out of
> `_scan_relocs` and into `_scan_standalone_relocs`** — i.e. out of phase 7
> and into phase 5.  On Path A that is a pure *encoding* change (D4's two
> paths through an immutable image).  On Path B it is a **targeting** change,
> because phase 7's `stype == 27` / `_group_of is None` arm is the only place
> the deferred `#^Const` `>>16` is ever resolved (mutation 4; this path calls
> `_defer_shifts` with no `abs_syms`, D3) while phase 5's absolute arm just
> `continue`s with **no image write**.  Dropping `(2,16)` from the set would
> therefore leave every absolute-equate bank-word site holding the unshifted
> low word — TS2 `0x88a`'s exact regression shape, reached by another route.
> Mutations 1/3/5 stand in the same relation to `(3,0)`/`(4,0)`/`(2,0)`.

So honouring it is an unforced redesign of phase 5's targeting with no golden
artifact to gate it, which by §5 rule 2 is a type-(b) change and must be
driven by a discovery, not by an opt name.  A caller that genuinely needs
Apr-93 SUPER coverage on a multi-segment file is holding that discovery and
must gate it against gold.  `super_classes` is also now documented in
`expressload()`'s opts table, marked single-segment-only.

### D9 — ALIGN gap filling now reaches both paths

`_place` rounds a segment's base up to its header `ALIGN`.  Path A merges with
`_linkiigs._merge_bodies`, which zero-fills exactly those rounding gaps.  Until
0.6.0 Path B merged with `b''.join(group_bodies)` while still resolving each
body at `adj_seg_base = seg_base - group_base` — i.e. at the *rounded* base — so
a group whose second-or-later segment carried `PROC align` emitted an image
whose byte offsets disagreed with the addresses its own EXPRs *and its own
relocation records* were resolved against.

Phase 3 now calls the same `_merge_bodies`, over this group's placed tuples in
`indices` order.  `_merge_bodies` derives its origin as `placed[0][2]`, which
for that list is exactly the driver's `group_base`, so the gap it computes is
the group-relative one; and for a group with no such gap it is byte-identical
to `b''.join` (its own docstring).

**No corpus group has one.**  Established positively, not by absence of
symptoms: an out-of-tree `sitecustomize` hook wrapped `linkiigs._merge_bodies`
across a full `--full` gate and logged, per call, the caller, the first
SEGNAMEs, the per-segment `(ALIGN, gap)` pairs, and whether the result differed
from `b''.join(bodies)`.  **59** calls originate in phase 3 — groups of 1 to
322 placed segments — and every one reports `ALIGN 0` and `gap 0` at *every*
segment, hence `differs=False`.

The measurement is not vacuous, because `PROC align` *is* live in this corpus:
**AppleDisk5.25** (`ref/GSOS_6/…/GS.OS/Drivers/AppleDisk5.25/AppleDisk5.25.src`)
declares `align 256` on `driver_data`, `rdadr16`, `read16`, `write16` and
`format16`, and its 22-segment link is the **only** artifact in the gate whose
merge fills anything — 173, 12, 22 and 9 zero bytes.  It reaches
`_merge_bodies` twice, through `linkiigs.link` and through Path A's
`_build_single_output_seg`, and never through Path B.  That is the whole shape
of D9: the one aligned artifact is single-segment, so the multiseg path was
never asked the question it was answering wrongly.

The trap is pinned corpus-free by `tests/test_expressload_multiseg_align.py`:
a 3-byte segment followed by an `align 16` one, in one multiseg group.  Before
the fix that group's image was the 6 bytes `11 22 33 aa 10 00` while the `dc.w`
stored `$0010` and the SUPER record named offset `$11` — both past the end of
a 6-byte image.

### D10 — Symbol tables for re-evaluation

- **Path A**: one table per placed segment, `{**sym, **obj_globals[oi]}`, in
  joint/absolute space; used for both body building and reloc re-evaluation.
- **Path B**: **two** table families.  `adj_sym` / `_adj_og` are group-relative
  (every placed address inside the joint span shifted by `-group_base`, every
  absolute equate deliberately left alone) and build the body.  `grp_body_syms`
  is joint/absolute and classifies relocs.  Only Path B builds `_fallback_sym`,
  a union of every object's private table under `sym`, for combo groups whose
  pre-concatenated blobs give `_build_symtab` no `Asm` metadata.

**[GOLD]**: Tool018 `MAINPart` referencing `Pictures/pics.asm`'s
`SaveSomething` / `iStdComment` (both `PROC EXPORT`, present in neither `sym`
nor the referencing object's own table); TS2 `INIT`'s `QDCALLTABLE2` /
`ORIGBELLVECTOR`, which silently resolved to 0 and misclassified as same-group
when the classifier read group-adjusted image bytes back instead of
re-evaluating the expression.

---

## 5. THE ROUTING RULE

> **Classify your discovery by the question it answers, not by the file it was
> found in.**
>
> **(a) "Does this site need a relocation record *at all*?"** — a **suppression**
> rule, decidable from the referencing expression and the symbol tables alone,
> never mentioning another segment.  It belongs in the shared predicates
> (`_reloc_weight` / `_needs_reloc`) and reaches production **through Path A's
> scan calls only**.  On Path B the same rule must be re-expressed as a *late
> drop* — a `continue` inside the relevant `stype` branch, after `_group_of` —
> **and that branch must also perform whatever image write the dropped record
> would otherwise have supplied**.  Never thread a suppression table into
> `_scan_relocs(group_placed)`.
>
> **(b) "Which base does the loader add, and what must the image hold?"** — a
> **targeting** rule.  It is meaningless on Path A (there is exactly one base)
> and belongs exclusively in Path B's per-`stype` branches.  Any new `SUPER`
> subtype, any new inter-segment record shape, any new `~JumpTable` routing, and
> **any rule that changes a byte of the code image** is (b).
>
> **(c) "How is *one record* spelled?"** — an **encoding** rule: record layout,
> the page-list codec, `cRELOC`-vs-`RELOC` width promotion, the case-B addend
> convention, the standalone-before-`SUPER` ascending-offset order, jump-table
> thunk arithmetic.  These are genuinely shared, live in the module-level
> scanners and emitters, and changing one there **must** change both paths.  If
> you find yourself writing an encoding rule twice, you have mis-routed.
>
> **How to tell them apart, mechanically:**
>
> 1. Can you decide the rule without ever looking at another output segment's
>    base or number?  → (a) or (c).  If your rule's answer *names a segment*,
>    it is (b).
> 2. Does applying the rule change any byte of the code image?  → (b), always,
>    even if it also drops a record.  A rule that both drops a record and bakes
>    a value is (b) on Path B and (a) on Path A, and **must be implemented
>    twice, in different places** — that is D1/D3, and it is the shape that has
>    already regressed once.
> 3. Does the rule change the bytes of a record whose *set membership* is
>    already decided?  → (c).  Put it in the emitter or the scanner and let both
>    paths inherit it.
> 4. Is the rule about a `KIND` bit?  `$8000` is (b).  `$0100` (`BankRel`) is,
>    today, **neither** — it lives only in the third producer (§6); adding it to
>    Path B is (b) and adding it to Path A is (a), and neither has a golden
>    artifact behind it yet.
>
> **Then check the third producer.**  A discovery of type (a) or (b) about a
> *multi-segment* file must also be applied to `work/finderdatacheck.py` and
> `work/installerdatacheck.py`, which classify relocs themselves and inject the
> result past Path B entirely (§6).  Path B's code will not run for those forks.
>
> **Then prove the routing before you trust it.**  A rule routed to (a) that
> actually belonged to (b) will pass the fixtures and fail the gate at a body
> byte, not a record byte — that is the TS2 signature.  Run
> `python3 work/gate.py --full` and read `disk_logical_exact` and `tool_bytes`,
> not just `PASS`.

**Worked example, using the two receipts.**  *"An EXPORT-EQU reference must not
emit a relocation."*  Question (a): decidable from the expression + kinds, names
no segment → shared predicate, Path A scan.  Does it change an image byte?  On
Path A no — the body is immutable, and the const-shift half of the same rule is
handled separately by `_defer_shifts`' `equ_names` (D3).  On Path B **yes** —
the `#^Const` site's high word is baked by the very branch the suppression
would delete → so on Path B it is (b), already implemented as `_group_of is
None`, and must be left alone.  Routing done correctly, the fix is one line in
`_reloc_weight` plus one argument at each Path A call site.  Routing done
uniformly, TS2 loses a body byte at `0x88a`.

---

## 6. The third producer (do not forget it exists)

`_build_multiseg_output` has an opt-gated bypass:

```python
if reloc_dicts_opt is not None and bytes(_inj_name) in reloc_dicts_opt:
    merged        = seg_images_opt[bytes(_inj_name)]
    super_records = bytearray(reloc_dicts_opt[bytes(_inj_name)])
```

For a group named in `opts['reloc_dicts']`, **no body is built and no reloc is
classified** — the caller supplies both.  Two callers do:
`work/finderdatacheck.py` (Finder data fork, 13 load segments) and
`work/installerdatacheck.py` (Installer data fork).  Each contains its own
complete classifier with its own vocabulary — `13+T` / `25+T` / `2` /
standalone `cINTERSEG`, case-B, JT routing — *plus* the `BankRel_Segment`
($0100) suppression rules that neither Path A nor Path B implements:

- a bank-aligned segment's own `(2,0)` same-segment records are dropped;
- a `(2,0)` reference *into* a bank-aligned segment is dropped;
- the shift-0 low half of a case-B pair is dropped for a bank-aligned segment.

So the honest count is **three** reloc semantics, not two, and the third is the
only one that models `BankRel`.  When your discovery is of type (a) or (b) and
concerns a multi-segment file, grep `reloc_dicts` before you declare the fix
complete.  (Collapsing that classifier back into Path B is a legitimate 0.7.0
goal; it is not this document's claim that it should stay outside.)

---

## 7. What is genuinely shared, and must stay shared

Changing any of these changes both paths.  That is correct and intended; do not
fork them "for safety."

| shared surface | contract |
|---|---|
| `_SUPER_TYPE` `{(2,0):0, (3,0):1, (4,0):1, (2,16):27}` | the `(size, shift)` → *intra-segment* subtype map.  Path B rewrites 0/27 to `13+T`/`25+T` **after** this map; Path A never does.  A new `(size, shift)` class added here is visible to both. |
| `_get_shift`, `_has_sym_ref`, `_addend_of`, `_reloc_target_addr` | expression-shape utilities; no path-specific meaning. |
| `_reloc_weight` / `_needs_reloc` | the suppression predicate.  Path B calls them with `kinds=None`; that is the divergence (D1), not a defect in these functions. |
| `_scan_relocs`, `_scan_standalone_relocs`, `_scan_case_b` | the record **walkers**.  Both paths use them; the arguments differ (D1/D2/D8), the walking never does. |
| `emit_super` / `_encode_page_list` / `_decode_page_list` | the codec, verified round-trip against `de_express` and specified by `Do_SUPER` (§1.2).  **Defined in `gsasm/omf.py`** since 0.6.0 (SUPER is an OMF record and `omf.parse_records` decodes it); `expressload` re-exports the same objects, so every name here still resolves. |
| `emit_creloc` / `emit_reloc` / `emit_cinterseg` / `emit_interseg` | record layouts, `Loader.Equates` opcodes. |
| the width rule `offset < 0x10000 and value < 0x10000 → compressed` | applied identically in both paths, at three sites. |
| standalone-records-first, each block sorted by **ascending site offset** | **[GOLD]** the golden corpus's standalone records are offset-ordered regardless of case A/B or record type (TS3 INIT/MAIN, D4/D5). |
| case-B offsets are removed from the `SUPER` lists | a site cannot be both; both paths do this immediately after `_scan_case_b`. |
| `SUPER` records emitted in ascending subtype order, then one `END`; `reloc_size = len(records) - 1` | the `~ExpressLoad` HET's per-segment reloc size excludes the trailing `END`. |
| `_make_output_seg`, `_het_seg_meta`, `_build_het_lconst`, `_build_express_seg` | output framing; `BANKSIZE 0` for `Direct_Segment` ($12) KINDs, `0x10000` otherwise. |
| `jt_jsl_offset`, `encode_jumptable` | `Loader.Equates` `JE_*` layout.  Path A cannot reach them. |

---

## 8. The `_defer_shifts` call graph

`linkiigs._defer_shifts(recs, abs_syms=frozenset())` rewrites an EXPR whose
expression ends in a shift so the **stored** value is the un-shifted base-0
placeholder, and reports the shift as deferred.  `abs_syms` is the set of names
that are link-time **constants**: a shift over only those is not
placement-dependent and resolves now.  The `const_only` predicate is
Do-Not-Touch (`docs/REFACTORING.md` §5, Tool019).

There are **three** call sites in `gsasm/` and one in `work/`, carrying **three
distinct derivations** of `abs_syms` (the review's "three ways from two
files").  This section said "four in `gsasm/` and one in `work/`" and "all five
sites" when it was written; that was already stale — the walk collapse
(`93f8519`) deleted the fourth, the `stype == 27` symbol lookup that used to
re-walk the deferred records to find the EXPR at `abs_off`.  Phase 3 indexes
that once now, into `bank_sym_at`, off the RAW record; the equivalence
argument is the comment at that index's construction:

| site | `abs_syms` | what the caller expects |
|---|---|---|
| `linkiigs.link` (Pass 3, gated on `defer_shifts`) | every `GEQU` label across all placed segments, ∪ `opts['abs_extra']` upper-cased | Resolve const shifts now; defer genuine intra-segment `#^label` bank refs.  `abs_extra` additionally marks *inter-segment* targets as const so a cross-segment `LDX #(PICPROC>>8)` stores the **shifted** offset for its `cINTERSEG`, not the un-shifted low word a `SUPER` 27 would want. |
| `expressload._build_single_output_seg` (body loop) | `{n for n, k in local_kinds.items() if k == 'equ'}` — the per-object resolved kind table | Path A's D3: resolve `#work_vars_size>>16` to `0`.  Derived at the **same per-object precedence** as the body's own symbol values, which is why it is computed inside the loop and not once. |
| `expressload._build_multiseg_output` (body loop) | *(none — default `frozenset()`)* | Path B's D3: **always defer**.  The absolute-target high word is baked later by the `stype == 27` / `_group_of is None` branch.  Passing `abs_syms` here would move that resolution into `_omf._build_body` and leave mutation 4 writing a value that is already there — see D3's hazard note before you "fix" it. |
| `work/rezloadcheck.py` (`Launcher.Load` harness) | `abs_syms` computed locally from the GEQU set | Mirrors `linkiigs.link`'s plain-load-file semantics for a `LinkIIgs -x` golden. |

> `_defer_shifts` emits exactly one output record per input record with the
> same name and size (so identical body offsets) and rewrites an EXPR only by
> stripping the trailing `lit, >>, end` triple, which holds no symbol operand
> — so the FIRST `sym*` operand, all that lookup ever read, is the same in
> both bases.  That is why one raw-record walk can serve a deferred-basis
> consumer, and it is the property to re-check if `_defer_shifts` ever starts
> rewriting operands rather than trimming them.

**If you change `_defer_shifts`' signature or its `const_only` predicate, all
four sites change meaning at once.**  Path B's is the one whose correctness is
*not* legible from the function: it is correct only because of §3.1 mutation 4.

---

## 9. The pin

`tests/test_expressload_path_divergence.py` is corpus-free and asserts the
divergence itself, not just the outputs:

1. `_scan_relocs` **with** a kind table (Path A's call shape) suppresses an
   EXPORT-EQU site; **without** one (Path B's call shape) it does not.  If a
   future change makes the two agree, this fails by name.
2. Both paths nevertheless produce the *same* final image at a `#^AbsEqu` site
   — `fe 00`, the resolved high word — by different mechanisms: Path A via
   `_defer_shifts(equ_names)`, Path B via the `stype == 27` / `_group_of is
   None` bake.
3. Neither file emits **any** reloc record for those sites.
4. Path A's SUPER vocabulary is exactly `{0, 1, 27}` and `_SUPER_TYPE[(2,16)]
   == 25 + 2` — §1.1's identity, so that a `13+n`/`25+n` subtype appearing on
   Path A is caught as the type-(b) rule it would be.

The regression shapes it catches, both reproduced by monkeypatch during this
packet's research and both reverting the image word to the unshifted `ef 01`:

- kind-suppressing at scan level on Path B → **TS2 `0x88a`**;
- dropping `equ_names` from Path A's `_defer_shifts` → **SCSI.Manager `0xe5d`**.

It does **not** catch a *simultaneous* collapse (kinds threaded into Path B's
scan *and* `abs_syms` passed to Path B's `_defer_shifts`), because for an
absolute equate the two mechanisms agree numerically.  That combination is
still a Path B change of type (b) and must be gated against TS2/TS3, not
against this test.

---

## 10. Open items this contract does not settle

- ~~**D8 / D9** are unforced and unpinned~~ — **closed in 0.6.0**.  D8 is now a
  `ValueError` on Path B (and `super_classes` is documented in `expressload()`'s
  opts table), pinned by `tests/test_expressload_super_classes.py`; D9 now uses
  `_merge_bodies` on both paths, pinned by
  `tests/test_expressload_multiseg_align.py`.  What is still open is the
  *discovery* D8 refuses to guess at: whether a multi-segment file built by the
  30-Apr-93 encoder exists at all, and if one turns up, what phase 5 must do
  with the demoted classes' image writes.
- **`BankRel`** is modelled only in the third producer (§6).  Whether Path B
  should implement it — and whether Path A ever needs it — is undetermined; no
  single-segment golden exercises a bank-aligned KIND.
- The `else: final_relocs.setdefault(stype, ...)` arm at the end of Path B's
  classifier is unreachable given `_SUPER_TYPE`'s three values; it is defensive,
  and a new entry in `_SUPER_TYPE` would activate it silently with **intra**
  semantics.  That is a type-(b) trap: adding a `(size, shift)` class is not a
  Path-A-only change.
- The `~ExpressLoad` HET **compaction** formula (`entry_len = 51 +
  len(SEGNAME)`) remains cross-validated-empirical; the decoder walks
  per-segment pointers and is compaction-agnostic
  (`docs/GROUNDING_2026-08-02.md`).
