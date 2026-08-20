"""connpass 公式APIのfetcher。

API: https://connpass.com/about/api/
  GET https://connpass.com/api/v1/event/?keyword=<kw>&count=100&order=2
  order=2 は「開催日時順」。keyword はスペース区切りAND。
  1リクエストあたり最大100件。頻繁な呼び出しは避ける（3秒以上間隔推奨）。

APIキー不要。ただしBrowser系User-Agentが必要になる場合がある。
"""
from __future__ import annotations

import hashlib
import time

import requests

USER_AGENT = "Mozilla/5.0 (compatible; StudentBosyuBot/2.0; +https://github.com/liofval/GreenEXPO_Bot)"
API_URL = "https://connpass.com/api/v1/event/"
REQUEST_TIMEOUT = 30
INTER_QUERY_SLEEP = 3.5  # 秒。APIマナー

DEFAULT_KEYWORDS: tuple[str, ...] = (
    "ハッカソン",
    "アイデアソン",
    "ピッチ",
    "スタッフ募集",
    "登壇者募集",
    "メンター募集",
)


def _hash_id(event_id: int | str) -> str:
    return "connpass:" + hashlib.sha1(f"connpass-{event_id}".encode("utf-8")).hexdigest()[:16]


def fetch(keywords: tuple[str, ...] = DEFAULT_KEYWORDS) -> list[dict]:
    items: list[dict] = []
    seen_ids: set[str] = set()
    for i, kw in enumerate(keywords):
        if i > 0:
            time.sleep(INTER_QUERY_SLEEP)
        try:
            r = requests.get(
                API_URL,
                params={"keyword": kw, "count": 100, "order": 2},
                headers={"User-Agent": USER_AGENT},
                timeout=REQUEST_TIMEOUT,
            )
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            print(f"[connpass] fetch failed for '{kw}': {e}")
            continue
        for ev in data.get("events", []):
            event_id = ev.get("event_id")
            if event_id is None:
                continue
            item_id = _hash_id(event_id)
            if item_id in seen_ids:
                continue
            seen_ids.add(item_id)
            title = (ev.get("title") or "").strip()
            catch = (ev.get("catch") or "").strip()
            desc = (ev.get("description") or "").strip()
            # descriptionはHTML。長いので冒頭のみ、タグは main.py 側で strip する前提
            snippet = catch or desc[:300]
            link = (ev.get("event_url") or "").strip()
            owner = (
                ev.get("series", {}).get("title")
                or ev.get("owner_display_name")
                or ""
            ).strip()
            items.append({
                "id": item_id,
                "source": "connpass",
                "title": title,
                "link": link,
                "description": snippet,
                "company": owner,
                "extra_urls": [link, ev.get("series", {}).get("url") or ""],
            })
    return items
