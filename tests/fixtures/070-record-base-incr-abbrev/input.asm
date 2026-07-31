* fixture: a template RECORD's base operand with the ABBREVIATED ,INCR modifier
* (VideoKeyboard Key.a `StackFrame RECORD 1,INCR`). Only the full words
* increment/decrement were stripped before, so the base `1` failed to evaluate
* and every field offset came out one low. With the base honored, the fields
* start at offset 1: a=1, b=3 (the buggy build gave a=0, b=2).
SF	RECORD	1,INCR
a	DS.W	1
b	DS.W	1
	ENDR
T	PROC
	EXPORT	T
	dc.w	a
	dc.w	b
	ENDP
	END
