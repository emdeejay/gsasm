# SCSI.Manager / SCSIHD.Driver full-file ExpressLoad residual — diagnosis

Read-only investigation. No repo files were modified; all patches described
below were applied in-process via monkeypatch in throwaway scratch scripts
under this scratchpad directory, never written to `gsasm/` or `work/`.

## 1. Reproduction

`work/drivercheck.py`'s `DRIVERMAP` entries for `SCSI.Manager` (11 source
files, `GS.OS/SupervisoryDrivers/SCSI.Manager(1meg)`) and `SCSIHD.Driver`
(13 shared source files, `GS.OS/Drivers/SCSI.Drivers`, `-d type=0`) were
rebuilt with the exact recipe `work/diskcheck.py._build_unidisk35_fullfile`
uses for `UniDisk3.5`: assemble every source file as its own `(obj_bytes,
asm)` object, call `gsasm.expressload.expressload(objects)` with no opts
(single-segment / `merge`-style output). Gold = the raw (still-ExpressLoad'd,
not de-expressed) DBIN files `ref/GSOS_6/driver_bin/SCSI.Manager#BB0140` and
`.../SCSIHD.Driver#BB013F`, which are byte-identical to Disk 1's own
`/Install/System/Drivers/{SCSI.Manager,SCSIHD.Driver}` forks (confirmed via
`a2til.prodos.Volume.read_file`, sizes 10150 / 17344 match exactly).

Confirmed exactly as reported:

| file | built | gold | delta | first diff |
|---|---|---|---|---|
| SCSI.Manager | 10158 | 10150 | **+8** | 0x64 (~ExpressLoad forward-pointer field) |
| SCSIHD.Driver | 17358 | 17344 | **+14** | 0x64 (same field) |

`~ExpressLoad` directory is `N=1` (single load segment `'main'`) for both —
confirmed via HET header decode (`N-1` word = 0), so the size delta is
entirely inside the `'main'` segment's own reloc-dictionary tail (the offset
0x64 divergence is a **downstream symptom**: the HET entry's
`reloc_start`/`code_start` fields are absolute file offsets, and they shift
because the reloc dictionary that follows the LCONST body is a different
size — not a bug in the HET encoder itself).

## 2. Structural diff, record-by-record (zero unclassified residue)

Decoded every OMF record (LCONST / cRELOC / SUPER page-lists via
`_decode_page_list`) in the `'main'` segment of both built and gold, for
both files.

**SCSI.Manager** — all three record TYPES and COUNTS match except SUPER
page-list *contents*:

```
SUPER type=0 (2-byte, shift=0):  built=514 offsets   gold=509 offsets
  only_in_built = 0x346, 0xe60, 0x1af2, 0x1e54, 0x1e68
SUPER type=27 (2-byte, shift=16, bank byte): built=16  gold=15
  only_in_built = 0xe5d
SUPER type=1, standalone cRELOCs: identical, no diff
```
5 + 1 = 6 spurious relocation offsets → +5 bytes (type 0, no new SUPER page
boundary) + 3 bytes (type 27, the extra offset 0xe5d falls on a page not
otherwise present, forcing a new page-count byte) = **+8 bytes exactly**,
matching the measured delta with **zero unaccounted bytes**.

**SCSIHD.Driver** — SUPER dictionaries are **byte-identical** between built
and gold (all three types, same offsets, same page-list bytes). The entire
delta is two spurious **standalone cRELOC records** the built output emits
that gold does not:
```
cRELOC (size=1, shift=0, offset=10254, relOffset=5)
cRELOC (size=1, shift=0, offset=10405, relOffset=3)
```
2 records × 7 bytes/cRELOC = **+14 bytes exactly**, again zero residue.

## 3. Root cause

Traced every flagged offset back to source (via `_scan_relocs`'s live ops
list) and grepped the defining source files:

| offset | file | symbol | resolved value |
|---|---|---|---|
| 0x346 | SCSIM.Entry | `MAX_CMD` | 5 |
| 0xe60 / 0xe5d | SCSIM.Mgmnt | `WORK_VARS_SIZE` | 89 (0x59) |
| 0x1af2 | SCSIM.Misc | `NUM_DEV_TYPES` | 2 |
| 0x1e54 / 0x1e68 | SCSIM.Misc | `WORK_VARS_SIZE` | 89 |
| 10254 / 10405 (SCSIHD) | SCSI Command Table / Main Driver | `C_LEN_LEN` / `C_BLK_LEN` | 5 / 3 |

Every one of these is declared with the **identical idiom**:
```
    EXPORT  max_cmd:equ
max_cmd  equ  (*-cmd_table)/2        ; SCSIM.Header

    EXPORT  work_vars_size:equ
work_vars_size  equ  *-scsi_variables  ; SCSIM.Variables

    EXPORT  c_len_len:equ
c_len_len  equ  *-start_tbl          ; SCSI Command Table
```
`EXPORT name:equ` — a **link-time numeric CONSTANT**, exported for other
files in the same driver to `IMPORT` and use as an immediate operand
(`cpx #max_cmd`, `PUSHLONG #work_vars_size`, `lda #num_dev_types`). This is
*exactly* the idiom the project already has a rule for — see
`gsasm/expressload.py`'s `_scan_relocs` docstring: *"a symbol that itself
resolves OUTSIDE the load seg — an exported absolute EQU like MIDISynth's
`XSHIFTOUT equ $E01E8C` — is dropped (gold emits no reloc)"* and
`_group_of`'s docstring citing TS2's `UserDummyTable equ $FE01EF` /
`OENDCALL4 equ $feffc2`.

**The bug**: that existing rule is implemented as a *numeric range check*
(`_scan_relocs`: `if sym_addr is not None and not (0 <= sym_addr <=
body_len): # absolute — no reloc`) — a **value-based proxy** for "is this an
EXPORT-EQU constant", not the true structural signal. It works whenever the
EQU's resolved value happens to be large (`$FE01EF`, `$E01E8C` — always
outside `[0, body_len)`). It silently fails when the EQU's value is *small*
(5, 89, 2, 3 here) and coincidentally falls inside `[0, body_len)` — the
exact SCSI-family case, since `MAX_CMD`/`WORK_VARS_SIZE`/`NUM_DEV_TYPES`/
`C_LEN_LEN`/`C_BLK_LEN` are all tiny table-size constants.

**Where the true signal is lost**: gsasm's own assembler *does* track this
correctly at the single-object level — `Asm.symtype[name]` is `'equ'` |
`'label'` | `'import'` (`gsasm/asm.py:476`), and `omf.emit_segment` uses it
to emit a genuine OMF **GEQU** record (opcode `0xE7`) for every
`symtype=='equ'` export, structurally distinct from the **GLOBAL** record
(`0xE6`) emitted for an address label (`gsasm/omf.py:1176-1180` vs
`:1242-1250`). But `gsasm/linkiigs.py::_build_symtab`'s pass (c), which
merges every object's GLOBAL/GEQU records into the flat cross-object symbol
table used by the reloc scan, throws the GEQU/GLOBAL distinction away:
```python
elif nm == 'GEQU':
    label = d['label']
    sym.setdefault(label, _omf._eval(d['expr'], sym))   # value only, no "kind"
```
By the time `expressload.py`'s `_scan_relocs`/`_scan_case_b` see the merged
`sym`/`body_syms` tables, a GEQU-sourced constant and a GLOBAL-sourced
address are indistinguishable ints — forcing the downstream numeric-range
heuristic, which is definitionally unsound (a small constant is still a
constant, regardless of what integer it equals).

## 4. Hypothesis test — confirms the rule, closes the residual

Monkeypatched (in-process only, scratch scripts, no repo edits)
`gsasm.expressload._reloc_weight` so a bare `symXX` reference whose folded
name is a *known EXPORT:equ name* (computed per-`expressload()`-call as
`{name.upper() for obj,a in objects if a for name in a.exports if
a.symtype.get(name)=='equ'}`) contributes weight **0** instead of 1 — i.e.
generalizes the *existing* "same-segment `End-Start` difference is a
link-time constant, no reloc" weight-folding rule (already in
`_reloc_weight`, used for exactly this purpose) to also fold in "this
operand is an EXPORT-EQU constant, no reloc", using the correct structural
predicate instead of the value-range proxy.

Result, full-file byte comparison against gold:

| file | before | after fix | note |
|---|---|---|---|
| SCSI.Manager | +8B, 6 spurious offsets | **reloc dictionary byte-identical to gold, file size exact (10150/10150)** | 1 unrelated pre-existing 1-byte diff surfaces elsewhere — see §6 |
| SCSIHD.Driver | +14B, 2 spurious cRELOCs | **BYTE-EXACT (17344/17344)** | |
| SCSICD.Driver | +14B (same bug, never gated before) | **BYTE-EXACT (14635/14635)** | shares `SCSI Command Table` |
| SCSIScan.Driver | +14B (ditto) | **BYTE-EXACT (9227/9227)** | ditto |
| SCSITape.Driver | +14B (ditto) | **BYTE-EXACT (18244/18244)** | ditto |

The three SCSICD/Scan/Tape drivers were **not previously known to have this
residual** — `work/drivercheck.py` only ever gated their DE-ExpressLoad'd
code image (`linkiigs.link(merge=True)`), never their full ExpressLoad'd
file. Testing them was not requested but fell out naturally since they share
`_SCSI_SHARED` sources with `SCSIHD.Driver`; all three had the *identical*
latent +14B bug and the *identical* fix closes all three to byte-exact. This
is strong independent corroboration that the rule (not a coincidence
special-cased to one file) is correct.

## 5. Cross-corpus safety — the naive global-set implementation is UNSAFE

Per the task's discipline, tested the same patch against every other
builder in the corpus that calls `gsasm.expressload.expressload()` for a
**full-file** (not de-expressed) comparison — these are the only callers
that actually exercise the SUPER/standalone reloc-dictionary scan the same
way:

`work/appdatacheck.py` (ControlPanel data), `work/easymountcheck.py`
(EasyMount), `work/expressloadcheck.py` (Start/QuickLogoff/Tool038/ATInit/
ATResponder/net-Start/CloseView, 85067/85067), `work/findercheck.py`
(Finder fork), `work/finderdatacheck.py` (Finder data, 293,848/293,848),
`work/installerdatacheck.py` (Installer data, 56163/56163),
`work/mountimagecheck.py` (MountImageGS — notably the `SUPER_CLASSES_APR93`
older-toolchain opt), and `toolcheck.build_tool035_fullfile()` (MIDISynth
Tool035, 29842/29842 — the file whose `XSHIFTOUT equ $E01E8C` is the
*original* falsifying case for the current value-range heuristic).

All of these stayed **byte-identical** before/after the patch — good, no
regression, and confirms the fix subsumes the existing large-value cases
(XSHIFTOUT etc.) rather than conflicting with them.

**However**, `work/diskcheck.py --disk 'Disk 1 of 7 Install.2mg'` (which
exercises `SOURCE_BUILDERS[.../TS2]` → `work/diskbuilders/toolsets.py
_build_ts2()`, a 3-output-group `obj_group` merge of ~60 separately-pulled
GSToolbox source files) **regressed**: `TS2: logical (data) differs at
0x88a` (was 37/37 logical-exact, became 36/37).

Root-caused this too: `_build_ts2()`'s ~60 file pulls collectively define
**37 names that are `symtype=='equ'` in one constituent file and
`symtype=='label'` (a real relocatable address) in a different constituent
file of the same merge** — e.g. `USERDUMMYTABLE`/`DUMMYTABLE` (ironically
the *same* names cited in the codebase's own docstring as the historical
motivating case for the value-range rule!), plus generic names like `MASK`,
`TEMP`, `NEXT`, `ERROR`, `RETURN`, `A1`, `A2`, `SIGN`, `SCAN` that many
independent GSToolbox source files happen to reuse as local labels. My
scratch patch computed the EXPORT-EQU set as one **flat name set unioned
across every object in the merge** — so a reference to (say) `DUMMYTABLE`
as a private label in file B got incorrectly zeroed out because file A
(elsewhere in the same 60-file merge) happens to `EXPORT DUMMYTABLE:equ` a
constant with the same folded name. This is a real, demonstrated collision
risk, not a hypothetical one.

**The correct, safe design must resolve equ-vs-label with the same
per-object PRECEDENCE `linkiigs._build_symtab` already uses for the symbol's
*value*, not a separate flat global name set.** Concretely:

- `_build_symtab`'s pass (b) (an object's own interior labels — first
  priority) and pass (c) (cross-object GLOBAL/GEQU records — fallback,
  `setdefault`/override per existing single-vs-multi-object rules) already
  establish a strict precedence for *which definition wins* when a name is
  ambiguous. A parallel **kind** table (`sym_kind: dict[str,'equ'|'label']`,
  `obj_kind: list[dict[str,...]]`) must be threaded through those exact same
  passes, at the exact same precedence points, so that whichever definition
  the VALUE resolution picked is also the one the KIND check consults —
  guaranteeing no name-string collision across unrelated files, because a
  same-object private label always shadows a cross-object EXPORT-EQU of the
  same name (exactly like it already does for the value itself).
- Confirmed empirically that this precedence is what's needed: Tool035
  (MIDISynth, real per-file objects, no `obj_group` combining) had **no**
  collisions and passed cleanly; TS2/TS3 (also real per-file objects via
  `obj_group`, but ~60 files with many short/generic local label names) is
  exactly the case where a same-name cross-file collision occurs and a
  scoped/precedence-respecting kind lookup is required.

## 6. Separate, unrelated finding (SCSI.Manager only — not this bug)

After applying the fix, SCSI.Manager's reloc dictionary and file size are
100% correct, but **one single body byte still differs** from gold, at file
offset `0xf35` (merged-body offset `0xea6`): built encodes the low byte of a
`jmp badmin` target as `0x59`, gold as `0x00` — i.e. the two builds resolve
the address of label `badmin` differently at this one call site. `badmin` is
both `ENTRY badmin` (SCSIM.Mgmnt line 96) and later `EXPORT badmin`
(line 1879) — a **duplicate ENTRY+EXPORT of the same name inside one
object**, the precedence rule `asm.py:3031-3050`/`_all_exports` already
tries to handle. This is a completely different, pre-existing bug (address
resolution for a same-object dual ENTRY/EXPORT label, not GEQU/reloc-dict
classification) that happens to be masked by/entangled with the file-size
delta this task was scoped to. It does **not** affect SCSIHD/CD/Scan/Tape
(they reach full byte-exactness with just the reloc-dictionary fix) and
should be filed as separate follow-up work, not folded into this fix.

## 7. Proposed fix (not implemented)

**Where**: `gsasm/linkiigs.py::_build_symtab` and `gsasm/expressload.py`.

1. In `_build_symtab`, alongside `sym`/`obj_globals`, build a parallel
   `sym_kind: dict[str, str]` (values `'equ'`/`'label'`) and
   `obj_kind: list[dict[str,str]]`, populated at the **same three passes,
   same precedence** as the value tables:
   - pass (b): an object's own interior label → `'label'`.
   - pass (c) GLOBAL record → `'label'`; GEQU record → `'equ'` — same
     `setdefault` (single-object first-wins) vs override (multi-object
     last-wins-for-EXPORT) rule already coded for `sym`.
2. Thread `sym_kind`/`obj_kind` (or a per-segment resolved `body_kind`
   parallel to today's `body_syms`) into `_scan_relocs`, `_scan_case_b`,
   `_scan_standalone_relocs`, and the `_reloc_weight`/`_needs_reloc` call
   sites in both `_build_single_output_seg` and `_build_multiseg_output`
   (single- and multi-segment paths both need it — SCSI files exercise
   single-seg, TS2/TS3 exercise multi-seg/`obj_group`).
3. Extend `_reloc_weight(ops, kind_lookup)`: when a `symXX` tag's name
   resolves (via the SAME precedence as its value) to kind `'equ'`,
   contribute weight `0` instead of `1` — folding into the *existing*
   constant-weight mechanism (already used for the same-segment
   `End-Start` case) rather than adding a new independent code path.
4. This can plausibly **replace** the current `0 <= sym_addr <= body_len`
   value-range check in `_scan_relocs`'s absolute-EQU-drop logic entirely
   (the structural check is strictly more correct and, per §5, does not
   change any of the large-value corpus files it currently protects) — but
   keep both as a belt-and-suspenders overlap until proven, since the
   value-range check may also catch cases with no reachable GEQU record
   (e.g. a caller-supplied `extern` absolute value with no OMF GEQU behind
   it at all).

**Fixture** (corpus-independent, no golden binary needed): two tiny
hand-written source files fed through `expressload([...])` directly —
File A: `EXPORT small_const:equ` / `small_const equ 3` (deliberately small,
so it lands inside the merged body's byte range — reproducing the exact
coincidence that hid this bug) and, separately, a same-named **local**
label `small_const` (no EXPORT) inside an unrelated File C in the same
merge. File B: `IMPORT small_const` / `lda #small_const` (2-byte, exercises
the SUPER path) and, under `longa off`, a second `lda #small_const` (1-byte,
exercises the standalone-cRELOC path, mirroring SCSIHD's `C_LEN_LEN`/
`C_BLK_LEN`). Assert: (a) neither immediate-load site emits ANY reloc
record (SUPER or standalone) — only the baked literal `3` in the LCONST
body; (b) File C's own reference to its private `small_const` label DOES
still get a normal relocation (the collision-safety regression case TS2
exposed).

## Files/scripts used (scratch only, not committed)

- `.../scratchpad/build_scsi.py`, `decode_het.py`, `decode_reloc2.py`,
  `diff_offsets.py`, `probe_scsi_mgr.py`, `probe_scsihd.py`,
  `probe_ea6.py` — reproduction + structural decode (§1–§2, §6).
- `.../scratchpad/validate_fix.py`, `validate_fix2.py`, `run_patched.py`,
  `probe_ts2b.py`, `probe_tool035.py` — hypothesis test + cross-corpus
  safety check (§4–§5), all via in-process monkeypatch, no repo files
  touched.
