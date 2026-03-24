# Author: gadwant
"""
mcpool exception hierarchy.
"""

from __future__ import annotations


class PoolError(Exception):
    """Base exception for all mcpool errors."""


class PoolExhaustedError(PoolError):
    """Raised when no sessions are available and the pool is at max capacity."""


class PoolShutdownError(PoolError):
    """Raised when operations are attempted on a pool that has been shut down."""


class SessionError(PoolError):
    """Raised when a session operation fails (connect, initialize, ping)."""


class HealthCheckError(PoolError):
    """Raised when a health check detects an unrecoverable problem."""


class CircuitOpenError(PoolError):
    """Raised when session creation is blocked by the circuit breaker."""
