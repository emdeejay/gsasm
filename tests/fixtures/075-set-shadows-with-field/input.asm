* fixture: a SET variable defined in the CURRENT segment shadows a WITH field
* of the same name — its live running value (in symbols) binds, not the field
* offset. discovered: VideoKeyboard Key.a R2Completion `rtlAddr SET dirPage+2`
* then `dataPtr SET rtlAddr+3` under a persisting `WITH StackFrame` whose
* template also has an rtlAddr field ($22): the RHS must bind the local SET
* ($4), so dataPtr=$07, not $25.
SF	record	1
pad	ds.w	16
rtlAddr	ds.w	1		; template field at offset $21
	endr
Work	PROC
	EXPORT	Work
	with	SF
dirPage	SET	2
rtlAddr	SET	dirPage+2	; local SET = 4 (shadows SF.rtlAddr $21)
dataPtr	SET	rtlAddr+3	; must be 7, NOT $24
	lda	#dataPtr
	rts
	endwith
	ENDP
	END
