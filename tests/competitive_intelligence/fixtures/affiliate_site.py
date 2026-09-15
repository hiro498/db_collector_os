"""A small, realistic synthetic affiliate site fixture for PHASE 15 tests
(spec section 33): home/category/tag/article/ranking/comparison/other page
types, connected by internal links, with the same nav/footer/CTA
boilerplate repeated on every page (so PHASE 1's boilerplate detector has
something real to exclude) plus affiliate links, tables, FAQ, numeric
facts, comparisons, and commercial modifiers mixed into the real content.

Registers every page against a `responses.RequestsMock` -- this repo's
established, safe way to exercise the real crawl/parse/classify/score
pipeline without any actual network I/O (a literal loopback socket is
correctly blocked by FetchEngine's SSRF guard, and that guard must never
be weakened for a test).
"""
from __future__ import annotations

BASE = "https://fixture-affiliate.example"

_NAV = (
    '<nav><a href="{base}/">ホーム</a><a href="{base}/category/sleep-goods/">睡眠グッズ</a>'
    '<a href="{base}/category/health/">健康グッズ</a><a href="{base}/tag/osusume/">おすすめタグ</a>'
    '<a href="{base}/tag/hikaku/">比較タグ</a><a href="{base}/contact/">お問い合わせ</a></nav>'
).format(base=BASE)

_FOOTER = (
    '<footer><a href="{base}/company/">会社概要</a><a href="{base}/privacy/">プライバシーポリシー</a>'
    '<a href="{base}/contact/">お問い合わせ</a><p>Copyright 2026 FixtureAffiliate All Rights Reserved</p>'
    '<p>広告表記: 当サイトはアフィリエイト広告を利用しています</p></footer>'
).format(base=BASE)

_CTA = (
    '<div class="cta"><a href="https://affiliate-partner.example/buy?ref=fixture" '
    'rel="sponsored">公式サイトで詳細を見る</a></div>'
)


def _page(title: str, h1: str, body: str, extra_links: str = "") -> str:
    return (
        f"<!doctype html><html><head><title>{title}</title></head><body>"
        f"{_NAV}<main><h1>{h1}</h1>{body}{_CTA}{extra_links}</main>{_FOOTER}</body></html>"
    )


_ARTICLE_RICH = _page(
    "おすすめ 睡眠グッズ【2026年最新・独自調査】",
    "おすすめ 睡眠グッズ【2026年最新版・独自調査】",
    """
    <p>編集部が実際に80点の睡眠グッズを試し、独自調査・n=80のアンケート調査を実施した結果をもとに作成しました。
    同ジャンル1,000点中上位1%です。レビュー数は300件から900件に増加しました。順位も25位から2位に上昇しています。
    調査方法は覆面調査です。サンプルサイズはn=80です。価格帯・特徴・専門家コメントも含めて徹底的に比較しています。</p>
    <table><caption>徹底比較表</caption><tr><th>商品</th><th>評価</th><th>価格</th><th>特徴</th></tr>
    <tr><td>商品A</td><td>4.8</td><td>3200円</td><td>速効性</td></tr>
    <tr><td>商品B</td><td>4.6</td><td>2800円</td><td>持続性</td></tr>
    <tr><td>商品C</td><td>4.3</td><td>2000円</td><td>コスパ</td></tr></table>
    <h2>選び方のポイント</h2><p>枕の高さと素材が重要です。</p>
    <h2>よくある質問</h2>
    <dl><dt>返品は可能ですか？</dt><dd>可能です。到着後30日以内であれば返品を受け付けています。</dd></dl>
    <dl><dt>効果はどれくらいで出ますか？</dt><dd>個人差がありますが、1〜2週間程度が目安です。</dd></dl>
    """,
    f'<a href="{BASE}/article/suimin-hikaku/">睡眠グッズ比較記事はこちら</a>'
    f'<a href="{BASE}/article/suimin-ranking/">睡眠グッズランキングはこちら</a>',
)

_ARTICLE_COMPARISON = _page(
    "睡眠グッズ 比較",
    "睡眠グッズ 徹底比較",
    """
    <p>人気の睡眠グッズ5点を実機で比較しました。価格・評価・特徴を一覧で確認できます。</p>
    <table><caption>比較表</caption><tr><th>商品</th><th>価格</th><th>評価</th></tr>
    <tr><td>枕A</td><td>3000円</td><td>4.5</td></tr><tr><td>枕B</td><td>2500円</td><td>4.2</td></tr></table>
    <h2>選び方の比較ポイント</h2><p>硬さと通気性の違いを比較しています。</p>
    """,
    f'<a href="{BASE}/article/suimin-osusume/">おすすめ記事に戻る</a>',
)

_ARTICLE_RANKING = _page(
    "睡眠グッズ ランキング",
    "睡眠グッズ 人気ランキングTOP10",
    """
    <p>売上・レビュー数をもとに独自集計したランキングです。100件のレビューを分析しました。</p>
    <table><tr><th>順位</th><th>商品</th><th>評価</th></tr>
    <tr><td>1位</td><td>枕A</td><td>4.8</td></tr><tr><td>2位</td><td>枕B</td><td>4.5</td></tr></table>
    """,
)

_ARTICLE_HEALTH_OSUSUME = _page(
    "健康グッズ おすすめ",
    "健康グッズ おすすめ特集",
    """
    <p>編集部が選ぶ健康グッズのおすすめを紹介します。実際に使用した感想をもとにまとめました。
    レビュー数は50件から200件に増加しています。</p>
    <h2>選び方</h2><p>用途に合わせて選ぶことが大切です。</p>
    """,
)

_ARTICLE_HEALTH_HIKAKU = _page(
    "健康グッズ 比較",
    "健康グッズ 比較記事",
    """
    <p>健康グッズ4点を比較しました。価格帯別に特徴をまとめています。</p>
    <table><tr><th>商品</th><th>価格</th></tr><tr><td>商品X</td><td>1500円</td></tr></table>
    """,
)

_PLAIN_ARTICLES = [
    ("枕 おすすめ 比較", "枕 おすすめ 比較【編集部レビュー】",
     "<p>睡眠グッズの中でも枕のおすすめを比較レビューします。高さ・素材・硬さの3点が特に重要とされています。"
     "編集部が実際に睡眠グッズ10種類の枕を試し、口コミと評判をもとにおすすめ順にまとめました。"
     "睡眠グッズ選びで失敗しないための比較ポイントも解説します。</p>"),
    ("マットレス 口コミ 評判", "マットレス 口コミ・評判まとめ",
     "<p>睡眠グッズであるマットレスの口コミと評判をまとめました。定期的な陰干しと防水シーツの使用が効果的です。"
     "実際に使用した編集部のレビューと、購入者の評判を比較しながら紹介します。"
     "睡眠グッズのお手入れ方法についても解説しています。</p>"),
    ("快眠グッズ ランキング", "快眠グッズ 人気ランキング【最新版】",
     "<p>快眠グッズの人気ランキングをまとめました。編集部が実際に温湿度計や睡眠グッズを使って検証した結果です。"
     "睡眠グッズのおすすめランキングは季節によって変動するため、夏場と冬場それぞれの推奨設定も紹介します。</p>"),
    ("いびき対策グッズ おすすめ", "いびき対策グッズ おすすめ比較",
     "<p>いびき対策グッズのおすすめを比較しました。鼻腔拡張テープと横向き枕という2種類の睡眠グッズを検証しています。"
     "編集部が実際に試した口コミと、使用感の違いについて詳しく解説しています。"
     "睡眠グッズとしてのいびき対策アイテム選びの参考にしてください。</p>"),
    ("睡眠グッズ アイマスク 評判", "睡眠グッズ アイマスク 評判・効果検証",
     "<p>睡眠グッズの中でも人気のアイマスクの評判と効果を検証しました。遮光性の高いアイマスクを5種類試し、"
     "編集部の実体験をもとにまとめています。睡眠グッズとしてのおすすめ度を比較し、着け心地の違いも解説します。</p>"),
    ("耳栓 おすすめ 睡眠グッズ", "耳栓 おすすめ【睡眠グッズ比較】",
     "<p>睡眠用の耳栓のおすすめを比較しました。遮音性と装着感のバランスが重要なポイントです。"
     "他の睡眠グッズとあわせて使うことで、より効果的に快眠環境を整えられます。実際の使用レビューを交えて紹介します。</p>"),
    ("健康グッズ 口コミ 評判", "健康グッズ 口コミ・評判まとめ",
     "<p>健康グッズの口コミと評判をまとめました。マットレスや枕には交換の目安があります。"
     "編集部が主要メーカーの推奨交換時期を調査し、健康グッズとしての評判をあわせてまとめています。"
     "素材ごとの耐久性の違いも解説しています。</p>"),
]


def build_fixture_site() -> dict[str, str]:
    """Returns {full_url: html} for every page in the fixture."""
    pages: dict[str, str] = {}

    home_links = "".join(
        f'<a href="{BASE}{path}">{title}</a>'
        for path, title in [
            ("/category/sleep-goods/", "睡眠グッズカテゴリー"), ("/category/health/", "健康グッズカテゴリー"),
            ("/article/suimin-osusume/", "おすすめ 睡眠グッズ【2026年最新・独自調査】"),
        ]
    )
    pages[f"{BASE}/"] = _page(
        "睡眠・健康グッズ比較サイト", "睡眠グッズ・健康グッズ 比較サイト",
        "<p>睡眠グッズと健康グッズを実際に使って比較するサイトです。編集部が実機レビューをもとに紹介します。</p>",
        home_links,
    )

    plain_slugs = [f"plain-{i}" for i in range(len(_PLAIN_ARTICLES))]
    article_links = "".join(
        f'<a href="{BASE}/article/{slug}/">{title}</a>' for slug, title in [
            ("suimin-osusume", "おすすめ 睡眠グッズ"), ("suimin-hikaku", "睡眠グッズ比較"),
            ("suimin-ranking", "睡眠グッズランキング"),
        ]
    ) + "".join(f'<a href="{BASE}/article/{slug}/">関連記事</a>' for slug in plain_slugs)
    pages[f"{BASE}/category/sleep-goods/"] = _page(
        "睡眠グッズ カテゴリー", "睡眠グッズ カテゴリー一覧",
        "<p>睡眠グッズに関する記事一覧です。</p>", article_links,
    )
    pages[f"{BASE}/category/health/"] = _page(
        "健康グッズ カテゴリー", "健康グッズ カテゴリー一覧",
        "<p>健康グッズに関する記事一覧です。</p>",
        f'<a href="{BASE}/article/kenko-osusume/">健康グッズおすすめ</a>'
        f'<a href="{BASE}/article/kenko-hikaku/">健康グッズ比較</a>',
    )
    pages[f"{BASE}/tag/osusume/"] = _page(
        "「おすすめ」タグ", "「おすすめ」タグの記事一覧",
        "<p>おすすめタグが付いた記事の一覧です。</p>",
        f'<a href="{BASE}/article/suimin-osusume/">おすすめ 睡眠グッズ</a>'
        f'<a href="{BASE}/article/kenko-osusume/">健康グッズ おすすめ</a>',
    )
    pages[f"{BASE}/tag/hikaku/"] = _page(
        "「比較」タグ", "「比較」タグの記事一覧",
        "<p>比較タグが付いた記事の一覧です。</p>",
        f'<a href="{BASE}/article/suimin-hikaku/">睡眠グッズ比較</a>',
    )

    pages[f"{BASE}/article/suimin-osusume/"] = _ARTICLE_RICH
    pages[f"{BASE}/article/suimin-hikaku/"] = _ARTICLE_COMPARISON
    pages[f"{BASE}/article/suimin-ranking/"] = _ARTICLE_RANKING
    pages[f"{BASE}/article/kenko-osusume/"] = _ARTICLE_HEALTH_OSUSUME
    pages[f"{BASE}/article/kenko-hikaku/"] = _ARTICLE_HEALTH_HIKAKU
    for i, (title, h1, body) in enumerate(_PLAIN_ARTICLES):
        pages[f"{BASE}/article/plain-{i}/"] = _page(title, h1, body)

    pages[f"{BASE}/company/"] = _page(
        "会社概要", "会社概要", "<p>当サイトの運営会社情報です。所在地・連絡先を掲載しています。</p>",
    )
    pages[f"{BASE}/contact/"] = _page(
        "お問い合わせ", "お問い合わせ", "<p>お問い合わせはこちらのフォームからお願いします。</p>",
    )
    pages[f"{BASE}/privacy/"] = _page(
        "プライバシーポリシー", "プライバシーポリシー", "<p>個人情報の取り扱いについて定めたページです。</p>",
    )
    return pages


# spec section 35: expected top-quality keywords for the QUALITY TEST,
# used to assert the resulting TOP50 A+B rate matches human intuition --
# not to hand-author audit_class values (those stay machine/human-only,
# per section 10).
EXPECTED_STRONG_KEYWORDS = ("睡眠グッズ", "健康グッズ", "おすすめ", "比較")
EXPECTED_NOISE_TERMS = ("お問い合わせ", "会社概要", "プライバシーポリシー", "広告表記")
