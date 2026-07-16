* fixture: a storage-less (bare) label inside a TEMPLATE record is a constant
* field OFFSET, not a relocatable code label -- so a memory operand referencing
* it sizes DIRECT-PAGE when the offset < $100 (opcode 86, two bytes), exactly
* like its DS/EQU sibling.  Before the fix the bare alias was typed 'label'
* (relocatable), which forces ABSOLUTE (opcode 8E, three bytes) and over-sizes
* the instruction -- cascading every downstream address.
*
* Golden proof: AppleShare FST's `dp` record math_temp/quotient/divisor aliases;
* gold `stx math_temp` = 86 A8, not 8E A8 00.  Same class as the GS.OS kernel
* init-header case.  (A DATA record's positional labels stay 'label'/absolute:
* they address emitted bytes and relocate -- only TEMPLATE records are offsets.)
	longa	on
	longi	on
dp	RECORD	0
	org	$a0
src_ptr	ds.l	1		; $a0 -- DS field (equate) -> direct-page
math_temp			; $a4 -- bare alias, no storage
quotient			; $a4 -- second bare alias, same offset
fact1	ds.l	1		; $a4 -- DS field (equate)
	ENDR
t	PROC
	with	dp
	stx	src_ptr		; 86 a0  (DS field, already DP)
	stx	math_temp	; 86 a4  (bare alias -- was 8e a4 00 before the fix)
	stx	quotient	; 86 a4  (bare alias)
	stx	fact1		; 86 a4  (DS field, DP)
	rts
	ENDP
	END
