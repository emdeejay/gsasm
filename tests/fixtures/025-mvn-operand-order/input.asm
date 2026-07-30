* fixture: MVN/MVP operands are written src,dest but encode dest,src
* discovered: -
* The operands are ADDRESSES; each emitted byte is the operand's BANK
* (`value >> 16`, MPW AsmIIGS — see fixture 064), and the DESTINATION bank
* precedes the SOURCE bank in the instruction stream.  `mvn $010000,$020000`
* encodes as 54 02 01 (dest bank $02, then src bank $01); `mvp $7E0000,$7F0000`
* encodes as 44 7f 7e.  Distinct banks keep the dest-before-src ORDER visible
* under the corrected `>>16` bank semantics (a small literal like $01 is bank 0,
* which would hide the order).
BlockMv	PROC
	mvn	$010000,$020000
	mvp	$7E0000,$7F0000
	ENDP
	END
