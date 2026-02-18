from __future__ import annotations

import inspect

from apps.sentiment.src import scheduler


def test_scheduler_uses_schema_qualified_analysis_table():
    src = inspect.getsource(scheduler.run_scheduled_analyses)
    assert "FROM rankalpha.fact_ai_stock_analysis" in src
