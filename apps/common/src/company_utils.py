"""Helpers for normalizing company names for display."""

from __future__ import annotations

import re
import time
from typing import Sequence

_SUFFIX_PATTERNS: Sequence[Sequence[str]] = (
    ("common", "stock"),
    ("common", "shares"),
    ("common",),
    ("stock",),
    ("sponsored", "adr"),
    ("adr",),
    ("adr", "representing", "one", "ordinary", "share"),
    ("preferred", "stock"),
    ("preference", "shares"),
    ("ltd",),
    ("ltd", "plc"),
    ("limited",),
    ("corp",),
    ("corporation",),
    ("inc",),
    ("incorporated",),
    ("company",),
    ("co",),
    ("plc",),
    ("llc",),
    ("l.l.c",),
    ("llp",),
    ("lp",),
    ("sa",),
    ("nv",),
    ("ag",),
    ("spa",),
    ("s.p.a",),
    ("holding",),
    ("holdings",),
    ("holdings", "plc"),
    ("partners", "lp"),
    ("unit",),
    ("class", "a"),
    ("class", "b"),
    ("class", "c"),
    ("class", "d"),
    ("class", "e"),
    ("class", "f"),
)

_PUNCT_RE = re.compile(r"[.,/&-]+$")
_CACHE_TTL_SECONDS = 60 * 60 * 24  # 1 day
_NAME_CACHE: dict[str, tuple[float, str]] = {}  # simple TTL cache for sanitized names


def _normalize_token(token: str) -> str:
    token = token.strip()
    if not token:
        return ""
    token = re.sub(r"[.,]", "", token)
    return token.lower()


def _tokens_without_trailing_affixes(
    tokens: list[str], suffixes: Sequence[Sequence[str]]
) -> list[str]:
    if not tokens:
        return tokens

    normalized = [_normalize_token(t) for t in tokens]
    end = len(tokens)

    # strip trailing suffix groups
    while end > 0:
        removed = False
        for pattern in suffixes:
            length = len(pattern)
            if length == 0 or end - length < 0:
                continue
            window = normalized[end - length : end]
            if all(window[i] == pattern[i] for i in range(length)):
                end -= length
                # drop trailing punctuation-only tokens
                while end > 0 and _PUNCT_RE.match(tokens[end - 1]):
                    end -= 1
                removed = True
                break
        if not removed:
            break

    # remove any remaining suffix pattern occurrences inside the name
    if end > 1:
        filtered_tokens: list[str] = []
        filtered_normalized: list[str] = []
        i = 0
        while i < end:
            matched = False
            for pattern in suffixes:
                length = len(pattern)
                if length == 0 or i + length > end:
                    continue
                window = normalized[i : i + length]
                if all(window[j] == pattern[j] for j in range(length)):
                    matched = True
                    i += length
                    break
            if matched:
                continue
            filtered_tokens.append(tokens[i])
            filtered_normalized.append(normalized[i])
            i += 1
        tokens = filtered_tokens
        normalized = filtered_normalized
        end = len(tokens)

    return tokens[:end]


def _strip_trailing_punct(token: str) -> str:
    return _PUNCT_RE.sub("", token)


def clean_company_name(name: str | None) -> str | None:
    """Return a version of *name* with redundant suffixes removed.

    The logic targets common corporate designations (Inc., Corp, PLC, ADR, etc.)
    that add noise in UI displays. If the cleaning step removes all tokens, the
    original name is returned to avoid an empty label.
    """

    if not name:
        return name

    trimmed = name.strip()
    if not trimmed:
        return trimmed

    cached = _NAME_CACHE.get(trimmed)
    now = time.time()
    if cached:
        cached_at, cached_value = cached
        if now - cached_at < _CACHE_TTL_SECONDS:
            return cached_value

    tokens = trimmed.split()
    if len(tokens) <= 1:
        if len(_NAME_CACHE) > 4096:
            _NAME_CACHE.clear()
        _NAME_CACHE[trimmed] = (now, trimmed)
        return trimmed

    kept = [
        _strip_trailing_punct(t) for t in _tokens_without_trailing_affixes(tokens, _SUFFIX_PATTERNS)
    ]
    result = " ".join(t for t in kept if t).strip()
    cleaned = result or trimmed
    if len(_NAME_CACHE) > 4096:
        _NAME_CACHE.clear()
    _NAME_CACHE[trimmed] = (now, cleaned)
    return cleaned


__all__ = ["clean_company_name"]
