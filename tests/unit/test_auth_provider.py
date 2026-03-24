# Author: gadwant
"""
Unit tests for auth_provider support.
"""

from __future__ import annotations

import pytest
from tests.conftest import MockMCPSession

from mcpool.config import PoolConfig
from mcpool.pool import MCPPool


def _make_config(**overrides) -> PoolConfig:
    defaults = {
        "endpoint": "http://localhost:8000/mcp",
        "min_sessions": 0,
        "max_sessions": 5,
        "health_check_interval_s": 0,
        "tool_cache_ttl_s": 60.0,
        "max_session_lifetime_s": 0,
        "recycle_window_s": 0.1,
        "connect_timeout_s": 2.0,
        "borrow_timeout_s": 2.0,
        "drain_timeout_s": 2.0,
        "retry_count": 0,
        "retry_base_delay_s": 0.0,
        "retry_max_delay_s": 0.0,
    }
    defaults.update(overrides)
    return PoolConfig(**defaults)


class TestAuthProvider:
    @pytest.mark.asyncio
    async def test_auth_provider_string_token(self):
        """auth_provider returning a string should set Bearer header."""
        received_headers: dict[str, str] = {}

        async def my_token_provider() -> str:
            return "sigv4-signed-token"

        async def capturing_factory(endpoint: str, headers: dict[str, str]):
            received_headers.update(headers)
            return MockMCPSession(), None

        cfg = _make_config(
            auth_provider=my_token_provider,
            transport_factory=capturing_factory,
            min_sessions=1,
        )
        pool = MCPPool(config=cfg)
        await pool.start()

        assert "Authorization" in received_headers
        assert received_headers["Authorization"] == "Bearer sigv4-signed-token"
        await pool.shutdown()

    @pytest.mark.asyncio
    async def test_auth_provider_dict_headers(self):
        """auth_provider returning a dict should merge headers."""
        received_headers: dict[str, str] = {}

        async def my_header_provider() -> dict[str, str]:
            return {
                "Authorization": "AWS4-HMAC-SHA256 ...",
                "X-Amz-Date": "20260323T000000Z",
            }

        async def capturing_factory(endpoint: str, headers: dict[str, str]):
            received_headers.update(headers)
            return MockMCPSession(), None

        cfg = _make_config(
            auth_provider=my_header_provider,
            transport_factory=capturing_factory,
            min_sessions=1,
        )
        pool = MCPPool(config=cfg)
        await pool.start()

        assert "Authorization" in received_headers
        assert received_headers["Authorization"].startswith("AWS4-HMAC-SHA256")
        assert "X-Amz-Date" in received_headers
        await pool.shutdown()

    @pytest.mark.asyncio
    async def test_static_auth_backward_compat(self):
        """Static auth= should still work when auth_provider is not set."""
        received_headers: dict[str, str] = {}

        async def capturing_factory(endpoint: str, headers: dict[str, str]):
            received_headers.update(headers)
            return MockMCPSession(), None

        cfg = _make_config(
            auth="my-api-key",
            transport_factory=capturing_factory,
            min_sessions=1,
        )
        pool = MCPPool(config=cfg)
        await pool.start()

        assert received_headers["Authorization"] == "Bearer my-api-key"
        await pool.shutdown()

    @pytest.mark.asyncio
    async def test_auth_provider_takes_precedence_over_static(self):
        """When both auth and auth_provider are set, auth_provider wins."""
        received_headers: dict[str, str] = {}

        async def my_provider() -> str:
            return "dynamic-token"

        async def capturing_factory(endpoint: str, headers: dict[str, str]):
            received_headers.update(headers)
            return MockMCPSession(), None

        cfg = _make_config(
            auth="static-token",
            auth_provider=my_provider,
            transport_factory=capturing_factory,
            min_sessions=1,
        )
        pool = MCPPool(config=cfg)
        await pool.start()

        assert received_headers["Authorization"] == "Bearer dynamic-token"
        await pool.shutdown()

    @pytest.mark.asyncio
    async def test_auth_provider_called_per_session(self):
        """auth_provider should be called for each new session creation."""
        call_count = 0

        async def counting_provider() -> str:
            nonlocal call_count
            call_count += 1
            return f"token-{call_count}"

        async def factory(endpoint: str, headers: dict[str, str]):
            return MockMCPSession(), None

        cfg = _make_config(
            auth_provider=counting_provider,
            transport_factory=factory,
            min_sessions=3,
        )
        pool = MCPPool(config=cfg)
        await pool.start()

        assert call_count == 3  # Called once per session creation
        await pool.shutdown()
