# Design: Rez resource compiler (M7 — stretch)

**Replaces:** MPW `RezIIgs`. **Unlocks:** the shipping files for the *asm* desktop
targets whose code already assembles with gsasm but which carry a resource fork —
**Finder, Installer, and the asm-only CDEVs/NDAs** (CDRemote, CloseView,
EasyAccess, VideoKeyboard, General/Namer/Network CDEVs, MountImageGS). Read
`README.md` first.

This is the lowest-priority milestone and the largest single new *language* — do
M2–M6 first. It is a genuinely separate compiler, not byte-shuffling. Scope it to
the **subset of Rez actually used by the asm desktop targets**, not full Rez.

## What it does
Compiles a Rez source file (`.r`/`.rez`/`.rii`) — resource **type declarations**
plus **resource data** — into an Apple IIgs **resource fork** (the `rResource`
format: a resource map + typed resource records). The shipping desktop file is
then `code fork (from gsasm+M2) + resource fork (from Rez)`.

Typical invocations to match:
`RezIIGS Finder.rez -o Finder -t "C7  " -c "pdos"`,
`RezIIGS x.r -o <CDEV> -t "C7  " -c "pdos"`, NDAs with `-t NDA`.

## Approach (incremental)
1. **Survey the actual Rez used.** Read the `.r`/`.rez` files under `A.U.G/Finder`,
   `A.U.G/Installer`, and the asm CDEVs. Enumerate exactly which resource types and
   Rez language features appear (type templates, `read`, `$$` funcs, includes).
   Implement only those.
2. **Rez front end.** A parser for the Rez grammar subset: `type` declarations
   (field templates), `resource <type>(<id>) { ... }` bodies, integer/string/array/
   fill fields, `read`/`$$Resource` includes. (Rez is C-preprocessor-ish + a typed
   data DSL.)
3. **IIgs resource fork back end.** Emit the IIgs resource file format: the resource
   header, the resource map (index of type→[(id, offset, attrs)]), and each
   resource's bytes per its type template. Reference: the IIgs Toolbox Reference
   (Resource Manager) resource-file layout; validate against a golden fork.
4. **Fork assembly.** Combine the gsasm/M2 code output (data fork) with the Rez
   resource fork into the shipping file, with filetype/auxtype (M3 `stamp`).

## Integration
- New subpackage `gsasm/rez/` (`lexer.py`, `parser.py`, `emit.py`) — it's big enough
  to warrant its own module.
- `work/rezcheck.py`: compile a `.r` → resource fork, byte-compare against the
  resource fork extracted from the shipping file (`cadius` can pull both forks).

## Validation & acceptance
- Start with the **smallest** asm target that has a resource fork (an asm CDEV or
  MountImageGS), not the Finder.
- Compile its `.r` → compare the resource fork byte-for-byte vs the shipping file's
  resource fork.
- Then Finder / Installer.
- **Done when:** one asm desktop target's resource fork byte-matches.

## Gotchas
- Rez is a real language with an include/preprocessor layer — but the 6.0.1 desktop
  targets use a limited subset; don't build all of Rez.
- The resource **fork** is separate from the data fork; the disk file is
  dual-fork. `cadius` and the 2MG/HFS layer expose both — make sure the harness
  compares the right fork.
- Type templates define byte layout (endianness, alignment, string forms). Get them
  from the `type` declarations in the same Rez sources — they're self-describing.
- This milestone can be deferred indefinitely without blocking the OS core (M2–M6);
  it only affects the GUI shell.
