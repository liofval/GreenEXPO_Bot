"""記事本文から運営母体の公式SNSアカウントを抽出する。

対応:
  - X (旧Twitter): x.com/<handle>, twitter.com/<handle>
  - Instagram: instagram.com/<handle>

方針:
  - 本文テキスト + 追加で渡された extra_urls 全部から正規表現でハンドルを拾う
  - `share`, `intent`, `home`, `p` などのシステム系パスは除外
  - 最初に見つかった1件だけ返す（複数出てくる場合の precedence は呼び出し側で制御）
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# ハンドル部分にありがちなノイズパス
_X_NOISE_PATHS = {
    "share", "intent", "home", "search", "hashtag", "i", "compose",
    "explore", "notifications", "messages", "settings", "login", "signup",
}
_IG_NOISE_PATHS = {
    "p", "reel", "reels", "explore", "stories", "tv", "accounts",
    "direct", "about", "developer", "legal",
}

# 正規表現
_X_RE = re.compile(
    r"https?://(?:www\.)?(?:x|twitter)\.com/(@?[A-Za-z0-9_]{1,15})(?:[/?#]|$)",
    re.IGNORECASE,
)
_IG_RE = re.compile(
    r"https?://(?:www\.)?instagram\.com/(@?[A-Za-z0-9_.]{1,30})(?:[/?#]|$)",
    re.IGNORECASE,
)


@dataclass
class SnsHandles:
    x_handle: str | None = None      # "@handle" 形式
    x_url: str | None = None
    instagram_handle: str | None = None
    instagram_url: str | None = None

    def any(self) -> bool:
        return bool(self.x_handle or self.instagram_handle)


def _normalize_handle(raw: str) -> str:
    h = raw.lstrip("@")
    return f"@{h}"


def _first_valid(pattern: re.Pattern[str], text: str, noise: set[str]) -> tuple[str, str] | None:
    for m in pattern.finditer(text):
        handle_raw = m.group(1).lstrip("@")
        if not handle_raw or handle_raw.lower() in noise:
            continue
        # URL全体を再構築（クエリ・fragmentは落とす）
        start = m.start()
        # ドメイン抽出のためsub-match domainがないのでURL全体を取り直し
        url_match = re.match(
            r"https?://(?:www\.)?[^/]+/" + re.escape(handle_raw),
            text[start:],
            re.IGNORECASE,
        )
        url = url_match.group(0) if url_match else m.group(0).rstrip("/?#")
        return (_normalize_handle(handle_raw), url)
    return None


def extract(text: str, extra_urls: list[str] | None = None) -> SnsHandles:
    """テキスト（+補助URLリスト）からSNSアカウントを抽出。"""
    haystack = text or ""
    if extra_urls:
        haystack = haystack + "\n" + "\n".join(u for u in extra_urls if u)

    result = SnsHandles()
    x = _first_valid(_X_RE, haystack, _X_NOISE_PATHS)
    if x:
        result.x_handle, result.x_url = x
    ig = _first_valid(_IG_RE, haystack, _IG_NOISE_PATHS)
    if ig:
        result.instagram_handle, result.instagram_url = ig
    return result
