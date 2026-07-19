* fixture: a DS COUNT that is a full expression must fold across the blanks
* (MPW BLANKS-ON operand).  P8's Sel.Alt.n pads to a paragraph boundary with
*     ds.b (alt_dispatch + 16) - * -2
* where alt_dispatch is the ORG'd PROC label and `*` the current (origin-based)
* location.  gsasm previously CUT the operand at the first blank -> `(disp + 16)`
* and reserved 0x1010 = 4112 bytes, shifting the whole segment; it now folds the
* whole `- * -2` tail and reserves 5.  (A PURE-numeric tail like `ds.b 2 +2`
* still does NOT fold — that stays a count-with-comment; see fixture 041.)
*
* Here: 9 data bytes -> * = $1009; (disp+16)-*-2 = $1010-$1009-2 = 5 pad bytes;
* `tail` lands at offset 9+5 = 14 = $100E, so `dc.w tail` emits 0E 10.
disp	PROC	ORG $1000
	dc.b	1,2,3,4,5,6,7,8,9	; 9 bytes -> * = $1009
	ds.b	(disp + 16) - * -2	; paragraph pad: reserve 5 (NOT 4112)
tail	dc.w	tail			; offset 14 = $100E -> 0E 10
	ENDP
	END
