# Design: Rez resource compiler (M7 — DONE: Sys.Resources byte-exact)

**Replaces:** MPW `RezIIgs`. **Unlocks:** the shipping files for the *asm* desktop
targets whose code already assembles with gsasm but which carry a resource fork.
Read `README.md` and `design/README.md` first.

This is a genuinely separate compiler, not byte-shuffling: a C-preprocessor layer
over a typed-data DSL. Scope it to the **subset of Rez actually used by the
targets**, not full Rez.

## Status (2026-07-14 survey; done-gate closed same day, packet R7)

The survey that follows was done against the golden `Sys.Resources` fork and the
6.0.1 archive. Everything below is *measured*, not assumed; re-derive with
`work/rezcheck.py`. All seven work packets (R1–R7) below are now complete:
the golden Sys.Resources resource fork reproduces byte-exact from source via
both the public library pipeline and the `gsrez` CLI (`work/
rezbuildcheck.py`, wired into `gate.py`) — see "How to build Sys.Resources"
further down.

### Inputs — all present

- **Rez sources:** ~70 `.r/.rez/.rii` files under `ref/GSOS_6/IIGS.601.SRC`.
  First target: `ref/GSOS_6/IIGS.601.SRC/GSToolbox/Sys.Resources/` (source,
  makefile, and the four `.aii` code-resource sources) — the archive is the
  canonical source root, same as toolcheck/fstcheck. NOTE: classic-Mac CR line
  endings, MacRoman high bytes. **Do not use `work/txt/Sys.Resources/`** — that
  copy was converted (LF + UTF-8) during early exploration and is not
  byte-faithful; string bytes in the golden fork are MacRoman.
- **`TypesIIGS.r`** (the single external include every target uses): extracted
  from `ref/gsrom3/system500.hfv` (`MPW-GM/MPW/Interfaces/TypesIIGS.r`, dated
  1992-02-21 — right vintage) to **`work/rincludes/TypesIIGS.r`** (gitignored,
  like all Apple material). It defines the standard type templates and the
  `#define` table `rIcon $8001 … rComment $802A`.
- **Golden forks:** 9 resource-forked files on the System Disk, extractable via
  `work/diskcheck.py`'s `Volume.read_file(path, fork='rsrc')`.
- **Oracles:** `RezIIGS`, `DeRezIIGS`, `ResEqualIIGS` binaries live in the same
  `.hfv` — SheepShaver capture sessions can settle any ambiguous language corner.

### First target: Sys.Resources (the M7 "done" gate)

`/System.Disk/System/System.Setup/Sys.Resources` — **empty data fork**; the whole
shipping file is one 24,337-byte resource fork. Invocation (from the makefile):
`reziigs -rd sys.resources.r -o SYS.RESOURCES -t "F9  "`. Its four embedded code
resources build from `.aii` with gsasm+gslink (`-x`, i.e. plain load files — what
gsasm's linker already emits). 143 resources across 17 types exercising: local
`type` declarations, `$$Word()` expressions, `read`, `#define`, string
concatenation, hex strings, arrays, and `rControlTemplate` (switch templates).

### Golden fork format — decoded facts

Layout (all little-endian):

- **Header** (12 B): `rFileVersion=0`, `rFileToMap=0x8C`, `rFileMapSize`.
- **Memo area** (offset 12, 128 B): NOT zeros. Observed: a Pascal string
  `\x0DSys.Resources`, `\x02\x00\x00\x00`, two copies of `F9  pdos`
  (filetype+creator), a Mac-epoch timestamp (~1993), and a copy of the file
  length. Layout must be reverse-engineered across all 9 golden forks (packet
  R2); the timestamp is a determinism hazard — handle like the other tools
  (settable/captured constant).
- **Map** at 0x8C: handle(4,=0) flags(2) offset(4) size(4) toIndex(2,=116)
  fileNum(2) fileID(2) indexSize(4) indexUsed(4) freeListSize(2)
  freeListUsed(2), free list, then the index.
  R1 survey (all 9 forks, `work/rezcheck.py`): freeListSize always 10 with 1
  used; the used entry is an EOF sentinel `(offset=fork_length,
  size=−(fork_length+1)` as signed 32-bit`)`. indexSize = indexUsed + 10 in
  all 9 forks (flat +10 slack). Two constant pads: 4 bytes after the
  free-list array (before the index) and 2 bytes after the index (before
  resource data).
- **Index**: 20-byte records `type(2) id(4) offset(4) attr(2) size(4)
  handle(4,=0)`, **sorted by (type, id)**; unused slots zeroed.
- **Resource data**: contiguous, zero gaps, immediately after the map,
  **in source-statement order** (not index order). Totals reconcile exactly:
  140 + map 3178 + data 21019 = 24337.
- **Attributes**: source flags map onto IIgs Resource Manager attr bits —
  `locked`=0x8000, `fixed`=0x4000, `preload`=0x0040,
  `nospecialmemory`=0x0008, `Convert` (on `read`)=0x0800; a bare numeric attr
  (e.g. `$8000`) passes through; default 0. Observed words: $C048, $8800,
  $8000, $0000 — all consistent. Attribute keywords are RezIIgs built-ins
  (not `#define`s in TypesIIGS.r).

### Target order and the ceiling

Sys.Resources → EasyMount (asm, `.rii`) → General CDEV (asm) → **Finder**
(`/System/Start`, 52 KB fork — the prize; `Finder.rez` includes 7 sub-`.rez`
files + `Finder.rez.equ`). The Pascal CDEVs (Printer, RAM, Slots, Time) and
ControlPanel NDA can never be fully byte-exact — their embedded code resources
are Pascal-compiled — so they stay SUBSTITUTE, like their data forks.

**EasyMount (2026-07-14 resource fork; 2026-07-15 data fork — `work/
easymountcheck.py`): BOTH forks byte-exact.** EasyMount is the first
dual-fork target (a real 65816 data fork, not an empty one like
Sys.Resources) and the first to prove the Rez pipeline generalizes: every
resource type `EasyMount.rii` uses (rVersion, rComment, rIcon,
rControlList, rControlTemplate incl. the previously-unexercised
`RadioControl` switch case, rPString, rTextForLETextBox2, rWindParam1) was
already golden-verified by the Sys.Resources corpus — no new types, no
`read`/Convert, no synthesized rResName. Two small, evidence-backed
`gsasm/rez/gen.py` additions closed the gap to byte-exact (2500/2500 bytes,
25/25 resources): the `\$HH` string escape (a hex-byte escape distinct from
`\0xHH`, needed by the Cancel/Connect `KeyEquiv` char pairs) and
generalizing the TypedField "partial-fill omits the rest of the field
list" rule to nested ArrayField/SwitchField/GroupField (needed by
`iconButtonControl`'s unnamed `KeyEquiv` array, supplied only 7 of 8
values). The data fork (`EasyMount.aii`+`DES.aii`, assembled with
`-d DebugSymbols=0` and ExpressLoad'd — its own bytes confirm a
`~ExpressLoad` directory segment despite the makefile's `linkiigs -t $B6`
carrying no explicit `-x`/ExpressLoad flag, same as every other
System.Setup/Tools/FSTs/Drivers file) needed 5 assembler-environment
includes (`E16.Finder`/`E16.GSOS`/`E16.Locator`/`E16.QuickDraw`/`m16.debug`)
absent from the `ref/GSOS_6/IIGS.601.SRC` archive snapshot entirely — like
TypesIIGS.r, recovered from `ref/gsrom3/system500.hfv`
(`MPW-GM:MPW:Interfaces:AIIGSIncludes:`, an HFS volume) via `hfsutils`
(`hmount`/`hcopy`/`humount`) into `work/rincludes/AIIGSIncludes/`
(gitignored). With those, both sources assemble cleanly (0 errors), and
(R11, 2026-07-15) the linked/ExpressLoad'd result is now byte-exact
(9221/9221) — two precisely diagnosed residuals, both in core asm/link
files, fixed at their root cause:

  (a) **`Asm.expand_macro()`'s @-label scope, not `Asm.resolve()`'s
  tie-break.** The wrong branch-operand byte was never a nearest-vs-farther
  distance question: `@done` was defined TWICE under the SAME `_symkey`
  scope key (`SFTOOLNUMBER@DONE`) because `GetStandardFile`/
  `KillStandardFile` are declared with the MPW `&lab NAME` macro idiom (the
  `NAME` macro's body is just `&lab` — a bare label-only line that
  re-emits the call-site label to define it as a real, @-scope-resetting
  global). Since `NAME` has a `label_var`, `dispatch()` never calls
  `define_label` at the call site itself — the label is defined INSIDE the
  macro body — and `expand_macro()` unconditionally restored
  `self.last_global` to its pre-call value when the body finished (a
  guard meant to sandbox a macro's PRIVATE `local_ctx` @-labels), silently
  discarding that definition's effect on @-scope. Two NAME-declared
  routines back-to-back sharing an @-label name (`@done`; also
  `GetStatus`/`TestUserVolume`'s `@retry`/`@loop`/`@match`/`@exit`, which
  collided into a bogus `L2@...` scope the same way) then fall back to
  whatever REAL, non-macro label preceded them both. The fix: after a
  macro body runs, keep `last_global` as the body left it when it now
  equals the call site's own (non-`@`) label — i.e. only skip the restore
  in exactly the case where the body defined that same label as a real
  global — else restore as before (protecting a macro's other, genuinely
  private internal labels). With scope keys correctly disambiguated this
  way, every `@`-label in EasyMount.aii/DES.aii ends up with exactly ONE
  definition per key — `Asm.resolve()`'s nearest-by-distance tie-break
  policy is untouched and never even exercised for these cases. Fixture:
  `tests/fixtures/030-name-macro-at-label-scope/`.

  (b) **`expressload.py`'s single-segment reloc-dictionary scan evaluated
  standalone-record expressions against the plain multi-object-shared
  `sym` table, not the per-object-merged table `_build_body` actually
  resolves bodies against.** `linkiigs._build_symtab` deliberately keeps
  segment names object-PRIVATE in a multi-object link (a segment named
  `SHUTDOWN` in one object must not shadow another object's EXPORT of the
  same name) — visible only via `obj_globals[obj_idx]`. DES.aii's own
  `DES` code segment addresses its own `DESDATA` data segment (the `lda
  #s1`/`lda #>s1` S-box-table-pointer pair) via exactly that
  object-private binding, but `_scan_standalone_relocs`/`_scan_case_b`
  evaluated their expressions against bare `sym`, where `DESDATA` isn't a
  key — evaluating to 0 instead of DESDATA's real placed base (6193, which
  is exactly EasyMount.aii's own linked segment length prepended before
  it), 6193 bytes short of the correct address. Separately, the `#s1` (low
  byte, shift=0) half of the pair was dropped from the dictionary
  entirely: the standalone-scan condition required a truthy `shift`, but a
  1-byte field can't ride ANY SUPER page list (`_SUPER_TYPE` has no size-1
  entry at any shift) regardless of whether it's shifted, so it needs a
  standalone record either way. Fix: `expressload()` now keeps
  `body_syms[placed_i]` (the exact table each segment's body was resolved
  against) alongside `bodies[placed_i]`, and `_scan_standalone_relocs`/
  `_scan_case_b` are evaluated per-segment against that table; the
  standalone condition drops the `shift and` guard (any `(size, shift)`
  absent from `_SUPER_TYPE` needs a standalone record, matching the
  existing size-1/shift=16 and size-2/shift=8 cases already handled this
  way). The **multi-segment** (`multiseg=True`) ExpressLoad output path
  has no analogous fix — it never scans for standalone case-A/B records at
  all (a separate, larger gap; see `docs/TODO.md` section 1, and
  `work/archive/toolsetup_probe.py` — TS2/TS3/Tool.Setup's residuals are a
  different reloc-record-ENCODING wall, unrelated to this placement-base
  bug, and were unaffected by this fix).

`work/diskcheck.py` wires both of EasyMount's forks (REZ_BUILDERS for the
resource fork; a REZ-owned SOURCE_BUILDERS branch for the now-exact data
fork) — `disk_logical_exact` improved 18→19/30 in the gate baseline as a
result. Gate metric `rez_easymount_data_bytes_exact: 9221` (alongside the
existing `rez_easymount_rsrc_bytes_exact: 2500`) is registered in
`work/gate.py`/`gate_baseline.json`.

## Work packets

Each packet is agent-sized with a byte-level acceptance test. Dependency graph:

```
R1 (harness+format spec) ──→ R2 (emitter) ──┐
R3 (preproc+lexer) ──→ R4 (parser) ──→ R5 (generator) ──→ R7 (CLI+gate)
R6 (read/Convert + linker -lseg) ───────────┘        (R6 needs R1 only)
```

- **R1 — `work/rezcheck.py` harness.** Extract the 9 golden forks from the
  System Disk 2mg (reuse `diskcheck.Volume`); parse header/memo/map/index;
  `--dump` listing (type/id/attr/size/offset per resource); a `compare()`
  that diffs a built fork against golden with per-resource attribution.
  *Accept:* golden Sys.Resources parses; counts/totals above reproduce.
- **R2 — `gsasm/rez/emit.py` fork emitter.** Input: ordered `(type, id, attr,
  data)` list + file metadata. Output: byte-exact fork. Reverse the memo
  layout and the indexSize/freeList allocation rule against all 9 golden
  forks. *Accept:* re-emitting each golden fork from its own parsed contents
  is byte-identical (rezcheck round-trip test), ≥3 forks minimum, all 9 ideal.
- **R3 — `gsasm/rez/lexer.py` preprocessor + lexer.** CR/CRLF/LF line endings;
  `/* */` and `//` comments; `#include` (search path list), `#define`
  (object-like), `#if/#ifdef/#else/#endif` with `defined()`; string literals
  (adjacent-literal concatenation, escapes), hex strings `$"…"`, numbers
  (`$…`, `0x…`, decimal, `'…'` char constants), identifiers (case-insensitive
  type names — confirm), punctuation. *Accept:* tokenizes
  `work/rincludes/TypesIIGS.r` + `sys.resources.r` completely (no error
  tokens, full coverage) — corpus checks live in `work/`, never `tests/`;
  `tests/` only ever gets small hand-authored snippets (Apple sources are not
  distributable).
- **R4 — `gsasm/rez/parser.py`.** Grammar for `type` declarations (integer/
  longint/byte/word/char/string/pstring/cstring/hex variants, `string[expr]`,
  fill/align, arrays, `switch` templates, labeled fields, `= const` defaults,
  symbolic value lists), `resource <type>(<id>[, "name"][, attrs…]) { … }`,
  `read <type>(<id>[, attrs…]) "file"`, expressions incl. `$$Word/$$Byte/
  $$Long` field references and arithmetic. *Accept:* full-fidelity AST for
  TypesIIGS.r + sys.resources.r (corpus check in `work/`; hand-authored
  grammar cases in `tests/`).
- **R5 — `gsasm/rez/gen.py` data generator.** Evaluate a resource body against
  its type template → bytes. `$$` functions, switch dispatch, arrays, fills,
  string forms, numeric widths/radix. Also **synthesize the `rResName`
  ($8014) name-index resource**: RezIIgs auto-generates one resource (id
  0x00018001 in Sys.Resources) from the `"name"` strings attached to other
  resources — it has no source statement (R4 survey; template is an
  (id, pstring) table per TypesIIGS.r). *Accept:* every non-`read` resource
  in golden Sys.Resources — all 139, including the synthesized rResName —
  reproduced byte-exact individually (driven by R1's per-resource diff).
- **R6 — `read` + Convert.** Build the four `.Load` inputs with gsasm+gslink
  (Launcher needs `-t $BC -lseg:code:nospecial:static` semantics — may need a
  small linker/CLI extension); reverse the OMF-load-file→resource `Convert`
  transformation against the golden embedded bytes (sizes 2649/1313/633/4899
  at known offsets). *Accept:* all four embedded code resources byte-exact.
- **R7 — CLI + integration. DONE.** `gsrez` entry point (`gsasm/__main__.py`
  `rez_main()`, `pyproject.toml` script `gsrez = gsasm.__main__:rez_main`);
  `work/rezbuildcheck.py` drives the full public pipeline (parse -> generate
  -> resolve `read`s via `work/rezloadcheck.py`'s `.Load` builder +
  `convert.convert_load` -> `to_emit_tuples` -> `emit_fork`) with the golden
  meta values recovered the same way `work/rezemitcheck.py` does, AND
  separately exercises the `gsrez` CLI (subprocess) with matching `--meta`
  overrides; both reproduce the golden 24,337-byte fork byte-exact. Wired
  into `gate.py` (`rez_sysresources_bytes_exact: 24337`) and flipped
  Sys.Resources from REZ/substitute to REZ/buildable in `diskcheck.py` (see
  "diskcheck flip" below); corpus-free fixtures added at
  `tests/test_rez_pipeline.py`. *Accept, met:* `gate.py` green with the new
  metric; **golden Sys.Resources fork byte-exact = M7 done**, via both the
  library and the CLI.

## How to build Sys.Resources

```
python3 work/rezbuildcheck.py
```

reproduces the golden `/System.Disk/System/System.Setup/Sys.Resources`
resource fork byte-exact two independent ways and fails loudly if either
diverges:

1. **library pipeline** — `gsasm.rez.parser.parse()` (predefining
   `RezIIGS=1`) -> `gsasm.rez.gen.generate()` -> resolve the four `read`
   statements' `.Load` files (built fresh from `ref/GSOS_6/IIGS.601.SRC/
   GSToolbox/Sys.Resources/*.aii` via `work/rezloadcheck.py`'s builder) ->
   `gsasm.rez.gen.to_emit_tuples()` -> `gsasm.rez.emit.emit_fork()`, called
   with the golden fork's own recovered `meta` (name/filetype/creator/
   creation timestamp — `work/rezemitcheck.py`'s `_meta_from_golden`).
2. **`gsrez` CLI** — the same pipeline invoked out-of-process through
   `gsasm.__main__.rez_main()`, given the identical golden values via
   `-t`/`-c`/`--meta`, to prove the CLI is a faithful wrapper and not a
   second, divergent code path.

"Byte-exact" here means the full 24,337-byte fork — header, memo,
map/index, and all 143 resources' data (139 generated + 4 embedded code
resources reproduced via `read`/`Convert` + the synthesized rResName) —
matches the golden fork captured off the System 6.0.1 disk image with zero
diffs (`work/rezcheck.py`'s `compare()`). The `gsrez` CLI itself, run
without harness-supplied `--meta` overrides, stays HONEST rather than
golden-shaped: its defaults (creator `pdos`, a zero memo timestamp, no file
type) do not reproduce any specific archival file's undocumented memo
bytes on their own — that reproduction is `work/rezbuildcheck.py`'s job
(or any caller supplying the same `--meta`/library arguments).

### CLI surface

```
gsrez <source.r> [-I <incdir>]... [-o <out>] [-t <filetype-hex>]
      [-c <creator>] [--read-dir <dir>]... [--meta KEY=VAL]...
```

mirrors the makefile's `reziigs -rd sys.resources.r -o SYS.RESOURCES -t
"F9  "` invocation as `gsrez sys.resources.r -o SYS.RESOURCES -t F9`.
`-I` adds `#include` search directories; `--read-dir` (repeatable) adds
directories searched — case-insensitively, before the source file's own
directory — for each `read` statement's file; `--meta KEY=VAL` (repeatable)
overrides any `gsasm.rez.emit.DEFAULT_META` field (bytes-valued fields take
an explicit `0x`-prefixed hex string, or otherwise a literal string encoded
latin-1). Output is the RAW resource-fork image only; packaging it with a
(commonly empty) data fork into one dual-fork disk file is out of scope for
this CLI.

Follow-on (post-gate): EasyMount, General CDEV, Finder — each mostly exercises
R3–R5 breadth (more types from TypesIIGS.r), plus Finder's multi-file include
structure.

### diskcheck flip

`work/diskcheck.py` overlaid only DATA forks before this packet; Sys.Resources'
data fork is empty (the whole shipping file is its resource fork), so a
parallel resource-fork path was added: `DiskFile.rsrc_blocks` (mirroring
`data_blocks`, resolved via `Volume._resolve_fork(entry, 'rsrc')` +
`_blocks_for`), `overlay_rsrc()` (mirroring `overlay()`), and a `REZ_BUILDERS`
registry (mirroring `SOURCE_BUILDERS`) wired to
`rezbuildcheck.build_sysresources_fork` via a lazy import inside the builder
function — exactly like the existing `_build_prodos()`'s lazy `import
probootcheck` — since `work/rezbuildcheck.py` -> `work/rezcheck.py` ->
`import diskcheck as dc` would otherwise be a module-load-time import cycle.
Verified clean and additive: `--selftest` overlays all 9 REZ files' original
resource-fork bytes back onto themselves with zero drift, the PHYSICAL image
byte-match stays 100% (819264/819264) after the real build-and-overlay, and
`built-bytes covered` rises by exactly 24,337 (124,898 -> 149,235); the
`disk_logical_exact` gate metric moved from 15/27 to 16/28 (both `good` and
its denominator rose together — an addition, not a fix to an existing file —
and is now the locked-in baseline).

## Gotchas

- Archive sources and TypesIIGS.r use CR line endings and MacRoman high bytes;
  the preprocessor treats CR/CRLF/LF as line terminators and passes string
  bytes through verbatim (don't normalize files on disk — they're fixtures,
  and MacRoman bytes must reach the fork untouched).
- The resource **fork** is separate from the data fork; the shipping file is
  dual-fork. `diskcheck.Volume` exposes both; compare the right one.
- Resource data order (source order) ≠ index order (type/id-sorted); get both
  right or offsets shift.
- `-rd` in the makefile invocation = "suppress warnings about redeclared
  types" (verify against MPW docs; harmless for byte-output either way).
- Don't build all of Rez: if a construct doesn't appear in the 6.0.1 corpus,
  it's out of scope. When RezIIgs semantics are ambiguous, capture an oracle
  run in SheepShaver rather than guessing (see `docs/TODO.md` §4).
