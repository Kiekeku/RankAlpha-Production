from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from apps.common.src.models import NewsCursor


def load_cursors(db: Session) -> Dict[str, datetime | None]:
    rows = db.query(NewsCursor).all()
    out: Dict[str, datetime | None] = {}
    for r in rows:
        dt = r.last_seen if r.last_seen else None
        if dt is not None:
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            else:
                dt = dt.astimezone(timezone.utc)
        out[r.source_name] = dt
    # Ensure keys exist
    out.setdefault("gdelt", None)
    out.setdefault("serper", None)
    out.setdefault("rss", None)
    return out


def save_cursors(db: Session, cursors: Dict[str, datetime | None]) -> None:
    for name, dt in cursors.items():
        if dt is None:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        stmt = (
            pg_insert(NewsCursor)
            .values(source_name=name, last_seen=dt, updated_at=datetime.now(tz=timezone.utc))
            .on_conflict_do_update(
                index_elements=[NewsCursor.source_name],
                set_={"last_seen": dt, "updated_at": datetime.now(tz=timezone.utc)},
            )
        )
        db.execute(stmt)
    db.flush()
