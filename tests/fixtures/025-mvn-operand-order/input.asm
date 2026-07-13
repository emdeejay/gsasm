* fixture: MVN/MVP operands are written src,dest but encode dest,src
* discovered: -
* mvn $01,$02 encodes as 54 02 01: the DESTINATION bank byte precedes the
* source bank byte in the instruction stream.
BlockMv	PROC
	mvn	$01,$02
	mvp	$7E,$7F
	ENDP
	END
