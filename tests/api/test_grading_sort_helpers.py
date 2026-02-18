from __future__ import annotations

from apps.api.src.routers.grading import _metric_sort_column_name, _metric_sort_order_expr
from sqlalchemy import column
from sqlalchemy.dialects import postgresql


def _to_sql(expr) -> str:  # type: ignore[no-untyped-def]
    return str(expr.compile(dialect=postgresql.dialect()))


def test_metric_sort_column_name_maps_only_mvs():
    assert _metric_sort_column_name("momentum") == "momentum_score"
    assert _metric_sort_column_name("value") == "value_score"
    assert _metric_sort_column_name("sentiment") == "sentiment_score"
    assert _metric_sort_column_name("grade") is None
    assert _metric_sort_column_name("symbol") is None


def test_metric_sort_order_expr_adds_nulls_last_for_desc_and_asc():
    m_col = column("momentum_score")
    v_col = column("value_score")
    s_col = column("sentiment_score")

    desc_expr = _metric_sort_order_expr(
        "momentum",
        "desc",
        momentum_col=m_col,
        value_col=v_col,
        sentiment_col=s_col,
    )
    asc_expr = _metric_sort_order_expr(
        "value",
        "asc",
        momentum_col=m_col,
        value_col=v_col,
        sentiment_col=s_col,
    )

    assert desc_expr is not None
    assert "momentum_score DESC NULLS LAST" in _to_sql(desc_expr)
    assert asc_expr is not None
    assert "value_score ASC NULLS LAST" in _to_sql(asc_expr)


def test_metric_sort_order_expr_returns_none_for_non_metric_sort():
    out = _metric_sort_order_expr(
        "grade",
        "desc",
        momentum_col=column("momentum_score"),
        value_col=column("value_score"),
        sentiment_col=column("sentiment_score"),
    )
    assert out is None
