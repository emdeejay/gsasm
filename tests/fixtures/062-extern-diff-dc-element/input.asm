* fixture: a DC element that is the DIFFERENCE of two EXTERNALS (both pure
* declared IMPORTs) is a link-time constant emitted by name, not baked to
* the unresolved sentinel.
* discovered: Finder alert.aii `dc.L endTextAlertStr-textAlertStr` (a GS/OS
* WriteGS request's byte count; golden $126, was $FFFFFFFF).
Tbl	PROC
	IMPORT	blkStart
	IMPORT	blkEnd
	dc.l	blkStart
	dc.l	blkEnd-blkStart
	dc.l	0
	ENDP
	END
