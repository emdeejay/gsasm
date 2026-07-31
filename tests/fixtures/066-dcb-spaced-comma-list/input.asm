* fixture: a DC.B comma-list written with SPACED commas ` , ` continues across
* the whitespace (it is a list separator, not a comment boundary). discovered:
* ImageWriter/ImageWriter.LQ imager.aii intl_tbl — 32 rows each written
* `dc.b $5B,50 , $5D,50 , $43,00 , $45,00`; gsasm kept only the first word of
* each row (2 of 8 bytes), dropping 32 x 6 = 192 bytes. Gated to expr_cont so an
* instruction's unmarked comment starting with a comma is untouched.
Tbl	PROC
	EXPORT	Tbl
	dc.b	$5B,50 , $5D,50 , $43,00 , $45,00
	ENDP
	END
