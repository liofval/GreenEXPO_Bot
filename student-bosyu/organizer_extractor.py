"""タイトル/本文抜粋から「主催・共催・協賛・後援・協力」を抽出する。

Google News の抜粋やconnpass catchなど短文が対象。明示的に
`主催: ○○` `【主催】○○` のように書かれた場合のみ拾える前提。
取れなければ何も返さない（Slack側で行ごと省略される）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

LABEL_KEYS = ("主催", "共催", "協賛", "後援", "協力")
_LABEL_ALT = "|".join(LABEL_KEYS)

# 【主催】 / 主催: / 主催： / 主催者： / 主催団体： 形式のラベル頭
_LABEL_HEAD = re.compile(
    rf"(?:【\s*({_LABEL_ALT})\s*】|({_LABEL_ALT})(?:者|団体|企業|社)?\s*[:：])"
)

# 「〇〇主催」「〇〇協賛」インライン形式。
# 直前が語境界（空白・括弧・句読点・記事タイトル頭）で、
# 直後に「者/社/団体/する/予定/…」が来ないもののみ拾う（誤検出防止）。
_INLINE_BOUNDARY = r"(?:^|[\s\t、,。！？!?「」【】〈〉『』()（）\[\]｜|/／・─—–\-＿_])"
_NAME_CHARS = r"[一-龥ぁ-んァ-ヴA-Za-z0-9・ー]"
_INLINE_ROLE = re.compile(
    rf"{_INLINE_BOUNDARY}"
    rf"({_NAME_CHARS}{{2,15}}?)"
    rf"({_LABEL_ALT})"
    r"(?!者|社|団体|企業|する|し[てた]|さ|により|予定|関連|参画|参加|募集)"
)

# 名前間の区切り。半角スペース単発は組織名内の可能性が高いので採用しない
_SEPARATORS = re.compile(r"[、,／/・|｜]+|\s{2,}")

# 打ち切り。長すぎる場合は末尾に他のメタ情報が混ざったとみなす
_MAX_SEGMENT_CHARS = 80
_MAX_NAME_CHARS = 60
_MIN_NAME_CHARS = 2

_KEY_MAP = {
    "主催": "organizer",
    "共催": "co_organizer",
    "協賛": "sponsor",
    "後援": "supporter",
    "協力": "cooperator",
}


@dataclass
class Organizers:
    organizer: list[str] = field(default_factory=list)
    co_organizer: list[str] = field(default_factory=list)
    sponsor: list[str] = field(default_factory=list)
    supporter: list[str] = field(default_factory=list)
    cooperator: list[str] = field(default_factory=list)

    def any(self) -> bool:
        return any(
            (self.organizer, self.co_organizer, self.sponsor, self.supporter, self.cooperator)
        )

    def to_dict(self) -> dict[str, list[str]]:
        return {
            "organizer": self.organizer,
            "co_organizer": self.co_organizer,
            "sponsor": self.sponsor,
            "supporter": self.supporter,
            "cooperator": self.cooperator,
        }


def _split_names(segment: str) -> list[str]:
    parts = _SEPARATORS.split(segment)
    out: list[str] = []
    for p in parts:
        name = p.strip(" 　:：/／、,・|｜-–—「」()（）")
        if _MIN_NAME_CHARS <= len(name) <= _MAX_NAME_CHARS:
            out.append(name)
    return out


_ROLE_KW_RE = re.compile("|".join(LABEL_KEYS))
_TRAILING_PARTICLE = re.compile(r"[がはをにでとのもよりへや]+$")


def _add(bucket: list[str], name: str) -> None:
    name = name.strip(" 　:：/／、,・|｜-–—「」()（）")
    if _MIN_NAME_CHARS <= len(name) <= _MAX_NAME_CHARS and name not in bucket:
        bucket.append(name)


def _add_inline(bucket: list[str], name: str) -> None:
    # インライン抽出の後処理: 助詞剥がし + 役割語を含む名前は誤検出とみなし棄却
    if _ROLE_KW_RE.search(name):
        return
    name = _TRAILING_PARTICLE.sub("", name.strip(" 　"))
    if _MIN_NAME_CHARS <= len(name) <= _MAX_NAME_CHARS and name not in bucket:
        bucket.append(name)


def extract(text: str) -> Organizers:
    result = Organizers()
    if not text:
        return result
    matches = list(_LABEL_HEAD.finditer(text))
    for i, m in enumerate(matches):
        label = m.group(1) or m.group(2)
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        segment = text[start:end]
        segment = re.split(r"[。\n\r]", segment, maxsplit=1)[0]
        if len(segment) > _MAX_SEGMENT_CHARS:
            segment = segment[:_MAX_SEGMENT_CHARS]
        for n in _split_names(segment):
            _add(getattr(result, _KEY_MAP[label]), n)

    # インライン形式（「〇〇主催」「〇〇協賛」など）
    for m in _INLINE_ROLE.finditer(text):
        name, label = m.group(1), m.group(2)
        _add_inline(getattr(result, _KEY_MAP[label]), name)

    return result
