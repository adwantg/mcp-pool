# Migration Guide

## `0.1.0` -> `0.2.0`

`0.2.0` is a minor release focused on correctness, safety, and operational tooling.

## New Defaults and Behaviors

- Session creation now retries by default with exponential backoff.
- A circuit breaker opens after repeated session-creation failures.
- `borrow_timeout_s` is separate from `connect_timeout_s`.
- Idle sessions can be recycled proactively before hard expiry.

## New APIs

- `async with pool.try_session() as session:` for non-blocking borrows.
- `PoolConfig.event_hooks` for lifecycle callbacks.
- `PoolConfig.enable_opentelemetry` for OTel spans/metrics.

## Recommended Upgrade Steps

1. Keep your old `PoolConfig` and add `borrow_timeout_s` explicitly if you want different capacity-wait behavior.
2. Tune `retry_count`, `failure_threshold`, and `recovery_timeout_s` for your MCP endpoint.
3. If you rotate credentials aggressively, set `max_session_lifetime_s` and `recycle_window_s`.
4. If you use observability tooling, install `mcp-pool[otel]` and enable telemetry.
