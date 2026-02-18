from __future__ import annotations

from sqlalchemy import String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from apps.api.src import router_factory


class _Base(DeclarativeBase):
    pass


class _SinglePk(_Base):
    __tablename__ = "test_table"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50))


class _CompositePk(_Base):
    __tablename__ = "test_composite"

    k1: Mapped[int] = mapped_column(primary_key=True)
    k2: Mapped[int] = mapped_column(primary_key=True)
    value: Mapped[str] = mapped_column(String(50))


class _ReadOnlyView(_Base):
    __tablename__ = "vw_test_view"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50))


def _methods_by_path(router) -> dict[str, set[str]]:  # type: ignore[no-untyped-def]
    out: dict[str, set[str]] = {}
    for r in router.routes:
        if not hasattr(r, "methods") or not hasattr(r, "path"):
            continue
        out.setdefault(r.path, set()).update(set(r.methods or []))
    return out


def test_build_router_single_pk_includes_full_crud(monkeypatch):
    monkeypatch.setattr(router_factory.SETTINGS, "api_read_only", False, raising=False)
    r = router_factory.build_router(_SinglePk, base_prefix="/internal")
    methods = _methods_by_path(r)

    assert methods["/internal/test_table/"] == {"GET", "POST"}
    assert methods["/internal/test_table/{item_id}"] == {"GET", "PUT", "DELETE"}


def test_build_router_composite_pk_has_no_item_id_routes(monkeypatch):
    monkeypatch.setattr(router_factory.SETTINGS, "api_read_only", False, raising=False)
    r = router_factory.build_router(_CompositePk, base_prefix="/internal")
    methods = _methods_by_path(r)

    assert methods["/internal/test_composite/"] == {"GET", "POST", "DELETE"}
    assert "/internal/test_composite/{item_id}" not in methods


def test_build_router_read_only_view_is_get_only(monkeypatch):
    monkeypatch.setattr(router_factory.SETTINGS, "api_read_only", False, raising=False)
    r = router_factory.build_router(_ReadOnlyView, base_prefix="/internal")
    methods = _methods_by_path(r)

    assert methods["/internal/vw_test_view/"] == {"GET"}
    assert "/internal/vw_test_view/{item_id}" in methods
    assert methods["/internal/vw_test_view/{item_id}"] == {"GET"}


def test_build_router_respects_global_api_read_only(monkeypatch):
    monkeypatch.setattr(router_factory.SETTINGS, "api_read_only", True, raising=False)
    r = router_factory.build_router(_SinglePk, base_prefix="/internal")
    methods = _methods_by_path(r)

    assert methods["/internal/test_table/"] == {"GET"}
    assert methods["/internal/test_table/{item_id}"] == {"GET"}

