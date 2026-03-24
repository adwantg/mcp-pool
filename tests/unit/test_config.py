# Author: gadwant
"""
Unit tests for PoolConfig.
"""

from __future__ import annotations

import pytest

from mcpool.config import PoolConfig


class TestPoolConfigDefaults:
    """Verify default values are sensible."""

    def test_valid_http_config(self):
        cfg = PoolConfig(endpoint="http://localhost:8000/mcp")
        assert cfg.transport == "streamable_http"
        assert cfg.min_sessions == 2
        assert cfg.max_sessions == 10
        assert cfg.effective_borrow_timeout_s == cfg.connect_timeout_s

    def test_valid_stdio_config(self):
        cfg = PoolConfig(endpoint="uv", transport="stdio", stdio_args=["run", "server"])
        assert cfg.transport == "stdio"

    def test_frozen(self):
        cfg = PoolConfig(endpoint="http://localhost/mcp")
        with pytest.raises(AttributeError):
            cfg.min_sessions = 99  # type: ignore[misc]


class TestPoolConfigValidation:
    """Verify constraint enforcement."""

    def test_min_sessions_negative(self):
        with pytest.raises(ValueError, match="min_sessions must be >= 0"):
            PoolConfig(endpoint="http://x", min_sessions=-1)

    def test_max_sessions_zero(self):
        with pytest.raises(ValueError, match="max_sessions must be >= 1"):
            PoolConfig(endpoint="http://x", max_sessions=0)

    def test_min_exceeds_max(self):
        with pytest.raises(ValueError, match="cannot exceed"):
            PoolConfig(endpoint="http://x", min_sessions=10, max_sessions=5)

    def test_empty_endpoint_http(self):
        with pytest.raises(ValueError, match="endpoint is required"):
            PoolConfig(endpoint="", transport="streamable_http")

    def test_empty_endpoint_stdio(self):
        with pytest.raises(ValueError, match=r"endpoint.*required"):
            PoolConfig(endpoint="", transport="stdio")

    def test_zero_min_sessions_allowed(self):
        """min_sessions=0 is valid for lazy/cold-start pools."""
        cfg = PoolConfig(endpoint="http://x", min_sessions=0)
        assert cfg.min_sessions == 0

    def test_equal_min_max(self):
        """Fixed-size pool (min == max)."""
        cfg = PoolConfig(endpoint="http://x", min_sessions=5, max_sessions=5)
        assert cfg.min_sessions == cfg.max_sessions == 5

    def test_invalid_recycle_window(self):
        with pytest.raises(ValueError, match="recycle_window_s"):
            PoolConfig(
                endpoint="http://x",
                max_session_lifetime_s=10,
                recycle_window_s=10,
            )

    def test_invalid_borrow_timeout(self):
        with pytest.raises(ValueError, match="borrow_timeout_s"):
            PoolConfig(endpoint="http://x", borrow_timeout_s=-1)

    def test_invalid_retry_count(self):
        with pytest.raises(ValueError, match="retry_count"):
            PoolConfig(endpoint="http://x", retry_count=-1)

    def test_invalid_failure_threshold(self):
        with pytest.raises(ValueError, match="failure_threshold"):
            PoolConfig(endpoint="http://x", failure_threshold=0)


class TestPoolConfigEdgeCases:
    """Edge-case testing for config fields."""

    def test_large_pool_config(self):
        cfg = PoolConfig(endpoint="http://x", min_sessions=0, max_sessions=1000)
        assert cfg.max_sessions == 1000

    def test_custom_headers(self):
        cfg = PoolConfig(
            endpoint="http://x",
            mcp_headers={"X-Custom": "val"},
        )
        assert cfg.mcp_headers == {"X-Custom": "val"}

    def test_auth_token(self):
        cfg = PoolConfig(endpoint="http://x", auth="my-secret-token")
        assert cfg.auth == "my-secret-token"

    def test_all_timeouts(self):
        cfg = PoolConfig(
            endpoint="http://x",
            health_check_interval_s=0,
            tool_cache_ttl_s=0,
            max_session_lifetime_s=0,
            recycle_window_s=0,
            connect_timeout_s=1.0,
            borrow_timeout_s=0.5,
            drain_timeout_s=1.0,
        )
        assert cfg.health_check_interval_s == 0
        assert cfg.tool_cache_ttl_s == 0
        assert cfg.borrow_timeout_s == 0.5


class TestPoolConfigNewFields:
    """Validation for v0.3.0 config additions."""

    def test_transport_factory_skips_endpoint_validation(self):
        async def my_factory(endpoint, headers):
            pass

        cfg = PoolConfig(endpoint="", transport_factory=my_factory)
        assert cfg.transport_factory is not None

    def test_auth_provider_config(self):
        async def my_provider() -> str:
            return "token"

        cfg = PoolConfig(endpoint="http://x", auth_provider=my_provider)
        assert cfg.auth_provider is not None

    def test_graceful_degradation_default(self):
        cfg = PoolConfig(endpoint="http://x")
        assert cfg.graceful_degradation is False

    def test_graceful_degradation_enabled(self):
        cfg = PoolConfig(endpoint="http://x", graceful_degradation=True)
        assert cfg.graceful_degradation is True

    def test_all_new_fields_together(self):
        async def factory(endpoint, headers):
            pass

        async def provider() -> str:
            return "tk"

        cfg = PoolConfig(
            endpoint="http://x",
            transport_factory=factory,
            auth_provider=provider,
            graceful_degradation=True,
        )
        assert cfg.transport_factory is not None
        assert cfg.auth_provider is not None
        assert cfg.graceful_degradation is True
