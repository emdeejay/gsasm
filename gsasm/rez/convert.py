"""gsasm/rez/convert.py — M7/R6: the RezIIgs `read ... Convert` transformation.

RezIIgs's `sys.resources.r` embeds four code resources via `read` statements
(not `resource` bodies), e.g.:

    read rCtlDefProc(0x07FF0001, ...) "IconButton.Load"

Each carries the `Convert` attribute bit (0x0800) in the resource index
(golden Sys.Resources attr word 0x8800 = locked 0x8000 | Convert 0x0800 for
all four — see work/rezcheck.py and docs/design/rez.md).

## What Convert turns out to be: the identity

Established byte-exactly by work/rezloadcheck.py (packet R6): rebuilding each
.Load input from the archive sources with gsasm (assemble + LinkIIgs-`-x`
-style link) reproduces the golden embedded resource bytes verbatim, 4/4:

    rCtlDefProc   ($800C) 0x07FF0001  2649 B  IconButton.Load
    rCtlDefProc   ($800C) 0x07FF0002  1313 B  Thermodial.Load
    rCtlDefProc   ($800C) 0x07FF0003   633 B  FrameControl.Load
    rCodeResource ($8017) 0x07FF0001  4899 B  Launcher.Load

Each golden resource is a complete standalone OMF v2 load file — 44-byte
header with BYTECNT == the resource's byte size, LCONST body, relocation
dictionary (RELOC/SUPER records), END.  Nothing is stripped, restructured,
or re-dated.  The `Convert` keyword only sets attribute bit 0x0800, a
Resource Manager *runtime* hint (LoadResource applies the embedded OMF
relocation dictionary when the resource is loaded); there is no build-time
content transformation of the `read` file's bytes.

See work/rezloadcheck.py's module docstring for the full evidence trail,
including the LinkIIgs `-x` relocation-dictionary encoding facts (SUPER
type 26 for the shift-16 class, standalone RELOCs for >24-bit targets such
as `#VersionFilter+$80000000`) that the byte-exact rebuild established.
"""

from __future__ import annotations


def convert_load(load_bytes: bytes) -> bytes:
    """Apply RezIIgs's `read ... Convert` transformation to a .Load file.

    Evidenced identity transform — see the module docstring.  Kept as a real
    function (not a bare alias) so R5/R7 call sites stay stable if further
    corpus evidence ever narrows the finding.
    """
    return bytes(load_bytes)
