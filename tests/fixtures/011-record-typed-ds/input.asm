* fixture: RECORD template + typed DS instance: Label ds Rec -> Label.field
* discovered: d74139a
* `Buf ds MyRec` reserves sizeof(MyRec) and makes Buf.f2 resolve to the
* field offset within the instance.
MyRec	RECORD	0
f1	ds.w	1
f2	ds.l	1
f3	ds.b	4
	ENDR
TypedDS	PROC
Buf	ds	MyRec
	lda	Buf.f2
	ldx	#Buf.f3
	rts
	ENDP
	END
