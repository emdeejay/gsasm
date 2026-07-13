* fixture: doubled quote inside a string literal collapses ('won''t' -> won't)
* discovered: c336b13
Quote	PROC
	dc.b	'won''t'
	dc.b	''''
	ENDP
	END
