# Author: gadwant
"""
Token-bucket rate limiter for MCP pool borrow operations.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

logger = logging.getLogger("mcpool")


@dataclass(frozen=True)
class RateLimiterConfig:
    """
    Configuration for request rate limiting.

    Attributes:
        requests_per_second: Sustained request rate (token refill rate).
        burst_size: Maximum burst capacity (bucket size).
            Defaults to ``requests_per_second`` if not set.
    """

    requests_per_second: float = 100.0
    burst_size: int | None = None

    @property
    def effective_burst(self) -> int:
        if self.burst_size is not None:
            return self.burst_size
        return max(1, int(self.requests_per_second))

    def __post_init__(self) -> None:
        if self.requests_per_second <= 0:
            raise ValueError(
                f"requests_per_second must be > 0, got {self.requests_per_second}"
            )
        if self.burst_size is not None and self.burst_size < 1:
            raise ValueError(f"burst_size must be >= 1, got {self.burst_size}")


class TokenBucketLimiter:
    """
    Async-safe token-bucket rate limiter.

    Tokens refill at ``requests_per_second``.  The bucket can hold up to
    ``burst_size`` tokens.  ``acquire()`` blocks until a token is available.
    """

    def __init__(self, config: RateLimiterConfig) -> None:
        self._rate = config.requests_per_second
        self._burst = config.effective_burst
        self._tokens = float(self._burst)
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()
        self._throttled_until: float = 0.0
        self._wait_count = 0
        self._reject_count = 0

    @property
    def wait_count(self) -> int:
        """Number of times a caller had to wait for a token."""
        return self._wait_count

    @property
    def reject_count(self) -> int:
        """Number of rejected requests (only used with try_acquire)."""
        return self._reject_count

    @property
    def available_tokens(self) -> float:
        """Current number of available tokens (may be stale)."""
        self._refill()
        return self._tokens

    def _refill(self) -> None:
        """Add tokens based on elapsed time."""
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self._burst, self._tokens + elapsed * self._rate)
        self._last_refill = now

    async def acquire(self) -> None:
        """
        Wait until a token is available, then consume it.

        Respects server-signaled throttling via ``report_throttled()``.
        """
        async with self._lock:
            # Honour server-requested backoff.
            now = time.monotonic()
            if now < self._throttled_until:
                wait = self._throttled_until - now
                self._wait_count += 1
                await asyncio.sleep(wait)

            self._refill()
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return

            # Wait for the next available token.
            deficit = 1.0 - self._tokens
            wait_s = deficit / self._rate
            self._wait_count += 1
            await asyncio.sleep(wait_s)
            self._tokens = 0.0
            self._last_refill = time.monotonic()

    def try_acquire(self) -> bool:
        """
        Try to consume a token without waiting.

        Returns ``True`` if a token was consumed, ``False`` otherwise.
        """
        self._refill()
        if self._tokens >= 1.0:
            self._tokens -= 1.0
            return True
        self._reject_count += 1
        return False

    def report_throttled(self, retry_after_s: float) -> None:
        """
        Signal that the server returned a 429 / throttle response.

        The limiter will pause all requests for ``retry_after_s``.
        """
        self._throttled_until = time.monotonic() + retry_after_s
        logger.warning(
            "Rate limiter pausing for %.1fs (server throttle)", retry_after_s
        )

    def reset(self) -> None:
        """Reset the limiter to full capacity."""
        self._tokens = float(self._burst)
        self._last_refill = time.monotonic()
        self._throttled_until = 0.0
        self._wait_count = 0
        self._reject_count = 0
