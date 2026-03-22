# Author: gadwant
"""
mcpool — async connection pool for MCP client sessions.
"""
from __future__ import annotations

from .cache import ToolCache
from .config import PoolConfig
from .errors import (
    HealthCheckError,
    PoolError,
    PoolExhaustedError,
    PoolShutdownError,
    SessionError,
)
from .metrics import PoolMetrics
from .pool import MCPPool
from .session import PooledSession

__all__ = [
    "HealthCheckError",
    # Core
    "MCPPool",
    "PoolConfig",
    # Errors
    "PoolError",
    "PoolExhaustedError",
    "PoolMetrics",
    "PoolShutdownError",
    "PooledSession",
    "SessionError",
    "ToolCache",
]

__version__ = "0.1.0"
