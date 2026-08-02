# Grounding hunt: gsasm linker/ExpressLoad empirical rules vs. held reference material

Date: 2026-08-02. Read-only research; nothing in the repo was modified.

## 0. Inventory of what documentation EXISTS in ref/

| Source | What it actually is | IIgs/OMF relevant? |
|---|---|---|
| `ref/MPW_3.0_Reference_Volume_1_1988.pdf` (676pp) | MPW 3.0 Shell/tools reference, **68K Macintosh only**. Zero occurrences of "IIgs"/"IIGS" anywhere in the extracted text. Chapter 10 "More About Linking" and Appendix H "Object File Format" describe the classic 68K `Link`/`Lib` toolchain and its OWN, textually-different object-record format (First/Last/Pad/Comment/Dictionary/Module/EntryPoint/Size/Contents/Reference/ComputedReference/... — 20 record types 0-19). This is **not** OMF (no SUPER/RELOC/GLOBAL/GEQU opcodes, no 0xE2/0xF7-style byte codes). |
| `ref/MPW_3.0_Assembler_Reference_1988.pdf` | MPW 3.0 Assembler reference, also 68K-only. 3 hits for "OMF" (p.258), but referring to the *same* 68K "Module Begin (entry) OMF records" / "Local Identifier OMF records" — i.e. Apple used the term "OMF" generically for the 68K MPW object format too; this is not the IIgs opcode-based format either. |
| `ref/gsrom3/system500.hfv` | A late (Mac OS 8.5-era, ~1998) MPW-GM CD image. Opens fine under `a2til.hfs.HfsVolume` (HFS standard, no caveats needed). Contains `/MPW-GM/MPW/Tools/{LinkIIGS,ExpressIIGS,MakeBinIIGS,DumpObjIIGS,AsmIIGS,...}` (binaries only, no source) and `/MPW-GM/MPW/Interfaces/{A,C}IIGSIncludes/*.Loader` (System-Loader *toolset call* equates — error codes and `_LoaderXxx` macros, not OMF format docs). `MPW.Help` (233,900 bytes, the on-disk MPW help database) has **zero** occurrences of "IIGS" — the IIgs cross-dev tools' help was never merged into this disk's consolidated Help file. No `*.doc`/`ReadMe`/`Notes` files exist anywhere near the IIgs tools folder. `LinkIIGS`'s resource fork has embedded diagnostic strings (`Duplicate symbol "%s" in LSeg "%s" OSeg "%s" and LSeg "%s" OSeg "%s"`, `Missing symbol - "%s"`) confirming duplicate/unresolved-symbol detection exists, but no prose describing the resolution *policy*. |
| `ref/GSOS_6/IIGS.601.SRC/GS.OS/Loader/*` | **The actual GS/OS System Loader v4.00 source** (by Lou Infeld / Greg Branche, Copyright Apple 1986-92) — `Relocation.a`, `ExpressLoad.a` (147KB), `Segments.a`, `Files.a`, `Struct.a`, `Loader.Equates`, etc. This is the **runtime consumer** of everything gsasm's linker/expressload emit: it decodes RELOC/cRELOC/INTERSEG/cINTERSEG/SUPER records and the on-disk `~ExpressLoad` directory. This is by far the highest-value find — genuine ground-truth source, not prose, but load-bearing and directly comparable byte-for-byte to gsasm's reverse-engineered encoders. |
| `ref/GSOS_6/IIGS.601.SRC/GS.OS/P8/Loader.Expansion.Notes` | A 1989 engineering note about expanding the **ProDOS-8 boot loader** code region (`.SYSTEM` bootstrap, `ram.n`/`mlisrc.aii`). Unrelated "Loader" — this is P8's boot-time loader, not the OMF/ExpressLoad System Loader. Not relevant to the mission's rules. |
| Everything else in `ref/GSOS_6/IIGS.601.SRC` (`*Release Notes*`, `*ReadMe*`) | App-level release notes for Finder/Installer/CloseView/etc — not toolchain-format documentation. |

**Bottom line on inventory**: neither PDF documents the IIgs OMF or LinkIIGS at all (they are exclusively 68K-MPW). The one on-disk resource that *does* fully ground gsasm's rules is the GS/OS System Loader source tree, which is a reference *implementation*, not a spec document — but for a byte-exact cross-check that is effectively as good as a spec, since gsasm and the Loader must agree byte-for-byte for real ExpressLoad files to actually load.

## 1. Rule-by-rule verdicts

### 1a. Linker duplicate-symbol resolution: first-definition-wins

**Verdict: DOCUMENTED** (68K MPW `Link`, not IIgs-specific, but same MPW toolchain family/generation — exactly the angle the mission asked about).

`ref/MPW_3.0_Reference_Volume_1_1988.pdf`, Chapter 10 "More About Linking" → "Resolving symbol definitions" / "Multiple external symbol definitions" (p. 291):

> "If the object files contain more than one definition for an external symbol, **the first definition is used, and all references are treated as references to the first definition.** This lets you selectively override entry points in libraries so that you can substitute new versions of code. When subsequent definitions are encountered, a warning is generated."

and immediately above it, on symbol lookup order:

> "If the linker finds a symbol, it will first try to match the symbol to a local symbol in the same file. If the name cannot be located, the linker will then look for it externally."

This is precisely gsasm's `linkiigs.py:_build_symtab` docstring claim ("Symbol resolution order — processed per object in link order so that first-definition wins (matching MPW LinkIIgs behaviour)") and its local-before-global precedence (`obj_globals[obj_idx]` consulted before the cross-object `sym` table). It is NOT IIgs-specific evidence (LinkIIGS itself is binary-only in our refs — its resource fork only confirms duplicate-detection exists via the string `Duplicate symbol "%s" in LSeg "%s" OSeg "%s" and LSeg "%s" OSeg "%s"`, with no resolution-policy prose), so treat this as strong *family* corroboration, not an IIgs-primary-source citation.

Also from Ch.8 "The Build Process" ("Linking multilingual programs", p.246): "Normally it doesn't matter which of the duplicate copies of a particular routine are linked with your program. (You can use Link's -d option to suppress the duplicate definitions warnings.)" — consistent, softer restatement of the same rule.

### 1b. Unresolved symbol → value 0

**Verdict: NOT FOUND** (and mildly CONTRADICTED in spirit by the 68K doc, though for a different toolchain).

Nothing in either PDF or the GS/OS source states that an unresolved external defaults to the numeric value 0. `omf.py:_eval` does this via plain Python `dict.get(val, 0)` (`gsasm/omf.py:211`) — an implementation convenience with no cited authority. The 68K `Link` reference's "Unresolved external symbols" section (p.292) describes only the case-sensitivity/`-ma` module-alias workaround; it doesn't discuss a linked value at all, implying (for the 68K linker) an unresolved symbol is normally a hard link error, not silently zeroed. LinkIIGS itself is binary-only here so its true unresolved-symbol behavior can't be checked against source. This rule stays purely empirical.

### 1c. OMF record opcodes (RELOC/cRELOC/INTERSEG/cINTERSEG/SUPER/LCONST/DS/END)

**Verdict: DOCUMENTED**, exact byte-for-byte match, from `ref/GSOS_6/IIGS.601.SRC/GS.OS/Loader/Loader.Equates`:

```
END       EQU $00      ;END record
RELOC     EQU $E2      ;Relocation record
INTERSEG  EQU $E3      ;Inter-Segment relocation record
DS        EQU $F1      ;Zero Fill record
LCONST    EQU $F2      ;Long Constant record
cRELOC    EQU $F5      ;compressed RELOC record
cINTERSEG EQU $F6      ;compressed INTERSEG record
SUPER     EQU $F7      ;super compressed record
```

This matches `gsasm/omf.py:39-43`'s `REC` dict (`0xE2:'RELOC', 0xE3:'INTERSEG', 0xF1:'DS', 0xF2:'LCONST', 0xF5:'cRELOC', 0xF6:'cINTERSEG', 0xF7:'SUPER', 0x00:'END'`) and `expressload.py`'s `emit_creloc`/`emit_interseg`/etc opcode bytes exactly, opcode-for-opcode.

### 1d. RELOC/cRELOC/INTERSEG/cINTERSEG record field layouts

**Verdict: DOCUMENTED**, from `GS.OS/Loader/Relocation.a` (`Do_RELOC`, `Do_cRELOC`, `Do_INTERSEG`, `Do_cINTERSEG` PROCs). Field layouts (offsets into the on-disk record body after the opcode+length prefix), quoted verbatim from the source's local `equ` blocks:

```
Do_RELOC:     Bytes=0  Shift=1  Offset=2  Value=6      (10-byte body)
Do_cRELOC:    Bytes=0  Shift=1  Offset=2  Value=4       (6-byte body)
Do_INTERSEG:  Bytes=0  Shift=1  Offset=2  FileNum=6 SegNum=8 SegOffset=10  (14-byte body)
Do_cINTERSEG: Bytes=0  Shift=1  Offset=2  SegNum=4  SegOffset=5            (7-byte body)
```

This matches gsasm's `emit_creloc`/`emit_reloc`/`emit_cinterseg`/`emit_interseg` encoders in `expressload.py:148-200` field-for-field (opcode + bytesInOperand + bitShiftCount(signed) + offset [+ far-target fields]).

`Common_Reloc`'s shift-application logic (right/left shift by a *signed* 8-bit `Shift` byte, with `-16` as a documented special case that swaps in the high word directly) matches gsasm's `_get_shift` sign convention (`neg_shift` before a SHL op) and the `(2,16)→type 27` "bank byte" special case described below.

### 1e. SUPER record subtype formula

**Verdict: DOCUMENTED**, exact formula match, from `GS.OS/Loader/Relocation.a`'s `Do_SUPER` PROC (the authoritative decoder — this *is* the code that must agree with gsasm's encoder for real ExpressLoad files to load). Transcribed from the branch logic (`cont1a`/`cont1b`/`cont1c`/`cont2`/`cont3a`):

- **type 0**: "RELOC2" — same-segment, `Bytes = 2` (`type + 2`).
- **type 1**: "RELOC3" — same-segment, `Bytes = 3` (`type + 2`).
- **types 2-13** ("INTERSEGn", n=1..12): `Bytes=3`, `FileNum = type-1`, `SegNum` is read live from the 3 bytes *already sitting at the patch location* (a self-describing far pointer).
- **types 14-25**: `SegNum = type-13`, `FileNum=1`, `Bytes=2`, low word.
- **types 26-37**: `SegNum = type-25`, `FileNum=1`, `Bytes=2`, **high word** (source comment: *"if INTERSEG25-36, use high word for Patch (equivalent to shifting the patch by -16)"* — `cpx #26; bcc cont3a; lda TempZero+6`).
- type ≥ 38 is rejected as `Illegal` (`idBadRecordErr`).

This is an **exact** match to gsasm's formulas in `expressload.py`:
- `_SUPER_TYPE = {(2,0):0, (3,0):1, (4,0):1, (2,16):27}` — types 0/1 = same-seg 2/3-byte, confirmed.
- `corrected_type = 25 + tgt_segnum` (bank-byte/high-word cross-group case, `expressload.py` ~line 2020) — exact match to the Loader's `type-25=SegNum` (26-37) branch.
- `corrected_type = 13 + segnum` equivalent (stype==0 low-word cross-group correction, "13 + the target's own final segnum") — exact match to the Loader's `type-13=SegNum` (14-25) branch.
- The `(4,0)→type 1` mapping (a 4-byte `dc.l` address patched via a 3-byte SUPER record) is also confirmed correct: `Do_SUPER`'s RELOC3 path only ever writes `Bytes` bytes (2 or 3, never 4) at `cont3a`'s byte-copy loop — so a `dc.l` slot's top byte is legitimately left unpatched (must be baked 0 at emit time), exactly as gsasm's comment states.

### 1f. SUPER page-list codec (skip/count bytes, 256-byte pages)

**Verdict: DOCUMENTED**, exact algorithmic match, from `Do_SUPER`'s `loop1`/`loop2`/`eloop1` byte-stream walk:
- A byte tested with `bpl` (bit7=0, "count header"): becomes `Counter`, then `Counter+1` patch-offset bytes are read and applied to the current page, after which the page index increments by 1 (`eloop1` adds 1 to `PatchLoc`'s page byte).
- A byte with bit7=1 ("skip header"): `and #$FF7F` (bit7 cleared, i.e. `b & 0x7F`) is added directly to the page index — **no** implicit `+1**.

This matches `gsasm/expressload.py:_decode_page_list`/`_encode_page_list` byte-for-byte, including the encoder comment "no +1; matches loader behaviour exactly" for the skip case and the count-byte `(b&0x7f)+1` semantics.

### 1g. KIND bit semantics (0x4000 private, 0x8000 dynamic, 0x0100 bank-aligned)

**Verdict: DOCUMENTED**, exact and complete, from `GS.OS/Loader/Loader.Equates` — this is the single strongest hit of the whole hunt, a full authoritative enumeration:

```
Code_Segment    EQU $00
Data_Segment    EQU $01
Jump_Segment    EQU $02
Path_Segment    EQU $04
Lib_Segment     EQU $08
Init_Segment    EQU $10
Direct_Segment  EQU $12
BankRel_Segment EQU %0000000100000000   ($0100)
Skip_Segment    EQU %0000001000000000   ($0200)
Reload_Segment  EQU %0000010000000000   ($0400)
AbsBank_Segment EQU %0000100000000000   ($0800)
NoSpec_Segment  EQU %0001000000000000   ($1000)
PosInd_Segment  EQU %0010000000000000   ($2000)
Priv_Segment    EQU %0100000000000000   ($4000)
Dyn_Segment     EQU %1000000000000000   ($8000)
```

Direct hits on all three rules of special interest:
- **`0x4000` = `Priv_Segment`** — matches `linkiigs.py:364`'s `is_public_seg = not (_hdr.get('KIND', 0) & 0x4000)` exactly (bit set = private).
- **`0x8000` = `Dyn_Segment`** — matches every `& 0x8000` "dynamic group" check in `expressload.py` (e.g. `dyn_flags[i] = bool(segkinds & 0x8000)`).
- **`0x0100` = `BankRel_Segment`** — this is the literal named foundation of gsasm's "BankRel omission rule". The Loader's own `Common_Pass1_Check` masks `Header.Kind and #%11111` (low 5 bits = base type 0x00-0x12) when deciding Init-segment reset-address behavior, i.e. it treats the low 5 bits as the "base kind" and the higher bits (including `BankRel_Segment`) as independent flag bits — consistent with gsasm treating `KIND & 0x00FF` as the base type for e.g. the direct-page/stack BANKSIZE-0 special case in `_make_suffix_template`.

Also `Direct_Segment EQU $12` confirms gsasm's `(kind & 0x00FF) == 0x12` "direct-page/stack segment" special case in `expressload.py:_make_suffix_template` (BANKSIZE=0 override) by name.

### 1h. `~ExpressLoad` directory segment / HET format

**Verdict: PARTIAL — confirms field semantics exactly; the on-disk *compaction* (chained/suffix-spilling variable-length entries) is not documented and the Loader.Equates' own `Record` declaration is, read literally, in tension with it.**

`GS.OS/Loader/Loader.Equates` gives full `Record` (struct) declarations:

```
HET_Entry        Record 0
SegOffset  ds.w 1   ;relative offset to first header entry
SegFlags   ds.w 1   ;segment flags
SegHandle  ds.l 1   ;segment handle
EndR

SegHeaderEntry   Record 0
LConst_Mark       ds.l 1
LConst_Length     ds.l 1
RelocDict_Mark    ds.l 1
RelocDict_Length  ds.l 1
           ds.b 1   ;reserved
LabLen     ds.b 1
NumLen     ds.b 1
Version    ds.b 1
BankSize   ds.l 1
Kind       ds.w 1
           ds.w 1   ;reserved
Org        ds.l 1
Align      ds.l 1
NumSex     ds.b 1
           ds.b 1   ;reserved
SegNum     ds.w 1
Entry      ds.l 1
DispName   ds.w 1
RelocDict_Hndl    ds.l 1
           ds.b 8   ;reserved
name_overhead equ *-DispName       ; = 58 bytes total
EndR

ExpressloadSeg   Record 0
RefNum          ds.w 1     ;reserved field in ExpressSeg LConst
PathnameOffset  ds.w 1     ;offset of pathname within segment
SegCount        ds.w 1     ;number of segments in ExpressSeg
SegEntry        ds HET_Entry        ;array of HET_Entry
SegConversion   ds.w 1              ;array of integer (seg number conversion)
SegHeader       ds SegHeaderEntry   ;array of SegHeaderEntry
EndR
```

**Confirms exactly**:
- `make_HET_ptr`'s own comment states `HET_ptr` points "to the segment count field **of the segment (of Disk Image)**" — i.e. this *is* the raw on-disk byte layout, not a transcoded runtime copy, so it is directly comparable to gsasm's HET builder.
- gsasm's `_het_entries`' 4 leading dwords per entry (`code_start`, `length`, `reloc_start`, `reloc_size`) are **exactly** `LConst_Mark`/`LConst_Length`/`RelocDict_Mark`/`RelocDict_Length` — same fields, same order, same meaning (mark=file offset of the LCONST/reloc-dict data, length/size in bytes).
- The last 42 bytes of `SegHeaderEntry` (struct offset 16..57, i.e. `reserved,LabLen,NumLen,BankSize,Kind,reserved,Org,Align,NumSex,reserved,SegNum,Entry,DispName,RelocDict_Hndl,reserved[8]`) is **the same 42 bytes** gsasm's `_make_suffix_template` builds, field-for-field, confirming `NUMLEN=4`,`VERSION=2`,`BANKSIZE`,`KIND`,`ALIGN`,`SEGNUM`,`DISPNAME` at the relative positions gsasm's docstring claims.
- The 8-byte `extra_block`/`HET_Entry` array (`SegOffset:word`, `SegFlags:word`, `SegHandle:long`) matches gsasm's "N items of 8 bytes each" claim in size and count, though gsasm's docstring models it as one 4-byte little-endian pointer + 4 zero bytes — the true field split is `offset(word)+flags(word)` then `handle(long)`. Byte-identical on disk (flags=0, handle=0 pre-load) but the true field boundary differs from gsasm's mental model — worth a documentation touch-up, not a functional bug.
- gsasm's `[22..25]=SEGNUM as LE dword` and `[28..31]=DISPNAME as LE dword` are, per the real struct, actually `SegNum:word` immediately followed by `Entry:long` (always-0 in the corpus), and `DispName:word` immediately followed by `RelocDict_Hndl:long` (always-0 pre-load) respectively — again byte-identical for every observed gold file (because those adjacent runtime-only fields are always zero on disk) but a hidden coincidence, not a documented invariant. **This is worth flagging to the maintainer**: if a hypothetical ExpressLoad build ever had a segment with a non-zero `Entry` field (an actual entry-point offset — real for some KIND types) this template would silently corrupt it; the golden corpus apparently never exercises that case.

**Not confirmed / apparent tension (does not rise to a hard CONTRADICTION)**: gsasm's `_build_het_lconst` docstring is explicit that for N>1 segments the golden format is a "*chained, suffix-spilling* design" where `SegHeaderEntry` templates and pathnames are NOT stored as separate, fixed-stride array elements — they're packed/overlapped across entry boundaries by a formula (`entry_size = 51 + len(own SEGNAME)`) reverse-engineered from golden binaries. The `ExpressloadSeg` `Record` declaration above, read literally, models `SegHeader` as a plain **array of fixed 58-byte `SegHeaderEntry` structs** (no chaining, no compaction) — a materially simpler layout. Two readings reconcile this without a true contradiction: (1) the `Record` declaration is very plausibly just a symbolic/logical offset-naming convenience (common MPW-macro-assembler idiom) rather than a literal claim about on-disk stride, and (2) every place the Loader source actually *reads* an entry does so via an explicit per-segment relative-offset pointer (`HET_entry_ptr`'s `SegOffset` field → `seg_header_ptr = HET_entry_ptr + [HET_entry_ptr]`, see `find_Segment`/`Process_Reloc`/`setup_seg_ptrs`), never by assuming fixed-stride indexing into a `SegHeaderEntry` array — so the **decoder is compaction-agnostic**: it will correctly walk gsasm's chained/spilled layout exactly because it never assumes a fixed stride for entry bodies (only the outer 8-byte pointer array is fixed-stride, confirmed above). The compaction algorithm itself (which encoder produces it, and the exact `51+len(name)` formula) has no source or documentation in our refs — the *encoder* side (LinkIIGS `-express` / `ExpressIIGS`) is binary-only. This part of gsasm's rule (the `entry_size = 51 + len(SEGNAME)` formula and the partial/spill byte-count derivation in `_het_entries`) is genuinely **NOT FOUND** in any held reference and remains purely empirically reverse-engineered from golden binaries, as gsasm's own comments candidly say ("SPIKE-3", "measured against gold").

### 1i. Case-B flagged-addend rule (`Label+$80000000`/`Label+$C0000000`)

**Verdict: NOT FOUND.** Grepped the entire `GS.OS/Loader` tree and the rest of `ref/GSOS_6` for `80000000`/`C0000000`/"flagged"/"far pointer" — no hits. This is consistent with it being an **assembler/linker-side** convention (how AsmIIGS/LinkIIGS choose to *encode* an expression that should ride a SUPER page-list vs. get a standalone record) rather than something the Loader (a pure consumer of already-resolved records) would ever need to know about. Neither AsmIIGS nor LinkIIGS has source in our refs (both are HFV binaries only), so this rule cannot be grounded further with held material.

### 1j. Unresolved-symbol value / BankRel omission mechanics beyond the KIND bit itself

**Verdict: NOT FOUND** for the omission *mechanics* (why a BankRel-flagged segment's cross-references are dropped from SUPER records) — only the `BankRel_Segment=$0100` bit's *existence and name* is documented (§1g above); the Loader source's own use of the bit was not located in the portions read (the 147KB `ExpressLoad.a` was sampled heavily but not exhaustively — a targeted re-read of `Load_Segment`/`Do_Segment`/`Segments.a`'s `Check_KIND` for explicit `BankRel_Segment` handling could still turn up more and was not fully exhausted in this pass).

## 2. Summary counts

| Verdict | Count | Rules |
|---|---|---|
| DOCUMENTED | 6 | first-wins duplicate resolution (68K-family); OMF opcodes; RELOC/cRELOC/INTERSEG/cINTERSEG field layouts; SUPER subtype formula; SUPER page-list codec; KIND bits 0x4000/0x8000/0x0100 |
| PARTIAL | 1 | `~ExpressLoad` HET field semantics (confirmed) vs. its chained/suffix-spilling compaction (unconfirmed, apparent tension with the `Record` declaration but reconcilable) |
| NOT FOUND | 3 | unresolved-symbol-defaults-to-0; case-B flagged-addend convention; BankRel omission *mechanics* (bit itself is documented, its consumption isn't) |
| CONTRADICTED | 0 | none found |

**No outright contradictions.** The highest-value result is that `ref/GSOS_6/IIGS.601.SRC/GS.OS/Loader/` (previously apparently under-mined) contains the actual System Loader v4.00 source, which independently and exactly corroborates gsasm's OMF opcode table, RELOC/INTERSEG record field layouts, the full SUPER subtype formula (types 0/1 same-seg, 2-13/14-25/26-37 INTERSEG families), the SUPER page-list skip/count codec, and — most notably — the complete KIND bit table including the literal `BankRel_Segment = $0100` constant that names the foundation of gsasm's "BankRel omission rule". The two PDFs are both exclusively 68K-Macintosh MPW documentation (confirmed via full-text search: zero "IIGS" occurrences in either), so their only contribution is the family-level first-definition-wins linker precedent, not IIgs-primary evidence. The `~ExpressLoad` on-disk directory's *compaction algorithm* (the empirically-derived `51+len(name)` chained suffix-spilling entry-length rule) remains genuinely undocumented anywhere in the held references — LinkIIGS/ExpressIIGS/AsmIIGS are binary-only on the MPW-GM disk image, with no embedded help text beyond bare diagnostic strings.

## 3. Extracted files (scratchpad only, not committed)

`/private/tmp/claude-501/-Users-mdj-src-gsasm/a5794041-df24-4aed-8c97-b8fdc88c5ec8/scratchpad/hfv_extract/`:
`MPW_Vol1.txt`, `MPW_Asm.txt` (full pdftotext dumps), `full_listing.txt` (complete HFV directory walk), `Relocation.a.txt`, `ExpressLoad.a.txt`, `Segments.a.txt`, `Struct.a.txt`, `Files.a.txt`, `Loader.Equates.txt`, `Loader.a.txt`, `E16.Loader`, `M16.Loader`, `Loader.h`, `LinkIIGS.rsrc` (extracted resource fork).
