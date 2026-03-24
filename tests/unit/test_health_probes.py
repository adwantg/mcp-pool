# Author: gadwant
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from mcpool.health import HealthChecker
from mcpool.metrics import PoolMetrics
from mcpool.session import PooledSession


class TestCustomHealthProbe:
    @pytest.mark.asyncio
    async def test_default_probe_uses_list_tools(self):
        """Without custom probe, health check should use list_tools."""
        mock_session = MagicMock()
        mock_session.list_tools = AsyncMock(return_value=[])

        ps = PooledSession(session=mock_session)
        metrics = PoolMetrics()

        checker = HealthChecker(
            interval_s=1.0,
            get_idle_sessions=lambda: [ps],
            remove_session=AsyncMock(),
            replace_session=AsyncMock(),
            metrics=metrics,
        )

        await checker._check_all()
        assert metrics.health_check_count == 1
        mock_session.list_tools.assert_called_once()

    @pytest.mark.asyncio
    async def test_custom_probe_healthy(self):
        """Custom probe returning True should keep session alive."""
        mock_session = MagicMock()
        ps = PooledSession(session=mock_session)
        metrics = PoolMetrics()

        async def my_probe(session):
            return True

        checker = HealthChecker(
            interval_s=1.0,
            get_idle_sessions=lambda: [ps],
            remove_session=AsyncMock(),
            replace_session=AsyncMock(),
            metrics=metrics,
            health_probe=my_probe,
        )

        await checker._check_all()
        assert metrics.health_check_count == 1
        assert metrics.health_check_failures == 0

    @pytest.mark.asyncio
    async def test_custom_probe_unhealthy(self):
        """Custom probe returning False should remove session."""
        mock_session = MagicMock()
        ps = PooledSession(session=mock_session)
        metrics = PoolMetrics()
        remove_fn = AsyncMock()
        replace_fn = AsyncMock()

        async def my_probe(session):
            return False

        checker = HealthChecker(
            interval_s=1.0,
            get_idle_sessions=lambda: [ps],
            remove_session=remove_fn,
            replace_session=replace_fn,
            metrics=metrics,
            health_probe=my_probe,
        )

        await checker._check_all()
        assert metrics.health_check_count == 1
        assert metrics.health_check_failures == 1
        remove_fn.assert_called_once_with(ps)
        replace_fn.assert_called_once()

    @pytest.mark.asyncio
    async def test_custom_probe_exception(self):
        """Custom probe raising an exception should remove session."""
        mock_session = MagicMock()
        ps = PooledSession(session=mock_session)
        metrics = PoolMetrics()
        remove_fn = AsyncMock()
        replace_fn = AsyncMock()

        async def my_probe(session):
            raise ConnectionError("Server unreachable")

        checker = HealthChecker(
            interval_s=1.0,
            get_idle_sessions=lambda: [ps],
            remove_session=remove_fn,
            replace_session=replace_fn,
            metrics=metrics,
            health_probe=my_probe,
        )

        await checker._check_all()
        assert metrics.health_check_failures == 1
        remove_fn.assert_called_once_with(ps)
