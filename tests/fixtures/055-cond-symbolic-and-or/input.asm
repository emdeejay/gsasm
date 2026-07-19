* fixture: MPW symbolic logical operators in conditionals: ** = AND, ++ = OR
* discovered: E3 Tool034 (TextEdit.macros addl: IF &C='' ** &B='' THEN — same
*             macro in StdFile/dave.macros and ControlMgr/special.macros)
* The addl-style macro picks the compact add-in-place form when BOTH optional
* args are empty; with `**` unsupported the ELSE branch mis-expanded with
* empty operands.  ++ (symbolic OR) is the pair operator, same level as OR.
	MACRO
	addl	&A,&B,&C
	IF &C='' ** &B='' THEN
	clc
	adc	&A
	sta	&A
	bcc	@1
	inc	&A+2
@1
	ELSE
	lda	&A
	clc
	adc	&B
	sta	&C
	ENDIF
	MEND
Var	equ	$40
Alt	equ	$50
Res	equ	$60
CondSym	PROC
	addl	Var
	addl	Var,Alt,Res
	IF 'x'='' ++ 1=1 THEN
	dc.b	$AA
	ENDIF
	IF 1=2 ++ 'y'='' THEN
	dc.b	$BB
	ENDIF
	rts
	ENDP
	END
