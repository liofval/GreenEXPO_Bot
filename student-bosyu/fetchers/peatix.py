"""Peatix 検索ページのHTMLスクレイピングfetcher。

Peatix には公式APIがない。検索結果ページの構造に依存するため、
構造変更で壊れる前提で運用する（壊れたら空リストを返してmainは継続）。

URL: https://peatix.com/search?q=<query>&country=JP
"""
from __future__ import annotations

import hashlib
import time
from urllib.parse import quote_plus, urljoin

import requests
from bs4 import BeautifulSoup

USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0 Safari/537.36"
SEARCH_URL = "https://peatix.com/search?q={q}&country=JP"
REQUEST_TIMEOUT = 30
INTER_QUERY_SLEEP = 2.0

DEFAULT_KEYWORDS: tuple[str, ...] = (
    "ハッカソン",
    "ピッチ",
    "スタッフ募集",
    "登壇者",
    "アイデアソン",
)


def _hash_id(link: str) -> str:
    return "peatix:" + hashlib.sha1(link.encode("utf-8")).hexdigest()[:16]


def _parse(html_text: str) -> list[dict]:
    soup = BeautifulSoup(html_text, "html.parser")
    items: list[dict] = []
    # Peatixの検索結果は event-card 系のクラス。安定していないので複数のセレクタを試す。
    candidates = soup.select("[data-testid='event-card']") or soup.select(".event-card") or soup.select("article")
    for card in candidates:
        a = card.find("a", href=True)
        if not a:
            continue
        link = urljoin("https://peatix.com/", a["href"])
        # event page pattern: https://peatix.com/event/<id>/...
        if "/event/" not in link:
            continue
        title_el = card.find(["h3", "h2"]) or a
        title = title_el.get_text(strip=True)
        if not title:
            continue
        desc_el = card.find("p")
        description = desc_el.get_text(" ", strip=True) if desc_el else ""
        owner_el = card.find(class_=lambda c: c and "organizer" in c.lower())
        owner = owner_el.get_text(strip=True) if owner_el else ""
        items.append({
            "id": _hash_id(link),
            "source": "peatix",
            "title": title,
            "link": link,
            "description": description,
            "company": owner,
            "extra_urls": [link],
        })
    return items


def fetch(keywords: tuple[str, ...] = DEFAULT_KEYWORDS) -> list[dict]:
    seen_ids: set[str] = set()
    result: list[dict] = []
    for i, kw in enumerate(keywords):
        if i > 0:
            time.sleep(INTER_QUERY_SLEEP)
        url = SEARCH_URL.format(q=quote_plus(kw))
        try:
            r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT)
            r.raise_for_status()
        except Exception as e:
            print(f"[peatix] fetch failed for '{kw}': {e}")
            continue
        for it in _parse(r.text):
            if it["id"] in seen_ids:
                continue
            seen_ids.add(it["id"])
            result.append(it)
    return result
