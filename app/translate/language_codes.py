from __future__ import annotations

_BAIDU_MT_LANGUAGE_ALIASES = {
    "auto": "auto",
    "en": "en",
    "english": "en",
    "us": "en",
    "zh": "zh",
    "zh-cn": "zh",
    "zh-hans": "zh",
    "zh_cn": "zh",
    "zh_hans": "zh",
    "chinese": "zh",
    "cn": "zh",
}


def to_baidu_mt_language(value: str) -> str:
    normalized = value.strip().lower()
    if not normalized:
        return "auto"
    if normalized in _BAIDU_MT_LANGUAGE_ALIASES:
        return _BAIDU_MT_LANGUAGE_ALIASES[normalized]
    return normalized.split("-", maxsplit=1)[0].split("_", maxsplit=1)[0]
