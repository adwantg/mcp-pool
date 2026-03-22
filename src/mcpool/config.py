# Author: gadwant
"""
Pool configuration.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from .hooks import EventHooks


@dataclass(frozen=True)
class PoolConfig:
    """
    Configuration for an MCPPool instance.

    Attributes:
        endpoint: MCP server URL (for streamable_http) or command (for stdio).
        transport: Transport type — ``"streamable_http"`` or ``"stdio"``.
        min_sessions: Number of sessions to pre-warm on ``start()``.
        max_sessions: Hard cap on concurrent sessions.
        health_check_interval_s: Seconds between idle-session pings.
            Set to ``0`` to disable periodic health checks.
        tool_cache_ttl_s: Seconds to cache ``tools/list`` responses.
            Set to ``0`` to disable caching.
        max_session_lifetime_s: Force-recycle a session after this many
            seconds.  Set to ``0`` to disable.
        recycle_window_s: Proactively recycle idle sessions this many
            seconds before their lifetime expires.
        connect_timeout_s: Timeout for establishing a new session.
        borrow_timeout_s: Timeout for waiting on pool capacity.
            ``None`` defaults to ``connect_timeout_s``.
        drain_timeout_s: Max wait for in-flight calls during shutdown.
        auth: Optional authentication token or API key.
        mcp_headers: Extra headers sent on every MCP request.
        stdio_args: Arguments for stdio transport command.
        stdio_env: Environment variables for stdio transport.
        retry_count: Number of retries for session creation after the first attempt.
        retry_base_delay_s: Base retry delay before exponential backoff.
        retry_max_delay_s: Maximum retry delay cap.
        failure_threshold: Consecutive session-creation failures before opening
            the circuit breaker.
        recovery_timeout_s: Seconds to keep the circuit open before a half-open probe.
        enable_opentelemetry: Enable OpenTelemetry spans/metrics when the optional
            dependency is installed.
        event_hooks: Optional async lifecycle callbacks.
    """

    endpoint: str = ""
    transport: Literal["streamable_http", "stdio"] = "streamable_http"
    min_sessions: int = 2
    max_sessions: int = 10
    health_check_interval_s: float = 30.0
    tool_cache_ttl_s: float = 300.0
    max_session_lifetime_s: float = 3600.0
    recycle_window_s: float = 30.0
    connect_timeout_s: float = 10.0
    borrow_timeout_s: float | None = None
    drain_timeout_s: float = 30.0
    auth: str | None = None
    mcp_headers: dict[str, str] = field(default_factory=dict)
    stdio_args: list[str] = field(default_factory=list)
    stdio_env: dict[str, str] | None = None
    retry_count: int = 2
    retry_base_delay_s: float = 0.1
    retry_max_delay_s: float = 2.0
    failure_threshold: int = 5
    recovery_timeout_s: float = 30.0
    enable_opentelemetry: bool = False
    event_hooks: EventHooks = field(default_factory=EventHooks)

    @property
    def effective_borrow_timeout_s(self) -> float:
        if self.borrow_timeout_s is None:
            return self.connect_timeout_s
        return self.borrow_timeout_s

    def __post_init__(self) -> None:
        if self.min_sessions < 0:
            raise ValueError(f"min_sessions must be >= 0, got {self.min_sessions}")
        if self.max_sessions < 1:
            raise ValueError(f"max_sessions must be >= 1, got {self.max_sessions}")
        if self.min_sessions > self.max_sessions:
            raise ValueError(
                f"min_sessions ({self.min_sessions}) cannot exceed "
                f"max_sessions ({self.max_sessions})"
            )
        if self.recycle_window_s < 0:
            raise ValueError(f"recycle_window_s must be >= 0, got {self.recycle_window_s}")
        if self.max_session_lifetime_s > 0 and self.recycle_window_s >= self.max_session_lifetime_s:
            raise ValueError(
                "recycle_window_s must be smaller than max_session_lifetime_s when lifetime "
                "recycling is enabled"
            )
        if self.connect_timeout_s <= 0:
            raise ValueError(f"connect_timeout_s must be > 0, got {self.connect_timeout_s}")
        if self.borrow_timeout_s is not None and self.borrow_timeout_s < 0:
            raise ValueError(f"borrow_timeout_s must be >= 0, got {self.borrow_timeout_s}")
        if self.drain_timeout_s <= 0:
            raise ValueError(f"drain_timeout_s must be > 0, got {self.drain_timeout_s}")
        if self.retry_count < 0:
            raise ValueError(f"retry_count must be >= 0, got {self.retry_count}")
        if self.retry_base_delay_s < 0:
            raise ValueError(
                f"retry_base_delay_s must be >= 0, got {self.retry_base_delay_s}"
            )
        if self.retry_max_delay_s < self.retry_base_delay_s:
            raise ValueError(
                "retry_max_delay_s must be >= retry_base_delay_s"
            )
        if self.failure_threshold < 1:
            raise ValueError(f"failure_threshold must be >= 1, got {self.failure_threshold}")
        if self.recovery_timeout_s <= 0:
            raise ValueError(
                f"recovery_timeout_s must be > 0, got {self.recovery_timeout_s}"
            )
        if self.transport == "streamable_http" and not self.endpoint:
            raise ValueError("endpoint is required for streamable_http transport")
        if self.transport == "stdio" and not self.endpoint:
            raise ValueError("endpoint (command) is required for stdio transport")
