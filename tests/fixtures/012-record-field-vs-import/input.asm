* fixture: template-RECORD bare field name yields to a declared IMPORT
* discovered: 1ab6e2a
* `beta` is both a field of a RECORD TEMPLATE (never instantiated) and a
* declared IMPORT.  A bare reference resolves to the IMPORT (external),
* not the template field offset.
Tmpl	RECORD	0
alpha	ds.w	1
beta	ds.w	1
	ENDR
FieldImp	PROC
	IMPORT	beta
	lda	beta
	ENDP
	END
