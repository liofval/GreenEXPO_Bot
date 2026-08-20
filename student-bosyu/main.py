"""Web広く「企画スタッフ・登壇・ハッカソン枠」を検知してSlackに通知するbot。

- 複数ソース（Google News RSS / connpass API / Peatix）から新着itemを取得
- 2段フィルタ: 対象語 AND 募集語 → スコアリング → 閾値以上を通知
- 通知: Slack Incoming Webhook (Block Kit)
- 運営母体の公式SNS (X, Instagram) を記事本文から抽出して同梱
- 重複排除: state.json に投稿済みIDを保存、60日で剪定
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from fetchers import connpass, google, peatix
from keywords import (
    has_excluded,
    matches_recruit,
    matches_target,
    score,
    tag_category,
)
from sns_extractor import SnsHandles, extract as extract_sns

STATE_PATH = Path(__file__).resolve().parent / "state.json"
RETENTION_DAYS = 60
SCORE_THRESHOLD = 8          # これ以上のスコアで通知
DESCRIPTION_MAX = 200
MAX_ITEMS_PER_POST = 20
REQUEST_TIMEOUT = 30

SOURCE_DISPLAY = {
    "google": "Google",
    "connpass": "connpass",
    "peatix": "Peatix",
}


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


# --- fetch ---

def fetch_all() -> list[dict]:
    # connpass は CloudFront WAF で 403、Peatix は SPA 化で通常HTTP fetchが空。
    # コードは fetchers/ に残してあるので API キー取得や headless 導入時に有効化する。
    active = (("google", google.fetch),)
    all_items: list[dict] = []
    for name, fn in active:
        try:
            items = fn()
            print(f"[bosyu] source={name} fetched={len(items)}", file=sys.stderr)
            all_items.extend(items)
        except Exception as e:
            print(f"[bosyu] source={name} failed: {e}", file=sys.stderr)
    return all_items


# --- filter & score ---

def evaluate(item: dict) -> dict | None:
    """1件を評価。通知対象なら score/category/hits/sns を付けて返す。除外なら None。"""
    # descriptionにHTMLが含まれるソース(connpass等)があるためstrip
    item["description"] = strip_html(item.get("description", ""))
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
    item["sns"] = extract_sns(
        f"{item['title']} {item['description']}",
        extra_urls=item.get("extra_urls") or [],
    )
    return item


# --- Slack ---

def _sns_line(sns: SnsHandles) -> str:
    parts: list[str] = []
    if sns.x_url and sns.x_handle:
        parts.append(f"<{sns.x_url}|X {sns.x_handle}>")
    if sns.instagram_url and sns.instagram_handle:
        parts.append(f"<{sns.instagram_url}|Instagram {sns.instagram_handle}>")
    return "📱 " + " · ".join(parts) if parts else ""


def build_blocks(items: list[dict]) -> list[dict]:
    blocks: list[dict] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"🎯 企画スタッフ・登壇枠の新着 ({len(items)}件)"},
        },
        {"type": "divider"},
    ]
    for it in items:
        company = it["company"] or "（主催者不明）"
        title = it["title"]
        desc = truncate(it["description"], DESCRIPTION_MAX) if it["description"] else ""
        source_tag = SOURCE_DISPLAY.get(it.get("source", ""), it.get("source", ""))
        tag_line = f"{it['category_display']}  *{company}*  · via {source_tag}"
        hits_line = " ".join(f"`{h}`" for h in it["hits"][:6]) if it["hits"] else ""
        body_parts = [
            tag_line,
            f"<{it['link']}|{title}>",
        ]
        if desc:
            body_parts.append(f"> {desc}")
        if hits_line:
            body_parts.append(f"🏷 {hits_line} · score {it['score']}")
        sns_line = _sns_line(it["sns"])
        if sns_line:
            body_parts.append(sns_line)
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": "\n".join(body_parts)},
        })
        blocks.append({"type": "divider"})
    return blocks


def slack_post(webhook_url: str, items: list[dict]) -> None:
    for i in range(0, len(items), MAX_ITEMS_PER_POST):
        chunk = items[i : i + MAX_ITEMS_PER_POST]
        payload = {
            "text": f"企画スタッフ・登壇枠の新着 {len(chunk)}件",
            "blocks": build_blocks(chunk),
        }
        r = requests.post(webhook_url, json=payload, timeout=REQUEST_TIMEOUT)
        if not r.ok:
            print(f"Slack error {r.status_code}: {r.text}", file=sys.stderr)
            r.raise_for_status()


# --- orchestration ---

def run(state: dict, dry_run: bool) -> int:
    items = fetch_all()
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
    print(f"[bosyu] total_fetched={len(items)} new={new_count} hits={len(hits)}", file=sys.stderr)

    if not hits:
        return 0
    if dry_run:
        print("--- student-bosyu (dry-run) ---")
        for h in hits:
            print(f"[score {h['score']}] {h['category_display']} {h['company']} · via {h.get('source')}")
            print(f"  {h['title']}")
            print(f"  {h['link']}")
            print(f"  hits: {', '.join(h['hits'])}")
            sns: SnsHandles = h["sns"]
            if sns.any():
                print(f"  sns: X={sns.x_handle or '-'} IG={sns.instagram_handle or '-'}")
            print()
        return 0

    webhook = os.environ.get("SLACK_WEBHOOK_URL_BOSYU")
    if not webhook:
        print("SLACK_WEBHOOK_URL_BOSYU is not set", file=sys.stderr)
        return 2
    slack_post(webhook, hits)
    return 0


# --- test data ---

TEST_ITEMS: list[dict] = [
    {
        "id": "test-1",
        "source": "google",
        "title": "【テスト投稿】SPIKES in IVS 2027 企画スタッフ募集開始",
        "link": "https://example.com/ivs-spikes",
        "description": "IVS 2027 の伝説の裏方部隊「SPIKES」の第一期メンバーを募集します。イベント全体の企画運営に若手クリエイターとして参画できます。 https://x.com/ivs_official https://instagram.com/ivs_official",
        "company": "IVS運営事務局（合成データ）",
        "score": 18,
        "hits": ["SPIKES in IVS", "SPIKES", "企画スタッフ", "IVS", "クリエイター"],
        "category": "staff_planning",
        "category_display": "🛠 企画スタッフ",
        "sns": SnsHandles(
            x_handle="@ivs_official", x_url="https://x.com/ivs_official",
            instagram_handle="@ivs_official", instagram_url="https://instagram.com/ivs_official",
        ),
    },
    {
        "id": "test-2",
        "source": "connpass",
        "title": "【テスト投稿】東京都主催 SUSHITECH ITAMAE 第2期募集",
        "link": "https://example.com/sushitech",
        "description": "スタートアップと行政をつなぐ「ITAMAE」を募集。企画スタッフとして SUSHI TECH TOKYO の中核を担っていただきます。 https://x.com/sushitech_tokyo",
        "company": "東京都SUSHITECH事務局（合成データ）",
        "score": 15,
        "hits": ["ITAMAE", "SUSHITECH", "企画スタッフ", "スタートアップ"],
        "category": "staff_planning",
        "category_display": "🛠 企画スタッフ",
        "sns": SnsHandles(
            x_handle="@sushitech_tokyo", x_url="https://x.com/sushitech_tokyo",
        ),
    },
    {
        "id": "test-3",
        "source": "connpass",
        "title": "【テスト投稿】未来の食×AIハッカソン 参加者募集",
        "link": "https://example.com/food-ai-hackathon",
        "description": "48時間で「未来の食」をAIでハックする。学生・若手エンジニア対象。賞金50万円。 https://twitter.com/food_ai_hack",
        "company": "テック合同会社（合成データ）",
        "score": 12,
        "hits": ["ハッカソン", "エンジニア", "学生", "賞金"],
        "category": "hackathon",
        "category_display": "🧠 ハッカソン",
        "sns": SnsHandles(x_handle="@food_ai_hack", x_url="https://twitter.com/food_ai_hack"),
    },
    {
        "id": "test-4",
        "source": "peatix",
        "title": "【テスト投稿】U30起業家ピッチイベント 登壇者募集",
        "link": "https://example.com/pitch",
        "description": "U-30の起業家によるピッチイベント。登壇者を全国から募集します。優勝者には賞金100万円。",
        "company": "スタートアップ協議会（合成データ）",
        "score": 14,
        "hits": ["登壇者募集", "ピッチイベント", "起業家", "U-30", "賞金"],
        "category": "pitch",
        "category_display": "🎤 ピッチ登壇",
        "sns": SnsHandles(),
    },
]


def run_test(dry_run: bool) -> int:
    print(f"[bosyu][test] posting {len(TEST_ITEMS)} synthetic hits", file=sys.stderr)
    if dry_run:
        print("--- student-bosyu test (dry-run) ---")
        for h in TEST_ITEMS:
            print(f"[score {h['score']}] {h['category_display']} {h['company']} · via {h['source']}")
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
