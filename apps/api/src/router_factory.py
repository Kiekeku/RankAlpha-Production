from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .database import get_db
from .schemas import make_pydantic_pair
from .security import require_operator_access
from .settings import Settings

SETTINGS = Settings()


def build_router(sa_cls, *, base_prefix: str = "/internal") -> APIRouter:
    """Generate an APIRouter with full CRUD for *sa_cls*.

    *Views* (VW*, V*) are treated as read‑only (GET only).
    Composite‑key tables get list/filtered + POST; single‑PK tables add /{id} paths.
    """
    base = (base_prefix or "").rstrip("/")
    router = APIRouter(
        tags=[sa_cls.__tablename__],
        prefix=f"{base}/{sa_cls.__tablename__}",
        dependencies=[Depends(require_operator_access)],
    )

    ModelIn, ModelOut = make_pydantic_pair(sa_cls)
    pk_cols = [c for c in sa_cls.__table__.columns if c.primary_key]
    read_only = sa_cls.__tablename__.startswith(("v_", "vw_", "mv_")) or sa_cls.__name__.startswith(
        ("V", "Mv")
    )

    # ---- GET many (with basic paging) ----------------------------------------
    @router.get("/", response_model=list[ModelOut])
    def list_items(
        db: Session = Depends(get_db),
        skip: int = Query(0, ge=0),
        limit: int = Query(100, le=500),
    ):
        return db.scalars(select(sa_cls).offset(skip).limit(limit)).all()

    # ---- GET by PK (only if single‑key) -------------------------------------
    if len(pk_cols) == 1:
        pk_type = pk_cols[0].type.python_type

        @router.get("/{item_id}", response_model=ModelOut)
        def get_item(item_id: pk_type, db: Session = Depends(get_db)):  # type: ignore
            obj = db.get(sa_cls, item_id)
            if not obj:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
            return obj

    # ---- Early exit for read‑only objects -----------------------------------
    # Global read-only guard for production (disables mutation routes)
    if read_only or SETTINGS.api_read_only:
        return router

    # ---- POST create --------------------------------------------------------
    @router.post("/", response_model=ModelOut, status_code=status.HTTP_201_CREATED)
    def create(item: ModelIn, db: Session = Depends(get_db)):
        obj = sa_cls(**item.model_dump(exclude_unset=True))
        db.add(obj)
        db.flush()  # allows PK to be populated
        db.refresh(obj)
        return obj

    # ---- PUT (full replacement) – single‑PK only ---------------------------
    if len(pk_cols) == 1:
        pk_type = pk_cols[0].type.python_type

        @router.put("/{item_id}", response_model=ModelOut)
        def update_item(item_id: pk_type, item: ModelIn, db: Session = Depends(get_db)):  # type: ignore
            obj = db.get(sa_cls, item_id)
            if not obj:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
            for k, v in item.model_dump(exclude_unset=True).items():
                setattr(obj, k, v)
            db.add(obj)
            db.flush()
            db.refresh(obj)
            return obj

        @router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
        def delete_item(item_id: pk_type, db: Session = Depends(get_db)):  # type: ignore
            if not db.get(sa_cls, item_id):
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
            db.execute(delete(sa_cls).where(pk_cols[0] == item_id))
            # 204 ‑ no body
    else:
        # For composite keys: allow delete via JSON body
        @router.delete("/", status_code=status.HTTP_204_NO_CONTENT)
        def delete_composite(item: ModelIn, db: Session = Depends(get_db)):
            filt = [pk_cols[i] == getattr(item, pk_cols[i].name) for i in range(len(pk_cols))]
            db.execute(delete(sa_cls).where(*filt))

    return router
