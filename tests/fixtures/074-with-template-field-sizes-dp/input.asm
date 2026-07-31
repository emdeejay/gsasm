* fixture: under an active WITH, a TEMPLATE-record field takes resolve()'s
* precedence over a SAME-NAMED global label for operand sizing and relocation:
* `sta bufptr` is STA dp $08 (2 bytes, no reloc), even though a real label
* `bufptr` exists in another (data) segment. discovered: NetBoot Stub.aii
* `with dp` — gold ProDOS16 Image stub is 830 bytes with dp-sized field refs;
* gsasm emitted 3-byte absolutes relocated to the ListSessions data segment
* (838 bytes, every address +8).
dp	record	0
nameptr	ds.l	1
bufptr	ds.l	1
	endr
Work	PROC
	EXPORT	Work
	with	dp
	sta	bufptr		; STA dp $04 (2 bytes), NOT abs -> Data's bufptr
	rts
	endwith
	ENDP
Data	record
filler	ds.w	1
bufptr	ds.l	1		; a real data-segment label of the same name
	endr
	END
