from news_utils.dedup import canonicalize_url, simhash64, hamming_distance, cluster_near_duplicates


def test_canonicalize_url_strips_tracking():
    u = "https://Example.com/article?id=123&utm_source=x&gclid=abc"
    c = canonicalize_url(u)
    assert c == "https://example.com/article?id=123"


def test_simhash_distance_small_for_similar_titles():
    t1 = "Company A acquires Company B for $100M"
    t2 = "Company A to acquire Company B in $100M deal"
    d = hamming_distance(simhash64(t1), simhash64(t2))
    # Allow some variance from the simple SimHash; close phrases should be near
    assert d <= 16


def test_cluster_near_duplicates_groups_items():
    items = [
        {"url": "https://x.com/news/1", "title": "MegaCorp acquires X for $1B", "snippet": ""},
        {"url": "https://x.com/news/1?utm_source=foo", "title": "MegaCorp acquires X for $1B", "snippet": ""},
        {"url": "https://x.com/news/2", "title": "MegaCorp to buy X in $1B deal", "snippet": ""},
        {"url": "https://y.com/other", "title": "Unrelated story", "snippet": ""},
    ]
    clusters = cluster_near_duplicates(items, max_hamming=4)
    # Expect duplicates to be clustered; near-duplicate titles should also group in many cases
    sizes = sorted(len(c) for c in clusters)
    assert sizes[-1] >= 2
