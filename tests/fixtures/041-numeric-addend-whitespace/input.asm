* fixture: a memory-operand instruction folds a PURE NUMERIC addend across
* whitespace (MPW BLANKS ON, the preset).  The continuation is SCOPED:
*   - memory operands fold (`lda base +2` -> base+2), incl. multi-term `+4 -2`;
*   - a prose comment without ';' still terminates the operand;
*   - BRANCHES never fold (a relative target's unmarked comment may be `+n`);
*   - COUNT directives (DS/DCB) never fold (`ds.b 2 +2` reserves 2, not 4).
* GS.OS Device.Dispatcher `lda |temp_load_addr +2` reads the second SIB word.
base	equ	$1000
chk	PROC
	lda	base +2			; memory operand -> lda base+2 ($1002)
	lda	base +4 -2		; multi-term numeric (BLANKS ON) -> base+2
	lda	base -more.		; prose comment -> lda base ($1000)
	bne	skip +2			; BRANCH: NOT folded -> bne skip ($5c is comment)
skip	rtl
	ENDP
buf	PROC
	ds.b	2 +2			; COUNT directive: NOT folded -> reserves 2 bytes
	ENDP
	END
