"""Limitador de taxa por janela deslizante, em cache local (suficiente para uma instância).
Com várias instâncias web, configure CACHES com Redis/Memcached — a assinatura não muda."""

from __future__ import annotations

import time
from dataclasses import dataclass

from django.core.cache import cache


@dataclass
class RateLimitResult:
    ok: bool
    remaining: int
    retry_after_seconds: int


def rate_limit(key: str, limit: int, window_seconds: int) -> RateLimitResult:
    now = time.time()
    cache_key = f"rl:{key}"
    hits = [t for t in cache.get(cache_key, []) if now - t < window_seconds]
    if len(hits) >= limit:
        cache.set(cache_key, hits, window_seconds)
        return RateLimitResult(False, 0, int(window_seconds - (now - hits[0])) + 1)
    hits.append(now)
    cache.set(cache_key, hits, window_seconds)
    return RateLimitResult(True, limit - len(hits), 0)
