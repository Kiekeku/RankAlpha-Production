from models import (
    FactNewsRaw,
    DimNewsCluster,
    FactNewsEvent,
    FactNewsImpact,
    MvLatestMaterialNews,
    VwNewsBySymbol,
)


def test_newswire_models_available():
    assert FactNewsRaw.__tablename__ == "fact_news_raw"
    assert DimNewsCluster.__tablename__ == "dim_news_cluster"
    assert FactNewsEvent.__tablename__ == "fact_news_event"
    assert FactNewsImpact.__tablename__ == "fact_news_impact"
    assert MvLatestMaterialNews.__tablename__ == "mv_latest_material_news"
    assert VwNewsBySymbol.__tablename__ == "vw_news_by_symbol"

