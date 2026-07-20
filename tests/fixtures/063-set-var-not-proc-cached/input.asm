* fixture: a SET (redefinable) variable used inside a PROC must NOT be
* cached in the proc-local seg_equ shadow table — it is a mutable assembler
* counter whose running value lives in `symbols`, and module-scope code
* between one PROC's ENDP and the next PROC still shares that PROC's segment
* index, so a stale shadow would win in resolve() over the fresh value.
* discovered: Finder common.aii — `DummyPC` (all.macros DefineStack counter)
* used in COLORMENUDEF PROC (seg_equ=24) then reused at module scope for
* CardSetUp's ctlPtr/ctlColorPtr/cardPtr block, which baked 24 not 1/5/9.
First	PROC
count	set	10
	lda	#count		; 10, inside the proc
	rts
	ENDP
count	set	1		; module scope: reset the counter
val1	equ	count		; must be 1 (fresh), NOT the stale proc value 10
count	set	count+1
val2	equ	count		; must be 2
Second	PROC
	lda	#val1
	lda	#val2
	rts
	ENDP
	END
