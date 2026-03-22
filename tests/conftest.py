# Author: gadwant
"""
Shared test fixtures for mcpool.
"""
from __future__ import annotations

import asyncio
from typing import Any

import pytest

from mcpool.cache import ToolCache
from mcpool.config import PoolConfig
from mcpool.metrics import PoolMetrics
from mcpool.session import PooledSession

# ─── Mock MCP Session ───


class MockToolResult:
    """Simulates the result from list_tools."""

    def __init__(self, tools: list[Any] | None = None) -> None:
        self.tools = tools or [
            {"name": "tool_a", "description": "A test tool"},
            {"name": "tool_b", "description": "Another test tool"},
        ]


class MockCallToolResult:
    """Simulates the result from call_tool."""

    def __init__(self, content: list[Any] | None = None) -> None:
        self.content = content or [{"type": "text", "text": "mock result"}]


class MockMCPSession:
    """
    A mock MCP ClientSession for testing without a real MCP server.
    """

    def __init__(self, *, should_fail: bool = False, latency: float = 0.0) -> None:
        self._should_fail = should_fail
        self._latency = latency
        self._initialized = False
        self._tools = MockToolResult()
        self.call_count = 0

    async def initialize(self) -> None:
        if self._latency:
            await asyncio.sleep(self._latency)
        if self._should_fail:
            raise ConnectionError("Mock connection failed")
        self._initialized = True

    async def list_tools(self) -> MockToolResult:
        if self._latency:
            await asyncio.sleep(self._latency)
        if self._should_fail:
            raise ConnectionError("Mock list_tools failed")
        self.call_count += 1
        return self._tools

    async def call_tool(
        self, name: str, arguments: dict[str, Any] | None = None
    ) -> MockCallToolResult:
        if self._latency:
            await asyncio.sleep(self._latency)
        if self._should_fail:
            raise ConnectionError("Mock call_tool failed")
        self.call_count += 1
        return MockCallToolResult()

    async def send_ping(self) -> None:
        if self._should_fail:
            raise ConnectionError("Mock ping failed")

    async def __aenter__(self) -> MockMCPSession:
        await self.initialize()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        pass


# ─── Fixtures ───


@pytest.fixture
def default_config() -> PoolConfig:
    """A sensible default config for testing."""
    return PoolConfig(
        endpoint="http://localhost:8000/mcp",
        transport="streamable_http",
        min_sessions=2,
        max_sessions=5,
        health_check_interval_s=0,  # Disable for unit tests
        tool_cache_ttl_s=60.0,
        max_session_lifetime_s=3600.0,
        recycle_window_s=30.0,
        connect_timeout_s=5.0,
        borrow_timeout_s=5.0,
        drain_timeout_s=5.0,
    )


@pytest.fixture
def mock_session() -> MockMCPSession:
    return MockMCPSession()


@pytest.fixture
def failing_session() -> MockMCPSession:
    return MockMCPSession(should_fail=True)


@pytest.fixture
def pooled_session(mock_session: MockMCPSession) -> PooledSession:
    return PooledSession(session=mock_session)


@pytest.fixture
def tool_cache() -> ToolCache:
    return ToolCache(ttl_s=60.0)


@pytest.fixture
def metrics() -> PoolMetrics:
    return PoolMetrics()
