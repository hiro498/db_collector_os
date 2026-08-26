from __future__ import annotations

from db_collector_os.deduplication import Deduplicator, compute_fingerprint
from db_collector_os.entities import EntityStore


def test_new_entity_when_no_match(db, job_id):
    dedup = Deduplicator(EntityStore(db))
    decision = dedup.resolve(job_id, "product", name="Widget", normalized_name="widget", domain="example.com")
    assert decision.action == "new"


def test_merge_on_fingerprint_match(db, job_id):
    entities = EntityStore(db)
    dedup = Deduplicator(entities)
    fp = compute_fingerprint("product", normalized_name="widget", domain="example.com")
    entities.create(
        job_id=job_id, entity_type="product", name="Widget", normalized_name="widget",
        canonical_url=None, domain="example.com", address=None, telephone=None,
        external_id=None, fingerprint=fp, data={},
    )
    decision = dedup.resolve(
        job_id, "product", name="Widget", normalized_name="widget", domain="example.com", external_id=None,
    )
    # same normalized_name+domain -> same fingerprint -> merge
    assert decision.action == "merge"


def test_merge_on_canonical_url_match(db, job_id):
    entities = EntityStore(db)
    dedup = Deduplicator(entities)
    entity_id = entities.create(
        job_id=job_id, entity_type="product", name="Widget", normalized_name="widget-a",
        canonical_url="https://example.com/w", domain="example.com", address=None,
        telephone=None, external_id=None, fingerprint="fp-1", data={},
    )
    decision = dedup.resolve(
        job_id, "product", name="Widget (updated title)", normalized_name="widget-b",
        canonical_url="https://example.com/w", domain="example.com",
    )
    assert decision.action == "merge"
    assert decision.entity_id == entity_id


def test_ambiguous_name_match_goes_to_review(db, job_id):
    entities = EntityStore(db)
    dedup = Deduplicator(entities)
    entities.create(
        job_id=job_id, entity_type="local_business", name="Sakura", normalized_name="sakura",
        canonical_url="https://a.example.com/shop", domain="a.example.com", address="Tokyo A",
        telephone="+81312340000", external_id=None, fingerprint="fp-x", data={},
    )
    # Same normalized name, but a different domain and a conflicting address -> ambiguous.
    decision = dedup.resolve(
        job_id, "local_business", name="Sakura", normalized_name="sakura",
        canonical_url="https://b.example.com/shop", domain="b.example.com", address="Osaka B",
    )
    assert decision.action == "review"


def test_external_id_match_wins_over_weaker_signals(db, job_id):
    entities = EntityStore(db)
    dedup = Deduplicator(entities)
    fp = compute_fingerprint("product", external_id="SKU-1")
    entity_id = entities.create(
        job_id=job_id, entity_type="product", name="Widget", normalized_name="widget",
        canonical_url="https://example.com/old-url", domain="example.com", address=None,
        telephone=None, external_id="SKU-1", fingerprint=fp, data={},
    )
    decision = dedup.resolve(
        job_id, "product", name="Widget Renamed", normalized_name="widget-renamed",
        canonical_url="https://example.com/new-url", domain="example.com", external_id="SKU-1",
    )
    assert decision.action == "merge"
    assert decision.entity_id == entity_id
