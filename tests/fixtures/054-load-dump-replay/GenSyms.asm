* Dump-generating source (the fixture's stand-in for TextEdit's GenerateDump /
* AppleShare's Equates.aii).  Assembled only via LOAD replay: state as of the
* DUMP line — the equate, record, and macro — is restored; everything AFTER
* the DUMP (PostDump equate, the END) must NOT be processed.
BaseVal	equ	$1100

MyRec	RECORD	0
first	ds.w	1
second	ds.w	1
	ENDR

	MACRO
	EmitPair	&val
	dc.w	&val
	dc.w	&val+1
	ENDM

	DUMP	':obj:syms.dump'

PostDump	equ	$DEAD
	END
