* fixture: '/' is a LEGAL character in an HFS filename — MPW's path separator is
* ':', never '/'.  A source whose name contains '/' extracts to disk with the
* '/' rewritten to '_'.  gsasm's _find_ci splits an include spec on '/' and so
* never finds the '_' file; do_include then only APPENDS to a.errors and keeps
* going, SILENTLY dropping the included code.  This was the SCSIHD.Driver residual
* (`INCLUDE 'SCSI Get Vol/Disk'`, on disk as `SCSI Get Vol_Disk` — ~1850 bytes of
* Get/Set-Volume-Parms code vanished, reached only under the direct_acc device
* type, so only SCSIHD diverged while the three sibling SCSI drivers stayed exact).
* resolve_include now retries the spec with '/'->'_' PER path component (real
* ':'-derived separators preserved), so the include resolves and its bytes appear
* in the object.  Without the fix this fixture fails to build (the unresolved
* include leaves a.errors non-empty -> run_fixtures raises).  The included file
* here is named `Get Vol_Disk`; the source references it as 'Get Vol/Disk'.
t	PROC
	dc.b	$11
	INCLUDE	'Get Vol/Disk'
	dc.b	$22
	ENDP
	END
