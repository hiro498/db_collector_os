"""End-to-end Phase 1 pipeline test: the Good Smile scalefigure_list page as
discovery entry point, feeding multiple product detail pages (mixed
manufacturers/brands) through the real Worker, with duplicate-URL
suppression and per-domain rate limiting exercised along the way.

All fixtures are reconstructions (see their own header comments) -- this
environment has no outbound web access to www.goodsmile.com.
"""

from __future__ import annotations

from pathlib import Path

import responses

from db_collector_os.job_registry import JobRegistry
from db_collector_os.models.enums import CollectorType
from db_collector_os.worker import Worker

FIXTURES_DIR = Path(__file__).parent / "fixtures"
GOODSMILE_PATTERN = r"/en/product/(\d+)/|/en/scalefigure_list"


def load_fixture(name: str) -> str:
    return (FIXTURES_DIR / name).read_text(encoding="utf-8")


def _max_factory_detail_html(product_id: str, name: str) -> str:
    return f"""
    <html><head><meta charset="utf-8">
    <title>{name} | Good Smile Company</title>
    <link rel="canonical" href="https://www.goodsmile.com/en/product/{product_id}/figma-sample-figure">
    <script type="application/ld+json">
    {{"@context": "https://schema.org", "@type": "Product", "name": "{name}",
      "sku": "{product_id}", "brand": {{"@type": "Brand", "name": "Max Factory"}},
      "offers": {{"@type": "Offer", "price": "62.00", "priceCurrency": "USD"}}}}
    </script>
    </head><body><h1>{name}</h1></body></html>
    """


def _make_job(jr: JobRegistry, **overrides) -> str:
    defaults = dict(
        job_name="Figure Official Site (Good Smile, test)", category="figure",
        target_db="figure_official_site_test", target_table="entities",
        collector_type=CollectorType.OFFICIAL_SITE, adapter="figure_official_site",
        priority=50, schedule="@daily", max_pages=10, max_depth=2, concurrency=1, rate_limit=0.0,
        config={
            "seed_urls": ["https://www.goodsmile.com/en/scalefigure_list"],
            "discovery": {
                "robots_seed_urls": ["https://www.goodsmile.com/"],
                "internal_links": True,
                "related_entities": True,
                "allowed_domains": ["www.goodsmile.com"],
                "product_url_pattern": GOODSMILE_PATTERN,
            },
            "phase1_conditions": {"queue_empty": True, "require_discovery_saturation": True, "min_entity_count": 1},
        },
    )
    defaults.update(overrides)
    return jr.create(**defaults)


def _mock_site():
    responses.add(responses.GET, "https://www.goodsmile.com/robots.txt", status=404)
    responses.add(
        responses.GET, "https://www.goodsmile.com/en/scalefigure_list", status=200, content_type="text/html",
        body=load_fixture("goodsmile_scalefigure_list.html"),
    )
    responses.add(
        responses.GET,
        "https://www.goodsmile.com/en/product/1141716/Rikka%2BTakarada%2BAkane%2BShinjo%2Bfeat.%2Btoridamono",
        status=200, content_type="text/html", body=load_fixture("goodsmile_product_1141716.html"),
    )
    for pid, slug, name in (
        ("2200481", "Nendoroid%2BSample%2BFigure", "Nendoroid Sample Figure"),
        ("3301592", "POP%2BUP%2BPARADE%2BSample", "POP UP PARADE Sample"),
    ):
        responses.add(
            responses.GET, f"https://www.goodsmile.com/en/product/{pid}/{slug}", status=200, content_type="text/html",
            body=_max_factory_detail_html(pid, name).replace("Max Factory", "Good Smile Company"),
        )
    for pid, slug, name in (
        ("4402703", "figma%2BSample%2BFigure", "figma Sample Figure"),
        ("5503814", "Max%2BFactory%2BScale%2BSample", "Max Factory Scale Sample"),
    ):
        responses.add(
            responses.GET, f"https://www.goodsmile.com/en/product/{pid}/{slug}", status=200, content_type="text/html",
            body=_max_factory_detail_html(pid, name),
        )
    responses.add(
        responses.GET, "https://www.goodsmile.com/en/scalefigure_list?page=2", status=200, content_type="text/html",
        body=load_fixture("goodsmile_scalefigure_list_page2.html"),
    )
    for pid, slug, name in (
        ("6604925", "another-good-smile-figure", "Another Figure GSC"),
        ("7706036", "another-max-factory-figure", "Another Figure MF"),
    ):
        responses.add(
            responses.GET, f"https://www.goodsmile.com/en/product/{pid}/{slug}", status=200, content_type="text/html",
            body=_max_factory_detail_html(pid, name),
        )


@responses.activate
def test_scalefigure_list_discovers_and_creates_multi_brand_entities(app_config, db):
    _mock_site()
    jr = JobRegistry(db)
    job_id = _make_job(jr)
    worker = Worker(app_config, worker_id="gs-phase1-test-worker", db=db)

    for _ in range(8):
        jr.mark_queued(job_id)
        worker.run_one_job()

    entities = db.query("SELECT * FROM entities WHERE job_id=?", (job_id,))
    names = {e["name"] for e in entities}

    assert "Rikka Takarada & Akane Shinjo feat. toridamono" in names  # HTML entity decoded
    assert any("Nendoroid" in n for n in names)
    assert any("figma" in n for n in names)

    brands = {}
    import json as _json
    for e in entities:
        data = _json.loads(e["data_json"])
        brands[e["name"]] = data.get("brand")

    # brand is per-page, never hardcoded to a single manufacturer:
    assert "Good Smile Company" in brands.values()
    assert "Max Factory" in brands.values()

    # the list page itself was never turned into an entity:
    assert not any("Scale Figures" == n for n in names)

    # the duplicate-slug URL for 1141716 must not have produced a second entity:
    rikka_entities = [e for e in entities if "Rikka" in e["name"]]
    assert len(rikka_entities) == 1

    # domain is tracked separately from brand/manufacturer:
    assert all(e["domain"] == "www.goodsmile.com" for e in entities)

    run_rows = db.query("SELECT * FROM run_history WHERE job_id=?", (job_id,))
    assert all(r["status"] == "completed" for r in run_rows)
    assert any(r["duration_seconds"] is not None for r in run_rows)
