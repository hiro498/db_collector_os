-- Adds the column needed for a real "distributed across the body" signal
-- in keyword_scorer.compute_content_score (spec section 22: content
-- importance must weigh in-page frequency, domain-wide rarity, lead
-- position, AND distribution across the whole body -- the last of these
-- needs both where a keyword first AND last appears, not just first).
--
-- Purely additive (new column, nullable, no default-breaking change) and
-- does not touch 0001_init.sql or 0002_competitive_intelligence.sql.
ALTER TABLE ci_keyword_occurrences ADD COLUMN last_position INTEGER;
