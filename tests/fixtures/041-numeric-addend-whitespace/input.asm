* fixture: a memory-operand instruction folds a PURE NUMERIC addend across
* whitespace (MPW BLANKS ON, the preset), but a prose comment (no ';') still
* terminates the operand.
* GS.OS Device.Dispatcher `lda |temp_load_addr +2` reads the SECOND word of a
* SIB pointer -> temp_load_addr+2, not temp_load_addr.  The tail must be entirely
* `[+-] <number>` terms; a tail with any word (`-more.`, `* text`) is a comment.
base	equ	$1000
chk	PROC
	lda	base +2			; numeric addend -> lda base+2 ($1002)
	lda	base -more.		; prose comment -> lda base ($1000)
	rtl
	ENDP
	END
