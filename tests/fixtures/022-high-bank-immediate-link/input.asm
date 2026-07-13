* fixture: #^Label defers a >>16 shift to a load-time relocation; link resolves it
* discovered: 8cc1a55+700dad5
* The bank byte of a relocatable label is not known until load: #^Buf must
* emit a shift expression the linker evaluates, not a baked 0.
HighShift	PROC
	lda	#^Buf
	lda	#Buf
	rts
Buf	ds.b	4
	ENDP
	END
