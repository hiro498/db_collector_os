"""local_business collector: storefronts/venues (fortune-telling parlors,
live houses, love hotels, dance schools, theaters, ...). Discovery leans on
prefecture-based expansion in addition to sitemap/search; extraction leans on
LocalBusiness structured data via the Adapter.
"""

from __future__ import annotations

from .pipeline import BaseCollector


class LocalBusinessCollector(BaseCollector):
    pass
