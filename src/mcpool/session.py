# Author: gadwant
"""
PooledSession — metadata wrapper around an MCP ClientSession.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class PooledSession:
    """
    Wraps an MCP ``ClientSession`` with pool-level bookkeeping.

    The actual client session, read/write streams, and context-manager
    references are stored here so the pool can manage the full lifecycle.

    Attributes:
        session: The underlying MCP ``ClientSession``.
        session_id: Unique identifier for this pooled session.
        created_at: Monotonic timestamp when the session was created.
        last_used_at: Monotonic timestamp of the most recent borrow.
        borrow_count: Number of times this session has been borrowed.
        transport_ctx: The outer transport context manager (for cleanup).
        session_ctx: The inner session context manager (for cleanup).
        extra_headers: Per-request headers injected on the next call.
        affinity_key: Optional affinity key this session is bound to.
    """

    session: Any  # mcp.ClientSession — kept as Any to avoid hard import at dataclass level
    session_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    created_at: float = field(default_factory=time.monotonic)
    last_used_at: float = field(default_factory=time.monotonic)
    borrow_count: int = 0
    transport_ctx: Any = None  # The transport async CM
    session_ctx: Any = None  # The ClientSession async CM
    _read_stream: Any = None
    _write_stream: Any = None
    extra_headers: dict[str, str] = field(default_factory=dict)
    affinity_key: str | None = None

    @property
    def age_s(self) -> float:
        """Seconds since this session was created."""
        return time.monotonic() - self.created_at

    @property
    def idle_s(self) -> float:
        """Seconds since this session was last used."""
        return time.monotonic() - self.last_used_at

    def mark_borrowed(self) -> None:
        """Record that this session has been borrowed."""
        self.borrow_count += 1
        self.last_used_at = time.monotonic()

    def mark_returned(self) -> None:
        """Record that this session has been returned."""
        self.last_used_at = time.monotonic()
        self.extra_headers = {}

    def is_expired(self, max_lifetime_s: float) -> bool:
        """Return True if the session exceeds the max lifetime."""
        if max_lifetime_s <= 0:
            return False
        return self.age_s >= max_lifetime_s
