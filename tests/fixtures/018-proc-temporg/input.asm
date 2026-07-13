* fixture: PROC TEMPORG: labels take the temporary origin; refs bake its addresses
* discovered: 025f204+c6a5112
* TEMPORG on the PROC line assembles the body at a temporary origin: label
* arithmetic uses $80-based addresses as absolute literals.
TmpOrg	PROC	TEMPORG $80
Tbl	dc.w	$1111
	dc.w	Tbl+2
	dc.w	Tbl
	ENDP
	END
