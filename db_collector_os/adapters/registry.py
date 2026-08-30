"""Adapter registry: maps the `adapter` name stored on a Job to an Adapter
class. Adding a new DB means writing one adapter module and registering it
here (or importing it before use) -- no core changes required.
"""

from __future__ import annotations

from .base import Adapter

_REGISTRY: dict[str, type[Adapter]] = {}


def register_adapter(name: str):
    def decorator(cls: type[Adapter]) -> type[Adapter]:
        _REGISTRY[name] = cls
        return cls

    return decorator


def _import_builtin_adapters() -> None:
    # Make sure every built-in adapter module registers itself. Importing a
    # module is idempotent, so calling this repeatedly is cheap and safe.
    from . import (  # noqa: F401
        figure_official_site,
        lovehotel_couples,
        sample_api,
        sample_local_business,
        sample_official_site,
        sample_person,
    )


def get_adapter(name: str) -> Adapter:
    if name not in _REGISTRY:
        _import_builtin_adapters()

    if name not in _REGISTRY:
        raise KeyError(f"Unknown adapter: {name!r}. Registered: {sorted(_REGISTRY)}")
    return _REGISTRY[name]()


def list_adapters() -> list[str]:
    _import_builtin_adapters()
    return sorted(_REGISTRY)
