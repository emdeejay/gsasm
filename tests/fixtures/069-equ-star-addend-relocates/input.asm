* fixture: `name EQU *+<const>` inside a relocatable PROC is a code LABEL (the
* current location plus a constant), NOT an absolute equate. References to it
* must relocate (SEGNAME+offset) so a cross-object use gets the target object's
* placed base added by the linker — gsasm previously only treated a bare `EQU *`
* as a label, so `EQU *+0` (StyleWriter patchprocs.a PuPiSrcLookupMask) stayed an
* object-local absolute constant and a small value emitted a DP operand with no
* reloc. Here `lda Lstar` must be an ABSOLUTE operand (AD ..) carrying a
* relocation, exactly like `lda Lreal`, not a DP operand (A5 ..).
Code	PROC
	EXPORT	Code
	nop
	nop
Lreal	dc.w	$1234
Lstar	equ	*+0
	lda	Lreal
	lda	Lstar
	rts
	ENDP
	END
