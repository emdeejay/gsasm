* fixture: size-prefixed operand with parenthesized expression keeps its tail
* discovered: E3 Tool034 (fastdraw.aii CallMemoryCode return-address trick)
* After an explicit size prefix (| ! < >) the operand is direct by definition,
* so `(` is arithmetic grouping, NOT indirection: `pea |(Target-1)>>8` must
* carry the >>8 into the OMF expression (a shift reloc at link time), not
* truncate at the close paren.  The immediate <<8 pair is the left-shift
* sibling (stored un-shifted under a deferred shift reloc — see
* tests/test_linkiigs_defer_left_shift.py).
Trick	PROC
	pea	|(Target-1)>>8
	lda	#(Target-1)<<8
	ora	$1234
Target	anop
	rts
	ENDP
	END
