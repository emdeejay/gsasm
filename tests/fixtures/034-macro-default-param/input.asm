* fixture: an MPW macro KEYWORD PARAMETER with a default value, `&param=default`.
* When the argument is omitted at the call site the declared default is
* substituted; when supplied it overrides.
*
* AppleShare's Data.aii `ftype` macro:  `&creator=$FFFFFFFF`.  Before the fix the
* `=$FFFFFFFF` was folded INTO the parameter name (`creator=$FFFFFFFF`), so the
* body's `&creator` bound to nothing (empty) and `dc.l &hfs,&creator` dropped its
* second long -- 4 bytes short per entry, cascading the whole file-types table.
	case	on
	longa	on
	macro
&lab	ftype	&type,&aux,&hfs,&creator=$FFFFFFFF
&lab	dc.w	&type,&aux
	dc.l	&hfs,&creator
	endm
t	proc
	ftype	$D7,$0000,'MIDI'		; creator defaults -> ffffffff
	ftype	$E0,$0005,'dImg','dCpy'		; creator supplied -> 'dCpy'
	rts
	endp
	end
