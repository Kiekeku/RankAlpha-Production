from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, Iterable, List, Tuple
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

TRACKING_QS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "gclid",
    "fbclid",
    "mc_cid",
    "mc_eid",
}

STOPWORDS = {
    "the",
    "a",
    "an",
    "for",
    "to",
    "in",
    "on",
    "of",
    "and",
    "or",
    "with",
    "by",
    "at",
    "from",
    "as",
    "into",
    "over",
    "under",
    "after",
    "before",
    "about",
    "into",
    "via",
    "is",
    "are",
    "be",
    "was",
    "were",
}


def canonicalize_url(url: str) -> str:
    """Return a deterministic canonical URL for dedup.

    - lowercase scheme/host
    - drop default ports
    - strip tracking query params
    - collapse repeated slashes
    - strip trailing slash (except root)
    """
    try:
        p = urlparse(url)
    except Exception:
        return url

    scheme = (p.scheme or "http").lower()
    netloc = (p.netloc or "").lower()
    if netloc.endswith(":80") and scheme == "http":
        netloc = netloc[:-3]
    if netloc.endswith(":443") and scheme == "https":
        netloc = netloc[:-4]

    # Normalize path: remove duplicate slashes
    path = re.sub(r"/+", "/", p.path or "/")
    if path != "/" and path.endswith("/"):
        path = path[:-1]

    # Remove known tracking params; keep stable order
    qs_pairs = [
        (k, v) for k, v in parse_qsl(p.query, keep_blank_values=False) if k not in TRACKING_QS
    ]
    query = urlencode(qs_pairs, doseq=True)

    canon = urlunparse((scheme, netloc, path, "", query, ""))
    return canon


def _tokenize(text: str) -> list[str]:
    text = (text or "").lower()
    # Word tokens (alphanum + $%.-)
    raw_words = re.findall(r"[a-z0-9$%\.\-]+", text)
    # Naive stemming for common verb/noun variants
    words = []
    for w in raw_words:
        base = w
        if len(base) > 4 and base.endswith("ing"):
            base = base[:-3]
        elif len(base) > 3 and base.endswith("ed"):
            base = base[:-2]
        elif len(base) > 3 and base.endswith("es"):
            base = base[:-2]
        elif len(base) > 3 and base.endswith("s"):
            base = base[:-1]
        words.append(base)
    # Character 3-gram shingles over a compressed string (spaces removed)
    compact = re.sub(r"\s+", "", text)
    shingles = [compact[i : i + 3] for i in range(max(0, len(compact) - 2))]
    return words + shingles


def simhash64(text: str, hash_bits: int = 64) -> int:
    """Compute a simple 64-bit simhash for the given text.

    This is a compact, dependency-free variant suitable for dedup/hamming distance checks.
    """
    if not text:
        return 0
    v = [0] * hash_bits
    for tok in _tokenize(text):
        # Per-token 64-bit hash
        h = int.from_bytes(hashlib.blake2b(tok.encode("utf-8"), digest_size=8).digest(), "big")
        # Weight: give word-like tokens a bit more influence than shingles
        w = 2 if re.match(r"^[a-z0-9$%\.\-]+$", tok) else 1
        for i in range(hash_bits):
            v[i] += w if (h >> i) & 1 else -w
    out = 0
    for i in range(hash_bits):
        if v[i] >= 0:
            out |= 1 << i
    return out


def hamming_distance(x: int, y: int) -> int:
    return (x ^ y).bit_count()


def cluster_near_duplicates(
    items: Iterable[Dict[str, Any]],
    text_fields: Tuple[str, ...] = ("title", "snippet"),
    max_hamming: int = 3,
) -> List[List[Dict[str, Any]]]:
    """Group items into clusters using URL canonicalization and SimHash proximity.

    - Exact URL canonical match goes into the same cluster.
    - Else, compute SimHash on concatenated `text_fields` and group if within `max_hamming`.
    Returns list of clusters (each cluster is a list of dicts).
    """
    items = list(items)
    if not items:
        return []

    # Precompute canon URLs and fingerprints
    for it in items:
        url = it.get("url") or it.get("link") or ""
        it["url_canonical"] = canonicalize_url(url)
        text = " ".join([str(it.get(f, "")) for f in text_fields])
        it["text_fp"] = simhash64(text)
        # store word set for fallback Jaccard similarity
        raw_ws = set(re.findall(r"[a-z0-9$%\.\-]+", (text or "").lower()))
        it["_word_set"] = {w for w in raw_ws if w not in STOPWORDS and len(w) > 1}

    # First, cluster by identical canonical URL
    by_url: Dict[str, List[Dict[str, Any]]] = {}
    for it in items:
        by_url.setdefault(it["url_canonical"], []).append(it)

    clusters: List[List[Dict[str, Any]]] = []
    consumed = set()
    # Each URL-bucket is a base cluster; within, we may still split if wildly different titles
    for bucket in by_url.values():
        if len(bucket) == 1:
            clusters.append(bucket)
            continue
        # Simple agglomerative by simhash within URL bucket
        local = []
        for it in bucket:
            if id(it) in consumed:
                continue
            c = [it]
            consumed.add(id(it))
            for jt in bucket:
                if id(jt) in consumed:
                    continue
                if hamming_distance(it["text_fp"], jt["text_fp"]) <= max_hamming:
                    c.append(jt)
                    consumed.add(id(jt))
                else:
                    # Fallback by Jaccard on word sets
                    ws_i, ws_j = it.get("_word_set", set()), jt.get("_word_set", set())
                    if ws_i and ws_j:
                        inter = len(ws_i & ws_j)
                        union = len(ws_i | ws_j)
                        if union > 0 and (inter / union) >= 0.5:
                            c.append(jt)
                            consumed.add(id(jt))
            local.append(c)
        clusters.extend(local)

    # Handle items with unique URLs: group by near-duplicate simhash
    # Collect all unique-URL items
    unique_items = [it for it in items if len(by_url[it["url_canonical"]]) == 1]
    visited = set()
    for i, it in enumerate(unique_items):
        if i in visited:
            continue
        group = [it]
        visited.add(i)
        for j in range(i + 1, len(unique_items)):
            if j in visited:
                continue
            jt = unique_items[j]
            if hamming_distance(it["text_fp"], jt["text_fp"]) <= max_hamming:
                group.append(jt)
                visited.add(j)
            else:
                ws_i, ws_j = it.get("_word_set", set()), jt.get("_word_set", set())
                if ws_i and ws_j:
                    inter = len(ws_i & ws_j)
                    union = len(ws_i | ws_j)
                    if union > 0 and (inter / union) >= 0.5:
                        group.append(jt)
                        visited.add(j)
        clusters.append(group)

    # Final merge: if cluster centroids are near-duplicates, merge clusters
    if len(clusters) > 1:
        centroids = [c[0] for c in clusters]
        merged: List[List[Dict[str, Any]]] = []
        used = [False] * len(clusters)
        for i, ci in enumerate(centroids):
            if used[i]:
                continue
            group = list(clusters[i])
            used[i] = True
            for j in range(i + 1, len(centroids)):
                if used[j]:
                    continue
                cj = centroids[j]
                if hamming_distance(ci["text_fp"], cj["text_fp"]) <= max_hamming:
                    group.extend(clusters[j])
                    used[j] = True
                else:
                    ws_i, ws_j = ci.get("_word_set", set()), cj.get("_word_set", set())
                    if ws_i and ws_j:
                        inter = len(ws_i & ws_j)
                        union = len(ws_i | ws_j)
                        if union > 0 and (inter / union) >= 0.5:
                            group.extend(clusters[j])
                            used[j] = True
            merged.append(group)
        clusters = merged

    return clusters
