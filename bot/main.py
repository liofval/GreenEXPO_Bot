"""GREEN×EXPO 2027 通知bot。

- daily: 毎朝Google Newsから企業関連ニュースをキーワードスコア順に通知
- official: 公式サイト(expo2027yokohama.or.jp)の更新を検知して通知
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
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import quote_plus, urljoin

import feedparser
import requests
from bs4 import BeautifulSoup

QUERY_TERMS = [
    '"GREEN×EXPO 2027"',
    '"GREENEXPO 2027"',
    '"GREEN EXPO 2027"',
    '"国際園芸博覧会 2027"',
    '"国際園芸博 2027"',
    "横浜 園芸博",
    "横浜 花博 2027",
    "上瀬谷 万博",
    "旧上瀬谷通信施設 博覧会",
    "横浜 花博",
    "横浜 万博 2027",
    "GREEN×EXPO協会",
    "AIPH 2027",
    '"Yokohama Expo 2027"',
    '"Horticultural Expo 2027"',
]

# 企業がイベントにどう関わっているかを重視。数値は重み。
CORPORATE_KEYWORDS: dict[str, int] = {
    "協賛": 5, "スポンサー": 5, "スポンサーシップ": 5,
    "パビリオン": 5, "コラボ": 4, "コラボレーション": 4,
    "パートナー": 4, "提携": 4, "参画": 3, "出資": 4,
    "出展": 4, "展示": 2, "ブース": 3, "ショーケース": 2,
    "新技術": 3, "グリーン技術": 3, "環境技術": 3,
    "SDGs": 2, "サステナ": 2, "脱炭素": 2, "カーボン": 2,
    "企業": 1, "参加企業": 2, "共創": 2, "官民": 1,
    "契約を調印": 3, "公式参加": 2,
}

OFFICIAL_BASE = "https://expo2027yokohama.or.jp"
OFFICIAL_NEWS_URL = f"{OFFICIAL_BASE}/news/"
RSS_TEMPLATE = "https://news.google.com/rss/search?q={query}&hl=ja&gl=JP&ceid=JP:ja"
GNEWS_PER_QUERY_LIMIT = 20
LINE_BROADCAST_ENDPOINT = "https://api.line.me/v2/bot/message/broadcast"
USER_AGENT = "Mozilla/5.0 (compatible; GreenExpoBot/1.0; +https://github.com/liofval/GreenEXPO_Bot)"

STATE_PATH = Path(__file__).resolve().parent.parent / "state.json"
LEGACY_SEEN_PATH = Path(__file__).resolve().parent.parent / "seen.json"

MIN_CORPORATE_SCORE = 0  # 0にすると全件通知。>0で企業関連のみ
TITLE_SIMILARITY_THRESHOLD = 0.55
MAX_NEWS_ITEMS = 8
MAX_OFFICIAL_ITEMS = 10
MAX_X_DRAFTS = 3
X_BODY_MAX = 140
X_HASHTAGS = "#GreenExpo2027 #国際園芸博覧会 #横浜"
RETENTION_DAYS = 60
LINE_TEXT_LIMIT = 4900
OFFICIAL_SUMMARY_MAX = 120


# --- state ---

def load_state() -> dict:
    if STATE_PATH.exists():
        try:
            data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = {}
    else:
        data = {}
    data.setdefault("news_seen", {})
    data.setdefault("official_seen", {})
    if not data["news_seen"] and LEGACY_SEEN_PATH.exists():
        try:
            data["news_seen"].update(json.loads(LEGACY_SEEN_PATH.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            pass
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


# --- Google News ---

def rss_url_for(term: str) -> str:
    return RSS_TEMPLATE.format(query=quote_plus(term))


def fetch_google_news() -> list[dict]:
    """QUERY_TERMSごとに個別にRSSを取得し、URL単位でdedupして返す。

    OR句を1つにまとめるとGoogle Newsが結果を絞るため、クエリを分割している。
    """
    seen_ids: set[str] = set()
    items: list[dict] = []
    for term in QUERY_TERMS:
        feed = feedparser.parse(rss_url_for(term))
        for entry in feed.entries[:GNEWS_PER_QUERY_LIMIT]:
            key = entry.get("id") or entry.get("link") or entry.get("title", "")
            item_id = hash_id(key)
            if item_id in seen_ids:
                continue
            seen_ids.add(item_id)
            source_obj = entry.get("source")
            source = ""
            if source_obj is not None:
                if isinstance(source_obj, dict):
                    source = source_obj.get("title", "")
                elif hasattr(source_obj, "get"):
                    source = source_obj.get("title", "")
            items.append({
                "id": item_id,
                "title": (entry.get("title") or "").strip(),
                "link": entry.get("link", ""),
                "source": source or "",
            })
    return items


def score_corporate(item: dict) -> int:
    text = item.get("title", "")
    return sum(w for kw, w in CORPORATE_KEYWORDS.items() if kw in text)


def normalize_title(title: str) -> str:
    title = re.sub(r"[（(].*?[)）]", "", title)
    title = re.sub(r"[「『【\[\]『」』】(){}]", "", title)
    title = re.sub(r"[-—、・,.。！!?？:：/／|｜~〜]", "", title)
    title = re.sub(r"\s+", "", title)
    return title


def cluster_similar(items: list[dict]) -> list[dict]:
    """類似タイトルを1件にまとめ、代表を score 降順で先頭に。"""
    kept: list[dict] = []
    for item in sorted(items, key=lambda x: -x["score"]):
        merged = False
        norm = normalize_title(item["title"])
        for k in kept:
            if SequenceMatcher(None, norm, normalize_title(k["title"])).ratio() >= TITLE_SIMILARITY_THRESHOLD:
                k.setdefault("variants", []).append(item)
                merged = True
                break
        if not merged:
            item.setdefault("variants", [])
            kept.append(item)
    return kept


# --- Official site ---

def fetch_official_list() -> list[dict]:
    r = requests.get(OFFICIAL_NEWS_URL, headers={"User-Agent": USER_AGENT}, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    items: list[dict] = []
    for li in soup.select("li"):
        a = li.find("a", href=True)
        if not a:
            continue
        date_el = li.find("span", class_="date")
        cat_el = li.find("span", class_="cat")
        title_el = li.select_one(".title .text")
        if not (date_el and cat_el and title_el):
            continue
        url = urljoin(OFFICIAL_BASE, a["href"])
        items.append({
            "id": hash_id(url),
            "date": date_el.get_text(strip=True),
            "category": cat_el.get_text(strip=True),
            "title": title_el.get_text(strip=True),
            "link": url,
        })
    return items


def fetch_official_summary(url: str) -> str:
    """お知らせ詳細ページから冒頭テキストを抽出。失敗時は空文字。"""
    if not url.startswith(OFFICIAL_BASE) or url.endswith(".pdf"):
        return ""
    try:
        r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=20)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        main = soup.find("main") or soup.find("article") or soup
        for tag in main.find_all(["script", "style", "nav", "header", "footer"]):
            tag.decompose()
        for p in main.find_all("p"):
            text = p.get_text(strip=True)
            if len(text) >= 20:
                return truncate(text, OFFICIAL_SUMMARY_MAX)
        return ""
    except requests.RequestException:
        return ""


# --- LINE ---

def line_send(text: str, token: str) -> None:
    r = requests.post(
        LINE_BROADCAST_ENDPOINT,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"messages": [{"type": "text", "text": text[:LINE_TEXT_LIMIT]}]},
        timeout=30,
    )
    if not r.ok:
        print(f"LINE API error {r.status_code}: {r.text}", file=sys.stderr)
        r.raise_for_status()


# --- X draft ---

def clean_title_for_x(title: str, source: str) -> str:
    """Google Newsのタイトル末尾に付く『 - ソース名』を除去。"""
    title = title.strip()
    if source:
        suffix = f" - {source}"
        if title.endswith(suffix):
            title = title[: -len(suffix)].strip()
    return title


def build_x_draft(title: str, link: str, source: str = "") -> str:
    body = clean_title_for_x(title, source)
    if len(body) > X_BODY_MAX:
        body = body[: X_BODY_MAX - 1] + "…"
    parts = [body]
    if link:
        parts.append(link)
    parts.append(X_HASHTAGS)
    return "\n".join(parts)


def build_x_drafts_block(items: list[dict]) -> str:
    if not items:
        return ""
    lines = ["", "─── X下書き ───"]
    for it in items[:MAX_X_DRAFTS]:
        lines.append("")
        lines.append(build_x_draft(it["title"], it.get("link", ""), it.get("source", "")))
        lines.append("───")
    return "\n".join(lines)


# --- message builders ---

def build_daily_message(items: list[dict]) -> str | None:
    if not items:
        return None
    today = datetime.now(timezone(timedelta(hours=9))).strftime("%m/%d")
    lines = [f"☀️ おはようございます ({today})", "GREEN×EXPO 2027 関連ニュース", ""]
    for it in items[:MAX_NEWS_ITEMS]:
        title = clean_title_for_x(it["title"], it["source"])
        prefix = f"[{it['source']}] " if it["source"] else ""
        marker = "🏢 " if it.get("score", 0) > 0 else ""
        lines.append(f"▪ {marker}{prefix}{title}")
        if it["variants"]:
            lines.append(f"  関連{len(it['variants'])}件を集約")
        if it["link"]:
            lines.append(f"  {it['link']}")
        lines.append("")
    remaining = len(items) - MAX_NEWS_ITEMS
    if remaining > 0:
        lines.append(f"…ほか{remaining}件")
    body = "\n".join(lines).rstrip()
    return body + build_x_drafts_block(items)


def build_official_message(items: list[dict]) -> str | None:
    if not items:
        return None
    lines = ["📢 GREEN×EXPO 2027 公式サイト更新", ""]
    for it in items[:MAX_OFFICIAL_ITEMS]:
        lines.append(f"▪ [{it['category']}] {it['title']}")
        lines.append(f"  {it['date']}")
        if it.get("summary"):
            lines.append(f"  {it['summary']}")
        lines.append(f"  {it['link']}")
        lines.append("")
    remaining = len(items) - MAX_OFFICIAL_ITEMS
    if remaining > 0:
        lines.append(f"…ほか{remaining}件")
    body = "\n".join(lines).rstrip()
    return body + build_x_drafts_block(items)


# --- orchestration ---

def run_daily(state: dict, dry_run: bool) -> None:
    items = fetch_google_news()
    now_iso = datetime.now(timezone.utc).isoformat()
    new_items = []
    for it in items:
        if it["id"] in state["news_seen"]:
            continue
        it["score"] = score_corporate(it)
        state["news_seen"][it["id"]] = now_iso
        new_items.append(it)
    filtered = [x for x in new_items if x["score"] >= MIN_CORPORATE_SCORE]
    clustered = cluster_similar(filtered)
    text = build_daily_message(clustered)
    if text is None:
        print("[daily] 新着なし", file=sys.stderr)
        return
    if dry_run:
        print("--- daily ---")
        print(text)
        return
    token = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
    line_send(text, token)


def run_official(state: dict, dry_run: bool) -> None:
    try:
        items = fetch_official_list()
    except requests.RequestException as e:
        print(f"[official] fetch failed: {e}", file=sys.stderr)
        return
    now_iso = datetime.now(timezone.utc).isoformat()
    new_items = []
    for it in items:
        if it["id"] in state["official_seen"]:
            continue
        it["summary"] = fetch_official_summary(it["link"])
        state["official_seen"][it["id"]] = now_iso
        new_items.append(it)
    text = build_official_message(new_items)
    if text is None:
        print("[official] 新着なし", file=sys.stderr)
        return
    if dry_run:
        print("--- official ---")
        print(text)
        return
    token = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
    line_send(text, token)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["daily", "official", "both"], default="both")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    state = load_state()
    state["news_seen"] = prune(state["news_seen"])
    state["official_seen"] = prune(state["official_seen"])

    if args.mode in ("daily", "both"):
        run_daily(state, args.dry_run)
    if args.mode in ("official", "both"):
        run_official(state, args.dry_run)

    if not args.dry_run:
        save_state(state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
