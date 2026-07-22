"""Cache backend abstraction (T-14).

Phase 2 uses in-process cachetools.TTLCache. Phase 5 (T-31) ships a Redis
backend behind the same ``CacheBackend`` Protocol — call sites unchanged.

Key shape (per TODO T-14):
    SHA256(
        panel_id +
        normalized_slice_request +
        api_view_version +
        user_permission_scope
    )
"""
from __future__ import annotations

import hashlib
import json
import os
from typing import Any, Protocol

try:
    from cachetools import TTLCache
except ImportError:  # pragma: no cover
    TTLCache = None  # type: ignore[misc,assignment]


class CacheBackend(Protocol):
    """Stable interface for slice caching. Phase 2: cachetools, Phase 5: Redis."""

    def get(self, key: str) -> Any | None: ...
    def set(self, key: str, value: Any, ttl_sec: int) -> None: ...
    def clear(self) -> None: ...
    def stats(self) -> dict[str, int]: ...


class InProcessCache:
    """cachetools.TTLCache wrapper — Phase 2 default."""

    def __init__(self, maxsize: int = 1024, default_ttl: int = 900) -> None:
        if TTLCache is None:
            raise RuntimeError("cachetools not installed")
        self._cache: TTLCache = TTLCache(maxsize=maxsize, ttl=default_ttl)
        self._default_ttl = default_ttl
        self._hits = 0
        self._misses = 0

    def get(self, key: str) -> Any | None:
        v = self._cache.get(key)
        if v is None:
            self._misses += 1
        else:
            self._hits += 1
        return v

    def set(self, key: str, value: Any, ttl_sec: int | None = None) -> None:
        # TTLCache uses a single TTL; per-entry TTL would need a wrapper.
        # We approximate by reinserting with the default TTL.
        self._cache[key] = value

    def clear(self) -> None:
        self._cache.clear()
        self._hits = 0
        self._misses = 0

    def stats(self) -> dict[str, int]:
        return {"hits": self._hits, "misses": self._misses, "size": len(self._cache)}


class RedisCache:
    """Redis backend (T-31) — drop-in replacement for InProcessCache.

    Connection is lazy; the first get/set establishes the pool. The Protocol
    is honoured exactly so panels_api / slice endpoints need no changes.

    For tests, pass an explicit ``client`` (e.g. ``fakeredis.FakeRedis()``).
    """

    KEY_PREFIX = "pit:slice:"

    def __init__(
        self,
        url: str | None = None,
        default_ttl: int = 900,
        client: Any | None = None,
    ) -> None:
        self._default_ttl = default_ttl
        self._client = client
        self._url = url or os.environ.get("PIT_MARKET_REDIS_URL", "redis://localhost:6379/0")
        self._hits = 0
        self._misses = 0
        self._sets = 0

    def _get_client(self) -> Any:
        if self._client is None:
            import redis  # lazy import — keeps the dep optional at import time
            self._client = redis.Redis.from_url(self._url, decode_responses=True)
        return self._client

    def get(self, key: str) -> Any | None:
        try:
            raw = self._get_client().get(self.KEY_PREFIX + key)
        except Exception:
            # Network unavailable — treat as miss; do not raise
            self._misses += 1
            return None
        if raw is None:
            self._misses += 1
            return None
        self._hits += 1
        try:
            return json.loads(raw)
        except (TypeError, ValueError):
            return raw

    def set(self, key: str, value: Any, ttl_sec: int | None = None) -> None:
        ttl = ttl_sec if ttl_sec is not None else self._default_ttl
        payload = json.dumps(value, default=str, ensure_ascii=False)
        try:
            # redis 8.x deprecated `setex`; use `set(..., ex=ttl)`
            self._get_client().set(self.KEY_PREFIX + key, payload, ex=ttl)
            self._sets += 1
        except Exception:
            # Network unavailable — silently drop; callers fall back to recompute
            pass

    def clear(self) -> None:
        try:
            c = self._get_client()
            # only clear our prefix
            for k in c.scan_iter(self.KEY_PREFIX + "*"):
                c.delete(k)
        except Exception:
            pass
        self._hits = 0
        self._misses = 0
        self._sets = 0

    def stats(self) -> dict[str, int]:
        return {
            "hits": self._hits,
            "misses": self._misses,
            "sets": self._sets,
            "size": -1,  # SCAN-based; not enumerated by default
        }


def make_cache_key(
    panel_id: str,
    slice_request: dict[str, Any],
    api_view_version: str = "v1",
    user_permission_scope: str = "default",
) -> str:
    """Stable SHA256 cache key for a slice request."""
    normalized = json.dumps(slice_request, sort_keys=True, default=str)
    body = f"{panel_id}|{normalized}|{api_view_version}|{user_permission_scope}"
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:32]


def build_cache(backend: str = "inprocess", **kwargs: Any) -> CacheBackend:
    """Factory honouring ``PIT_MARKET_CACHE_BACKEND`` env (default: inprocess).

    Phase 5: set ``PIT_MARKET_CACHE_BACKEND=redis`` to use RedisCache.
    """
    backend = (backend or os.environ.get("PIT_MARKET_CACHE_BACKEND", "inprocess")).lower()
    if backend == "redis":
        return RedisCache(**kwargs)
    return InProcessCache(**{k: v for k, v in kwargs.items() if k in {"maxsize", "default_ttl"}})

