* fixture: a bare ORG (no operand) resets the record location counter to the
* MAXIMUM offset reached so far — MPW 3.0 Assembler Reference p.102:
*   "If you use ORG with no operand, the Assembler sets the current location
*    counter to the maximum positive ... location-counter value assigned to the
*    module up to this point."
* This is the variant-record / union idiom: two overlay arms mapped over the
* same base via `ORG vstart`, then a bare ORG to make the record size span the
* LARGER arm.  (GS/OS my_direct_page: graphics vs. text dialog overlays ->
* my_dp_size must be 80, the graphics arm, not 74, the text arm.)
* Without bare-ORG-to-max, gsasm sized the union at the LAST arm (small: 6),
* so `dc.w vsize` emitted 6 instead of the correct 12.
myrec	record	0
a	ds.w	1		; +0
b	ds.w	1		; +2
vstart	equ	*		; +4  (start of variant area)
	org	vstart		; arm 1 (large): two longs -> ends at +12
big1	ds.l	1
big2	ds.l	1
	org	vstart		; arm 2 (small): one word -> ends at +6
small1	ds.w	1
	org			; bare ORG -> reset to max (+12)
vend
vsize	equ	vend-myrec
	endr
chk	PROC
	dc.w	vsize		; -> 12 ($000c), the larger arm, NOT 6
	ENDP
	END
