from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import time


@dataclass
class NewswireSettings:
    sources: list[str]
    premkt_start: time
    premkt_end: time
    tz: str
    materiality_threshold: float
    tfidf_model_path: str | None
    gdelt_period_sec: int
    serper_period_sec: int
    rss_period_sec: int
    gdelt_period_pre_sec: int | None
    serper_period_pre_sec: int | None
    rss_period_pre_sec: int | None

    @classmethod
    def from_env(cls) -> "NewswireSettings":
        def _parse_time(val: str, default: time) -> time:
            try:
                h, m = val.split(":", 1)
                return time(hour=int(h), minute=int(m))
            except Exception:
                return default

        sources = [s.strip() for s in os.environ.get("NEWS_SOURCES", "rss").split(",") if s.strip()]
        premkt_start = _parse_time(os.environ.get("NEWS_PREMARKET_START", "07:00"), time(7, 0))
        premkt_end = _parse_time(os.environ.get("NEWS_PREMARKET_END", "09:15"), time(9, 15))
        tz = os.environ.get("NEWS_TIMEZONE", "America/New_York")
        try:
            mat = float(os.environ.get("NEWS_MATERIALITY_THRESHOLD", "0.80"))
        except Exception:
            mat = 0.80

        tfidf_path = os.environ.get("NEWS_TFIDF_MODEL_PATH")
        try:
            gdelt_period = int(os.environ.get("NEWS_GDELT_PERIOD_SEC", "900"))  # default 15 minutes
        except Exception:
            gdelt_period = 900
        try:
            serper_period = int(
                os.environ.get(
                    "NEWS_SERPER_PERIOD_SEC", os.environ.get("NEWS_POLL_INTERVAL", "300")
                )
            )
        except Exception:
            serper_period = 300
        try:
            rss_period = int(
                os.environ.get("NEWS_RSS_PERIOD_SEC", os.environ.get("NEWS_POLL_INTERVAL", "300"))
            )
        except Exception:
            rss_period = 300
        # Optional pre-market overrides
        try:
            gdelt_period_pre = int(os.environ.get("NEWS_GDELT_PERIOD_PRE_SEC", "0")) or None
        except Exception:
            gdelt_period_pre = None
        try:
            serper_period_pre = int(os.environ.get("NEWS_SERPER_PERIOD_PRE_SEC", "0")) or None
        except Exception:
            serper_period_pre = None
        try:
            rss_period_pre = int(os.environ.get("NEWS_RSS_PERIOD_PRE_SEC", "0")) or None
        except Exception:
            rss_period_pre = None
        return cls(
            sources=sources,
            premkt_start=premkt_start,
            premkt_end=premkt_end,
            tz=tz,
            materiality_threshold=mat,
            tfidf_model_path=tfidf_path,
            gdelt_period_sec=gdelt_period,
            serper_period_sec=serper_period,
            rss_period_sec=rss_period,
            gdelt_period_pre_sec=gdelt_period_pre,
            serper_period_pre_sec=serper_period_pre,
            rss_period_pre_sec=rss_period_pre,
        )
