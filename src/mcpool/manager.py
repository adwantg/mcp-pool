# Author: gadwant
"""
MCPPoolManager — multi-endpoint pool orchestration.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Literal

from .config import PoolConfig
from .pool import MCPPool

logger = logging.getLogger("mcpool")

RoutingStrategy = Literal["round_robin", "failover", "least_connections"]


class MCPPoolManager:
    """
    Manages multiple named :class:`MCPPool` instances and routes
    requests across them using a configurable strategy.

    Usage::

        manager = MCPPoolManager()
        manager.add("primary", PoolConfig(endpoint="http://primary/mcp"))
        manager.add("fallback", PoolConfig(endpoint="http://fallback/mcp"))

        async with manager:
            async with manager.session(strategy="failover") as session:
                await session.call_tool("my_tool")
    """

    def __init__(self) -> None:
        self._pools: dict[str, MCPPool] = {}
        self._order: list[str] = []
        self._rr_index: int = 0
        self._started: bool = False

    # ───── pool management ─────

    def add(self, name: str, config: PoolConfig) -> MCPPool:
        """
        Add a named pool.  If the manager is already started, the pool
        is started immediately.

        Args:
            name: Unique identifier for this endpoint.
            config: Pool configuration.

        Returns:
            The created :class:`MCPPool` instance.

        Raises:
            ValueError: If *name* is already registered.
        """
        if name in self._pools:
            raise ValueError(f"Pool '{name}' already exists")
        pool = MCPPool(config=config)
        self._pools[name] = pool
        self._order.append(name)
        return pool

    async def remove(self, name: str) -> None:
        """
        Remove and shut down a named pool.

        Raises:
            KeyError: If *name* is not registered.
        """
        pool = self._pools.pop(name)
        self._order.remove(name)
        await pool.shutdown()

    def get(self, name: str) -> MCPPool:
        """Get a specific pool by name."""
        return self._pools[name]

    @property
    def pool_names(self) -> list[str]:
        """Return the names of all registered pools."""
        return list(self._order)

    @property
    def size(self) -> int:
        """Number of registered pools."""
        return len(self._pools)

    # ───── lifecycle ─────

    async def start(self) -> None:
        """Start all registered pools."""
        if self._started:
            return
        self._started = True
        await asyncio.gather(
            *(pool.start() for pool in self._pools.values()),
            return_exceptions=True,
        )

    async def shutdown(self) -> None:
        """Shut down all pools."""
        if not self._started:
            return
        self._started = False
        await asyncio.gather(
            *(pool.shutdown() for pool in self._pools.values()),
            return_exceptions=True,
        )
        self._rr_index = 0

    async def __aenter__(self) -> MCPPoolManager:
        await self.start()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.shutdown()

    # ───── routing ─────

    @asynccontextmanager
    async def session(
        self,
        *,
        strategy: RoutingStrategy = "round_robin",
        headers: dict[str, str] | None = None,
        affinity_key: str | None = None,
    ) -> AsyncIterator[Any]:
        """
        Borrow a session from one of the managed pools.

        Args:
            strategy: Routing strategy — ``round_robin``, ``failover``,
                or ``least_connections``.
            headers: Per-request headers.
            affinity_key: Session affinity routing key.
        """
        pool = self._select_pool(strategy)
        async with pool.session(headers=headers, affinity_key=affinity_key) as sess:
            yield sess

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        *,
        strategy: RoutingStrategy = "round_robin",
        headers: dict[str, str] | None = None,
    ) -> Any:
        """Convenience: route a single tool call through the manager."""
        pool = self._select_pool(strategy)
        return await pool.call_tool(name, arguments, headers=headers)

    async def list_tools(
        self,
        *,
        pool_name: str | None = None,
        strategy: RoutingStrategy = "round_robin",
    ) -> Any:
        """
        Return tool list from a specific pool or the next pool in rotation.
        """
        if pool_name:
            return await self._pools[pool_name].list_tools()
        pool = self._select_pool(strategy)
        return await pool.list_tools()

    def _select_pool(self, strategy: RoutingStrategy) -> MCPPool:
        """Select a pool based on the routing strategy."""
        if not self._pools:
            raise RuntimeError("No pools registered in the manager")

        if strategy == "round_robin":
            return self._round_robin()
        if strategy == "failover":
            return self._failover()
        if strategy == "least_connections":
            return self._least_connections()
        raise ValueError(f"Unknown strategy: {strategy}")

    def _round_robin(self) -> MCPPool:
        """Round-robin across healthy pools."""
        names = self._order
        n = len(names)
        for _ in range(n):
            idx = self._rr_index % n
            self._rr_index += 1
            pool = self._pools[names[idx]]
            if pool.is_started and not pool.is_degraded:
                return pool
        # Fallback: return any pool.
        return self._pools[names[0]]

    def _failover(self) -> MCPPool:
        """Always use the first healthy pool; fall back to the next."""
        for name in self._order:
            pool = self._pools[name]
            if pool.is_started and not pool.is_degraded:
                return pool
        # All degraded — use the primary.
        return self._pools[self._order[0]]

    def _least_connections(self) -> MCPPool:
        """Route to the pool with the fewest active sessions."""
        best: MCPPool | None = None
        best_active = float("inf")
        for pool in self._pools.values():
            if not pool.is_started:
                continue
            active = pool.metrics.active
            if active < best_active:
                best = pool
                best_active = active
        if best is None:
            return self._pools[self._order[0]]
        return best

    # ───── introspection ─────

    def metrics_snapshot(self) -> dict[str, dict[str, object]]:
        """Return a snapshot of metrics from all pools."""
        return {name: pool.metrics.snapshot() for name, pool in self._pools.items()}

    def debug_snapshot(self) -> dict[str, list[dict[str, Any]]]:
        """Return debug snapshots from all pools."""
        return {name: pool.debug_snapshot() for name, pool in self._pools.items()}
