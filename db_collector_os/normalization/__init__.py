from .address import normalize_address
from .names import normalize_name
from .telephone import normalize_telephone
from .unicode import normalize_unicode
from .url import normalize_url
from .whitespace import normalize_whitespace

__all__ = [
    "normalize_address",
    "normalize_name",
    "normalize_telephone",
    "normalize_unicode",
    "normalize_url",
    "normalize_whitespace",
]
