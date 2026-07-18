* fixture: a TOP-LEVEL equate that collides with a data-record field name is NOT
* module-local, so it updates the global normally — the data-record `keep_prior`
* masking is scoped to PROC-INTERIOR equates (StdFile devName).  asm.py
* define_label: keep_prior for kind=='equ' requires self.in_proc.  Adversarial-
* review Finding 2.  Without the fix the top-level `foo EQU $1234` is swallowed
* (recorded in labels but discarded from resolution) and `dc.w foo` relocates
* against the DataRec field (LEXPR sym83:DATAREC); with it, the literal $1234.
DataRec	RECORD	Export
foo	dc.w	0
	ENDR
foo	EQU	$1234
Use	PROC
	dc.w	foo
	ENDP
	END
