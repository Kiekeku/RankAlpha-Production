from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from sqlalchemy.orm import Session

from apps.common.src.models import DimStock


def _schedule_path() -> Path:
    p = (
        os.environ.get("NEWS_SENTIMENT_SCHEDULE_FILE")
        or "/data/analysis_schedule/analysis_schedule.json"
    )
    return Path(p)


def _load_schedule() -> Dict[str, Any]:
    fp = _schedule_path()
    if not fp.exists():
        return {}
    try:
        with open(fp, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_schedule(data: Dict[str, Any]) -> None:
    fp = _schedule_path()
    fp.parent.mkdir(parents=True, exist_ok=True)
    with open(fp, "w") as f:
        json.dump(data, f, indent=2)


def enqueue_analysis_for_stock(db: Session, stock_key: int) -> bool:
    """Append today's date to the sentiment analysis schedule for a stock.

    Returns True if a date was added, False if it already existed or errored.
    """
    r = db.query(DimStock).filter(DimStock.stock_key == int(stock_key)).one_or_none()
    if r is None:
        return False
    sym = (r.symbol or "").upper()
    name = r.company_name or ""

    today_str = datetime.now().strftime("%Y-%m-%d")
    sched = _load_schedule()
    key = str(int(stock_key))
    if key not in sched:
        sched[key] = {"company_name": name, "symbol": sym, "analysis_dates": [today_str]}
        _save_schedule(sched)
        return True
    dates = set(sched[key].get("analysis_dates") or [])
    if today_str in dates:
        return False
    dates.add(today_str)
    sched[key]["company_name"] = name or sched[key].get("company_name") or ""
    sched[key]["symbol"] = sym or sched[key].get("symbol") or ""
    sched[key]["analysis_dates"] = sorted(list(dates))
    _save_schedule(sched)
    return True
