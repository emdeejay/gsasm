* fixture: TSA/TAS are 65816 alias mnemonics for TSC/TCS
* discovered: R8 (promoted from a work/rezloadcheck.py harness-local shim)
* MPW AsmIIgs accepts TSA/TAS as spellings of TSC/TCS (stack<->accumulator
* transfer); golden proof: Thermodial.aii:802,805 use TSA/TAS. Both spellings
* must encode identically to their canonical mnemonic.
TsaTas	PROC
	tsa
	tsc
	tas
	tcs
	rts
	ENDP
	END
