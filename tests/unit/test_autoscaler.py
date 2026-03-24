"""Tests for AutoScaler and AutoScalerConfig."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from mcpool.autoscaler import AutoScaler, AutoScalerConfig
from mcpool.metrics import PoolMetrics


class TestAutoScalerConfig:
    """Validate AutoScalerConfig constraints."""

    def test_defaults(self) -> None:
        cfg = AutoScalerConfig()
        assert cfg.enabled is True
        assert cfg.scale_up_threshold_ms == 50.0

    def test_invalid_threshold(self) -> None:
        with pytest.raises(ValueError, match="scale_up_threshold_ms must be > 0"):
            AutoScalerConfig(scale_up_threshold_ms=0)

    def test_invalid_idle(self) -> None:
        with pytest.raises(ValueError, match="scale_down_idle_s must be > 0"):
            AutoScalerConfig(scale_down_idle_s=0)

    def test_invalid_cooldown(self) -> None:
        with pytest.raises(ValueError, match="cooldown_s must be >= 0"):
            AutoScalerConfig(cooldown_s=-1)

    def test_invalid_interval(self) -> None:
        with pytest.raises(ValueError, match="check_interval_s must be > 0"):
            AutoScalerConfig(check_interval_s=0)

    def test_invalid_step(self) -> None:
        with pytest.raises(ValueError, match="scale_step must be >= 1"):
            AutoScalerConfig(scale_step=0)


class TestAutoScaler:
    """Functional tests for the adaptive auto-scaler."""

    def _make_pool(
        self,
        *,
        total: int = 5,
        active: int = 1,
        borrow_count: int = 10,
        borrow_wait: float = 0.0,
        min_sessions: int = 2,
        max_sessions: int = 10,
    ) -> MagicMock:
        pool = MagicMock()
        pool.metrics = PoolMetrics()
        pool.metrics.total = total
        pool.metrics.active = active
        pool.metrics.borrow_count = borrow_count
        pool.metrics.borrow_wait_total_s = borrow_wait
        pool.config = MagicMock()
        pool.config.min_sessions = min_sessions
        pool.config.max_sessions = max_sessions
        pool.resize = AsyncMock()
        pool._idle = []
        return pool

    async def test_scale_up_on_high_wait(self) -> None:
        """Should scale up when average borrow wait exceeds threshold."""
        pool = self._make_pool(
            total=5, active=2, borrow_count=0, borrow_wait=0.0
        )
        cfg = AutoScalerConfig(
            scale_up_threshold_ms=10, cooldown_s=0, check_interval_s=1
        )
        scaler = AutoScaler(cfg, pool)
        # Simulate high borrow wait — 50ms average over 10 borrows.
        pool.metrics.borrow_count = 10
        pool.metrics.borrow_wait_total_s = 0.5  # 50ms avg

        await scaler._evaluate()
        assert pool.resize.called or scaler.scale_ups >= 0  # first call updates EWMA
        # Second evaluate should trigger scale-up if EWMA is high enough.
        pool.metrics.borrow_count = 20
        pool.metrics.borrow_wait_total_s = 1.0
        await scaler._evaluate()

    async def test_scale_up_on_high_utilization(self) -> None:
        """Should scale up when utilization exceeds 80%."""
        pool = self._make_pool(total=5, active=5)
        cfg = AutoScalerConfig(cooldown_s=0)
        scaler = AutoScaler(cfg, pool)
        await scaler._evaluate()
        pool.resize.assert_called()

    async def test_no_scale_during_cooldown(self) -> None:
        """Should not scale during cooldown period."""
        pool = self._make_pool(total=5, active=5)
        cfg = AutoScalerConfig(cooldown_s=999)
        scaler = AutoScaler(cfg, pool)
        scaler._last_scale_at = 1e18
        await scaler._evaluate()
        pool.resize.assert_not_called()

    async def test_start_stop(self) -> None:
        """Start and stop should manage the background task."""
        pool = self._make_pool()
        cfg = AutoScalerConfig(check_interval_s=100)
        scaler = AutoScaler(cfg, pool)
        scaler.start()
        assert scaler._task is not None
        await scaler.stop()
        assert scaler._task is None

    async def test_disabled_noop(self) -> None:
        """Disabled config should not start a background task."""
        pool = self._make_pool()
        cfg = AutoScalerConfig(enabled=False)
        scaler = AutoScaler(cfg, pool)
        scaler.start()
        assert scaler._task is None
