"""CORE/VERTICAL extension point (spec section 4).

CORE (crawler/parser/page_classifier/keyword/link_analyzer/monetization)
must never hardcode a genre-specific dictionary or entity. A vertical adds
one by implementing `VerticalProfile` and registering it under a name; CORE
only ever sees the "general" profile unless a caller explicitly asks for a
different one by name.

No genre-specific vertical ships in this P0 -- only the extension point and
the always-available "general" no-op profile.
"""

from __future__ import annotations

from typing import Protocol


class VerticalProfile(Protocol):
    """A vertical may extend keyword modifiers/brand terms and provide its
    own entity dictionary; every method has a safe empty-set default so a
    missing/undeveloped vertical never breaks CORE.
    """

    name: str

    def extra_modifier_terms(self) -> dict[str, list[str]]:
        """Additional {modifier_key: [trigger terms]} entries, merged on top
        of keyword.modifiers.MODIFIER_TERMS."""
        ...

    def brand_terms(self) -> set[str]:
        """Known brand/service names for this vertical, used by
        keyword.normalizer's branded_type classification."""
        ...


class GeneralVertical:
    name = "general"

    def extra_modifier_terms(self) -> dict[str, list[str]]:
        return {}

    def brand_terms(self) -> set[str]:
        return set()


_REGISTRY: dict[str, VerticalProfile] = {"general": GeneralVertical()}


def register_vertical(profile: VerticalProfile) -> None:
    _REGISTRY[profile.name] = profile


def get_vertical(name: str | None) -> VerticalProfile:
    return _REGISTRY.get(name or "general", _REGISTRY["general"])
