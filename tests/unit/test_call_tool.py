# Author: gadwant
"""
Unit tests for pool.call_tool() convenience API.
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
        "min_sessions": 1,
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


class TestCallTool:
    @pytest.mark.asyncio
    async def test_call_tool_borrows_and_returns(self):
        """call_tool should internally borrow, call, and return a session."""
        pool = MCPPool(config=_make_config())
        pool._create_session = lambda: _mock_create_session(pool)  # type: ignore

        await pool.start()
        result = await pool.call_tool("my_tool", {"key": "value"})
        assert result is not None
        assert pool.metrics.borrow_count == 1
        assert pool.metrics.return_count == 1
        assert pool.metrics.active == 0  # session returned
        await pool.shutdown()

    @pytest.mark.asyncio
    async def test_call_tool_with_headers(self):
        """call_tool should pass per-call headers."""
        pool = MCPPool(config=_make_config())
        pool._create_session = lambda: _mock_create_session(pool)  # type: ignore

        await pool.start()
        result = await pool.call_tool(
            "my_tool", headers={"X-Access-Token": "eyJ..."}
        )
        assert result is not None
        await pool.shutdown()

    @pytest.mark.asyncio
    async def test_call_tool_without_arguments(self):
        """call_tool with no arguments should work."""
        pool = MCPPool(config=_make_config())
        pool._create_session = lambda: _mock_create_session(pool)  # type: ignore

        await pool.start()
        result = await pool.call_tool("ping_tool")
        assert result is not None
        await pool.shutdown()

    @pytest.mark.asyncio
    async def test_multiple_call_tool_sequential(self):
        """Multiple sequential call_tool invocations should work."""
        pool = MCPPool(config=_make_config())
        pool._create_session = lambda: _mock_create_session(pool)  # type: ignore

        await pool.start()
        for i in range(5):
            await pool.call_tool(f"tool_{i}", {"index": i})
        assert pool.metrics.borrow_count == 5
        assert pool.metrics.return_count == 5
        await pool.shutdown()
