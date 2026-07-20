* fixture: a PROC-local equate in ANOTHER segment is module-local (MPW) —
* it must not direct-page-size a forward reference to the current PROC's
* own later code label of the same name.
* discovered: Finder verify.aii GetVerifyInfo `sLen1 equ 9` vs
* GetValidInfo's trailing `sLen1 dc.w 0` (gold 8d ef 0f, was 85 e7).
First	PROC
tmp	equ	9
	lda	#tmp
	rts
	ENDP
Second	PROC
	lda	#2
	sta	tmp
	rts
tmp	dc.w	0
	ENDP
	END
