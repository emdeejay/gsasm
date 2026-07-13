* fixture: CASE ON makes symbols case-sensitive
* discovered: ea4fb70
* Under CASE ON, Value and VALUE are DIFFERENT symbols.
	CASE	ON
Value	EQU	1
VALUE	EQU	2
CaseOn	PROC
	dc.b	Value
	dc.b	VALUE
	ENDP	CaseOn
	END
