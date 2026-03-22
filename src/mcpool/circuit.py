# Author: gadwant
"""
Circuit breaker for session creation.
"""
from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable

from .errors import CircuitOpenError

StateChangeHook = Callable[[str, str], Awaitable[None] | None]


class CircuitBreaker:
    """
    Simple async circuit breaker for upstream session creation.

    States:
        closed: normal operation
        open: fail fast until recovery timeout elapses
        half_open: allow a single probe attempt
    """

    def __init__(
        self,
        *,
        failure_threshold: int,
        recovery_timeout_s: float,
        on_state_change: StateChangeHook | None = None,
    ) -> None:
        self._failure_threshold = failure_threshold
        self._recovery_timeout_s = recovery_timeout_s
        self._on_state_change = on_state_change
        self._state = "closed"
        self._consecutive_failures = 0
        self._opened_at: float | None = None
        self._half_open_in_flight = False
        self._lock = asyncio.Lock()

    @property
    def state(self) -> str:
        return self._state

    async def before_request(self) -> None:
        """Raise if the circuit is open and not yet ready to probe again."""
        async with self._lock:
            now = time.monotonic()
            if self._state == "open":
                if self._opened_at is None:
                    self._opened_at = now
                if (now - self._opened_at) < self._recovery_timeout_s:
                    raise CircuitOpenError("Session creation circuit is open")
                await self._set_state("half_open")
                self._half_open_in_flight = True
                return

            if self._state == "half_open":
                if self._half_open_in_flight:
                    raise CircuitOpenError("Session creation circuit probe already in flight")
                self._half_open_in_flight = True

    async def record_success(self) -> None:
        async with self._lock:
            self._consecutive_failures = 0
            self._opened_at = None
            self._half_open_in_flight = False
            if self._state != "closed":
                await self._set_state("closed")

    async def record_failure(self) -> None:
        async with self._lock:
            self._consecutive_failures += 1
            self._half_open_in_flight = False
            if self._state == "half_open" or self._consecutive_failures >= self._failure_threshold:
                self._opened_at = time.monotonic()
                await self._set_state("open")

    async def _set_state(self, new_state: str) -> None:
        if self._state == new_state:
            return
        previous = self._state
        self._state = new_state
        if self._on_state_change is not None:
            result = self._on_state_change(previous, new_state)
            if isinstance(result, Awaitable):
                await result
