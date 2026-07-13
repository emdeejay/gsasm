* fixture: AND/OR in an IF with no relation are BITWISE, not logical
* discovered: 575be9e
* In IF/ELSEIF conditions with no relational operator, AND and OR are
* BITWISE: `4 AND 2` is 0 (false), not logical-true.
flags	EQU	4
Bitwise	PROC
	IF	flags AND 2 THEN
	dc.b	$AA
	ELSE
	dc.b	$BB
	ENDIF
	IF	flags AND 4 THEN
	dc.b	$CC
	ENDIF
	IF	flags OR 0 THEN
	dc.b	$DD
	ENDIF
	ENDP
	END
