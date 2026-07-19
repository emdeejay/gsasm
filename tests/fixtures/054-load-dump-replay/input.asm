* fixture: MPW LOAD/DUMP — LOAD replays the registered dump-generating source
* discovered: E3 Tool034 (TextEdit GlobalIncludes `LOAD 'Include.Symbols'`;
*             AppleShare Equates.aii `dump ':obj:equates.dump'`)
* LOAD 'syms.dump' replays GenSyms.asm (fixture.json "loads" maps the dump
* name to it, mirroring the makefile rule) and stops AT its DUMP line: the
* equate/record/macro before the DUMP are restored; the PostDump equate and
* END after it must not be seen.  Leaf-name matching: the LOAD operand has no
* path, the DUMP operand is ':obj:'-prefixed.  PostDump defined here proves
* the replay didn't leak past the DUMP (a leak would collide/clobber).
	LOAD	'syms.dump'
PostDump	equ	$BEEF
LoadUse	PROC
	lda	#BaseVal
	ldx	#MyRec.second
	EmitPair	BaseVal
	dc.w	PostDump
	rts
	ENDP
	END
