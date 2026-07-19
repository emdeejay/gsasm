* fixture: two &-substitution rules from the P8 drivers.
*
* (1) An undefined `&NAME` OUTSIDE any macro is left LITERAL — at top level a
*     bare `&name` can only be a SET/GBL variable, and MPW leaves an unknown
*     &-reference untouched rather than deleting it.  CClock.n's
*     `DC.B 'JIMJAYKERRY&MIKE'` keeps the literal `&MIKE`; before the fix gsasm
*     expanded the undefined MIKE to '' and dropped 5 bytes.
*
* (2) A `;`-comment is NOT &-substituted: Ram.n:101
*     `LDA <CMD,X ;CMD,UNIT,BUFPTR,&BLOCK(lo)` has `&BLOCK(lo)` inside the
*     comment, which must not be read as a builtin call (it raised "unknown
*     builtin &BLOCK") nor expanded.
*
* A DEFINED &-var still substitutes normally (proves the fix is scoped).
	GBLC	&who
&who	SETC	'BOB'
t	PROC
	dc.b	'A&MIKE'		; undefined &MIKE -> literal: 41 26 4D 49 4B 45
	dc.b	'&who'			; defined &who -> 'BOB': 42 4F 42
	lda	#0	;trailing &BLOCK(lo) in a comment must not raise/expand
	ENDP
	END
