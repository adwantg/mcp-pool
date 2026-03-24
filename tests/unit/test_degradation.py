# Author: gadwant
"""
Unit tests for graceful degradation.
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


class TestGracefulDegradation:
    @pytest.mark.asyncio
    async def test_enters_degraded_mode_on_warmup_failure(self):
        """Pool should enter degraded mode when warmup fails and graceful_degradation=True."""
        cfg = _make_config(graceful_degradation=True, min_sessions=2)
        pool = MCPPool(config=cfg)

        # Make all session creation fail
        async def failing_create() -> PooledSession:
            raise ConnectionError("Cannot reach gateway")

        pool._create_session = failing_create  # type: ignore
        await pool.start()

        assert pool.is_degraded is True
        assert pool.metrics.degraded is True
        assert pool.is_ready is False
        await pool.shutdown()

    @pytest.mark.asyncio
    async def test_ephemeral_sessions_in_degraded_mode(self):
        """In degraded mode, sessions should be created ephemerally."""
        cfg = _make_config(graceful_degradation=True, min_sessions=2)
        pool = MCPPool(config=cfg)

        fail_count = 0

        async def sometimes_fail() -> PooledSession:
            nonlocal fail_count
            fail_count += 1
            if fail_count <= 2:
                raise ConnectionError("warmup fails")
            return PooledSession(session=MockMCPSession())

        pool._create_session = sometimes_fail  # type: ignore
        await pool.start()
        assert pool.is_degraded is True

        # Borrowing should work via ephemeral sessions
        async with pool.session() as session:
            assert session is not None

        await pool.shutdown()

    @pytest.mark.asyncio
    async def test_no_degradation_when_disabled(self):
        """Without graceful_degradation, pool starts normally even if warmup partially fails."""
        cfg = _make_config(graceful_degradation=False, min_sessions=2)
        pool = MCPPool(config=cfg)

        attempts = 0

        async def partial_fail() -> PooledSession:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise ConnectionError("first one fails")
            return PooledSession(session=MockMCPSession())

        pool._create_session = partial_fail  # type: ignore
        await pool.start()

        # Not degraded because at least one session succeeded
        assert pool.is_degraded is False
        await pool.shutdown()

    @pytest.mark.asyncio
    async def test_degraded_mode_metrics_flag(self):
        """metrics.degraded should reflect degraded state."""
        cfg = _make_config(graceful_degradation=True, min_sessions=1)
        pool = MCPPool(config=cfg)

        async def always_fail() -> PooledSession:
            raise ConnectionError("offline")

        pool._create_session = always_fail  # type: ignore
        await pool.start()

        snap = pool.metrics.snapshot()
        assert snap["degraded"] is True
        await pool.shutdown()
