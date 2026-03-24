"""Tests for MCPPoolManager multi-endpoint orchestration."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mcpool.config import PoolConfig
from mcpool.manager import MCPPoolManager


def _mock_pool(
    *, started: bool = True, degraded: bool = False, active: int = 0
) -> MagicMock:
    pool = MagicMock()
    pool.is_started = started
    pool.is_degraded = degraded
    pool.metrics = MagicMock()
    pool.metrics.active = active
    pool.metrics.snapshot.return_value = {"active": active}
    pool.debug_snapshot.return_value = []
    pool.start = AsyncMock()
    pool.shutdown = AsyncMock()
    pool.call_tool = AsyncMock(return_value="result")
    pool.list_tools = AsyncMock(return_value=["tool1"])
    return pool


class TestMCPPoolManager:
    """Tests for multi-endpoint pool manager."""

    def test_add_and_size(self) -> None:
        mgr = MCPPoolManager()
        mgr.add("p1", PoolConfig(endpoint="http://a/mcp"))
        assert mgr.size == 1
        assert mgr.pool_names == ["p1"]

    def test_add_duplicate_raises(self) -> None:
        mgr = MCPPoolManager()
        mgr.add("p1", PoolConfig(endpoint="http://a/mcp"))
        with pytest.raises(ValueError, match="Pool 'p1' already exists"):
            mgr.add("p1", PoolConfig(endpoint="http://b/mcp"))

    def test_get_pool(self) -> None:
        mgr = MCPPoolManager()
        pool = mgr.add("p1", PoolConfig(endpoint="http://a/mcp"))
        assert mgr.get("p1") is pool

    def test_get_missing_raises(self) -> None:
        mgr = MCPPoolManager()
        with pytest.raises(KeyError):
            mgr.get("missing")

    @patch("mcpool.manager.MCPPool")
    async def test_start_shutdown(self, MockPool: MagicMock) -> None:
        mock_pool = _mock_pool()
        MockPool.return_value = mock_pool
        mgr = MCPPoolManager()
        mgr.add("p1", PoolConfig(endpoint="http://a/mcp"))
        # Replace internal pool with mock.
        mgr._pools["p1"] = mock_pool

        await mgr.start()
        mock_pool.start.assert_called_once()

        await mgr.shutdown()
        mock_pool.shutdown.assert_called_once()

    async def test_remove(self) -> None:
        mgr = MCPPoolManager()
        mgr.add("p1", PoolConfig(endpoint="http://a/mcp"))
        mock_pool = _mock_pool()
        mgr._pools["p1"] = mock_pool
        await mgr.remove("p1")
        assert mgr.size == 0
        mock_pool.shutdown.assert_called_once()

    def test_round_robin(self) -> None:
        mgr = MCPPoolManager()
        p1 = _mock_pool()
        p2 = _mock_pool()
        mgr._pools = {"a": p1, "b": p2}
        mgr._order = ["a", "b"]
        # Round-robin should alternate.
        pool = mgr._select_pool("round_robin")
        assert pool in (p1, p2)

    def test_failover(self) -> None:
        mgr = MCPPoolManager()
        p1 = _mock_pool(started=False)
        p2 = _mock_pool(started=True)
        mgr._pools = {"primary": p1, "fallback": p2}
        mgr._order = ["primary", "fallback"]
        pool = mgr._select_pool("failover")
        assert pool is p2

    def test_least_connections(self) -> None:
        mgr = MCPPoolManager()
        p1 = _mock_pool(active=5)
        p2 = _mock_pool(active=1)
        mgr._pools = {"a": p1, "b": p2}
        mgr._order = ["a", "b"]
        pool = mgr._select_pool("least_connections")
        assert pool is p2

    def test_empty_raises(self) -> None:
        mgr = MCPPoolManager()
        with pytest.raises(RuntimeError, match="No pools registered"):
            mgr._select_pool("round_robin")

    def test_metrics_snapshot(self) -> None:
        mgr = MCPPoolManager()
        p1 = _mock_pool(active=3)
        mgr._pools = {"a": p1}
        mgr._order = ["a"]
        snap = mgr.metrics_snapshot()
        assert "a" in snap

    async def test_call_tool(self) -> None:
        mgr = MCPPoolManager()
        mock_pool = _mock_pool()
        mgr._pools = {"a": mock_pool}
        mgr._order = ["a"]
        mgr._started = True
        await mgr.call_tool("my_tool", {"key": "val"})
        mock_pool.call_tool.assert_called_once()

    async def test_list_tools_specific_pool(self) -> None:
        mgr = MCPPoolManager()
        mock_pool = _mock_pool()
        mgr._pools = {"a": mock_pool}
        mgr._order = ["a"]
        tools = await mgr.list_tools(pool_name="a")
        assert tools == ["tool1"]
