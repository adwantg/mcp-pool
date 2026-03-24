# Author: gadwant
"""
Unit tests for PooledSession.
"""

from __future__ import annotations

import time

from tests.conftest import MockMCPSession

from mcpool.session import PooledSession


class TestPooledSessionCreation:
    def test_has_unique_id(self, pooled_session: PooledSession):
        assert len(pooled_session.session_id) == 12

    def test_borrow_count_starts_zero(self, pooled_session: PooledSession):
        assert pooled_session.borrow_count == 0

    def test_created_at_is_set(self, pooled_session: PooledSession):
        assert pooled_session.created_at > 0


class TestPooledSessionLifecycle:
    def test_mark_borrowed(self, pooled_session: PooledSession):
        pooled_session.mark_borrowed()
        assert pooled_session.borrow_count == 1

    def test_mark_returned_clears_headers(self, pooled_session: PooledSession):
        pooled_session.extra_headers = {"X-Token": "abc"}
        pooled_session.mark_returned()
        assert pooled_session.extra_headers == {}

    def test_age_increases(self, pooled_session: PooledSession):
        time.sleep(0.01)
        assert pooled_session.age_s > 0.0

    def test_idle_time(self, pooled_session: PooledSession):
        time.sleep(0.01)
        assert pooled_session.idle_s > 0.0


class TestPooledSessionExpiry:
    def test_not_expired_when_disabled(self, pooled_session: PooledSession):
        assert pooled_session.is_expired(0) is False

    def test_not_expired_within_lifetime(self, pooled_session: PooledSession):
        assert pooled_session.is_expired(3600) is False

    def test_expired_after_lifetime(self):
        ps = PooledSession(session=MockMCPSession())
        # Fudge created_at to simulate an old session
        object.__setattr__(ps, "created_at", time.monotonic() - 100)
        assert ps.is_expired(50) is True


class TestPooledSessionHeaders:
    def test_extra_headers_default_empty(self, pooled_session: PooledSession):
        assert pooled_session.extra_headers == {}

    def test_set_extra_headers(self, pooled_session: PooledSession):
        pooled_session.extra_headers = {"Authorization": "Bearer xyz"}
        assert pooled_session.extra_headers["Authorization"] == "Bearer xyz"
