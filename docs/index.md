# mcpool

`mcpool` is an async connection pool for Model Context Protocol client sessions.

It is built for MCP workloads that need:

- warm session reuse instead of connect-per-request
- cached `tools/list` responses without refresh stampedes
- safer failure handling with retries and a circuit breaker
- background health checks and lifetime recycling
- metrics and optional OpenTelemetry instrumentation

Start with the [Quickstart](quickstart.md), then move to [Configuration](configuration.md) and the [Migration Guide](migration.md) if you are upgrading from `0.1.0`.
