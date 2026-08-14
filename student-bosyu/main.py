"""PRTIMES から学生向け募集を検知して Slack に通知するbot。

- 毎時poll: PR TIMES RSS(index.rdf) から全プレスリリースを取得
- 2段フィルタ: 対象語(学生等) AND 募集語 → スコアリング → 閾値以上を通知
- 通知: Slack Incoming Webhook (Block Kit)
- 重複排除: state.json に投稿済みURLを保存、60日で剪定
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import feedparser
import requests

from keywords import (
    has_excluded,
    matches_recruit,
    matches_target,
    score,
    tag_category,
)

PRTIMES_RSS = "https://prtimes.jp/index.rdf"
USER_AGENT = "Mozilla/5.0 (compatible; StudentBosyuBot/1.0; +https://github.com/liofval/GreenEXPO_Bot)"

STATE_PATH = Path(__file__).resolve().parent / "state.json"
RETENTION_DAYS = 60
SCORE_THRESHOLD = 3          # これ以上のスコアで通知
DESCRIPTION_MAX = 180        # Slack本文の抜粋長
MAX_ITEMS_PER_POST = 20      # 1メッセージあたり最大件数（超過分は分割）
REQUEST_TIMEOUT = 30


# --- state ---

def load_state() -> dict:
    if STATE_PATH.exists():
        try:
            data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = {}
    else:
        data = {}
    data.setdefault("seen", {})
    return data


def save_state(state: dict) -> None:
    STATE_PATH.write_text(
        json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def prune(seen: dict[str, str]) -> dict[str, str]:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)).isoformat()
    return {k: v for k, v in seen.items() if v >= cutoff}


# --- helpers ---

def strip_html(text: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", text or "")).strip()


def truncate(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def hash_id(key: str) -> str:
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


# --- PR TIMES ---

def fetch_prtimes() -> list[dict]:
    """PR TIMES RSSからプレスリリースを取得。"""
    feed = feedparser.parse(PRTIMES_RSS, agent=USER_AGENT)
    items: list[dict] = []
    for entry in feed.entries:
        link = entry.get("link", "").strip()
        if not link:
            continue
        title = (entry.get("title") or "").strip()
        description = strip_html(entry.get("summary") or entry.get("description") or "")
        # PR TIMES RSS の dc:corp に会社名。無ければ description 冒頭の [会社名] を抜く。
        company = (entry.get("dc_corp") or "").strip()
        if not company:
            m = re.match(r"\s*\[([^\]]+)\]", description)
            if m:
                company = m.group(1).strip()
        # description 冒頭の [会社名] を本文からは削除
        description = re.sub(r"^\s*\[[^\]]+\]\s*", "", description)
        items.append({
            "id": hash_id(link),
            "title": title,
            "link": link,
            "description": description,
            "company": company,
        })
    return items


# --- filter & score ---

def evaluate(item: dict) -> dict | None:
    """1件を評価。通知対象なら score/category/hits を付けて返す。除外なら None。"""
    text = f"{item['title']} {item['description']}"
    if not matches_target(text) or not matches_recruit(text):
        return None
    if has_excluded(text):
        return None
    total, hits = score(text)
    if total < SCORE_THRESHOLD:
        return None
    cat = tag_category(text)
    item["score"] = total
    item["hits"] = hits
    item["category"] = cat[0] if cat else "other"
    item["category_display"] = cat[1] if cat else "🎓 その他"
    return item


# --- Slack ---

def build_blocks(items: list[dict]) -> list[dict]:
    """Slack Block Kit ペイロードを組み立て。"""
    blocks: list[dict] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"🎓 学生向け募集の新着 ({len(items)}件)"},
        },
        {"type": "divider"},
    ]
    for it in items:
        company = it["company"] or "（会社名不明）"
        title = it["title"]
        desc = truncate(it["description"], DESCRIPTION_MAX) if it["description"] else ""
        tag_line = f"{it['category_display']}  *{company}*"
        hits_line = " ".join(f"`{h}`" for h in it["hits"][:6]) if it["hits"] else ""
        body_parts = [
            tag_line,
            f"<{it['link']}|{title}>",
        ]
        if desc:
            body_parts.append(f"> {desc}")
        if hits_line:
            body_parts.append(f"🏷 {hits_line} · score {it['score']}")
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": "\n".join(body_parts)},
        })
        blocks.append({"type": "divider"})
    return blocks


def slack_post(webhook_url: str, items: list[dict]) -> None:
    """複数件を MAX_ITEMS_PER_POST ずつに分割して投稿。"""
    for i in range(0, len(items), MAX_ITEMS_PER_POST):
        chunk = items[i : i + MAX_ITEMS_PER_POST]
        payload = {
            "text": f"学生向け募集の新着 {len(chunk)}件",  # fallback text
            "blocks": build_blocks(chunk),
        }
        r = requests.post(webhook_url, json=payload, timeout=REQUEST_TIMEOUT)
        if not r.ok:
            print(f"Slack error {r.status_code}: {r.text}", file=sys.stderr)
            r.raise_for_status()


# --- orchestration ---

def run(state: dict, dry_run: bool) -> int:
    try:
        items = fetch_prtimes()
    except Exception as e:
        print(f"[bosyu] fetch failed: {e}", file=sys.stderr)
        return 1
    now_iso = datetime.now(timezone.utc).isoformat()
    hits: list[dict] = []
    new_count = 0
    for it in items:
        if it["id"] in state["seen"]:
            continue
        new_count += 1
        state["seen"][it["id"]] = now_iso
        evaluated = evaluate(it)
        if evaluated:
            hits.append(evaluated)

    hits.sort(key=lambda x: -x["score"])
    print(f"[bosyu] fetched={len(items)} new={new_count} hits={len(hits)}", file=sys.stderr)

    if not hits:
        return 0
    if dry_run:
        print("--- student-bosyu (dry-run) ---")
        for h in hits:
            print(f"[score {h['score']}] {h['category_display']} {h['company']}")
            print(f"  {h['title']}")
            print(f"  {h['link']}")
            print(f"  hits: {', '.join(h['hits'])}")
            print()
        return 0

    webhook = os.environ.get("SLACK_WEBHOOK_URL_BOSYU")
    if not webhook:
        print("SLACK_WEBHOOK_URL_BOSYU is not set", file=sys.stderr)
        return 2
    slack_post(webhook, hits)
    return 0


TEST_ITEMS: list[dict] = [
    {
        "id": "test-1",
        "title": "【テスト投稿】学生実行委員募集：GREEN×EXPO 2027 学生アンバサダー第一期",
        "link": "https://prtimes.jp/main/html/rd/p/000000000.000000001.html",
        "description": "横浜で開催される国際園芸博覧会にて、学生実行委員として運営に携わる大学生を募集します。任期は2026年9月〜2027年11月。",
        "company": "株式会社テスト（合成データ）",
        "score": 22,
        "hits": ["学生アンバサダー", "学生実行委員", "実行委員募集", "横浜", "green×expo", "国際園芸博"],
        "category": "student_org",
        "category_display": "🏫 学生団体",
    },
    {
        "id": "test-2",
        "title": "【テスト投稿】長期インターン募集：新規事業立ち上げに参画する大学生・大学院生",
        "link": "https://prtimes.jp/main/html/rd/p/000000000.000000002.html",
        "description": "大学生・大学院生対象。有給。週3日〜。",
        "company": "テスト株式会社（合成データ）",
        "score": 8,
        "hits": ["学生インターン", "長期インターン"],
        "category": "internship",
        "category_display": "💼 学生インターン",
    },
    {
        "id": "test-3",
        "title": "【テスト投稿】学生対象ビジネスコンテスト参加者募集開始",
        "link": "https://prtimes.jp/main/html/rd/p/000000000.000000003.html",
        "description": "賞金100万円。全国の大学生・大学院生を対象。",
        "company": "サンプル合同会社（合成データ）",
        "score": 13,
        "hits": ["学生 コンテスト", "大学生 コンテスト", "学生対象", "学生 向け"],
        "category": "contest",
        "category_display": "🏆 コンテスト",
    },
]


def run_test(dry_run: bool) -> int:
    """合成データでSlack投稿パイプラインだけをテスト。state・fetchは触らない。"""
    print(f"[bosyu][test] posting {len(TEST_ITEMS)} synthetic hits", file=sys.stderr)
    if dry_run:
        print("--- student-bosyu test (dry-run) ---")
        for h in TEST_ITEMS:
            print(f"[score {h['score']}] {h['category_display']} {h['company']}")
            print(f"  {h['title']}")
        return 0
    webhook = os.environ.get("SLACK_WEBHOOK_URL_BOSYU")
    if not webhook:
        print("SLACK_WEBHOOK_URL_BOSYU is not set", file=sys.stderr)
        return 2
    slack_post(webhook, TEST_ITEMS)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Slack投稿せず標準出力にヒット一覧を表示")
    parser.add_argument("--no-save", action="store_true", help="state.jsonを書き換えない（テスト用）")
    parser.add_argument("--test", action="store_true", help="合成データでSlack投稿だけをテスト（fetchもstateも触らない）")
    args = parser.parse_args()

    if args.test:
        return run_test(args.dry_run)

    state = load_state()
    state["seen"] = prune(state["seen"])
    rc = run(state, args.dry_run)
    if not args.dry_run and not args.no_save:
        save_state(state)
    return rc


if __name__ == "__main__":
    sys.exit(main())
