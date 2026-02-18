from __future__ import annotations

from apps.api.src.services.ai_analysis.cache import _deserialize as ai_deserialize
from apps.api.src.services.ai_analysis.cache import _serialize as ai_serialize
from apps.api.src.services.prices.cache import PriceHistoryCache
from apps.api.src.utils.cache_codec import deserialize_compressed_json, serialize_compressed_json


def test_cache_codec_round_trip():
    payload = {
        "symbol": "AAPL",
        "items": [{"price_date": "2025-01-03", "close_px": 204.42}],
        "total_count": 1,
    }
    encoded = serialize_compressed_json(payload)
    decoded = deserialize_compressed_json(encoded)
    assert decoded == payload


def test_cache_codec_plain_json_fallback():
    plain_json = '{"symbol":"AAPL","total_count":1}'
    decoded = deserialize_compressed_json(plain_json)
    assert decoded == {"symbol": "AAPL", "total_count": 1}


def test_ai_and_prices_caches_use_compatible_codec():
    payload = {"payload": {"symbol": "MSFT"}, "refreshed_at": "2026-02-06T00:00:00Z"}

    ai_encoded = ai_serialize(payload)
    assert PriceHistoryCache._deserialize(ai_encoded) == payload

    prices_encoded = PriceHistoryCache._serialize(payload)
    assert ai_deserialize(prices_encoded) == payload
