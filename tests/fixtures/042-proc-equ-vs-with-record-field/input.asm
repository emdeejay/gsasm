* fixture: a PROC-interior EQU must not clobber a same-named DATA-RECORD field,
* and a stale (still-active) WITH must not shadow that local EQU.
*
* StdFile's custompopup.aii defines a `PopUpGlobals Record` whose field `DevName`
* is a relocatable data-segment label; a later `GetThePrefix` PROC defines its
* own `devName equ ParBlock+02` while a `with PopUpGlobals` from an earlier PROC
* is still active (these sources never ENDWITH -- WITH is re-issued per PROC).
* Two bugs collided here:
*   (1) the proc-local EQU overwrote the GLOBAL DevName symbol (label->equ), so a
*       `ldx #DevName` in the popup code stopped relocating -- it baked the field
*       OFFSET ($36) instead of POPUPGLOBALS+$36; and
*   (2) resolve() consulted the WITH field namespace BEFORE the proc-local EQU, so
*       `sta DevName` in GetThePrefix used the field offset ($36) instead of the
*       local equate ($b8).
* Guards both fixes together.
	longa	on
	longi	on
Globals	RECORD
DevNum	ds.w	1		; +0
DevName	ds.b	4		; +2  <- data-record field: relocatable label
	ENDR
reader	PROC
	with	Globals
	ldx	#DevName	; a2 02 00 + reloc Globals+2 (field ADDRESS, relocatable)
	ENDP
* deliberately NO endwith -- `with Globals` stays active into the next PROC
user	PROC
DevName	equ	$b8		; module-local equate; must NOT clobber the field
	lda	DevName		; a5 b8 (absolute local equate, NOT the field offset)
	ENDP
	END
