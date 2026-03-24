# Author: gadwant
"""
Per-tenant concurrency limiter.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

logger = logging.getLogger("mcpool")


@dataclass(frozen=True)
class TenantLimiterConfig:
    """
    Configuration for per-tenant concurrency caps.

    Attributes:
        max_concurrent_per_tenant: Maximum concurrent borrows per tenant key.
        tenant_key_header: If set, extract the tenant key from this header
            name in per-request headers.  Falls back to ``affinity_key``.
    """

    max_concurrent_per_tenant: int = 5
    tenant_key_header: str | None = None

    def __post_init__(self) -> None:
        if self.max_concurrent_per_tenant < 1:
            raise ValueError(
                f"max_concurrent_per_tenant must be >= 1, "
                f"got {self.max_concurrent_per_tenant}"
            )


class TenantLimiter:
    """
    Per-tenant concurrency limiter using per-key semaphores.

    Tracks active tenant counts and rejects requests when a tenant
    exceeds its concurrency cap.
    """

    def __init__(self, config: TenantLimiterConfig) -> None:
        self._max = config.max_concurrent_per_tenant
        self._header = config.tenant_key_header
        self._semaphores: dict[str, asyncio.Semaphore] = {}
        self._active_counts: dict[str, int] = {}
        self._reject_count = 0

    @property
    def reject_count(self) -> int:
        """Total number of rejected tenant requests."""
        return self._reject_count

    def resolve_tenant_key(
        self,
        headers: dict[str, str] | None,
        affinity_key: str | None,
    ) -> str | None:
        """
        Extract the tenant key from headers or affinity key.

        Returns ``None`` if no tenant key can be resolved (no limiting applied).
        """
        if self._header and headers:
            key = headers.get(self._header)
            if key:
                return key
        return affinity_key

    async def acquire(self, tenant_key: str) -> bool:
        """
        Try to acquire a slot for the given tenant.

        Returns ``True`` if acquired, ``False`` if the tenant is at capacity.
        """
        if tenant_key not in self._semaphores:
            self._semaphores[tenant_key] = asyncio.Semaphore(self._max)
            self._active_counts[tenant_key] = 0

        sem = self._semaphores[tenant_key]
        if sem.locked():
            self._reject_count += 1
            return False

        await sem.acquire()
        self._active_counts[tenant_key] = (
            self._active_counts.get(tenant_key, 0) + 1
        )
        return True

    def release(self, tenant_key: str) -> None:
        """Release a slot for the given tenant."""
        sem = self._semaphores.get(tenant_key)
        if sem is not None:
            sem.release()
            count = self._active_counts.get(tenant_key, 1)
            self._active_counts[tenant_key] = max(0, count - 1)

    def active_count(self, tenant_key: str) -> int:
        """Return the number of active borrows for a tenant."""
        return self._active_counts.get(tenant_key, 0)

    def tenant_snapshot(self) -> dict[str, int]:
        """Return a snapshot of active counts per tenant."""
        return {k: v for k, v in self._active_counts.items() if v > 0}

    def cleanup_idle(self) -> int:
        """
        Remove semaphores for tenants with zero active sessions.

        Returns the number of tenants cleaned up.
        """
        idle_keys = [
            k for k, v in self._active_counts.items() if v <= 0
        ]
        for k in idle_keys:
            self._semaphores.pop(k, None)
            self._active_counts.pop(k, None)
        return len(idle_keys)

    def reset(self) -> None:
        """Reset all state."""
        self._semaphores.clear()
        self._active_counts.clear()
        self._reject_count = 0
