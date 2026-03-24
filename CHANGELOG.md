# Changelog

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
