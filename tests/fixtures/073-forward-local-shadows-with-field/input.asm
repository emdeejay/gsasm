* fixture: a segment's OWN label shadows a WITH-instance field of the same bare
* name — including a FORWARD local (defined later in the segment), which the
* multi-pass seed makes visible to resolve()'s local_here gate, and at OMF emit
* where the instance field rides equ_alias. discovered: NetBoot Console
* SortArray references `Count` (its own trailing `Count ds.w 1`) while a
* `with ConsData` typed-DS instance is still active (MPW never pops WITH at
* ENDP); golden BootLog8 binds SORTARRAY's local, not ConsData.count.
* Here `lda Count / sta Count` must produce SEGNAME(WORK)+<local> relocations,
* not INST+2 — the blessed .obj records the expression targets.
Rec	RECORD	0
first	DS.W	1
Count	DS.W	1
	ENDR
	WITH	Inst
Work	PROC
	EXPORT	Work
	lda	Count		; forward local below, NOT Inst.Count (+2)
	sta	Count
	rts
Count	ds.w	1
	ENDP
Inst	PROC
	EXPORT	Inst
	ds	Rec
	ENDP
	END
