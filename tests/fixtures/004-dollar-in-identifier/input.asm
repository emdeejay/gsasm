* fixture: '$' is a valid identifier character mid-symbol
* discovered: 4c561f5
* '$' inside a symbol is part of the NAME, not a hex-literal prefix.
IO$Base	EQU	$C000
Off$2	EQU	2
DolIdent	PROC
	lda	IO$Base+Off$2
	lda	#IO$Base
	ENDP
	END
