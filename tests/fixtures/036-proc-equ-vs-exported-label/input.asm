* fixture: a proc-local EQU must not clobber a same-named EXPORTed label.
*
* MPW Asm Ref: "labels defined inside a code module are local to that module"
* unless declared EXPORT/ENTRY.  So a proc-interior `shared equ ...` is
* module-local and cannot be the global binding for a name that ANOTHER
* segment references by name.
*
* This is the GS/OS bank0.dispatcher `a_reg` idiom:
*   `shared` is an EXPORTed `ds.b` in the `vars` segment (the real address);
*   the `user` segment references it `>shared` (must relocate to vars+offset);
*   the `local` segment has its OWN `shared equ 4` (module-local scratch).
* The equate must land in seg_equ (local to `local`), NOT overwrite the export
* in the global symbol table — otherwise `user`'s `>shared` bakes the equate
* value ($0004) instead of relocating to the exported label.
* Regression guard for the asm.py define_label proc-EQU-vs-export scoping fix.
vars	PROC
	export	shared
shared	ds.b	1
	ENDP
user	PROC
	lda	>shared		; -> relocates to VARS+offset (the export)
	ENDP
local	PROC
shared	equ	4		; module-local; must not clobber the export
	lda	shared		; -> literal $0004 (the local equate)
	ENDP
	END
