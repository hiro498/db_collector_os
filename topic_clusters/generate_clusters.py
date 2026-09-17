#!/usr/bin/env python3
"""Generate BtoB SEO topic-cluster data (1 pillar article + 20-30 sub-articles
per category) for every category in categories_input.json, via the Gemini API.

Usage:
    export GEMINI_API_KEY=...
    python3 topic_clusters/generate_clusters.py
    python3 topic_clusters/generate_clusters.py --dry-run          # no API calls, synthetic sample
    python3 topic_clusters/generate_clusters.py --limit 2          # only the first 2 categories
    python3 topic_clusters/generate_clusters.py --input my.json --output out.json

Input format: see categories_input.json (top-level "categories" list; each
item has category_name / overview / persona / top_ranking_points).

Output format: see the module docstring of build_prompt() below, or just run
with --dry-run and read the printed sample.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - python-dotenv is a project dependency
    load_dotenv = None

HERE = Path(__file__).resolve().parent
DEFAULT_INPUT = HERE / "categories_input.json"
DEFAULT_OUTPUT = HERE / "output" / "topic_clusters.json"

REQUIRED_CATEGORY_FIELDS = ("category_name", "overview", "persona", "top_ranking_points")
CLASSIFICATIONS = ["費用・相場系", "比較・選定系", "トラブル・修繕系", "法令・規格系"]
MIN_SUB_ARTICLES = 20
MAX_SUB_ARTICLES = 30


class GenerationError(Exception):
    pass


def load_categories(input_path: Path) -> list[dict[str, str]]:
    with open(input_path, encoding="utf-8") as f:
        data = json.load(f)

    categories = data.get("categories")
    if not isinstance(categories, list) or not categories:
        raise GenerationError(
            f"{input_path} に 'categories' 配列が見つかりません（1件以上必要です）。"
        )

    problems = []
    for i, cat in enumerate(categories):
        missing = [field for field in REQUIRED_CATEGORY_FIELDS if not cat.get(field)]
        if missing:
            problems.append(f"  - categories[{i}] ({cat.get('category_name', '?')}): 不足フィールド {missing}")
    if problems:
        raise GenerationError(
            "入力データに不足フィールドがあります:\n" + "\n".join(problems)
        )

    return categories


def build_prompt(category: dict[str, str]) -> str:
    """Prompt asking Gemini for one category's topic cluster, as pure JSON:

    {
      "category_name": "...",
      "pillar_article": {"main_keyword": "...", "title": "..."},
      "sub_articles": [
        {
          "keyword": "...",
          "h2_headings": ["...", "...", "..."],
          "classification": "費用・相場系" | "比較・選定系" | "トラブル・修繕系" | "法令・規格系"
        },
        ... (20〜30件)
      ]
    }
    """
    classifications = "」「".join(CLASSIFICATIONS)
    return f"""あなたはBtoB向けSEOコンテンツ設計の専門家です。
以下のカテゴリについて、トピッククラスター構造（ピラー記事1本＋サブ記事20〜30本）を設計してください。

【カテゴリ名】
{category['category_name']}

【概要】
{category['overview']}

【ペルソナ】
{category['persona']}

【上位表示ポイント】
{category['top_ranking_points']}

【要件】
1. 検索するのはBtoBの意思決定者・現場担当者です。費用・相場、比較・選定、トラブル・修繕、法令・規格の4種類の検索意図を網羅してください。
2. サブ記事は20〜30本、キーワードの重複がないようにしてください。
3. 各サブ記事に、想定されるH2見出し案を3〜5個つけてください。
4. 各サブ記事を必ず次の4分類のいずれか1つに分類してください:「{classifications}」
5. 出力は次のJSONスキーマに厳密に従い、JSON以外の文字（説明文やMarkdownのコードフェンス）を一切含めないでください。

{{
  "category_name": "{category['category_name']}",
  "pillar_article": {{"main_keyword": "...", "title": "..."}},
  "sub_articles": [
    {{"keyword": "...", "h2_headings": ["...", "..."], "classification": "..."}}
  ]
}}
"""


def parse_response_text(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        if text.endswith("```"):
            text = text.rsplit("```", 1)[0]
        text = text.strip()
        if text.startswith("json"):
            text = text[len("json"):].strip()
    return json.loads(text)


def validate_cluster(cluster: dict[str, Any]) -> list[str]:
    problems = []
    pillar = cluster.get("pillar_article")
    if not isinstance(pillar, dict) or not pillar.get("main_keyword") or not pillar.get("title"):
        problems.append("pillar_article.main_keyword / title が欠落しています")

    sub_articles = cluster.get("sub_articles")
    if not isinstance(sub_articles, list):
        problems.append("sub_articles が配列ではありません")
        return problems

    if not (MIN_SUB_ARTICLES <= len(sub_articles) <= MAX_SUB_ARTICLES):
        problems.append(
            f"sub_articles の件数が範囲外です（{len(sub_articles)}件、期待値 {MIN_SUB_ARTICLES}〜{MAX_SUB_ARTICLES}）"
        )

    for i, article in enumerate(sub_articles):
        if not article.get("keyword"):
            problems.append(f"sub_articles[{i}].keyword が欠落しています")
        if not article.get("h2_headings"):
            problems.append(f"sub_articles[{i}].h2_headings が欠落しています")
        if article.get("classification") not in CLASSIFICATIONS:
            problems.append(
                f"sub_articles[{i}].classification が不正です: {article.get('classification')!r}"
            )

    return problems


def generate_cluster_for_category(
    category: dict[str, str],
    model: Any,
    retries: int,
) -> dict[str, Any]:
    prompt = build_prompt(category)
    last_error: Exception | None = None

    for attempt in range(1, retries + 1):
        try:
            response = model.generate_content(prompt)
            cluster = parse_response_text(response.text)
        except Exception as exc:  # noqa: BLE001 - report and retry
            last_error = exc
            print(f"    [試行 {attempt}/{retries}] エラー: {exc}", file=sys.stderr)
            continue

        problems = validate_cluster(cluster)
        if not problems:
            cluster.setdefault("category_name", category["category_name"])
            return cluster

        last_error = GenerationError("; ".join(problems))
        print(f"    [試行 {attempt}/{retries}] 出力バリデーション失敗: {last_error}", file=sys.stderr)

    raise GenerationError(f"{retries}回試行しても生成に失敗しました: {last_error}")


def build_dry_run_cluster(category: dict[str, str]) -> dict[str, Any]:
    sub_articles = []
    for i in range(MIN_SUB_ARTICLES):
        classification = CLASSIFICATIONS[i % len(CLASSIFICATIONS)]
        sub_articles.append(
            {
                "keyword": f"{category['category_name']} サンプルキーワード{i + 1}",
                "h2_headings": [
                    f"{category['category_name']}の{classification}に関する見出し1",
                    f"{category['category_name']}の{classification}に関する見出し2",
                    f"{category['category_name']}の{classification}に関する見出し3",
                ],
                "classification": classification,
            }
        )
    return {
        "category_name": category["category_name"],
        "pillar_article": {
            "main_keyword": f"{category['category_name']} まとめ",
            "title": f"{category['category_name']}の費用・選び方・法令を徹底解説【完全ガイド】",
        },
        "sub_articles": sub_articles,
    }


def atomic_write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp_path.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="入力カテゴリJSON (default: %(default)s)")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="出力先JSON (default: %(default)s)")
    parser.add_argument("--model", default="gemini-3.6-flash", help="Geminiモデル名 (default: %(default)s)")
    parser.add_argument("--limit", type=int, default=None, help="先頭N件のカテゴリのみ処理（動作確認用）")
    parser.add_argument("--sleep", type=float, default=2.0, help="カテゴリ間の待機秒数 (default: %(default)s)")
    parser.add_argument("--retries", type=int, default=3, help="1カテゴリあたりの最大リトライ回数 (default: %(default)s)")
    parser.add_argument("--dry-run", action="store_true", help="Gemini APIを呼ばずダミーデータで構造のみ確認する")
    args = parser.parse_args()

    if load_dotenv:
        load_dotenv()

    try:
        categories = load_categories(args.input)
    except (GenerationError, OSError, json.JSONDecodeError) as exc:
        print(f"入力エラー: {exc}", file=sys.stderr)
        return 1

    if args.limit is not None:
        categories = categories[: args.limit]

    model = None
    if not args.dry_run:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            print("エラー: 環境変数 GEMINI_API_KEY が設定されていません（--dry-run で構造のみ確認できます）。", file=sys.stderr)
            return 1
        try:
            import google.generativeai as genai
        except ImportError:
            print(
                "エラー: google-generativeai がインストールされていません。"
                " `pip install -e '.[content-tools]'` を実行してください。",
                file=sys.stderr,
            )
            return 1
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(
            args.model,
            generation_config={"response_mime_type": "application/json"},
        )

    results: list[dict[str, Any]] = []
    failed: list[str] = []
    total = len(categories)

    for i, category in enumerate(categories, start=1):
        name = category["category_name"]
        print(f"[{i}/{total}] {name} ... ", end="", flush=True)
        try:
            if args.dry_run:
                cluster = build_dry_run_cluster(category)
            else:
                cluster = generate_cluster_for_category(category, model, args.retries)
        except GenerationError as exc:
            print(f"FAILED ({exc})")
            failed.append(name)
            continue

        results.append(cluster)
        print(f"OK ({len(cluster['sub_articles'])}本のサブ記事)")

        atomic_write_json(args.output, {"categories": results, "failed_categories": failed})

        if not args.dry_run and i < total:
            time.sleep(args.sleep)

    print()
    print(f"完了: {len(results)}/{total} カテゴリ成功, {len(failed)}件失敗")
    if failed:
        print(f"失敗したカテゴリ: {', '.join(failed)}")
    print(f"出力先: {args.output}")

    if results:
        print()
        print("=== サンプル構造 (先頭カテゴリの一部) ===")
        sample = dict(results[0])
        sample["sub_articles"] = sample["sub_articles"][:3] + [
            {"...": f"(他 {len(results[0]['sub_articles']) - 3} 本省略)"}
        ]
        print(json.dumps(sample, ensure_ascii=False, indent=2))

    return 0 if not failed else 2


if __name__ == "__main__":
    raise SystemExit(main())
