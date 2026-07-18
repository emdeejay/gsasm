* fixture: a WITH-instance record field used in a MULTI-TERM arithmetic operand
* (`inst_field - template_offset`) must still relocate against the INSTANCE
* (import + net addend), not collapse to a baked direct-page template offset.
*
* A `WITH inst` over a TYPED IMPORT (`Import inst:Type`) binds each bare field to
* inst+offset via an equ-kind alias (fixture 032, single bare field -> absolute
* external `ad off off`).  But when the field appears inside an EXPRESSION the
* alias is equ-kind, so the old linear-reloc classifier folded it into the
* constant and LOST the relocation -- the operand baked the assembly-time value
* (direct-page template offset) with no reloc record.
*
* Golden proof: AppleShare send_option `lda my_f_info-tOpt.f_info,y` links to
* MYDATA+$60 (b9 b5 3e once MYDATA is placed at $3E55); gsasm baked b9 60 00.
* Here my_f_info is a template field at $62 of the imported instance `mydata`
* and tOpt.f_info is a pure template-offset constant ($04, tOpt is a plain
* offset RECORD, not WITH'd/imported), so the operand must emit ONE relocation
* against MYDATA with net addend $62-$04 = $5E -- an absolute (16-bit) operand
* with an OMF expression, NOT the bare literal $005E.
*
* Regression guard for omf._grouped_linear_reloc: an equ_alias'd WITH-instance
* field term collapses to a single +1 relocation, template-offset terms fold
* into the constant addend.  Complement of fixture 032 (single field).
	longa	on
	longi	on
tdata	RECORD	0
fst_active	ds.w	1		; $00 -- DS field
	ds.b	$60			; pad
my_f_info	ds.w	1		; $62 -- instance field (aliased by WITH mydata)
	ENDR
tOpt	RECORD	0
	ds.w	1			; $00
opt_size	ds.w	1		; $02
f_info	ds.w	1		; $04 -- template offset: a pure constant here
	ENDR
t	PROC
	import	mydata:tdata
	with	mydata
	lda	my_f_info-tOpt.f_info,y	; b9 + reloc MYDATA+$5E (was b9 5e 00 literal)
	rts
	ENDP
	END
