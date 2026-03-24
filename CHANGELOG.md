# Changelog

## 1.0.0 - 2026-03-23

- **Adaptive Pool Sizing** (`AutoScalerConfig`): Background auto-scaler that monitors
  EWMA borrow wait time and utilization ratio to dynamically scale pool size up/down
  with hysteresis cooldown.
- **Multi-Endpoint Pool Manager** (`MCPPoolManager`): Manage multiple named pools
  with routing strategies — `round_robin`, `failover`, `least_connections`.
  Aggregated metrics and debug snapshots across all endpoints.
- **Per-Tenant Concurrency Caps** (`TenantLimiterConfig`): Prevent noisy-tenant
  starvation with per-key semaphore limits. Tenant key extracted from headers
  or affinity key.
- **Rate Limiting** (`RateLimiterConfig`, `TokenBucketLimiter`): Token-bucket
  rate limiter with burst support, server throttle awareness (`report_throttled`),
  and async-safe operation.
- New event hooks: `on_rate_limited`, `on_autoscale`.
- New metrics: `rate_limit_waits`, `rate_limit_rejects`, `tenant_rejects`,
  `autoscale_ups`, `autoscale_downs`.
- Exported: `MCPPoolManager`, `RateLimiterConfig`, `TokenBucketLimiter`,
  `TenantLimiter`, `TenantLimiterConfig`.

## 0.4.0 - 2026-03-23

- Added OAuth 2.1 support with PKCE (`OAuthConfig`, `OAuthProvider`) via `mcpool[oauth]` extra.
  - OIDC discovery, background token refresh, circuit breaker integration.
- Added custom health probe hooks (`health_probe`, `warmup_hook`) in `PoolConfig`.
  - Replace default `list_tools()` ping with custom readiness checks.
  - Run per-session setup after `initialize()` via warmup hook.
- Added tool schema change detection in `ToolCache`.
  - Hash-based comparison detects tool additions/removals/modifications.
  - New `on_schema_changed` event hook emitted on schema changes.
- Added `OAuthConfig`, `OAuthProvider`, `HealthProbe`, `WarmupHook` to public API.

## 0.3.0 - 2026-03-23

- Added `transport_factory` config for custom transport creation (e.g. `aws_iam_streamablehttp_client`).
- Added `auth_provider` config for dynamic/rotating auth (SigV4, IAM, OAuth tokens).
- Per-request headers now propagate to the underlying HTTP transport, not just stored on the session.
- Added `pool.call_tool()` convenience one-liner for the borrow→call→return pattern.
- Added `pool.langchain_tools()` for LangChain `Tool` integration via `mcpool[langchain]` extra.
- Added `pool.wait_ready()` / `pool.is_ready` for health-check readiness gating.
- Added `pool.resize(min=..., max=...)` for runtime pool capacity adjustment.
- Added `pool.session(affinity_key="...")` for sticky session routing.
- Added `graceful_degradation` config — ephemeral fallback with background recovery on startup failure.
- Added `pool.metrics.publish(namespace="...")` CloudWatch publisher via `mcpool[aws]` extra.
- Added `pool.metrics.to_prometheus()` for Prometheus-compatible metrics export.
- Added `pool.debug_snapshot()` for per-session introspection.

## 0.2.0 - 2026-03-22

- Added single-flight `list_tools()` refresh with cache refresh and waiter metrics.
- Added session creation retry/backoff, circuit breaker protection, and separate `borrow_timeout_s`.
- Added `pool.try_session()` and proactive background recycling for near-expiry idle sessions.
- Added optional OpenTelemetry integration plus event hooks for core lifecycle events.
- Added benchmark tests, Hypothesis fuzz tests, and a mkdocs-based documentation site.
