* fixture: nested RECORD templates qualify fields to arbitrary depth
* discovered: R8 (nested-record bug fixed; work/rezloadcheck.py's harness
* shim that pre-seeded the composite defines was retired in favor of this)
* `Ctl RECORD` containing `Rect ds Rectangle` must define the DOUBLY
* qualified field `Ctl.Rect.y2` = Ctl.Rect (this record's own field offset)
* + Rectangle.y2 (the nested template's field offset) -- not just the
* one-level `Rect.y2`, and as a plain offset EQUATE (no spurious
* relocation), since it is a record-relative constant, not a code address.
* Golden proof: IconButton.aii's Ctl/Rect templates, referenced as
* `ldy #Ctl.rect.y2` at 14 sites.
Rectangle	RECORD	0
y1	ds.w	1
x1	ds.w	1
y2	ds.w	1
x2	ds.w	1
	ENDR
Ctl	RECORD	0
Next	ds.l	1
Owner	ds.l	1
Rect	ds	Rectangle
	ENDR
NestedRec	PROC
	ldy	#Ctl.Rect.y2
	rts
	ENDP
	END
