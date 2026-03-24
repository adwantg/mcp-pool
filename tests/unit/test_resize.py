# Author: gadwant
"""
Unit tests for pool.resize().
"""

from __future__ import annotations

import pytest
from tests.conftest import MockMCPSession

from mcpool.config import PoolConfig
from mcpool.pool import MCPPool
from mcpool.session import PooledSession


def _make_config(**overrides) -> PoolConfig:
    defaults = {
        "endpoint": "http://localhost:8000/mcp",
        "min_sessions": 2,
        "max_sessions": 5,
        "health_check_interval_s": 0,
        "tool_cache_ttl_s": 60.0,
        "max_session_lifetime_s": 0,
        "recycle_window_s": 0.1,
        "connect_timeout_s": 2.0,
        "borrow_timeout_s": 2.0,
        "drain_timeout_s": 2.0,
        "retry_count": 0,
        "retry_base_delay_s": 0.0,
        "retry_max_delay_s": 0.0,
    }
    defaults.update(overrides)
    return PoolConfig(**defaults)


async def _mock_create_session(pool: MCPPool) -> PooledSession:
    ps = PooledSession(session=MockMCPSession())
    pool._metrics.sessions_created += 1
    return ps


class TestResize:
    @pytest.mark.asyncio
    async def test_resize_scale_up(self):
        """resize() should add sessions when scaling up."""
        pool = MCPPool(config=_make_config(min_sessions=1, max_sessions=3))
        pool._create_session = lambda: _mock_create_session(pool)  # type: ignore
        await pool.start()
        assert pool.size == 1

        await pool.resize(min_sessions=3, max_sessions=5)
        assert pool.size >= 3
        assert pool.config.max_sessions == 5
        await pool.shutdown()

    @pytest.mark.asyncio
    async def test_resize_scale_down(self):
        """resize() should drain excess idle sessions."""
        pool = MCPPool(config=_make_config(min_sessions=3, max_sessions=5))
        pool._create_session = lambda: _mock_create_session(pool)  # type: ignore
        await pool.start()
        assert pool.size == 3

        await pool.resize(min_sessions=1, max_sessions=2)
        assert pool.size <= 2
        await pool.shutdown()

    @pytest.mark.asyncio
    async def test_resize_invalid_params(self):
        pool = MCPPool(config=_make_config())
        pool._create_session = lambda: _mock_create_session(pool)  # type: ignore
        await pool.start()

        with pytest.raises(ValueError, match="min_sessions"):
            await pool.resize(min_sessions=-1)
        with pytest.raises(ValueError, match="max_sessions"):
            await pool.resize(max_sessions=0)
        with pytest.raises(ValueError, match="cannot exceed"):
            await pool.resize(min_sessions=10, max_sessions=2)
        await pool.shutdown()

    @pytest.mark.asyncio
    async def test_resize_only_min(self):
        """Resizing only min_sessions should keep max_sessions unchanged."""
        pool = MCPPool(config=_make_config(min_sessions=1, max_sessions=5))
        pool._create_session = lambda: _mock_create_session(pool)  # type: ignore
        await pool.start()

        await pool.resize(min_sessions=3)
        assert pool.config.min_sessions == 3
        assert pool.config.max_sessions == 5
        await pool.shutdown()

    @pytest.mark.asyncio
    async def test_resize_only_max(self):
        """Resizing only max_sessions should keep min_sessions unchanged."""
        pool = MCPPool(config=_make_config(min_sessions=1, max_sessions=5))
        pool._create_session = lambda: _mock_create_session(pool)  # type: ignore
        await pool.start()

        await pool.resize(max_sessions=10)
        assert pool.config.min_sessions == 1
        assert pool.config.max_sessions == 10
        await pool.shutdown()
