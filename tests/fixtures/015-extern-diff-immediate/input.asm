* fixture: difference of two externals in an immediate -> by-name difference expression
* discovered: fbced28
* #ExtHi+2-ExtLo is unknown at assembly but is a link-time constant: emit
* the RPN by-name expression (ExtHi ExtLo SUB +2), never a baked 0.
ExtDiff	PROC
	IMPORT	ExtHi,ExtLo
	lda	#ExtHi+2-ExtLo
	ENDP
	END
