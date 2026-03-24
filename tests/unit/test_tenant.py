"""Tests for TenantLimiter and TenantLimiterConfig."""

from __future__ import annotations

import pytest

from mcpool.tenant import TenantLimiter, TenantLimiterConfig


class TestTenantLimiterConfig:
    """Validation tests for TenantLimiterConfig."""

    def test_defaults(self) -> None:
        cfg = TenantLimiterConfig()
        assert cfg.max_concurrent_per_tenant == 5
        assert cfg.tenant_key_header is None

    def test_invalid_max(self) -> None:
        with pytest.raises(ValueError, match="max_concurrent_per_tenant must be >= 1"):
            TenantLimiterConfig(max_concurrent_per_tenant=0)


class TestTenantLimiter:
    """Functional tests for the per-tenant concurrency limiter."""

    @pytest.fixture()
    def limiter(self) -> TenantLimiter:
        return TenantLimiter(TenantLimiterConfig(max_concurrent_per_tenant=2))

    async def test_acquire_and_release(self, limiter: TenantLimiter) -> None:
        assert await limiter.acquire("t1") is True
        assert limiter.active_count("t1") == 1
        limiter.release("t1")
        assert limiter.active_count("t1") == 0

    async def test_rejects_at_cap(self, limiter: TenantLimiter) -> None:
        """Should reject when tenant is at concurrency cap."""
        assert await limiter.acquire("t1") is True
        assert await limiter.acquire("t1") is True
        assert await limiter.acquire("t1") is False
        assert limiter.reject_count == 1

    async def test_independent_tenants(self, limiter: TenantLimiter) -> None:
        """Different tenants should have independent limits."""
        assert await limiter.acquire("t1") is True
        assert await limiter.acquire("t1") is True
        assert await limiter.acquire("t2") is True
        assert await limiter.acquire("t2") is True
        assert limiter.active_count("t1") == 2
        assert limiter.active_count("t2") == 2

    def test_resolve_tenant_key_from_header(self) -> None:
        limiter = TenantLimiter(
            TenantLimiterConfig(tenant_key_header="X-Tenant-ID")
        )
        key = limiter.resolve_tenant_key({"X-Tenant-ID": "abc"}, None)
        assert key == "abc"

    def test_resolve_tenant_key_fallback_to_affinity(self) -> None:
        limiter = TenantLimiter(TenantLimiterConfig())
        key = limiter.resolve_tenant_key(None, "user-123")
        assert key == "user-123"

    def test_resolve_tenant_key_none(self) -> None:
        limiter = TenantLimiter(TenantLimiterConfig())
        key = limiter.resolve_tenant_key(None, None)
        assert key is None

    async def test_tenant_snapshot(self, limiter: TenantLimiter) -> None:
        await limiter.acquire("t1")
        snap = limiter.tenant_snapshot()
        assert snap == {"t1": 1}

    async def test_cleanup_idle(self, limiter: TenantLimiter) -> None:
        await limiter.acquire("t1")
        limiter.release("t1")
        cleaned = limiter.cleanup_idle()
        assert cleaned == 1

    def test_reset(self, limiter: TenantLimiter) -> None:
        limiter.reset()
        assert limiter.reject_count == 0
        assert limiter.tenant_snapshot() == {}


# Needed for the sync test.
