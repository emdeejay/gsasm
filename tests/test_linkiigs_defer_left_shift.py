"""Hand-authored test for E3's linker fix (Tool034/TextEdit closure):
``linkiigs._defer_shifts`` must defer LEFT shifts on a relocatable
expression exactly like right shifts — the stored field is the un-shifted,
segment-relative target and the shift becomes a load-time relocation.

BUG (pre-fix): only ``count < 0`` (right shift) deferred.  A left shift
baked ``(offset << N) & mask`` into the stored bytes.  TextEdit fastdraw's
return-address trick

    pea  |(returnHere-1)>>8
    lda  #(returnHere-1)<<8      ; low byte of the address, high-positioned
    ora  theCodePtr+2
    pha

ships in gold Tool034 with BOTH operands stored as the un-shifted offset
($3226) under shift relocs; baking the << made the stored image differ AND
would compute the wrong runtime value once the loader relocates the segment
(the relocated address's low byte is not the link-time one).

A shift over link-time constants (GEQU / abs_extra) still resolves at link
time, left or right.

Two assertions (2026-07-19 adversarial-review Finding 3: body bytes alone
under-specify the fix — a bug that stores the un-shifted value but DROPS the
load-time record would pass a body-only check while relocating wrong at
runtime):

  1. linkiigs.link merged body: both operands store the un-shifted target.
  2. expressload() — the path that ships the TextEdit class — emits BOTH
     standalone cRELOC records: (size 2, shift -8) for the >> site and
     (size 2, shift +8) for the << site, each with the correct patch offset
     and the un-shifted target as relOffset (gold Tool034 main carries
     exactly this pair: (2,0xf8,0x321b,0x3226) + (2,0x08,0x321e,0x3226)).

Run either as:
    python3 -m pytest tests/test_linkiigs_defer_left_shift.py
    python3 tests/test_linkiigs_defer_left_shift.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from gsasm import asm, omf, linkiigs               # noqa: E402
from gsasm.expressload import expressload          # noqa: E402

# Target sits at offset 6 (lda #.. is 3 bytes, ora abs 3 bytes).  The two
# shifted immediates must BOTH store the un-shifted offset of Target.
SOURCE = (
    'Shifty\tPROC\n'
    '\tlda\t#(Target-1)<<8\n'
    '\tora\t$1234\n'
    'Target\tanop\n'
    '\tlda\t#(Target-1)>>8\n'
    '\trts\n'
    '\tENDP\n'
    '\tEND\n'
)


def _assemble(tmp):
    src = os.path.join(tmp, 'shifty.asm')
    with open(src, 'w') as fh:
        fh.write(SOURCE)
    a = asm.assemble(src, [tmp])
    assert not a.errors, a.errors
    return omf.emit(a), a


def test_left_shift_defers_like_right():
    with tempfile.TemporaryDirectory() as tmp:
        obj, a = _assemble(tmp)
        linked = linkiigs.link([(obj, a)], opts={'merge': True})
        img = b''.join(r[2] for seg in omf.iter_segments(linked)
                       for r in seg['recs'] if r[1] in ('CONST', 'LCONST'))
        # Target-1 = 5.  Un-shifted stored value 0x0005 for BOTH sites:
        # baking would store 0x0500 at the << site.
        assert img[0] == 0xA9
        assert img[1:3] == b'\x05\x00', f'<< site stored {img[1:3].hex()}'
        assert img[7:9] == b'\x05\x00', f'>> site stored {img[7:9].hex()}'


def test_shift_relocs_survive_into_expressload_dictionary():
    """The deferred shifts must become standalone cRELOC records in the
    ExpressLoad output — not just un-shifted body bytes (Finding 3)."""
    with tempfile.TemporaryDirectory() as tmp:
        obj, a = _assemble(tmp)
        out = expressload([(obj, a)])
        crelocs = [r[2] for seg in omf.iter_segments(out)
                   if seg['name'] == 'main'
                   for r in seg['recs'] if r[1] == 'cRELOC']
        # (size, shift_byte, patch_offset, rel_offset); shift byte is the
        # OMF signed convention: 8 = left 8 (the << site at operand offset
        # 1), 0xF8 = right 8 (the >> site at operand offset 7).  relOffset
        # is the un-shifted target Target-1 = 5 for both.
        assert (2, 8, 1, 5) in crelocs, f'<<8 cRELOC missing: {crelocs}'
        assert (2, 248, 7, 5) in crelocs, f'>>8 cRELOC missing: {crelocs}'


if __name__ == '__main__':
    test_left_shift_defers_like_right()
    test_shift_relocs_survive_into_expressload_dictionary()
    print('ok')
