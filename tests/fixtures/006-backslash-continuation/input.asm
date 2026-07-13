* fixture: backslash line-continuation; token boundary preserved between fused words
* discovered: 74a65d6+7abce18
* A trailing backslash continues the logical line.  The continuation is a
* TOKEN BOUNDARY: words split across it must not fuse into one token.
Cont	PROC
	dc.b	1,2,\
		3,4
	dc.w	$1111 + \
		$0202
	ENDP
	END
