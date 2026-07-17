* fixture: an immediate that shifts a CROSS-segment relocatable label and adds a
* constant -> emit the link-time expression (SEGNAME * N + K), not a baked
* assembly-time literal.
* GS.OS SCM `lda #((common_int_ent<<8)+$5c)` packs the ENTRY's placed low byte as
* the high byte of a JML operand ($5C = JML opcode); the value is only known once
* the linker places common_int_ent.  A bare `label<<8` already relocated (the
* trailing-shift path), but `(label<<8)+const` fell through to a baked $5c.
* `tgt` is an ENTRY in another PROC, so its value is link-assigned.
target	PROC
	entry	tgt
tgt	nop
	rtl
	ENDP
user	PROC
	lda	#((tgt<<8)+$5c)		; -> SEGNAME(TARGET)*256 + $5c EXPR
	rtl
	ENDP
	END
