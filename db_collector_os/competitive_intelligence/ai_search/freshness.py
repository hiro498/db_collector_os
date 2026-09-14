"""Evidence freshness detection (spec section 7). A timestamp alone
("2026/9/10更新") never earns points here -- only evidence that something
measurable actually *changed* does (a review count, a ranking position, a
price, before vs. after). `data_updated_at` (when the underlying data was
last refreshed) is tracked separately from the page's own
published_at/modified_at, since a page can be edited without its
underlying facts changing at all, or vice versa.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .enums import FreshnessEventType

_DATA_UPDATE_PATTERNS = (
    re.compile(r"(?:データ更新日|集計日|調査日|最終更新)\s*[:：]?\s*([0-9]{4}[-/年][0-9]{1,2}[-/月][0-9]{1,2})"),
)
_ARROW_DELTA_RE = re.compile(r"(\d[\d,]*\.?\d*)\s*(?:位|件|人|円|%)?\s*(?:→|->|⇒)\s*(\d[\d,]*\.?\d*)")
_KARA_NI_DELTA_RE = re.compile(
    r"(\d[\d,]*\.?\d*)\s*(位|件|人|円|%)?\s*から\s*(\d[\d,]*\.?\d*)\s*(位|件|人|円|%)?\s*[にへ]"
)
_CONTEXT_WINDOW = 15

_EVENT_TYPE_MARKERS: dict[str, tuple[str, ...]] = {
    FreshnessEventType.RANKING_DELTA: ("位", "ランキング", "順位"),
    FreshnessEventType.REVIEW_DELTA: ("レビュー", "口コミ", "評価件数"),
    FreshnessEventType.PRICE_DELTA: ("円", "価格", "値段"),
    FreshnessEventType.INVENTORY_DELTA: ("在庫",),
    FreshnessEventType.NEW_ITEM_DELTA: ("新作", "新着", "新入荷"),
}


@dataclass
class FreshnessEventCandidate:
    event_type: str
    before_value: str
    after_value: str
    source_text: str
    confidence: float = 0.6


def extract_data_updated_at(text: str) -> str | None:
    if not text:
        return None
    for pattern in _DATA_UPDATE_PATTERNS:
        m = pattern.search(text)
        if m:
            return m.group(1)
    return None


def detect_change_events(text: str) -> list[FreshnessEventCandidate]:
    if not text:
        return []
    events: list[FreshnessEventCandidate] = []
    for m in _ARROW_DELTA_RE.finditer(text):
        window = text[max(0, m.start() - _CONTEXT_WINDOW): m.end() + _CONTEXT_WINDOW]
        events.append(FreshnessEventCandidate(
            _classify_event(window), m.group(1), m.group(2), window, 0.75
        ))
    for m in _KARA_NI_DELTA_RE.finditer(text):
        window = text[max(0, m.start() - _CONTEXT_WINDOW): m.end() + _CONTEXT_WINDOW]
        events.append(FreshnessEventCandidate(
            _classify_event(window), m.group(1), m.group(3), window, 0.7
        ))
    return events


def _classify_event(window: str) -> str:
    for event_type, markers in _EVENT_TYPE_MARKERS.items():
        if any(marker in window for marker in markers):
            return event_type
    return FreshnessEventType.BEFORE_AFTER_TEXT


def freshness_timestamp_score(published_at: str | None, modified_at: str | None, data_updated_at: str | None) -> int:
    """0-100, capped low on purpose: distinct timestamps are a weak signal
    on their own (spec section 7's explicit "date alone is not enough")."""
    distinct = len({v for v in (published_at, modified_at, data_updated_at) if v})
    return min(30, distinct * 15)


def evidence_change_score(events: list[FreshnessEventCandidate]) -> int:
    if not events:
        return 0
    return max(0, min(100, len(events) * 25))


def evidence_freshness_score(timestamp_score: int, change_score: int) -> int:
    """The change signal dominates -- a page with zero demonstrated changes
    caps out well below one that shows even a single meaningful delta."""
    return max(0, min(100, round(timestamp_score * 0.3 + change_score * 0.7)))
