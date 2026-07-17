# The "proven ceiling" audit: how confident negative claims go wrong

*A postmortem on a batch of mislabeled "proven limits" — and the one lesson
worth keeping.*

gsasm's whole method is differential: everything it builds is checked
byte-for-byte against the shipping binary, so anything it reproduces is
*proven correct, not assumed*. That discipline was never the problem.

The problem was the other kind of claim — the **negative** one. Over the
project's life, several targets got written up in `RESULTS.md` as *proven
limits*: "symbols absent from the archive," "no source," "source disagrees
with the binary," "not derivable from these sources." Those read with the
same authority as the byte-match results. They shouldn't have. A byte-match
is a measurement; "we couldn't find it" is the absence of one.

This audit re-examined each. Here is what a single day of actually looking
turned up.

## GS.OS — "94 bytes reference symbols absent from the archive"

The residual 94 bytes of GS.OS referenced bank-$E1 vectors —
`E1_MSG_ADDRESS`, `E1_VOLNAME`, `E1_CURRENT_ID`. The write-up said they were
defined nowhere. They are `EXPORT`ed `DS.B` globals in `GQuit.src`, in a
bank-$E1 layout block that literally comments them *"accessed by SCM"* — SCM
being the module that was short. Apple's `linkOS` links the whole OS in one
pass and resolves the cross-reference; `gsasm`'s kernel harness linked SCM
without seeding GQuit's exports, so the references baked `$000000`.

Why it was missed: the original search looked for `equ`-style definitions and
never considered `EXPORT`ed `DS` globals in a `DUM` section. **94 → 44 bytes**
(the rest are named `gsasm` assembler bugs, not a floor).

## AppleShare.FST — "has no source in the archive"

There is a complete `GS.OS/FSTs/AppleShare/Src/` with 24 `.aii` modules, a
`MakeFile` with the exact link recipe, and a golden binary on the SystemTools2
disk. It builds to ~89%. Why it was missed: nobody ran `ls` on that
directory. (The MakeFile even *omits a real module*, `JudgeName.aii` — a bug
in Apple's own build script, visible only once you try to build it.)

## Tool019 (Print Manager) — "source disagrees with its shipping binary"

It disagrees by **one byte**, and the byte is a `gsasm` *linker* bug, not a
source revision. `linkiigs._defer_shifts` decided a right-shift was
placement-dependent (and so must defer to a load-time relocation) with the
guard `bool(syms) and all(...)`. For a *pure-literal* shift —
`pushlong #LocalPathEnd-LocalPathname`, where two same-segment labels'
difference already collapsed to the constant 31, and `31>>16` must be 0 — the
symbol set is empty, `bool(syms)` is false, and it wrongly deferred, baking
`$001F` where `$0000` belonged. Fix the guard and Tool019 is **byte-exact**.

The "two source trees" that made it *look* like a revision mismatch? The
second tree is an ORCA/M *listing dump*, not assembler input. A mirage.

## The scorecard

| documented limit | verdict |
|---|---|
| GS.OS "94-byte external floor" | false — 94→44, seeding + an assembler fix |
| AppleShare.FST "no source" | false — full source, builds ~89% |
| ExpressLoad case-B "not reproducible" | false — the flag was a source addend |
| Tool019 "source disagrees" | false — byte-exact after a 1-byte linker fix |
| ~JumpTable (Tool015/16/18) "unclosable" | overstated — the generator is in the MPW image |
| P8 "includes not in the tree" | overstated — they're likely in the image |
| SCSIHD.Driver "later source revision" | **holds** — positive differential evidence |

Four flatly false, two overstated, one solid. SCSIHD is the one backed by a
*measurement*: the shared `SCSI.Drivers` source builds its three sibling
drivers byte-exact and only the `type=0` variant diverges, with code inserted
throughout. That is what an evidence-backed limit looks like.

## The lesson (which applies to whoever reads this too)

Twice while running this audit, the author nearly shipped an under-verified
claim of their own: a corrected `RESULTS.md` paragraph not re-checked, and a
regression test that **passed with the bug still present** (it folded the
constant before reaching the buggy code path — caught only by deliberately
re-introducing the bug and watching the test stay green).

So the rule isn't "the old analysis was sloppy." It's structural:

- A **positive** result (bytes match) is self-verifying. A **negative** one
  ("absent," "unclosable," "not derivable") is only as good as the search
  behind it — and searches are easy to under-run.
- This archive has **three** source trees (`IIGS.601.SRC`, `ROM Source
  Code`, and the MPW/SheepShaver image `system500.hfv`). A claim checked
  against one of them is a third of a claim.
- Symbols hide as `EXPORT`ed `DS`/`DC` globals, not just `equ`. Grep
  accordingly.
- Before believing a test guards a fix, **re-introduce the bug and watch it
  fail.** A green test proves nothing until you've seen it go red.

The byte-exact reproductions were always trustworthy. It was the confident
"we can't" that needed a second look — and it usually didn't survive one.
