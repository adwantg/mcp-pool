"""Tests for TokenBucketLimiter and RateLimiterConfig."""

from __future__ import annotations

import asyncio

import pytest

from mcpool.rate_limiter import RateLimiterConfig, TokenBucketLimiter


class TestRateLimiterConfig:
    """Validation tests for RateLimiterConfig."""

    def test_default_config(self) -> None:
        cfg = RateLimiterConfig()
        assert cfg.requests_per_second == 100.0
        assert cfg.burst_size is None
        assert cfg.effective_burst == 100

    def test_custom_burst(self) -> None:
        cfg = RateLimiterConfig(requests_per_second=10, burst_size=20)
        assert cfg.effective_burst == 20

    def test_invalid_rate(self) -> None:
        with pytest.raises(ValueError, match="requests_per_second must be > 0"):
            RateLimiterConfig(requests_per_second=0)

    def test_invalid_burst(self) -> None:
        with pytest.raises(ValueError, match="burst_size must be >= 1"):
            RateLimiterConfig(burst_size=0)


class TestTokenBucketLimiter:
    """Functional tests for the token bucket."""

    @pytest.fixture()
    def limiter(self) -> TokenBucketLimiter:
        return TokenBucketLimiter(
            RateLimiterConfig(requests_per_second=100, burst_size=5)
        )

    async def test_acquire_within_burst(self, limiter: TokenBucketLimiter) -> None:
        """Should consume tokens without waiting when burst is available."""
        for _ in range(5):
            await limiter.acquire()
        assert limiter.wait_count == 0

    async def test_acquire_blocks_after_burst(self) -> None:
        """Should block (wait_count > 0) after burst is exhausted."""
        limiter = TokenBucketLimiter(
            RateLimiterConfig(requests_per_second=1000, burst_size=2)
        )
        await limiter.acquire()
        await limiter.acquire()
        await limiter.acquire()  # Should wait
        assert limiter.wait_count >= 1

    def test_try_acquire_success(self, limiter: TokenBucketLimiter) -> None:
        assert limiter.try_acquire() is True

    def test_try_acquire_fails_after_burst(self) -> None:
        limiter = TokenBucketLimiter(
            RateLimiterConfig(requests_per_second=1000, burst_size=1)
        )
        assert limiter.try_acquire() is True
        assert limiter.try_acquire() is False
        assert limiter.reject_count == 1

    async def test_report_throttled(self) -> None:
        """Acquiring after report_throttled should incur a wait."""
        limiter = TokenBucketLimiter(
            RateLimiterConfig(requests_per_second=1000, burst_size=10)
        )
        limiter.report_throttled(0.01)
        await limiter.acquire()
        assert limiter.wait_count >= 1

    def test_reset(self, limiter: TokenBucketLimiter) -> None:
        limiter.try_acquire()
        limiter.try_acquire()
        limiter.reset()
        assert limiter.available_tokens >= 4.9
        assert limiter.wait_count == 0
        assert limiter.reject_count == 0

    async def test_concurrent_acquires(self) -> None:
        """Multiple concurrent acquires should not raise."""
        limiter = TokenBucketLimiter(
            RateLimiterConfig(requests_per_second=10000, burst_size=50)
        )
        tasks = [limiter.acquire() for _ in range(20)]
        await asyncio.gather(*tasks)
        # All should have completed.
