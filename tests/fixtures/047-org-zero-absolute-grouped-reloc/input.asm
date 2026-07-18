* fixture: a multi-term reloc expression whose target labels live in an explicit
* `ORG 0` (zero-origin ABSOLUTE) segment must resolve as an ABSOLUTE LITERAL — it
* must NOT pick up the segment's link placement base.  omf._reloc_target_key used
* a truthiness test (`not (seg.org or seg.temporg)`) that classified `ORG 0` as
* relocatable because 0 is falsy; fixed to `seg.org is None and seg.temporg is
* None`, matching needs_reloc/_equ_alias_of.  Adversarial-review Finding 1.
* Without the fix `lda #target+here2-here` emits a relocation (LEXPR sym83:TARGET)
* and links to the placement base; with it, the absolute literal a9 01 00
* (target=0, here=1, here2=2 -> 0+2-1 = 1).
	longa	on
	longi	on
USER	PROC
	lda	#target+here2-here
	rts
	ENDP
ABS	PROC	ORG 0
target	dc.b	0
here	dc.b	0
here2	dc.b	0
	ENDP
	END
