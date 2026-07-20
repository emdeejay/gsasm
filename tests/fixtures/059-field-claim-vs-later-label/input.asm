* fixture: a template-record field's courtesy claim of a bare name must not
* direct-page-size a forward reference to a LATER same-file code label.
* discovered: Finder verify.aii DoRead `sta bytes` vs GSOS.equ recFileInfo's
* `bytes DS.L 1` field (gold 8d xx xx absolute, was 85 xx direct-page).
* The record claims BARE `count` (offset 2, < $100); Use's `sta count`
* references the PROC's own trailing `count dc.w 0` — a relocatable label —
* and must size 16-bit absolute in every pass.
Rec	RECORD	0
first	DS.W	1
count	DS.L	1
	ENDR
Use	PROC
	lda	#1
	sta	count
	rts
count	dc.w	0
	ENDP
	END
