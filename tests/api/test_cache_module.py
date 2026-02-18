from __future__ import annotations

import json

import pytest
from apps.api.src import cache


@pytest.fixture(autouse=True)
def _reset_cache_state():
    cache._redis_client = None
    cache._cache_disabled = False
    cache._cache_disabled_until = None
    yield
    cache._redis_client = None
    cache._cache_disabled = False
    cache._cache_disabled_until = None


def test_make_key_is_stable_across_param_order():
    k1 = cache.make_key("pfx", {"b": 2, "a": 1})
    k2 = cache.make_key("pfx", {"a": 1, "b": 2})
    assert k1 == k2


def test_get_client_uses_redis_url_and_caches_instance(monkeypatch):
    class _S:
        redis_url = "redis://localhost:6379/0"
        redis_host = None
        redis_port = None
        redis_db = None
        redis_password = None

    calls: list[tuple[str, dict]] = []
    sentinel = object()

    def fake_from_url(url: str, **kwargs):  # type: ignore[no-untyped-def]
        calls.append((url, dict(kwargs)))
        return sentinel

    monkeypatch.setattr(cache, "Settings", lambda: _S())
    monkeypatch.setattr(cache.redis, "from_url", fake_from_url)

    c1 = cache._get_client()
    c2 = cache._get_client()
    assert c1 is sentinel
    assert c2 is sentinel
    assert len(calls) == 1


def test_get_client_uses_host_port_dns_probe_and_password(monkeypatch):
    class _S:
        redis_url = None
        redis_host = "redis.local"
        redis_port = 6380
        redis_db = 2
        redis_password = "pw"

    dns_calls: list[tuple[str, int]] = []
    redis_calls: list[dict] = []
    sentinel = object()

    def fake_getaddrinfo(host: str, port: int):  # type: ignore[no-untyped-def]
        dns_calls.append((host, port))
        return [("ok",)]

    def fake_redis_ctor(**kwargs):  # type: ignore[no-untyped-def]
        redis_calls.append(dict(kwargs))
        return sentinel

    monkeypatch.setattr(cache, "Settings", lambda: _S())
    monkeypatch.setattr(cache.socket, "getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr(cache.redis, "Redis", lambda **kw: fake_redis_ctor(**kw))

    out = cache._get_client()
    assert out is sentinel
    assert dns_calls == [("redis.local", 6380)]
    assert redis_calls
    assert redis_calls[0]["host"] == "redis.local"
    assert redis_calls[0]["port"] == 6380
    assert redis_calls[0]["db"] == 2
    assert redis_calls[0]["password"] == "pw"


def test_get_client_raises_when_redis_host_not_resolvable(monkeypatch):
    class _S:
        redis_url = None
        redis_host = "badhost"
        redis_port = 6379
        redis_db = 0
        redis_password = None

    monkeypatch.setattr(cache, "Settings", lambda: _S())
    monkeypatch.setattr(cache.socket, "getaddrinfo", lambda *_a, **_k: (_ for _ in ()).throw(OSError("no dns")))

    with pytest.raises(ConnectionError):
        cache._get_client()


def test_get_json_disables_cache_on_errors(monkeypatch):
    def boom():  # type: ignore[no-untyped-def]
        raise RuntimeError("redis down")

    monkeypatch.setattr(cache, "_get_client", boom)
    assert cache.get_json("k") is None
    assert cache.is_cache_disabled() is True

    # During the temporary cooldown, reads are fast no-ops (no client calls).
    assert cache.get_json("k") is None


def test_cache_recovers_after_temporary_disable(monkeypatch):
    clock = {"now": 1_000.0}
    calls = {"n": 0}

    monkeypatch.setattr(cache, "_CACHE_ERROR_DISABLE_SECONDS", 5.0)
    monkeypatch.setattr(cache.time, "time", lambda: clock["now"])

    def boom():  # type: ignore[no-untyped-def]
        calls["n"] += 1
        raise RuntimeError("redis down")

    monkeypatch.setattr(cache, "_get_client", boom)
    assert cache.get_json("k") is None
    assert calls["n"] == 1
    assert cache.is_cache_disabled() is True
    assert cache.get_json("k") is None
    assert calls["n"] == 1  # no redis attempts during cooldown

    class _FakeRedis:
        def get(self, _key):  # type: ignore[no-untyped-def]
            return '{"ok": true}'

    clock["now"] = 1_006.0
    monkeypatch.setattr(cache, "_get_client", lambda: _FakeRedis())
    assert cache.get_json("k") == {"ok": True}
    assert cache.is_cache_disabled() is False


def test_set_json_uses_setex_when_ttl_and_set_when_no_ttl(monkeypatch):
    calls: list[tuple[str, tuple]] = []

    class _FakeRedis:
        def setex(self, key, ttl, value):  # type: ignore[no-untyped-def]
            calls.append(("setex", (key, ttl, value)))

        def set(self, key, value):  # type: ignore[no-untyped-def]
            calls.append(("set", (key, value)))

    monkeypatch.setattr(cache, "_get_client", lambda: _FakeRedis())

    cache.set_json("k1", {"a": 1}, ttl_secs=60)
    cache.set_json("k2", {"b": 2}, ttl_secs=None)

    assert calls[0][0] == "setex"
    assert calls[0][1][0] == "k1"
    assert calls[0][1][1] == 60
    assert json.loads(calls[0][1][2]) == {"a": 1}

    assert calls[1][0] == "set"
    assert calls[1][1][0] == "k2"
    assert json.loads(calls[1][1][1]) == {"b": 2}


def test_invalidate_prefix_scans_and_deletes(monkeypatch):
    deleted: list[str] = []

    class _FakeRedis:
        def __init__(self):
            self._calls = 0

        def scan(self, *, cursor, match, count):  # type: ignore[no-untyped-def]
            assert match == "pfx:*"
            assert count == 500
            self._calls += 1
            if self._calls == 1:
                return 1, ["pfx:a", "pfx:b"]
            return 0, ["pfx:c"]

        def delete(self, *keys):  # type: ignore[no-untyped-def]
            deleted.extend(list(keys))
            return len(keys)

    monkeypatch.setattr(cache, "_get_client", lambda: _FakeRedis())
    out = cache.invalidate_prefix("pfx:")
    assert out == 3
    assert deleted == ["pfx:a", "pfx:b", "pfx:c"]


def test_ping_redis_disables_cache_when_ping_false(monkeypatch):
    class _FakeRedis:
        def ping(self):  # type: ignore[no-untyped-def]
            return False

    monkeypatch.setattr(cache, "_get_client", lambda: _FakeRedis())
    assert cache.ping_redis() is False
    assert cache.is_cache_disabled() is True
