* fixture: import +/- constant -> by-name OMF expression, not a baked value
* discovered: 5f4a8c9
* A reference to an external plus a constant must reach the linker as a
* by-name expression; it cannot be resolved (or zero/ffff-baked) here.
ImpConst	PROC
	IMPORT	ExtSym
	dc.w	ExtSym+3
	dc.w	ExtSym-1
	ENDP
	END
