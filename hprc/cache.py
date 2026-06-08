"""Response caching.

HPRC caches LLM responses keyed on everything that can change the output:

* the fully-resolved prompt text (which already embeds fill values, request
  parameters and included responses),
* the model,
* the temperature,
* the max_tokens,
* the sorted list of tool names.

The :class:`Cache` abstraction is intentionally minimal so a Redis-backed
implementation can be dropped in later without touching the renderer.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# TTL parsing
# ---------------------------------------------------------------------------
_DURATION_RE = re.compile(r"^\s*(\d+)\s*([smhdw])\s*$", re.IGNORECASE)
_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}


def parse_ttl(spec: Optional[str]) -> Optional[int]:
    """Parse a cache spec like ``"24h"`` / ``"30m"`` / ``"3600"`` into seconds.

    Returns ``None`` when there is no caching directive (``None`` or empty).
    A bare integer is interpreted as seconds. ``"0"`` disables caching.
    """
    if spec is None:
        return None
    spec = str(spec).strip()
    if not spec:
        return None
    if spec.isdigit():
        seconds = int(spec)
    else:
        match = _DURATION_RE.match(spec)
        if not match:
            raise ValueError(f"Invalid cache duration: {spec!r}")
        value, unit = match.groups()
        seconds = int(value) * _UNIT_SECONDS[unit.lower()]
    # A non-positive TTL means "do not cache" (per this function's contract),
    # rather than "cache for 0 seconds" (which would store an entry that is
    # evicted on the very next read).
    return seconds if seconds > 0 else None


def build_cache_key(
    *,
    prompt_text: str,
    model: Optional[str],
    temperature: Optional[float],
    max_tokens: Optional[int],
    tools: List[str],
) -> str:
    """Build a stable cache key from the inputs that determine the response."""
    payload = {
        "prompt": prompt_text,
        "model": model,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "tools": sorted(tools or []),
    }
    blob = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Cache abstraction
# ---------------------------------------------------------------------------
class Cache(ABC):
    """Abstract cache interface. Implement to back HPRC with Redis, etc."""

    @abstractmethod
    async def get(self, key: str) -> Optional[str]:
        """Return the cached value for ``key`` or ``None`` if missing/expired."""

    @abstractmethod
    async def set(self, key: str, value: str, ttl: Optional[int]) -> None:
        """Store ``value`` under ``key`` for ``ttl`` seconds (None = forever)."""


class MemoryCache(Cache):
    """Simple in-process TTL cache.

    A ``time_func`` may be injected (defaults to :func:`time.time`) which makes
    expiry behaviour deterministic in tests.
    """

    def __init__(self, time_func=time.time) -> None:
        self._store: Dict[str, Tuple[float, Optional[float]]] = {}
        self._values: Dict[str, str] = {}
        self._time = time_func

    async def get(self, key: str) -> Optional[str]:
        entry = self._store.get(key)
        if entry is None:
            return None
        _, expires_at = entry
        if expires_at is not None and self._time() >= expires_at:
            # Expired — evict.
            self._store.pop(key, None)
            self._values.pop(key, None)
            return None
        return self._values.get(key)

    async def set(self, key: str, value: str, ttl: Optional[int]) -> None:
        now = self._time()
        expires_at = now + ttl if ttl is not None else None
        self._store[key] = (now, expires_at)
        self._values[key] = value

    def clear(self) -> None:
        """Drop all cached entries (test/debug helper)."""
        self._store.clear()
        self._values.clear()


class NullCache(Cache):
    """A cache that stores nothing — every lookup misses."""

    async def get(self, key: str) -> Optional[str]:  # noqa: D102
        return None

    async def set(self, key: str, value: str, ttl: Optional[int]) -> None:  # noqa: D102
        return None
