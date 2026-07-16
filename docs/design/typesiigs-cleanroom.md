# Design: a clean-room, distributable `TypesIIGS.r`

**Goal.** Ship a clean-room `typesiigs.r` with gsasm so `gsrez` is
*batteries-included* for real IIgs desktop development — not "bring your own
Apple copyrighted include."

## Why

`gsrez` is a general Rez compiler: it emits resource bytes from whatever
`type` templates the source gives it (inline or via `#include`). It hardcodes
no Apple types — proven by the corpus-free test suite, which declares its own
types inline and passes with zero Apple material.

But to compile Apple-dialect resource sources — and, more importantly, for a
developer to write *standard* IIgs resources (windows, controls, menus, icons,
strings, version, Finder bundles) — you need the standard type-template
library. Apple's `TypesIIGS.r` (~36 KB, ~46 types) is that library. It is
Apple copyright, gitignored, not distributable. So today gsrez can't ship a
usable resource toolkit.

A clean-room re-implementation fixes that: it's our own writing, legally
distributable, and — critically — *provably correct* against golden bytes.

## The oracle insight

We do **not** need to trust careful transcription. We already reproduce the
golden resource forks byte-exact. So a clean-room `typesiigs.r` is correct
**iff** `gsrez` + our file recompiles the golden corpus to the exact golden
bytes. Same differential-validation method as the whole project. The bytes
match or they don't.

Two sources, two roles:

- **Golden forks → correctness.** They pin the exact byte layout of every
  type the corpus uses. `work/rezcheck.py` decodes any golden fork;
  `rezbuildcheck`/`easymountcheck`/`rezgencheck` are the acceptance gate.
- **IIgs Toolbox Reference → ergonomics.** The bytes don't name fields
  (`wFrame` vs `wControls`) or give the symbolic constants (`verUS`,
  `release`, attribute bits, the `rMI*` menu-style flags). The reference
  supplies the readable names, comments, and `#define` tables. You *consult*
  it and write your **own** declarations — byte layouts and field names are
  functional specs (facts), not copyrightable expression. This is the same
  clean-room posture gsasm was built under.

## Scope: proven core vs reference-only tail

Our golden corpus (Sys.Resources + EasyMount) exercises ~17–20 of the ~46
types — the desktop-app core. Split the file accordingly:

**Proven core** (golden-validated byte-exact — the types a real app uses):
`rIcon`, `rControlList`, `rControlTemplate`, `rPString`, `rMenu`, `rMenuItem`,
`rTextForLETextBox2`, `rCtlDefProc`, `rWindParam1`, `rWindColor`, `rResName`
(synthesized), `rAlertString`, `rCodeResource`, `rErrorString`, `rCursor`
(a.k.a. `rMyCursor`), `rVersion`, `rComment`.

**Reference-only tail** (transcribed from the Toolbox Reference, *not*
golden-checked — flag them, same honesty as `gen.py`'s speculative markers):
`rPicture`, `rStringList`, `rMenuBar`, `rWindParam2`, `rStyleBlock`/
`rTextBlock`, `rToolStartup`, `rTwoRects`, `rFileType`, `rCString`/`rWString`,
`rSoundSample`, `rTERuler`, `rBundle`/`rFinderPath`, `rPrintRecord`, `rFont`,
`rCDEVCode`/`rCDEVFlags`, `rXCMD`/`rXFCN`, … (the rest).

## Method

1. Enumerate the corpus's used types (`work/rezcheck.py --dump` over the
   golden forks) — that's the proven-core list to nail first.
2. For each, derive the exact byte layout by decoding real golden resources
   of that type, and get field names/semantics + the `#define` constant
   tables from the Toolbox Reference. Write clean-room `type` declarations in
   our own words.
3. Validate: put our `typesiigs.r` on the include path *in place of* Apple's,
   and require `rezbuildcheck` (Sys.Resources), `easymountcheck` (resource
   fork), and `rezgencheck` (139/139) to stay byte-exact green. That is the
   acceptance test — functional equivalence, proven.
4. Add the reference-only tail, flagged unproven; extend the corpus over time
   (Finder, CDEVs) to promote tail types into the proven core as new golden
   forks exercise them.

## Deliverables

- `gsasm/rincludes/TypesIIGS.r` (or similar) — clean-room, shipped with the
  package; `gsrez` gains a default include path pointing at it so
  `#include "typesiigs.r"` just works out of the box.
- A test that recompiles the golden corpus with the clean-room file (Apple's
  off the path) and asserts byte-exact — wired into `work/gate.py`.
- Docs: a "writing IIgs resources with gsrez" quickstart once the core lands.

## Legal posture / street-library

Consult the Toolbox Reference; write our own declarations. Facts (layouts,
field names) aren't copyrightable; Apple's file text and the reference PDF
are — don't copy either verbatim, don't redistribute the PDF. The
**street-library commons** is the place to bank the *distilled* resource-format
facts as first-party learnings (e.g. "`rWindParam1` layout: …"), which this
work cites — knowledge capture, not book redistribution. (The commons already
carries gsasm-lineage learnings; this extends that.)

## Status

Planned. The proven-core path is well-bounded — a few dozen declarations, most
*provably* correct — and the validation harness already exists. This is the
piece that makes `gsrez` matter to the IIgs homebrew scene.
