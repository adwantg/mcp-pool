# Changelog

## 0.2.0 - 2026-03-22

- Added single-flight `list_tools()` refresh with cache refresh and waiter metrics.
- Added session creation retry/backoff, circuit breaker protection, and separate `borrow_timeout_s`.
- Added `pool.try_session()` and proactive background recycling for near-expiry idle sessions.
- Added optional OpenTelemetry integration plus event hooks for core lifecycle events.
- Added benchmark tests, Hypothesis fuzz tests, and a mkdocs-based documentation site.
