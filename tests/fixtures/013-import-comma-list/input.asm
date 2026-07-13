* fixture: IMPORT splits comma-separated names on one line
* discovered: 63fc266
Imps	PROC
	IMPORT	ExtOne,ExtTwo,ExtThree
	dc.w	ExtOne
	dc.w	ExtTwo
	dc.w	ExtThree
	ENDP
	END
