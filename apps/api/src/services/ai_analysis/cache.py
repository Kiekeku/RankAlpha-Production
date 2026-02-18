from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional, Sequence
from uuid import UUID

from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.src.cache import _get_client as get_redis_client
from apps.api.src.database import SessionLocal
from apps.api.src.settings import Settings
from apps.api.src.utils.cache_codec import (
    deserialize_compressed_json,
    serialize_compressed_json,
)
from apps.common.src.models import DimStock, FactAiStockAnalysis, VwAiAnalysisFull
from apps.common.src.observability import (
    get_or_create_counter,
    get_or_create_histogram,
)

from .utils import compute_proximity_for_analysis, load_precomputed_proximity, row_to_dict

AI_CACHE_HITS = get_or_create_counter(
    "ai_analysis_cache_hits_total",
    "Cache hits for AI analysis lookups",
)
AI_CACHE_MISSES = get_or_create_counter(
    "ai_analysis_cache_misses_total",
    "Cache misses for AI analysis lookups",
)
AI_CACHE_WARMS = get_or_create_counter(
    "ai_analysis_cache_warm_total",
    "Warm operations for AI analysis cache",
)
AI_CACHE_WARM_FAILURES = get_or_create_counter(
    "ai_analysis_cache_warm_failures_total",
    "Failed warm operations for AI analysis cache",
)
AI_CACHE_STALES = get_or_create_counter(
    "ai_analysis_cache_stales_total",
    "Stale AI analysis cache entries detected",
)
AI_CACHE_WARM_SECONDS = get_or_create_histogram(
    "ai_analysis_cache_warm_seconds",
    "Duration of AI analysis warm operations",
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)


def _serialize(payload: dict[str, Any]) -> str:
    return serialize_compressed_json(payload)


def _deserialize(data: str) -> dict[str, Any]:
    return deserialize_compressed_json(data)


@dataclass(slots=True)
class AiAnalysisCacheEntry:
    payload: dict[str, Any]
    refreshed_at: str

    def to_dict(self) -> dict[str, Any]:
        return {"payload": self.payload, "refreshed_at": self.refreshed_at}


class AiAnalysisCache:
    """Read-through cache for AI analysis lookups."""

    def __init__(self, *, ttl_seconds: Optional[int] = None) -> None:
        settings = Settings()
        default_ttl = int(getattr(settings, "ai_analysis_cache_ttl_seconds", None) or 6 * 3600)
        self.ttl_seconds = int(ttl_seconds or default_ttl)
        self.meta_ttl_seconds = max(self.ttl_seconds, 6 * 3600)

    @staticmethod
    def _latest_key(symbol: str, include_proximity: bool) -> str:
        suffix = "prox" if include_proximity else "plain"
        return f"ai:latest:{symbol.upper()}:{suffix}"

    @staticmethod
    def _detail_key(analysis_id: UUID | str, include_proximity: bool) -> str:
        suffix = "prox" if include_proximity else "plain"
        return f"ai:analysis:{str(analysis_id)}:{suffix}"

    def _get(self, key: str) -> Optional[AiAnalysisCacheEntry]:
        try:
            client = get_redis_client()
            raw = client.get(key)
        except (RedisError, ConnectionError, OSError):
            AI_CACHE_MISSES.inc()
            return None
        if not raw:
            AI_CACHE_MISSES.inc()
            return None
        try:
            data = _deserialize(raw)
            entry = AiAnalysisCacheEntry(
                payload=data.get("payload", {}),
                refreshed_at=data.get("refreshed_at", ""),
            )
            AI_CACHE_HITS.inc()
            return entry
        except Exception:
            AI_CACHE_WARM_FAILURES.inc()
            return None

    def _set(self, key: str, entry: AiAnalysisCacheEntry) -> None:
        try:
            client = get_redis_client()
            serialized = _serialize(entry.to_dict())
            client.setex(key, self.ttl_seconds, serialized)
        except (RedisError, ConnectionError, OSError):
            AI_CACHE_WARM_FAILURES.inc()

    def get_latest(self, symbol: str, *, include_proximity: bool) -> Optional[dict[str, Any]]:
        key = self._latest_key(symbol, include_proximity)
        entry = self._get(key)
        if not entry:
            return None
        payload = entry.payload
        # If a cached payload has organic targets but no computed summary fields, treat as stale.
        try:
            organic = payload.get("human_analyst_targets_organic")
            count = payload.get("human_analyst_target_count")
            has_organic = False
            if isinstance(organic, list):
                has_organic = bool(organic)
            elif isinstance(organic, str):
                s = organic.strip()
                has_organic = bool(s) and s not in ("[]", "{}")
            if has_organic and count in (None, ""):
                AI_CACHE_STALES.inc()
                AI_CACHE_MISSES.inc()
                return None
        except Exception:
            pass
        return payload

    def get_detail(
        self, analysis_id: UUID | str, *, include_proximity: bool
    ) -> Optional[dict[str, Any]]:
        key = self._detail_key(analysis_id, include_proximity)
        entry = self._get(key)
        if not entry:
            return None
        payload = entry.payload
        try:
            organic = payload.get("human_analyst_targets_organic")
            count = payload.get("human_analyst_target_count")
            has_organic = False
            if isinstance(organic, list):
                has_organic = bool(organic)
            elif isinstance(organic, str):
                s = organic.strip()
                has_organic = bool(s) and s not in ("[]", "{}")
            if has_organic and count in (None, ""):
                AI_CACHE_STALES.inc()
                AI_CACHE_MISSES.inc()
                return None
        except Exception:
            pass
        return payload if entry else None

    def warm_latest(
        self,
        symbol: str,
        *,
        include_proximity: bool,
        session: Session | None = None,
    ) -> Optional[dict[str, Any]]:
        AI_CACHE_WARMS.inc()
        start = datetime.utcnow()
        local_session: Session | None = None
        try:
            db = session
            if db is None:
                local_session = SessionLocal()
                db = local_session

            sym = symbol.upper()
            latest_id = db.execute(
                select(FactAiStockAnalysis.analysis_id)
                .join(DimStock, DimStock.stock_key == FactAiStockAnalysis.stock_key)
                .where(
                    DimStock.symbol == sym,
                    DimStock.is_active.is_(True),
                )
                .order_by(
                    FactAiStockAnalysis.date_key.desc(),
                    FactAiStockAnalysis.load_ts.desc(),
                    FactAiStockAnalysis.analysis_id.desc(),
                )
                .limit(1)
            ).scalar_one_or_none()
            if not latest_id:
                return None
            payload = self._load_analysis_payload(
                db, latest_id, include_proximity=include_proximity
            )
            if not payload:
                return None
            entry = AiAnalysisCacheEntry(payload=payload, refreshed_at=_now_iso())
            self._set(self._latest_key(sym, include_proximity), entry)
            self._set(self._detail_key(latest_id, include_proximity), entry)
            return payload
        except Exception:
            AI_CACHE_WARM_FAILURES.inc()
            return None
        finally:
            AI_CACHE_WARM_SECONDS.observe((datetime.utcnow() - start).total_seconds())
            if local_session is not None:
                local_session.close()

    def warm_detail(
        self,
        analysis_id: UUID | str,
        *,
        include_proximity: bool,
        session: Session | None = None,
    ) -> Optional[dict[str, Any]]:
        AI_CACHE_WARMS.inc()
        start = datetime.utcnow()
        local_session: Session | None = None
        try:
            db = session
            if db is None:
                local_session = SessionLocal()
                db = local_session

            payload = self._load_analysis_payload(
                db, analysis_id, include_proximity=include_proximity
            )
            if not payload:
                return None
            entry = AiAnalysisCacheEntry(payload=payload, refreshed_at=_now_iso())
            self._set(self._detail_key(analysis_id, include_proximity), entry)
            return payload
        except Exception:
            AI_CACHE_WARM_FAILURES.inc()
            return None
        finally:
            AI_CACHE_WARM_SECONDS.observe((datetime.utcnow() - start).total_seconds())
            if local_session is not None:
                local_session.close()

    def warm_latest_many(
        self,
        symbols: Sequence[str],
        *,
        include_proximity: bool,
        session: Session | None = None,
    ) -> dict[str, bool]:
        results: dict[str, bool] = {}
        for sym in symbols:
            entry = self.warm_latest(sym, include_proximity=include_proximity, session=session)
            results[sym.upper()] = bool(entry)
        return results

    def warm_detail_many(
        self,
        analysis_ids: Sequence[UUID | str],
        *,
        include_proximity: bool,
        session: Session | None = None,
    ) -> dict[str, bool]:
        results: dict[str, bool] = {}
        for aid in analysis_ids:
            entry = self.warm_detail(aid, include_proximity=include_proximity, session=session)
            results[str(aid)] = bool(entry)
        return results

    def invalidate_symbols(self, symbols: Sequence[str]) -> int:
        deleted = 0
        try:
            client = get_redis_client()
        except Exception:
            return 0
        keys = []
        for sym in symbols:
            upper = sym.upper()
            keys.append(self._latest_key(upper, True))
            keys.append(self._latest_key(upper, False))
        if keys:
            try:
                deleted = client.delete(*keys)
            except Exception:
                deleted = 0
        return deleted

    def invalidate_analyses(self, analysis_ids: Sequence[UUID | str]) -> int:
        deleted = 0
        try:
            client = get_redis_client()
        except Exception:
            return 0
        keys = []
        for aid in analysis_ids:
            keys.append(self._detail_key(aid, True))
            keys.append(self._detail_key(aid, False))
        if keys:
            try:
                deleted = client.delete(*keys)
            except Exception:
                deleted = 0
        return deleted

    def _load_analysis_payload(
        self,
        db: Session,
        analysis_id: UUID | str,
        *,
        include_proximity: bool,
    ) -> Optional[dict[str, Any]]:
        row = db.execute(
            select(VwAiAnalysisFull)
            .join(DimStock, DimStock.symbol == VwAiAnalysisFull.symbol)
            .where(
                VwAiAnalysisFull.analysis_id == analysis_id,
                DimStock.is_active.is_(True),
            )
        ).scalar_one_or_none()
        if not row:
            return None
        payload = row_to_dict(row)
        analysis_key = payload.get("analysis_id")
        if include_proximity and analysis_key:
            prox = load_precomputed_proximity(db, [analysis_key]).get(str(analysis_key))
            if prox is None:
                prox = compute_proximity_for_analysis(db, analysis_key, payload.get("symbol"))
            if prox:
                payload.update(prox)
        return payload


def _now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
