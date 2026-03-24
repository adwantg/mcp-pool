# Author: gadwant
"""
mcpool — async connection pool for MCP client sessions.
"""

from __future__ import annotations

from .cache import ToolCache
from .circuit import CircuitBreaker
from .cloudwatch import CloudWatchPublisher
from .config import AuthProvider, HealthProbe, PoolConfig, TransportFactory, WarmupHook
from .errors import (
    CircuitOpenError,
    HealthCheckError,
    PoolError,
    PoolExhaustedError,
    PoolShutdownError,
    SessionError,
)
from .hooks import EventHooks
from .manager import MCPPoolManager
from .metrics import PoolMetrics
from .oauth import OAuthConfig, OAuthProvider
from .pool import MCPPool
from .rate_limiter import RateLimiterConfig, TokenBucketLimiter
from .session import PooledSession
from .tenant import TenantLimiter, TenantLimiterConfig

__all__ = [
    "AuthProvider",
    "CircuitBreaker",
    "CircuitOpenError",
    "CloudWatchPublisher",
    "EventHooks",
    "HealthCheckError",
    "HealthProbe",
    "MCPPool",
    "MCPPoolManager",
    "OAuthConfig",
    "OAuthProvider",
    "PoolConfig",
    "PoolError",
    "PoolExhaustedError",
    "PoolMetrics",
    "PoolShutdownError",
    "PooledSession",
    "RateLimiterConfig",
    "SessionError",
    "TenantLimiter",
    "TenantLimiterConfig",
    "TokenBucketLimiter",
    "ToolCache",
    "TransportFactory",
    "WarmupHook",
]

__version__ = "1.0.0"
