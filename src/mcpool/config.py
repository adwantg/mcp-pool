# Author: gadwant
"""
Pool configuration.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


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
        connect_timeout_s: Timeout for establishing a new session.
        drain_timeout_s: Max wait for in-flight calls during shutdown.
        auth: Optional authentication token or API key.
        mcp_headers: Extra headers sent on every MCP request.
        stdio_args: Arguments for stdio transport command.
        stdio_env: Environment variables for stdio transport.
    """

    endpoint: str = ""
    transport: Literal["streamable_http", "stdio"] = "streamable_http"
    min_sessions: int = 2
    max_sessions: int = 10
    health_check_interval_s: float = 30.0
    tool_cache_ttl_s: float = 300.0
    max_session_lifetime_s: float = 3600.0
    connect_timeout_s: float = 10.0
    drain_timeout_s: float = 30.0
    auth: str | None = None
    mcp_headers: dict[str, str] = field(default_factory=dict)
    stdio_args: list[str] = field(default_factory=list)
    stdio_env: dict[str, str] | None = None

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
        if self.transport == "streamable_http" and not self.endpoint:
            raise ValueError("endpoint is required for streamable_http transport")
        if self.transport == "stdio" and not self.endpoint:
            raise ValueError("endpoint (command) is required for stdio transport")
