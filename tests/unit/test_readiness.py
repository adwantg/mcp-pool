# Author: gadwant
"""
Unit tests for pool readiness: wait_ready() and is_ready.
"""
from __future__ import annotations

import asyncio

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


class TestReadiness:
    @pytest.mark.asyncio
    async def test_is_ready_false_before_start(self):
        pool = MCPPool(config=_make_config())
        assert pool.is_ready is False

    @pytest.mark.asyncio
    async def test_is_ready_true_after_start(self):
        pool = MCPPool(config=_make_config())
        pool._create_session = lambda: _mock_create_session(pool)  # type: ignore
        await pool.start()
        assert pool.is_ready is True
        await pool.shutdown()

    @pytest.mark.asyncio
    async def test_is_ready_false_after_shutdown(self):
        pool = MCPPool(config=_make_config())
        pool._create_session = lambda: _mock_create_session(pool)  # type: ignore
        await pool.start()
        await pool.shutdown()
        assert pool.is_ready is False

    @pytest.mark.asyncio
    async def test_wait_ready_returns_immediately_if_ready(self):
        pool = MCPPool(config=_make_config())
        pool._create_session = lambda: _mock_create_session(pool)  # type: ignore
        await pool.start()
        assert await pool.wait_ready(timeout_s=0.1) is True
        await pool.shutdown()

    @pytest.mark.asyncio
    async def test_wait_ready_timeout(self):
        pool = MCPPool(config=_make_config(min_sessions=0))
        pool._create_session = lambda: _mock_create_session(pool)  # type: ignore
        # min_sessions=0, so _ready_event may or may not be set
        # regardless, wait_ready should not hang
        await pool.start()
        # With min_sessions=0, the pool counts 0 >= 0 so it's ready
        result = await pool.wait_ready(timeout_s=0.1)
        assert result is True
        await pool.shutdown()

    @pytest.mark.asyncio
    async def test_is_ready_with_zero_min(self):
        """Pool with min_sessions=0 should be ready immediately."""
        pool = MCPPool(config=_make_config(min_sessions=0))
        pool._create_session = lambda: _mock_create_session(pool)  # type: ignore
        await pool.start()
        assert pool.is_ready is True
        await pool.shutdown()
