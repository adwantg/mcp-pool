# Author: gadwant
"""
Unit tests for HealthChecker.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest
from tests.conftest import MockMCPSession

from mcpool.health import HealthChecker
from mcpool.metrics import PoolMetrics
from mcpool.session import PooledSession


def _make_pooled(*, should_fail: bool = False) -> PooledSession:
    return PooledSession(session=MockMCPSession(should_fail=should_fail))


class TestHealthCheckerBasics:
    @pytest.mark.asyncio
    async def test_disabled_when_interval_zero(self):
        """Health checker should not start when interval is 0."""
        metrics = PoolMetrics()
        checker = HealthChecker(
            interval_s=0,
            get_idle_sessions=lambda: [],
            remove_session=lambda ps: None,
            replace_session=AsyncMock(),
            metrics=metrics,
        )
        await checker.start()
        assert checker._task is None
        await checker.stop()

    @pytest.mark.asyncio
    async def test_start_and_stop(self):
        metrics = PoolMetrics()
        checker = HealthChecker(
            interval_s=0.05,
            get_idle_sessions=lambda: [],
            remove_session=lambda ps: None,
            replace_session=AsyncMock(),
            metrics=metrics,
        )
        await checker.start()
        assert checker._task is not None
        await asyncio.sleep(0.02)
        await checker.stop()
        assert checker._task is None


class TestHealthCheckerDetection:
    @pytest.mark.asyncio
    async def test_removes_dead_session(self):
        """Dead sessions should be removed and replaced."""
        dead = _make_pooled(should_fail=True)
        removed: list[PooledSession] = []
        replaced = AsyncMock()

        metrics = PoolMetrics()
        checker = HealthChecker(
            interval_s=0.05,
            get_idle_sessions=lambda: [dead],
            remove_session=lambda ps: removed.append(ps),
            replace_session=replaced,
            metrics=metrics,
        )

        await checker.start()
        await asyncio.sleep(0.15)
        await checker.stop()

        assert len(removed) >= 1
        assert removed[0].session_id == dead.session_id
        assert replaced.call_count >= 1
        assert metrics.health_check_failures >= 1

    @pytest.mark.asyncio
    async def test_keeps_healthy_session(self):
        """Healthy sessions should not be removed."""
        healthy = _make_pooled(should_fail=False)
        removed: list[PooledSession] = []

        metrics = PoolMetrics()
        checker = HealthChecker(
            interval_s=0.05,
            get_idle_sessions=lambda: [healthy],
            remove_session=lambda ps: removed.append(ps),
            replace_session=AsyncMock(),
            metrics=metrics,
        )

        await checker.start()
        await asyncio.sleep(0.15)
        await checker.stop()

        assert len(removed) == 0
        assert metrics.health_check_count >= 1
        assert metrics.health_check_failures == 0
