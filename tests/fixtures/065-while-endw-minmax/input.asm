* fixture: WHILE..ENDW (short loop terminator) + &max/&min integer builtins.
* discovered: Tool029 (ACE) ace.asm decode tables. AsmIIgs accepts `ENDW` as a
* synonym for `ENDWHILE`; gsasm knew only the long spelling, so every ACE WHILE
* loop fell through and its DC.W table collapsed to a single row. And the
* &max(a,b)/&min(a,b) integer clamp builtins (used in NewIPoint*Table) were
* unimplemented -> `()<<4` folded to 0, zeroing whole tables. This exercises
* both in one macro-time loop: 4 rows must emit, each with clamped columns.
	MACRO
&lab	Rows
	LCLA	&i
&lab
&i	SETA	0
	WHILE	&i<=3 DO
	DC.W	(&max(&i-1,0))<<4, (&min(&i+2,3))<<4
&i	SETA	&i+1
	ENDW
	MEND
Tbl	PROC
	EXPORT	Tbl
	Rows			; must expand to 4 rows (8 words / 16 bytes), not 1
	ENDP
	END
