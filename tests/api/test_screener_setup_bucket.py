from __future__ import annotations

import pytest

from apps.api.src.utils.setup_taxonomy import setup_bucket_for_hit


def test_setup_bucket_handles_lowercase_style_names():
    assert setup_bucket_for_hit(style_name="momentum", source_name="Some Screener") == (
        "Momentum",
        "momentum",
        True,
    )
    assert setup_bucket_for_hit(style_name="value", source_name="Some Screener") == (
        "Value",
        "value",
        True,
    )
    assert setup_bucket_for_hit(style_name="meanrev", source_name="Some Screener") == (
        "Mean Reversion",
        "mean_reversion",
        True,
    )
    assert setup_bucket_for_hit(style_name="Mean Reversion", source_name="Some Screener") == (
        "Mean Reversion",
        "mean_reversion",
        True,
    )
    assert setup_bucket_for_hit(style_name="Mean_Reversion", source_name="Some Screener") == (
        "Mean Reversion",
        "mean_reversion",
        True,
    )


def test_setup_bucket_breakout_wins_over_momentum():
    assert setup_bucket_for_hit(style_name="momentum", source_name="52W Breakouts") == (
        "Breakout",
        "breakout",
        True,
    )


def test_setup_bucket_earnings_detects_case_insensitively():
    assert setup_bucket_for_hit(style_name="earningspre", source_name=None) == (
        "Earnings",
        "earnings",
        True,
    )
    assert setup_bucket_for_hit(style_name=None, source_name="Upcoming Earnings") == (
        "Earnings",
        "earnings",
        True,
    )
