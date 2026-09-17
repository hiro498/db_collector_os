# Topic Clusters（BtoB SEOトピッククラスター自動生成）

28カテゴリ（例: プレハブ冷凍庫施工、放置太陽光パネル撤去 等）それぞれについて、
ピラー記事1本＋サブ記事20〜30本のトピッククラスター構造を Gemini API で一括生成し、
`output/topic_clusters.json` に保存するツールです。DB Collector OS本体（データ収集
パイプライン）とは独立した、コンテンツ設計用の補助スクリプトです。

## ファイル構成

```
topic_clusters/
├── categories_input.json   # 入力データ（28カテゴリ分。下記フォーマット参照）
├── generate_clusters.py    # 生成スクリプト本体
├── output/
│   └── topic_clusters.json # 生成結果（generate_clusters.py実行後に作成される）
└── README.md
```

## 入力データの用意（categories_input.json）

スプレッドシートの列を、以下のキーにマッピングして `categories` 配列に追記してください。

| スプレッドシート列 | JSONキー |
| --- | --- |
| カテゴリ名 | `category_name` |
| 概要 | `overview` |
| ペルソナ | `persona` |
| 上位表示ポイント | `top_ranking_points` |

```json
{
  "categories": [
    {
      "category_name": "プレハブ冷凍庫施工",
      "overview": "...",
      "persona": "...",
      "top_ranking_points": "..."
    }
  ]
}
```

サンプルとして2件（プレハブ冷凍庫施工、放置太陽光パネル撤去）を同梱しています。
残り26カテゴリ分を同じ形式で追記し、合計28カテゴリにしてください。4フィールドの
いずれかが空のカテゴリがあると、スクリプトは実行前にエラーで一覧表示します。

## セットアップ

```bash
pip install -e ".[content-tools]"   # google-generativeai を追加インストール
export GEMINI_API_KEY="..."         # .env に書いてもよい（python-dotenv で自動読込）
```

## 実行

```bash
# 構造だけ先に確認したい場合（API呼び出しなし、ダミーデータ生成）
python3 topic_clusters/generate_clusters.py --dry-run

# 先頭2カテゴリだけで動作確認（API課金を抑えて確認）
python3 topic_clusters/generate_clusters.py --limit 2

# 28カテゴリ全件を本生成
python3 topic_clusters/generate_clusters.py
```

主なオプション:

| オプション | 説明 |
| --- | --- |
| `--input PATH` | 入力JSON（デフォルト: `categories_input.json`） |
| `--output PATH` | 出力先JSON（デフォルト: `output/topic_clusters.json`） |
| `--model NAME` | Geminiモデル名（デフォルト: `gemini-2.5-flash`） |
| `--limit N` | 先頭N件のカテゴリのみ処理 |
| `--sleep SEC` | カテゴリ間の待機秒数（デフォルト: 2.0） |
| `--retries N` | 1カテゴリあたりの最大リトライ回数（デフォルト: 3） |
| `--dry-run` | Gemini APIを呼ばず、ダミーデータで出力構造のみ確認する |

処理は1カテゴリ成功するごとに `output/topic_clusters.json` へ都度保存されるため、
途中でエラーが出ても、それまでの成功分は失われません。失敗したカテゴリ名は
`failed_categories` に記録され、実行後にターミナルへも一覧表示されます。

## 出力フォーマット（topic_clusters.json）

```json
{
  "categories": [
    {
      "category_name": "プレハブ冷凍庫施工",
      "pillar_article": {
        "main_keyword": "プレハブ冷凍庫 施工",
        "title": "プレハブ冷凍庫施工の費用・選び方・法令を徹底解説【完全ガイド】"
      },
      "sub_articles": [
        {
          "keyword": "プレハブ冷凍庫 坪単価 費用",
          "h2_headings": [
            "プレハブ冷凍庫の坪単価相場はいくら？",
            "費用を左右する3つの要因",
            "見積もり時に確認すべきポイント"
          ],
          "classification": "費用・相場系"
        }
      ]
    }
  ],
  "failed_categories": []
}
```

`classification` は次の4分類のいずれかです: `費用・相場系` / `比較・選定系` /
`トラブル・修繕系` / `法令・規格系`。
