# Author: gadwant
"""
Optional OpenTelemetry integration.
"""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

logger = logging.getLogger("mcpool.telemetry")


class PoolTelemetry:
    """Best-effort OpenTelemetry adapter with no-op fallback."""

    def __init__(
        self,
        *,
        enabled: bool,
        metrics: Any,
        transport: str,
        endpoint: str,
    ) -> None:
        self._enabled = False
        self._metrics = metrics
        self._transport = transport
        self._endpoint = endpoint
        self._tracer: Any = None
        self._borrow_wait_histogram: Any = None
        self._errors_counter: Any = None
        self._Observation: Any = None

        if not enabled:
            return

        try:
            from opentelemetry import metrics as otel_metrics
            from opentelemetry import trace
            from opentelemetry.metrics import Observation
        except ImportError:
            logger.warning(
                "OpenTelemetry requested but opentelemetry-api is not installed; telemetry disabled"
            )
            return

        self._enabled = True
        self._tracer = trace.get_tracer("mcpool")
        meter = otel_metrics.get_meter("mcpool")
        self._Observation = Observation

        self._borrow_wait_histogram = meter.create_histogram(
            "pool.borrow_wait_seconds",
            unit="s",
            description="Borrow wait time for pool sessions",
        )
        self._errors_counter = meter.create_counter(
            "pool.errors_total",
            description="Total pool errors",
        )
        meter.create_observable_gauge(
            "pool.active_sessions",
            callbacks=[self._observe_active_sessions],
            description="Active sessions in the pool",
        )
        meter.create_observable_gauge(
            "pool.idle_sessions",
            callbacks=[self._observe_idle_sessions],
            description="Idle sessions in the pool",
        )

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    def _observe_active_sessions(self, _options: Any) -> list[Any]:
        if not self._enabled or self._Observation is None:
            return []
        return [self._Observation(self._metrics.active)]

    def _observe_idle_sessions(self, _options: Any) -> list[Any]:
        if not self._enabled or self._Observation is None:
            return []
        return [self._Observation(self._metrics.idle)]

    @asynccontextmanager
    async def span(
        self,
        name: str,
        *,
        attributes: dict[str, Any] | None = None,
    ) -> AsyncIterator[None]:
        if not self._enabled or self._tracer is None:
            yield
            return

        attrs = {"mcpool.transport": self._transport, "mcpool.endpoint": self._endpoint}
        if attributes:
            attrs.update(attributes)

        with self._tracer.start_as_current_span(name, attributes=attrs) as span:
            try:
                yield
            except Exception as exc:
                span.record_exception(exc)
                try:
                    from opentelemetry.trace import Status, StatusCode

                    span.set_status(Status(StatusCode.ERROR))
                except ImportError:
                    pass
                raise

    def record_borrow_wait(self, wait_seconds: float) -> None:
        if self._borrow_wait_histogram is not None:
            self._borrow_wait_histogram.record(wait_seconds)

    def record_error(self, kind: str) -> None:
        if self._errors_counter is not None:
            self._errors_counter.add(1, {"mcpool.error.kind": kind})
