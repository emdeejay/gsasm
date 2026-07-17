* fixture: cross-segment label difference where ONE side is ORG'd (absolute)
* and the other is relocatable -> emit the link-time diff EXPRESSION, not a
* baked literal.
*
* This is the GS/OS Init-manager header idiom `DC.W init_N_end-init_N_start`:
*   my_start  is an ORG'd pad PROC (absolute address, final at assembly)
*   my_end    is a relocatable end-bracket PROC that FOLLOWS a data segment,
*             so its assembly-time value is 0-based (the data RECORD reset the
*             location counter) and a baked `my_end-my_start` literal is WRONG.
* Only the LINKER, after placing my_end's segment, knows the true segment
* length.  _diff_reloc must therefore emit the expression whenever the two
* segments are not BOTH ORG'd (a mixed absolute/relocatable pair is not final).
* Regression guard for the omf._diff_reloc org-guard fix (`or` -> `and`).
Hdr	PROC	org $B1D0
	Import	my_start,my_end
	DC.W	my_end-my_start
	ENDP
my_start	PROC	org $B200
	ENDP
Payload	Record	Export
	DC.L	0
	EndR
my_end	PROC
	ENDP
	END
