"""Shared helpers for the living work/ measurement harnesses.

These helpers deliberately preserve each harness's path ordering. Include-path
order is observable because MPW-style includes can shadow each other.
"""
from __future__ import annotations

import os
import sys
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
