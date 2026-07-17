* fixture: a character constant in an expression evaluates to the source BYTE
* (Mac Roman), not the Unicode code point.
* gsasm reads sources as Mac Roman.  A high character such as the curly quote
* Ò is stored in the source as the single Mac Roman byte $D2; decoded to a
* Python string it becomes U+201C, so a naive ord() would yield $201C.  The
* assembler must use the byte: `pea Ò` pushes $00D2 (GS.OS Init2 static
* text), and `lda #'A'` stays $41 (ASCII is identity).  THIS FILE IS MAC ROMAN.
chk	PROC
	pea	'Ò'		; U+201C -> Mac Roman byte $D2
	pea	'Ó'		; U+201D -> Mac Roman byte $D3
	lda	#'A'		; ASCII identity -> $41
	ENDP
	END
