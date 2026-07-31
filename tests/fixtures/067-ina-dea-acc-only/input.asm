* fixture: INA / DEA are accumulator-only spellings of INC A / DEC A. Any
* trailing text is an unmarked comment (there is no INA <addr> form). discovered:
* Epson driver epson.asm:10461 `ina<tab>skip 50% reduction` — gsasm parsed
* "skip" as a memory operand and emitted INC abs (EE ..), +2 bytes.
Code	PROC
	EXPORT	Code
	ina	skip 50% reduction	; must be $1A (INC A), not INC abs
	dea	whatever		; must be $3A (DEC A)
	ina				; bare acc form, already worked
	rts
	ENDP
	END
