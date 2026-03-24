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
        auth_provider: Any | None = None,
        mcp_headers: dict[str, str] | None = None,
        retry_count: int = 2,
        retry_base_delay_s: float = 0.1,
        retry_max_delay_s: float = 2.0,
        failure_threshold: int = 5,
        recovery_timeout_s: float = 30.0,
        enable_opentelemetry: bool = False,
        event_hooks: EventHooks | None = None,
        transport_factory: Any | None = None,
        graceful_degradation: bool = False,
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
                auth_provider=auth_provider,
                mcp_headers=mcp_headers or {},
                retry_count=retry_count,
                retry_base_delay_s=retry_base_delay_s,
                retry_max_delay_s=retry_max_delay_s,
                failure_threshold=failure_threshold,
                recovery_timeout_s=recovery_timeout_s,
                enable_opentelemetry=enable_opentelemetry,
                event_hooks=event_hooks or EventHooks(),
                transport_factory=transport_factory,
                graceful_degradation=graceful_degradation,
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
        self._degraded = False
        self._recovery_task: asyncio.Task[None] | None = None

        # Readiness tracking
        self._ready_event = asyncio.Event()

        # Session affinity map: affinity_key -> session_id
        self._affinity_map: dict[str, str] = {}

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
    def is_ready(self) -> bool:
        """``True`` when min_sessions are warmed and the pool is usable."""
        return self._ready_event.is_set()

    @property
    def is_degraded(self) -> bool:
        """``True`` if the pool is operating in degraded (ephemeral) mode."""
        return self._degraded

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
        self._degraded = False

        # Pre-warm sessions
        tasks = [self._create_and_add_session() for _ in range(self._config.min_sessions)]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        warmup_ok = self._config.min_sessions == 0 or len(self._idle) >= self._config.min_sessions

        if not warmup_ok and self._config.graceful_degradation:
            self._degraded = True
            self._metrics.degraded = True
            logger.warning("MCPPool warmup failed — entering degraded mode (ephemeral sessions)")
            # Start background recovery
            self._recovery_task = asyncio.create_task(
                self._background_recovery(), name="mcpool-recovery"
            )
        elif not warmup_ok:
            # If graceful_degradation is off, still start but with fewer sessions
            logger.warning(
                "MCPPool warmup failed — pool started with %d sessions (wanted %d)",
                len(self._idle),
                self._config.min_sessions,
            )

        self._metrics.idle = len(self._idle)
        self._metrics.total = len(self._all_sessions)

        await self._health_checker.start()

        if not self._degraded and len(self._idle) >= self._config.min_sessions:
            self._ready_event.set()

        logger.info(
            "MCPPool started: %d sessions pre-warmed (min=%d, max=%d)%s",
            len(self._idle),
            self._config.min_sessions,
            self._config.max_sessions,
            " [DEGRADED]" if self._degraded else "",
        )

    async def wait_ready(self, *, timeout_s: float | None = None) -> bool:
        """
        Wait until the pool has warmed ``min_sessions`` and is ready.

        Returns ``True`` if ready, ``False`` on timeout.
        """
        if self._ready_event.is_set():
            return True
        try:
            await asyncio.wait_for(self._ready_event.wait(), timeout=timeout_s)
            return True
        except asyncio.TimeoutError:
            return False

    async def shutdown(self) -> None:
        """Drain in-flight calls and close all sessions."""
        if not self._started:
            return
        self._shutting_down = True

        # Cancel recovery task if running
        if self._recovery_task is not None:
            self._recovery_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._recovery_task
            self._recovery_task = None

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
        self._affinity_map.clear()
        self._started = False
        self._degraded = False
        self._ready_event.clear()
        self._metrics.active = 0
        self._metrics.idle = 0
        self._metrics.total = 0
        self._metrics.degraded = False
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
        affinity_key: str | None = None,
    ) -> AsyncIterator[Any]:
        async with self._session_context(
            headers=headers,
            borrow_timeout_s=self._config.effective_borrow_timeout_s,
            raise_on_timeout=True,
            affinity_key=affinity_key,
        ) as session:
            yield session

    @asynccontextmanager
    async def try_session(
        self,
        headers: dict[str, str] | None = None,
        affinity_key: str | None = None,
    ) -> AsyncIterator[Any | None]:
        """
        Attempt to borrow a session without waiting.

        Yields ``None`` immediately when the pool has no free capacity.
        """
        async with self._session_context(
            headers=headers,
            borrow_timeout_s=0.0,
            raise_on_timeout=False,
            affinity_key=affinity_key,
        ) as session:
            yield session

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        *,
        headers: dict[str, str] | None = None,
    ) -> Any:
        """
        Convenience: borrow a session, call **name**, and return.

        This covers the common one-tool-call pattern::

            result = await pool.call_tool("my_tool", {"key": "value"})
        """
        async with self.session(headers=headers) as sess:
            return await sess.call_tool(name, arguments=arguments)

    def langchain_tools(self) -> list[Any]:
        """
        Return LangChain ``Tool`` objects backed by this pool.

        Requires ``langchain-core`` — install with
        ``pip install "mcpool[langchain]"``.
        """
        from .langchain import langchain_tools as _langchain_tools

        return _langchain_tools(self)

    @asynccontextmanager
    async def _session_context(
        self,
        *,
        headers: dict[str, str] | None,
        borrow_timeout_s: float,
        raise_on_timeout: bool,
        affinity_key: str | None = None,
    ) -> AsyncIterator[Any | None]:
        if self._shutting_down:
            raise PoolShutdownError("Pool is shutting down")
        if not self._started:
            raise PoolShutdownError("Pool has not been started. Call pool.start() first.")

        # In degraded mode, create an ephemeral session.
        if self._degraded:
            ps = await self._create_ephemeral_session(headers)
            try:
                yield ps.session
            finally:
                await self._close_session(ps, reason="ephemeral")
            return

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

            ps = await self._borrow(headers, affinity_key=affinity_key)
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

    async def _borrow(
        self,
        headers: dict[str, str] | None,
        *,
        affinity_key: str | None = None,
    ) -> PooledSession:
        """Pop an idle session or create a new one."""
        # Try affinity-preferred session first.
        if affinity_key:
            ps = await self._try_borrow_affinity(affinity_key, headers)
            if ps is not None:
                return ps

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
                    if affinity_key:
                        ps.affinity_key = affinity_key
                        self._affinity_map[affinity_key] = ps.session_id
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
        if affinity_key:
            ps.affinity_key = affinity_key
            self._affinity_map[affinity_key] = ps.session_id

        async with self._lock:
            self._all_sessions[ps.session_id] = ps
            self._active.add(ps.session_id)
            self._metrics.active = len(self._active)
            self._metrics.total = len(self._all_sessions)

        return ps

    async def _try_borrow_affinity(
        self,
        affinity_key: str,
        headers: dict[str, str] | None,
    ) -> PooledSession | None:
        """Try to borrow the session bound to *affinity_key*."""
        session_id = self._affinity_map.get(affinity_key)
        if session_id is None:
            return None
        async with self._lock:
            ps = self._all_sessions.get(session_id)
            if ps is None or ps.session_id in self._active:
                return None
            # Ensure it's in idle
            try:
                self._idle.remove(ps)
            except ValueError:
                return None
            if ps.is_expired(self._config.max_session_lifetime_s):
                self._all_sessions.pop(ps.session_id, None)
                self._affinity_map.pop(affinity_key, None)
                self._metrics.sessions_destroyed += 1
                self._metrics.total = len(self._all_sessions)
                self._metrics.idle = len(self._idle)
                return None
            ps.mark_borrowed()
            if headers:
                ps.extra_headers = headers
            ps.affinity_key = affinity_key
            self._active.add(ps.session_id)
            self._metrics.active = len(self._active)
            self._metrics.idle = len(self._idle)
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

    # ───── pool resize ─────

    async def resize(
        self,
        *,
        min_sessions: int | None = None,
        max_sessions: int | None = None,
    ) -> None:
        """
        Adjust pool capacity at runtime without restart.

        Only the supplied parameters are changed; omitted ones keep their
        current value.

        Args:
            min_sessions: New minimum session count.
            max_sessions: New maximum session count.

        Raises:
            ValueError: If the new values are invalid.
        """
        new_min = min_sessions if min_sessions is not None else self._config.min_sessions
        new_max = max_sessions if max_sessions is not None else self._config.max_sessions

        if new_min < 0:
            raise ValueError(f"min_sessions must be >= 0, got {new_min}")
        if new_max < 1:
            raise ValueError(f"max_sessions must be >= 1, got {new_max}")
        if new_min > new_max:
            raise ValueError(f"min_sessions ({new_min}) cannot exceed max_sessions ({new_max})")

        old_max = self._config.max_sessions

        # Update config (frozen dataclass — create a new one).
        cfg_dict = {
            f.name: getattr(self._config, f.name)
            for f in self._config.__dataclass_fields__.values()
        }
        cfg_dict["min_sessions"] = new_min
        cfg_dict["max_sessions"] = new_max
        self._config = PoolConfig(**cfg_dict)

        # Adjust semaphore capacity.
        delta = new_max - old_max
        if delta > 0:
            for _ in range(delta):
                self._semaphore.release()
        elif delta < 0:
            for _ in range(-delta):
                try:
                    await asyncio.wait_for(self._semaphore.acquire(), timeout=0.0)
                except asyncio.TimeoutError:
                    break  # Can't shrink further right now

        # Scale up: ensure min_sessions are available.
        current = len(self._all_sessions)
        if current < new_min:
            warmup = [
                self._create_and_add_session(reason="resize") for _ in range(new_min - current)
            ]
            if warmup:
                await asyncio.gather(*warmup, return_exceptions=True)

        # Scale down: drain excess idle sessions.
        async with self._lock:
            while len(self._all_sessions) > new_max and self._idle:
                ps = self._idle.pop()
                self._all_sessions.pop(ps.session_id, None)
                self._affinity_map = {
                    k: v for k, v in self._affinity_map.items() if v != ps.session_id
                }
                self._metrics.sessions_destroyed += 1
                await self._close_session(ps, reason="resize_drain")

            self._metrics.total = len(self._all_sessions)
            self._metrics.idle = len(self._idle)
            self._metrics.active = len(self._active)

        logger.info(
            "MCPPool resized: min=%d, max=%d  (was min=%d, max=%d)",
            new_min,
            new_max,
            self._config.min_sessions if min_sessions is None else old_max,
            new_max,
        )

    # ───── introspection ─────

    def debug_snapshot(self) -> list[dict[str, Any]]:
        """
        Return per-session debug information.

        Useful for debugging production issues — exposes age, idle time,
        borrow count, state, and affinity key for every session.
        """
        snapshots: list[dict[str, Any]] = []
        for ps in self._all_sessions.values():
            state = "active" if ps.session_id in self._active else "idle"
            snapshots.append(
                {
                    "session_id": ps.session_id,
                    "state": state,
                    "age_s": round(ps.age_s, 2),
                    "idle_s": round(ps.idle_s, 2),
                    "borrow_count": ps.borrow_count,
                    "affinity_key": ps.affinity_key,
                }
            )
        return snapshots

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
        # User-supplied transport factory takes precedence.
        if self._config.transport_factory is not None:
            return await self._create_custom_session()
        if self._config.transport == "streamable_http":
            return await self._create_http_session()
        return await self._create_stdio_session()

    async def _resolve_auth_headers(self) -> dict[str, str]:
        """Build headers including dynamic auth if an auth_provider is set."""
        headers = dict(self._config.mcp_headers)
        if self._config.auth_provider is not None:
            token_or_headers = await self._config.auth_provider()
            if isinstance(token_or_headers, dict):
                headers.update(token_or_headers)
            else:
                headers["Authorization"] = f"Bearer {token_or_headers}"
        elif self._config.auth:
            headers["Authorization"] = f"Bearer {self._config.auth}"
        return headers

    def _retry_delay(self, attempt: int) -> float:
        delay = min(
            self._config.retry_max_delay_s,
            self._config.retry_base_delay_s * (2 ** (attempt - 1)),
        )
        if delay == 0:
            return 0.0
        return float(delay + random.uniform(0.0, delay / 2))

    async def _create_custom_session(self) -> PooledSession:
        """Create a session via user-supplied transport_factory."""
        headers = await self._resolve_auth_headers()
        factory = self._config.transport_factory
        assert factory is not None
        result = await factory(self._config.endpoint, headers)
        # Factory must return (read_stream, write_stream, transport_ctx, session_ctx, session)
        if isinstance(result, tuple) and len(result) == 5:
            read_stream, write_stream, transport_ctx, session_ctx, session = result
        else:
            # Fallback: factory returns (session, transport_ctx) for simpler cases.
            session, transport_ctx = result
            read_stream = write_stream = session_ctx = None

        ps = PooledSession(
            session=session,
            transport_ctx=transport_ctx,
            session_ctx=session_ctx,
            _read_stream=read_stream,
            _write_stream=write_stream,
        )
        self._metrics.sessions_created += 1
        return ps

    async def _create_http_session(self) -> PooledSession:
        """Create a session using streamable HTTP transport."""
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        headers = await self._resolve_auth_headers()

        import httpx

        http_client = httpx.AsyncClient(headers=headers)

        transport_ctx = streamable_http_client(
            self._config.endpoint,
            http_client=http_client,
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

    async def _create_ephemeral_session(self, headers: dict[str, str] | None) -> PooledSession:
        """Create a one-off session for degraded mode."""
        ps = await self._create_session()
        if headers:
            ps.extra_headers = headers
        self._metrics.sessions_created += 1  # double-counted intentionally for observability
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
            self._affinity_map = {k: v for k, v in self._affinity_map.items() if v != ps.session_id}
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
            self._affinity_map = {k: v for k, v in self._affinity_map.items() if v != ps.session_id}
            self._metrics.sessions_destroyed += 1
            self._metrics.total = len(self._all_sessions)
            self._metrics.idle = len(self._idle)
            self._metrics.active = len(self._active)

        await self._close_session(ps, reason="recycled")
        await self._create_and_add_session(reason="recycled")

    async def _background_recovery(self) -> None:
        """Attempt to recover from degraded mode in the background."""
        await asyncio.sleep(5.0)  # Initial backoff
        while self._degraded and not self._shutting_down:
            try:
                tasks = [
                    self._create_and_add_session(reason="recovery")
                    for _ in range(self._config.min_sessions)
                ]
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)
                if len(self._idle) >= self._config.min_sessions:
                    self._degraded = False
                    self._metrics.degraded = False
                    self._ready_event.set()
                    logger.info("MCPPool recovered from degraded mode")
                    return
            except Exception:
                logger.debug("Recovery attempt failed", exc_info=True)
            await asyncio.sleep(10.0)

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
