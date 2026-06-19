# gsasm: the last 14 bytes — multiply-defined-label SCOPE resolution

This document captures everything learned while grinding the gsasm ROM-03 build
from 251 mismatched toolbox-bank bytes down to **14**, with **all firmware 100%**
byte-exact and the full 256K ROM verified byte-identical. The remaining 14 bytes
are ONE problem: by-name references to labels that are defined many times across
the source. This doc is the ground truth for fixing it correctly (encapsulating
the real MPW IIgs semantics) rather than with more linker heuristics.

## The validation harness (ALL must hold / improve; never regress)

Run from `/Users/mdj/src/gsasm`:
- `python3 work/objcheck.py | tail -1`  → `OBJ byte-identical: 25/61` (per-module
  .obj vs the captured original .obj). MUST NOT drop below 25.
- `python3 work/linkcheck.py | grep -E "IDENTICAL|DIFF"` → `54 LINK_IDENTICAL / 7
  LINK_DIFF` (differential `iix link`). MUST NOT regress.
- `python3 work/romcov.py | grep exact` → `66816/66816 (100%), 9 segs perfect`
  (firmware+overlays flat image). MUST stay 100%.
- `python3 work/buildrom.py | grep -E "byte-identical|=>"` → builds the full ROM
  via the native bank linker (`work/linkrom.py`) + firmware; reports gsasm-built
  byte count (261,363) and verifies byte-identical to the real ROM.

### Per-bank diff count + precise diff→record→symbol identifier
```python
import sys; sys.path.insert(0,'.')
import work.linkrom as L
placements,gtab=L.place(); sym2val=L.parse_map()
def rlen(name,detail):
    if name in('CONST','LCONST'): return len(detail)
    if name=='DS': return detail
    if name in('LEXPR','BEXPR','EXPR','ZEXPR','RELEXPR'): return detail[0]
    return 0
for bank,fn in [(0xFE,'ROM.FE'),(0xFC,'ROM.FC'),(0xFD,'ROM.FD')]:
    img=L.emit_bank(bank,placements,gtab,sym2val)
    real=open('work/romsrc/GS_ROM/ROM/'+fn,'rb').read()
    for seg in placements[bank]:
        lo=seg['base']-(bank<<16); hi=lo+seg['length']
        d=[i for i in range(lo,hi) if i<len(real) and img[i]!=real[i]]
        if not d: continue
        off=lo; seen=set()
        for at,name,detail in seg['recs']:
            n=rlen(name,detail)
            if any(off<=x<off+n for x in d) and off not in seen:
                seen.add(off)
                info=detail[-1] if name in('LEXPR','BEXPR','EXPR','RELEXPR') else ''
                print(f"{fn} {seg['objrel'].split('/')[-1]}:{seg['segname']} "
                      f"@{hex(off)} {name} {info} mine={img[off:off+3].hex()} "
                      f"real={real[off:off+3].hex()}")
            off+=n
```
(The older `work/recmap.py` mis-attributes records by ±1 — use the walker above.)

## The exact 14 remaining bytes (as of this writing)

All are LEXPR/BEXPR/RELEXPR `sym83 NAME` records the native linker resolves to the
WRONG one of several same-named definitions.

| Module / seg | Symbol | mine | real | real def is… |
|---|---|---|---|---|
| FC dialog GETNEXTITEM | NEXTITEM (×3) | $…8022 | $…8014 | neither of the 2 dialog defs exactly |
| FC fm CHOOSEFONT | @BADCHAR (×2, RELEXPR) | $3AC95B | $3AC91F | a cross-segment `@`-label branch |
| FC CallTable CALLTABLE | ERASERECT-1 | $FCF2CA | $FE2F64 | qd/RECTS idx7 (the QuickDraw routine) |
| FD WDefProc HSET* (×4) | SETLONG | $FD48E7 | $FD48FD | WDefProc's SECOND `SetLong` entry |
| FD atp HARDRESET | DISPATCH | $FD6FC5 | $FDFE68 | lap_includes idx71 (forward, another file) |

`gtab['defs'][NAME]` = list of `(linkidx, addr, kind)` where kind ∈
{export, entry, local}. Module link order (`linkidx`) and the bank each lives in
do NOT agree on address order: link places FE first (idx 0–26) but FE = $FE0000
is the HIGHEST address; FC (idx 29+) = $FC0000 lowest; FD (idx ~47+) = $FD0000.

### Full definition lists (abridged) and what real binds to
- **DONE** (already FIXED by "first-def-in-module wins", lever 36): defined ~100×
  (essentially once per PROC: tl, ENV, regions, rgndefs, em, im, mm, le, fm, …,
  cdamenu ×2 entry). cdamenu's `GOTRETURN` (seg5) → real binds to cdamenu's FIRST
  `done` ($FED401), not its second ($FED7A0) or any other module's.
- **NEWMENU** (FIXED by lever 36): MenuMgr defines it twice (entry $FD5BE5,
  $FD652B). MENUCALLTABLE → real = FIRST ($FD5BE5).
- **SETLONG**: WDefProc defines it twice (entry $FD48E7, $FD48FD). The HSET*
  refs → real = SECOND ($FD48FD). ← CONTRADICTS "first wins". So it is NOT
  uniformly first/last; it is per-reference SCOPE (the SetLong in/after the
  referring routine's scope).
- **DISPATCH**: tl entry $FE00C5, WindMgr entry $FD2019, MenuMgr entry $FD6FC5,
  lap_includes LOCAL $FDFE68. atp_includes (idx70) IMPORTs DISPATCH; real binds to
  lap_includes (idx71, the next appletalk file, FORWARD in link order). The three
  ENTRY defs are PRIVATE to their own assemblies (MPW: "ENTRY makes them
  accessible only in modules within the same assembly") → must be EXCLUDED as
  cross-file candidates. aptalk+atp+lap are the AppleTalk sub-unit.
- **ERASERECT**: qd/RECTS LOCAL $FE2F64 (idx7), le LOCAL $FC5A13 (idx33), ListMgr
  ENTRY $FCF2CA (idx45). QD/CallTable.asm (idx46) has `DC.L EraseRect-1` (EraseRect
  UNDEFINED there → external). real binds to qd/RECTS (idx7) — the QuickDraw
  routine — NOT the nearer FC dups. This needs TOOLSET grouping: the QD call table
  dispatches to QuickDraw's routines.

## Why no single LINKER heuristic fits
- "first def in link order wins" → fixes DONE/NEWMENU/ERASERECT, breaks SETLONG.
- "last def at/before referencing module" (current) → fixes SETLONG/DRAWRECT,
  breaks DONE/NEWMENU/ERASERECT.
- "nearest by address" / "nearest by linkidx" → each fixes some, breaks others.
- ENTRY-visibility (exclude other-file ENTRY) is necessary for DISPATCH but not
  sufficient elsewhere.

## THE LIKELY CORRECT MODEL (hypothesis to prove/refine)

In the MPW IIgs assembler, **PROC/ENDP and FUNC/ENDF delimit a code MODULE**, and
"all identifiers defined within a code or data module" have **LOCAL scope —
accessible only within that module, overriding global declarations** (Assembler
Reference, Ch.2 "kinds of identifiers", and the @-label section confirms scope is
delimited by labels). So a label like `done` defined once per PROC is ~100 DISTINCT
local symbols, and a reference inside PROC X resolves to **PROC X's own `done`**.
EXPORT promotes a local to file-global; ENTRY promotes it to assembly-global;
plain locals stay module-local. IMPORT/undefined names resolve at link time, and
"if the object files contain more than one definition for an external symbol, the
FIRST definition is used" (Reference Vol 1, Ch.10).

gsasm currently keys labels by `last_global` (the last non-`@` label) and treats a
whole assembled FILE as the symbol namespace (`msym`/`seg_local` span the file).
The mismatch: **the unit of label locality is the PROC (module), not the file**.
When a reference and a same-named definition sit in DIFFERENT PROCs of one file,
gsasm emits the reference by NAME (sym83) and the linker then has to disambiguate
— which it cannot do correctly because the scope information was thrown away at
assembly time.

### Implications to verify and encode
1. **Module = PROC/FUNC.** A reference resolves first to a definition in the SAME
   PROC (→ emit SEGNAME+offset, fully resolved), only then to file-EXPORT, then
   ENTRY-within-assembly, then external (linker, first-def-wins).
   - This directly explains SETLONG (the HSET* refs and the right SetLong are in
     the same PROC scope) and DONE/NEWMENU (same-PROC first match).
2. **ENTRY is assembly-private**; an ENTRY in another .obj is NOT a candidate for a
   cross-file by-name reference (explains DISPATCH skipping MenuMgr/WindMgr/tl).
3. **AppleTalk (aptalk+atp+lap) may be one linked sub-unit** so lap's local
   DISPATCH is visible to atp — confirm how the original links them (ROM MakeFile /
   the .obj structure) vs. gsasm/linkrom treating them as 3 separate modules.
4. **Dispatch/call tables** (QD CallTable, MenuCallTable) reference the canonical
   toolset routine. Determine from the source/headers how `EraseRect` etc. are
   declared so the table binds to QuickDraw's (likely an IMPORT or a toolset-scoped
   name) — ERASERECT is the one case that may need explicit import/toolset info.
5. **@BADCHAR**: a cross-SEGMENT `@`-label branch (RELEXPR). The @-label scope
   ("both directions to the nearest non-@ label", Assembler Ref p.17 — already
   implemented for the firmware) must compose with PROC/segment boundaries here.

The cleanest fix is almost certainly **scope-aware resolution at ASSEMBLY time**
(asm.py): resolve a cross-segment same-module reference to the specific in-scope
definition and emit `SEGNAME+offset`, instead of punting a bare name to the linker;
plus correct ENTRY-visibility and the appletalk sub-unit grouping in the linker
(`work/linkrom.py`). Prove each rule against the table above; do not over-fit.

## Key code locations
- `work/linkrom.py`: `place()` builds `gtab['defs']`, `msym` (entry/export, first-
  wins), `msloc` (plain local, first-wins); `resolve_name()` order = segbase →
  msym → rommap → global EXPORT → msloc → last-def-at/before-linkidx; `emit_bank()`.
- `gsasm/omf.py`: `_expr_for()` (how a reference becomes SEGNAME+offset vs by-name;
  `as_data` distinguishes DC tables from instruction operands), `emit_segment()`
  (instruction/DC reloc decisions, MVN/MVP per-bank-byte handling, branch RELEXPR),
  `_linear_reloc()`, `_reloc_elem()`.
- `gsasm/asm.py`: `_symkey()` / `define_label()` / `last_global` (label scoping,
  including the `@`-label scope = nearest non-`@` label rule), `resolve()`, segment
  (PROC) handling, `seg_local`/`symseg`/`exports`/`entries`/`imports`.
- Manuals (extract with `pdftotext -layout`): `ref/MPW_3.0_Assembler_Reference_1988.pdf`
  → /tmp/asm.txt (local labels p.17 line ~1316; scope summary line ~1335; EXPORT/
  ENTRY rules line ~4060). `ref/MPW_3.0_Reference_Volume_1_1988.pdf` → /tmp/mpw.txt
  (linker symbol resolution line ~11959).

## Hard constraints
- Never regress: objcheck ≥ 25, linkcheck ≥ 54 IDENTICAL, firmware 100%, ROM stays
  byte-identical. Goal: toolbox bank diffs 14 → 0 (then the ROM is fully gsasm-built
  byte-exact from original source, not just byte-identical via substitution).
