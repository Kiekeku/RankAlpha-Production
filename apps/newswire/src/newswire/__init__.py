"""Newswire package: collectors, dedup, and prefilter.

Exports lightweight utilities so tests can import without running the service.
"""

from .dedup import canonicalize_url, cluster_near_duplicates, hamming_distance, simhash64
from .prefilter import MaterialityPrefilter, MaterialityResult

__all__ = [
    "MaterialityPrefilter",
    "MaterialityResult",
    "canonicalize_url",
    "simhash64",
    "hamming_distance",
    "cluster_near_duplicates",
]
