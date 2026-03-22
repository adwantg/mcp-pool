# Author: gadwant
"""
Unit tests for ToolCache.
"""
from __future__ import annotations

import asyncio
import time

import pytest

from mcpool.cache import ToolCache


class _FakeSession:
    """Minimal session-like object for cache tests."""

    def __init__(self, tools: object = "tool_list_v1") -> None:
        self._tools = tools
        self.call_count = 0

    async def list_tools(self) -> object:
        self.call_count += 1
        return self._tools


class TestToolCacheBasics:
    def test_empty_cache_returns_none(self, tool_cache: ToolCache):
        assert tool_cache.get() is None

    def test_set_and_get(self, tool_cache: ToolCache):
        tool_cache.set(["tool_a", "tool_b"])
        assert tool_cache.get() == ["tool_a", "tool_b"]

    def test_is_valid_after_set(self, tool_cache: ToolCache):
        tool_cache.set("data")
        assert tool_cache.is_valid is True

    def test_invalidate(self, tool_cache: ToolCache):
        tool_cache.set("data")
        tool_cache.invalidate()
        assert tool_cache.get() is None
        assert tool_cache.is_valid is False


class TestToolCacheTTL:
    def test_expired_cache_returns_none(self):
        cache = ToolCache(ttl_s=0.05)
        cache.set("data")
        time.sleep(0.06)
        assert cache.get() is None

    def test_disabled_cache(self):
        """ttl_s=0 means no caching."""
        cache = ToolCache(ttl_s=0)
        cache.set("data")
        assert cache.get() is None
        assert cache.is_valid is False

    def test_valid_within_ttl(self):
        cache = ToolCache(ttl_s=10.0)
        cache.set("data")
        assert cache.get() == "data"


class TestToolCacheGetOrFetch:
    @pytest.mark.asyncio
    async def test_fetch_on_miss(self):
        cache = ToolCache(ttl_s=60.0)
        session = _FakeSession(tools="fresh_tools")
        result = await cache.get_or_fetch(session)
        assert result.value == "fresh_tools"
        assert result.hit is False
        assert result.refreshed is True
        assert session.call_count == 1

    @pytest.mark.asyncio
    async def test_cache_hit(self):
        cache = ToolCache(ttl_s=60.0)
        cache.set("cached_tools")
        session = _FakeSession()
        result = await cache.get_or_fetch(session)
        assert result.value == "cached_tools"
        assert result.hit is True
        assert session.call_count == 0

    @pytest.mark.asyncio
    async def test_concurrent_fetch_deduplication(self):
        """Only one fetch should happen even under concurrent access."""
        cache = ToolCache(ttl_s=60.0)
        fetch_count = 0

        class SlowSession:
            async def list_tools(self) -> str:
                nonlocal fetch_count
                fetch_count += 1
                await asyncio.sleep(0.05)
                return "tools"

        session = SlowSession()
        results = await asyncio.gather(
            cache.get_or_fetch(session),
            cache.get_or_fetch(session),
            cache.get_or_fetch(session),
        )
        assert fetch_count == 1
        assert sum(1 for result in results if result.waited) >= 1
        for result in results:
            assert result.value == "tools"


class TestToolCacheProperties:
    def test_ttl_property(self):
        cache = ToolCache(ttl_s=42.0)
        assert cache.ttl_s == 42.0
