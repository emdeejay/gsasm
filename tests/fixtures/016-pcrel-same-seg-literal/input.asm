* fixture: same-segment `label-*` is a computed literal, not a relocation
* discovered: 650a698
* Distances between points in ONE segment are position-independent: emit
* the literal difference, no reloc record.
PcRel	PROC
	nop
Here	dc.w	Here-*
	dc.w	After-*
	dc.w	After-Here
After	nop
	ENDP
	END
