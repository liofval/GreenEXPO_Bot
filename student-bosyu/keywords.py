"""学生向け募集の検出に使うキーワード辞書。

2段フィルタで使う:
  Layer 1 (gate): TARGET_TERMS と RECRUIT_TERMS を両方含む記事だけ通す
  Layer 2 (score): POSITIVE_KEYWORDS で加点し、EXCLUDE_KEYWORDS があれば弾く

CATEGORY_TAGS はヒットしたキーワードから 4カテゴリ（学生団体/イベント運営/インターン/コンテスト）を推定する。
"""
from __future__ import annotations

# --- Layer 1: gate ---

# 「誰向けか」語。1つ以上マッチ必須。
TARGET_TERMS: tuple[str, ...] = (
    "学生", "大学生", "高校生", "中高生", "高専生", "専門学校生", "院生", "大学院生",
    "若者", "ユース", "Z世代", "U-25", "U25", "10代", "20代",
)

# 「募集」語。1つ以上マッチ必須。
RECRUIT_TERMS: tuple[str, ...] = (
    "募集", "応募", "エントリー", "参加者", "参加受付", "参加無料", "参加費無料",
    "オーディション", "コンテスト", "アワード", "コンペ", "コンペティション",
    "メンバー募集", "スタッフ募集", "ボランティア", "アンバサダー", "サポーター",
    "インターン", "インターンシップ", "モニター", "登壇者", "スピーカー募集",
    "受講生", "参加校", "参加チーム", "ゼミ生", "ワークショップ参加",
)

# --- Layer 2: scoring ---

# 加点キーワード。値が加点スコア。
POSITIVE_KEYWORDS: dict[str, int] = {
    # 学生団体・プロジェクト系（本命）
    "学生団体": 5, "学生プロジェクト": 5, "学生スタッフ": 5,
    "学生ボランティア": 5, "学生アンバサダー": 5, "学生インターン": 5,
    "学生サポーター": 4, "学生リーダー": 4, "学生リーダーシップ": 4,
    "学生実行委員": 5, "実行委員募集": 4, "運営メンバー募集": 4,
    "学生モニター": 3, "学生アドバイザー": 3,
    # イベント運営文脈
    "運営スタッフ": 4, "イベントスタッフ": 3, "イベントボランティア": 4,
    "スタッフとして参加": 3, "ボランティアスタッフ": 3,
    # コンテスト/アワード（学生対象を強めるため学生語と共起で加点）
    "学生 コンテスト": 3, "大学生 コンテスト": 3, "高校生 コンテスト": 3,
    "学生 アワード": 3, "学生 コンペ": 3,
    "学生対象": 3, "学生限定": 3, "大学生限定": 3, "高校生限定": 3,
    "学生 向け": 2, "大学生 向け": 2, "高校生 向け": 2,
    # インターン
    "長期インターン": 3, "有給インターン": 2, "サマーインターン": 2,
    # GreenExpo/横浜文脈ボーナス（既存プロジェクトの狙いに沿う）
    "横浜": 2, "神奈川": 2, "green×expo": 3, "greenexpo": 3, "国際園芸博": 3,
    "サステナ": 2, "サステナビリティ": 2, "SDGs": 2, "環境": 1, "脱炭素": 2,
    "地域": 1, "まちづくり": 2, "共創": 2,
}

# 除外キーワード。1つでもマッチしたら弾く。
# 求人系ノイズや、対象が学生でない可能性が高いもの。
EXCLUDE_KEYWORDS: tuple[str, ...] = (
    # 就活・採用ノイズ
    "新卒採用", "中途採用", "中途入社", "経験者採用", "第二新卒",
    "就職セミナー", "就活イベント", "就活サービス", "就活生向け", "26卒", "27卒", "28卒",
    "求人媒体", "採用ブランディング", "採用サイト", "採用広報", "採用強化",
    "エンジニア募集(正社員)", "エンジニア募集（正社員）", "デザイナー募集(正社員)",
    "業務委託契約", "業務委託 募集",
    # 商品文脈ノイズ
    "学生服", "学生証", "学割", "学生時代", "学生協", "学生寮",
    # 教員/専門職向け
    "教員募集", "教員採用", "講師募集", "研究員募集",
    # 求人プラットフォーム自体のPR
    "求人サイト", "求人プラットフォーム", "採用管理",
)

# --- Category tagging ---

# キーワード → カテゴリタグ。複数マッチしたら最初のカテゴリを採用。
CATEGORY_TAGS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("student_org", "🏫 学生団体", (
        "学生団体", "学生プロジェクト", "学生実行委員", "実行委員募集",
        "学生リーダー", "学生アンバサダー", "運営メンバー募集",
    )),
    ("event_staff", "🎪 イベント運営", (
        "運営スタッフ", "イベントスタッフ", "イベントボランティア",
        "ボランティアスタッフ", "スタッフ募集", "ボランティア",
    )),
    ("internship", "💼 学生インターン", (
        "インターン", "インターンシップ", "長期インターン", "サマーインターン", "有給インターン",
    )),
    ("contest", "🏆 コンテスト", (
        "コンテスト", "アワード", "コンペ", "コンペティション", "オーディション",
    )),
)


def tag_category(text: str) -> tuple[str, str] | None:
    """テキストからカテゴリを推定。返り値は (slug, display) または None。"""
    for slug, display, keywords in CATEGORY_TAGS:
        if any(kw in text for kw in keywords):
            return (slug, display)
    return None


def matches_target(text: str) -> bool:
    return any(term in text for term in TARGET_TERMS)


def matches_recruit(text: str) -> bool:
    return any(term in text for term in RECRUIT_TERMS)


def has_excluded(text: str) -> bool:
    return any(term in text for term in EXCLUDE_KEYWORDS)


def score(text: str) -> tuple[int, list[str]]:
    """加点合計と、ヒットした加点キーワード一覧を返す。"""
    hits: list[str] = []
    total = 0
    lower = text.lower()
    for kw, weight in POSITIVE_KEYWORDS.items():
        # スペース区切りの複合語は分解してAND判定
        if " " in kw:
            parts = kw.split()
            if all(p.lower() in lower for p in parts):
                hits.append(kw)
                total += weight
        elif kw.lower() in lower:
            hits.append(kw)
            total += weight
    return total, hits
