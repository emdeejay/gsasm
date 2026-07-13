* fixture: SEG loadname persists until the next SEG
* discovered: 48b7cef
* One SEG covers every following PROC until the next SEG: both P1 and P2
* carry LOADNAME 'LoadA', P3 switches to 'LoadB'.
	SEG	'LoadA'
P1	PROC
	nop
	ENDP
P2	PROC
	nop
	ENDP
	SEG	'LoadB'
P3	PROC
	nop
	ENDP
	END
