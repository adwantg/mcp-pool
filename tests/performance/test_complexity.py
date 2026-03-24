# Author: gadwant
"""
Performance / complexity tests using bigocheck.

Validates that core operations have the expected TIME and SPACE complexity
to ensure the pool doesn't degrade at scale.

Uses bigocheck's verify_bounds() for imperative tests and
@assert_complexity() decorator for declarative complexity contracts.
"""
from __future__ import annotations

import tracemalloc
from collections import deque

from bigocheck import assert_complexity, verify_bounds
from tests.conftest import MockMCPSession

from mcpool.cache import ToolCache
from mcpool.metrics import PoolMetrics
from mcpool.session import PooledSession

# ─── Input sizes ───

SIZES = [100, 500, 1000, 5000, 10000]
SMALL_SIZES = [100, 500, 1000, 2000]


# ═══════════════════════════════════════════════════════════════
# TIME COMPLEXITY TESTS
# ═══════════════════════════════════════════════════════════════


class TestToolCacheTimeComplexity:
    """Tool cache get/set should be O(1) per operation."""

    def test_cache_set_is_constant_time(self):
        """N set operations should be O(n) total => O(1) per op."""

        def cache_set_n_times(n: int) -> None:
            cache = ToolCache(ttl_s=3600)
            for i in range(n):
                cache.set(f"tools_{i}")

        result = verify_bounds(cache_set_n_times, SIZES, expected="O(n)", tolerance=0.5)
        assert result.passes, result.message

    def test_cache_get_is_constant_time(self):
        """N get operations should be O(n) total => O(1) per op."""

        def cache_get_n_times(n: int) -> None:
            cache = ToolCache(ttl_s=3600)
            cache.set("tools")
            for _ in range(n):
                cache.get()

        result = verify_bounds(cache_get_n_times, SIZES, expected="O(n)")
        assert result.passes, result.message

    def test_cache_invalidate_is_constant_time(self):
        """N invalidate operations should be O(n) total => O(1) per op."""

        def cache_invalidate_n_times(n: int) -> None:
            cache = ToolCache(ttl_s=3600)
            for _ in range(n):
                cache.set("data")
                cache.invalidate()

        result = verify_bounds(cache_invalidate_n_times, SIZES, expected="O(n)")
        assert result.passes, result.message


class TestSessionCreationTimeComplexity:
    """Session creation should scale linearly with count."""

    def test_pooled_session_creation_is_linear(self):
        """Creating n PooledSession objects should be O(n)."""

        def create_sessions(n: int) -> None:
            for _ in range(n):
                PooledSession(session=MockMCPSession())

        result = verify_bounds(create_sessions, SMALL_SIZES, expected="O(n)", tolerance=0.8)
        assert result.passes, result.message


class TestMetricsTimeComplexity:
    """Metrics snapshot should be O(1) per call."""

    def test_snapshot_is_constant_time(self):
        """N snapshot calls should be O(n) total."""

        def snapshot_n_times(n: int) -> None:
            metrics = PoolMetrics()
            metrics.borrow_count = n
            metrics.cache_hits = n
            for _ in range(n):
                metrics.snapshot()

        result = verify_bounds(snapshot_n_times, SIZES, expected="O(n)", tolerance=0.8)
        assert result.passes, result.message

    def test_to_prometheus_is_constant_time(self):
        """N to_prometheus() calls should be O(n) total => O(1) per op."""

        def prometheus_n_times(n: int) -> None:
            metrics = PoolMetrics()
            metrics.borrow_count = n
            for _ in range(n):
                metrics.to_prometheus()

        result = verify_bounds(prometheus_n_times, SIZES, expected="O(n)", tolerance=0.8)
        assert result.passes, result.message


class TestSessionMarkTimeComplexity:
    """mark_borrowed / mark_returned should be O(1)."""

    def test_mark_borrowed_is_constant(self):
        def mark_n_times(n: int) -> None:
            ps = PooledSession(session=MockMCPSession())
            for _ in range(n):
                ps.mark_borrowed()

        result = verify_bounds(mark_n_times, SIZES, expected="O(n)", tolerance=0.5)
        assert result.passes, result.message

    def test_mark_returned_is_constant(self):
        def mark_n_times(n: int) -> None:
            ps = PooledSession(session=MockMCPSession())
            for _ in range(n):
                ps.mark_returned()

        result = verify_bounds(mark_n_times, SIZES, expected="O(n)", tolerance=0.5)
        assert result.passes, result.message


class TestDequeOperationsTimeComplexity:
    """Pool uses deque internally — verify O(1) append/popleft."""

    def test_deque_append_popleft_is_constant(self):
        """N append + popleft cycles should be O(n) total."""

        def deque_ops(n: int) -> None:
            q: deque[PooledSession] = deque()
            sessions = [PooledSession(session=MockMCPSession()) for _ in range(min(n, 50))]
            for i in range(n):
                ps = sessions[i % len(sessions)]
                q.append(ps)
                q.popleft()

        result = verify_bounds(deque_ops, SIZES, expected="O(n)", tolerance=0.6)
        assert result.passes, result.message


class TestAffinityMapTimeComplexity:
    """Affinity map (dict) lookups should be O(1) per operation."""

    def test_affinity_map_lookup_is_constant(self):
        """N lookups in an affinity map should be O(n) total."""

        def map_lookups(n: int) -> None:
            affinity_map: dict[str, str] = {}
            for i in range(min(n, 100)):
                affinity_map[f"key-{i}"] = f"session-{i}"
            for i in range(n):
                _ = affinity_map.get(f"key-{i % 100}")

        result = verify_bounds(map_lookups, SIZES, expected="O(n)", tolerance=0.5)
        assert result.passes, result.message


class TestDebugSnapshotTimeComplexity:
    """debug_snapshot() should be O(n) where n is the number of sessions."""

    def test_debug_snapshot_is_linear(self):
        """Building debug snapshot for n sessions should be O(n)."""

        def snapshot_n_sessions(n: int) -> None:
            sessions = {f"id-{i}": PooledSession(session=MockMCPSession()) for i in range(n)}
            active = set(list(sessions.keys())[:n // 2])
            result = []
            for ps in sessions.values():
                state = "active" if ps.session_id in active else "idle"
                result.append({
                    "session_id": ps.session_id,
                    "state": state,
                    "age_s": round(ps.age_s, 2),
                    "idle_s": round(ps.idle_s, 2),
                    "borrow_count": ps.borrow_count,
                    "affinity_key": ps.affinity_key,
                })

        result = verify_bounds(snapshot_n_sessions, SMALL_SIZES, expected="O(n)", tolerance=0.8)
        assert result.passes, result.message


# ═══════════════════════════════════════════════════════════════
# SPACE COMPLEXITY TESTS
# ═══════════════════════════════════════════════════════════════


class TestSessionSpaceComplexity:
    """Pool data structures should have O(n) space complexity."""

    @staticmethod
    def _peak_memory(func, n: int) -> int:
        tracemalloc.start()
        func(n)
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        return peak

    def test_session_list_space_is_linear(self):
        """Storing n sessions should use O(n) memory."""

        def create_session_list(n: int) -> None:
            sessions = []
            for _ in range(n):
                sessions.append(PooledSession(session=MockMCPSession()))

        small_peak = self._peak_memory(create_session_list, 100)
        large_peak = self._peak_memory(create_session_list, 2000)
        assert large_peak > small_peak
        assert large_peak < (small_peak * 40)

    def test_deque_space_is_linear(self):
        """Deque holding n sessions should use O(n) memory."""

        def create_deque(n: int) -> None:
            q: deque[PooledSession] = deque()
            for _ in range(n):
                q.append(PooledSession(session=MockMCPSession()))

        small_peak = self._peak_memory(create_deque, 100)
        large_peak = self._peak_memory(create_deque, 2000)
        assert large_peak > small_peak
        assert large_peak < (small_peak * 40)

    def test_metrics_snapshot_space_is_constant(self):
        """Snapshot dict size should not grow with counter values."""

        def snapshot_with_large_counters(n: int) -> None:
            metrics = PoolMetrics()
            metrics.borrow_count = n
            metrics.cache_hits = n
            metrics.sessions_created = n
            snapshot = metrics.snapshot()  # noqa: F841

        small_peak = self._peak_memory(snapshot_with_large_counters, 100)
        large_peak = self._peak_memory(snapshot_with_large_counters, 100000)
        assert large_peak <= (small_peak * 2)

    def test_affinity_map_space_is_linear(self):
        """Affinity map holding n entries should use O(n) memory."""

        def create_affinity_map(n: int) -> None:
            m: dict[str, str] = {}
            for i in range(n):
                m[f"key-{i}"] = f"session-{i}"

        small_peak = self._peak_memory(create_affinity_map, 100)
        large_peak = self._peak_memory(create_affinity_map, 2000)
        assert large_peak > small_peak
        assert large_peak < (small_peak * 40)


# ═══════════════════════════════════════════════════════════════
# DECORATOR-STYLE COMPLEXITY CONTRACTS (using @assert_complexity)
# ═══════════════════════════════════════════════════════════════


class TestDecoratorComplexityContracts:
    """Use bigocheck @assert_complexity decorator for declarative contracts."""

    def test_linear_session_creation_contract(self):
        """Declarative contract: session creation is O(n)."""

        @assert_complexity("O(n)", sizes=SMALL_SIZES)
        def create_n_sessions(n: int) -> None:
            for _ in range(n):
                PooledSession(session=MockMCPSession())

        create_n_sessions(100)  # First call triggers benchmark

    def test_linear_cache_set_contract(self):
        """Declarative contract: cache set is O(n) for n calls."""

        @assert_complexity("O(n)", sizes=SIZES)
        def set_cache_n_times(n: int) -> None:
            cache = ToolCache(ttl_s=3600)
            for i in range(n):
                cache.set(f"val_{i}")

        set_cache_n_times(100)  # First call triggers benchmark

    def test_linear_affinity_map_contract(self):
        """Declarative contract: affinity map lookups are O(n) for n ops."""

        @assert_complexity("O(n)", sizes=SIZES)
        def lookup_n_times(n: int) -> None:
            m = {f"k-{i}": f"v-{i}" for i in range(100)}
            for i in range(n):
                m.get(f"k-{i % 100}")

        lookup_n_times(100)
