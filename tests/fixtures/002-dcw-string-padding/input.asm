* fixture: width>1 DC string = bytes padded to element width
* discovered: 5f4a8c9
* A quoted string under a width>1 DC is emitted as its BYTES, zero-padded
* up to a multiple of the element width -- NOT one character per element.
* dc.w 'ABC' -> 41 42 43 00 (not 41 00 42 00 43 00); dc.l 'AB' -> 41 42 00 00.
Pad	PROC
	dc.w	'ABC'
	dc.l	'AB'
	dc.w	'A'
	dc.b	'AB'
	ENDP
	END
