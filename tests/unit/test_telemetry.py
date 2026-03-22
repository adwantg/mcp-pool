# Author: gadwant
"""
Unit tests for optional OpenTelemetry integration.
"""
from __future__ import annotations

import pytest

from mcpool.metrics import PoolMetrics
from mcpool.telemetry import PoolTelemetry


class TestPoolTelemetry:
    @pytest.mark.asyncio
    async def test_disabled_telemetry_is_noop(self):
        telemetry = PoolTelemetry(
            enabled=False,
            metrics=PoolMetrics(),
            transport="streamable_http",
            endpoint="http://localhost:8000/mcp",
        )

        assert telemetry.is_enabled is False
        async with telemetry.span("pool.borrow"):
            telemetry.record_borrow_wait(0.001)
            telemetry.record_error("test")

    @pytest.mark.asyncio
    async def test_enabled_telemetry_initializes_when_dependency_is_available(self):
        pytest.importorskip("opentelemetry.metrics")

        telemetry = PoolTelemetry(
            enabled=True,
            metrics=PoolMetrics(),
            transport="streamable_http",
            endpoint="http://localhost:8000/mcp",
        )

        assert telemetry.is_enabled is True
        async with telemetry.span("list_tools"):
            telemetry.record_borrow_wait(0.002)
            telemetry.record_error("example")
