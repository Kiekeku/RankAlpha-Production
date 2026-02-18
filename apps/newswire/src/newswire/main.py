from __future__ import annotations

import asyncio
import logging
import os
import zoneinfo
from datetime import datetime, time, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Dict, List

from sqlalchemy import or_

from apps.common.src.logging import setup_logging
from apps.common.src.models import DimNewsCluster, FactNewsEvent, FactNewsImpact, FactNewsRaw
from apps.common.src.news_utils.dedup import cluster_near_duplicates
from apps.common.src.news_utils.entity_map import map_entities_to_symbols
from apps.common.src.news_utils.persist import (
    create_cluster,
    insert_event,
    insert_impacts,
    upsert_raw,
)
from apps.common.src.news_utils.prefilter import MaterialityPrefilter
from apps.common.src.news_utils.queue import enqueue_sentiment_analysis

from .body_store import store_body_if_needed
from .collector.gdelt import poll_gdelt
from .collector.rss import poll_rss
from .collector.serper import poll_serper
from .cursor import load_cursors, save_cursors
from .db import session_factory
from .llm import analyze_event_cluster
from .schedule import enqueue_analysis_for_stock
from .settings import NewswireSettings

logger = logging.getLogger(__name__)


def _setup_logging() -> None:
    level_name = os.environ.get("NEWS_LOG_LEVEL") or os.environ.get("LOG_LEVEL") or "INFO"
    setup_logging(level_name)
    logger.debug("Logging initialized at level %s", level_name.upper())


def _parse_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    s = str(value).strip()
    if not s:
        return None
    # ISO 8601
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        pass
    # RFC 2822 / RSS date strings
    try:
        dt = parsedate_to_datetime(s)
        if dt is not None:
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
    except Exception:
        pass
    # GDELT yyyymmddhhmmss
    if s.isdigit() and len(s) == 14:
        try:
            return datetime.strptime(s, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
        except Exception:
            pass
    # Epoch seconds or ms
    try:
        iv = int(s)
        if len(s) > 10:
            iv //= 1000
        return datetime.fromtimestamp(iv, tz=timezone.utc)
    except Exception:
        return None


def _cap_backfill(since: datetime | None, now: datetime, source: str) -> datetime | None:
    """Limit catch-up windows to keep the collector responsive after long downtime.

    Set NEWS_MAX_BACKFILL_HOURS=0 to disable.
    """
    if since is None:
        return None
    try:
        max_hours = int(os.environ.get("NEWS_MAX_BACKFILL_HOURS", "72"))
    except Exception:
        max_hours = 72
    if max_hours <= 0:
        return since
    cap = now - timedelta(hours=max_hours)
    if since < cap:
        logger.warning(
            "Capping %s backfill window: since=%s -> %s (NEWS_MAX_BACKFILL_HOURS=%s)",
            source,
            since.isoformat(),
            cap.isoformat(),
            max_hours,
        )
        return cap
    return since


async def _collect_once(
    settings: NewswireSettings,
    last_seen: Dict[str, datetime | None],
    last_run: Dict[str, datetime | None],
) -> tuple[List[Dict[str, Any]], Dict[str, datetime | None], Dict[str, datetime | None]]:
    docs: List[Dict[str, Any]] = []
    updated = dict(last_seen)

    overlap_min = int(os.environ.get("NEWS_CURSOR_OVERLAP_MIN", "2"))
    grace = timedelta(minutes=max(0, overlap_min))
    now = datetime.now(tz=timezone.utc)
    epoch_floor = datetime(1970, 1, 1, tzinfo=timezone.utc)
    for key, val in list(updated.items()):
        if val is None:
            continue
        if isinstance(val, datetime) and val <= epoch_floor:
            updated[key] = None
            continue
        if val.tzinfo is None:
            val = val.replace(tzinfo=timezone.utc)
        updated[key] = val

    tasks: List[tuple[str, asyncio.Task]] = []
    # Determine due windows per source using per-source periods
    if "gdelt" in settings.sources:
        premkt = _in_premarket(settings, now)
        period = (
            settings.gdelt_period_pre_sec
            if premkt and settings.gdelt_period_pre_sec
            else settings.gdelt_period_sec
        )
        due = True
        if last_run.get("gdelt") is not None:
            due = (now - last_run["gdelt"]) >= timedelta(seconds=max(60, int(period)))
        if due:
            gdelt_query = os.environ.get(
                "GDELT_QUERY",
                (
                    "(sourcecountry:US OR sourcecountry:CA) "
                    "AND (earnings OR guidance OR merger OR acquisition OR bankruptcy "
                    'OR "SEC" OR "FDA" OR "DOJ" OR "CFTC" OR recall OR dividend OR layoffs)'
                ),
            )
            since = updated.get("gdelt")
            if since and since <= epoch_floor:
                since = None
            elif since:
                since = max(epoch_floor, since - grace)
            since = _cap_backfill(since, now, "gdelt")
            logger.debug(
                "Scheduling GDELT poll (premarket=%s) since=%s until=%s query=%s",
                premkt,
                since.isoformat() if since else None,
                now.isoformat(),
                gdelt_query,
            )
            tasks.append(
                (
                    "gdelt",
                    asyncio.create_task(
                        _consume_stream(poll_gdelt(since=since, until=now, query=gdelt_query))
                    ),
                )
            )
        else:
            last = last_run.get("gdelt") or now
            next_eta = (last + timedelta(seconds=max(60, int(period)))) - now
            logger.debug(
                "Skipping GDELT poll; %.1fs until next window", max(0.0, next_eta.total_seconds())
            )
    if "serper" in settings.sources:
        premkt = _in_premarket(settings, now)
        period = (
            settings.serper_period_pre_sec
            if premkt and settings.serper_period_pre_sec
            else settings.serper_period_sec
        )
        due = True
        if last_run.get("serper") is not None:
            due = (now - last_run["serper"]) >= timedelta(seconds=max(60, int(period)))
        if due:
            since = updated.get("serper")
            if since and since <= epoch_floor:
                since = None
            elif since:
                since = max(epoch_floor, since - grace)
            since = _cap_backfill(since, now, "serper")
            logger.debug(
                "Scheduling Serper poll (premarket=%s) since=%s until=%s",
                premkt,
                since.isoformat() if since else None,
                now.isoformat(),
            )
            tasks.append(
                (
                    "serper",
                    asyncio.create_task(_consume_stream(poll_serper(since=since, until=now))),
                )
            )
        else:
            last = last_run.get("serper") or now
            next_eta = (last + timedelta(seconds=max(60, int(period)))) - now
            logger.debug(
                "Skipping Serper poll; %.1fs until next window", max(0.0, next_eta.total_seconds())
            )

    if "rss" in settings.sources:
        premkt = _in_premarket(settings, now)
        period = (
            settings.rss_period_pre_sec
            if premkt and settings.rss_period_pre_sec
            else settings.rss_period_sec
        )
        due = True
        if last_run.get("rss") is not None:
            due = (now - last_run["rss"]) >= timedelta(seconds=max(60, int(period)))
        if due:
            since = updated.get("rss")
            if since and since <= epoch_floor:
                since = None
            elif since:
                since = max(epoch_floor, since - grace)
            since = _cap_backfill(since, now, "rss")
            logger.debug(
                "Scheduling RSS poll (premarket=%s) since=%s until=%s",
                premkt,
                since.isoformat() if since else None,
                now.isoformat(),
            )
            tasks.append(
                ("rss", asyncio.create_task(_consume_stream(poll_rss(since=since, until=now))))
            )
        else:
            last = last_run.get("rss") or now
            next_eta = (last + timedelta(seconds=max(60, int(period)))) - now
            logger.debug(
                "Skipping RSS poll; %.1fs until next window", max(0.0, next_eta.total_seconds())
            )

    if tasks:
        done = await asyncio.gather(*[t for _, t in tasks], return_exceptions=True)
        for (name, _), part in zip(tasks, done):
            if isinstance(part, list):
                docs.extend(part)
                max_seen = updated.get(name)
                parsed_any = False
                for d in part:
                    ts = _parse_dt(d.get("published_at"))
                    if ts is None:
                        continue
                    parsed_any = True
                    if max_seen is None or ts > max_seen:
                        max_seen = ts
                # If we couldn't parse any timestamps, advance to "now" to avoid replaying the same window forever.
                if part and not parsed_any:
                    max_seen = now
                updated[name] = max_seen or updated.get(name)
                last_run[name] = now
                logger.info(
                    "%s poll returned %s documents; latest_ts=%s",
                    name,
                    len(part),
                    (max_seen or now).isoformat(),
                )
            elif isinstance(part, Exception):
                logger.warning(
                    "%s poll errored: %r",
                    name,
                    part,
                    exc_info=(type(part), part, part.__traceback__),
                )
                # Avoid hot-looping a failing source; next attempt will respect per-source cadence.
                last_run[name] = now
    else:
        logger.debug("No sources were due this cycle (sources=%s)", settings.sources)

    return docs, updated, last_run


async def _consume_stream(aiter):
    out = []
    async for item in aiter:
        out.append(item)
    return out


def _in_premarket(settings: NewswireSettings, now: datetime) -> bool:
    tz = zoneinfo.ZoneInfo(settings.tz)
    local = now.astimezone(tz)
    start = time(settings.premkt_start.hour, settings.premkt_start.minute, tzinfo=tz)
    end = time(settings.premkt_end.hour, settings.premkt_end.minute, tzinfo=tz)
    return start <= local.timetz() <= end


async def run_forever():
    _setup_logging()
    settings = NewswireSettings.from_env()
    logger.info(
        "Newswire starting: sources=%s premkt=%s-%s %s materiality>=%.2f llm_auto=%s sentiment_enqueue=%s",
        ",".join(settings.sources),
        settings.premkt_start.strftime("%H:%M"),
        settings.premkt_end.strftime("%H:%M"),
        settings.tz,
        settings.materiality_threshold,
        os.environ.get("NEWS_LLM_AUTO", "false"),
        os.environ.get(
            "NEWS_SENTIMENT_ENQUEUE_ENABLED", os.environ.get("NEWS_SENTIMENT_QUEUE_ENABLED", "true")
        ),
    )
    logger.debug(
        "Polling cadence: GDELT=%ss (pre=%s) SERPER=%ss (pre=%s) RSS=%ss (pre=%s) poll_interval=%s/%s",
        settings.gdelt_period_sec,
        settings.gdelt_period_pre_sec or "n/a",
        settings.serper_period_sec,
        settings.serper_period_pre_sec or "n/a",
        settings.rss_period_sec,
        settings.rss_period_pre_sec or "n/a",
        os.environ.get("NEWS_POLL_INTERVAL", "180"),
        os.environ.get(
            "NEWS_POLL_INTERVAL_PRE", os.environ.get("NEWS_POLL_INTERVAL_Premarket", "60")
        ),
    )
    prefilter = MaterialityPrefilter(model_path=settings.tfidf_model_path)
    SessionLocal = session_factory()

    # Optional bounded runtime for Airflow blitz runs
    run_minutes_env = os.environ.get("NEWS_RUN_MINUTES")
    run_until = None
    if run_minutes_env:
        try:
            mins = int(run_minutes_env)
            run_until = datetime.now(tz=zoneinfo.ZoneInfo("UTC")) + timedelta(minutes=mins)
        except Exception:
            run_until = None

    # Track per-source last seen timestamps (UTC) – persisted in DB
    with SessionLocal() as _s:
        try:
            last_seen = load_cursors(_s)
        except Exception:
            last_seen = {"gdelt": None, "serper": None, "rss": None}
    # Track last-run times in-memory to respect per-source cadence
    last_run: Dict[str, datetime | None] = {"gdelt": None, "serper": None, "rss": None}

    while True:
        try:
            docs, last_seen, last_run = await _collect_once(settings, last_seen, last_run)
            if docs:
                logger.debug("Processing collected docs: total=%s", len(docs))
                # Persist raw; enrich docs with raw_id and canonical URL
                with SessionLocal() as db:  # type: Session
                    try:
                        logger.info("Starting raw upsert: incoming=%s", len(docs))
                        docs = upsert_raw(db, docs)
                        logger.info("Raw upsert complete: records=%s", len(docs))
                        clusters = cluster_near_duplicates(docs)
                        logger.info("Clustering complete: clusters=%s", len(clusters))
                        created_event_ids = []
                        for cl in clusters:
                            # Choose first as centroid
                            centroid = cl[0]
                            member_ids = [d["raw_id"] for d in cl if d.get("raw_id")]
                            simhash = int(centroid.get("text_fp") or 0)
                            try:
                                with db.begin_nested():
                                    cluster_row = create_cluster(
                                        db,
                                        centroid_raw_id=centroid.get("raw_id"),
                                        simhash=simhash,
                                        members_raw_ids=member_ids,
                                    )
                                    # Prefilter score on centroid
                                    m = prefilter.score(
                                        title=str(centroid.get("title", "")),
                                        snippet=str(centroid.get("snippet", "")),
                                        source_domain=str(centroid.get("source_domain", "")),
                                    )
                                    # If score passes the body gate, fetch+store body (domain-allowlisted, size-capped)
                                    try:
                                        body_result = store_body_if_needed(
                                            db,
                                            raw_id=centroid.get("raw_id"),
                                            url=str(
                                                centroid.get("url_canonical")
                                                or centroid.get("url")
                                                or ""
                                            ),
                                            prefilter_score=float(m.score or 0.0),
                                        )
                                        centroid["body_fetch_status"] = (
                                            body_result.status
                                        )  # diagnostic hint
                                        logger.debug(
                                            "Body fetch status: raw_id=%s status=%s domain=%s score=%.2f",
                                            centroid.get("raw_id"),
                                            body_result.status,
                                            centroid.get("source_domain"),
                                            m.score,
                                        )
                                    except Exception:
                                        centroid["body_fetch_status"] = "error"
                                        logger.debug(
                                            "Body fetch errored: raw_id=%s url=%s",
                                            centroid.get("raw_id"),
                                            centroid.get("url_canonical") or centroid.get("url"),
                                            exc_info=True,
                                        )

                                    if m.score < settings.materiality_threshold:
                                        continue

                                    # Out-of-batch duplicate guard: suppress new events if a recent
                                    # event exists with the same canonical URL or identical text fingerprint.
                                    try:
                                        dup_hours = int(
                                            os.environ.get("NEWS_EVENT_DUP_WINDOW_HOURS", "72")
                                        )
                                    except Exception:
                                        dup_hours = 72
                                    cutoff = datetime.now(tz=timezone.utc) - timedelta(
                                        hours=max(1, dup_hours)
                                    )
                                    url_canon = str(
                                        centroid.get("url_canonical") or centroid.get("url") or ""
                                    )
                                    fp_val = centroid.get("text_fp")
                                    url_filter = FactNewsRaw.url_canonical == url_canon
                                    if isinstance(fp_val, int) and fp_val > 0:
                                        fp_filter = FactNewsRaw.text_fingerprint == int(fp_val)
                                        combined = or_(url_filter, fp_filter)
                                    else:
                                        combined = url_filter
                                    exists = (
                                        db.query(FactNewsEvent.event_id)
                                        .join(
                                            DimNewsCluster,
                                            FactNewsEvent.cluster_id == DimNewsCluster.cluster_id,
                                        )
                                        .join(
                                            FactNewsRaw,
                                            DimNewsCluster.centroid_raw_id == FactNewsRaw.raw_id,
                                        )
                                        .filter(
                                            or_(
                                                FactNewsEvent.decided_at >= cutoff,
                                                FactNewsRaw.published_at >= cutoff,
                                            )
                                        )
                                        .filter(combined)
                                        .first()
                                    )
                                    if exists is not None:
                                        logger.info(
                                            "Duplicate event suppressed via URL/text_fp guard: url=%s raw_id=%s",
                                            url_canon,
                                            centroid.get("raw_id"),
                                        )
                                        continue

                                    ev = insert_event(
                                        db,
                                        cluster_id=cluster_row.cluster_id,
                                        score=m.score,
                                        summary=str(centroid.get("title", ""))[:500],
                                        event_type=None,
                                        direction=None,
                                        timescale=None,
                                        is_high_confidence=(m.score >= 0.9),
                                        prefilter_reason=m.reason,
                                    )
                                    try:
                                        impacts = map_entities_to_symbols(
                                            db,
                                            centroid.get("title", ""),
                                            centroid.get("snippet", ""),
                                        )
                                        if impacts:
                                            insert_impacts(db, ev.event_id, impacts)
                                            logger.debug(
                                                "Inserted impacts: event_id=%s count=%s",
                                                ev.event_id,
                                                len(impacts),
                                            )
                                    except Exception:
                                        logger.debug(
                                            "Impact mapping failed: event_id=%s raw_id=%s",
                                            ev.event_id,
                                            centroid.get("raw_id"),
                                            exc_info=True,
                                        )

                                    created_event_ids.append(ev.event_id)
                                    logger.info(
                                        "Event created: event_id=%s cluster_id=%s score=%.2f",
                                        ev.event_id,
                                        ev.cluster_id,
                                        m.score,
                                    )
                            except Exception:
                                logger.exception(
                                    "Failed processing cluster: raw_id=%s url=%s",
                                    centroid.get("raw_id"),
                                    centroid.get("url_canonical") or centroid.get("url"),
                                )
                                continue
                    except Exception:
                        logger.exception("Batch processing failed; rolling back")
                        db.rollback()
                        raise
                    # Save latest cursors and commit
                    try:
                        save_cursors(db, last_seen)
                    except Exception:
                        logger.debug("Failed to save cursors; continuing", exc_info=True)
                    logger.info(
                        "Processed batch: docs=%s clusters=%s events=%s",
                        len(docs),
                        len(clusters),
                        len(created_event_ids),
                    )
                    # Optionally auto-run LLM on new events (cap per run)
                    try:
                        llm_enabled = os.environ.get("NEWS_LLM_ENABLED", "true").lower() == "true"
                        if (
                            llm_enabled
                            and os.environ.get("NEWS_LLM_AUTO", "false").lower() == "true"
                        ):
                            premkt = _in_premarket(
                                settings, datetime.now(tz=zoneinfo.ZoneInfo("UTC"))
                            )
                            max_events = int(
                                os.environ.get(
                                    "NEWS_LLM_MAX_EVENTS_PRE" if premkt else "NEWS_LLM_MAX_EVENTS",
                                    "5",
                                )
                            )
                            min_score = float(os.environ.get("NEWS_LLM_MIN_SCORE", "0.50"))
                            # Filter to sufficiently material events
                            todo = []
                            for eid in created_event_ids:
                                ev = db.get(FactNewsEvent, eid)
                                if ev and (float(ev.materiality_score or 0) / 100.0) >= min_score:
                                    todo.append(eid)
                                if len(todo) >= max(0, max_events):
                                    break
                            for eid in todo:
                                _ = analyze_event_cluster(db, eid)
                    except Exception as _e:
                        # Don't block pipeline on LLM errors
                        pass

                    # Optionally enqueue highly material items to sentiment (DB queue preferred; fallback schedule file)
                    try:
                        if (
                            os.environ.get("NEWS_SENTIMENT_ENQUEUE_ENABLED", "true").lower()
                            == "true"
                        ):
                            enqueue_event_thr = float(
                                os.environ.get("NEWS_SENTIMENT_ENQUEUE_MIN_EVENT_SCORE", "0.85")
                            )
                            enqueue_imp_thr = float(
                                os.environ.get("NEWS_SENTIMENT_ENQUEUE_MIN_IMPACT_MAG", "70")
                            )
                            use_db_queue = (
                                os.environ.get("NEWS_SENTIMENT_QUEUE_ENABLED", "true").lower()
                                == "true"
                            )
                            for eid in created_event_ids:
                                ev = db.get(FactNewsEvent, eid)
                                if not ev:
                                    continue
                                if (float(ev.materiality_score or 0) / 100.0) < enqueue_event_thr:
                                    continue
                                # Look up the correct centroid for THIS event (do not reuse last loop's centroid)
                                title_for_event: str | None = None
                                url_for_event: str | None = None
                                raw_id_for_event: str | None = None
                                try:
                                    cl = (
                                        db.get(DimNewsCluster, ev.cluster_id)
                                        if ev.cluster_id
                                        else None
                                    )
                                    raw = (
                                        db.get(FactNewsRaw, cl.centroid_raw_id)
                                        if cl and cl.centroid_raw_id
                                        else None
                                    )
                                    if raw:
                                        title_for_event = raw.title or ""
                                        url_for_event = raw.url_canonical or None
                                        raw_id_for_event = str(raw.raw_id)
                                except Exception:
                                    # Non-fatal; fall back to ev.summary only
                                    title_for_event = None
                                    url_for_event = None
                                # pick impacts with high magnitude (if present); else enqueue issuer-level anyway
                                imps = (
                                    db.query(FactNewsImpact)
                                    .filter(FactNewsImpact.event_id == ev.event_id)
                                    .all()
                                )
                                any_enqueued = False
                                for imp in imps:
                                    mag = float(imp.magnitude_score or 0)
                                    if mag >= enqueue_imp_thr:
                                        ok = False
                                        if use_db_queue:
                                            ok = enqueue_sentiment_analysis(
                                                db,
                                                int(imp.stock_key),
                                                event_id=str(ev.event_id),
                                                title=ev.summary or (title_for_event or ""),
                                                url=url_for_event,
                                                priority=int(
                                                    round(float(ev.materiality_score or 0))
                                                ),
                                                source="newswire",
                                                force_run=True,
                                                raw_id=raw_id_for_event,
                                            )
                                        else:
                                            ok = enqueue_analysis_for_stock(db, int(imp.stock_key))
                                        if ok:
                                            any_enqueued = True
                                # If no impact met the threshold, still enqueue issuer-level impacts if present
                                if not any_enqueued and imps:
                                    for imp in imps:
                                        ok = False
                                        if use_db_queue:
                                            ok = enqueue_sentiment_analysis(
                                                db,
                                                int(imp.stock_key),
                                                event_id=str(ev.event_id),
                                                title=ev.summary or (title_for_event or ""),
                                                url=url_for_event,
                                                priority=int(
                                                    round(float(ev.materiality_score or 0))
                                                ),
                                                source="newswire",
                                                force_run=True,
                                                raw_id=raw_id_for_event,
                                            )
                                        else:
                                            ok = enqueue_analysis_for_stock(db, int(imp.stock_key))
                                        if ok:
                                            break
                    except Exception:
                        # Don't block pipeline on downstream errors
                        pass
                    try:
                        db.commit()
                    except Exception:
                        db.rollback()
                        raise
            else:
                logger.debug("No new documents collected this cycle.")
            # Sleep based on mode
            # Sleep based on mode
            now = datetime.now(tz=zoneinfo.ZoneInfo("UTC"))
            if _in_premarket(settings, now):
                await asyncio.sleep(
                    int(
                        os.environ.get(
                            "NEWS_POLL_INTERVAL_Premarket",
                            os.environ.get("NEWS_POLL_INTERVAL_PRE", 60),
                        )
                    )
                )
            else:
                await asyncio.sleep(int(os.environ.get("NEWS_POLL_INTERVAL", 180)))

            # Exit if bounded blitz window expired
            if run_until and datetime.now(tz=zoneinfo.ZoneInfo("UTC")) >= run_until:
                break
        except Exception as e:
            logger.exception("Unhandled error in newswire collector loop: %s", e)
            await asyncio.sleep(60)


if __name__ == "__main__":
    asyncio.run(run_forever())
