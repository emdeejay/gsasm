# Rez includes uplift — clean-room `TypesIIGS.r` replacement

2026-07-19.  The last dependency keeping `gsrez` from working out of the box
is Apple's `TypesIIGS.r` (36KB, 43 type templates, recovered from the MPW-GM
image into gitignored `work/rincludes/`).  Both validated Rez targets
(`sys.resources.r`, `EasyMount.rii`) `#include "typesiigs.r"`.  This plan
replaces it with an ORIGINAL, committed, MIT include shipped in the package.

## Method (the house move, in miniature)

For every template the corpus uses we hold BOTH sides of the compilation:
the source-level resource bodies (values, case labels, symbolic names) and
the byte-exact golden output (the Sys.Resources fork, 24,337 B / 143
resources, and EasyMount's resource fork — both already reproduced
byte-for-byte by `gsrez`).  So each template's structure (field widths,
string kinds, padding, arrays, switch layouts, fill semantics) is DERIVED
from (body values → golden bytes) pairs, corroborated against the published
resource-format documentation (Apple IIgs Toolbox Reference Vol 3 Appendix E;
GS TechNotes), and expressed in our own template text.  Apple's template
FILE is never the source of expression — only the interface facts that
corpus sources dictate (template names, case labels, symbolic constants,
type numbers) carry over, since compatibility requires them.

## Measured contract (what the corpus actually needs)

From parsing both corpus sources through `gsasm.rez.parser` against the
golden include (inventory scripts in the session log, 2026-07-19):

- **Templates instantiated: 13 of Apple's 43** (+ `rMyCursor`, defined
  locally in sys.resources.r itself — not our problem):
  rIcon($8001), rControlList($8003), rControlTemplate($8004),
  rPString($8006), rMenu($8009), rMenuItem($800A),
  rTextForLETextBox2($800B), rWindParam1($800E), rWindColor($8010),
  rAlertString($8015), rErrorString($8020), rVersion($8029),
  rComment($802A).
- **Type-number `#define`s** referenced by bodies (typeids + `read`/code
  refs): the 13 above plus rCodeResource, rCtlDefProc.
- **Switch case labels**: simpleButtonControl, radioControl,
  statTextControl, editLineControl, iconButtonControl (all
  rControlTemplate).
- **Named values**: `infront` (rWindParam1), `release`/`verUS` (rVersion),
  `rMIItalic` (rMenuItem flag).
- **Oracle density**: 90 rErrorString, 21 rControlTemplate, 12 rIcon,
  10 rPString instances — every template has at least one
  (values → bytes) pair; the big ones have dozens.

## Work packets

1. **T1 — oracle harness** (`work/rez_types_diag.py`): per-resource golden
   byte slices (fork decoder already exists in the rezbuildcheck path)
   paired with parsed body ASTs, keyed by (type, id).  A `check_template`
   mode compiles ONE resource body against a candidate template and diffs
   its bytes — the per-template inner loop.
2. **T2 — the include** (`rinclude/Types.r`, committed; name resolvable as
   `typesiigs.r` via the existing case-insensitive include lookup):
   templates authored simplest-first — rPString/rComment/rErrorString/
   rAlertString (string kinds + termination/padding), rIcon (hex data),
   rVersion (bcd/named values), rWindColor/rWindParam1/rMenu/rMenuItem/
   rTextForLETextBox2/rControlList, then rControlTemplate (the 5-case
   switch, largest surface).  Each template lands only when every corpus
   instance of it round-trips byte-exact through T1.
3. **T3 — flip the harnesses**: `rezbuildcheck`/`easymountcheck`/
   `rezlexcheck` INCS point at the committed include ONLY; gate must stay
   green (rez_* metrics identical).  `work/rincludes/TypesIIGS.r` becomes
   unused by the gate (AIIGSIncludes asm includes remain — separate,
   assembler-side dependency for the embedded code resources).
4. **T4 — ship it**: package data + `gsrez` default include path;
   README/docs note.  The remaining 30 Apple templates are OUT OF SCOPE
   until a corpus target exercises them (house rule: no byte oracle, no
   claim); the include says so explicitly.

## Status — DONE in one session (2026-07-19)

All four packets landed same-day:

- T1: `work/rez_types_diag.py` (scoreboard + `--pairs` derivation view;
  validated end-to-end on rMyCursor's corpus-local decl, 6/6).
- T2: all 13 templates authored and byte-exact — 138/138 corpus resources.
  Notable derived mechanics: rIcon's computed
  `iconSize = (mask-image)/8` label span; rControlTemplate's
  `pCount = 3 + $$optionalCount(params)` with partial optional fill and
  the procRef long as switch key (iconButtonControl keys on the $07FF0001
  defproc-resource convention); rVersion's ReverseBytes group over
  big-endian-ordered fields; rMenu/rControlList template-supplied zero
  terminators.  Plus 8 corpus-dictated `#define`s (menu ref/flag
  constants) recovered by diffing token streams lexed under each include.
- T3: `_common.rincludes()` flipped; rezbuildcheck (library AND CLI),
  easymountcheck, rezlexcheck all byte-exact through the clean-room
  include ONLY; full gate at baseline.  The recovered Apple TypesIIGS.r is
  no longer consulted by any Rez pipeline.
- T4: shipped as package data (`gsasm/rez/include/TypesIIGS.r`, wheel-
  verified); `gsrez` appends it to the include path after user `-I` dirs;
  corpus-free guard `tests/test_rez_bundled_types.py`.

Mechanism-peek disclosure (clean-room boundary): template structures were
derived from oracle byte pairs.  For the three constructs whose Rez-dialect
expression could not be inferred from pairs alone (the `optionalCount`
pCount idiom, the OptionalField wrapper, ReverseBytes), the PARSED
field-kind skeleton of the recovered include was inspected — node kinds and
one arithmetic shape, no field names, no comments, no text.  Those
constructs are equally documented in the public MPW Rez manual's template
language; the peek confirmed which of them Apple's file exercised.

## Rules

- The golden include may be READ only for the bounded interface facts
  listed above (names/numbers the corpus dictates anyway); template
  structure comes from oracle pairs + public docs.  Cite the doc source in
  each template's comment.
- Gate discipline unchanged: rez metrics must not move until T3, where
  they must stay byte-identical with the new include in the path.
- Every derivation surprise (a padding rule, a string-kind quirk) gets a
  corpus-free fixture in `tests/` per the standing rule.

## Phase 2 — proving out the rest (plan set 2026-07-19, CDEV tier DONE 2026-07-20)

Coverage grows only with oracles, in three tiers:

1. **Shipping-fork oracles** (same discipline): archived `.r`/`.rez`/`.rii`
   source + golden fork off the System 6.0.1 disk images.  The census
   (session log 2026-07-19; NB the first pass missed `.rez` extensions —
   re-check globs when hunting sources) found 31+ sources.
2. **Forks without archived sources**: `DeRezIIGS` from the MPW-GM image as
   a decompilation cross-check while deriving from bytes.
3. **No shipping usage at all**: the real `RezIIGS` binary under SheepShaver
   as a controlled oracle (author original bodies, compile with Apple's
   tool, byte-compare).  Templates with NO oracle stay OUT of the include.

### CDEV sweep — DONE (2026-07-20, commits fa8ec8e + 6cc7072)

All 17 CtlPanel resource forks byte-exact (143,782 B; gate metric
`cdev_rsrc_bytes_exact`; `work/cdevcheck.py`, disk-parametrized over Disks
1/2/3/4).  `disk_logical_exact` 30 → 36 (five CDEVs + ControlPanel NDA
wired as diskcheck REZ builders).  `rCDEVCode`/`rCodeResource` reads are
extraction-fed from the golden forks (the Pascal-code wall; the whole Rez
layer around them is what is proven).  Template growth: rCDEVFlags
(fixed-capacity pstrings 16/33/9), rTwoRects, rTaggedStrings, rListRef
(empty case), and five rControlTemplate cases — checkControl $82000000,
scrollControl $86000000, popUpControl $87000000, listControl $89000000,
rectangleControl $87FF0003 — 10 of 14 known cases now golden-proven.

Dialect discoveries (each unit-guarded in tests/test_rez_lexer.py /
test_rez_gen.py; all corpus-neutral by full gate):

- An unterminated `/*` on a `#`-directive line ends AT the newline
  (AppleShare.r:782 vs its golden rWindParam1(60)).
- Preprocessor macro names are CASE-INSENSITIVE (fCtlProcNotPtr /
  FctlProcNotPtr; rPString spelling variants).
- Single-quoted char constants are big-endian-packed NUMBERs
  (FolderPriv `'GB'` → id 0x4742).
- A string-literal run absorbs adjacent `$"…"` hex segments (FolderPriv
  rAlertString trailing NUL).
- `$$optionalCount` counts FIELDS EMITTED including defaulted constants,
  not values consumed (listControl pCount=15 with defaulted listDraw).
- Resource attribute `noCrossBank` = 0x0010; `pstring[N]` = capacity,
  storage N+1 (rCDEVFlags author/version are pstring[32]/[8]).

Method notes: the token-stream diff for recovering `#define` values has a
blind spot when a definition expands to multiple tokens (zip alignment
shifts) — probe-file lexing (`#include` + bare identifiers, read the folded
numbers) is the reliable form; a build→catch-unresolved→probe→append loop
automates constant recovery.

### Finder sweep — DONE (2026-07-20; work/findercheck.py)

The Finder resource fork is byte-exact AND fully source-built — the only
non-Rez ingredient, the `read rFinderExtension(1)` payload, is gsasm-
assembled+linked+ExpressLoad'd from `KeyboardNav/KeyboardNav.aii`
(byte-exact on the first try; defines: Finder.make AOPTIONS +
`InitVersion=0`).  Gate metric `finder_rsrc_bytes_exact` 104790/104790;
`disk_logical_exact` 36 → 37.

**The Start dead end was wrong**: `/System.Disk/System/Start` IS the
Finder — its resource fork is byte-identical to Disk 3's
`/SystemTools1/System/Finder` (the Finder ships renamed as the boot
program).  findercheck checks BOTH golden copies; Start's rsrc fork is a
diskcheck REZ builder now.  (Start's DATA fork — the ~150 KB Finder OMF
executable built from the eleven `.aii` sources per Finder.make — is a
separate, large assembler target; unattempted.)

New templates (oracle: the 381-resource Finder fork): rToolStartup,
rRectList, rFinderPath, rCString, rText, rBundle (the 54-OneDoc icon-
matching beast: per-doc self-inclusive size word + matchFlags-offset word
from subscripted label differences, `$$optionalCount` launch element
count, 8-byte icon/path refs, tagged match sections as twelve two-armed
switches keyed 1..12 with `empty` storing a zero word; matchFlags bit n-1
<-> section n), plus rControlTemplate cases editTextControl ($85000000,
20 optional params) and thermometerControl ($87FF0002, value+scale) and
the launch/match `#define` sets (LaunchThis/reads/writes/native/creator =
$01/$10/$20/$40/$80; FileType/AuxType/FileName/NetworkAccess/HFSFileType/
HFSCreator = bit(section-1)).  rFinderExtension needs no template (the
source `#define`s it 0x0042 and only `read`s it).

Dialect discoveries (corpus-free fixtures in tests/test_rez_gen.py +
test_rez_bundled_types.py):

- `|` is a value-expression operator (lowest tier, below additive), and a
  field's symbolic named values stay in scope through such an expression
  (`FileType|NetworkAccess`) — lexer punct + parser tier + gen eval added.
- The speculative `$$ArrayIndex`/subscripted-label machinery is now
  GOLDEN-VERIFIED (rBundle), and its one real bug found+fixed:
  `$$optionalCount`/`$$Countof` of a group inside an array iteration must
  read per-iteration counts (`indexed_counts`, mirroring
  `indexed_offsets`) — the plain slot holds the last iteration's count by
  emit-pass time.
- 380/381 resources were byte-exact on the FIRST full-fork build; the 11
  differing bytes were all that per-iteration count bug.

### Installer sweep — DONE (2026-07-20; work/installercheck.py)

Byte-exact 17,895/17,895 (90 resources; gate metric
`installer_rsrc_bytes_exact`).  Installer.r turned out to be fully
SELF-CONTAINED — it declares all fifteen of its own templates
(rInstallScript, rDiskNames, rPicture, rMenuBar, rCtlColorTbl, …) and
includes nothing, so nothing was added to the bundled include
(corpus-local policy, the rMyCursor precedent); the target proves the
DIALECT.  The shipped variant compiles with `-d SystemSoftware` (MakeFile;
Easy Update).  87/90 resources were exact on the first build; the rest
were two dialect gaps (corpus-free fixtures in tests/test_rez_gen.py):

- `<<`/`>>` shift operators — two-char lexer tokens, a precedence tier
  between `|` and additive, gen eval (rPicture's Clip case
  `(ClipEnd[i]-ClipStart[i]) >> 3`; more subscripted-label machinery
  golden-proven, incl. `hex string [$$Word(ClipStart[i]) - 10]`).
- `\t` → 0x09 (keyEquiv `{"\t","",…}` pairs).
- `string [N]`/`hex string [N]` with a CONSTANT-FOLDABLE bracket
  zero-pads content to N (PnPat: 16 pattern bytes in a [32] field);
  a runtime bracket ($$Word…) keeps the rIcon content-length semantics —
  two prior fixtures that over-generalized "bracket ignored" to literal
  brackets were corrected against the new golden evidence.
- Already supported, exercised for the first time: `0b` literals,
  `#if defined NAME`.

### Next targets (tier 1, sources + goldens both confirmed on hand)
- **Teach** — `ToolBoxMisc/Teach/teach.r` (12 types incl rStyleBlock?).
  Golden: `/SystemTools2/Teach` (Disk 4).
- **MountImage** — `MountImageGS/MountImage.r` (7 types).  Golden location
  TBD (not on disks 1–4 walked so far; check 5–7 / the MountImage release).
- **Finder data fork** — the eleven-module AsmIIgs/LinkIIgs build
  (`-lseg` load segments incl. three dynamic ones, `-at $DB03`); would
  flip Start+Finder to dual-fork logical-exact.
