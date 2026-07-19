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
