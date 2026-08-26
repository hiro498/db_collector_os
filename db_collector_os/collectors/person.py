"""person collector: public-figure directories (fortune tellers, wrestlers,
idols, K-pop members, cosplayers, ...). Extraction leans on Person structured
data and `sameAs` social links via the Adapter and related-entity discovery.
"""

from __future__ import annotations

from .pipeline import BaseCollector


class PersonCollector(BaseCollector):
    pass
