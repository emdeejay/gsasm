* fixture: a REDEFINABLE (SET) definition does not clobber an existing STORAGE
* LABEL binding — the label stays the module-visible symbol; the SET is local
* to its defining segment (read there via setvar_seg/setvar_val).
* discovered: CloseView Core.aii — `v ds.W 1` (a dp cell, CloseView.equ) vs
* UpdateScreen2X's proc-scoped `v set h+2`; a LATER proc's `stz <v` binds the
* LABEL (gold $1B), not the stale SET value. Here: P1's `lda #v` reads its own
* SET (=7); P2's `dc.w v` binds the storage label's address (offset 2 in Vars).
Vars	PROC
	EXPORT	Vars
	ds.w	1
v	ds.w	1		; the storage label
	ENDP
P1	PROC
	EXPORT	P1
v	set	7		; segment-local SET, must NOT clobber the label
	lda	#v		; = 7 (this segment's SET)
	rts
	ENDP
P2	PROC
	EXPORT	P2
	dc.w	v		; the STORAGE LABEL (Vars+2), not 7
	ENDP
	END
