* fixture: a plain module-local label must NOT clobber a same-named ENTRY.
* MPW: a label inside a code module is local to that module unless it is an
* ENTRY/EXPORT.  An ENTRY names a single global entry point; a same-named plain
* label in another module is that module's own local.  So a cross-module
* reference from a segment WITHOUT its own copy must resolve to the ENTRY, while
* a reference inside a module that has a local copy binds to the local.
* GS.OS SCM: `entry more` (copy_ext_string) vs plain `more` copy loops in
* get_prefix/get_name/end_session/swapout; `allocvcr`'s `jsr more` must reach
* the ENTRY ($B70A), not the last plain redefinition ($F99B).
* Restricted to ENTRY (EXPORT keeps last-wins: AppleDisk3.5 `export DATAMARKS`).
theloop	PROC
	entry	loop
loop	dey			; the ENTRY copy loop
	bne	loop		; local ref -> this loop
	rtl
	ENDP
other	PROC
loop	nop			; module-local reuse — must NOT become the global
	bra	loop		; -> OTHER's own loop, not the entry
	rtl
	ENDP
caller	PROC
	jsr	loop		; no local loop -> must reach the ENTRY (THELOOP)
	rtl
	ENDP
	END
