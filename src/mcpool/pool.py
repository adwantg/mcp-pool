# Author: gadwant
"""
MCPPool — the core async connection pool for MCP client sessions.
"""
from __future__ import annotations

import asyncio
import inspect
import logging
import random
import time
from collections import deque
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from typing import Any

from .cache import ToolCache
from .circuit import CircuitBreaker
from .config import PoolConfig
from .errors import CircuitOpenError, PoolExhaustedError, PoolShutdownError, SessionError
from .health import HealthChecker
from .hooks import EventHooks
from .metrics import PoolMetrics
from .session import PooledSession
from .telemetry import PoolTelemetry

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
        recycle_window_s: float = 30.0,
        connect_timeout_s: float = 10.0,
        borrow_timeout_s: float | None = None,
        drain_timeout_s: float = 30.0,
        auth: str | None = None,
        mcp_headers: dict[str, str] | None = None,
        retry_count: int = 2,
        retry_base_delay_s: float = 0.1,
        retry_max_delay_s: float = 2.0,
        failure_threshold: int = 5,
        recovery_timeout_s: float = 30.0,
        enable_opentelemetry: bool = False,
        event_hooks: EventHooks | None = None,
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
                recycle_window_s=recycle_window_s,
                connect_timeout_s=connect_timeout_s,
                borrow_timeout_s=borrow_timeout_s,
                drain_timeout_s=drain_timeout_s,
                auth=auth,
                mcp_headers=mcp_headers or {},
                retry_count=retry_count,
                retry_base_delay_s=retry_base_delay_s,
                retry_max_delay_s=retry_max_delay_s,
                failure_threshold=failure_threshold,
                recovery_timeout_s=recovery_timeout_s,
                enable_opentelemetry=enable_opentelemetry,
                event_hooks=event_hooks or EventHooks(),
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
        self._hooks = self._config.event_hooks
        self._telemetry = PoolTelemetry(
            enabled=self._config.enable_opentelemetry,
            metrics=self._metrics,
            transport=self._config.transport,
            endpoint=self._config.endpoint,
        )
        self._circuit_breaker = CircuitBreaker(
            failure_threshold=self._config.failure_threshold,
            recovery_timeout_s=self._config.recovery_timeout_s,
            on_state_change=self._on_circuit_state_change,
        )
        self._metrics.circuit_state = self._circuit_breaker.state

        self._health_checker = HealthChecker(
            interval_s=self._config.health_check_interval_s,
            get_idle_sessions=lambda: list(self._idle),
            remove_session=self._remove_session,
            replace_session=lambda: self._create_and_add_session(reason="health_replace"),
            metrics=self._metrics,
            recycle_session=self._recycle_idle_session,
            should_recycle=self._should_recycle_session,
            on_health_check_failed=self._on_health_check_failed,
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
        async with self._session_context(
            headers=headers,
            borrow_timeout_s=self._config.effective_borrow_timeout_s,
            raise_on_timeout=True,
        ) as session:
            yield session

    @asynccontextmanager
    async def try_session(
        self,
        headers: dict[str, str] | None = None,
    ) -> AsyncIterator[Any | None]:
        """
        Attempt to borrow a session without waiting.

        Yields ``None`` immediately when the pool has no free capacity.
        """
        async with self._session_context(
            headers=headers,
            borrow_timeout_s=0.0,
            raise_on_timeout=False,
        ) as session:
            yield session

    @asynccontextmanager
    async def _session_context(
        self,
        *,
        headers: dict[str, str] | None,
        borrow_timeout_s: float,
        raise_on_timeout: bool,
    ) -> AsyncIterator[Any | None]:
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
        acquired = False
        released = False
        ps: PooledSession | None = None
        try:
            acquired = await self._acquire_capacity(
                borrow_timeout_s=borrow_timeout_s,
                raise_on_timeout=raise_on_timeout,
            )
            if not acquired:
                yield None
                return
            if self._shutting_down:
                released = True
                self._semaphore.release()
                raise PoolShutdownError("Pool is shutting down")

            ps = await self._borrow(headers)
            borrow_wait_s = time.monotonic() - wait_start
            self._metrics.borrow_count += 1
            self._metrics.borrow_wait_total_s += borrow_wait_s
            self._telemetry.record_borrow_wait(borrow_wait_s)

            self._in_flight += 1
            self._drain_event.clear()
            await self._emit_hook(
                "on_borrow",
                {
                    "session_id": ps.session_id,
                    "borrow_wait_s": round(borrow_wait_s, 6),
                    "active": len(self._active),
                    "idle": len(self._idle),
                },
            )

            try:
                async with self._telemetry.span("pool.borrow"):
                    yield ps.session
            finally:
                self._in_flight -= 1
                if self._in_flight == 0:
                    self._drain_event.set()
                if ps is not None:
                    await self._return(ps)
                    await self._emit_hook(
                        "on_return",
                        {
                            "session_id": ps.session_id,
                            "active": len(self._active),
                            "idle": len(self._idle),
                        },
                    )
                if acquired:
                    self._semaphore.release()
                    released = True
        except Exception:
            if acquired and not released:
                self._semaphore.release()
            raise

    async def _acquire_capacity(
        self,
        *,
        borrow_timeout_s: float,
        raise_on_timeout: bool,
    ) -> bool:
        """Acquire a pool slot, optionally without waiting."""
        if borrow_timeout_s == 0:
            if self._semaphore.locked():
                if raise_on_timeout:
                    raise PoolExhaustedError("No session available immediately")
                return False
            await self._semaphore.acquire()
            return True

        try:
            await asyncio.wait_for(
                self._semaphore.acquire(),
                timeout=borrow_timeout_s,
            )
            return True
        except asyncio.TimeoutError:
            if raise_on_timeout:
                raise PoolExhaustedError(
                    f"No session available within {borrow_timeout_s}s"
                ) from None
            return False

    async def _borrow(self, headers: dict[str, str] | None) -> PooledSession:
        """Pop an idle session or create a new one."""
        while True:
            if self._shutting_down:
                raise PoolShutdownError("Pool is shutting down")
            expired: PooledSession | None = None
            needs_create = False
            async with self._lock:
                while self._idle:
                    ps = self._idle.popleft()
                    if ps.is_expired(self._config.max_session_lifetime_s):
                        expired = ps
                        self._all_sessions.pop(ps.session_id, None)
                        self._metrics.sessions_destroyed += 1
                        self._metrics.total = len(self._all_sessions)
                        self._metrics.idle = len(self._idle)
                        break

                    ps.mark_borrowed()
                    if headers:
                        ps.extra_headers = headers
                    self._active.add(ps.session_id)
                    self._metrics.active = len(self._active)
                    self._metrics.idle = len(self._idle)
                    return ps

                if expired is None and len(self._all_sessions) >= self._config.max_sessions:
                    raise PoolExhaustedError("Pool at max capacity")
                if expired is None:
                    needs_create = True

            if expired is not None:
                self._metrics.recycled_count += 1
                await self._close_session(expired, reason="expired")
                continue
            if needs_create:
                break

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
        async with self._telemetry.span("pool.return"), self._lock:
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
        async with self._telemetry.span("list_tools"):
            cached = self._cache.get()
            if cached is not None:
                self._metrics.cache_hits += 1
                return cached

            result = await self._cache.get_or_fetch(self._fetch_tools_uncached)
            if result.waited:
                self._metrics.cache_waiters += 1
            if result.refreshed:
                self._metrics.cache_misses += 1
                self._metrics.cache_refresh_count += 1
            elif result.hit:
                self._metrics.cache_hits += 1
            return result.value

    def invalidate_tools_cache(self) -> None:
        """Force the tool cache to refetch on the next call."""
        self._cache.invalidate()

    # ───── internal helpers ─────

    async def _fetch_tools_uncached(self) -> Any:
        async with self.session() as sess:
            return await sess.list_tools()

    async def _create_session(self) -> PooledSession:
        """Create a new MCP session with retries and circuit-breaker protection."""
        last_exc: Exception | None = None

        for attempt in range(self._config.retry_count + 1):
            if attempt > 0:
                self._metrics.retry_attempts += 1
                await asyncio.sleep(self._retry_delay(attempt))

            try:
                await self._circuit_breaker.before_request()
                async with self._telemetry.span("session.create"):
                    ps = await asyncio.wait_for(
                        self._create_session_once(),
                        timeout=self._config.connect_timeout_s,
                    )
            except CircuitOpenError as exc:
                self._metrics.errors += 1
                self._telemetry.record_error("circuit_open")
                raise SessionError(f"Failed to create session: {exc}") from exc
            except Exception as exc:
                last_exc = exc
                await self._circuit_breaker.record_failure()
                if attempt >= self._config.retry_count:
                    self._metrics.errors += 1
                    self._telemetry.record_error("session_create")
                    raise SessionError(f"Failed to create session: {exc}") from exc
                continue
            else:
                await self._circuit_breaker.record_success()
                return ps

        self._metrics.errors += 1
        self._telemetry.record_error("session_create")
        raise SessionError(f"Failed to create session: {last_exc}") from last_exc

    async def _create_session_once(self) -> PooledSession:
        if self._config.transport == "streamable_http":
            return await self._create_http_session()
        return await self._create_stdio_session()

    def _retry_delay(self, attempt: int) -> float:
        delay = min(
            self._config.retry_max_delay_s,
            self._config.retry_base_delay_s * (2 ** (attempt - 1)),
        )
        if delay == 0:
            return 0.0
        return float(delay + random.uniform(0.0, delay / 2))

    async def _create_http_session(self) -> PooledSession:
        """Create a session using streamable HTTP transport."""
        from mcp.client.streamable_http import (  # type: ignore[import-not-found]  # noqa: I001
            streamable_http_client,
        )
        from mcp import ClientSession  # type: ignore[import-not-found]

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
        from mcp.client.stdio import stdio_client  # type: ignore[import-not-found]  # noqa: I001
        from mcp import ClientSession, StdioServerParameters

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

    async def _close_session(self, ps: PooledSession, *, reason: str = "closed") -> None:
        """Gracefully close a pooled session and its transport."""
        async with self._telemetry.span("session.close", attributes={"mcpool.reason": reason}):
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
        await self._emit_hook(
            "on_session_destroyed",
            {"session_id": ps.session_id, "reason": reason},
        )

    async def _create_and_add_session(self, *, reason: str = "warmup") -> None:
        """Create a new session and add it to the idle pool."""
        ps: PooledSession | None = None
        try:
            ps = await self._create_session()
            async with self._lock:
                self._all_sessions[ps.session_id] = ps
                self._idle.append(ps)
                self._metrics.total = len(self._all_sessions)
                self._metrics.idle = len(self._idle)
            if reason == "health_replace":
                self._metrics.reconnect_count += 1
            await self._emit_hook(
                "on_session_created",
                {"session_id": ps.session_id, "reason": reason},
            )
        except Exception:
            logger.exception("Failed to create session during %s", reason)

    async def _remove_session(self, ps: PooledSession) -> None:
        """Remove a session from the pool and close its transport."""
        async with self._lock:
            with suppress(ValueError):
                self._idle.remove(ps)
            self._all_sessions.pop(ps.session_id, None)
            self._active.discard(ps.session_id)
            self._metrics.sessions_destroyed += 1
            self._metrics.total = len(self._all_sessions)
            self._metrics.idle = len(self._idle)
            self._metrics.active = len(self._active)
        await self._close_session(ps, reason="health_failed")

    def _should_recycle_session(self, ps: PooledSession) -> bool:
        if self._config.max_session_lifetime_s <= 0:
            return False
        recycle_after_s = self._config.max_session_lifetime_s - self._config.recycle_window_s
        return ps.age_s >= recycle_after_s

    async def _recycle_idle_session(self, ps: PooledSession) -> None:
        async with self._lock:
            if ps.session_id not in self._all_sessions:
                return
            with suppress(ValueError):
                self._idle.remove(ps)
            self._all_sessions.pop(ps.session_id, None)
            self._active.discard(ps.session_id)
            self._metrics.sessions_destroyed += 1
            self._metrics.total = len(self._all_sessions)
            self._metrics.idle = len(self._idle)
            self._metrics.active = len(self._active)

        await self._close_session(ps, reason="recycled")
        await self._create_and_add_session(reason="recycled")

    async def _on_health_check_failed(self, ps: PooledSession, exc: Exception) -> None:
        await self._emit_hook(
            "on_health_check_failed",
            {
                "session_id": ps.session_id,
                "error": str(exc),
            },
        )

    async def _on_circuit_state_change(self, previous: str, new: str) -> None:
        self._metrics.circuit_state = new
        if new == "open":
            await self._emit_hook(
                "on_circuit_open",
                {"previous_state": previous, "state": new},
            )
        elif new == "closed":
            await self._emit_hook(
                "on_circuit_close",
                {"previous_state": previous, "state": new},
            )

    async def _emit_hook(self, hook_name: str, payload: dict[str, Any]) -> None:
        hook = getattr(self._hooks, hook_name, None)
        if hook is None:
            return
        try:
            result = hook(payload)
            if inspect.isawaitable(result):
                await result
        except Exception:
            logger.exception("Event hook %s failed", hook_name)
