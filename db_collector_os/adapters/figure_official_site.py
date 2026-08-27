"""Production adapter: 美少女フィギュア公式メーカーDB (bishoujo figure official
manufacturer product DB) -- the FIRST_PRODUCTION_DB for DB Collector OS.

Design notes (see docs/first_production_db.md for the full rationale):

- This targets `collector_type: official_site`, driven entirely by
  schema.org `Product` JSON-LD (the same open, vendor-neutral structure
  `sample_official_site` already validated) -- no site-specific scraping
  logic, so the same adapter should generalize to other manufacturer
  product catalogs (tires/wheels/swimwear/...) with only a Job config
  change, as the project's "one core + adapter + job" design intends.
- A real manufacturer's catalog also serves plain category/listing/nav
  pages that internal-link discovery will inevitably enqueue alongside
  real product detail pages. Rather than sending every one of those to the
  Review Queue as "missing required field" noise, a page with no `Product`
  JSON-LD at all is treated as a confirmed non-entity page and skipped
  silently (see `ExtractedRecord.skip`). A page that *does* carry `Product`
  JSON-LD but is missing the product name is still routed to review --
  that is a real data-quality problem worth a human's attention.
- External identifier preference order (used for dedup fingerprinting via
  the existing Deduplicator): GTIN (13/12/14/8) > MPN > SKU > a site's own
  `product_master_code` (see below). GTIN is the closest thing to a
  universal, cross-retailer stable product identifier; SKU/product code
  alone are only guaranteed unique within one manufacturer's own site.
- schema.org `Product` JSON-LD is always the primary/authoritative source.
  Where a field it would normally carry is missing, this adapter falls
  back to the page's `dataLayer` (GA4 Enhanced Ecommerce convention --
  item_id/item_name/item_brand/item_category/item_category2/price are
  GA4's own standard parameter names, not something specific to any one
  site) for: brand, series/category, price, a stable product code, and one
  field JSON-LD's Product schema has no equivalent for at all --
  `reservation_deadline` (common for pre-order figures). See
  extraction/datalayer.py for the (intentionally conservative -- strict-
  JSON-only) parser.
"""

from __future__ import annotations

from typing import Any

from ..extraction.datalayer import extract_data_layer_items
from .base import Adapter, ExtractedRecord
from .registry import register_adapter

_GTIN_KEYS = ("gtin13", "gtin14", "gtin12", "gtin8", "gtin")


@register_adapter("figure_official_site")
class FigureOfficialSiteAdapter(Adapter):
    name = "figure_official_site"
    entity_type = "figure"
    required_fields = ("name",)

    def extract(self, common: dict[str, Any], url: str, raw_html: str | None) -> ExtractedRecord:
        product_block = _find_product(common.get("json_ld", []))

        if product_block is None:
            # No Product structured data on this page at all -- almost
            # certainly a category/listing/navigation/boilerplate page
            # reached via internal-link discovery, not a figure itself.
            return ExtractedRecord(skip=True, skip_reason="no schema.org Product JSON-LD on page")

        # Fallback source, used only for fields JSON-LD left empty (see the
        # class docstring): a merged view of every dataLayer ecommerce item
        # found on the page. Never overrides a JSON-LD-derived value.
        dl = _merge_data_layer_items(extract_data_layer_items(raw_html or ""))

        name = _clean_str(product_block.get("name")) or common.get("name") or _clean_str(dl.get("item_name"))

        brand_obj = product_block.get("brand")
        brand = _clean_str(brand_obj.get("name")) if isinstance(brand_obj, dict) else _clean_str(brand_obj)
        brand = brand or _clean_str(dl.get("item_brand"))

        manufacturer_obj = product_block.get("manufacturer")
        manufacturer = (
            _clean_str(manufacturer_obj.get("name")) if isinstance(manufacturer_obj, dict) else _clean_str(manufacturer_obj)
        )

        # schema.org `category` is the closest standard field to a figure
        # "series" (e.g. the anime/game franchise the figure belongs to).
        # GA4's item_category2 is typically the more specific of the two
        # dataLayer category levels, so it's preferred as the fallback.
        series = _clean_str(product_block.get("category")) or _clean_str(dl.get("item_category2")) or _clean_str(dl.get("item_category"))
        category_l1 = _clean_str(dl.get("item_category"))
        category_l2 = _clean_str(dl.get("item_category2"))

        scale = _clean_str(product_block.get("size")) or _extract_scale_hint(name)

        sku = _clean_str(product_block.get("sku"))
        mpn = _clean_str(product_block.get("mpn"))
        gtin = next((_clean_str(product_block.get(k)) for k in _GTIN_KEYS if _clean_str(product_block.get(k))), None)
        product_master_code = _clean_str(dl.get("product_master_code"))
        external_id = gtin or mpn or sku or product_master_code

        offers = product_block.get("offers")
        if isinstance(offers, list):
            offers = offers[0] if offers else None
        offers = offers if isinstance(offers, dict) else {}
        price = _clean_str(offers.get("price")) or _clean_str(dl.get("price"))
        currency = _clean_str(offers.get("priceCurrency"))
        availability = _clean_str(offers.get("availability"))

        release_date = _clean_str(product_block.get("releaseDate"))
        # No schema.org Product equivalent at all -- dataLayer-only field,
        # common for pre-order figures (the cutoff date to place an order).
        reservation_deadline = _clean_str(dl.get("reservation_deadline"))

        images = product_block.get("image")
        if isinstance(images, str):
            images = [images]
        if not images and dl.get("image_url"):
            images = [dl["image_url"]]
        if not images:
            images = common.get("image_urls", [])[:5]

        record = ExtractedRecord(
            name=name,
            entity_type=self.entity_type,
            canonical_url=common.get("canonical_url") or url,
            external_id=external_id,
            confidence=0.8,
            fields={
                "brand": brand,
                "manufacturer": manufacturer,
                "series": series,
                "category_l1": category_l1,
                "category_l2": category_l2,
                "scale": scale,
                "sku": sku,
                "mpn": mpn,
                "gtin": gtin,
                "product_master_code": product_master_code,
                "price": price,
                "currency": currency,
                "availability": availability,
                "release_date": release_date,
                "reservation_deadline": reservation_deadline,
                "image_urls": images[:5] if images else [],
            },
        )
        if not record.name:
            record.missing_required = ["name"]
        return record


def _merge_data_layer_items(items: list[dict[str, Any]]) -> dict[str, Any]:
    """A page can push several dataLayer events (page_view, view_item, ...);
    merge every item found into one flat lookup dict, later items winning on
    key conflicts. Cheap and safe: this is only ever used to fill fields
    JSON-LD left empty, never to override JSON-LD.
    """
    merged: dict[str, Any] = {}
    for item in items:
        merged.update(item)
    return merged


def _find_product(json_ld_blocks: list[dict[str, Any]]) -> dict[str, Any] | None:
    for block in json_ld_blocks:
        if _type_is(block, "Product"):
            return block
    return None


def _type_is(block: dict[str, Any], type_name: str) -> bool:
    t = block.get("@type")
    if isinstance(t, list):
        return type_name in t
    return t == type_name


def _clean_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _extract_scale_hint(name: str | None) -> str | None:
    """Best-effort fallback: figure names conventionally include a scale
    like "1/7" or "1/8" when the manufacturer doesn't populate a structured
    `size`/`additionalProperty` field for it.
    """
    if not name:
        return None
    import re

    m = re.search(r"\b1/(4|6|7|8|10|12)\b", name)
    return m.group(0) if m else None
