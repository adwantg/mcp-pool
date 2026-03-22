# Author: gadwant
"""
Optional async event hooks for pool lifecycle events.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

EventPayload = dict[str, Any]
EventHook = Callable[[EventPayload], Awaitable[None] | None]


@dataclass(frozen=True)
class EventHooks:
    """
    Optional callbacks for key pool lifecycle events.

    Each callback receives a small dictionary payload describing the event.
    Callbacks may be sync or async. Exceptions are logged and swallowed by the pool.
    """

    on_session_created: EventHook | None = None
    on_session_destroyed: EventHook | None = None
    on_borrow: EventHook | None = None
    on_return: EventHook | None = None
    on_health_check_failed: EventHook | None = None
    on_circuit_open: EventHook | None = None
    on_circuit_close: EventHook | None = None
