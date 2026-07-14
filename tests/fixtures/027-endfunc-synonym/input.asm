* fixture: ENDFUNC is a synonym for ENDF (closes a FUNC block)
* discovered: R8 (promoted from a work/rezloadcheck.py harness-local shim)
* MPW AsmIIgs's FUNC/ENDF construct (a PROC/ENDP-like OMF segment closer for
* function blocks) also accepts ENDFUNC as a spelling of ENDF; golden proof:
* FrameControl.aii:442 closes a FUNC with ENDFUNC.
EndFuncSyn	FUNC
	nop
	ENDFUNC
	END
