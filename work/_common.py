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
    """Resource include path used by Rez harnesses."""
    inc = work_rel('rincludes')
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
