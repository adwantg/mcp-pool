# Author: gadwant
from __future__ import annotations

import pytest

from mcpool.cache import ToolCache


class TestSchemaChangeDetection:
    def test_hash_computed_on_set(self):
        cache = ToolCache(ttl_s=300)
        assert cache.schema_hash is None

        cache.set([{"name": "tool1", "description": "desc1"}])
        assert cache.schema_hash is not None
        assert len(cache.schema_hash) == 16

    def test_same_data_same_hash(self):
        cache = ToolCache(ttl_s=300)
        data = [{"name": "tool1", "description": "desc1"}]
        cache.set(data)
        h1 = cache.schema_hash

        cache.set(data)
        h2 = cache.schema_hash

        assert h1 == h2

    def test_different_data_different_hash(self):
        cache = ToolCache(ttl_s=300)
        cache.set([{"name": "tool1"}])
        h1 = cache.schema_hash

        cache.set([{"name": "tool2"}])
        h2 = cache.schema_hash

        assert h1 != h2

    def test_has_changed_detects_difference(self):
        cache = ToolCache(ttl_s=300)
        cache.set([{"name": "tool1"}])

        assert cache.has_changed([{"name": "tool2"}]) is True
        assert cache.has_changed([{"name": "tool1"}]) is False

    def test_has_changed_with_no_prior_cache(self):
        cache = ToolCache(ttl_s=300)
        # No prior data, has_changed should return False
        assert cache.has_changed([{"name": "tool1"}]) is False

    def test_hash_with_object_tools(self):
        """Tools with attribute-based access (e.g. MCP Tool objects)."""

        class MockTool:
            def __init__(self, name, desc):
                self.name = name
                self.description = desc

        cache = ToolCache(ttl_s=300)
        cache.set([MockTool("t1", "d1")])
        h1 = cache.schema_hash

        cache.set([MockTool("t1", "d1")])
        h2 = cache.schema_hash

        assert h1 == h2

        cache.set([MockTool("t1", "different")])
        h3 = cache.schema_hash

        assert h1 != h3

    def test_hash_with_tools_attribute(self):
        """Data objects with .tools attribute (e.g. ListToolsResult)."""

        class MockResult:
            def __init__(self, tools):
                self.tools = tools

        cache = ToolCache(ttl_s=300)
        cache.set(MockResult([{"name": "a"}]))
        h1 = cache.schema_hash

        cache.set(MockResult([{"name": "a"}]))
        h2 = cache.schema_hash
        assert h1 == h2

        cache.set(MockResult([{"name": "b"}]))
        h3 = cache.schema_hash
        assert h1 != h3

    @pytest.mark.asyncio
    async def test_get_or_fetch_reports_schema_changed(self):
        cache = ToolCache(ttl_s=0.001)  # Very short TTL

        # First fetch
        async def fetch_v1():
            return [{"name": "tool1"}]

        result1 = await cache.get_or_fetch(fetch_v1)
        assert result1.refreshed is True
        assert result1.schema_changed is False  # First time, no prior

        # Force expiry
        import asyncio

        await asyncio.sleep(0.01)

        # Second fetch with same data
        result2 = await cache.get_or_fetch(fetch_v1)
        assert result2.refreshed is True
        assert result2.schema_changed is False

        # Force expiry
        await asyncio.sleep(0.01)

        # Third fetch with different data
        async def fetch_v2():
            return [{"name": "tool1"}, {"name": "tool2_new"}]

        result3 = await cache.get_or_fetch(fetch_v2)
        assert result3.refreshed is True
        assert result3.schema_changed is True

    def test_invalidate_preserves_hash(self):
        """Invalidating cache should not clear schema hash."""
        cache = ToolCache(ttl_s=300)
        cache.set([{"name": "tool1"}])
        h1 = cache.schema_hash
        assert h1 is not None

        cache.invalidate()
        # Data is cleared but hash is still set for change detection
        assert cache.schema_hash == h1
