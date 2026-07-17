* fixture: `Name RECORD IMPORT` declares Name as an EXTERNAL data instance whose
* fields are laid out inline as offsets.  A `Name.field` reference is therefore
* the external Name+offset (ABSOLUTE, linker-resolved), NOT a direct-page
* template offset.
*
* AppleShare's SPWrite/SPCommand param blocks use exactly this: `record import`
* in Flush/Write (declaring the layout), `record export` in Data (defining the
* instance), and `import SPWrite:tSPWrite` elsewhere -- three spellings of the
* same external.  Before the fix gsasm treated `record import` as a base-0
* template, so `sta SPWrite.WrtBufLen` sized direct-page (85 0f) instead of the
* golden absolute (8d 0f 00 + a relocation against the imported SPWrite).
*
* Proof here: the field ref assembles 3-byte absolute (opcode 8d) and emits a
* relocation record against the import SPWrite (an unresolved external in this
* standalone object).
	case	on
	longa	on
	longi	on
SPWrite	record	import
	ds.w	1			; +0 sync/callnum
Result	ds.w	1			; +2 result code
	ds.l	1			; +4 completion
SRef	ds.b	1			; +8 session ref
ComLen	ds.w	1			; +9 command length
ComAddr	ds.l	1			; +$0b command address
WrtBufLen ds.w	1			; +$0f amount to write
	endr
t	proc
	sta	SPWrite.WrtBufLen	; 8d 0f 00, reloc SPWrite+$0f (was 85 0f, DP)
	rts
	endp
	end
