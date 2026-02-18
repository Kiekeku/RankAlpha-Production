from models import NewsCursor


def test_newscursor_model_available():
    assert NewsCursor.__tablename__ == "news_cursor"
    assert hasattr(NewsCursor, "source_name")
    assert hasattr(NewsCursor, "last_seen")

