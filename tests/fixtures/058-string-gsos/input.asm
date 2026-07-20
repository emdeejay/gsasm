* fixture: STRING GSOS = little-endian WORD length prefix on DC.B strings
* discovered: Finder Strings.aii `string GSOS` block (gold `06 00 'SYSTEM'`);
* PASCAL and ASIS modes unchanged around it.
Strs	PROC
	string	ASIS
	dc.b	'AB'
	string	GSOS
	dc.b	'SYSTEM'
	dc.b	'Icons'
	string	PASCAL
	dc.b	'CD'
	string	ASIS
	dc.b	'EF'
	ENDP
	END
