* fixture: MVN/MVP block-move operands are ADDRESSES; each emitted bank byte is
* the operand's bank = `value >> 16`, matching MPW AsmIIGS — NOT the operand's
* low byte.  So `mvp $FF,$FF` assembles to `44 00 00` (bank of $FF is 0), the
* self-modified placeholder MIDI's midi.main direct-page image ships as `44 00
* 00`.  A full 24-bit operand still contributes its real bank byte, and the
* image order is opcode, bank(dest), bank(src).
*
* Before the fix the block-move bank lambda special-cased operands < $10000 to
* use the value directly, so `mvp $FF,$FF` wrongly baked `44 ff ff`.
t	PROC
	mvp	$FF,$FF			; -> 44 00 00 : bank($FF)=0 both banks
	mvn	$E10000,$E00000		; -> 54 e0 e1 : bank(dst)=$e0, bank(src)=$e1
	mvp	$012345,$0067FF		; -> 44 00 01 : bank(dst)=$00, bank(src)=$01
	ENDP
	END
