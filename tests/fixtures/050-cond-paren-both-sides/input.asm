* fixture: a conditional-assembly relation with a parenthesised term on EACH
* side — `IF (A) < (B) THEN` — must NOT be mistaken for a fully-parenthesised
* expression.  The whole string opens with '(' and ends with ')', but those are
* DIFFERENT parens; the old `t[0]=='(' and t[-1]==')'` test stripped them,
* leaving the malformed `A) < (B` which mis-evaluated (P8 MliSrc's
* `IF (*-procstart) < ($E000-Proc3_Org) THEN` wrongly took the true branch, ran
* a `ds.b` with a negative count, and corrupted the whole PROCTHREE layout).
* _outer_parens_wrap now confirms the leading '(' matches the trailing ')'.
*
*   false PROC: IF (3) < (2)  -> FALSE  -> ds.b 4 skipped -> dc.b $AA at off 0
*   true  PROC: IF (1) < (2)  -> TRUE   -> ds.b 2 taken   -> dc.b $BB at off 2
false	PROC
	if	(1+2) < (1+1) then	; (3) < (2) = false
	ds.b	4
	endif
	dc.b	$AA			; no pad -> offset 0
	ENDP
true	PROC
	if	(1) < (1+1) then	; (1) < (2) = true
	ds.b	2
	endif
	dc.b	$BB			; padded -> offset 2
	ENDP
	END
