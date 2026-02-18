from __future__ import annotations

from apps.sentiment.src import analysis_workflow


def test_output_filename_is_collision_resistant_and_symbol_tagged():
    name1 = analysis_workflow._build_output_filename("Apple Inc", "AAPL")
    name2 = analysis_workflow._build_output_filename("Apple Inc", "AAPL")

    assert name1.endswith(".md")
    assert "_aapl_report_" in name1
    assert name1 != name2
