"""Prefecture-based discovery: expands a URL/query template across Japan's 47
prefectures. Useful for local_business / person directories that are
organized by region (e.g. https://example.com/area/{pref}/).
"""

from __future__ import annotations

from .base import DiscoveredURL

PREFECTURES = [
    "北海道", "青森県", "岩手県", "宮城県", "秋田県", "山形県", "福島県",
    "茨城県", "栃木県", "群馬県", "埼玉県", "千葉県", "東京都", "神奈川県",
    "新潟県", "富山県", "石川県", "福井県", "山梨県", "長野県", "岐阜県",
    "静岡県", "愛知県", "三重県", "滋賀県", "京都府", "大阪府", "兵庫県",
    "奈良県", "和歌山県", "鳥取県", "島根県", "岡山県", "広島県", "山口県",
    "徳島県", "香川県", "愛媛県", "高知県", "福岡県", "佐賀県", "長崎県",
    "熊本県", "大分県", "宮崎県", "鹿児島県", "沖縄県",
]

PREFECTURE_SLUGS = [
    "hokkaido", "aomori", "iwate", "miyagi", "akita", "yamagata", "fukushima",
    "ibaraki", "tochigi", "gunma", "saitama", "chiba", "tokyo", "kanagawa",
    "niigata", "toyama", "ishikawa", "fukui", "yamanashi", "nagano", "gifu",
    "shizuoka", "aichi", "mie", "shiga", "kyoto", "osaka", "hyogo",
    "nara", "wakayama", "tottori", "shimane", "okayama", "hiroshima", "yamaguchi",
    "tokushima", "kagawa", "ehime", "kochi", "fukuoka", "saga", "nagasaki",
    "kumamoto", "oita", "miyazaki", "kagoshima", "okinawa",
]


def discover_by_prefecture(url_template: str, use_slug: bool = False) -> list[DiscoveredURL]:
    """`url_template` must contain a `{pref}` placeholder,
    e.g. "https://example.com/area/{pref}/".
    """
    values = PREFECTURE_SLUGS if use_slug else PREFECTURES
    found = []
    for value in values:
        if "{pref}" not in url_template:
            break
        url = url_template.format(pref=value)
        found.append(DiscoveredURL(url=url, method="prefecture", confidence=0.6))
    return found
