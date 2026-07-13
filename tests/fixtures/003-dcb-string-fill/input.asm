* fixture: DCB with a quoted-string fill replicates the string bytes
* discovered: 9556041
* DCB count,'str' fills count elements by REPLICATING the string bytes,
* not by repeating a single numeric value.
Fill	PROC
	dcb.b	6,'AB'
	dcb.b	3,'X'
	ENDP
	END
