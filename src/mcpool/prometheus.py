# Author: gadwant
"""
Prometheus-compatible metrics export.

Returns pool metrics in a flat dict structure compatible with
the ``prometheus_client`` library.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .metrics import PoolMetrics


def to_prometheus(metrics: PoolMetrics) -> dict[str, float | int]:
    """
    Convert a :class:`PoolMetrics` snapshot to Prometheus-friendly names.

    Returns a flat dict with metric names using ``_`` separators and
    Prometheus naming conventions (``_total`` for counters, no suffix
    for gauges).

    Usage::

        prom = pool.metrics.to_prometheus()
        # {"mcpool_active_sessions": 3, "mcpool_borrow_total": 42, ...}
    """
    snap = metrics.snapshot()
    return {
        # Gauges
        "mcpool_active_sessions": snap["active"],
        "mcpool_idle_sessions": snap["idle"],
        "mcpool_total_sessions": snap["total"],
        "mcpool_avg_borrow_wait_seconds": snap["avg_borrow_wait_s"],
        "mcpool_cache_hit_rate": snap["cache_hit_rate"],
        "mcpool_uptime_seconds": snap["uptime_s"],
        # Counters (Prometheus convention: *_total suffix)
        "mcpool_borrow_total": snap["borrow_count"],
        "mcpool_return_total": snap["return_count"],
        "mcpool_cache_hits_total": snap["cache_hits"],
        "mcpool_cache_misses_total": snap["cache_misses"],
        "mcpool_cache_refresh_total": snap["cache_refresh_count"],
        "mcpool_cache_waiters_total": snap["cache_waiters"],
        "mcpool_reconnect_total": snap["reconnect_count"],
        "mcpool_retry_attempts_total": snap["retry_attempts"],
        "mcpool_health_check_total": snap["health_check_count"],
        "mcpool_health_check_failures_total": snap["health_check_failures"],
        "mcpool_recycled_total": snap["recycled_count"],
        "mcpool_sessions_created_total": snap["sessions_created"],
        "mcpool_sessions_destroyed_total": snap["sessions_destroyed"],
        "mcpool_errors_total": snap["errors"],
    }
