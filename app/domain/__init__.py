"""Hermes Web UI domain logic (formerly top-level ``api/`` package)."""
from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path

__path__ = [str(Path(__file__).resolve().parent)]

__all__ = sorted(
    info.name
    for info in pkgutil.iter_modules(__path__)
    if not info.name.startswith("_")
)


def __getattr__(name: str):
    if name in __all__:
        mod = importlib.import_module(f".{name}", __name__)
        globals()[name] = mod
        return mod
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
