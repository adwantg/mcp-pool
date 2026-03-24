# Author: gadwant
"""
Optional CloudWatch metrics publisher.

Publishes pool metrics to AWS CloudWatch using ``boto3``.  Requires the
``mcpool[aws]`` extra (``pip install "mcpool[aws]"``).
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .metrics import PoolMetrics

logger = logging.getLogger("mcpool.cloudwatch")


class CloudWatchPublisher:
    """
    Publish :class:`PoolMetrics` to CloudWatch.

    Usage::

        publisher = CloudWatchPublisher(namespace="ECC/MCPPool")
        await publisher.publish(pool.metrics)

    Or via the convenience method::

        pool.metrics.publish(namespace="ECC/MCPPool")

    Requires ``boto3`` — install with ``pip install "mcpool[aws]"``.
    """

    def __init__(
        self,
        *,
        namespace: str = "MCPPool",
        dimensions: dict[str, str] | None = None,
        region_name: str | None = None,
    ) -> None:
        self._namespace = namespace
        self._dimensions = dimensions or {}
        self._region_name = region_name
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is None:
            try:
                import boto3
            except ImportError as exc:
                raise ImportError(
                    "boto3 is required for CloudWatch publishing.  "
                    "Install it with: pip install 'mcpool[aws]'"
                ) from exc
            kwargs: dict[str, Any] = {}
            if self._region_name:
                kwargs["region_name"] = self._region_name
            self._client = boto3.client("cloudwatch", **kwargs)
        return self._client

    def publish(self, metrics: PoolMetrics) -> None:
        """Push a snapshot of *metrics* to CloudWatch as custom metrics."""
        client = self._get_client()
        snap = metrics.snapshot()

        dims = [{"Name": k, "Value": v} for k, v in self._dimensions.items()]

        metric_data: list[dict[str, Any]] = []
        gauge_keys = {
            "active": "ActiveSessions",
            "idle": "IdleSessions",
            "total": "TotalSessions",
        }
        counter_keys = {
            "borrow_count": "BorrowCount",
            "return_count": "ReturnCount",
            "cache_hits": "CacheHits",
            "cache_misses": "CacheMisses",
            "errors": "Errors",
            "retry_attempts": "RetryAttempts",
            "health_check_failures": "HealthCheckFailures",
            "sessions_created": "SessionsCreated",
            "sessions_destroyed": "SessionsDestroyed",
            "recycled_count": "RecycledCount",
        }
        float_keys = {
            "avg_borrow_wait_s": ("AvgBorrowWaitSeconds", "Seconds"),
            "cache_hit_rate": ("CacheHitRate", "None"),
            "uptime_s": ("UptimeSeconds", "Seconds"),
        }

        for key, name in gauge_keys.items():
            metric_data.append({
                "MetricName": name,
                "Dimensions": dims,
                "Value": float(snap[key]),  # type: ignore[arg-type]
                "Unit": "Count",
            })
        for key, name in counter_keys.items():
            metric_data.append({
                "MetricName": name,
                "Dimensions": dims,
                "Value": float(snap[key]),  # type: ignore[arg-type]
                "Unit": "Count",
            })
        for key, (name, unit) in float_keys.items():
            metric_data.append({
                "MetricName": name,
                "Dimensions": dims,
                "Value": float(snap[key]),  # type: ignore[arg-type]
                "Unit": unit,
            })

        # CloudWatch allows max 1000 per PutMetricData call; we have ~16.
        try:
            client.put_metric_data(Namespace=self._namespace, MetricData=metric_data)
            logger.debug("Published %d metrics to CloudWatch/%s", len(metric_data), self._namespace)
        except Exception:
            logger.exception("Failed to publish metrics to CloudWatch")
