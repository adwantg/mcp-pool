# Author: gadwant
"""
mcpool — async connection pool for MCP client sessions.
"""
from __future__ import annotations

from .cache import ToolCache
from .circuit import CircuitBreaker
from .config import PoolConfig
from .errors import (
    CircuitOpenError,
    HealthCheckError,
    PoolError,
    PoolExhaustedError,
    PoolShutdownError,
    SessionError,
)
from .hooks import EventHooks
from .metrics import PoolMetrics
from .pool import MCPPool
from .session import PooledSession

__all__ = [
    "CircuitBreaker",
    "CircuitOpenError",
    "EventHooks",
    "HealthCheckError",
    "MCPPool",
    "PoolConfig",
    "PoolError",
    "PoolExhaustedError",
    "PoolMetrics",
    "PoolShutdownError",
    "PooledSession",
    "SessionError",
    "ToolCache",
]

__version__ = "0.2.0"
