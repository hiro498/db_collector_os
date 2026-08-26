"""official_site collector: manufacturer / official product DB sites (tires,
wheels, swimwear, figures, cars, ...). Behavior is entirely generic HTML +
JSON-LD crawling -- DB-specific fields come from the Adapter.
"""

from __future__ import annotations

from .pipeline import BaseCollector


class OfficialSiteCollector(BaseCollector):
    pass
