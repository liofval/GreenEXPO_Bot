"""GREEN×EXPO 2027 関連ニュースを毎朝LINEに通知する。"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote_plus

import feedparser
import requests

QUERY_TERMS = [
    '"GREEN×EXPO 2027"',
    '"GREENEXPO 2027"',
    '"GREEN EXPO 2027"',
    '"国際園芸博覧会 2027"',
    '"国際園芸博 2027"',
    "横浜 園芸博",
    "横浜 花博 2027",
]
RSS_TEMPLATE = "https://news.google.com/rss/search?q={query}&hl=ja&gl=JP&ceid=JP:ja"
LINE_BROADCAST_ENDPOINT = "https://api.line.me/v2/bot/message/broadcast"

SEEN_PATH = Path(__file__).resolve().parent.parent / "seen.json"
MAX_ITEMS_PER_MESSAGE = 5
RETENTION_DAYS = 60
LINE_TEXT_LIMIT = 4900


def build_rss_url() -> str:
    query = " OR ".join(f"({term})" for term in QUERY_TERMS)
    return RSS_TEMPLATE.format(query=quote_plus(query))


def load_seen() -> dict[str, str]:
    if not SEEN_PATH.exists():
        return {}
    try:
        return json.loads(SEEN_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def save_seen(seen: dict[str, str]) -> None:
    SEEN_PATH.write_text(
        json.dumps(seen, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def prune_seen(seen: dict[str, str]) -> dict[str, str]:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)).isoformat()
    return {k: v for k, v in seen.items() if v >= cutoff}


def entry_id(entry) -> str:
    key = entry.get("id") or entry.get("link") or entry.get("title", "")
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def entry_source(entry) -> str:
    source = entry.get("source")
    if isinstance(source, dict):
        return source.get("title", "") or ""
    if hasattr(source, "get"):
        return source.get("title", "") or ""
    return ""


def fetch_new_entries(seen: dict[str, str]) -> list[tuple[str, dict]]:
    feed = feedparser.parse(build_rss_url())
    now = datetime.now(timezone.utc).isoformat()
    fresh: list[tuple[str, dict]] = []
    for entry in feed.entries:
        eid = entry_id(entry)
        if eid in seen:
            continue
        fresh.append((eid, entry))
        seen[eid] = now
    return fresh


def build_message_text(fresh: list[tuple[str, dict]]) -> str:
    today = datetime.now(timezone(timedelta(hours=9))).strftime("%m/%d(%a)")
    if not fresh:
        return (
            f"☀️ おはようございます ({today})\n"
            "本日のGREEN×EXPO 2027関連ニュースはまだ見つかりませんでした。"
        )
    lines = [f"☀️ おはようございます ({today})", f"GREEN×EXPO 2027 関連ニュース {len(fresh)}件", ""]
    for _, entry in fresh[:MAX_ITEMS_PER_MESSAGE]:
        title = entry.get("title", "(タイトル不明)")
        link = entry.get("link", "")
        source = entry_source(entry)
        prefix = f"[{source}] " if source else ""
        lines.append(f"▪ {prefix}{title}")
        if link:
            lines.append(f"  {link}")
        lines.append("")
    if len(fresh) > MAX_ITEMS_PER_MESSAGE:
        lines.append(f"…ほか{len(fresh) - MAX_ITEMS_PER_MESSAGE}件")
    text = "\n".join(lines).rstrip()
    return text[:LINE_TEXT_LIMIT]


def send_line(text: str, token: str) -> None:
    response = requests.post(
        LINE_BROADCAST_ENDPOINT,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        json={"messages": [{"type": "text", "text": text}]},
        timeout=30,
    )
    if not response.ok:
        print(f"LINE API error {response.status_code}: {response.text}", file=sys.stderr)
        response.raise_for_status()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="LINEに送らずに標準出力へ")
    args = parser.parse_args()

    seen = prune_seen(load_seen())
    fresh = fetch_new_entries(seen)
    text = build_message_text(fresh)

    if args.dry_run:
        print(text)
        print(f"\n--- {len(fresh)} new entries; seen total {len(seen)} ---")
        return 0

    token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
    if not token:
        print("LINE_CHANNEL_ACCESS_TOKEN is not set", file=sys.stderr)
        return 1
    send_line(text, token)
    save_seen(seen)
    return 0


if __name__ == "__main__":
    sys.exit(main())
