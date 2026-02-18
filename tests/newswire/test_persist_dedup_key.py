from __future__ import annotations

from apps.common.src.news_utils import persist as common_persist
from newswire import persist as newswire_persist


def test_build_dedup_key_hostless_urls_do_not_collapse() -> None:
    fp = 123456789
    u1 = "http:///example.com/news/one"
    u2 = "http:///another.com/news/two"

    c1 = common_persist._build_dedup_key(u1, fp)
    c2 = common_persist._build_dedup_key(u2, fp)
    n1 = newswire_persist._build_dedup_key(u1, fp)
    n2 = newswire_persist._build_dedup_key(u2, fp)

    assert c1 != c2
    assert n1 != n2


def test_build_dedup_key_hosted_urls_differ_for_different_paths() -> None:
    fp = 987654321
    u1 = "https://example.com/news/a"
    u2 = "https://example.com/news/b"

    c1 = common_persist._build_dedup_key(u1, fp)
    c2 = common_persist._build_dedup_key(u2, fp)
    n1 = newswire_persist._build_dedup_key(u1, fp)
    n2 = newswire_persist._build_dedup_key(u2, fp)

    assert c1 != c2
    assert n1 != n2


def test_build_dedup_key_hosted_urls_match_for_same_path_query_variants() -> None:
    fp = 444444444
    u1 = "https://example.com/news/a?utm_source=x"
    u2 = "https://example.com/news/a?utm_campaign=y"

    c1 = common_persist._build_dedup_key(u1, fp)
    c2 = common_persist._build_dedup_key(u2, fp)
    n1 = newswire_persist._build_dedup_key(u1, fp)
    n2 = newswire_persist._build_dedup_key(u2, fp)

    assert c1 == c2
    assert n1 == n2
