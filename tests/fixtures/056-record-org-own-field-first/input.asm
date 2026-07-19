* fixture: ORG <field> inside a RECORD binds the record's OWN field first
* discovered: E3 Tool034 (TextEdit GlobalVars TempStyle RECORD WorkArea with
*             `ORG fontID` while `with TEStyle` is active)
* TempStyle-style record: nonzero symbolic origin, mid-record ORG back to the
* first field to overlay an alternate layout.  Bare `fontID` in the ORG must
* resolve to Rec2.fontID (origin+0 = $dc), NOT the WITH-active Rec1.fontID
* (offset 0) — else every post-ORG field loses the origin.
Rec1	RECORD	0
fontID	ds.l	1
flags	ds.w	1
	ENDR
	WITH	Rec1
Base	equ	$DC
Rec2	RECORD	Base
fontID	ds.l	1
	ORG	fontID
fontFamily	ds.w	1
fontAttr	ds.b	1
fontSize	ds.b	1
foreColor	ds.w	1
	ENDR
OrgOwn	PROC
	lda	Rec2.fontFamily
	sta	Rec2.foreColor
	ldx	#Rec2.fontAttr
	ldy	#Rec1.flags
	rts
	ENDP
	ENDWITH
	END
