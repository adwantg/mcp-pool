# Author: gadwant
"""
Unit tests for MCPPool.

Uses mock sessions to test pool lifecycle, borrow/return, graceful drain,
and error paths without a real MCP server.
"""
from __future__ import annotations

import asyncio
import time

import pytest
from tests.conftest import MockMCPSession

from mcpool.config import PoolConfig
from mcpool.errors import PoolExhaustedError, PoolShutdownError, SessionError
from mcpool.hooks import EventHooks
from mcpool.pool import MCPPool
from mcpool.session import PooledSession

# ─── Helpers ───

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
        "failure_threshold": 2,
        "recovery_timeout_s": 0.05,
    }
    defaults.update(overrides)
    return PoolConfig(**defaults)


async def _mock_create_session(pool: MCPPool) -> PooledSession:
    """Monkey-patched session creator that returns a MockMCPSession."""
    ps = PooledSession(session=MockMCPSession())
    pool._metrics.sessions_created += 1
    return ps


# ─── Tests ───


class TestPoolLifecycle:
    @pytest.mark.asyncio
    async def test_start_and_shutdown(self):
        pool = MCPPool(config=_make_config(min_sessions=0))
        pool._create_session = lambda: _mock_create_session(pool)  # type: ignore

        await pool.start()
        assert pool.is_started is True
        assert pool.size == 0  # min_sessions=0

        await pool.shutdown()
        assert pool.is_started is False

    @pytest.mark.asyncio
    async def test_context_manager(self):
        pool = MCPPool(config=_make_config(min_sessions=0))
        pool._create_session = lambda: _mock_create_session(pool)  # type: ignore

        async with pool:
            assert pool.is_started is True
        assert pool.is_started is False

    @pytest.mark.asyncio
    async def test_prewarm_sessions(self):
        pool = MCPPool(config=_make_config(min_sessions=3))
        pool._create_session = lambda: _mock_create_session(pool)  # type: ignore

        await pool.start()
        assert pool.size == 3
        assert pool.metrics.sessions_created == 3
        await pool.shutdown()

    @pytest.mark.asyncio
    async def test_double_start_is_safe(self):
        pool = MCPPool(config=_make_config(min_sessions=0))
        pool._create_session = lambda: _mock_create_session(pool)  # type: ignore

        await pool.start()
        await pool.start()  # Should be idempotent
        assert pool.is_started is True
        await pool.shutdown()


class TestSessionBorrowing:
    @pytest.mark.asyncio
    async def test_borrow_and_return(self):
        pool = MCPPool(config=_make_config(min_sessions=1))
        pool._create_session = lambda: _mock_create_session(pool)  # type: ignore

        await pool.start()
        async with pool.session() as session:
            assert session is not None
            assert pool.metrics.active == 1

        assert pool.metrics.active == 0
        assert pool.metrics.borrow_count == 1
        assert pool.metrics.return_count == 1
        await pool.shutdown()

    @pytest.mark.asyncio
    async def test_multiple_borrows(self):
        pool = MCPPool(config=_make_config(min_sessions=3, max_sessions=5))
        pool._create_session = lambda: _mock_create_session(pool)  # type: ignore

        await pool.start()

        sessions = []
        # Borrow 3 sessions concurrently
        async def borrow_one(i: int):
            async with pool.session() as s:
                sessions.append(s)
                await asyncio.sleep(0.01)

        await asyncio.gather(*[borrow_one(i) for i in range(3)])
        assert pool.metrics.borrow_count == 3
        await pool.shutdown()

    @pytest.mark.asyncio
    async def test_borrow_creates_new_if_idle_empty(self):
        pool = MCPPool(config=_make_config(min_sessions=0, max_sessions=3))
        pool._create_session = lambda: _mock_create_session(pool)  # type: ignore

        await pool.start()
        assert pool.size == 0  # No pre-warmed sessions

        async with pool.session() as session:
            assert session is not None
            assert pool.size == 1  # Created lazily

        await pool.shutdown()

    @pytest.mark.asyncio
    async def test_session_reuse(self):
        pool = MCPPool(config=_make_config(min_sessions=1))
        pool._create_session = lambda: _mock_create_session(pool)  # type: ignore

        await pool.start()

        # Borrow and return, then borrow again — same session should be reused
        async with pool.session():
            pass
        async with pool.session():
            pass

        # Only 1 session should have been created
        assert pool.metrics.sessions_created == 1
        assert pool.metrics.borrow_count == 2
        await pool.shutdown()

    @pytest.mark.asyncio
    async def test_per_request_headers(self):
        pool = MCPPool(config=_make_config(min_sessions=1))
        pool._create_session = lambda: _mock_create_session(pool)  # type: ignore

        await pool.start()
        async with pool.session(headers={"X-Token": "abc123"}):
            # The session was borrowed with headers
            pass
        await pool.shutdown()

    @pytest.mark.asyncio
    async def test_try_session_returns_none_when_pool_is_busy(self):
        pool = MCPPool(config=_make_config(min_sessions=1, max_sessions=1))
        pool._create_session = lambda: _mock_create_session(pool)  # type: ignore

        await pool.start()

        async with pool.session(), pool.try_session() as session:
            assert session is None

        await pool.shutdown()

    @pytest.mark.asyncio
    async def test_borrow_timeout_is_separate_from_connect_timeout(self):
        pool = MCPPool(
            config=_make_config(
                min_sessions=1,
                max_sessions=1,
                borrow_timeout_s=0.01,
                connect_timeout_s=1.0,
            )
        )
        pool._create_session = lambda: _mock_create_session(pool)  # type: ignore

        await pool.start()

        start = time.monotonic()
        async with pool.session():
            with pytest.raises(PoolExhaustedError, match=r"0\.01s"):
                async with pool.session():
                    pass

        assert time.monotonic() - start < 0.25
        await pool.shutdown()


class TestErrorPaths:
    @pytest.mark.asyncio
    async def test_borrow_before_start_raises(self):
        pool = MCPPool(config=_make_config(min_sessions=0))
        with pytest.raises(PoolShutdownError, match="not been started"):
            async with pool.session():
                pass

    @pytest.mark.asyncio
    async def test_borrow_after_shutdown_raises(self):
        pool = MCPPool(config=_make_config(min_sessions=0))
        pool._create_session = lambda: _mock_create_session(pool)  # type: ignore
        await pool.start()
        await pool.shutdown()

        with pytest.raises(PoolShutdownError, match="shutting down"):
            async with pool.session():
                pass


class TestGracefulDrain:
    @pytest.mark.asyncio
    async def test_shutdown_waits_for_in_flight(self):
        pool = MCPPool(config=_make_config(min_sessions=1, drain_timeout_s=5.0))
        pool._create_session = lambda: _mock_create_session(pool)  # type: ignore

        await pool.start()

        # Start a long-running "call" in the background
        async def long_call():
            async with pool.session():
                await asyncio.sleep(0.1)

        task = asyncio.create_task(long_call())
        await asyncio.sleep(0.01)  # Let the borrow happen

        # Shutdown should wait for the in-flight call
        await pool.shutdown()
        await task  # Ensure it finished
        assert pool.metrics.borrow_count == 1


class TestToolCacheIntegration:
    @pytest.mark.asyncio
    async def test_list_tools_caches(self):
        pool = MCPPool(config=_make_config(min_sessions=1))
        pool._create_session = lambda: _mock_create_session(pool)  # type: ignore

        await pool.start()

        await pool.list_tools()
        await pool.list_tools()

        # Second call should be a cache hit
        assert pool.metrics.cache_hits >= 1
        assert pool.metrics.borrow_count == 1  # Only one actual borrow
        await pool.shutdown()

    @pytest.mark.asyncio
    async def test_invalidate_cache(self):
        pool = MCPPool(config=_make_config(min_sessions=1))
        pool._create_session = lambda: _mock_create_session(pool)  # type: ignore

        await pool.start()

        await pool.list_tools()
        pool.invalidate_tools_cache()
        await pool.list_tools()

        assert pool.metrics.cache_misses == 2  # Both were misses
        assert pool.metrics.borrow_count == 2
        await pool.shutdown()

    @pytest.mark.asyncio
    async def test_list_tools_uses_single_flight_refresh(self):
        pool = MCPPool(config=_make_config(min_sessions=1))

        async def slow_create() -> PooledSession:
            ps = PooledSession(session=MockMCPSession(latency=0.05))
            pool._metrics.sessions_created += 1
            return ps

        pool._create_session = slow_create  # type: ignore[method-assign]

        await pool.start()
        await asyncio.gather(pool.list_tools(), pool.list_tools(), pool.list_tools())

        assert pool.metrics.cache_refresh_count == 1
        assert pool.metrics.borrow_count == 1
        assert pool.metrics.cache_waiters >= 1
        await pool.shutdown()


class TestRetriesAndCircuitBreaker:
    @pytest.mark.asyncio
    async def test_retries_session_creation_before_success(self):
        pool = MCPPool(config=_make_config(retry_count=2, failure_threshold=10))
        attempts = 0

        async def create_once() -> PooledSession:
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise ConnectionError("temporary failure")
            return PooledSession(session=MockMCPSession())

        pool._create_session_once = create_once  # type: ignore[method-assign]
        await pool.start()

        async with pool.session() as session:
            assert session is not None

        assert attempts == 3
        assert pool.metrics.retry_attempts == 2
        assert pool.metrics.circuit_state == "closed"
        await pool.shutdown()

    @pytest.mark.asyncio
    async def test_circuit_opens_and_closes(self):
        events: list[str] = []

        async def on_open(_payload: dict[str, object]) -> None:
            events.append("open")

        async def on_close(_payload: dict[str, object]) -> None:
            events.append("close")

        cfg = _make_config(
            retry_count=0,
            failure_threshold=2,
            recovery_timeout_s=0.05,
            min_sessions=0,
            event_hooks=EventHooks(on_circuit_open=on_open, on_circuit_close=on_close),
        )
        pool = MCPPool(config=cfg)

        attempts = 0

        async def failing_once() -> PooledSession:
            nonlocal attempts
            attempts += 1
            raise ConnectionError("boom")

        pool._create_session_once = failing_once  # type: ignore[method-assign]
        await pool.start()

        for _ in range(2):
            with pytest.raises(SessionError):
                async with pool.session():
                    pass

        assert pool.metrics.circuit_state == "open"
        assert events == ["open"]

        with pytest.raises(SessionError, match="circuit"):
            async with pool.session():
                pass

        async def healthy_once() -> PooledSession:
            return PooledSession(session=MockMCPSession())

        pool._create_session_once = healthy_once  # type: ignore[method-assign]
        await asyncio.sleep(0.06)
        async with pool.session() as session:
            assert session is not None

        assert pool.metrics.circuit_state == "closed"
        assert events == ["open", "close"]
        await pool.shutdown()


class TestBackgroundRecycling:
    @pytest.mark.asyncio
    async def test_idle_sessions_are_recycled_in_background(self):
        pool = MCPPool(
            config=_make_config(
                min_sessions=1,
                health_check_interval_s=0.05,
                max_session_lifetime_s=0.2,
                recycle_window_s=0.1,
            )
        )
        pool._create_session = lambda: _mock_create_session(pool)  # type: ignore

        await pool.start()
        original = next(iter(pool._all_sessions.values()))
        original.created_at -= 1.0

        await asyncio.sleep(0.12)

        assert pool.metrics.recycled_count >= 1
        assert pool.metrics.sessions_created >= 2
        assert original.session_id not in pool._all_sessions
        await pool.shutdown()


class TestPoolProperties:
    @pytest.mark.asyncio
    async def test_config_property(self):
        cfg = _make_config()
        pool = MCPPool(config=cfg)
        assert pool.config is cfg

    @pytest.mark.asyncio
    async def test_size_property(self):
        pool = MCPPool(config=_make_config(min_sessions=2))
        pool._create_session = lambda: _mock_create_session(pool)  # type: ignore

        await pool.start()
        assert pool.size == 2
        await pool.shutdown()
        assert pool.size == 0
