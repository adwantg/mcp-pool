# Author: gadwant
"""
Background health-check task for idle sessions.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable, Coroutine
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .metrics import PoolMetrics
    from .session import PooledSession

logger = logging.getLogger("mcpool.health")


class HealthChecker:
    """
    Periodically pings idle sessions and removes dead ones.

    The checker runs as a background ``asyncio.Task`` and can be
    started / stopped by the owning pool.

    Args:
        interval_s: Seconds between health-check sweeps.
        get_idle_sessions: Callback returning current idle sessions.
        remove_session: Callback to remove a dead session from the pool.
        replace_session: Async callback to create a replacement session.
        metrics: Shared metrics object.
    """

    def __init__(
        self,
        interval_s: float,
        get_idle_sessions: Callable[[], list[PooledSession]],
        remove_session: Callable[[PooledSession], Coroutine[Any, Any, None]],
        replace_session: Callable[[], Coroutine[Any, Any, None]],
        metrics: PoolMetrics,
        recycle_session: Callable[[PooledSession], Coroutine[Any, Any, None]] | None = None,
        should_recycle: Callable[[PooledSession], bool] | None = None,
        on_health_check_failed: (
            Callable[[PooledSession, Exception], Coroutine[Any, Any, None]] | None
        ) = None,
    ) -> None:
        self._interval_s = interval_s
        self._get_idle = get_idle_sessions
        self._remove = remove_session
        self._replace = replace_session
        self._metrics = metrics
        self._recycle_session = recycle_session
        self._should_recycle = should_recycle
        self._on_health_check_failed = on_health_check_failed
        self._task: asyncio.Task[None] | None = None
        self._stopped = asyncio.Event()

    async def start(self) -> None:
        """Start the background health-check loop."""
        if self._interval_s <= 0:
            return
        self._stopped.clear()
        self._task = asyncio.create_task(self._loop(), name="mcpool-health-check")

    async def stop(self) -> None:
        """Signal the loop to stop and wait for it."""
        self._stopped.set()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _loop(self) -> None:
        """Main loop: sleep, then check all idle sessions."""
        try:
            while not self._stopped.is_set():
                await asyncio.sleep(self._interval_s)
                if self._stopped.is_set():
                    break
                await self._check_all()
        except asyncio.CancelledError:
            return

    async def _check_all(self) -> None:
        """Ping every idle session; remove dead ones."""
        idle = self._get_idle()
        recycled_this_sweep = False
        for ps in idle:
            if (
                not recycled_this_sweep
                and self._should_recycle is not None
                and self._recycle_session is not None
                and self._should_recycle(ps)
            ):
                recycled_this_sweep = True
                self._metrics.recycled_count += 1
                await self._recycle_session(ps)
                continue

            self._metrics.health_check_count += 1
            try:
                # Use list_tools as a lightweight ping — the result
                # is typically cached anyway.
                await asyncio.wait_for(
                    ps.session.list_tools(),
                    timeout=5.0,
                )
            except Exception as exc:
                logger.warning(
                    "Health check failed for session %s, removing", ps.session_id
                )
                self._metrics.health_check_failures += 1
                if self._on_health_check_failed is not None:
                    await self._on_health_check_failed(ps, exc)
                await self._remove(ps)
                try:
                    await self._replace()
                except Exception:
                    logger.exception("Failed to create replacement session")
                    self._metrics.errors += 1
