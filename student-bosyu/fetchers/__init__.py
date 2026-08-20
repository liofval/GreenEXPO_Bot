"""複数ソースからitemを収集するfetcher群。

各fetcherは fetch(config) -> list[Item] を提供する。
Item は下記のdictで統一:
    {
        "id": str,             # 安定ハッシュ (sourceを含んで衝突回避)
        "source": str,         # "google" | "connpass" | "peatix"
        "title": str,
        "link": str,
        "description": str,
        "company": str,        # 主催者名 (取れる場合)
        "extra_urls": [str],   # SNS抽出用の追加URL (Google結果のsite URL等)
    }
"""
from __future__ import annotations

from . import connpass, google, peatix

__all__ = ["google", "connpass", "peatix"]
