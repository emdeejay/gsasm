* fixture: a @-local label passed as a macro LABEL parameter and THREADED
* THROUGH a nested macro must retain the scope of the ORIGINAL (outermost) call
* site, not re-key under the enclosing macro's private expansion context.
*
* QDAux/seedfill.asm DownLine does exactly this: `@NoCarry1 MoveLong ...`, and
* MoveLong's body forwards its label param into the nested `moveword` macro
* (`&lab moveword ...`).  The @-label is defined via that inner expansion, whose
* local_ctx is MoveLong's own 'M<uid>' context.  Before the fix the definition
* keyed under 'M<uid>@NoCarry1' while the caller's own `bcc @NoCarry1` keyed
* under 'DownLine@NoCarry1' and could not reach it — so the backward branch
* resolved to the WRONG @-label instance and baked the wrong displacement
* (seedfill.asm off 0xae3: gsasm 0x1c vs gold 0x02).
*
* Here Outer forwards its &lab param into Inner exactly as MoveLong forwards into
* moveword.  The `bcc @skip` in the main body must reach the @skip defined by the
* nested Inner expansion (displacement = 1, skipping the single `nop`).  Without
* the scope-inheritance fix the branch cannot find @skip in its own scope and
* mis-resolves.
        MACRO
&lab    Inner
&lab    nop                     ; @-label param lands HERE, one byte
        MEND

        MACRO
&lab    Outer
&lab    Inner                   ; forward &lab into the nested macro (M<uid> ctx)
        MEND

t       PROC
down    clc
        bcc     @skip           ; must branch to @skip (skip the one nop) = +1
        nop
@skip   Outer                   ; defines @skip via Outer -> Inner (nested)
        rts
        ENDP
        END
