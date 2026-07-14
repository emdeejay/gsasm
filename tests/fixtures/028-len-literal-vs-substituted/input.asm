* fixture: &LEN counts a literal's CONTENT but a substituted arg's RAW text
* discovered: R8 (promoted from a work/rezloadcheck.py harness-local shim)
* &len('ab') on a literal quoted string written directly counts its CONTENT
* (2, quotes stripped). A macro parameter passed the same literal keeps its
* quotes through substitution, so &len(&s) inside the macro counts the RAW
* substituted text (4, quotes included) -- golden proof: Launcher.mac's wstr
* macro (`dc.w &len(&str)-2` yields the golden 2/6 for 'P8'/'PRODOS' only if
* &len(&str) counts the quotes too) versus Console.aii's
* `dcb.b 31-&len('CONSOLE'),' '` (pads to exactly 31 chars, needing
* &len('CONSOLE')==7, content-only).
		MACRO
		mlen	&s
		dc.b	&len(&s)
		MEND
LenTest	PROC
	dc.b	&len('ab')
	mlen	'ab'
	rts
	ENDP
	END
