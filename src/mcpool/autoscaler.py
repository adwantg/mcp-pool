# Author: gadwant
"""
Adaptive pool auto-scaler — adjusts pool size based on load.
"""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import suppress
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("mcpool")


@dataclass(frozen=True)
class AutoScalerConfig:
    """
    Configuration for adaptive pool sizing.

    Attributes:
        enabled: Master switch for the auto-scaler.
        scale_up_threshold_ms: Scale up when average borrow wait exceeds
            this many milliseconds.
        scale_down_idle_s: Scale down when idle sessions have been unused
            for this many seconds.
        cooldown_s: Minimum seconds between consecutive scale actions.
        check_interval_s: How often the auto-scaler evaluates metrics.
        scale_step: Number of sessions to add/remove per scale action.
    """

    enabled: bool = True
    scale_up_threshold_ms: float = 50.0
    scale_down_idle_s: float = 120.0
    cooldown_s: float = 30.0
    check_interval_s: float = 10.0
    scale_step: int = 2

    def __post_init__(self) -> None:
        if self.scale_up_threshold_ms <= 0:
            raise ValueError(
                f"scale_up_threshold_ms must be > 0, got {self.scale_up_threshold_ms}"
            )
        if self.scale_down_idle_s <= 0:
            raise ValueError(
                f"scale_down_idle_s must be > 0, got {self.scale_down_idle_s}"
            )
        if self.cooldown_s < 0:
            raise ValueError(f"cooldown_s must be >= 0, got {self.cooldown_s}")
        if self.check_interval_s <= 0:
            raise ValueError(
                f"check_interval_s must be > 0, got {self.check_interval_s}"
            )
        if self.scale_step < 1:
            raise ValueError(f"scale_step must be >= 1, got {self.scale_step}")


class AutoScaler:
    """
    Background task that monitors pool metrics and auto-scales.

    Uses EWMA (Exponentially Weighted Moving Average) of borrow wait time
    and utilization ratio to make scaling decisions.
    """

    def __init__(self, config: AutoScalerConfig, pool: Any) -> None:
        self._config = config
        self._pool = pool
        self._task: asyncio.Task[None] | None = None
        self._last_scale_at: float = 0.0
        self._ewma_wait_ms: float = 0.0
        self._alpha: float = 0.3  # EWMA smoothing factor
        self._last_borrow_count: int = 0
        self._last_borrow_wait_total: float = 0.0
        self._scale_ups: int = 0
        self._scale_downs: int = 0

    @property
    def scale_ups(self) -> int:
        return self._scale_ups

    @property
    def scale_downs(self) -> int:
        return self._scale_downs

    @property
    def ewma_wait_ms(self) -> float:
        return self._ewma_wait_ms

    def start(self) -> None:
        """Start the auto-scaler background loop."""
        if self._task is not None:
            return
        if not self._config.enabled:
            return
        self._task = asyncio.create_task(
            self._loop(), name="mcpool-autoscaler"
        )

    async def stop(self) -> None:
        """Stop the auto-scaler."""
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _loop(self) -> None:
        """Periodic evaluation loop."""
        while True:
            await asyncio.sleep(self._config.check_interval_s)
            try:
                await self._evaluate()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.debug("AutoScaler evaluation failed", exc_info=True)

    async def _evaluate(self) -> None:
        """Evaluate metrics and decide whether to scale."""
        metrics = self._pool.metrics
        now = time.monotonic()

        # Cooldown check.
        if now - self._last_scale_at < self._config.cooldown_s:
            return

        # Update EWMA of borrow wait time.
        new_borrows = metrics.borrow_count - self._last_borrow_count
        if new_borrows > 0:
            new_wait = metrics.borrow_wait_total_s - self._last_borrow_wait_total
            avg_wait_ms = (new_wait / new_borrows) * 1000.0
            self._ewma_wait_ms = (
                self._alpha * avg_wait_ms + (1 - self._alpha) * self._ewma_wait_ms
            )
        self._last_borrow_count = metrics.borrow_count
        self._last_borrow_wait_total = metrics.borrow_wait_total_s

        # Calculate utilization.
        total = metrics.total
        utilization = metrics.active / total if total > 0 else 0.0

        config = self._pool.config

        # Scale UP: high wait time or high utilization.
        if (
            self._ewma_wait_ms > self._config.scale_up_threshold_ms
            or utilization > 0.8
        ) and config.max_sessions > total:
            new_max = min(
                config.max_sessions,
                total + self._config.scale_step,
            )
            new_min = min(new_max, config.min_sessions + self._config.scale_step)
            await self._pool.resize(min_sessions=new_min, max_sessions=config.max_sessions)
            self._last_scale_at = now
            self._scale_ups += 1
            logger.info(
                "AutoScaler scaled UP: min=%d (ewma_wait=%.1fms, util=%.1f%%)",
                new_min,
                self._ewma_wait_ms,
                utilization * 100,
            )
            return

        # Scale DOWN: excess idle sessions sitting unused.
        idle_sessions = [
            ps
            for ps in self._pool._idle
            if ps.idle_s > self._config.scale_down_idle_s
        ]
        if idle_sessions and config.min_sessions > 1 and utilization < 0.3:
            new_min = max(1, config.min_sessions - self._config.scale_step)
            await self._pool.resize(min_sessions=new_min)
            self._last_scale_at = now
            self._scale_downs += 1
            logger.info(
                "AutoScaler scaled DOWN: min=%d (idle_excess=%d, util=%.1f%%)",
                new_min,
                len(idle_sessions),
                utilization * 100,
            )
