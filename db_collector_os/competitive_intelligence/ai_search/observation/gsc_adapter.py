"""Google Search Console adapter -- interface skeleton only (spec: "GSC
連携はこのフェーズではスケルトンのみ; 実OAuth接続は行わない").

The only way GSC data enters this codebase in PHASE 13 is a manually
exported CSV/JSON file through ``importer.import_observation_file(...,
observation_type="gsc")``, which talks to ``GscObservationRepository``
directly and does not go through this module at all.

This class exists purely to name the shape a future real GSC OAuth
integration would have to implement, so that call sites written against it
now do not need to change later. Calling ``fetch`` raises
``NotImplementedError`` unconditionally -- there is no fake data path and
no silent fallback to another provider.
"""

from __future__ import annotations

from .providers import ProviderResult


class GscApiAdapter:
    """Placeholder for a real Search Console API (OAuth) integration.
    Not implemented in PHASE 13 -- see module docstring."""

    name = "gsc_api"

    def __init__(self, *_args, **_kwargs) -> None:
        pass

    def fetch(self, query: str, country: str, language: str, device: str) -> ProviderResult:
        raise NotImplementedError(
            "GscApiAdapter.fetch is a PHASE 13 interface skeleton only -- no GSC OAuth/API integration "
            "exists in this codebase. Import GSC data offline via "
            "`ci observation import <file> --type gsc` instead."
        )
