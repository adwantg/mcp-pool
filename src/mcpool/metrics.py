# Author: gadwant
"""
Pool metrics and observability.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class PoolMetrics:
    """
    Live counters for pool activity.

    All fields are updated atomically by the pool and can be read
    at any time for monitoring dashboards.
    """

    active: int = 0
    idle: int = 0
    total: int = 0
    borrow_count: int = 0
    borrow_wait_total_s: float = 0.0
    return_count: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    cache_refresh_count: int = 0
    cache_waiters: int = 0
    reconnect_count: int = 0
    retry_attempts: int = 0
    health_check_count: int = 0
    health_check_failures: int = 0
    recycled_count: int = 0
    sessions_created: int = 0
    sessions_destroyed: int = 0
    errors: int = 0
    circuit_state: str = "closed"
    _start_time: float = field(default_factory=time.monotonic)

    @property
    def uptime_s(self) -> float:
        """Seconds since the metrics tracker was initialized."""
        return time.monotonic() - self._start_time

    @property
    def avg_borrow_wait_s(self) -> float:
        """Average borrow wait time in seconds."""
        if self.borrow_count == 0:
            return 0.0
        return self.borrow_wait_total_s / self.borrow_count

    @property
    def cache_hit_rate(self) -> float:
        """Cache hit rate as a float between 0.0 and 1.0."""
        total = self.cache_hits + self.cache_misses
        if total == 0:
            return 0.0
        return self.cache_hits / total

    def snapshot(self) -> dict[str, object]:
        """Return a frozen dictionary snapshot of current metrics."""
        return {
            "active": self.active,
            "idle": self.idle,
            "total": self.total,
            "borrow_count": self.borrow_count,
            "avg_borrow_wait_s": round(self.avg_borrow_wait_s, 6),
            "return_count": self.return_count,
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "cache_refresh_count": self.cache_refresh_count,
            "cache_waiters": self.cache_waiters,
            "cache_hit_rate": round(self.cache_hit_rate, 4),
            "reconnect_count": self.reconnect_count,
            "retry_attempts": self.retry_attempts,
            "health_check_count": self.health_check_count,
            "health_check_failures": self.health_check_failures,
            "recycled_count": self.recycled_count,
            "sessions_created": self.sessions_created,
            "sessions_destroyed": self.sessions_destroyed,
            "errors": self.errors,
            "circuit_state": self.circuit_state,
            "uptime_s": round(self.uptime_s, 2),
        }

    def reset(self) -> None:
        """Reset all counters to zero."""
        self.active = 0
        self.idle = 0
        self.total = 0
        self.borrow_count = 0
        self.borrow_wait_total_s = 0.0
        self.return_count = 0
        self.cache_hits = 0
        self.cache_misses = 0
        self.cache_refresh_count = 0
        self.cache_waiters = 0
        self.reconnect_count = 0
        self.retry_attempts = 0
        self.health_check_count = 0
        self.health_check_failures = 0
        self.recycled_count = 0
        self.sessions_created = 0
        self.sessions_destroyed = 0
        self.errors = 0
        self.circuit_state = "closed"
        self._start_time = time.monotonic()
