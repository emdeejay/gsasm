* fixture: &sysdate/&systime builtins honor injected values for reproducible builds
* discovered: 851f69c
Stamp	PROC
	dc.b	'&sysdate'
	dc.b	'&systime'
	ENDP
	END
