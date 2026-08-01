# Finding 5 hardening — structured evidence extraction report

Source: `docs/disk_census_2026-07-30.json` (read-only; nothing in the repo was modified).
Output: `c2_structured_evidence.json` (195 records, 195 gap entries), built by `build_structured.py`.

## Scope

195 census file-records carry classification `no-source-substitute`,
`pascal-c-nontarget`, or `technical-exception`:

| classification         | count |
|-------------------------|------:|
| no-source-substitute    |   185 |
| pascal-c-nontarget       |     8 |
| technical-exception      |     2 |
| **total**                |  **195** |

Per-disk breakdown:

| disk                              | count |
|------------------------------------|------:|
| Disk 1 of 7 Install.2mg            |    61 |
| Disk 3 of 7 SystemTools1.2mg       |    44 |
| Disk 5 of 7 Fonts.2mg              |    29 |
| Disk 6 of 7 synthLAB.2mg           |    23 |
| Disk 4 of 7 SystemTools2.2mg       |    19 |
| Disk 2 of 7 System Disk.2mg        |    13 |
| Disk 7 of 7 Apple II Setup.2mg     |     6 |

The 195 records reduce to only **96 distinct verbatim `evidence` strings**
(heavy duplication — e.g. the sentence `"Finder desktop DB; no producing
source (runtime metadata)."` alone covers 10 records, `"Installer SCRIPT
text data; verbatim copy in A.U.G/InstallerScripts/. No build step."`
covers 32). Every one of the 96 unique strings was read in full and
hand-annotated (not regex-guessed) into the four structured fields; the
annotation was then mechanically fanned out to all 195 records sharing that
string, plus each record's own `disk`/`path`/`classification`.

## Field coverage

| field            | populated | null (→ gap) | % populated |
|-------------------|----------:|--------------:|------------:|
| `decision`        |       195 |             0 |       100%  |
| `searched_trees`  |        21 |           174 |        11%  |
| `search_patterns` |        13 |           182 |         7%  |
| `search_date`      |         0 |           195 |         0%  |

By classification:

| classification         | n   | searched_trees | search_patterns | decision |
|--------------------------|----:|----------------:|------------------:|---------:|
| no-source-substitute     | 185 |              21 |               13 |      185 |
| pascal-c-nontarget       |   8 |               0 |                0 |        8 |
| technical-exception       |   2 |               0 |                0 |        2 |

`decision` hit 100% because it is a verbatim sentence (or short verbatim
span) copied directly out of the evidence text — never paraphrased — chosen
by: (a) the sentence containing a conclusion marker (`->`, "blocked by",
"non-target", "Carried verbatim", "cannot be regenerated", "FLAG", "no clean
enum bucket", "SUBSTITUTE by rule", "out of the ... scope", "outside
gsasm"), else (b) the evidence's last sentence. Every evidence string had at
least one sentence, so this never came up empty; it is a selection, not an
inference.

`search_date` is 0/195: **no evidence string in the entire 96-pattern corpus
anchors an absolute date to when a source search happened.** One record
(`/Fonts/Icons/Finder.Data`, Disk 5) contains the literal string
`2026-07-30`, but it reads `"ADDED 2026-07-30 (census agent dropped it;
Codex review)"` — that is the date the census *row* was added/reviewed, not
a search date, so it was correctly left null rather than misappropriated.

`searched_trees` and `search_patterns` are populated only when the evidence
explicitly frames a **search action** — "Searched X", "searched X", `grep
'x'`, `find -iname x`, "no producing source in X/Y/Z", "absent from
X/Y/Z". A record that merely states *where a verbatim copy was found*
(e.g. the 32-record `A.U.G/InstallerScripts/` family, or `pascal-c-nontarget`
records that name a concrete Pascal source path) does **not** get a
`searched_trees` entry — locating a copy/source is a different claim from
"I searched these trees and found nothing," and conflating the two would be
exactly the kind of overclaim finding 5 exists to prevent. That is why 174
records are null on `searched_trees`: most of the corpus either (a) names a
found location instead of a search, (b) is a rule-based classification
(Finder.Data basename rule, diskcheck SUBSTITUTE-by-rule) with no search
description at all, or (c) says "no source in any tree" / "all 3 source
trees" / "every source tree" generically without naming which trees.

## Normalizations applied

Only four, all unambiguous same-tree spelling variants, applied consistently wherever they occurred:

1. `ref/GSOS_6/IIGS.601.SRC` → `IIGS.601.SRC` (path-qualified vs. short form of the same tree used everywhere else in the census).
2. `ROM Source` / bare `ROM` (when it appears inside a slash-list alongside `IIGS.601.SRC`/`system500`, e.g. `"IIGS.601.SRC/ROM/system500"`) → `ROM Source Code` (the full name used in sibling records for the same tree).
3. `work/rincludes/system500` → `system500` (same tree, path-qualified vs. short form).
4. The compressed list `fst/driver/tool/os_bin` (in `/SystemTools2/AppleTalk/Finder.Data`'s evidence) → expanded to `["fst_bin", "driver_bin", "tool_bin", "os_bin"]`, matching the full directory names the same census file uses elsewhere (Disk 1 notes: `ref/GSOS_6/{driver_bin,fst_bin,tool_bin,os_bin}`).

Deliberately **not** normalized/expanded (left as literal null + gap
instead), because the record does not name the trees and expanding would be
guessing: `"all bin dirs"` (`/SystemTools2/Archiver`), `"any tree"` /
`"every source tree"` / `"all 3 source trees"` (dozens of records).

## Gaps

All 195 records have at least one null field (every record is missing
`search_date`, since no record anchors one). The gaps file
(`c2_structured_evidence.json` → `"gaps"`) has one entry per record listing
exactly which fields are null and why, categorized into these reasons:

| reason (paraphrased)                                                                 | records* |
|----------------------------------------------------------------------------------------|-------:|
| no search date stated anywhere in the evidence corpus                                  |    195 |
| evidence names an unnamed/generic set ("any tree", "every source tree", counted-but-unnamed) |     92 |
| copy/source location is named directly — not a "searched, found nothing" claim          |     51 |
| classification is rule-based (Finder.Data basename rule / SUBSTITUTE-by-rule) — no search described |     31 |
| no quoted grep/find search term present                                                |    182 |
| record documents a build-fidelity technical exception, not a source-search claim (Tool.Setup ×2) |      2 |

*counts overlap (a record can hit more than one reason across its missing fields).

**To close these gaps**, a human or a follow-up search-agent would need to,
per record: (1) for the 51 "copy located, not searched" records — either
re-run and log an actual adversarial search across all source trees for
each of those basenames (most are already known-present as verbatim copies,
so this would mainly be about proving *no other, wrong-version* source
exists), or explicitly accept that "found a verbatim copy" is sufficient
proof for `no-source-substitute` and stop treating `searched_trees` as
required for that sub-case; (2) for the 92 "generic any-tree" records —
go back to whatever search was actually run (this is very likely the same
3-tree sweep used on the sibling records that *do* name trees, e.g. the
Disk 5 font family) and record the actual tree list instead of "any tree";
(3) for the 31 rule-based records — decide whether a rule-based
classification (e.g. "any file named Finder.Data is a runtime desktop DB")
needs a tree search at all, since by definition no source could exist for
Finder-generated runtime state — if so, document that decision once at the
rule level rather than per file; (4) for `search_date` (all 195) — start
recording the date each adversarial search was actually run, since the
census currently never captures this anywhere.

## Records worth a second look (prose nuance / soft classification)

These aren't necessarily wrong, but the prose itself flags uncertainty or a
softer conclusion than a flat "no source exists," and are worth a human
pass:

1. **`/SystemTools2/Archiver`** (no-source-substitute) — evidence ends
   `"FLAG: would be buildable if source surfaced."` The record's own author
   flags this as contingent, not a hard wall.
2. **`/SystemTools2/CLOCK.PATCH`** (pascal-c-nontarget, `confidence: "low"`)
   — evidence explicitly says the file doesn't fit any clean bucket
   ("Applesoft BASIC, not asm/rez/Pascal/C ... no clean enum bucket; using
   pascal-c-nontarget as nearest non-target. FLAG for human decision.").
   This is a forced/approximate classification by the census author's own
   admission.
3. **`/SystemTools2/System/Drivers/IWEM`** (no-source-substitute) — nuance:
   source (`IWEm.Src` + the `BuildIWEm` MPW script) genuinely exists and
   builds *something*, but the built output diverges from the shipped
   binary after 78 bytes because the tree holds the wrong `IWEm.Src`
   version. This is "source exists but doesn't reproduce the exact bytes,"
   a materially different claim from "no source exists at all," even
   though it lands in the same `no-source-substitute` bucket.
4. **`/Apple II Script`** and **`/Installer`** (Disk 7, both
   no-source-substitute) — both are Macintosh-Rez / 68k-Mac payloads
   (`Types.r`/`InstallerTypes.r` Mac-Rez templates, a `bjbc`-signed 68k Mac
   Installer app) that are structurally out of scope for an Apple IIgs
   asm/Rez toolchain regardless of what's searched — a different flavor of
   "no source" than the font/data-file records (worth distinguishing from
   the rest of the no-source-substitute bucket if this classification is
   ever split further).
5. **`/Fonts/Icons/Finder.Data`** — the only record with a literal date in
   its evidence (`ADDED 2026-07-30`), but as noted above that date is about
   the census row's history, not a search; flagged here so it isn't
   mistaken for a real search-date data point during any future automated
   pass over this file.

No record's evidence prose actually *contradicts* its own classification
(e.g. nothing says "source found and builds byte-exact" while still being
classified `no-source-substitute`) — the five items above are softness/scope
nuances in otherwise-consistent classifications, not contradictions.
