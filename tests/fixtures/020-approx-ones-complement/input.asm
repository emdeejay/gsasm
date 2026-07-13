* fixture: 'е' (MacRoman $C5) is the MPW one's-complement operator
* discovered: b4bb889
* dc.b ~1 -> $FE, dc.w ~$F0 -> $FF0F, double-complement is identity.
* (Sources are MacRoman: the operator is byte $C5.)
Approx	PROC
	dc.b	е1
	dc.w	е$F0
	dc.b	ее5
	ENDP
	END
