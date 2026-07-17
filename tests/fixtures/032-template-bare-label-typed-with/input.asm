* fixture: a bare (storage-less) label field of a TEMPLATE record, referenced
* under a TYPED-IMPORT `WITH inst` (`Import inst:Type` then `WITH inst`), binds
* to inst+offset -- an ABSOLUTE external the linker resolves -- exactly like a
* DS-allocated field of the template.
*
* Before the fix only DS-allocated fields were registered as template fields, so
* the typed-import WITH bound only those; a bare-label field (e.g. AppleShare
* `partial_len`, an unsized alias of the following field) fell back to the raw
* direct-page template offset -- `lda partial_len` -> a5 04 -- instead of the
* golden absolute `ad 04 00` = mydata+4.  The fix registers positional template
* labels (DS OR bare) as fields; an interior EQU *constant* (kind != 'label') is
* NOT a field and must stay a constant (`lda #flag_bit` -> a9 00 80).
*
* Complement of fixture 031 (a bare field under a PLAIN `WITH dp` stays
* direct-page): the difference is the TYPED IMPORT, which makes the instance
* absolute.
	longa	on
	longi	on
tdata	RECORD	0
fst_active	ds.w	1		; $00 -- DS field
my_span		ds.w	1		; $02 -- DS field
partial_len				; $04 -- bare alias, no storage
newline_mask	ds.w	1		; $04 -- DS field
flag_bit	equ	$8000		; interior EQU constant -- NOT a field
	ENDR
t	PROC
	import	mydata:tdata
	with	mydata
	lda	my_span			; ad 02 00  (DS field   -> mydata+2, absolute external)
	lda	partial_len		; ad 04 00  (bare field  -> mydata+4; was a5 04)
	lda	newline_mask		; ad 04 00  (DS field   -> mydata+4)
	lda	#flag_bit		; a9 00 80  (constant, NOT mydata+$8000)
	rts
	ENDP
	END
