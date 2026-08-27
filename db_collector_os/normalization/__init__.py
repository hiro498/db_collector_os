from .address import normalize_address
from .html_entities import decode_html_entities, decode_html_entities_deep
from .names import normalize_name
from .telephone import normalize_telephone
from .unicode import normalize_unicode
from .url import normalize_url
from .whitespace import normalize_whitespace

__all__ = [
    "decode_html_entities",
    "decode_html_entities_deep",
    "normalize_address",
    "normalize_name",
    "normalize_telephone",
    "normalize_unicode",
    "normalize_url",
    "normalize_whitespace",
]
