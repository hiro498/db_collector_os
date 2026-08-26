from ..models.enums import CollectorType
from .api import ApiCollector
from .context import CollectorContext
from .local_business import LocalBusinessCollector
from .official_site import OfficialSiteCollector
from .person import PersonCollector
from .pipeline import BaseCollector, RunOutcome

_COLLECTOR_CLASSES = {
    CollectorType.OFFICIAL_SITE: OfficialSiteCollector,
    CollectorType.LOCAL_BUSINESS: LocalBusinessCollector,
    CollectorType.PERSON: PersonCollector,
    CollectorType.API: ApiCollector,
}


def get_collector(collector_type: str, ctx: CollectorContext) -> BaseCollector:
    cls = _COLLECTOR_CLASSES.get(collector_type, BaseCollector)
    return cls(ctx)


__all__ = [
    "CollectorContext",
    "BaseCollector",
    "RunOutcome",
    "OfficialSiteCollector",
    "LocalBusinessCollector",
    "PersonCollector",
    "ApiCollector",
    "get_collector",
]
