* fixture: MPW grouped EXPORT/IMPORT syntax `(a,b,c):type` expands to individual
* symbols each carrying the shared :type (Start/StartLog
* `export (InitParm,FrameParms1,MainWindow):code`). Previously the whole paren
* group was stored as one bogus symbol, so the members were never exported and
* references linked as 0. Here A and B must each become real EXPORTed labels.
	EXPORT	(A,B):code
A	dc.w	$1111
B	dc.w	$2222
	END
