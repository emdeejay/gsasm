* fixture: DC/EQU operand expressions continue across whitespace around +/-
* discovered: ce71e12
* An operand expression keeps going past whitespace around +/-: the field
* does not end at the first blank.
base	EQU	$10
sum	EQU	base + 5
Wsp	PROC
	dc.w	base + 3
	lda	#sum
	ENDP
	END
