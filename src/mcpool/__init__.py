# Author: gadwant
"""
mcpool — async connection pool for MCP client sessions.
"""

from __future__ import annotations

from .cache import ToolCache
from .circuit import CircuitBreaker
from .cloudwatch import CloudWatchPublisher
from .config import AuthProvider, PoolConfig, TransportFactory
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
    "AuthProvider",
    "CircuitBreaker",
    "CircuitOpenError",
    "CloudWatchPublisher",
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
    "TransportFactory",
]

__version__ = "0.3.0"
