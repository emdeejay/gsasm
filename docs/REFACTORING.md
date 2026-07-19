# Refactoring Guide (2026-07-18 audit)

An analysis of the codebase's structural debt, written as work packets a junior
can execute. Read the **Prime Directive** and **Verification Recipe** before
touching anything; every packet below links back to them.

Status note (2026-07-19): R1 segment iteration, R2 harness common helpers,
R3 forensic-script quarantine, R4 annotation hygiene, R5 drift fixes, and R9
expressload decomposition landed with the Tier-1/E0 work.  R8 (link.py eval
utils -> omf.py, commit ea7ea5f), R6 (dispatch split, cebad22), and R7
(define_label predicates, 6731bb4) landed post-E3, each verified gate-stdout
byte-identical.  Remaining backlog: R10 (opt-in assembly cache) only.  Keep
this guide as the spec the landed commits were reviewed against.

---

## 0. The Prime Directive

This project's only product is **byte-exactness**: gsasm reproduces the ROM 03,
GS.OS, P8, tools, drivers, and FSTs byte-for-byte from the original source.
Refactoring here means **changing the shape of the code without changing a
single output byte**. The safety net already exists and is non-negotiable:

- `python3 tests/run_fixtures.py` — 53 corpus-free fixtures (~seconds).
- `python3 work/gate.py` — the full golden gate (~2 min, needs `ref/`).
  13 metrics, all currently at 100% except `obj_identical` (40/61, cosmetic —
  the 21 remainder are link-identical) and `operand_values` (745 known-benign
  relocation-base deltas).
- `python3 work/buildrom.py` — the shipping ROM 03 must stay byte-identical.

**Rules:**

1. A refactor PR must show `gate.py` output identical to baseline. Not "close",
   not "improved" — identical. If a metric *improves* you have accidentally
   changed behavior; stop and understand why before celebrating.
2. Never run `run_fixtures.py --bless` in a refactor PR. Blessing mints new
   expected bytes; a refactor by definition has nothing new to bless.
3. Behavior-bearing oddities are load-bearing. If a line looks wrong but has a
   comment citing a fixture, a golden file, or the MPW Asm Ref, it is a
   discovered AsmIIgs behavior — **do not "fix" it**. See §5 (Do-Not-Touch).
4. One packet per PR. Small diffs, mechanical transformations, no drive-by
   cleanups.

### Verification recipe (run for every packet)

```sh
python3 tests/run_fixtures.py                 # 53/53, fast inner loop
python3 work/gate.py                          # PASS, all metrics AT baseline
python3 work/buildrom.py | tail -3            # "verified byte-identical"
git diff --stat                               # only the files your packet names
```

For packets touching only `work/` harnesses, the fixtures can't regress, but
run the full gate anyway — the harnesses ARE the measurement instrument, and a
broken instrument that reports 100% is worse than a broken build.

---

## 1. The lay of the land

```
gsasm/            7,867 lines — the shippable library
  asm.py          3,060   macro engine, parser, pass logic  ← biggest debt
  expressload.py  1,290   ExpressLoad load-file packaging
  omf.py          1,242   OMF parse + emit
  linkiigs.py       799   the real linker (placement, SUPER, jump tables)
  m65816.py         425   instruction encoding (table-driven, clean)
  __main__.py       307   CLI
  makebin.py        251   MakeBinIIgs/OverlayIIgs models
  expr.py           250   MPW expression evaluator (clean)
  link.py           243   LEGACY eager flattener — now mostly a utility module
  rez/                    Rez compiler (lexer/parser/gen/emit — self-contained)

work/            10,410 lines — measurement harnesses (gitignored ref/ needed)
  kernelcheck.py  1,095   GS.OS build+compare      toolcheck.py  696
  diskcheck.py      400   whole-disk oracle        fstcheck.py   346
  drivercheck.py    345   + ~15 one-off diagnostic/probe scripts (see R3)
  diskbuilders/           per-artifact builders (p8_driver, toolsets, …)

tests/            2,581 lines — fixture runner + unit tests (healthy)
```

Import graph is acyclic and shallow (`asm → expr, m65816`; `omf → expr`;
`linkiigs/expressload/makebin → omf, link`). No package-level cycles — good.
The debt is *within* files (giant functions) and *across* `work/` (copy-paste
harness boilerplate), not in the architecture.

---

## 2. Tier 1 — mechanical packets (junior-friendly, low risk)

### R1. One OMF segment-walker to rule them all

**Problem.** The loop "walk a concatenated-OMF byte string, parse each
segment's header + records" is hand-rolled **20+ times**:

- `gsasm/makebin.py:63 _parse_segs` (dicts with name/hdr/recs/length)
- `work/diskbuilders/p8_driver.py:135 _parse_segs` (name/raw/length/org)
- `work/kernelcheck.py:303 _parse_obj_segs` (a third shape)
- bare `while off < len(...)` loops in `gsasm/__main__.py:104`,
  `gsasm/link.py:180`, `gsasm/expressload.py:52,245`, `gsasm/linkiigs.py:64`,
  `work/toolcheck.py:213,331`, `work/drivercheck.py:187`, `work/fstcheck.py:178`,
  `work/linkcheck.py:103`, `work/diskbuilders/expressload_files.py:88`, …

Each clone re-derives `BYTECNT`/`DISPDATA`/`NUMLEN`/`LABLEN` handling and the
`bc == 0` stop condition; several have subtly different SEGNAME decoding
(`.strip()` vs `.rstrip('\x00').strip()` vs `.upper()`).

**Fix.** Add ONE canonical iterator to `gsasm/omf.py`:

```python
def iter_segments(data: bytes, *, records: bool = True):
    """Yield one dict per OMF segment in *data*:
    {'name', 'raw', 'hdr', 'recs' (None unless records), 'off'}.
    'name' is the SEGNAME decoded mac_roman and stripped, ORIGINAL case —
    callers .upper() at their own comparison sites.
    """
```

**Steps.** (a) Implement + migrate the three named `_parse_segs` clones first,
keeping each caller's post-processing (upper-casing, org extraction) at the
call site so the diff is transparently mechanical. (b) Migrate the bare loops
one file per commit. (c) Leave `parse_header`/`parse_records` untouched — the
iterator wraps them.

**Trap to avoid:** do NOT normalize case inside the iterator. kernelcheck and
linkiigs compare names differently; changing case handling changes symbol
resolution → bytes.

**Verify:** full recipe. ~1 day.

### R2. `work/_common.py` — kill the harness boilerplate

**Problem.** Every `work/*.py` script re-implements the same five things:

1. **Path bootstrap** — 40 copies of `sys.path.insert(0, …)` sequences with
   ad-hoc `_ROOT` computation (`p8_driver.py:67-71` computes it with three
   nested `dirname`s and a comment explaining why).
2. **Include-path building** — 12 copies of
   `INCS = [CMN] + [d for d,_,_ in os.walk(GSOS)] + ['work/includes']`
   (`fstcheck.py:64`, `drivercheck.py:80`, `bytecheck.py:13`, `buildrom.py:22`,
   `linkrom.py:20`, `objcheck.py:11`, `linkcheck.py:20`, …). Some walk `GSOS`,
   some walk `ROOT`, some order `work/includes` first, some last — the order
   matters (include shadowing), so capture each variant as a named function:
   `gsos_incs()`, `romsrc_incs()`.
3. **`_IGNORE_OPS` + `_assemble()` error filter** — 3 identical copies
   (`kernelcheck.py:192`, `diskbuilders/kernel_setup.py:50`,
   `diskbuilders/kernel_os.py:69`). Note `p8_driver.py` deliberately does NOT
   ignore errors anymore (P8 builds clean and raises) — that asymmetry is
   intentional; the shared helper needs an `ignore_ops=` parameter, and
   p8_driver keeps its strict local version.
4. **Golden-file discovery** — `kernelcheck._find_golden` and friends.
5. **Byte-compare + "first diff @" printer** — 8 near-identical printers
   (`drivercheck.py:297`, `fstcheck.py:265,288`, `p8check.py:57`,
   `toolcheck.py:666`, `kernelcheck.py:886 _compare`, `linkrom.py:274`, …).
   Standardize on one `compare_bytes(mine, gold, label, show_diff) -> (m, n)`
   that prints the existing formats. **Careful:** `gate.py` regex-scrapes
   specific output lines (`work/gate.py:38-…` — e.g.
   `r'CORPUS raw code-image match:\s*(\d+)/(\d+)'`). The printed strings are
   API. Do not reword them; the helper must reproduce them verbatim.

**Steps.** Create `work/_common.py`; migrate ONE script per commit, diffing the
script's full stdout before/after (`python3 work/fstcheck.py > /tmp/a` vs
`/tmp/b; diff`). ~2 days for full coverage; stop any time — partial migration
is still a win.

### R3. Quarantine the forensic one-offs

**Problem.** `work/` mixes living gates with ~15 dead investigation scripts:
`tool016_diag.py`, `reloc_diag.py`, `reloc_survey.py`, `profst_diag.py`,
`appleshare_diag.py`, `hfs104b_analysis.py`, `hfs104b_roundtrip.py`,
`mpwmake_probe.py`, `p3_oracle.py`, `jumptable_probe.py` (superseded by
`expressload.encode_jumptable` — the port is noted in the handoff docs),
`loader_residual.py`, `startgsos_diag.py`, `toolsetup_probe.py`.

These are **evidence, not tooling** — several docs claims cite them (e.g.
`tool016_diag.py` decomposes the 451-diff misdiagnosis; `jumptable_probe.py`
proves the ~JumpTable codec). Deleting them would orphan the paper trail.

**Fix.** `git mv` them to `work/archive/` with a one-paragraph README each
(what question it answered, which doc cites it, date). Update any doc paths
that reference them (`grep -rn "tool016_diag\|jumptable_probe" docs/`).
**Do not edit their code** — they ran against a specific tree state; they are
allowed to bit-rot. Gate scripts (`gate.py` table) must all remain in `work/`
proper. ~half a day.

### R4. Annotation + Python-floor hygiene

**Problem.** `pyproject.toml` pins `requires-python = ">=3.9"` and CI runs a
3.9/3.12/3.14 matrix — but annotation style is inconsistent: 4 files have
`from __future__ import annotations`, 5 use bare PEP-585 generics without it
(safe on 3.9, but only accidentally), and nothing guards against someone
adding a PEP-604 `X | None` annotation to a file without the future import
(runtime `TypeError` on 3.9 that CI would catch late).

**Fix.** Add `from __future__ import annotations` as line 2 of every
`gsasm/**/*.py` (after the docstring). Zero behavioral risk. While there,
confirm `python3.9 -c "import gsasm.asm, gsasm.rez.parser"` in CI covers
import-time evaluation (it does today via the fixture run). ~1 hour.

### R5. Docstring/comment drift sweep

**Problem.** This project's docs are unusually load-bearing (they encode the
proof trail), which also means stale claims are actively harmful. The high-signal
claims swept in this branch:

- `gsasm/makebin.py`'s ProBoot 1666/1668 note has been re-verified against
  `work/probootcheck.py` and rewritten as a historical regression marker.
- `work/kernelcheck.py` now points to `work/p8check.py` for the accepted full
  P8 gate instead of excluding P8 from scope.
- `docs/GSOS_MILESTONES.md`, `docs/RESULTS.md`, `docs/TODO.md`, and
  `docs/design/expressload.md` have been swept for the highest-impact stale
  tool/FST/driver/kernel/P8 residual claims.
- Sweep procedure: `grep -rn "out of scope\|not fixable\|known gap\|TODO\|for now" gsasm/ work/ docs/`
  and for each hit either (a) re-verify the claim with a command and leave a
  dated confirmation, or (b) rewrite it citing the commit that closed it.
  **A claim you did not re-verify keeps its old wording** — this repo's core
  lesson (see `docs/TODO.md` §6) is that unverified negative claims rot.

~1 day, no code changes, pure docs.

---

## 3. Tier 2 — structural packets (senior review required)

These change code that produces bytes. The transformations are still meant to
be identical-output, but the blast radius justifies review + extra care.

### R6. Break up `Asm.dispatch` (asm.py:2007, **548 lines**)

The directive dispatcher is one `if u == 'X': … return` ladder handling ~45
directives inline. It works, but every new dialect discovery makes it longer,
and unrelated directives share accidental local state.

**Mechanical plan (do exactly this, nothing cleverer):**

1. For each directive block, extract a method `_dir_org(self, ln, u)`,
   `_dir_longa(self, ln)`, … — **copy the body verbatim**, replace the inline
   block with the call. One commit per ~5 directives.
2. Keep evaluation ORDER identical: the ladder's order is semantically
   meaningful in places (e.g. `_MNEM_SYNONYM` translation happens after the
   directive checks; `MACHINE` must be checked before the ignore-list since we
   removed it from there). The end state is still a sequential ladder of
   one-line calls — NOT a dict lookup. A dict dispatch changes order semantics
   and is a follow-up only after the extraction proves byte-neutral.
3. Do not rename locals inside moved bodies; do not merge "similar" branches.

Success criterion: `git diff` shows only moved lines; gate identical. ~2 days.

### R7. Name the collision rules in `define_label` (asm.py:1080, **232 lines**)

`define_label` encodes ≥6 hard-won symbol-collision rules (proc-local EQU vs
EXPORT/ENTRY/IMPORT, WITH-masked record fields, `prior_modscope`, ENTRY
last-wins narrowing, …) as nested conditionals. Each rule traces to a fixture
(036, 039, 042, 044, 048…). Extract each *predicate* (not the action) into a
named private method with the fixture number in its docstring:

```python
def _equ_reuses_global_name(self, name, kind): ...   # fixture 036
def _label_reuses_entry_elsewhere(self, name): ...   # fixture 039
```

The goal is that the next collision bug gets diagnosed by reading rule names
instead of re-deriving the whole ladder. Byte-neutral by construction if the
short-circuit order is preserved — add a comment at the top stating the order
is load-bearing. ~1-2 days.

### R8. Retire `gsasm/link.py` as a public linker; keep it as `omf` eval utils

**Current reality (measured):** importers use `_link._eval` (8 sites),
`_link._build_body` (8), `_link._make_segment` (3), `_link._body_length` (2) —
and only 3 callers use `link.link()` itself (`__main__`, `work/linkcheck.py`,
fixtures with `"link": true`). link.py is no longer the linker (linkiigs.py
is); it's a record-evaluation utility module wearing a linker's docstring.

**Plan:** (a) Move `_eval`, `_build_body`, `_body_length`, `_make_segment`
into `gsasm/omf.py` (they are OMF-record semantics); re-export from link.py
with deprecation comments so zero call sites change in this PR. (b) Follow-up
PR: mechanically update the 8+8+3+2 call sites, leaving `link.link()` alone
(it's the fixtures' `"link": true` oracle — renaming it would dirty blessed
fixture metadata for no gain). ~1 day + review.

### R9. Decompose `expressload._build_het_lconst` (271 lines) and `expressload()` (221 lines)

These build the ExpressLoad directory segment — the next active frontier
(Tool015/016/018/034, TS2/TS3 whole-file packaging), so investing here has
compounding returns. Extract the per-table builders (`_het_entries`,
`_seg_conversion`, `_seg_headers`, pathname block) as pure
`bytes -> bytes` functions with the golden layout offsets in their docstrings
(cross-reference `docs/design/expressload.md`). Do this BEFORE starting the
multi-segment packaging feature, not after — the feature will double this
file's complexity otherwise. ~2 days.

### R10. Opt-in assembly cache for the gate's inner loop

**Problem.** `gate.py` takes ~100s; kernelcheck/toolcheck/fstcheck/drivercheck
each re-assemble overlapping sources (12 different `os.walk` include sweeps).
During a debugging session you often run 3-4 checks back-to-back on an
unchanged tree.

**Plan:** a keyed cache (`source mtimes + defines + sysdate → emitted OMF`)
in `work/_common.py`, **opt-in via `GSASM_CACHE=1`** and disabled in `gate.py`
runs by default. It must be impossible for the cache to be on during a
baseline-updating (`--update`) or blessing run — assert against it. The cache
lives in `work/.cache/` (gitignore it). This is a pure harness accelerant;
the risk (stale cache masking a real diff) is why it stays opt-in. ~1 day.

---

## 4. Explicit non-goals

- **No renaming of gate-scraped output strings** (gate.py regexes are the
  contract; see R2 item 5).
- **No "modernization" passes** (dataclasses, pathlib, f-string sweeps,
  logging framework). The style is deliberately flat and greppable; the
  audience is forensic debugging, not framework aesthetics.
- **No test framework migration.** The bespoke fixture runner + bless
  interlock IS the methodology (`tests/run_fixtures.py` docstring). pytest
  would blur the corpus-free / golden-gated distinction.
- **No reordering of include paths, symbol tables, or record emission** even
  when order "shouldn't" matter. In this codebase, order is behavior until
  proven otherwise (see the `work/includes` shadowing note in R2).

## 5. Do-Not-Touch registry (behavior-bearing quirk code)

Any line in these zones is a discovered AsmIIgs behavior with a fixture or
golden proof behind it. Refactors may MOVE them verbatim (R6/R7) but never
"simplify" them:

| Zone | Why |
|---|---|
| `asm.py first_field` + `_NUM_ADDEND_TAIL` + `_EXPR_CONT_OPS` + `count_dir` | BLANKS-ON operand folding; fixtures 041, 045, 052 |
| `asm.py subst` / `_var_str` | undefined-`&NAME`-literal + comment rules; fixture 053 |
| `asm.py define_label` collision ladder | fixtures 036/039/042/044/048 |
| `asm.py emit_line`/`reserve` overlay logic | backward-ORG overlays; fixture 051 + AD3.5 |
| `asm.py _cond_leaf`/`_outer_parens_wrap`/`eval_cond` | fixture 050 + PushWord/PushLong history |
| `asm.py MACHINE/LONGA/LONGI` handlers | fixture 049; Monitor.aii ordering |
| `m65816.py` OPTABLE + `encode` + `_crossbank`/`_width` | the sizing rules; 100% opcode corpus |
| `expr.py` division/`*`-PC/MSB semantics | MPW truncating division; `pea '“'` mac-roman |
| `omf.py _diff_reloc`/`_mul_reloc_expr`/`_grouped_linear_reloc` | fixtures 035/040/044/047 |
| `expressload.py _scan_case_b` gating `(size,shift)∈{(2,0),(2,16)}` | dc.l false-positive guard |
| `linkiigs.py _defer_shifts` `const_only` predicate | Tool019 1-byte bug fix |
| all of `tests/fixtures/**` | blessed bytes; only `--bless` after a green gate may write them |

When in doubt: if deleting the line would flip a fixture or a gate byte, it is
behavior, not style.

## 6. Suggested sequencing

| Order | Packet | Risk | Est. |
|---|---|---|---|
| 1 | R4 annotations | none | 1h |
| 2 | R3 archive one-offs | none | 0.5d |
| 3 | R5 docstring sweep | none | 1d |
| 4 | R2 `work/_common.py` | low (harness-only) | 2d |
| 5 | R1 `omf.iter_segments` | low-med | 1d |
| 6 | R8 link.py utils → omf | med | 1d |
| 7 | R6 dispatch split | med | 2d |
| 8 | R7 define_label predicates | med | 1-2d |
| 9 | R9 expressload decomposition | med | 2d |
| 10 | R10 assembly cache | med (opt-in) | 1d |

Each packet independently shippable; stop anywhere. R9 should land before the
ExpressLoad multi-segment packaging feature (the remaining disk frontier);
everything else is order-flexible after the Tier-1 block.
