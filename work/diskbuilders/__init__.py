"""diskbuilders — per-category M8 disk-file builders (auto-discovered).

Each sibling module defines ``builders(V) -> {disk_path: callable() -> bytes}``
where ``V`` is the volume prefix (e.g. ``/System.Disk``) and each callable returns
the FULL on-disk file bytes (the ExpressLoad'd OMF / MakeBin output — NOT the
de-ExpressLoad'd code image the *check.py harnesses compare). ``diskcheck.py``
merges them into ``SOURCE_BUILDERS`` and gates each with the builder contract
(len == data-fork EOF; sparse blocks zero; logical == read_file; image identical).

One module per category lets builders be developed in parallel without colliding
on ``diskcheck.py``. A module that raises on import is skipped (partial fleets are
fine); a builder that produces wrong bytes is caught by the contract, not here.
"""
import importlib
import pkgutil


def load(V):
    out = {}
    for info in pkgutil.iter_modules(__path__):
        if info.name.startswith('_'):
            continue
        try:
            mod = importlib.import_module(f'{__name__}.{info.name}')
        except Exception:                    # a broken category shouldn't sink the rest
            continue
        if hasattr(mod, 'builders'):
            try:
                out.update(mod.builders(V))
            except Exception:
                continue
    return out
