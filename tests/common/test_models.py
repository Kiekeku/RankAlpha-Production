from models import DimSource, DimStyle, FactScreenerRank, FactScreenerRankChange, MVScreenerChanges, MVScreenerBreadth


def test_models_available():
    assert DimSource.__tablename__ == "dim_source"
    assert DimStyle.__tablename__ == "dim_style"
    assert FactScreenerRank.__tablename__ == "fact_screener_rank"
    assert FactScreenerRankChange.__tablename__ == "fact_screener_rank_change"
    assert MVScreenerChanges.__tablename__ == "mv_screener_changes"
    assert MVScreenerBreadth.__tablename__ == "mv_screener_breadth"
