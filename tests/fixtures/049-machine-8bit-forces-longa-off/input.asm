* fixture: MACHINE selects the target CPU width.  The 8-bit parts (M6502,
* M65C02) have no 16-bit accumulator/index, so an immediate operand is always
* one byte — MACHINE must force LONGA/LONGI OFF.  Before the fix MACHINE was a
* no-op and gsasm kept its 16-bit (M65816) default, so `lda #$10` emitted the
* 3-byte `A9 10 00` instead of the 2-byte `A9 10`; every 8-bit immediate ran
* one byte long and shifted the whole segment (P8's QuitCode.aii / Ram.n).
*
* Each PROC below is its own segment so the widths are checked independently:
*   eight  MACHINE M65C02  -> A9 10        LDX #$20 = A2 20   (1-byte imm)
*   wide   MACHINE M65816  -> A9 10 00     LDX #$20 = A2 20 00 (2-byte imm)
*   back   M65816 then LONGA OFF still wins (Monitor.aii ordering): A9 10
eight	PROC
	MACHINE	M65C02
	lda	#$10		; 8-bit accumulator -> A9 10
	ldx	#$20		; 8-bit index       -> A2 20
	ENDP
wide	PROC
	MACHINE	M65816
	lda	#$10		; 16-bit default    -> A9 10 00
	ldx	#$20		; 16-bit default    -> A2 20 00
	ENDP
back	PROC
	MACHINE	M65816		; asserts 16-bit ...
	LONGA	OFF		; ... but an explicit OFF still wins
	LONGI	OFF
	lda	#$10		; A9 10
	ldx	#$20		; A2 20
	ENDP
	END
