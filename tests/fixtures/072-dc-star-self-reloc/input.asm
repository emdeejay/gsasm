* fixture: a bare `*` as a DC data element is the ADDRESS of this point — a
* coefficient-1 SELF-segment relocation, not an assembly-time literal.
* discovered: NetBoot Logon.Main `VolName DC.L *`; golden Apple //e Boot Blocks
* ships it relocated to the placed base (gold $835B = org $62E8 + $2073), gsasm
* baked the segment-relative literal. The emitted OMF must carry a SEGNAME
* expression for the element (the blessed .obj records it); an ORG'd segment
* keeps the literal.
Code	PROC
	EXPORT	Code
	nop
	nop
VolName	DC.L	*
	rts
	ENDP
	END
