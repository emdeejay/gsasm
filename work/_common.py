"""Shared helpers for the living work/ measurement harnesses.

These helpers deliberately preserve each harness's path ordering. Include-path
order is observable because MPW-style includes can shadow each other.
"""
from __future__ import annotations

import hashlib
import json
import os
import struct
import sys
import tempfile
from collections.abc import Iterable


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = os.path.join(ROOT, 'work')


def ensure_repo_on_path(*extra: str) -> None:
    """Prepend the repo root and optional extra paths to sys.path."""
    paths = [ROOT, *extra]
    for path in reversed(paths):
        if path not in sys.path:
            sys.path.insert(0, path)


# --- a2til discovery -------------------------------------------------------
# a2til is the DOWNSTREAM disk-image library (ProDOS / HFS / 2IMG).  It is a
# separate checkout on purpose — filesystems live downstream of the assembler
# and are deliberately never vendored here — so the harnesses have to locate
# it.  ONE mechanism: $A2TIL_PATH is the override; if it is NOT set, we search
#   1. …/a2til       a checkout sitting beside this one
#   2. ~/src/a2til   the historical default
# A candidate counts only if it really holds the package (…/a2til/a2til/).
# An override that is set but wrong is a hard error, never a silent fall-back
# to somebody else's layout — that is the whole point of having an override.
A2TIL_ENV = 'A2TIL_PATH'
A2TIL_HINT = (f'set ${A2TIL_ENV} to an a2til checkout, or place one beside '
              'gsasm (…/a2til/a2til/prodos.py). See README.md / docs/RESULTS.md.')


def a2til_candidates() -> list[str]:
    """Return the a2til search path, in precedence order (unfiltered).

    When the override is set it is the ONLY candidate.
    """
    override = os.environ.get(A2TIL_ENV)
    if override:
        return [os.path.expanduser(override)]
    return [os.path.join(os.path.dirname(ROOT), 'a2til'),
            os.path.expanduser('~/src/a2til')]


def find_a2til() -> str | None:
    """Return the a2til checkout root, or None when it cannot be found."""
    for path in a2til_candidates():
        if os.path.isdir(os.path.join(path, 'a2til')):
            return path
    return None


def a2til_root(who: str = 'gsasm') -> str:
    """Return the a2til checkout root, or exit with a clear diagnostic.

    Exiting here keeps a missing/misconfigured a2til from surfacing as an
    obscure `ModuleNotFoundError: No module named 'a2til'` later on.
    """
    root = find_a2til()
    if not root:
        tried = ', '.join(a2til_candidates())
        why = (f'${A2TIL_ENV} does not point at an a2til checkout'
               if os.environ.get(A2TIL_ENV) else 'a2til not found')
        sys.exit(f'{who}: {why} — {A2TIL_HINT}\n'
                 f'  tried: {tried}')
    return root


def ensure_a2til_on_path(who: str = 'gsasm') -> str:
    """Put the a2til checkout on sys.path (idempotent); return its root."""
    root = a2til_root(who)
    if root not in sys.path:
        sys.path.insert(0, root)
    return root


def work_rel(*parts: str) -> str:
    """Return a repo-relative path under work/."""
    return os.path.join('work', *parts)


def work_abs(*parts: str) -> str:
    """Return an absolute path under work/."""
    return os.path.join(WORK, *parts)


def romsrc_root(*, abs_path: bool = False) -> str:
    """Return the ROM source corpus root."""
    root = work_rel('romsrc', 'GS_ROM')
    return os.path.join(ROOT, root) if abs_path else root


def romsrc_incs(root: str | None = None) -> list[str]:
    """Include order used by the ROM corpus harnesses."""
    root = root or romsrc_root()
    return [work_rel('includes')] + [d for d, _, _ in os.walk(root)]


def gsos_source_root(*, abs_path: bool = False) -> str:
    """Return the GS/OS source corpus root."""
    root = os.path.join('ref', 'GSOS_6', 'IIGS.601.SRC')
    return os.path.join(ROOT, root) if abs_path else root


def gsos_incs(work_include: str | None = None,
              src: str | None = None) -> list[str]:
    """Include order used by GS/OS artifact harnesses."""
    src = src or gsos_source_root()
    cmn = os.path.join(src, 'Common')
    gsos = os.path.join(src, 'GS.OS')
    return [cmn] + [d for d, _, _ in os.walk(gsos)] + [
        work_include or work_rel('includes')]


def gsos_tree_incs(src: str | None = None) -> list[str]:
    """Include order for sources that use every GS.OS subdir only."""
    src = src or gsos_source_root()
    return [d for d, _, _ in os.walk(os.path.join(src, 'GS.OS'))]


def toolbox_root(*, abs_path: bool = False) -> str:
    """Return the GSToolbox source root."""
    return os.path.join(gsos_source_root(abs_path=abs_path), 'GSToolbox')


def firmware_root(*, abs_path: bool = False) -> str:
    """Return the GSFirmware source root."""
    return os.path.join(gsos_source_root(abs_path=abs_path), 'GSFirmware')


def toolbox_incs(tb: str | None = None,
                 fw: str | None = None,
                 work_include: str | None = None) -> list[str]:
    """Include order used by the toolbox harness."""
    tb = tb or toolbox_root()
    fw = fw or firmware_root()
    return ([d for d, _, _ in os.walk(tb)]
            + [d for d, _, _ in os.walk(fw)]
            + [work_include or work_rel('includes')])


def rincludes(*, abs_path: bool = False) -> list[str]:
    """Resource include path used by Rez harnesses.

    Since 2026-07-19 this is the COMMITTED clean-room include
    (`gsasm/rez/include/TypesIIGS.r`, see docs/REZ_TYPES_PLAN.md) — the recovered
    Apple original in gitignored `work/rincludes/` is no longer consulted
    by the Rez pipeline (the gate proves byte-exactness against the new
    include).  `work/rincludes/AIIGSIncludes` remains a separate,
    assembler-side dependency for building embedded code resources
    (easymountcheck.INC_E16)."""
    inc = os.path.join('gsasm', 'rez', 'include')
    return [os.path.join(ROOT, inc) if abs_path else inc]


def sysresources_root(*, abs_path: bool = False) -> str:
    """Return the Sys.Resources source directory."""
    return os.path.join(toolbox_root(abs_path=abs_path), 'Sys.Resources')


def sysresources_rez(*, abs_path: bool = False) -> str:
    """Return the Sys.Resources Rez source path."""
    return os.path.join(sysresources_root(abs_path=abs_path), 'sys.resources.r')


def finder_root(*, abs_path: bool = False) -> str:
    """Return the A.U.G Finder source root."""
    return os.path.join(gsos_source_root(abs_path=abs_path), 'A.U.G', 'Finder')


def easymount_root(*, abs_path: bool = False) -> str:
    """Return the EasyMount source directory."""
    return os.path.join(finder_root(abs_path=abs_path), 'EasyMount')


IGNORED_ASM_OPS = ('pagesize', 'datachk', 'endproc', 'eject', 'writeln',
                   'codechk')


def nonignored_asm_errors(errors: list[str],
                          ignore_ops: tuple[str, ...] = IGNORED_ASM_OPS
                          ) -> list[str]:
    """Return assembler errors not covered by the kernel harness ignore list."""
    return [e for e in errors
            if not any(op in e.lower() for op in ignore_ops)]


def report_nonignored_asm_errors(src_path: str,
                                 errors: list[str],
                                 *,
                                 ignore_ops: tuple[str, ...] = IGNORED_ASM_OPS,
                                 limit: int = 2) -> list[str]:
    """Print the existing kernel-harness error summary and return fatal errors."""
    fatal = nonignored_asm_errors(errors, ignore_ops)
    if fatal:
        name = os.path.basename(src_path)
        print(f'  [{name}] {len(fatal)} non-ignored errors; first {limit}:',
              file=sys.stderr)
        for e in fatal[:limit]:
            print(f'    {e}', file=sys.stderr)
    return fatal


def unique_existing_paths(candidates: Iterable[str]) -> list[str]:
    """Return existing paths from *candidates*, preserving order and de-duping."""
    out: list[str] = []
    seen: set[str] = set()
    for path in candidates:
        if path in seen:
            continue
        seen.add(path)
        if os.path.exists(path):
            out.append(path)
    return out


def first_existing_path(candidates: Iterable[str]) -> str | None:
    """Return the first existing path from *candidates*."""
    paths = unique_existing_paths(candidates)
    return paths[0] if paths else None


def prefixed_file_candidates(directory: str, prefix: str) -> list[str]:
    """Return files in *directory* whose name is *prefix* or starts prefix#."""
    try:
        return [
            os.path.join(directory, fn)
            for fn in os.listdir(directory)
            if fn == prefix or fn.startswith(prefix + '#')
        ]
    except FileNotFoundError:
        return []


def suffixed_file_candidates(directory: str,
                             stem: str,
                             suffixes: Iterable[str]) -> list[str]:
    """Return candidate paths formed as directory/stem+suffix."""
    return [os.path.join(directory, stem + suffix) for suffix in suffixes]


def find_prefixed_file(directory: str, prefix: str) -> str | None:
    """Return the first file in *directory* whose name starts with *prefix*."""
    try:
        for fn in os.listdir(directory):
            if fn.startswith(prefix):
                return os.path.join(directory, fn)
    except FileNotFoundError:
        pass
    return None


def byte_match(mine: bytes, golden: bytes) -> tuple[int, int]:
    """Return (matching_bytes, compared_len) over the common byte range."""
    n = min(len(mine), len(golden))
    return sum(1 for i in range(n) if mine[i] == golden[i]), n


def byte_match_against_golden_len(mine: bytes, golden: bytes) -> tuple[int, int]:
    """Return matching common bytes, reporting the golden length as total."""
    return sum(1 for a, b in zip(mine, golden) if a == b), len(golden)


def first_diff(a: bytes, b: bytes) -> int | None:
    """Return the first differing offset, or the common length on size mismatch."""
    n = min(len(a), len(b))
    for i in range(n):
        if a[i] != b[i]:
            return i
    return None if len(a) == len(b) else n


def mismatch_offsets(a: bytes, b: bytes) -> list[int]:
    """Return differing offsets over the common byte range."""
    return [i for i in range(min(len(a), len(b))) if a[i] != b[i]]


def gate_result(**metrics: int | tuple[int, int]) -> int:
    """Return the process exit status for a gate-invoked check script.

    Call this as the LAST thing a check's ``__main__`` does, AFTER the headline
    line work/gate.py scrapes has already been printed::

        sys.exit(gate_result(fst_bytes=bad))               # nothing accepted
        sys.exit(gate_result(obj_identical=(bad, 21)))     # 21 accepted

    Each keyword names one metric -- use the name from gate.py's CHECKS table
    when the check feeds one, so the two tables stay greppable together -- and
    its value is that metric's current **bad** count in the check's own unit
    (bytes, forks, modules: whatever this harness tallies), or a
    ``(bad, accepted_bad)`` pair.

    ``accepted_bad`` is the check's ACCEPTED STATE: the known-benign residual
    this harness is expected to carry (e.g. objcheck's 21 cosmetically-different
    but link-identical objects, docs/REFACTORING.md 0).  It is written at the
    call site, beside the comment that explains the residual, deliberately: a
    second ledger of accepted values would be one more copy of a fact that
    already lives in two places.  In particular a check must NOT read
    work/gate_baseline.json to discover it -- that file is gate.py's ledger of
    what the checks reported, so consuming it here would invert the dependency
    and make each check's self-assessment a mirror of the gate's memory instead
    of an independent second signal.

    A zero exit promises: every metric named here is AT its accepted state or
    better (``bad <= accepted_bad``).  It does NOT promise ``bad == 0``, and it
    promises nothing about metrics not named here.
    A nonzero exit means: at least one named metric is WORSE than its accepted
    state -- a real regression.  gate.py's run_check() escalates any nonzero
    exit to a hard abort of the whole gate, so nonzero must mean exactly that,
    never "this run had something interesting in it".

    An IMPROVEMENT (``bad < accepted_bad``) is deliberately NOT a failure here:
    gate.py is where an unexpected improvement gets reported and reviewed
    (docs/REFACTORING.md 0, rule 1), and it cannot report what it never gets to
    parse.  Likewise a SHRINKING corpus (fewer good, no new bad) is gate.py's
    to catch: only it holds the previous good counts.

    Nothing is printed on the success path -- these scripts' stdout is a scraped
    contract (gate.py's CHECKS regexes) and must stay byte-identical.  A failure
    writes one line per regressed metric to stderr, where gate.py's error tail
    picks it up.
    """
    regressed = []
    for name, value in metrics.items():
        bad, accepted = value if isinstance(value, tuple) else (value, 0)
        if bad > accepted:
            regressed.append(f'{name}: bad={bad} exceeds accepted={accepted}')
    for line in regressed:
        print(f'gate_result: REGRESSION {line}', file=sys.stderr)
    return 1 if regressed else 0
# ---------------------------------------------------------------------------
# R10 — opt-in assembly cache for the harness inner loop
# ---------------------------------------------------------------------------
#
# WHAT THIS IS.  kernelcheck/toolcheck/fstcheck/drivercheck (and friends) each
# re-assemble overlapping corpus sources; running three or four of them
# back-to-back on an unchanged tree re-does the same work every time.  This is
# a persistent, cross-process memo of
#
#     omf.emit(asm.assemble(src, incs, **kwargs))  ->  (obj_bytes, a.errors)
#
# stored under work/.cache/ and keyed so that ANY change that can move a byte
# is a miss.
#
# WHY IT IS OFF BY DEFAULT.  A cache that returns a stale object makes the
# golden gate report success for code it never assembled.  That is strictly
# worse than a slow gate, so the accelerant is opt-in (`GSASM_CACHE=1`) and
# `assert_cache_disabled()` hard-fails any baseline-minting run.
#
# THE CORRECTNESS ARGUMENT.  `asm.assemble` + `omf.emit` read nothing from the
# clock, the environment or the network (grep: no os.environ / datetime / time
# / random anywhere in gsasm/, and `Asm.sysdate` is `sysdate or ''` — never a
# live date).  So the emitted OMF is a pure function of exactly four things:
#
#   1. the gsasm package's own code and data files,
#   2. the Python interpreter running it,
#   3. the call arguments,
#   4. the filesystem's answers to the finite set of questions the assembler
#      asks it: every `_find_ci(base, relpath)` include probe, and the content
#      of every file `read_text()` opens.
#
# 1-3 are knowable up front and form the LOOKUP KEY.  4 is only knowable after
# the fact, so a cold run RECORDS it (by wrapping `asm._find_ci` /
# `asm.read_text` for the duration of the call) and a warm run REPLAYS it:
# every recorded probe is re-asked of the real `_find_ci`, and every recorded
# file is re-hashed.  If all the answers are the same, the assembler cannot
# have seen different input.
#
# Recording the probe MISSES is the part that matters.  Include resolution
# searches `include_paths` in order and stops at the first hit, so a file
# *added* ahead of the winner would shadow it while leaving every previously
# read file byte-identical — content hashes alone would happily serve a stale
# object.  The recorded `(base, relpath) -> None` probes turn that into a miss.
# The probes after the winning hit are never recorded, and correctly so: the
# resolver never looked at them, so they cannot change the answer.
#
# FAIL SAFE.  Every failure mode in here — unreadable entry, truncated file,
# bad magic, key mismatch, un-canonicalisable argument, hash mismatch, any
# OSError — falls through to "recompute".  There is no path that guesses.
#
# HOUSEKEEPING.  Entries are never evicted: automatic eviction is one more
# thing that can be wrong, and the whole store is derived data.  Every edit to
# gsasm/ mints a fresh generation of keys (~1 MB per full ROM-corpus sweep),
# so during a long refactor `rm -rf work/.cache` is the maintenance procedure.

_CACHE_ENV = 'GSASM_CACHE'
# Bump on ANY change to the key composition, the recording scheme or the entry
# layout below.  Old entries then simply stop being found.
_CACHE_FORMAT = 1
_CACHE_MAGIC = b'GSASMCACHE\x01'
_CACHE_DIR = os.path.join(WORK, '.cache')


def cache_enabled() -> bool:
    """True when the opt-in assembly cache is switched on (`GSASM_CACHE=1`)."""
    return os.environ.get(_CACHE_ENV, '').strip().lower() in (
        '1', 'true', 'yes', 'on')


def assert_cache_disabled(context: str) -> None:
    """Hard-fail if the assembly cache is on during a baseline-minting run.

    Deliberately raises AssertionError directly rather than using the `assert`
    statement: `python3 -O` strips `assert`, and this interlock must not be
    strippable.  A blessed fixture or a rewritten gate baseline is a permanent
    claim about what gsasm emits; it may only ever be minted from bytes this
    process actually assembled."""
    if cache_enabled():
        raise AssertionError(
            f'{_CACHE_ENV} is set during {context}.  Refusing: baselines and '
            f'blessed fixtures must be minted from freshly assembled bytes, '
            f'never from cached ones.  Unset {_CACHE_ENV} and re-run.')


def cache_dir() -> str:
    """Return the assembly cache directory (work/.cache, gitignored)."""
    return _CACHE_DIR


def _sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha_file(path: str) -> str | None:
    """Return the sha256 of *path*, or None if it cannot be read."""
    try:
        with open(path, 'rb') as f:
            h = hashlib.sha256()
            while True:
                chunk = f.read(1 << 20)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


_LIB_DIGEST: dict[str, str] = {}


def _lib_digest(pkg_dir: str) -> str:
    """Content digest of every file in the imported gsasm package directory.

    NOT the version string: during a refactor the version is constant while the
    code changes every few minutes, so a version-keyed cache would serve output
    from the previous edit.  NOT mtimes either: a `git checkout` of an older
    revision restores old content with a new mtime, and `touch` bumps an mtime
    with no content change.  Only the bytes cannot lie.

    Keyed on the directory of the *imported* module, so a gsasm installed
    elsewhere on sys.path shadowing the repo copy is a different key rather
    than a silent mix-up.  Data files count too (gsasm/rez/include/*.r feeds
    Rez output), so this hashes everything except Python's own bytecode cache."""
    cached = _LIB_DIGEST.get(pkg_dir)
    if cached is not None:
        return cached
    h = hashlib.sha256()
    entries = []
    for base, dirs, files in os.walk(pkg_dir):
        dirs[:] = sorted(d for d in dirs if d != '__pycache__')
        for fn in sorted(files):
            if fn.endswith(('.pyc', '.pyo')):
                continue
            entries.append(os.path.join(base, fn))
    for path in sorted(entries):
        rel = os.path.relpath(path, pkg_dir)
        sha = _sha_file(path)
        if sha is None:           # unreadable file -> never-matching digest
            return 'unreadable:' + _sha_bytes(os.urandom(32))
        h.update(rel.encode('utf-8') + b'\0' + sha.encode('ascii') + b'\n')
    digest = h.hexdigest()
    _LIB_DIGEST[pkg_dir] = digest
    return digest


def _canon(value):
    """Canonicalise one assemble() argument, or raise ValueError.

    Sets and dicts are sorted (their *iteration* order is not part of the
    assembler's contract, but their contents are).  Anything whose repr carries
    a memory address is refused outright: such a key would differ on every run
    and quietly disable the cache, which is safe but pointless — better to
    bypass loudly than to pretend."""
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, (set, frozenset)):
        return ['set'] + sorted(_canon(v) for v in value)
    if isinstance(value, dict):
        return ['dict'] + sorted([str(k), _canon(v)] for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return ['seq'] + [_canon(v) for v in value]
    text = repr(value)
    if ' at 0x' in text or ' object ' in text:
        raise ValueError(f'un-canonicalisable assemble() argument: {text}')
    return ['repr', text]


def _cache_key(src_path: str, include_paths, kwargs: dict,
               pkg_dir: str) -> tuple[str, str] | None:
    """Return (key_hex, canonical_args_json), or None to bypass the cache."""
    try:
        blob = {
            'fmt': _CACHE_FORMAT,
            # A different interpreter is a different program.  gsasm is pure
            # Python, but "bytes from a different Python" is not a claim this
            # cache is entitled to make on this one's behalf.
            'py': f'{sys.implementation.name} {sys.version}',
            'pkg_dir': os.path.abspath(pkg_dir),
            'lib': _lib_digest(pkg_dir),
            'emit': 'omf.emit',
            'src': os.path.abspath(src_path),
            # ORDER-SENSITIVE on purpose: include-path order IS behaviour here
            # (docs/REFACTORING.md §4), so a reordered sweep must be a miss.
            'incs': [os.path.abspath(p) for p in include_paths],
            'kwargs': sorted([k, _canon(v)] for k, v in kwargs.items()),
        }
        args = json.dumps(blob, sort_keys=True, separators=(',', ':'))
    except (ValueError, TypeError):
        return None
    return _sha_bytes(args.encode('utf-8')), args


def _entry_path(key: str) -> str:
    return os.path.join(_CACHE_DIR, key[:2], key + '.bin')


def _read_entry(path: str, key: str, args: str):
    """Return (obj_bytes, errors, meta) for a structurally valid entry, else None."""
    try:
        with open(path, 'rb') as f:
            raw = f.read()
    except OSError:
        return None
    head = len(_CACHE_MAGIC) + 4
    if len(raw) < head or raw[:len(_CACHE_MAGIC)] != _CACHE_MAGIC:
        return None
    (meta_len,) = struct.unpack('>I', raw[len(_CACHE_MAGIC):head])
    if len(raw) < head + meta_len:
        return None
    try:
        meta = json.loads(raw[head:head + meta_len].decode('utf-8'))
    except (ValueError, UnicodeDecodeError):
        return None
    obj = raw[head + meta_len:]
    # Belt and braces: the key is already in the filename, but an entry that
    # does not itself agree it is this key (collision, hand-edit, half-written
    # file, a stray copy) is not evidence of anything.
    if (not isinstance(meta, dict) or meta.get('key') != key
            or meta.get('args') != args
            or meta.get('fmt') != _CACHE_FORMAT
            or meta.get('obj_len') != len(obj)
            or meta.get('obj_sha') != _sha_bytes(obj)):
        return None
    if not isinstance(meta.get('probes'), list) or not isinstance(
            meta.get('files'), list):
        return None
    errors = meta.get('errors')
    if not isinstance(errors, list) or not all(
            isinstance(e, str) for e in errors):
        return None
    return obj, errors, meta


def _deps_still_valid(meta: dict, asm_mod) -> bool:
    """Replay the recorded filesystem oracle; True only if nothing moved."""
    try:
        for item in meta['files']:
            if not (isinstance(item, list) and len(item) == 2):
                return False
            path, sha = item
            if _sha_file(path) != sha:
                return False
        for item in meta['probes']:
            if not (isinstance(item, list) and len(item) == 3):
                return False
            base, rel, result = item
            if asm_mod._find_ci(base, rel) != result:
                return False
    except (KeyError, TypeError, OSError):
        return False
    return True


class _OracleRecorder:
    """Record every include probe and every file read for the wrapped call.

    Installed only while the cache is enabled, and only around the one
    `assemble()` call it is recording; the originals are restored on the way
    out even if the assembly raises."""

    def __init__(self, asm_mod):
        self._mod = asm_mod
        self.probes: dict[tuple[str, str], str | None] = {}
        self.files: dict[str, str | None] = {}

    def __enter__(self):
        mod = self._mod
        self._find_ci, self._read_text = mod._find_ci, mod.read_text
        real_find, real_read = self._find_ci, self._read_text
        probes, files = self.probes, self.files

        def find_ci(base, relpath):
            result = real_find(base, relpath)
            probes[(base, relpath)] = result
            return result

        def read_text(path):
            if path not in files:
                files[path] = _sha_file(path)
            return real_read(path)

        mod._find_ci, mod.read_text = find_ci, read_text
        return self

    def __exit__(self, *exc):
        self._mod._find_ci = self._find_ci
        self._mod.read_text = self._read_text
        return False

    def safe_to_store(self) -> bool:
        """True only if every file read is readable AND still byte-identical.

        The re-hash closes a narrow but real hole: a source edited *while* the
        assembly was running would otherwise be recorded under its NEW hash
        against an object built from its OLD text, and every later run would
        hit that entry and serve bytes gsasm never produced.  Re-reading a few
        dozen small files costs microseconds; being wrong forever does not."""
        return all(sha is not None and _sha_file(path) == sha
                   for path, sha in self.files.items())


def _write_entry(path: str, key: str, args: str, meta_extra: dict,
                 obj: bytes) -> None:
    meta = dict(meta_extra)
    meta.update({'fmt': _CACHE_FORMAT, 'key': key, 'args': args,
                 'obj_len': len(obj), 'obj_sha': _sha_bytes(obj)})
    try:
        blob = json.dumps(meta, sort_keys=True,
                          separators=(',', ':')).encode('utf-8')
    except (TypeError, ValueError):
        return                         # not serialisable -> simply do not cache
    payload = _CACHE_MAGIC + struct.pack('>I', len(blob)) + blob + obj
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix='.tmp')
        try:
            with os.fdopen(fd, 'wb') as f:
                f.write(payload)
            os.replace(tmp, path)      # atomic: no reader ever sees a torn entry
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    except OSError:
        pass                           # a cache we cannot write is not fatal


# Per-process counters.  Nothing in the harnesses prints these (gate.py scrapes
# their output and §4 forbids changing it); they exist for the R10 evidence
# scripts and for anyone debugging a suspicious hit rate.
CACHE_STATS = {'hit': 0, 'miss': 0, 'bypass': 0, 'stale': 0}


def cached_assemble_emit(src_path: str, include_paths, **kwargs
                         ) -> tuple[bytes, list[str]]:
    """Return ``(omf.emit(asm.assemble(...)), a.errors)``, cached if enabled.

    With `GSASM_CACHE` unset this is exactly
    ``omf.emit(asm.assemble(src_path, include_paths, **kwargs))`` plus one
    function call — no hashing, no stat, no cache directory, no monkeypatch.

    Returns the OMF bytes and the assembler's error list rather than the `Asm`
    object, because the `Asm` is not reconstructible from a cache entry.  Call
    sites that need the symbol table, the segment list, or anything else off
    the `Asm` must keep calling `asm.assemble` directly — that is a correctness
    boundary, not an oversight.  (Note `omf.emit` also MUTATES the `Asm` it is
    given, so "assemble, emit, then read the Asm" is a third pattern this
    helper deliberately does not serve.)"""
    ensure_repo_on_path()
    from gsasm import asm as _asm_mod
    from gsasm import omf as _omf_mod

    if not cache_enabled():
        a = _asm_mod.assemble(src_path, include_paths, **kwargs)
        return _omf_mod.emit(a), list(a.errors)

    keyed = _cache_key(src_path, include_paths, kwargs,
                       os.path.dirname(os.path.abspath(_asm_mod.__file__)))
    if keyed is None:
        CACHE_STATS['bypass'] += 1
        a = _asm_mod.assemble(src_path, include_paths, **kwargs)
        return _omf_mod.emit(a), list(a.errors)

    key, args = keyed
    path = _entry_path(key)
    entry = _read_entry(path, key, args)
    if entry is not None:
        obj, errors, meta = entry
        if _deps_still_valid(meta, _asm_mod):
            CACHE_STATS['hit'] += 1
            return obj, errors
        CACHE_STATS['stale'] += 1       # key hit, oracle moved -> recompute
    else:
        CACHE_STATS['miss'] += 1

    with _OracleRecorder(_asm_mod) as rec:
        a = _asm_mod.assemble(src_path, include_paths, **kwargs)
        obj = _omf_mod.emit(a)
    errors = list(a.errors)
    if rec.safe_to_store():
        _write_entry(path, key, args, {
            'errors': errors,
            'files': sorted([p, s] for p, s in rec.files.items()),
            # sort on the (base, relpath) pair only: the recorded result is a
            # str-or-None and must never enter the comparison.
            'probes': sorted(([b, r, v] for (b, r), v in rec.probes.items()),
                             key=lambda item: (item[0], item[1])),
        }, obj)
    return obj, errors
