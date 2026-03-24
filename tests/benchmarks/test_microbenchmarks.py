# Author: gadwant
"""
Regression-guarded microbenchmarks for core pool paths.
"""

from __future__ import annotations

import asyncio
import time
from statistics import median

import pytest
from tests.conftest import MockMCPSession

from mcpool.config import PoolConfig
from mcpool.errors import SessionError
from mcpool.pool import MCPPool
from mcpool.session import PooledSession


def _config(**overrides: object) -> PoolConfig:
    defaults = {
        "endpoint": "http://localhost:8000/mcp",
        "transport": "streamable_http",
        "min_sessions": 0,
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


async def _measure_async(coro_factory, *, repeats: int = 5) -> float:
    samples: list[float] = []
    for _ in range(repeats):
        start = time.perf_counter()
        await coro_factory()
        samples.append(time.perf_counter() - start)
    return median(samples)


@pytest.mark.asyncio
@pytest.mark.benchmark
async def test_warm_borrow_outperforms_cold_session_creation():
    async def create_session() -> PooledSession:
        await asyncio.sleep(0.01)
        return PooledSession(session=MockMCPSession())

    warm_pool = MCPPool(config=_config(min_sessions=1))
    warm_pool._create_session = create_session  # type: ignore[method-assign]
    await warm_pool.start()

    async def warm_borrow() -> None:
        async with warm_pool.session():
            pass

    async def cold_borrow() -> None:
        pool = MCPPool(config=_config(min_sessions=0))
        pool._create_session = create_session  # type: ignore[method-assign]
        await pool.start()
        async with pool.session():
            pass
        await pool.shutdown()

    warm_time = await _measure_async(warm_borrow)
    cold_time = await _measure_async(cold_borrow, repeats=3)

    await warm_pool.shutdown()
    assert warm_time < (cold_time * 0.5)


@pytest.mark.asyncio
@pytest.mark.benchmark
async def test_cached_list_tools_outperforms_refresh():
    async def create_session() -> PooledSession:
        return PooledSession(session=MockMCPSession(latency=0.01))

    pool = MCPPool(config=_config(min_sessions=1))
    pool._create_session = create_session  # type: ignore[method-assign]
    await pool.start()

    async def cache_miss() -> None:
        pool.invalidate_tools_cache()
        await pool.list_tools()

    async def cache_hit() -> None:
        await pool.list_tools()

    miss_time = await _measure_async(cache_miss, repeats=3)
    hit_time = await _measure_async(cache_hit)

    await pool.shutdown()
    assert hit_time < (miss_time * 0.5)


@pytest.mark.asyncio
@pytest.mark.benchmark
async def test_open_circuit_fails_faster_than_repeated_connect_attempt():
    pool = MCPPool(config=_config(failure_threshold=1, retry_count=0, recovery_timeout_s=1.0))

    async def failing_create() -> PooledSession:
        await asyncio.sleep(0.01)
        raise ConnectionError("down")

    pool._create_session_once = failing_create  # type: ignore[method-assign]
    await pool.start()

    async def first_failure() -> None:
        with pytest.raises(SessionError):
            async with pool.session():
                pass

    async def second_failure() -> None:
        with pytest.raises(SessionError):
            async with pool.session():
                pass

    first_time = await _measure_async(first_failure, repeats=1)
    second_time = await _measure_async(second_failure, repeats=3)

    await pool.shutdown()
    assert second_time < (first_time * 0.5)
