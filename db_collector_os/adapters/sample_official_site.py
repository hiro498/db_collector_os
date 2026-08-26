"""Sample official_site adapter: a generic manufacturer/product page adapter
driven by schema.org Product JSON-LD, with an HTML fallback. Works against
any site that publishes Product structured data (tires, wheels, swimwear,
figures, cars, ... per the task's example categories) -- no site-specific
scraping is hard-coded.
"""

from __future__ import annotations

from typing import Any

from .base import Adapter, ExtractedRecord
from .registry import register_adapter


@register_adapter("sample_official_site")
class SampleOfficialSiteAdapter(Adapter):
    name = "sample_official_site"
    entity_type = "product"
    required_fields = ("name",)

    def extract(self, common: dict[str, Any], url: str, raw_html: str | None) -> ExtractedRecord:
        product_block = next(
            (b for b in common.get("json_ld", []) if _type_is(b, "Product")), None
        )

        name = (product_block or {}).get("name") or common.get("name") or common.get("title")
        brand = None
        sku = None
        price = None
        currency = None
        if product_block:
            brand_obj = product_block.get("brand")
            brand = brand_obj.get("name") if isinstance(brand_obj, dict) else brand_obj
            sku = product_block.get("sku") or product_block.get("mpn")
            offers = product_block.get("offers")
            if isinstance(offers, list):
                offers = offers[0] if offers else None
            if isinstance(offers, dict):
                price = offers.get("price")
                currency = offers.get("priceCurrency")

        record = ExtractedRecord(
            name=name,
            entity_type=self.entity_type,
            canonical_url=common.get("canonical_url") or url,
            external_id=sku,
            confidence=0.75 if product_block else 0.5,
            fields={
                "brand": brand,
                "sku": sku,
                "price": price,
                "currency": currency,
                "image_urls": common.get("image_urls", [])[:5],
                "meta_description": common.get("meta_description"),
            },
        )
        if not record.name:
            record.missing_required = ["name"]
        return record


def _type_is(block: dict[str, Any], type_name: str) -> bool:
    t = block.get("@type")
    if isinstance(t, list):
        return type_name in t
    return t == type_name
