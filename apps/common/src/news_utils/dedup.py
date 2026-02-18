from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, Iterable, List, Tuple
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

TRACKING_QS = {
    "_ga",
    "_gl",
    "cmp",
    "cmpid",
    "fb_action_ids",
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "utm_id",
    "utm_name",
    "utm_reader",
    "utm_viz_id",
    "utm_pubreferrer",
    "gclid",
    "fbclid",
    "msclkid",
    "s_cid",
    "ncid",
    "oref",
    "ocid",
    "share",
    "spm",
    "igshid",
    "mkt_tok",
    "mc_tid",
    "mc_cid",
    "mc_eid",
    "ref",
    "ref_src",
    "ref_url",
}


def canonicalize_url(url: str) -> str:
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
    path = re.sub(r"/+", "/", p.path or "/")
    if path != "/" and path.endswith("/"):
        path = path[:-1]
    qs_pairs = [
        (k, v)
        for k, v in parse_qsl(p.query, keep_blank_values=False)
        if k.lower() not in TRACKING_QS
    ]
    query = urlencode(sorted(qs_pairs), doseq=True)
    return urlunparse((scheme, netloc, path, "", query, ""))


def _tokenize(text: str) -> list[str]:
    text = (text or "").lower()
    raw_words = re.findall(r"[a-z0-9$%\.\-]+", text)
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
    compact = re.sub(r"\s+", "", text)
    shingles = [compact[i : i + 3] for i in range(max(0, len(compact) - 2))]
    return words + shingles


def simhash64(text: str, hash_bits: int = 64) -> int:
    if not text:
        return 0
    v = [0] * hash_bits
    for tok in _tokenize(text):
        h = int.from_bytes(hashlib.blake2b(tok.encode("utf-8"), digest_size=8).digest(), "big")
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
    items = list(items)
    if not items:
        return []
    for it in items:
        url = it.get("url") or it.get("link") or ""
        it["url_canonical"] = canonicalize_url(url)
        text = " ".join([str(it.get(f, "")) for f in text_fields])
        it["text_fp"] = simhash64(text)
        raw_ws = set(re.findall(r"[a-z0-9$%\.\-]+", (text or "").lower()))
        stop = {
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
        it["_word_set"] = {w for w in raw_ws if w not in stop and len(w) > 1}

    by_url: Dict[str, List[Dict[str, Any]]] = {}
    for it in items:
        by_url.setdefault(it["url_canonical"], []).append(it)

    clusters: List[List[Dict[str, Any]]] = []
    consumed = set()
    for bucket in by_url.values():
        if len(bucket) == 1:
            clusters.append(bucket)
            continue
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
                    ws_i, ws_j = it.get("_word_set", set()), jt.get("_word_set", set())
                    if ws_i and ws_j:
                        inter = len(ws_i & ws_j)
                        union = len(ws_i | ws_j)
                        if union > 0 and (inter / union) >= 0.5:
                            c.append(jt)
                            consumed.add(id(jt))
            local.append(c)
        clusters.extend(local)

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
