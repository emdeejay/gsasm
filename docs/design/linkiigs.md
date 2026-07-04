# Design: general LinkIIgs (M2 — the keystone)

**Replaces:** MPW `LinkIIgs -apw`. **Unlocks:** tools (M1), FSTs+drivers (M5),
GS/OS kernel (M6). Read `README.md` first.

## What it does
Takes N OMF object files (each multi-segment, APW/OMF format as produced by
`omf.emit`) and produces one relocated OMF **load file** — every segment placed at
a load address and every relocation/expression resolved. Two output modes:

- **merged** — concatenate all segment bodies into a single `LCONST` load segment
  (what a trivially-linked tool looks like before ExpressLoad). This is what
  `link.link` does today for one object; generalize to N objects.
- **segmented** — keep segments distinct with their relocation dictionaries. This
  is the input ExpressLoad (M4) needs, and what real multi-segment load files use.

## Why the current code isn't enough
- `gsasm/link.py` links exactly one object and carries only segment names +
  `GLOBAL`/`GEQU` in its symbol table — it misses internal cross-segment data
  labels (`lda #SomeVar` where `SomeVar` is in a sibling segment resolves to 0).
- `work/linkrom.py` does full multi-object relocation but is hard-wired to ROM
  bank placement (`BANKS`, fixed ORGs).
- `work/toolcheck.py::link_module` already prototypes the right approach (assemble
  → `omf.emit` → place sequentially → resolve with a **full** symbol table seeded
  from `asm.symbols`/`asm.symseg`). Promote that into `gsasm/linkiigs.py`.

## Algorithm
```
link(objects, opts) -> load_file_bytes
  objects: list of (obj_bytes, optional Asm)   # Asm gives the full symbol table
  opts: { order, kind, org|None, loadname, merge: bool, extern: {NAME:addr} }

  # pass 1: parse + place
  segs = []                       # (name, records, base, numlen)
  base = opts.org or 0
  for obj in objects (in opts.order):
      for each segment in obj:
          recs = omf.parse_records(seg, dispdata, numlen, lablen)
          length = link._body_length(recs)
          segs.append((name, recs, base, numlen))
          base += length           # sequential; honor per-seg ORG if set

  # pass 2: global symbol table  (THE fix — full table, not just GLOBALs)
  sym = {'__LOC__': 0}
  for (name, recs, segbase, _) in segs:
      sym[name.upper()] = segbase                      # segment start
  for obj with its Asm a:
      for label, off in a.symbols.items():             # every internal label
          sg = a.symseg.get(label)
          if sg is not None: sym.setdefault(label.upper(), base_of(a,sg)+off)
  for label, expr in GEQU records: sym[label] = eval(expr, sym)
  sym.update(opts.extern)                              # unresolved externals

  # pass 3: resolve
  bodies = [link._build_body(recs, sym, segbase) for (_,recs,segbase,_) in segs]

  # pass 4: emit
  if opts.merge: return link._make_segment(loadname, ..., b''.join(bodies))
  else:          re-emit each segment header + its relocated body + its reloc
                 records rebased for the load addresses   # for ExpressLoad
```
Reuse `link._eval`, `link._build_body`, `link._body_length`, `link._make_segment`.
For `base_of(a, sg)`, track each Asm's segment→base map during pass 1.

## Relocation frame (critical — see README gotcha 3)
The shipping tools store base-0 placeholders + a SUPER dict; a plain link at base 0
matches most refs but not shifted ones (`#^Label`). For **validation** you have two
consistent options; pick one and use it everywhere:
1. link at base 0 and compare against the shipping LCONST **relocated to base 0**
   (apply its SUPER dict at base 0 — needs M4's SUPER decode), or
2. link at a fixed nonzero base B and compare against the shipping file **loaded at
   B** (apply its SUPER dict at B). This is closest to "what the loader produces".
Document which; `toolcheck.py` currently does an un-relocated compare (98% ceiling).

## Integration
- New file `gsasm/linkiigs.py` with `link(objects, opts)`.
- `work/toolcheck.py::link_module` → thin wrapper over it.
- Optionally re-express `work/linkrom.py` placement in terms of it (ORG per bank).
- **Do not modify `gsasm/link.py`/`omf.py` semantics** the ROM relies on; you may
  add functions.

## Validation & acceptance
- `python3 work/toolcheck.py` — single-object managers stay ≥98% (no regression),
  and the harness now uses `linkiigs.link`.
- Unit test: `linkiigs.link([scrap.obj], merge=True)` == `link.link(scrap.obj)`
  byte-for-byte (backward-compat on the single-object path).
- ROM gate: `buildrom.py`+`objcheck.py`+`linkcheck.py` unaffected (this is new code).
- **Done when:** any of {a tool, an FST, a driver} links to a byte-image that
  matches its golden LCONST (post-relocation-frame) — i.e. M2 is proven the moment
  one M5 target byte-matches through it.

## Gotchas
- Segment/link order must match the makefile (transcribe it; don't sort).
- `RELEXPR` needs the correct `next_pc` (`segbase + pos + nb`) — `_build_body`
  already does this; keep bases consistent between placement and resolution.
- Unresolved cross-module externals (implicit externals) stay by-name; pass them in
  `opts.extern` or leave 0 and flag — do not silently mis-resolve to a ROM equate
  (the symbol-shadowing bug).
