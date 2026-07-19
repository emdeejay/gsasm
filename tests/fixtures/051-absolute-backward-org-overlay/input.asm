* fixture: a backward mid-segment ORG that re-lays previously emitted bytes must
* work in an ORG'd (ABSOLUTE) segment, not just a relocatable one.  The MPW
* self-modifying idiom
*       jmp   0          ; a placeholder operand, patched at run time
*       org   *-2        ; step the location back over that operand
*   v   ds.b  2          ; name the 2 operand bytes; reserve reuses the space
* must add NO net bytes (v aliases the jmp operand).  In an ORG'd segment
* self.loc is origin-based while item offsets are 0-based, so the overlay logic
* translates through the segment origin before comparing to the emitted length.
* Before the fix `not cur.absolute` disabled the overlay here, so the `ds.b 2`
* APPENDED two bytes and shifted the rest of the segment (P8 MliSrc PROCONE/
* PROCTHREE `jmp/jsr 0 ; org *-2` self-modified vectors).
*
* Expected body: 4C 00 00 99  (jmp=3 bytes, ds.b 2 reuses operand, dc.b at off 3)
* Label v resolves to $1001 (the jmp operand, origin $1000 + 1).
t	PROC	ORG $1000
	jmp	0		; 4C 00 00
	org	*-2		; back to offset 1
v	ds.b	2		; aliases the jmp operand — no net bytes
	dc.b	$99		; lands at offset 3
	dc.w	v		; $1001, proves v aliases the operand
	ENDP
	END
