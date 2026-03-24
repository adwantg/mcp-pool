# Author: gadwant
"""
Unit tests for transport_factory config.
"""
from __future__ import annotations

import asyncio

import pytest
from tests.conftest import MockMCPSession

from mcpool.config import PoolConfig
from mcpool.pool import MCPPool
from mcpool.session import PooledSession


async def _mock_factory(endpoint: str, headers: dict[str, str]):
    """Simulates a custom transport factory."""
    session = MockMCPSession()
    return session, None  # (session, transport_ctx)


async def _failing_factory(endpoint: str, headers: dict[str, str]):
    raise ConnectionError("Factory: endpoint unreachable")


def _make_config(**overrides) -> PoolConfig:
    defaults = {
        "endpoint": "http://localhost:8000/mcp",
        "transport": "streamable_http",
        "min_sessions": 0,
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
        "failure_threshold": 5,
        "recovery_timeout_s": 0.05,
    }
    defaults.update(overrides)
    return PoolConfig(**defaults)


class TestTransportFactory:
    @pytest.mark.asyncio
    async def test_custom_factory_is_used(self):
        """When transport_factory is set, it should be called instead of built-in transport."""
        cfg = _make_config(transport_factory=_mock_factory, min_sessions=1)
        pool = MCPPool(config=cfg)
        await pool.start()
        assert pool.size == 1
        async with pool.session() as session:
            assert session is not None
        await pool.shutdown()

    @pytest.mark.asyncio
    async def test_factory_receives_endpoint_and_headers(self):
        """Factory receives endpoint and auth headers."""
        received: dict[str, object] = {}

        async def capturing_factory(endpoint: str, headers: dict[str, str]):
            received["endpoint"] = endpoint
            received["headers"] = dict(headers)
            return MockMCPSession(), None

        cfg = _make_config(
            transport_factory=capturing_factory,
            auth="my-token",
            min_sessions=1,
        )
        pool = MCPPool(config=cfg)
        await pool.start()
        assert received["endpoint"] == "http://localhost:8000/mcp"
        assert "Authorization" in received["headers"]
        await pool.shutdown()

    @pytest.mark.asyncio
    async def test_factory_exception_bubbles_up(self):
        """Factory errors should be raised as SessionError."""
        cfg = _make_config(transport_factory=_failing_factory, min_sessions=0)
        pool = MCPPool(config=cfg)
        await pool.start()
        from mcpool.errors import SessionError
        with pytest.raises(SessionError, match="Factory"):
            async with pool.session():
                pass
        await pool.shutdown()

    def test_endpoint_not_required_with_factory(self):
        """When transport_factory is set, endpoint validation is skipped."""
        cfg = PoolConfig(
            endpoint="",
            transport_factory=_mock_factory,
        )
        assert cfg.transport_factory is not None

    @pytest.mark.asyncio
    async def test_factory_tuple_5_return_format(self):
        """Factory returning 5-tuple format should work."""

        async def five_tuple_factory(endpoint: str, headers: dict[str, str]):
            session = MockMCPSession()
            return None, None, None, None, session

        cfg = _make_config(transport_factory=five_tuple_factory, min_sessions=1)
        pool = MCPPool(config=cfg)
        await pool.start()
        assert pool.size == 1
        await pool.shutdown()
