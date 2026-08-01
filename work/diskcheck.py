#!/usr/bin/env python3
"""diskcheck.py — M8: reconstruct the shipping GS/OS 6.0.1 disk images byte-exact.

The disk-level analogue of work/buildrom.py. A shipping .2mg is a ProDOS volume;
most of the System Disk is ASM we build from clean-room source. This harness
reconstructs the image: every file with a wired builder is BUILT from source and
overlaid into its ORIGINAL data blocks; the rest is kept from the original — the
ROM pattern ("N% built, byte-identical via substitution"), one level up.

The ProDOS/2IMG layer is the a2til toolkit (read/write, extended/forked, sparse,
2IMG; byte-cross-checked vs cadius) — we do NOT re-implement the filesystem.

DISCIPLINE (per the M8 second-chair review — the physical image match alone is NOT
a builder-correctness gate; a no-builder run is trivially 100%):
  * ownership is an EXPLICIT manifest, not a file-type heuristic; an on-disk file
    absent from the manifest FAILS the inventory.
  * a wired builder must pass a 7-step contract (build_disk_file -> exact bytes;
    len == data-fork EOF; sparse logical blocks are zero; logical bytes ==
    read_file BEFORE overlay; overlay data blocks only; image stays byte-identical;
    coverage does not drop).
  * metrics are fork-aware and reported as THREE numbers, not one.

    python3 work/diskcheck.py                 # inventory + round-trip
    python3 work/diskcheck.py -v              # per-file manifest listing
    python3 work/diskcheck.py --selftest      # prove overlay byte-cleanliness
    python3 work/diskcheck.py --min-built N   # CI: fail if <N built-bytes covered
"""
import sys, os

from _common import ROOT, byte_match, ensure_repo_on_path, first_diff
ensure_repo_on_path()


def _find_a2til():
    """Locate the a2til toolkit without a hard-coded absolute path (P3)."""
    for p in (os.environ.get('A2TIL_PATH'),
              os.path.join(os.path.dirname(ROOT), 'a2til'),  # sibling
              os.path.expanduser('~/src/a2til')):
        if p and os.path.isdir(os.path.join(p, 'a2til')):
            return p
    return None


_A2TIL = _find_a2til()
if not _A2TIL:
    sys.exit("diskcheck: a2til not found — set A2TIL_PATH, or place it as a sibling "
             "of gsasm (…/a2til/a2til/prodos.py). See docs/design/M8_DISK_IMAGES.md.")
sys.path.insert(0, _A2TIL)
from a2til.prodos import Volume, ST_EXTENDED        # noqa: E402

DISKS = 'ref/GSOS_6/System601_disks/System 6.0.1'
SYSTEM_DISK = f'{DISKS}/Disk 2 of 7 System Disk.2mg'

# ---------------------------------------------------------------------------
# Ownership — an EXPLICIT per-path manifest (P1). Owners:
#   BUILD       clean-room ASM we build from source (data fork)
#   REZ         has a resource fork -> needs Rez (M7); substitute whole for now
#   SUBSTITUTE  data/Pascal/GUI — kept from the original image
#   OOS         out of scope (currently none — every on-disk file has an owner)
# A file whose name is `Finder.Data` is SUBSTITUTE by rule. Any other on-disk
# file not listed here FAILS the inventory (so new files can't slip through).
# ---------------------------------------------------------------------------
BUILD, REZ, SUBSTITUTE, OOS = 'build', 'rez', 'substitute', 'out-of-scope'
V = '/System.Disk'
MANIFEST = {
    f'{V}/ProDOS': BUILD, f'{V}/System/P8': BUILD,
    f'{V}/System/GS.OS': BUILD, f'{V}/System/Start.GS.OS': BUILD,
    f'{V}/System/GS.OS.Dev': BUILD, f'{V}/System/Error.Msg': BUILD,
    f'{V}/System/System.Setup/Resource.Mgr': BUILD,
    f'{V}/System/System.Setup/Tool.Setup': BUILD,
    f'{V}/System/System.Setup/TS2': BUILD, f'{V}/System/System.Setup/TS3': BUILD,
    f'{V}/System/FSTs/Char.FST': BUILD, f'{V}/System/FSTs/Pro.FST': BUILD,
    f'{V}/System/Drivers/AppleDisk3.5': BUILD,
    f'{V}/System/Drivers/AppleDisk5.25': BUILD,
    f'{V}/System/Drivers/Console.Driver': BUILD,
    f'{V}/System/CDevs/CDev.Data': SUBSTITUTE,   # binary CDEV config data, no ASM source
    **{f'{V}/System/Tools/Tool{n}': BUILD for n in
       ('014', '015', '016', '018', '019', '020', '021', '022', '023',
        '025', '027', '028', '034')},
    # resource-forked -> Rez (M7); the data fork may be ASM but the fork isn't
    f'{V}/System/Start': REZ, f'{V}/System/System.Setup/Sys.Resources': REZ,
    f'{V}/System/System.Setup/EasyMount': REZ,
    f'{V}/System/Desk.Accs/ControlPanel': REZ,
    f'{V}/System/CDevs/General': REZ, f'{V}/System/CDevs/Printer': REZ,
    f'{V}/System/CDevs/RAM': REZ, f'{V}/System/CDevs/Slots': REZ,
    f'{V}/System/CDevs/Time': REZ,
    # data / config / fonts / icons — substitute
    f'{V}/System/Fonts/Font.Lists': SUBSTITUTE, f'{V}/System/Fonts/Times.10': SUBSTITUTE,
    f'{V}/Icons/FType.Apple': SUBSTITUTE,
    # ProDOS-8 command interpreter — PURE 6502/65C02 ASM (the Applesoft
    # *language* is in ROM, NOT here), built byte-exact via work/basiccheck.py.
    f'{V}/BASIC.System': BUILD,
}


class DiskFile:
    __slots__ = ('path', 'type', 'aux', 'has_rsrc', 'data_eof', 'rsrc_eof',
                 'data_blocks', 'rsrc_blocks', 'owner')

    def __init__(self, path, entry, vol):
        self.path = path
        self.type = entry.type
        self.aux = entry.aux_type
        self.has_rsrc = (entry.storage_type == ST_EXTENDED)
        st, key, self.data_eof = vol._resolve_fork(entry, 'data')
        self.data_blocks = vol._blocks_for(st, key, self.data_eof)   # 0 = sparse
        if self.has_rsrc:
            rst, rkey, self.rsrc_eof = vol._resolve_fork(entry, 'rsrc')
            self.rsrc_blocks = vol._blocks_for(rst, rkey, self.rsrc_eof)
        else:
            self.rsrc_eof = 0
            self.rsrc_blocks = []
        self.owner = owner_for(path)

    @property
    def sparse_idx(self):
        return {i for i, b in enumerate(self.data_blocks) if b == 0}


def owner_for(path):
    if path.rsplit('/', 1)[-1] == 'Finder.Data':
        return SUBSTITUTE
    return MANIFEST.get(path)          # None -> inventory failure


def _walk(vol, path):
    for entry in vol.scandir(path):
        child = path.rstrip('/') + '/' + entry.name
        if entry.is_dir:
            yield from _walk(vol, child)
        else:
            yield child, entry


def catalog_disk(vol):
    files = [DiskFile(p, e, vol) for p, e in _walk(vol, '/' + vol.name)]
    unlisted = [f.path for f in files if f.owner is None]
    if unlisted:
        raise SystemExit("diskcheck: on-disk files not in the manifest "
                         "(add them with an owner):\n  " + "\n  ".join(unlisted))
    return files


def overlay(vol, f, content):
    """Overlay `content` into `f`'s ORIGINAL data blocks (raw, byte-clean).

    Asserts the build fits AND that any sparse logical block is zero in `content`
    (P0: a nonzero sparse block would be silently dropped and mask a bad build)."""
    if len(content) != f.data_eof:
        raise ValueError(f'{f.path}: build {len(content)}B != data-fork EOF {f.data_eof}')
    for i, blk in enumerate(f.data_blocks):
        chunk = content[i * 512:(i + 1) * 512]
        if blk == 0:                                   # sparse (unallocated)
            if any(chunk):
                raise ValueError(f'{f.path}: nonzero data in sparse block {i}')
            continue
        vol._write_block(blk, chunk)


def overlay_rsrc(vol, f, content):
    """The RESOURCE-fork analogue of `overlay()` (M7 flip): a REZ-owned file
    like Sys.Resources has an EMPTY data fork, so a byte-exact build has to
    land in its resource fork's own original blocks instead. Same
    byte-cleanliness contract as `overlay()`, just against `f.rsrc_blocks`/
    `f.rsrc_eof` in place of `f.data_blocks`/`f.data_eof`."""
    if len(content) != f.rsrc_eof:
        raise ValueError(f'{f.path}: build {len(content)}B != rsrc-fork EOF {f.rsrc_eof}')
    for i, blk in enumerate(f.rsrc_blocks):
        chunk = content[i * 512:(i + 1) * 512]
        if blk == 0:                                   # sparse (unallocated)
            if any(chunk):
                raise ValueError(f'{f.path}: nonzero data in sparse rsrc block {i}')
            continue
        vol._write_block(blk, chunk)


# path -> callable() -> the FULL on-disk file bytes (ExpressLoad'd OMF / MakeBin
# output), NOT the de-ExpressLoad'd code image the *check.py harnesses compare.
# Wired as each file's full-file build path is confirmed and passes the contract.
def _build_prodos():
    import probootcheck                     # M3: MakeBin over Boot/ProBoot.src @ $2000
    return probootcheck.build_prodos()


def _build_basic_system():
    import basiccheck                       # ProDOS-8 command interpreter (pure ASM;
    return basiccheck.build_basic_system()  # makebin_segments @ $2000/temporg — see
                                            # work/basiccheck.py). Byte-exact 10,240 B.


SOURCE_BUILDERS = {
    f'{V}/ProDOS': _build_prodos,           # 1668/1668 exact — first disk-ready file
    f'{V}/BASIC.System': _build_basic_system,   # 10240/10240 exact
}
# Per-category builders live in the diskbuilders/ package (auto-discovered), one
# module per category, so they can be developed in parallel without colliding on
# this file. Each module exposes `builders(V) -> {disk_path: callable() -> bytes}`.
try:
    import diskbuilders
    SOURCE_BUILDERS.update(diskbuilders.load(V))
except Exception:                           # missing/partial package is non-fatal
    pass


# path -> callable() -> the FULL RESOURCE-FORK bytes (M7). A REZ-owned file's
# DATA fork is typically empty (e.g. Sys.Resources: 0-byte data fork, the
# whole shipping file is its 24,337-byte resource fork), so these builders
# are wired separately from SOURCE_BUILDERS and overlaid via overlay_rsrc()
# below rather than overlay(). Lazy import (like _build_prodos() above):
# work/rezbuildcheck.py -> work/rezcheck.py -> `import diskcheck as dc` would
# otherwise be a module-level import cycle; deferring the import to call
# time (inside check(), well after this module has finished executing its
# own top level) sidesteps it exactly like _build_prodos()'s lazy
# `import probootcheck` already does.
def _build_sysresources_rsrc():
    import rezbuildcheck                    # M7: Rez pipeline, see docs/design/rez.md
    return rezbuildcheck.build_sysresources_fork()


def _build_easymount_rsrc():
    import easymountcheck                   # M7 follow-on: EasyMount (see docs/design/rez.md)
    return easymountcheck.build_easymount_rsrc_fork()


def _build_cdev(name):
    def _b():
        import cdevcheck                    # Rez tier-1: CDEV forks (clean-room
        return cdevcheck.build_cdev_fork(name)   # include; code extraction-fed)
    return _b


def _build_finder_rsrc():
    import findercheck                  # Rez tier-1: the Finder fork, which
    return findercheck.build_finder_fork()   # ALSO ships as System:Start --
                                        # fully source-built, incl. the
                                        # assembled KeyboardNav read payload
                                        # (see work/findercheck.py)


REZ_BUILDERS = {
    f'{V}/System/System.Setup/Sys.Resources': _build_sysresources_rsrc,
    f'{V}/System/System.Setup/EasyMount': _build_easymount_rsrc,
    f'{V}/System/Start': _build_finder_rsrc,
    f'{V}/System/CDevs/General': _build_cdev('General'),
    f'{V}/System/CDevs/Printer': _build_cdev('Printer'),
    f'{V}/System/CDevs/RAM': _build_cdev('RAM'),
    f'{V}/System/CDevs/Slots': _build_cdev('Slots'),
    f'{V}/System/CDevs/Time': _build_cdev('Time'),
    f'{V}/System/Desk.Accs/ControlPanel': _build_cdev('ControlPanel'),
}


# EasyMount is dual-fork: ALSO has a real (non-empty) data fork, wired
# separately here as a SOURCE_BUILDERS entry -- see the new REZ-owned
# SOURCE_BUILDERS branch in check() below. Lazy import for the same reason
# as _build_sysresources_rsrc()/_build_prodos() above (easymountcheck ->
# rezcheck -> `import diskcheck as dc` would otherwise be a module-load-time
# cycle). Byte-exact as of R11 (see easymountcheck.py's module docstring
# for the two now-fixed asm.py/expressload.py root-cause bugs).
def _build_easymount_data():
    import easymountcheck
    return easymountcheck.build_easymount_data_fork()


SOURCE_BUILDERS[f'{V}/System/System.Setup/EasyMount'] = _build_easymount_data


# Start is the Finder (byte-identical fork): its RESOURCE fork builds via the
# REZ builder above (_build_finder_rsrc); its DATA fork is the full 146,924-byte
# ExpressLoad'd Finder application, wired here as a dual-fork SOURCE_BUILDERS
# entry exactly like EasyMount.  Byte-exact as of the reloc-dictionary work
# (docs/EXPRESSLOAD_FINDER_PLAN.md); the dual-fork branch in check() overlays it.
def _build_finder_data():
    import finderdatacheck
    return finderdatacheck.build_finder_data()


SOURCE_BUILDERS[f'{V}/System/Start'] = _build_finder_data


# ---------------------------------------------------------------------------
# First-Disks phase — a manifest-driven whole-disk overlay for ANY disk, so
# non-System disks reconstruct byte-exact too (SOW physical_exact 1/7 -> 3/7).
#
# Disk 2 keeps its own MANIFEST/SOURCE_BUILDERS/REZ_BUILDERS/check() path
# UNCHANGED.  The generalized path below is a fully separate `reconstruct()`
# keyed by the census disk label; each disk's registry lists exactly the forks
# with a wired byte-exact builder.  Everything else on the disk is carried
# verbatim (the ROM substitution pattern) — so the physical image match is by
# construction, and the HONEST gate is the byte-exact-builder count (a failed
# build is simply not overlaid, which would leave the image trivially matching;
# `logical-exact: ok/N` is what goes red).  Same lazy-import discipline as the
# Disk-2 builder wrappers above (avoids rezcheck/cdevcheck import cycles).
# ---------------------------------------------------------------------------
def _build_fonts_readme_rsrc():
    import rezdatacheck                       # rez `data` fork (TeachText Read.Me)
    return rezdatacheck.build_rez_fork('Fonts.Read.Me')


def _build_midi_rsrc():
    import cdevcheck                          # synthLAB MIDI CDEV resource fork
    return cdevcheck.build_cdev_fork('MIDI')


def _build_tool035_fullfile():
    import toolcheck                          # full 29,842-byte ExpressLoad file
    return toolcheck.build_tool035_fullfile()  # (objsel link + single-seg wrap)


# ---------------------------------------------------------------------------
# Disk 1 (Install) — Disk-1-ONLY artifacts.  Everything else Disk 1 needs is a
# duplicate-of-Disk-2 file (same clean-room ASM, same shipping bytes — the
# census's "cmp-identical to the System-Disk copy" claim), so those entries
# below reuse the SAME SOURCE_BUILDERS/REZ_BUILDERS callables registered for
# the '/System.Disk/...' path above — NOT re-implemented here.  Same lazy-
# import discipline as the wrappers above (avoids install*check/appdatacheck/
# cdevcheck/expressloadcheck import cycles through diskcheck).
# ---------------------------------------------------------------------------
def _build_installer_data():
    import installerdatacheck               # S16 app, multiseg jt_entries link
    return installerdatacheck.build_installer_data()


def _build_installer_rsrc():
    import installercheck                    # Rez tier-1, self-contained dialect
    return installercheck.build_installer_fork()


def _build_controlpanel_data():
    import appdatacheck                      # APPMAP['ControlPanel'] (NDA code,
    return appdatacheck.build_app_data('ControlPanel')  # CtlPanel.aii+cbp.aii)


def _build_setstart_rsrc():
    import cdevcheck                          # CDEVMAP['SetStart'] (Install-only;
    return cdevcheck.build_cdev_fork('SetStart')  # not in Disk-2 REZ_BUILDERS)


def _build_install_start():
    import expressloadcheck                   # 565B SetStart-generated launcher —
    return expressloadcheck.build_start()      # NOT the Finder (System.Disk/Start
                                                # is a wholly different file/recipe)


def _driver_fullfile(name):
    """Full-file ExpressLoad builder for a drivercheck DRIVERMAP driver that
    ships on a non-System disk (no Disk-2 SOURCE_BUILDERS entry to reuse) —
    the generic assemble+expressload() recipe expressload_files._build_driver
    uses for the Disk-2 drivers.  Returns a lazy builder callable.

    Grew from the Disk-1 UniDisk3.5 one-off when the sym_kind fix
    (gsasm/linkiigs.py SymTab.kinds — the exported-EQU spurious-reloc bug,
    docs/SCSI_RELOC_DIAGNOSIS_2026-08-01.md) made seven more full driver
    files byte-exact: SCSIHD (D1) + SCSICD/SCSIScan/SCSITape/ImageWriter/
    ImageWriter.LQ/StyleWriter (D3)."""
    def _build():
        import drivercheck
        subdir, srcs, defines = drivercheck.DRIVERMAP[name]
        drv_dir = f'{drivercheck.SRC}/{subdir}'
        incs = [drv_dir] + drivercheck.INCS
        from gsasm import asm, omf
        from gsasm.expressload import expressload
        objects = []
        for r in srcs:
            a = asm.assemble(f'{drv_dir}/{r}', incs, defines=defines or None)
            objects.append((omf.emit(a), a))
        return expressload(objects)
    return _build


_build_unidisk35_fullfile = _driver_fullfile('UniDisk3.5')


# ---------------------------------------------------------------------------
# Disk 3 (SystemTools1) — full-file ExpressLoad builders for the census's
# 'built' forks that are NOT duplicates of a Disk-2 file (those instead reuse
# the SAME SOURCE_BUILDERS/REZ_BUILDERS callables below, exactly like Disk 1's
# block does — Tool025, BASIC.System, and the Printer/Slots/Time CDEVs are
# byte-identical shipping copies of the System-Disk files).  Same lazy-import
# discipline as every wrapper above.
#
# Investigated but left OUT (full-file surface NOT byte-exact even though the
# DE-ExpressLoad'd code image is proven byte-exact by drivercheck.py, which is
# what backs the census's 'built' classification for these 8 driver forks —
# see D3_OVERLAY_REPORT.md's Residuals section for the diagnosis of each):
#   SCSI.Manager, SCSICD.Driver, SCSIScan.Driver, SCSITape.Driver
#     (11/13-object merges; same reloc-dictionary forward-pointer class as
#     Disk 1's SCSIHD.Driver residual — +8B/+14B/+14B/+14B, first diff @ 0x64)
#   ImageWriter, ImageWriter.LQ, StyleWriter
#     (8/8/9-object merges; SAME class — +15B/+15B/+18B, first diff @ 0x64)
#   Epson
#     (2-object merge; a DIFFERENT, genuinely new residual class — same total
#     length, but the unmerged/segmented LCONST payload itself diverges from
#     gold's mid-code, at a byte position that is NOT a RELOC target offset —
#     i.e. not the SCSI-class reloc-dictionary bug. Unexplored; left OUT.)
def _build_driver_fullfile(name):
    """Generic full ExpressLoad file builder for one drivercheck.DRIVERMAP
    single/flat-object-list driver, reusing drivercheck's own build_time
    table (RAM5 embeds its build date/time — DRIVER_BUILD_TIME)."""
    def _b():
        import drivercheck
        subdir, srcs, defines = drivercheck.DRIVERMAP[name]
        drv_dir = f'{drivercheck.SRC}/{subdir}'
        incs = [drv_dir] + drivercheck.INCS
        from gsasm import asm, omf
        from gsasm.expressload import expressload
        sysdate, systime = drivercheck.DRIVER_BUILD_TIME.get(name, (None, None))
        objects = []
        for r in srcs:
            a = asm.assemble(f'{drv_dir}/{r}', incs, defines=defines or None,
                             sysdate=sysdate, systime=systime)
            objects.append((omf.emit(a), a))
        return expressload(objects)
    return _b


def _build_fst_fullfile(name):
    """Generic full ExpressLoad file builder for one fstcheck.FSTMAP FST,
    including the 'lib' packaging (MSDos.FST): the library-member extraction
    ORDER is captured straight from linkiigs.link_lib's own scan (a spy on
    linkiigs.link's seg_order argument during a throwaway merged-link call),
    so this is NOT a reimplementation of the -lib hash-bucket algorithm —
    it reuses the exact order fstcheck's own code-image comparison already
    gates byte-exact, then feeds that order to expressload() (unmerged)
    for the FULL on-disk file, the same way toolcheck.objsel_objects's
    seg_order feeds Tool032/035's full-file builds."""
    def _b():
        import fstcheck
        from gsasm import asm, omf, linkiigs
        from gsasm.expressload import expressload
        subdir, srcs, defines, *rest = fstcheck.FSTMAP[name]
        mode = rest[0] if rest else None
        fst_dir = f'{fstcheck.GSOS}/{subdir}'
        incs = [fst_dir] + fstcheck.INCS
        objects = []
        for r in srcs:
            a = asm.assemble(f'{fst_dir}/{r}', incs, defines=defines or None)
            objects.append((omf.emit(a), a))
        if mode == 'lib':
            captured = {}
            orig_link = linkiigs.link

            def _spy(objs, opts=None):
                captured['seg_order'] = (opts or {}).get('seg_order')
                return orig_link(objs, opts)

            linkiigs.link = _spy
            try:
                linkiigs.link_lib(objects[:1], objects[1:], opts={'merge': True})
            finally:
                linkiigs.link = orig_link
            return expressload(objects, opts={'order': captured['seg_order']})
        return expressload(objects)
    return _b


def _build_tool_flat_fullfile(tool):
    """Generic full ExpressLoad file builder for one toolcheck.TOOLMAP
    flat single-segment tool (Tool026/029 — same shape as
    diskbuilders/expressload_files.py's _build_tool, but for a Disk-3-only
    tool with no existing diskbuilder entry)."""
    def _b():
        import toolcheck
        from gsasm import asm, omf
        from gsasm.expressload import expressload
        subdir, srcs = toolcheck.TOOLMAP[tool]
        objects = []
        for r in srcs:
            a = asm.assemble(f'{toolcheck.TB}/{subdir}/{r}', toolcheck.INCS)
            objects.append((omf.emit(a), a))
        return expressload(objects)
    return _b


def _build_tool032_fullfile():
    import toolcheck                           # objsel-based (same shape as
    from gsasm.expressload import expressload  # toolcheck.build_tool035_fullfile)
    objects, seg_order = toolcheck.objsel_objects(toolcheck.TOOLMAP['032'][1]['objsel'])
    return expressload(objects, opts={'order': seg_order})


def _build_cdremote_data():
    import appdatacheck                        # CDRemote NDA, expressload'd
    return appdatacheck.build_app_data('CDRemote')


def _build_findfile_rsrc():
    import rezforkcheck                        # pure-Rez DA fork (no code rsrc)
    return rezforkcheck.build_rez_fork('FindFile')


def _build_advdiskutil_rsrc():
    import rezforkcheck                        # ADU app rsrc fork (data fork
    return rezforkcheck.build_rez_fork('Adv.Disk.Util')  # stays Pascal/substitute)


# ---------------------------------------------------------------------------
# Disk 4 (SystemTools2) — generic per-name wrapper factories, reused across
# many of the disk's 47 wired forks (mirrors _build_cdev(name) above). Same
# lazy-import discipline as every wrapper in this file.
# ---------------------------------------------------------------------------
def _build_rezforkcheck(name):
    def _b():
        import rezforkcheck                     # 8-target Rez fork harness
        return rezforkcheck.build_rez_fork(name)  # (MediaControl/VideoMix NDAs,
    return _b                                    # Pioneer4200 rsrc, Frog/Whoosh)


def _build_appdatacheck(name):
    def _b():
        import appdatacheck                      # 4(+1)-target pure-ASM data
        return appdatacheck.build_app_data(name)  # fork harness (Pioneer2000/
    return _b                                    # EasyAccess/Pioneer4200)


def _build_rezdatacheck(name):
    def _b():
        import rezdatacheck                      # template-free `data`-statement
        return rezdatacheck.build_rez_fork(name)  # rsrc forks (10 Sounds + the
    return _b                                    # 3 TeachText docs' rsrc fork)


def _build_teach_rsrc():
    import teachcheck                            # Pascal-walled Teach; Rez
    return teachcheck.build_teach_fork()         # layer only (data fork substitute)


def _build_text_source(relpath):
    """Disk 4's Read.Me/Shortcuts/Whats.New DATA forks are shipped verbatim
    from tracked source text (the makefiles' `Duplicate` rule) -- the SAME
    equality work/textdatacheck.py already gates as TEXT_DATA_BYTES_EXACT,
    wrapped here as a builder callable (open+read, no build step, exactly
    like textdatacheck's own comparison)."""
    def _b():
        with open(os.path.join(ROOT, 'ref', 'GSOS_6', 'IIGS.601.SRC', relpath),
                  'rb') as f:
            return f.read()
    return _b


def _build_iwem_d4():
    import iwemcheck                             # MPW BuildIWEm text-squeeze
    return iwemcheck.build_iwem_disk4()          # replay (cracked 2026-08-01)


def _build_quicklogoff():
    import expressloadcheck
    return expressloadcheck.build_quicklogoff()


def _build_tool038():
    import expressloadcheck
    return expressloadcheck.build_tool038()


def _build_atinit():
    import expressloadcheck
    return expressloadcheck.build_atinit()


def _build_atresponder():
    import expressloadcheck
    return expressloadcheck.build_atresponder()


def _build_net_start():
    import expressloadcheck
    return expressloadcheck.build_net_start()


# path -> (fork, builder()->bytes) per census disk label.  fork is the ACTUAL
# on-disk fork the builder targets (Read.Me/MIDI build their resource forks;
# Tool035 its data fork) — independent of the census's file-granular label.
DISK_BUILDER_REGISTRY = {
    'Disk 5 of 7 Fonts.2mg': {
        '/Fonts/Goodies/Read.Me': ('rsrc', _build_fonts_readme_rsrc),
    },
    'Disk 6 of 7 synthLAB.2mg': {
        '/synthLAB/MIDI': ('rsrc', _build_midi_rsrc),
        '/synthLAB/Tool035': ('data', _build_tool035_fullfile),
    },
    # Disk 1 (Install) — 37 of the census's 39 'built' forks.  RESIDUAL (left
    # OUT, not force-wired): /Install/System/Drivers/SCSI.Manager and
    # .../SCSIHD.Driver.  Their DE-EXPRESSLOAD'D code images are proven
    # byte-exact (work/drivercheck.py, closed 2026-07-18) — that is what the
    # census's 'built' classification is backed by — but the FULL on-disk
    # ExpressLoad'd file (this registry's surface, never gated before) is NOT:
    # a small reloc-dictionary encoding difference (+8B / +14B respectively;
    # first divergence in the ~ExpressLoad directory's forward-pointer fields,
    # propagating from a reloc-run delta assigned to the wrong dict slot around
    # the merged multi-file object — see the investigation in the M8 Disk-1
    # overlay work). 2026-08-01 UPDATE: BOTH closed, 39 of 39 wired. The
    # sym_kind fix (docs/SCSI_RELOC_DIAGNOSIS_2026-08-01.md) closed the
    # reloc-dict class (SCSIHD + the D3 five); SCSI.Manager's last body byte
    # was NOT the diagnosis-§6 badmin theory but a deferred CONST-only shift
    # (`#work_vars_size>>16` baking unshifted 89 instead of 0) — fixed by
    # passing the kind-derived equ set to _defer_shifts in expressload's
    # single path, exactly as linkiigs.link() already did (see the doc's
    # 2026-08-01 addendum).
    'Disk 1 of 7 Install.2mg': {
        '/Install/ProDOS': ('data', SOURCE_BUILDERS[f'{V}/ProDOS']),
        '/Install/System/GS.OS': ('data', SOURCE_BUILDERS[f'{V}/System/GS.OS']),
        '/Install/System/Start.GS.OS': (
            'data', SOURCE_BUILDERS[f'{V}/System/Start.GS.OS']),
        '/Install/System/Error.Msg': (
            'data', SOURCE_BUILDERS[f'{V}/System/Error.Msg']),
        '/Install/System/GS.OS.Dev': (
            'data', SOURCE_BUILDERS[f'{V}/System/GS.OS.Dev']),
        '/Install/System/FSTs/Pro.FST': (
            'data', SOURCE_BUILDERS[f'{V}/System/FSTs/Pro.FST']),
        '/Install/System/FSTs/Char.FST': (
            'data', SOURCE_BUILDERS[f'{V}/System/FSTs/Char.FST']),
        '/Install/System/Drivers/AppleDisk3.5': (
            'data', SOURCE_BUILDERS[f'{V}/System/Drivers/AppleDisk3.5']),
        '/Install/System/Drivers/AppleDisk5.25': (
            'data', SOURCE_BUILDERS[f'{V}/System/Drivers/AppleDisk5.25']),
        '/Install/System/Drivers/Console.Driver': (
            'data', SOURCE_BUILDERS[f'{V}/System/Drivers/Console.Driver']),
        '/Install/System/Drivers/UniDisk3.5': ('data', _build_unidisk35_fullfile),
        '/Install/System/Drivers/SCSIHD.Driver': (
            'data', _driver_fullfile('SCSIHD.Driver')),
        '/Install/System/Drivers/SCSI.Manager': (
            'data', _driver_fullfile('SCSI.Manager')),
        '/Install/System/System.Setup/Tool.Setup': (
            'data', SOURCE_BUILDERS[f'{V}/System/System.Setup/Tool.Setup']),
        '/Install/System/System.Setup/TS2': (
            'data', SOURCE_BUILDERS[f'{V}/System/System.Setup/TS2']),
        '/Install/System/System.Setup/TS3': (
            'data', SOURCE_BUILDERS[f'{V}/System/System.Setup/TS3']),
        '/Install/System/System.Setup/Resource.Mgr': (
            'data', SOURCE_BUILDERS[f'{V}/System/System.Setup/Resource.Mgr']),
        '/Install/System/System.Setup/Sys.Resources': (
            'rsrc', REZ_BUILDERS[f'{V}/System/System.Setup/Sys.Resources']),
        '/Install/System/CDevs/SetStart': ('rsrc', _build_setstart_rsrc),
        '/Install/System/CDevs/General': (
            'rsrc', REZ_BUILDERS[f'{V}/System/CDevs/General']),
        '/Install/System/CDevs/RAM': (
            'rsrc', REZ_BUILDERS[f'{V}/System/CDevs/RAM']),
        # dual-fork (like EasyMount/Start on Disk 2): a LIST of (fork, builder)
        # pairs for the same path — data (NDA code, appdatacheck) AND rsrc
        # (cdevcheck, same REZ_BUILDERS callable Disk 2's ControlPanel uses).
        '/Install/System/Desk.Accs/ControlPanel': [
            ('data', _build_controlpanel_data),
            ('rsrc', REZ_BUILDERS[f'{V}/System/Desk.Accs/ControlPanel']),
        ],
        '/Install/System/Start': ('data', _build_install_start),
        '/Install/System/P8': ('data', SOURCE_BUILDERS[f'{V}/System/P8']),
        **{f'/Install/System/Tools/Tool{n}': (
            'data', SOURCE_BUILDERS[f'{V}/System/Tools/Tool{n}'])
           for n in ('014', '015', '016', '018', '019', '020', '021', '022',
                     '023', '027', '028', '034')},
        '/Install/Installer': [
            ('data', _build_installer_data),
            ('rsrc', _build_installer_rsrc),
        ],
    },
    # Disk 3 (SystemTools1) — 30 of the census's 38 'built' forks.  8 driver
    # forks (SCSI.Manager/SCSICD.Driver/SCSIScan.Driver/SCSITape.Driver/
    # ImageWriter/ImageWriter.LQ/StyleWriter/Epson) are RESIDUAL, left OUT —
    # see the residual note above _build_driver_fullfile()'s definition and
    # D3_OVERLAY_REPORT.md for the full diagnosis (two distinct bug classes:
    # a reloc-dictionary forward-pointer miscount on 8-13 object merges, and
    # a separate mid-LCONST divergence for Epson's 2-object merge).  Both
    # driver forks stay on disk as their original bytes.
    'Disk 3 of 7 SystemTools1.2mg': {
        # dual-fork: reuses the SAME '/System.Disk/System/Start' callables
        # Disk 2 already gates (the census records Disk 3's Finder
        # cmp-identical to Start's data+rsrc forks).
        '/SystemTools1/System/Finder': [
            ('data', SOURCE_BUILDERS[f'{V}/System/Start']),
            ('rsrc', REZ_BUILDERS[f'{V}/System/Start']),
        ],
        # Printer/Slots/Time CDEVs are byte-identical shipping copies of the
        # System-Disk CDEVs (cdevcheck.CDEVMAP's own golden for these three
        # names is the Disk-2 copy) — reuse Disk 2's REZ_BUILDERS callables
        # exactly, not a fresh D3-golden build.
        '/SystemTools1/System/CDevs/Printer': (
            'rsrc', REZ_BUILDERS[f'{V}/System/CDevs/Printer']),
        '/SystemTools1/System/CDevs/Slots': (
            'rsrc', REZ_BUILDERS[f'{V}/System/CDevs/Slots']),
        '/SystemTools1/System/CDevs/Time': (
            'rsrc', REZ_BUILDERS[f'{V}/System/CDevs/Time']),
        # Disk-3-only CDEVs (cdevcheck.CDEVMAP already golds these against
        # THIS disk directly).
        '/SystemTools1/System/CDevs/DirectConnect': (
            'rsrc', _build_cdev('DirectConnect')),
        '/SystemTools1/System/CDevs/Keyboard': ('rsrc', _build_cdev('Keyboard')),
        '/SystemTools1/System/CDevs/Modem': ('rsrc', _build_cdev('Modem')),
        '/SystemTools1/System/CDevs/Monitor': ('rsrc', _build_cdev('Monitor')),
        '/SystemTools1/System/CDevs/Sound': ('rsrc', _build_cdev('Sound')),
        '/SystemTools1/System/Desk.Accs/CDRemote': ('data', _build_cdremote_data),
        '/SystemTools1/System/Desk.Accs/FindFile': ('rsrc', _build_findfile_rsrc),
        '/SystemTools1/Adv.Disk.Util': ('rsrc', _build_advdiskutil_rsrc),
        # Drivers — full-file byte-exact (single or 2-object merges only;
        # see the residual note above for the 8 left OUT).
        # sym_kind-fix graduates (2026-08-01): full files now byte-exact.
        '/SystemTools1/System/Drivers/SCSI.Manager': (
            'data', _driver_fullfile('SCSI.Manager')),
        '/SystemTools1/System/Drivers/SCSICD.Driver': (
            'data', _driver_fullfile('SCSICD.Driver')),
        '/SystemTools1/System/Drivers/SCSIScan.Driver': (
            'data', _driver_fullfile('SCSIScan.Driver')),
        '/SystemTools1/System/Drivers/SCSITape.Driver': (
            'data', _driver_fullfile('SCSITape.Driver')),
        '/SystemTools1/System/Drivers/ImageWriter': (
            'data', _driver_fullfile('ImageWriter')),
        '/SystemTools1/System/Drivers/ImageWriter.LQ': (
            'data', _driver_fullfile('ImageWriter.LQ')),
        '/SystemTools1/System/Drivers/StyleWriter': (
            'data', _driver_fullfile('StyleWriter')),
        '/SystemTools1/System/Drivers/A2.RAMCard': (
            'data', _build_driver_fullfile('A2.RAMCard')),
        '/SystemTools1/System/Drivers/RAM5': (
            'data', _build_driver_fullfile('RAM5')),
        '/SystemTools1/System/Drivers/Modem': (
            'data', _build_driver_fullfile('Modem')),
        '/SystemTools1/System/Drivers/Parallel.Card': (
            'data', _build_driver_fullfile('Parallel.Card')),
        '/SystemTools1/System/Drivers/Printer': (
            'data', _build_driver_fullfile('Printer')),
        '/SystemTools1/System/Drivers/Apple.Midi': (
            'data', _build_driver_fullfile('Apple.Midi')),
        '/SystemTools1/System/Drivers/Card6850.MIDI': (
            'data', _build_driver_fullfile('Card6850.MIDI')),
        # FSTs — all 5 full-file byte-exact, including MSDOS.FST's -lib
        # packaging (see _build_fst_fullfile's docstring).
        '/SystemTools1/System/FSTs/DOS3.3.FST': (
            'data', _build_fst_fullfile('DOS3.3.FST')),
        '/SystemTools1/System/FSTs/HFS.FST': (
            'data', _build_fst_fullfile('HFS.FST')),
        '/SystemTools1/System/FSTs/HS.FST': (
            'data', _build_fst_fullfile('HS.FST')),
        '/SystemTools1/System/FSTs/Pascal.FST': (
            'data', _build_fst_fullfile('Pascal.FST')),
        '/SystemTools1/System/FSTs/MSDOS.FST': (
            'data', _build_fst_fullfile('MSDos.FST')),
        # Tool025 is a byte-identical shipping copy of Disk 2's Tool025 —
        # reuse the same SOURCE_BUILDERS callable.  Tool026/029/032 are
        # Disk-3-only.
        '/SystemTools1/System/Tools/Tool025': (
            'data', SOURCE_BUILDERS[f'{V}/System/Tools/Tool025']),
        '/SystemTools1/System/Tools/Tool026': (
            'data', _build_tool_flat_fullfile('026')),
        '/SystemTools1/System/Tools/Tool029': (
            'data', _build_tool_flat_fullfile('029')),
        '/SystemTools1/System/Tools/Tool032': ('data', _build_tool032_fullfile),
        # BASIC.System is byte-identical on both shipping copies (basiccheck
        # proves it against this Disk-3 copy explicitly) — reuse the same
        # SOURCE_BUILDERS callable.
        '/SystemTools1/BASIC.System': ('data', SOURCE_BUILDERS[f'{V}/BASIC.System']),
    },
    # Disk 4 (SystemTools2) — 47 of the census's 52 'built' forks (fork-
    # granular: the census marks some FILES pascal-c-nontarget overall while
    # still classifying one of their two forks 'built' -- e.g. Teach, the
    # MediaControl/VideoMix NDAs -- exactly the fork-granular reading this
    # registry has used since Disk 1/3).  5 forks are RESIDUAL, left OUT (not
    # force-wired) -- see the notes above each helper and D4_OVERLAY_REPORT.md
    # for the full diagnosis:
    #   VideoKeyboard, ATP1.ATROM  -- SAME reloc-dictionary forward-pointer
    #     class as Disk 1's SCSIHD.Driver / Disk 3's 8 driver residuals (a
    #     multi-object ExpressLoad merge's reloc weight lands in the wrong
    #     directory slot).  VideoKeyboard: +18B, cascading diffs from offset
    #     0 once the directory/reloc-dict size disagrees.  ATP1.ATROM: SAME
    #     length (11080B) but 2 bytes differ at 0x144, inside a directory
    #     forward-pointer field (0x0e56 vs 0x0e95).
    #   LaserWriter  -- a genuinely NEW gap, not merely the above class: its
    #     DRIVERMAP entry is a 2-load-segment jt_segments driver (like
    #     Tool015/016/018), and drivercheck._link_jt_driver only ever
    #     produces the CONCATENATED CODE IMAGE (36644B) that de_express(gold)
    #     compares -- there is no jt-aware FULL ExpressLoad-file packager
    #     (directory + per-segment reloc dicts + ~JumpTable) anywhere in the
    #     codebase yet, so the 39779B on-disk file cannot be attempted.
    #   CloseView  -- same gap as LaserWriter: expressloadcheck.
    #     build_closeview_code() is explicitly documented as CODE-IMAGE-ONLY
    #     (2-lseg INIT+NDA, no packaging modeled); full-file needs the same
    #     unbuilt jt-aware ExpressLoad packager.
    #   AppleShare.FST  -- the disk's own census notes flag this exact file as
    #     the likely SCSI-class example; confirmed: a 25-object merge (24
    #     modules + JudgeName), SAME length as gold (19950 vs 19948 -- +2B)
    #     but diverges at offset 0x64, in the ~ExpressLoad directory.
    # All 5 stay on disk as their original (untouched) bytes; only
    # disk4_logical_exact's denominator is 47, not 52.
    'Disk 4 of 7 SystemTools2.2mg': {
        # AppleTalk net-boot trio + protocol/supervisory drivers -- generic
        # full-file expressload(objects) recipe (same _build_driver_fullfile
        # Disk 3's single/2-object drivers use); all confirmed byte-exact
        # full-file (probe 2026-08-01), including the 18-object ATP2.ATRAM
        # merge (object count alone does not predict the reloc-dict bug).
        '/SystemTools2/AppleTalk/Boot.Driver': (
            'data', _build_driver_fullfile('Boot.Driver')),
        '/SystemTools2/System/Drivers/SCC.Manager': (
            'data', _build_driver_fullfile('SCC.Manager')),
        '/SystemTools2/System/Drivers/AppleTalk': (
            'data', _build_driver_fullfile('AppleTalk')),
        '/SystemTools2/System/Drivers/ATP2.ATRAM': (
            'data', _build_driver_fullfile('ATP2.ATRAM')),
        '/SystemTools2/System/Drivers/ATalk': (
            'data', _build_driver_fullfile('ATalk')),
        '/SystemTools2/System/Drivers/Media.Control/AppleCDSC': (
            'data', _build_driver_fullfile('AppleCDSC')),
        '/SystemTools2/System/System.Setup/AppleIIVOC': (
            'data', _build_driver_fullfile('AppleIIVOC')),
        # IWEM -- PostScript text-squeeze replay (NOT 65816 code), the
        # BuildIWEm crack.
        '/SystemTools2/System/Drivers/IWEM': ('data', _build_iwem_d4),
        # expressloadcheck full-file builders (already whole-file, not code-
        # image-only, per that module's own docstring/contract).
        '/SystemTools2/AppleTalk/QuickLogoff': ('data', _build_quicklogoff),
        '/SystemTools2/System/Tools/Tool038': ('data', _build_tool038),
        '/SystemTools2/System/System.Setup/ATInit': ('data', _build_atinit),
        '/SystemTools2/System/System.Setup/ATResponder': (
            'data', _build_atresponder),
        '/SystemTools2/AppleTalk/Start': ('data', _build_net_start),
        # CDEVs -- rsrc only (data fork empty, no-source-substitute by
        # census); reuse the generic _build_cdev(name) factory Disk 1/3 use.
        '/SystemTools2/System/CDevs/AppleShare': (
            'rsrc', _build_cdev('AppleShare')),
        '/SystemTools2/System/CDevs/FolderPriv': (
            'rsrc', _build_cdev('FolderPriv')),
        '/SystemTools2/System/CDevs/MediaControl': (
            'rsrc', _build_cdev('MediaControl')),
        '/SystemTools2/System/CDevs/Namer': ('rsrc', _build_cdev('Namer')),
        '/SystemTools2/System/CDevs/NetPrinter': (
            'rsrc', _build_cdev('NetPrinter')),
        '/SystemTools2/System/CDevs/Network': ('rsrc', _build_cdev('Network')),
        # Pascal-walled Desk.Accs NDAs -- rsrc-only fork is 'built' even
        # though the file overall is pascal-c-nontarget (fork-granular
        # census reading, same as Teach below).
        '/SystemTools2/System/Desk.Accs/MediaControl': (
            'rsrc', _build_rezforkcheck('MediaControl')),
        '/SystemTools2/System/Desk.Accs/VideoMix': (
            'rsrc', _build_rezforkcheck('VideoMix')),
        # Media.Control drivers -- Pioneer2000 (single-object expressload,
        # appdatacheck), Pioneer4200 (BOTH forks: plain-load data fork via
        # appdatacheck, rsrc via rezforkcheck).
        '/SystemTools2/System/Drivers/Media.Control/Pioneer2000': (
            'data', _build_appdatacheck('Pioneer2000')),
        '/SystemTools2/System/Drivers/Media.Control/Pioneer4200': [
            ('data', _build_appdatacheck('Pioneer4200')),
            ('rsrc', _build_rezforkcheck('Pioneer4200')),
        ],
        # EasyAccess -- single-object expressload, appdatacheck.
        '/SystemTools2/System/System.Setup/EasyAccess': (
            'data', _build_appdatacheck('EasyAccess')),
        # EasyMount -- dual-fork, cmp-identical to the System-Disk copy per
        # the census; reuse the SAME Disk-2 SOURCE_BUILDERS/REZ_BUILDERS
        # callables (not re-implemented here), exactly like Disk 3's Finder
        # dual-fork reuse above. Confirmed logical-exact against THIS disk's
        # own on-disk forks by the reconstruct() pre-overlay compare, not
        # merely asserted.
        '/SystemTools2/System/System.Setup/EasyMount': [
            ('data', SOURCE_BUILDERS[f'{V}/System/System.Setup/EasyMount']),
            ('rsrc', REZ_BUILDERS[f'{V}/System/System.Setup/EasyMount']),
        ],
        # Tool033 (VideoMix toolset) -- flat single-object link, same shape
        # as Disk 3's Tool026/029 -- reuse the SAME generic helper.
        '/SystemTools2/System/Tools/Tool033': (
            'data', _build_tool_flat_fullfile('033')),
        # 10 System Sounds -- template-free `data`-statement rsrc forks
        # (rezdatacheck); 2 more (Frog/Whoosh) use the rSoundSample template
        # instead and live in rezforkcheck (wired just above the Media.
        # Control block via the SAME _build_rezforkcheck factory -- see
        # Desk.Accs/MediaControl and VideoMix entries' factory reuse).
        **{f'/SystemTools2/System/Sounds/{n}': ('rsrc', _build_rezdatacheck(n))
           for n in ('Ahh', 'Doorbell', 'Droplet', 'Eastern', 'PipeOrgan',
                     'Quack', 'SimpleBeep', 'Sosumi', 'Swish', 'Trumpets')},
        '/SystemTools2/System/Sounds/Frog': ('rsrc', _build_rezforkcheck('Frog')),
        '/SystemTools2/System/Sounds/Whoosh': (
            'rsrc', _build_rezforkcheck('Whoosh')),
        # Teach -- Pascal-walled editor; rsrc-only fork 'built' (data fork
        # stays a no-source-substitute wall).
        '/SystemTools2/Teach': ('rsrc', _build_teach_rsrc),
        # Read.Me/Shortcuts/Whats.New -- DUAL-FORK: data is the verbatim
        # tracked source text (textdatacheck's own comparison, wrapped as a
        # builder callable), rsrc is the TeachText TE-record+style-block Rez
        # fork (rezdatacheck, same pipeline as the Sounds above).
        '/SystemTools2/Read.Me': [
            ('data', _build_text_source('ToolBoxMisc/ReadMeFiles/Read.Me.text')),
            ('rsrc', _build_rezdatacheck('Read.Me')),
        ],
        '/SystemTools2/Shortcuts': [
            ('data', _build_text_source('ToolBoxMisc/ReadMeFiles/Shortcuts.text')),
            ('rsrc', _build_rezdatacheck('Shortcuts')),
        ],
        '/SystemTools2/Whats.New': [
            ('data', _build_text_source('ToolBoxMisc/ReadMeFiles/Whats.New.text')),
            ('rsrc', _build_rezdatacheck('Whats.New')),
        ],
    },
}


def _iter_registry(reg):
    """Yield (path, fork, builder) for every registered fork of `reg`
    (DISK_BUILDER_REGISTRY[disk_label]).  A path's value is either one
    (fork, builder) tuple or a LIST of them (dual-fork files, e.g. Disk 1's
    ControlPanel/Installer — data AND rsrc both wired for the same path)."""
    for path, val in reg.items():
        for fork, builder in (val if isinstance(val, list) else [val]):
            yield path, fork, builder


def reconstruct_hfs(disk_label):
    """Disk 7 (HFS) analogue of reconstruct(): overlay every registered fork
    via a2til's HfsVolume.overlay (issue #9 phase 2 — in-place rewrite into
    the fork's own extents, length changes refused, slack never written,
    MDB/boot blocks outside the write device by construction), then confirm
    the whole 2IMG image stays byte-identical.

    Same contract and print/return shape as reconstruct(): build -> logical
    compare vs the ORIGINAL fork BEFORE overlay -> overlay only a byte-exact
    build -> whole-image physical compare.  The registry is disk7check's
    _TARGETS (colon paths + builders — the six from-source data forks; the
    Mac-'vers' resource forks are substitutes and are never touched).
    Pre-wiring dress rehearsal 2026-08-01: self-overlay of all 24 forks
    byte-identical on the real image; all 6 built forks overlay with whole-
    image byte-identity; a corrupted build diffs exactly 1 in-fork byte
    (a2til issue #9 comment 798).  Returns (match, n, ok, total)."""
    from a2til.hfs import HfsVolume
    import disk7check
    disk_path = f'{DISKS}/{disk_label}'
    orig = open(disk_path, 'rb').read()
    buf = bytearray(orig)
    vol = HfsVolume(buf)
    reg = disk7check._TARGETS               # [(colon_path, builder)]
    ok = 0
    notes = []
    for tpath, builder in reg:
        try:
            content = bytes(builder())
        except Exception as e:                             # noqa: BLE001
            notes.append(f'{tpath}: builder raised {type(e).__name__}: {e}')
            continue
        original = vol.read_file(tpath)     # logical compare (pre-overlay)
        if content != original:
            notes.append(f'{tpath}: logical differs at '
                         f'{_first_diff(content, original)}')
            continue
        vol.overlay(tpath, content)         # only a byte-exact build
        ok += 1
    match, n = byte_match(bytes(buf), orig)
    print(f"{disk_label}: {vol.volume_name}  HFS "
          f"({vol.total_blocks} allocation blocks)")
    print(f"  builders wired: {len(reg)}  logical-exact: {ok}/{len(reg)}")
    print(f"  PHYSICAL image byte-match: {match}/{n} ({100*match//n}%)")
    if notes:
        print("  builder logical mismatches:")
        print("\n".join(f'    {x}' for x in notes))
    return match, n, ok, len(reg)


def reconstruct(disk_label):
    """Generalized First-Disks overlay: build+overlay every registered fork for
    `disk_label`, then confirm the whole image stays byte-identical.

    Mirrors check()'s per-file contract (build -> len==EOF -> logical-exact vs
    the ORIGINAL fork BEFORE overlay -> overlay only a byte-exact build), but is
    disk-agnostic and does NOT touch Disk-2's MANIFEST/catalog inventory gate
    (that is diskmanifest/manifestcheck's job).  Returns (match, n, ok, total).

    HFS Disk 7 routes to reconstruct_hfs() above (main() dispatches on the
    label — the ProDOS Volume path below cannot read an HFS image)."""
    disk_path = f'{DISKS}/{disk_label}'
    orig = open(disk_path, 'rb').read()
    buf = bytearray(orig)
    vol = Volume(buf)
    entries = dict(_walk(vol, '/' + vol.name))
    reg = DISK_BUILDER_REGISTRY.get(disk_label, {})
    reg_items = list(_iter_registry(reg))          # (path, fork, builder)*
    total = len(reg_items)

    ok = 0
    notes = []
    for path, fork, builder in reg_items:
        if path not in entries:
            notes.append(f'{path}: not on disk (stale registry entry)')
            continue
        f = DiskFile(path, entries[path], vol)
        try:
            content = builder()
        except Exception as e:                             # noqa: BLE001
            notes.append(f'{path}: builder raised {type(e).__name__}: {e}')
            continue
        eof = f.rsrc_eof if fork == 'rsrc' else f.data_eof
        if len(content) != eof:
            notes.append(f'{path}: build {len(content)}B != {fork} EOF {eof}')
            continue
        original = vol.read_file(path, fork=fork)          # pre-overlay compare
        if content != original:
            notes.append(f'{path}: logical ({fork}) differs at '
                         f'{_first_diff(content, original)}')
            continue
        (overlay_rsrc if fork == 'rsrc' else overlay)(vol, f, content)
        ok += 1

    match, n = byte_match(bytes(buf), orig)
    print(f"{disk_label}: {vol.name}  {vol.total_blocks} blocks")
    print(f"  builders wired: {total}  logical-exact: {ok}/{total}")
    print(f"  PHYSICAL image byte-match: {match}/{n} ({100*match//n}%)")
    if notes:
        print("  builder logical mismatches:")
        print("\n".join(f'    {x}' for x in notes))
    return match, n, ok, total


def build_and_overlay(vol, f):
    """The Phase-2 builder contract for one manifest BUILD file. Returns
    (built_ok, note)."""
    try:
        content = SOURCE_BUILDERS[f.path]()
    except Exception as e:                             # noqa: BLE001
        return False, f'builder raised {type(e).__name__}: {e}'
    if len(content) != f.data_eof:
        return False, f'len {len(content)} != EOF {f.data_eof}'
    original = vol.read_file(f.path)                    # logical compare (pre-overlay)
    if content != original:
        # Contract step 6 requires the overlaid image to stay byte-identical, so a
        # non-exact build is NOT overlaid (that would make the image worse than
        # substitution). It is reported as a residual worklist item instead.
        return False, f'logical differs at {_first_diff(content, original)}'
    overlay(vol, f, content)                            # only a byte-exact build
    return True, 'logical-exact'


def build_and_overlay_rsrc(vol, f):
    """The REZ-category analogue of `build_and_overlay()`: builds and
    overlays a RESOURCE fork instead of a data fork (see `REZ_BUILDERS`).
    Same contract otherwise: only a byte-exact build is overlaid."""
    try:
        content = REZ_BUILDERS[f.path]()
    except Exception as e:                             # noqa: BLE001
        return False, f'rez builder raised {type(e).__name__}: {e}'
    if len(content) != f.rsrc_eof:
        return False, f'len {len(content)} != rsrc EOF {f.rsrc_eof}'
    original = vol.read_file(f.path, fork='rsrc')       # logical compare (pre-overlay)
    if content != original:
        return False, f'logical (rsrc) differs at {_first_diff(content, original)}'
    overlay_rsrc(vol, f, content)                       # only a byte-exact build
    return True, 'logical-exact (rsrc)'


def _first_diff(a, b):
    d = first_diff(a, b)
    if d is not None and d < min(len(a), len(b)):
        return hex(d)
    return f'len {len(a)} vs {len(b)}'


def check(disk_path=SYSTEM_DISK, verbose=False, min_built=0):
    orig = open(disk_path, 'rb').read()
    buf = bytearray(orig)
    vol = Volume(buf)
    files = catalog_disk(vol)

    from collections import Counter
    own = Counter(f.owner for f in files)
    data_total = sum(f.data_eof for f in files)
    rsrc_total = sum(f.rsrc_eof for f in files)
    build_data = sum(f.data_eof for f in files if f.owner == BUILD)

    built_bytes = built_ok = built_logical = 0
    notes = []
    for f in files:
        if f.owner == BUILD and f.path in SOURCE_BUILDERS:
            ok, note = build_and_overlay(vol, f)
            built_ok += 1
            if ok:                                       # source-built AND byte-exact
                built_logical += 1
                built_bytes += f.data_eof
            else:
                notes.append(f'    {f.path}: {note}')
        if f.owner == REZ and f.path in REZ_BUILDERS:
            ok, note = build_and_overlay_rsrc(vol, f)
            built_ok += 1
            if ok:                                       # source-built AND byte-exact
                built_logical += 1
                built_bytes += f.rsrc_eof
            else:
                notes.append(f'    {f.path}: {note}')
        # A dual-fork REZ file (e.g. EasyMount: resource fork via Rez AND a
        # real 65816 data fork) can ALSO have a data-fork SOURCE_BUILDERS
        # entry -- independent of (not `elif`) the rsrc branch above, so
        # both forks of the same file are attempted. Additive: no BUILD- or
        # REZ-owned file loses coverage; this only adds a third case no
        # prior file could hit (a REZ file's path was never also a
        # SOURCE_BUILDERS key before).
        if f.owner == REZ and f.path in SOURCE_BUILDERS:
            ok, note = build_and_overlay(vol, f)
            built_ok += 1
            if ok:
                built_logical += 1
                built_bytes += f.data_eof
            else:
                notes.append(f'    {f.path}: {note}')

    recon = bytes(buf)
    match, n = byte_match(recon, orig)

    n_wireable = (own[BUILD]
                  + sum(1 for f in files if f.owner == REZ and f.path in REZ_BUILDERS)
                  + sum(1 for f in files if f.owner == REZ and f.path in SOURCE_BUILDERS))
    print(f"{os.path.basename(disk_path)}: {vol.name}  {vol.total_blocks} blocks")
    print(f"  files: {len(files)}  |  build:{own[BUILD]} rez:{own[REZ]} "
          f"substitute:{own[SUBSTITUTE]} oos:{own[OOS]}")
    print(f"  logical bytes:  data-fork {data_total}  resource-fork {rsrc_total}")
    print(f"  source-buildable (BUILD data-fork): {build_data} of {data_total} "
          f"({100*build_data//data_total}%)")
    print(f"  builders wired: {built_ok}/{n_wireable}  "
          f"logical-exact: {built_logical}/{built_ok}  "
          f"built-bytes covered: {built_bytes}")
    print(f"  PHYSICAL image byte-match: {match}/{n} ({100*match//n}%)")
    if notes:
        print("  builder logical mismatches (physical match may still be 100%):")
        print("\n".join(notes))
    if verbose:
        for f in sorted(files, key=lambda x: (x.owner, x.path)):
            w = ' [built]' if (f.path in SOURCE_BUILDERS or f.path in REZ_BUILDERS) else ''
            print(f"    {f.owner:10} ${f.type:02X} d={f.data_eof:>7} "
                  f"r={f.rsrc_eof:>6} {'+rsrc' if f.has_rsrc else '     '} "
                  f"sp={len(f.sparse_idx)} {f.path}{w}")

    if min_built and built_bytes < min_built:
        raise SystemExit(f"diskcheck: built-bytes {built_bytes} < required {min_built}")
    return match, n


def selftest(disk_path=SYSTEM_DISK):
    """Prove the harness + overlay are byte-clean (no builders needed)."""
    orig = open(disk_path, 'rb').read()
    buf = bytearray(orig)
    vol = Volume(buf)
    assert bytes(buf) == orig, "no-op round-trip not byte-identical"
    print("  no-op round-trip: byte-identical  OK")
    files = catalog_disk(vol)
    n = 0
    for f in files:
        if f.owner != BUILD:
            continue
        overlay(vol, f, vol.read_file(f.path))   # original content -> must stay identical
        n += 1
    ok = bytes(buf) == orig
    print(f"  overlay {n} BUILD files with original content: "
          f"{'byte-identical  OK' if ok else 'DIFFERS (overlay not clean!)'}")

    nr = 0
    for f in files:
        if f.owner != REZ or not f.has_rsrc:
            continue
        overlay_rsrc(vol, f, vol.read_file(f.path, fork='rsrc'))  # must stay identical
        nr += 1
    ok_rsrc = bytes(buf) == orig
    print(f"  overlay_rsrc {nr} REZ files with original resource-fork content: "
          f"{'byte-identical  OK' if ok_rsrc else 'DIFFERS (overlay_rsrc not clean!)'}")
    return ok and ok_rsrc


def main():
    if '--selftest' in sys.argv:
        sys.exit(0 if selftest() else 1)
    if '--disk' in sys.argv:                # First-Disks generalized overlay
        label = sys.argv[sys.argv.index('--disk') + 1]
        recon = reconstruct_hfs if label.startswith('Disk 7') else reconstruct
        match, n, ok, total = recon(label)
        # Exit status is a hard signal (adversarial-review finding #1: the
        # physical result was printed but discarded, so a corrupted overlay
        # could pass as long as the pre-overlay logical compare succeeded).
        sys.exit(0 if (match == n and ok == total) else 1)
    mb = 0
    if '--min-built' in sys.argv:
        mb = int(sys.argv[sys.argv.index('--min-built') + 1])
    match, n = check(verbose=('-v' in sys.argv or '--verbose' in sys.argv),
                     min_built=mb)
    sys.exit(0 if match == n else 1)


if __name__ == '__main__':
    main()
