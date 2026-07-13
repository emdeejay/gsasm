* fixture: default CASE OFF: symbol lookup is case-insensitive
* discovered: -
* Without CASE ON, MixedName / MIXEDNAME / mixedname are the same symbol.
MixedName	EQU	$77
CaseOff	PROC
	dc.b	MIXEDNAME
	dc.b	mixedname
	ENDP
	END
