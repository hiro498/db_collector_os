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


def get_adapter(name: str) -> Adapter:
    if name not in _REGISTRY:
        # Make sure built-in sample adapters are registered.
        from . import sample_official_site, sample_local_business, sample_person, sample_api  # noqa: F401

    if name not in _REGISTRY:
        raise KeyError(f"Unknown adapter: {name!r}. Registered: {sorted(_REGISTRY)}")
    return _REGISTRY[name]()


def list_adapters() -> list[str]:
    from . import sample_official_site, sample_local_business, sample_person, sample_api  # noqa: F401

    return sorted(_REGISTRY)
