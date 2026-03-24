# Author: gadwant
"""
Property-based tests for pool invariants.
"""

from __future__ import annotations

import asyncio

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from tests.conftest import MockMCPSession

from mcpool.config import PoolConfig
from mcpool.pool import MCPPool
from mcpool.session import PooledSession


def _config() -> PoolConfig:
    return PoolConfig(
        endpoint="http://localhost:8000/mcp",
        transport="streamable_http",
        min_sessions=0,
        max_sessions=3,
        health_check_interval_s=0,
        tool_cache_ttl_s=60.0,
        max_session_lifetime_s=0,
        recycle_window_s=0.1,
        connect_timeout_s=1.0,
        borrow_timeout_s=0.2,
        drain_timeout_s=1.0,
        retry_count=0,
        retry_base_delay_s=0.0,
        retry_max_delay_s=0.0,
        failure_threshold=10,
        recovery_timeout_s=0.05,
    )


async def _create_session(pool: MCPPool) -> PooledSession:
    ps = PooledSession(session=MockMCPSession())
    pool.metrics.sessions_created += 1
    return ps


def _assert_invariants(pool: MCPPool) -> None:
    assert pool.metrics.total == pool.size
    assert pool.metrics.active >= 0
    assert pool.metrics.idle >= 0
    if pool.is_started:
        assert pool.metrics.active + pool.metrics.idle == pool.size
        assert pool.size <= pool.config.max_sessions
    else:
        assert pool.size == 0


@pytest.mark.asyncio
@pytest.mark.fuzz
@settings(max_examples=30, deadline=None)
@given(
    st.lists(
        st.sampled_from(["borrow", "list_tools", "invalidate", "try", "shutdown", "restart"]),
        min_size=1,
        max_size=20,
    )
)
async def test_random_operation_sequences_preserve_pool_invariants(operations: list[str]):
    pool = MCPPool(config=_config())
    pool._create_session = lambda: _create_session(pool)  # type: ignore[method-assign]
    await pool.start()

    for op in operations:
        if op == "borrow" and pool.is_started:
            async with pool.session():
                await asyncio.sleep(0)
        elif op == "list_tools" and pool.is_started:
            await pool.list_tools()
        elif op == "invalidate":
            pool.invalidate_tools_cache()
        elif op == "try" and pool.is_started:
            async with pool.try_session():
                pass
        elif op == "shutdown" and pool.is_started:
            await pool.shutdown()
        elif op == "restart" and not pool.is_started:
            await pool.start()
        _assert_invariants(pool)

    if pool.is_started:
        await pool.shutdown()
    _assert_invariants(pool)


@pytest.mark.asyncio
@pytest.mark.fuzz
@settings(max_examples=20, deadline=None)
@given(
    borrower_count=st.integers(min_value=1, max_value=6),
    hold_ms=st.integers(min_value=0, max_value=10),
)
async def test_concurrent_borrows_and_shutdown_leave_pool_consistent(
    borrower_count: int,
    hold_ms: int,
):
    pool = MCPPool(config=_config())
    pool._create_session = lambda: _create_session(pool)  # type: ignore[method-assign]
    await pool.start()

    async def borrower() -> None:
        async with pool.session():
            await asyncio.sleep(hold_ms / 1000)

    tasks = [asyncio.create_task(borrower()) for _ in range(borrower_count)]
    await asyncio.sleep(0)
    await pool.shutdown()
    await asyncio.gather(*tasks, return_exceptions=True)

    _assert_invariants(pool)
