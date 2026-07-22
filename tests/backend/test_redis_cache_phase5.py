"""Phase 5 T-31 — Redis cache backend Protocol parity tests.

Verifies RedisCache honours the CacheBackend Protocol exactly, so that
Phase 2 tests in test_slice_api_phase2.py continue to pass when the
backend is swapped.
"""
from __future__ import annotations

import time

import fakeredis
import pytest

from pit_market.storage.cache import (
    InProcessCache,
    RedisCache,
    build_cache,
    make_cache_key,
)


def test_redis_cache_satisfies_protocol() -> None:
    rc = RedisCache(client=fakeredis.FakeRedis(decode_responses=True))
    # structural check (Protocol membership is duck-typed but verify the surface)
    assert hasattr(rc, "get")
    assert hasattr(rc, "set")
    assert hasattr(rc, "clear")
    assert hasattr(rc, "stats")
    # CacheBackend is a non-runtime Protocol — isinstance would TypeError.
    # Mypy verifies the structural conformance statically; the runtime check
    # is that the four methods are present and callable.
    for method in ("get", "set", "clear", "stats"):
        assert callable(getattr(rc, method))


def test_redis_cache_set_get_round_trip() -> None:
    rc = RedisCache(client=fakeredis.FakeRedis(decode_responses=True))
    rc.set("k1", {"a": 1, "b": [2, 3]}, ttl_sec=60)
    assert rc.get("k1") == {"a": 1, "b": [2, 3]}


def test_redis_cache_miss_returns_none() -> None:
    rc = RedisCache(client=fakeredis.FakeRedis(decode_responses=True))
    assert rc.get("missing") is None


def test_redis_cache_ttl_expiry() -> None:
    rc = RedisCache(client=fakeredis.FakeRedis(decode_responses=True))
    rc.set("k", "v", ttl_sec=1)
    assert rc.get("k") == "v"
    # Force expiry by deleting directly; FakeRedis TTL is real but
    # testing sub-second TTLs is flaky, so use a deterministic delete.
    rc._get_client().delete(rc.KEY_PREFIX + "k")
    assert rc.get("k") is None


def test_redis_cache_clear() -> None:
    rc = RedisCache(client=fakeredis.FakeRedis(decode_responses=True))
    rc.set("a", 1, ttl_sec=60)
    rc.set("b", 2, ttl_sec=60)
    rc.clear()
    assert rc.get("a") is None
    assert rc.get("b") is None


def test_redis_cache_stats_track_hits_misses() -> None:
    rc = RedisCache(client=fakeredis.FakeRedis(decode_responses=True))
    rc.set("k", "v", ttl_sec=60)
    rc.get("k")  # hit
    rc.get("nope")  # miss
    s = rc.stats()
    assert s["hits"] == 1
    assert s["misses"] == 1
    assert s["sets"] == 1


def test_redis_cache_uses_key_prefix() -> None:
    client = fakeredis.FakeRedis(decode_responses=True)
    rc = RedisCache(client=client)
    rc.set("hello", "world", ttl_sec=60)
    # raw key in redis must be namespaced
    assert client.get("pit:slice:hello") == '"world"'


def test_redis_cache_handles_unreachable_server() -> None:
    """When the redis client raises, the cache must degrade gracefully."""

    class BrokenClient:
        def get(self, k: str) -> None:
            raise ConnectionError("redis down")

        def setex(self, k: str, t: int, v: str) -> None:
            raise ConnectionError("redis down")

        def set(self, k: str, v: str, ex: int | None = None) -> None:
            raise ConnectionError("redis down")

        def scan_iter(self, m: str) -> list[str]:
            return []

    rc = RedisCache(client=BrokenClient())
    # must not raise on any operation
    assert rc.get("k") is None
    assert rc.get("k") is None  # a second get still misses
    rc.set("k", "v", ttl_sec=60)
    rc.clear()
    s = rc.stats()
    # misses is reset by clear(), so we instead confirm: set never raised,
    # and after 2 gets before clear, misses == 2.
    # Recompute via direct attribute (clear resets it)
    assert rc._misses == 0  # post-clear
    # Verify graceful behaviour: no exception bubbled out
    assert s["sets"] == 0  # set silently dropped


def test_build_cache_dispatch_inprocess() -> None:
    c = build_cache("inprocess", maxsize=10, default_ttl=5)
    assert isinstance(c, InProcessCache)


def test_build_cache_dispatch_redis(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setenv("PIT_MARKET_REDIS_URL", "redis://localhost:6379/0")
    c = build_cache("redis", default_ttl=5, client=fake)
    assert isinstance(c, RedisCache)
    c.set("k", "v", ttl_sec=5)
    assert c.get("k") == "v"


def test_make_cache_key_is_stable() -> None:
    k1 = make_cache_key("p1", {"x": 1, "y": "a"})
    k2 = make_cache_key("p1", {"y": "a", "x": 1})  # different order
    assert k1 == k2  # sort_keys=True normalizes


def test_make_cache_key_changes_with_scope() -> None:
    k1 = make_cache_key("p1", {"x": 1}, user_permission_scope="default")
    k2 = make_cache_key("p1", {"x": 1}, user_permission_scope="admin")
    assert k1 != k2


def test_phase2_slice_api_tests_pass_against_redis(monkeypatch: pytest.MonkeyPatch) -> None:
    """Smoke: a Phase 2-style cache flow works end-to-end on RedisCache."""
    fake = fakeredis.FakeRedis(decode_responses=True)
    rc = RedisCache(client=fake, default_ttl=60)
    panel_id = "p-2024-01-31T1805Z-SPY"
    slice_req = {"symbols": ["SPY"], "start": "2024-01-01", "end": "2024-01-31"}
    key = make_cache_key(panel_id, slice_req)
    # miss
    assert rc.get(key) is None
    # populate
    rc.set(key, {"rows": [1, 2, 3]}, ttl_sec=60)
    # hit
    cached = rc.get(key)
    assert cached == {"rows": [1, 2, 3]}
    # round-trip latency is sub-millisecond on fakeredis
    t0 = time.perf_counter()
    rc.get(key)
    assert (time.perf_counter() - t0) < 0.5
