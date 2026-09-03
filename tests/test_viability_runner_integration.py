"""End-to-end Phase 1 -> Phase 2 -> evaluate flow, exercised the same way a
real operator would drive it (generate keywords, import CSV metrics, run
phase1, import CSV SERP results, run phase2, evaluate) -- against the
project's actual default config/viability.yaml so these tests double as a
sanity check that the shipped defaults produce sane GO/NO-GO outcomes.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from db_collector_os.viability.config import load_viability_config
from db_collector_os.viability.keyword_sources.csv_import import CsvKeywordSource
from db_collector_os.viability.runner import EvaluationRunner, Phase1NotPassedError
from db_collector_os.viability.serp_sources.csv_import import CsvSerpSource
from db_collector_os.viability.store import ViabilityStore

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def vconfig():
    return load_viability_config(REPO_ROOT / "config" / "viability.yaml")


def _write_csv(path: Path, header: str, rows: list[str]) -> Path:
    path.write_text(header + "\n" + "\n".join(rows) + "\n", encoding="utf-8")
    return path


def test_demand_gate_blocks_low_volume_theme_from_phase2(db, vconfig):
    runner = EvaluationRunner(db, vconfig)
    idea_id = runner.create_idea("ニッチすぎるテーマ")
    runner.add_keywords_from_generator(idea_id, ["メインKW"], axes={"region": ["A", "B", "C"]})

    metrics_csv = _write_csv(
        Path(db.db_path).parent / "low_metrics.csv",
        "keyword,monthly_search_volume",
        ["メインKW,20"],
    )
    runner.import_keyword_metrics(idea_id, CsvKeywordSource(metrics_csv))
    summary, run_id = runner.run_phase1(idea_id)

    assert summary["phase1_result"] == "FAIL"
    idea = ViabilityStore(db).get_idea(idea_id)
    assert idea["status"] == "no_go"

    with pytest.raises(Phase1NotPassedError):
        runner.import_serp_results(run_id, idea_id, CsvSerpSource.__new__(CsvSerpSource))


def test_full_flow_weak_competition_yields_go(db, vconfig):
    runner = EvaluationRunner(db, vconfig)
    idea_id = runner.create_idea("アクセサリーのオーダーメイド工房", category="handicraft")
    runner.add_keywords_from_generator(
        idea_id,
        ["アクセサリー オーダーメイド"],
        axes={"type": ["指輪", "ネックレス"], "region": ["東京"], "motif": ["スカル", "クロス"]},
    )

    metrics_csv = _write_csv(
        Path(db.db_path).parent / "metrics.csv",
        "keyword,monthly_search_volume",
        [
            "アクセサリー オーダーメイド,880",
            "指輪 アクセサリー オーダーメイド,320",
            "アクセサリー オーダーメイド 指輪,140",
            "ネックレス アクセサリー オーダーメイド,210",
            "アクセサリー オーダーメイド ネックレス,90",
            "東京 アクセサリー オーダーメイド,70",
            "アクセサリー オーダーメイド 東京,40",
            "スカル アクセサリー オーダーメイド,50",
            "アクセサリー オーダーメイド スカル,30",
            "クロス アクセサリー オーダーメイド,40",
            "アクセサリー オーダーメイド クロス,20",
        ],
    )
    runner.import_keyword_metrics_csv(idea_id, metrics_csv)
    summary, run_id = runner.run_phase1(idea_id)
    assert summary["phase1_result"] == "PASS"

    serp_csv = _write_csv(
        Path(db.db_path).parent / "serp.csv",
        "query,rank,title,url,domain,site_type,page_type,db_type_page,intent_satisfied",
        [
            "指輪 アクセサリー オーダーメイド,1,指輪のオーダーメイド専門工房,https://koubou.example/ring,koubou.example,specialty_store,product,true,true",
            "ネックレス アクセサリー オーダーメイド,1,ネックレスの選び方ブログ,https://blog.example/necklace,blog.example,personal,article,false,false",
            "東京 アクセサリー オーダーメイド,1,東京のブログまとめ,https://blog.example/tokyo,blog.example,personal,article,false,false",
            "スカル アクセサリー オーダーメイド,1,スカルモチーフ雑記,https://blog.example/skull,blog.example,personal,article,false,false",
            "クロス アクセサリー オーダーメイド,1,クロスモチーフ雑記,https://blog.example/cross,blog.example,personal,article,false,false",
        ],
    )
    runner.import_serp_results_csv(run_id, idea_id, serp_csv)
    competition_summary = runner.run_phase2(run_id)
    assert competition_summary["weak_ratio"] > 0

    evaluation = runner.finalize_evaluation(run_id)
    assert evaluation["final_judgement"] == "GO"

    idea = ViabilityStore(db).get_idea(idea_id)
    assert idea["status"] == "go"


def test_reinvestigation_creates_a_new_run_without_touching_the_old_one(db, vconfig):
    runner = EvaluationRunner(db, vconfig)
    idea_id = runner.create_idea("テーマ")
    runner.add_keywords_from_generator(idea_id, ["メインKW"], axes={"region": ["A", "B", "C"]})
    metrics_csv = _write_csv(
        Path(db.db_path).parent / "m1.csv", "keyword,monthly_search_volume", ["メインKW,20"]
    )
    runner.import_keyword_metrics(idea_id, CsvKeywordSource(metrics_csv))

    _, run1 = runner.run_phase1(idea_id)
    _, run2 = runner.run_phase1(idea_id)

    assert run1 != run2
    store = ViabilityStore(db)
    assert store.get_demand_summary(run1) is not None
    assert store.get_demand_summary(run2) is not None
    assert len(store.list_runs(idea_id)) == 2
