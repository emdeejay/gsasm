* fixture: the MPW "&lab NAME"/"&lab PROCNAME" routine-header idiom (a
* macro whose body re-emits its OWN call-site label as a bare label-only
* line -- the entire point of the convention is to define `&lab` as a
* real, @-scope-resetting global label, identically to writing it with no
* macro at all) must have that definition PERSIST as the enclosing
* @-label scope for code after the macro call returns.
*
* Before the fix, Asm.expand_macro() unconditionally restored last_global
* to its pre-call value when the macro body finished (protecting a macro's
* PRIVATE local_ctx @-label sandbox) -- but that same restore also
* discarded the @-scope-resetting effect of a NAME-declared routine label,
* since NAME defines `&lab` INSIDE the macro body (`macro.label_var` is
* not None, so dispatch() never calls define_label at the call site
* itself). Two NAME-declared routines in a row sharing an @-label name
* (`@done`) then collided into ONE bogus shared scope keyed off whatever
* REAL (non-macro) label preceded them both -- here, the enclosing PROC's
* own name, `DEMO`.
*
* Discovered: EasyMount.aii's `GetStandardFile name` / `KillStandardFile
* name`, both using `@done` (see docs/design/rez.md, work/easymountcheck.py).
* `Second`'s `beq @done` sits BYTE-CLOSER to `First`'s @done (the wrong,
* nearer-by-distance def under the pre-fix same-key collision) than to its
* OWN @done (the correct target, several instructions further on) --
* exactly mirroring EasyMount's KillStandardFile/GetStandardFile shape, so
* a wrong scope rule flips this branch's operand byte, not just its symbol
* bookkeeping.
	MACRO
&lab	NAME
&lab
	MEND

Demo	PROC
First	NAME
	lda	#1
	beq	@done
	lda	#2
@done	rts

Second	NAME
	lda	#3
	beq	@done
	nop
	nop
	nop
	nop
	nop
	nop
	nop
	nop
@done	rts
	ENDP
	END
