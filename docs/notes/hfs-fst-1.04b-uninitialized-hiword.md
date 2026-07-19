# The other HFS.FST fix: recovering "1.04b" from a beta binary

*A second case study in relocation-aware subtraction — this time on the
community's own final HFS.FST, and it corroborates the people who wrote it.*

An [earlier note](hfs-fst-6.0.4-carry-bug.md) recovered the one-line multiply
fix that shipped in Apple IIgs System 6.0.4 — from the binary alone, with the
source long gone. That fix was real but, as it turns out, partial.

Petar Puskarich [opened an issue](https://github.com/emdeejay/gsasm/issues/1)
pointing this out. He
and Geoff Body spent about two years — Body coding, Puskarich running a large
hardware/timing test matrix — chasing the HFS corruption that persisted *after*
the 6.0.4 patch, and released the result as **HFS.FST 1.04b** at KansasFest
around 2020–2022. His recollection of the fixes, from Body:

> most of the fixes were properly initializing... a lot of the 16-bit
> variables that are in use before the code used them.

The source for 1.04b is gone too. All that survives is the beta binary, shipped
in the "System Add-ons" volume. Can we recover what they changed — and does it
match the account above?

## Getting the binary

The trail: the [whatisthe2gs](https://www.whatisthe2gs.apple2.org.za/news/) news
archive names the file (`HFS.1.04b.FST`), which points at the Call-A.P.P.L.E.
[announcement](https://www.callapple.org/vintage-apple-computers/apple-iigs/hfs-1-04-beta-announced/),
which links a ProDOS disk image: `callapple.org/soft/a2gs/gsos/hfs_1_04_Beta.po`.
`cadius` extracts one file from it — `hfs.1.04b.fst`, 36,922 bytes, whose
embedded version string reads `HFS FST          v01.04 Beta` (the 6.0.1 original
reads `v01.01`).

Three images now sit side by side:

| | file size | de-ExpressLoad'd code image | delta |
|---|---|---|---|
| 6.0.1 (Apple, original) | 36,922 B | 32,641 B | — |
| 6.0.4 (community, multiply fix) | 36,919 B | 32,638 B | −3 |
| **1.04b (Body / Puskarich)** | 36,922 B | 32,642 B | **+1** |

The size alone is a clue. 1.04b is **not** built on top of 6.0.4 (−3); it is a
separate branch off the 6.0.1 original with a net **+1**-byte code change. Two
independent forks of the same file.

## The method, unchanged

Same relocation-aware subtraction as before, because gsasm rebuilds the 6.0.1
original **byte-for-byte** (`work/fstcheck.py` — 32,641/32,641, byte-exact),
so every byte of that image maps back to a source line:

1. **De-ExpressLoad** all three images to flat code.
2. **Block-align** 1.04b against the 6.0.1 original (`difflib.SequenceMatcher`),
   which sees through the address shift.
3. **Classify** each edit: a single-byte `1→1` replace is relocation fallout
   (a shifted address); anything multi-byte or size-changing is a real edit.
4. **Name** each real edit by walking gsasm's own byte-exact layout to recover
   the segment and label at that offset.

```
1.04b vs 6.0.1 original:
  total edit regions:                     762
  single-byte 1->1 (relocation-shift):    757
  structural edits (insert/delete/multi):   5   ->  2 cosmetic + 3 functional
```

**762 differences collapse to 3 functional bytes**, at two code sites, plus a
handful of cosmetic version edits. The five structural regions are the version
*string* (`v01.01` → `v01.04 Beta`, two regions — the digits and the padding
spaces that make room for " Beta") and the three functional bytes below.

The 757 single-byte ripples are *almost* all relocation fallout — their signed
byte-deltas cluster hard on the two code-size changes:

```
delta -3: 541     (addresses pointing past the multiply site, which lost 3 B)
delta +1: 213     (addresses pointing past the net +1 change)
delta +3:   2     (branch displacement @2ce6, and one that isn't a shift — see below)
delta +4:   1     (branch displacement @56aa, adjusting for the +4 insert)
```

The honest caveat: subtraction *classifies* by heuristic, and one byte slips
through. The `+3` at offset `0x10` is **not** relocation fallout — it is the
numeric version field in the FST header (`DC.W $0101` → `$0104`), a deliberate
edit that happens to be a single byte and so lands in the "shift ripple" bucket.
The block-align can't tell it apart from a shifted address. The next section is
how we catch it — and prove the whole patch.

## Fix #1 — the multiply bug, again

The first functional edit is at offset `0x2cde`, in `WORD_MULTIPLY`:

```asm
          lsr  <multiplier      ; shift multiplier right — bit set?
          bcc  align            ; no
          clc                   ; yes — add multiplicand
          adc  <multiplicand
-         bcc  align            ; branch if no overflow   <-- 1.04b DELETES
-         inc  a                ; add in carry bit        <-- 1.04b DELETES
align     ror  a
          ror  <product
```

This is **byte-identical to the 6.0.4 fix** (same 3-byte deletion of `90 01 1a`
at the same offset). The bug — an extra `inc a` that double-counts the carry the
following `ror a` already folds in, corrupting `ablk→byte` disk-offset
arithmetic — is [dissected in the earlier note](hfs-fst-6.0.4-carry-bug.md).

So Body arrived at the *same* multiply fix independently. 1.04b is a strict
superset of the known-good 6.0.4 change — plus one more fix that 6.0.4 never
had.

## Fix #2 — the uninitialized high word

The new edit is in `ET_LOG_2_PHYS`, the routine that turns a logical file
position into a physical extent — core HFS block addressing. Its `@ok` block
does a 32-bit pointer add, `a1 = a1 + d1`, where `a1` is a pointer to the extent
descriptor and `d1` is the offset of the specific entry:

```asm
* calculate address of extent descriptor
@ok       clc
          lda  <a1              ; low word
          adc  |d1
          sta  <a1
          lda  <a1+2            ; high word
          adc  |d1+2            ; <-- adds the HIGH WORD of d1
          sta  <a1+2
```

`d1` here is a small entry offset — a 16-bit quantity. Its high word `d1+2`
**must be zero** for the pointer math to be correct. It isn't guaranteed to be.
`et_get_rec`, which produces `d1`, writes `d1+2 = $FFFF` on one path (a
"previous record" sentinel: `lda #-1 / sta |d1 / sta |d1+2`) and leaves it
untouched on others. So on entry to `@ok`, `d1+2` can hold stale data — and
`adc |d1+2` folds that garbage straight into the **high word of the
extent-descriptor pointer.** A wrong pointer means the FST reads its extent
mapping from the wrong address, producing wrong physical block numbers —
exactly the "serious corruption when blocks were changed and rewritten in the
HFS tree" Puskarich reported.

Here is what 1.04b actually changed, disassembled from both binaries
(gsasm's disassembler, validated against the 6.0.1 source it rebuilds):

```
  6.0.1 original                 1.04b modified
  ------------------------       ------------------------
  clc                            clc
  lda  <a1                       lda  <a1
  adc  |d1                       adc  |d1
  sta  <a1                       sta  <a1
                                 bcc  *+2          ; <-- inserted
                                 brk  #$69         ; <-- inserted
  lda  <a1+2                     lda  <a1+2
  adc  |d1+2       <-- BUG        adc  #0           ; <-- FIX
  sta  <a1+2                     sta  <a1+2
```

Two things happen:

- **`adc |d1+2` → `adc #0`** — the fix. Stop adding the uninitialized high word;
  add only the carry out of the low-word add. `d1` is now treated as the 16-bit
  offset it always was. This is *precisely* the class of bug Body described to
  Puskarich: a **16-bit variable used before it was properly initialized.** The
  original didn't read uninitialized memory by accident of a missing store — it
  read the high half of a value that only ever had a defined low half.

- **`bcc *+2 / brk #$69`** — a guard. If the low-word add carries (the pointer
  crosses a 64 KB boundary — the rare large-volume case this whole bug hides in),
  it traps to the monitor with `brk #$69`. The `adc #0` right after still
  handles the carry correctly; the `brk` is a **beta diagnostic** — entirely in
  character for a build labelled `v01.04 Beta` and QA'd against a large test
  matrix. It's there to *catch the moment the boundary case fires*, which is
  the exact condition the corruption depended on.

## Accounting for every byte

The whole 1.04b delta, in source terms:

```diff
  ; ET_LOG_2_PHYS @ok
   lda  <a1+2
+  bcc  *+2            ; beta carry trap
+  brk  #$69
-  adc  |d1+2          ; folded uninitialized high word into the pointer
+  adc  #0             ; propagate carry only
   sta  <a1+2

  ; WORD_MULTIPLY (identical to 6.0.4)
   adc  <multiplicand
-  bcc  align
-  inc  a
   ror  a
```

Net size: `+4` (the trap) `−3` (the multiply) `+0` (the same-size `adc` swap)
`+0` (version string) = **+1 byte**, matching `32642 − 32641` exactly.

## Proof by reproduction

Subtraction *isolates* the change; it doesn't *prove* it. The proof is to run
the recovery backwards: take the 6.0.1 source, apply the recovered edits — the
`$0101 → $0104` version field, the version string, the two-line multiply
deletion, and the `ET_LOG_2_PHYS` `bcc/brk`/`adc #0` — then reassemble, relink,
and re-ExpressLoad with gsasm, and compare the result to the *real* 1.04b binary.

```
$ python3 work/archive/hfs104b_roundtrip.py
rebuilt (patched 6.0.1 source) : 32642 bytes
real 1.04b binary (de-express) : 32642 bytes

  *** BYTE-EXACT — recovered patch reproduces 1.04b ***
```

Byte-for-byte. The patched source assembles to exactly the image Body and
Puskarich shipped — the same bar gsasm clears on the 6.0.1 original. This is
also what flushed out the version-field byte the block-align had mis-bucketed:
the first round-trip came back with **one** differing byte, at `0x10`, which is
precisely the `$0101`/`$0104` field. Reproduction leaves nothing to a heuristic —
either every byte matches or it names the one that doesn't. With that byte fixed,
the recovered patch is complete and exact, and "regenerate the source with all
the fixes folded in" is no longer a hope — it is a diff that builds.

## The point

The [first note](hfs-fst-6.0.4-carry-bug.md) recovered a fix whose authors were
anonymous. This one recovers a fix whose author *told us what he did* — and the
binary subtraction confirms it to the byte. Body said the fixes were
uninitialized 16-bit variables used before their time; the one functional data
bug in 1.04b beyond the shared multiply fix is exactly that: `adc |d1+2` reading
a high word that was never given a defined value, corrupting a disk pointer on
large volumes. We can now hand back not just "1.04b works better" but the two
specific instructions that make it work, in named routines, with the defect
explained — the raw material for regenerating the source "for posterity," which
is what the issue asked for.

---

*Reproduce it:*
*`python3 work/archive/hfs104b_analysis.py` — the subtraction: de-ExpressLoads the three
HFS.FST images, rebuilds the 6.0.1 offset→source map from gsasm's byte-exact
layout, block-aligns 1.04b, classifies the 762 edits, and disassembles both fix
sites.*
*`python3 work/archive/hfs104b_roundtrip.py` — the proof: applies the recovered edits to
the 6.0.1 source and rebuilds 1.04b byte-exact.*
*The 6.0.1 original is itself the image gsasm builds byte-exact
(`work/fstcheck.py HFS.FST`).*
