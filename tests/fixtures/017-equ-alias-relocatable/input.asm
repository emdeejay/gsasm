* fixture: EQU aliasing a relocatable label relocates via its target
* discovered: c1526c4
* Alias EQU Real does not freeze an absolute value: references through the
* alias still relocate against the label it names.
EquAlias	PROC
	nop
Real	nop
Alias	EQU	Real
	dc.w	Alias
	lda	Alias
	ENDP
	END
