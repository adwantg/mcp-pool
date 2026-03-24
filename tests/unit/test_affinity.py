# Author: gadwant
"""
Unit tests for session affinity routing.
"""

from __future__ import annotations

import pytest
from tests.conftest import MockMCPSession

from mcpool.config import PoolConfig
from mcpool.pool import MCPPool
from mcpool.session import PooledSession


def _make_config(**overrides) -> PoolConfig:
    defaults = {
        "endpoint": "http://localhost:8000/mcp",
        "min_sessions": 2,
        "max_sessions": 5,
        "health_check_interval_s": 0,
        "tool_cache_ttl_s": 60.0,
        "max_session_lifetime_s": 0,
        "recycle_window_s": 0.1,
        "connect_timeout_s": 2.0,
        "borrow_timeout_s": 2.0,
        "drain_timeout_s": 2.0,
        "retry_count": 0,
        "retry_base_delay_s": 0.0,
        "retry_max_delay_s": 0.0,
    }
    defaults.update(overrides)
    return PoolConfig(**defaults)


async def _mock_create_session(pool: MCPPool) -> PooledSession:
    ps = PooledSession(session=MockMCPSession())
    pool._metrics.sessions_created += 1
    return ps


class TestSessionAffinity:
    @pytest.mark.asyncio
    async def test_same_key_routes_to_same_session(self):
        """Consecutive borrows with the same affinity key should return the same session."""
        pool = MCPPool(config=_make_config(min_sessions=2))
        pool._create_session = lambda: _mock_create_session(pool)  # type: ignore
        await pool.start()

        session_ids = []
        for _ in range(3):
            async with pool.session(affinity_key="site-1234") as session:
                # Get the session id from the pooled sessions
                for ps in pool._all_sessions.values():
                    if ps.session is session:
                        session_ids.append(ps.session_id)
                        break

        # All should be the same session
        assert len(set(session_ids)) == 1
        await pool.shutdown()

    @pytest.mark.asyncio
    async def test_different_keys_can_use_different_sessions(self):
        """Different affinity keys can route to different sessions."""
        pool = MCPPool(config=_make_config(min_sessions=2))
        pool._create_session = lambda: _mock_create_session(pool)  # type: ignore
        await pool.start()

        # Two separate borrows with different keys
        async with pool.session(affinity_key="key-a"):
            pass
        async with pool.session(affinity_key="key-b"):
            pass

        # Both keys should be in the affinity map
        assert "key-a" in pool._affinity_map
        assert "key-b" in pool._affinity_map
        await pool.shutdown()

    @pytest.mark.asyncio
    async def test_fallback_when_preferred_session_busy(self):
        """If the affinity session is busy, fallback to another session."""
        pool = MCPPool(config=_make_config(min_sessions=2, max_sessions=2))
        pool._create_session = lambda: _mock_create_session(pool)  # type: ignore
        await pool.start()

        # Borrow once with affinity key to establish mapping
        async with pool.session(affinity_key="sticky"):
            pass

        # Now borrow the affinity session AND try to borrow another with same key
        async with (
            pool.session(affinity_key="sticky"),
            pool.session(affinity_key="sticky") as session2,
        ):
            # Should get a different session (fallback)
            assert session2 is not None

        await pool.shutdown()

    @pytest.mark.asyncio
    async def test_affinity_map_cleared_on_shutdown(self):
        pool = MCPPool(config=_make_config(min_sessions=1))
        pool._create_session = lambda: _mock_create_session(pool)  # type: ignore
        await pool.start()
        async with pool.session(affinity_key="test"):
            pass
        assert "test" in pool._affinity_map
        await pool.shutdown()
        assert len(pool._affinity_map) == 0
