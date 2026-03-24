# Author: gadwant
"""
Scenario benchmarks for pooled traffic patterns.
"""

from __future__ import annotations

import asyncio
import time

import pytest
from tests.conftest import MockMCPSession

from mcpool.config import PoolConfig
from mcpool.pool import MCPPool
from mcpool.session import PooledSession


def _config(**overrides: object) -> PoolConfig:
    defaults = {
        "endpoint": "http://localhost:8000/mcp",
        "transport": "streamable_http",
        "min_sessions": 2,
        "max_sessions": 4,
        "health_check_interval_s": 0,
        "tool_cache_ttl_s": 60.0,
        "max_session_lifetime_s": 0,
        "recycle_window_s": 0.1,
        "connect_timeout_s": 1.0,
        "borrow_timeout_s": 1.0,
        "drain_timeout_s": 1.0,
        "retry_count": 0,
        "retry_base_delay_s": 0.0,
        "retry_max_delay_s": 0.0,
        "failure_threshold": 10,
        "recovery_timeout_s": 0.05,
    }
    defaults.update(overrides)
    return PoolConfig(**defaults)


@pytest.mark.asyncio
@pytest.mark.benchmark
async def test_burst_traffic_with_pool_beats_cold_per_request_sessions():
    async def create_session() -> PooledSession:
        await asyncio.sleep(0.01)
        return PooledSession(session=MockMCPSession(latency=0.002))

    pooled = MCPPool(config=_config(min_sessions=4, max_sessions=8))
    pooled._create_session = create_session  # type: ignore[method-assign]
    await pooled.start()

    async def pooled_request() -> None:
        async with pooled.session() as session:
            await session.call_tool("demo", arguments={"x": 1})

    async def cold_request() -> None:
        pool = MCPPool(config=_config(min_sessions=0, max_sessions=1))
        pool._create_session = create_session  # type: ignore[method-assign]
        await pool.start()
        async with pool.session() as session:
            await session.call_tool("demo", arguments={"x": 1})
        await pool.shutdown()

    start = time.perf_counter()
    await asyncio.gather(*(pooled_request() for _ in range(8)))
    pooled_duration = time.perf_counter() - start

    start = time.perf_counter()
    for _ in range(8):
        await cold_request()
    cold_duration = time.perf_counter() - start

    await pooled.shutdown()
    assert pooled_duration < (cold_duration * 0.6)
