# Author: gadwant
"""
Unit tests for PoolMetrics.
"""

from __future__ import annotations

import time

from mcpool.metrics import PoolMetrics


class TestPoolMetricsDefaults:
    def test_initial_counters_are_zero(self, metrics: PoolMetrics):
        assert metrics.active == 0
        assert metrics.idle == 0
        assert metrics.borrow_count == 0
        assert metrics.errors == 0

    def test_uptime_increases(self, metrics: PoolMetrics):
        assert metrics.uptime_s >= 0.0
        time.sleep(0.01)
        assert metrics.uptime_s > 0.0


class TestPoolMetricsComputed:
    def test_avg_borrow_wait_zero_borrows(self, metrics: PoolMetrics):
        assert metrics.avg_borrow_wait_s == 0.0

    def test_avg_borrow_wait(self, metrics: PoolMetrics):
        metrics.borrow_count = 4
        metrics.borrow_wait_total_s = 2.0
        assert metrics.avg_borrow_wait_s == 0.5

    def test_cache_hit_rate_no_ops(self, metrics: PoolMetrics):
        assert metrics.cache_hit_rate == 0.0

    def test_cache_hit_rate(self, metrics: PoolMetrics):
        metrics.cache_hits = 3
        metrics.cache_misses = 1
        assert metrics.cache_hit_rate == 0.75


class TestPoolMetricsSnapshot:
    def test_snapshot_contains_all_keys(self, metrics: PoolMetrics):
        snap = metrics.snapshot()
        expected_keys = {
            "active",
            "idle",
            "total",
            "borrow_count",
            "avg_borrow_wait_s",
            "return_count",
            "cache_hits",
            "cache_misses",
            "cache_refresh_count",
            "cache_waiters",
            "cache_hit_rate",
            "reconnect_count",
            "retry_attempts",
            "health_check_count",
            "health_check_failures",
            "recycled_count",
            "sessions_created",
            "sessions_destroyed",
            "errors",
            "circuit_state",
            "degraded",
            "rate_limit_waits",
            "rate_limit_rejects",
            "tenant_rejects",
            "autoscale_ups",
            "autoscale_downs",
            "uptime_s",
        }
        assert set(snap.keys()) == expected_keys

    def test_snapshot_is_immutable(self, metrics: PoolMetrics):
        snap = metrics.snapshot()
        metrics.borrow_count = 999
        assert snap["borrow_count"] == 0

    def test_snapshot_degraded_field(self, metrics: PoolMetrics):
        assert metrics.snapshot()["degraded"] is False
        metrics.degraded = True
        assert metrics.snapshot()["degraded"] is True


class TestPoolMetricsReset:
    def test_reset_clears_all(self, metrics: PoolMetrics):
        metrics.borrow_count = 42
        metrics.errors = 7
        metrics.cache_hits = 100
        metrics.degraded = True
        metrics.reset()
        assert metrics.borrow_count == 0
        assert metrics.errors == 0
        assert metrics.cache_hits == 0
        assert metrics.degraded is False


class TestPoolMetricsPrometheus:
    def test_to_prometheus_returns_dict(self, metrics: PoolMetrics):
        prom = metrics.to_prometheus()
        assert isinstance(prom, dict)
        assert "mcpool_active_sessions" in prom
        assert "mcpool_borrow_total" in prom
        assert "mcpool_errors_total" in prom

    def test_to_prometheus_values_match_snapshot(self, metrics: PoolMetrics):
        metrics.borrow_count = 10
        metrics.errors = 2
        prom = metrics.to_prometheus()
        assert prom["mcpool_borrow_total"] == 10
        assert prom["mcpool_errors_total"] == 2
