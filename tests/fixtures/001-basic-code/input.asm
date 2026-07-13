* fixture: smoke test: instructions, data, one PROC segment
* discovered: -
* Baseline smoke test: absolute/immediate addressing, a data tail, RTS.
Smoke	PROC
	EXPORT	Smoke
	lda	#$1234
	sta	$2000
	ldx	#Tail
	rts
Tail	dc.w	$BEEF
	dc.b	$42
	ENDP
	END
