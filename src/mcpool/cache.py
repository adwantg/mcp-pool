# Author: gadwant
"""
Tool-list caching layer.

Caches the ``tools/list`` response to avoid redundant round-trips.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any, Protocol


class _SessionLike(Protocol):
    """Minimal session interface needed by the cache."""

    async def list_tools(self) -> Any: ...


class ToolCache:
    """
    Thread-safe (asyncio-safe) TTL cache for MCP ``tools/list`` responses.

    Args:
        ttl_s: Time-to-live in seconds.  ``0`` disables caching.
    """

    def __init__(self, ttl_s: float = 300.0) -> None:
        self._ttl_s = ttl_s
        self._data: Any | None = None
        self._fetched_at: float = 0.0
        self._lock = asyncio.Lock()

    @property
    def ttl_s(self) -> float:
        return self._ttl_s

    @property
    def is_valid(self) -> bool:
        """Return True if the cached data exists and has not expired."""
        if self._ttl_s <= 0 or self._data is None:
            return False
        return (time.monotonic() - self._fetched_at) < self._ttl_s

    def get(self) -> Any | None:
        """Return cached tools or ``None`` if expired / empty."""
        if self.is_valid:
            return self._data
        return None

    def set(self, data: Any) -> None:
        """Store data with the current timestamp."""
        self._data = data
        self._fetched_at = time.monotonic()

    def invalidate(self) -> None:
        """Force-expire the cache."""
        self._data = None
        self._fetched_at = 0.0

    async def get_or_fetch(self, session: _SessionLike) -> Any:
        """
        Return cached tools, or fetch from *session* if stale.

        Returns a tuple ``(tools, was_cache_hit)``.
        """
        cached = self.get()
        if cached is not None:
            return cached, True

        async with self._lock:
            # Double-check after acquiring the lock.
            cached = self.get()
            if cached is not None:
                return cached, True

            tools = await session.list_tools()
            self.set(tools)
            return tools, False
