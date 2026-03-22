# Author: gadwant
"""
MCPPool — the core async connection pool for MCP client sessions.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from typing import Any

from .cache import ToolCache
from .config import PoolConfig
from .errors import PoolExhaustedError, PoolShutdownError, SessionError
from .health import HealthChecker
from .metrics import PoolMetrics
from .session import PooledSession

logger = logging.getLogger("mcpool")


class MCPPool:
    """
    Async connection pool for MCP client sessions.

    Usage::

        pool = MCPPool(config=PoolConfig(endpoint="http://localhost:8000/mcp"))
        await pool.start()

        async with pool.session() as session:
            tools = await pool.list_tools()
            result = await session.call_tool("my_tool", arguments={"key": "value"})

        await pool.shutdown()

    Or as an async context manager::

        async with MCPPool(config=PoolConfig(endpoint="...")) as pool:
            async with pool.session() as session:
                ...
    """

    def __init__(
        self,
        config: PoolConfig | None = None,
        *,
        endpoint: str = "",
        transport: str = "streamable_http",
        min_sessions: int = 2,
        max_sessions: int = 10,
        health_check_interval_s: float = 30.0,
        tool_cache_ttl_s: float = 300.0,
        max_session_lifetime_s: float = 3600.0,
        connect_timeout_s: float = 10.0,
        drain_timeout_s: float = 30.0,
        auth: str | None = None,
        mcp_headers: dict[str, str] | None = None,
    ) -> None:
        if config is not None:
            self._config = config
        else:
            self._config = PoolConfig(
                endpoint=endpoint,
                transport=transport,  # type: ignore[arg-type]
                min_sessions=min_sessions,
                max_sessions=max_sessions,
                health_check_interval_s=health_check_interval_s,
                tool_cache_ttl_s=tool_cache_ttl_s,
                max_session_lifetime_s=max_session_lifetime_s,
                connect_timeout_s=connect_timeout_s,
                drain_timeout_s=drain_timeout_s,
                auth=auth,
                mcp_headers=mcp_headers or {},
            )

        self._idle: deque[PooledSession] = deque()
        self._active: set[str] = set()
        self._all_sessions: dict[str, PooledSession] = {}

        self._semaphore = asyncio.Semaphore(self._config.max_sessions)
        self._lock = asyncio.Lock()
        self._started = False
        self._shutting_down = False
        self._in_flight = 0
        self._drain_event = asyncio.Event()
        self._drain_event.set()  # no one in-flight initially

        self._metrics = PoolMetrics()
        self._cache = ToolCache(ttl_s=self._config.tool_cache_ttl_s)

        self._health_checker = HealthChecker(
            interval_s=self._config.health_check_interval_s,
            get_idle_sessions=lambda: list(self._idle),
            remove_session=self._remove_session,
            replace_session=self._create_and_add_session,
            metrics=self._metrics,
        )

    # ───── properties ─────

    @property
    def config(self) -> PoolConfig:
        return self._config

    @property
    def metrics(self) -> PoolMetrics:
        return self._metrics

    @property
    def cache(self) -> ToolCache:
        return self._cache

    @property
    def is_started(self) -> bool:
        return self._started

    @property
    def size(self) -> int:
        """Total number of sessions (active + idle)."""
        return len(self._all_sessions)

    # ───── lifecycle ─────

    async def start(self) -> None:
        """Pre-warm ``min_sessions`` and start the health checker."""
        if self._started:
            return
        self._started = True
        self._shutting_down = False

        # Pre-warm sessions
        tasks = [self._create_and_add_session() for _ in range(self._config.min_sessions)]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        self._metrics.idle = len(self._idle)
        self._metrics.total = len(self._all_sessions)

        await self._health_checker.start()
        logger.info(
            "MCPPool started: %d sessions pre-warmed (min=%d, max=%d)",
            len(self._idle),
            self._config.min_sessions,
            self._config.max_sessions,
        )

    async def shutdown(self) -> None:
        """Drain in-flight calls and close all sessions."""
        if not self._started:
            return
        self._shutting_down = True

        # Stop health checker
        await self._health_checker.stop()

        # Wait for in-flight calls to finish
        if self._in_flight > 0:
            self._drain_event.clear()
            try:
                await asyncio.wait_for(
                    self._drain_event.wait(),
                    timeout=self._config.drain_timeout_s,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "Drain timed out after %.1fs with %d in-flight calls",
                    self._config.drain_timeout_s,
                    self._in_flight,
                )

        # Close all sessions
        for ps in list(self._all_sessions.values()):
            await self._close_session(ps)

        self._idle.clear()
        self._active.clear()
        self._all_sessions.clear()
        self._started = False
        self._metrics.active = 0
        self._metrics.idle = 0
        self._metrics.total = 0
        logger.info("MCPPool shut down")

    async def __aenter__(self) -> MCPPool:
        await self.start()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.shutdown()

    # ───── session borrowing ─────

    @asynccontextmanager
    async def session(
        self,
        headers: dict[str, str] | None = None,
    ) -> AsyncIterator[Any]:
        """
        Borrow a session from the pool.

        Yields the underlying MCP ``ClientSession``.  The session is
        automatically returned when the context exits.

        Args:
            headers: Optional per-request headers to inject.
        """
        if self._shutting_down:
            raise PoolShutdownError("Pool is shutting down")
        if not self._started:
            raise PoolShutdownError("Pool has not been started. Call pool.start() first.")

        wait_start = time.monotonic()

        # Acquire semaphore (blocks if at max_sessions)
        acquired = False
        try:
            try:
                await asyncio.wait_for(
                    self._semaphore.acquire(),
                    timeout=self._config.connect_timeout_s,
                )
                acquired = True
            except asyncio.TimeoutError:
                raise PoolExhaustedError(
                    f"No session available within {self._config.connect_timeout_s}s"
                ) from None

            ps = await self._borrow(headers)
            self._metrics.borrow_count += 1
            self._metrics.borrow_wait_total_s += time.monotonic() - wait_start

            self._in_flight += 1
            self._drain_event.clear()

            try:
                yield ps.session
            finally:
                self._in_flight -= 1
                if self._in_flight == 0:
                    self._drain_event.set()
                await self._return(ps)
                self._semaphore.release()
        except Exception:
            if acquired:
                self._semaphore.release()
            raise

    async def _borrow(self, headers: dict[str, str] | None) -> PooledSession:
        """Pop an idle session or create a new one."""
        async with self._lock:
            # Try to get an idle session
            while self._idle:
                ps = self._idle.popleft()
                # Check lifetime expiry
                if ps.is_expired(self._config.max_session_lifetime_s):
                    await self._close_session(ps)
                    del self._all_sessions[ps.session_id]
                    self._metrics.sessions_destroyed += 1
                    continue

                ps.mark_borrowed()
                if headers:
                    ps.extra_headers = headers
                self._active.add(ps.session_id)
                self._metrics.active = len(self._active)
                self._metrics.idle = len(self._idle)
                return ps

            # No idle session — create a new one
            if len(self._all_sessions) >= self._config.max_sessions:
                raise PoolExhaustedError("Pool at max capacity")

        # Create outside the lock
        ps = await self._create_session()
        ps.mark_borrowed()
        if headers:
            ps.extra_headers = headers

        async with self._lock:
            self._all_sessions[ps.session_id] = ps
            self._active.add(ps.session_id)
            self._metrics.active = len(self._active)
            self._metrics.total = len(self._all_sessions)

        return ps

    async def _return(self, ps: PooledSession) -> None:
        """Return a session to the idle pool."""
        ps.mark_returned()
        async with self._lock:
            self._active.discard(ps.session_id)
            if not self._shutting_down and ps.session_id in self._all_sessions:
                self._idle.append(ps)
            self._metrics.active = len(self._active)
            self._metrics.idle = len(self._idle)
            self._metrics.return_count += 1

    # ───── tool cache ─────

    async def list_tools(self) -> Any:
        """
        Return the cached ``tools/list`` response, fetching if needed.

        Uses a borrowed session internally if the cache is stale.
        """
        cached = self._cache.get()
        if cached is not None:
            self._metrics.cache_hits += 1
            return cached

        self._metrics.cache_misses += 1
        async with self.session() as sess:
            tools = await sess.list_tools()
            self._cache.set(tools)
            return tools

    def invalidate_tools_cache(self) -> None:
        """Force the tool cache to refetch on the next call."""
        self._cache.invalidate()

    # ───── internal helpers ─────

    async def _create_session(self) -> PooledSession:
        """Create a new MCP session via the configured transport."""
        try:
            if self._config.transport == "streamable_http":
                return await self._create_http_session()
            else:
                return await self._create_stdio_session()
        except Exception as exc:
            self._metrics.errors += 1
            raise SessionError(f"Failed to create session: {exc}") from exc

    async def _create_http_session(self) -> PooledSession:
        """Create a session using streamable HTTP transport."""
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        headers = dict(self._config.mcp_headers)
        if self._config.auth:
            headers["Authorization"] = f"Bearer {self._config.auth}"

        transport_ctx = streamable_http_client(
            self._config.endpoint,
            headers=headers,
        )
        read_stream, write_stream, _ = await transport_ctx.__aenter__()

        session_ctx = ClientSession(read_stream, write_stream)
        session = await session_ctx.__aenter__()
        await session.initialize()

        ps = PooledSession(
            session=session,
            transport_ctx=transport_ctx,
            session_ctx=session_ctx,
            _read_stream=read_stream,
            _write_stream=write_stream,
        )
        self._metrics.sessions_created += 1
        return ps

    async def _create_stdio_session(self) -> PooledSession:
        """Create a session using stdio transport."""
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        server_params = StdioServerParameters(
            command=self._config.endpoint,
            args=self._config.stdio_args,
            env=self._config.stdio_env,
        )

        transport_ctx = stdio_client(server_params)
        read_stream, write_stream = await transport_ctx.__aenter__()

        session_ctx = ClientSession(read_stream, write_stream)
        session = await session_ctx.__aenter__()
        await session.initialize()

        ps = PooledSession(
            session=session,
            transport_ctx=transport_ctx,
            session_ctx=session_ctx,
            _read_stream=read_stream,
            _write_stream=write_stream,
        )
        self._metrics.sessions_created += 1
        return ps

    async def _close_session(self, ps: PooledSession) -> None:
        """Gracefully close a pooled session and its transport."""
        try:
            if ps.session_ctx is not None:
                await ps.session_ctx.__aexit__(None, None, None)
        except Exception:
            logger.debug("Error closing session CM for %s", ps.session_id, exc_info=True)
        try:
            if ps.transport_ctx is not None:
                await ps.transport_ctx.__aexit__(None, None, None)
        except Exception:
            logger.debug("Error closing transport CM for %s", ps.session_id, exc_info=True)

    async def _create_and_add_session(self) -> None:
        """Create a new session and add it to the idle pool."""
        try:
            ps = await self._create_session()
            async with self._lock:
                self._all_sessions[ps.session_id] = ps
                self._idle.append(ps)
                self._metrics.total = len(self._all_sessions)
                self._metrics.idle = len(self._idle)
        except Exception:
            self._metrics.errors += 1
            logger.exception("Failed to create session during warm-up/replacement")

    def _remove_session(self, ps: PooledSession) -> None:
        """Remove a session from the pool (called by health checker)."""
        with suppress(ValueError):
            self._idle.remove(ps)
        self._all_sessions.pop(ps.session_id, None)
        self._active.discard(ps.session_id)
        self._metrics.sessions_destroyed += 1
        self._metrics.total = len(self._all_sessions)
        self._metrics.idle = len(self._idle)
        self._metrics.active = len(self._active)
