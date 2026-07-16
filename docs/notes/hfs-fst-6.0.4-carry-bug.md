# Subtracting Apple: recovering a lost HFS.FST bug fix from a binary

*A case study in what byte-exact reproduction is actually good for.*

Someone in the Apple IIgs community shipped a modified `HFS.FST` in the
"System 6.0.4" release — a bug-fixed version of Apple's file-system
translator. The source for their change is gone. All that survives is the
compiled binary on a disk image.

Can we recover what they changed, with no source, from the binary alone?

Yes. And it takes about five minutes, because gsasm rebuilds Apple's
*original* `HFS.FST` byte-for-byte from source — which means we don't treat
that binary as opaque bytes. We treat it as **fully-known structure**: every
byte maps to a source line, every label to an address, every relocation is
accounted for. That turns the modified binary into a subtraction problem.

## Why you can't just `cmp` them

The two files:

| | file size | de-ExpressLoad'd code image |
|---|---|---|
| 6.0.1 (Apple, original) | 36,922 B | 32,641 B |
| 6.0.4 (community, modified) | 36,919 B | 32,638 B |

Three bytes smaller. You'd think a byte compare would light up the handful of
changed bytes. It doesn't. A naive `cmp` reports the files diverge at offset
`0x10` and then **disagree almost everywhere after that** — 97% "different".

The reason is the classic reverse-engineering wall: the modification *removed
three bytes of code*. Everything downstream of that point shifted by three,
so every absolute address in the binary — every `JSR`, every `LDA abs`, every
pointer — now holds a different value. One tiny logic change, an avalanche of
mechanical fallout. A binary differ drowns in it.

## The method: relocation-aware subtraction

gsasm knows the OMF structure of these files completely. So:

1. **De-ExpressLoad both** (`gsasm.expressload.de_express`) — peel off the
   ExpressLoad packing to get the flat code images.
2. **Block-align them** (`difflib.SequenceMatcher`) instead of byte-comparing
   — this finds the genuinely-matching runs and isolates the true edit spans,
   seeing through the shift.
3. **Classify the edits.** A flood of *single-byte* changes is the fingerprint
   of relocation fallout (shifted addresses); real logic changes are
   multi-byte or change the code size.

The result:

```
total edit regions:                                     760
  single-byte 1->1 replaces (relocation-shift signature): 757
  structural edits (insert / delete / multi-byte):          3
```

**760 differences collapse to 3.** Two of the three are a cosmetic version
bump (a header byte `01`→`02` and some version-string digits). The third is
the entire functional change:

```
delete  orig[0x2CDE:0x2CE1] (3 bytes: 90 01 1A) -> mod (0 bytes)
```

Three bytes of code, deleted. And the −3 explains the whole avalanche: it
shifted everything after `0x2CDE` by three, which *is* the 757 address
ripples. The subtraction is exact.

## What those three bytes were

gsasm builds the original from source, so `0x2CDE` maps straight back to
`hfs.fst.main`, into a routine the surrounding comments name for us — a
plain **16×16 unsigned multiply** (shift-and-add):

```asm
* Initialize.
          ldx  #16              ;init bit count
          lda  #0               ;init hi word of product to 0
          stz  <product         ;init lo word of product to 0
* Do the multiplication.
next_bit  lsr  <multiplier      ;shift multiplier right. bit set?
          bcc  align            ;no
          clc                   ;yes - so add multiplicand
          adc  <multiplicand    ;to hi word of product
          bcc  align            ;branch if no overflow   <-- 6.0.4 DELETES
          inc  a                ;add in carry bit        <-- 6.0.4 DELETES
align     ror  a                ;rotate hi word of product right
          ror  <product         ;rotate lo word of product right
          dex                   ;done all bits?
          bne  next_bit         ;no - so loop
```

The callers tell you what it computes:

```
sta  <multiplicand   ;multiplicand = alloc block #
...                  ;convert '# of ablks per clump' ... by allocation block size
```

It converts **HFS allocation-block numbers into byte/logical offsets** —
core disk-addressing arithmetic.

## The bug

This is the textbook shift-add multiply: `A` accumulates the running **high
word**, `<product>` the low word, and each step rotates the pair right so the
add's carry folds into the top. The carry out of `adc <multiplicand>` is bit
16 of the running sum, and the very next `ror a` rotates it into bit 15 —
that *is* the carry mechanism. Nothing else is needed.

The original 6.0.1 code slipped an extra **`inc a` on overflow** in between.
`inc a` doesn't touch the carry flag, so when a partial add overflowed the
routine did *both*: incremented `A`, **and** let the still-set carry rotate in
via `ror a`. The overflow got **counted twice**. The product comes out wrong
— too large — whenever an intermediate sum carries, which is exactly what
happens for larger operands. Since this multiply computes disk positions from
allocation-block numbers, a wrong answer means **addressing the wrong part of
the volume**: silent corruption on volumes big enough to trip it.

The clincher that it was a real defect and not intent: the *same routine's*
fast-path special cases (a "Monte 4/2/92" optimization block a few lines up)
handle the identical carry with `inc <product+2>` — incrementing the high
word of the product, the correct idiom. Only the general loop did it wrong,
with `inc a`. 6.0.4 deleted the two bad lines and the general path now matches.

## The recovered patch

The whole thing, in source terms, is a two-line deletion:

```diff
           clc                   ;yes - so add multiplicand
           adc  <multiplicand    ;to hi word of product
-          bcc  align            ;branch if no overflow
-          inc  a                ;add in carry bit
 align     ror  a                ;rotate hi word of product right
```

Everything else in that 36 KB binary — the size change, the 757 shifted
addresses, the adjusted branch offsets — falls out of removing those two
lines. We recovered a lost bug fix, in a named routine, with the defect
explained, from a binary whose author and source are gone.

## The point

A `cmp` says "97% different." The byte-exact reproduction says "two lines,
here, and here's why." That gap is the whole value of building a clean-room
toolchain that reproduces the originals to the byte: it makes the shipping
binaries *legible* — not just checkable, but subtractable. Old software stops
being a wall of opcodes and becomes something you can do archaeology on.

---

*Reproduce it: `gsasm.expressload.de_express` on the two `HFS.FST` images,
then a `difflib` block-align of the flat code. The original 6.0.1 image is
the one gsasm builds byte-exact (`work/fstcheck.py`).*
