"""Google News RSS でキーワードクエリを回すfetcher。

- 通常のGoogle News検索と、`site:x.com` 付きの検索を同じRSSで叩ける
- 1クエリ最大20件返る（Google仕様）
- redirect URL の対処は呼び出し側ではしない（Slackはこのままでも開ける）
"""
from __future__ import annotations

import hashlib
import html
import re
from urllib.parse import quote_plus

import feedparser

USER_AGENT = "Mozilla/5.0 (compatible; StudentBosyuBot/2.0; +https://github.com/liofval/GreenEXPO_Bot)"

# 企画スタッフ・登壇枠・ハッカソン軸のGoogle検索クエリ
DEFAULT_QUERIES: tuple[str, ...] = (
    '"企画スタッフ" 募集',
    '"運営スタッフ" 募集 イベント',
    '"スタッフ募集" ハッカソン',
    '"登壇者募集" ピッチ',
    '"スピーカー募集" カンファレンス',
    '"メンター募集" スタートアップ',
    'ハッカソン 参加者 募集',
    'アイデアソン 募集',
    'ピッチコンテスト 登壇者',
    'ピッチイベント 若手',
    '"ITAMAE" 募集',
    '"SPIKES" IVS スタッフ',
    'SUSHITECH 東京 学生 スタッフ',
    # X (Twitter) 側を site: で拾う（無料でX検索を代用）
    'site:x.com "スタッフ募集" イベント',
    'site:x.com "登壇者募集"',
    'site:x.com "ハッカソン" 募集',
    'site:twitter.com "企画スタッフ" 募集',
)

RSS_URL = "https://news.google.com/rss/search?q={q}&hl=ja&gl=JP&ceid=JP:ja"


def _strip_html(text: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", text or "")).strip()


def _hash_id(source: str, key: str) -> str:
    return source + ":" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def fetch(queries: tuple[str, ...] = DEFAULT_QUERIES) -> list[dict]:
    seen_links: set[str] = set()
    items: list[dict] = []
    for q in queries:
        url = RSS_URL.format(q=quote_plus(q))
        feed = feedparser.parse(url, agent=USER_AGENT)
        for entry in feed.entries:
            link = (entry.get("link") or "").strip()
            if not link or link in seen_links:
                continue
            seen_links.add(link)
            title = (entry.get("title") or "").strip()
            description = _strip_html(entry.get("summary") or entry.get("description") or "")
            source_name = ""
            if entry.get("source") and isinstance(entry.source, dict):
                source_name = (entry.source.get("title") or "").strip()
            items.append({
                "id": _hash_id("google", link),
                "source": "google",
                "title": title,
                "link": link,
                "description": description,
                "company": source_name,   # ソースメディア名を仮の"company"に流用
                "extra_urls": [link],     # SNS抽出のためにリンク自体も渡す
            })
    return items
