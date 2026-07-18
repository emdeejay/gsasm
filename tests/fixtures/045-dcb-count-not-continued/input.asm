* fixture: DCB is a COUNT directive (like DS), NOT a DATA-value directive (like
* DC.B/W/L).  Its first field is a byte count, so `dcb.b 2 +2` reserves 2 bytes —
* the trailing `+2` is an unmarked comment (the corpus reads as BLANKS-off, so a
* blank ends the operand), NOT part of the count.  Before the fix DCB rode the
* DC-family expression-continuation (`up.startswith('DC')`) and folded `+2` into
* the count, reserving 4 — so this object came out 2 bytes longer.  Guards the
* asm.py first_field `expr_cont` scoping (`and not up.startswith('DCB')`).
* The DC.W line confirms DATA continuation still folds across blanks (one word,
* $1235), so the fix narrows DCB without breaking DC.
t	PROC
	dcb.b	2 +2		; count is 2 (reserve 2 zero bytes); '+2' is a comment
	dc.w	$1234 + 1	; DC data folds across blanks -> one word $1235
	ENDP
	END
