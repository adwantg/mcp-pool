# mcpool

[![PyPI version](https://img.shields.io/pypi/v/mcp-pool.svg)](https://pypi.org/project/mcp-pool/)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)
[![Tests](https://github.com/adwantg/mcp-pool/actions/workflows/ci.yml/badge.svg)](https://github.com/adwantg/mcp-pool/actions)

Async connection pool for Model Context Protocol (MCP) client sessions. `mcpool` keeps sessions warm, reuses them across requests, collapses concurrent `tools/list` refreshes, and hardens pool behavior with retries, a circuit breaker, proactive recycling, and optional OpenTelemetry hooks.

## Why mcpool

Without pooling, every MCP call pays connection setup cost:

```text
Request -> TCP connect -> TLS handshake -> MCP initialize -> tools/list -> tools/call -> close
```

With `mcpool`, warm sessions are reused:

```text
App startup -> pool.start() -> N sessions ready
Request -> pool.session() -> tools/call -> return session
Shutdown -> pool.shutdown() -> drain + close
```

That removes repeated setup work, reduces `tools/list` churn, and gives you a safer operational model around endpoint failures.

## Installation

```bash
pip install mcp-pool
```

Optional extras:

```bash
pip install "mcp-pool[otel]"
pip install "mcp-pool[docs]"
```

## Quickstart

```python
import asyncio
from mcpool import MCPPool, PoolConfig


async def main() -> None:
    config = PoolConfig(
        endpoint="http://gateway.example.com/mcp",
        transport="streamable_http",
        min_sessions=2,
        max_sessions=10,
        tool_cache_ttl_s=300,
        health_check_interval_s=30,
        max_session_lifetime_s=3600,
        recycle_window_s=60,
        borrow_timeout_s=2,
        retry_count=2,
        auth="your-api-key",
        enable_opentelemetry=True,
    )

    async with MCPPool(config=config) as pool:
        async with pool.session(headers={"X-Request-ID": "req-123"}) as session:
            result = await session.call_tool("my_tool", arguments={"key": "value"})
            print(result)

        async with pool.try_session() as session:
            if session is not None:
                await session.call_tool("best_effort_tool")

        tools = await pool.list_tools()
        print(f"Tools: {[tool.name for tool in tools.tools]}")
        print(pool.metrics.snapshot())


asyncio.run(main())
```

## What v0.2.0 Adds

| Area | Change |
|------|--------|
| Correctness | Single-flight `list_tools()` refresh to prevent cache stampedes |
| Resilience | Session creation retries with exponential backoff + jitter |
| Safety | Circuit breaker for repeated session-creation failures |
| Scheduling | Separate `borrow_timeout_s` from `connect_timeout_s` |
| API | `pool.try_session()` for non-blocking borrow attempts |
| Lifecycle | Background recycling of near-expiry idle sessions |
| Observability | Optional OpenTelemetry spans and metrics |
| Tooling | Benchmark suite, Hypothesis fuzz tests, and mkdocs documentation |

## Core API

### `MCPPool`

```python
pool = MCPPool(config=PoolConfig(endpoint="http://..."))
# or
pool = MCPPool(endpoint="http://...", min_sessions=2, max_sessions=10)
```

| Method | Description |
|--------|-------------|
| `await pool.start()` | Pre-warm `min_sessions` and start the health checker |
| `await pool.shutdown()` | Drain in-flight work and close sessions |
| `async with pool.session(headers=...) as session:` | Borrow a session, waiting up to `borrow_timeout_s` |
| `async with pool.try_session(headers=...) as session:` | Borrow immediately or yield `None` if no capacity is free |
| `await pool.list_tools()` | Return cached tools, refreshing with single-flight behavior when stale |
| `pool.invalidate_tools_cache()` | Force the next `list_tools()` call to refresh |
| `pool.metrics.snapshot()` | Return a metrics dictionary |

### `PoolConfig` Highlights

| Parameter | Default | Description |
|-----------|---------|-------------|
| `min_sessions` | `2` | Sessions to pre-warm on startup |
| `max_sessions` | `10` | Hard cap on concurrent sessions |
| `tool_cache_ttl_s` | `300.0` | TTL for cached `tools/list` responses |
| `health_check_interval_s` | `30.0` | Seconds between idle-session health sweeps |
| `max_session_lifetime_s` | `3600.0` | Hard lifetime for a session |
| `recycle_window_s` | `30.0` | Recycle idle sessions this long before lifetime expiry |
| `connect_timeout_s` | `10.0` | Timeout for a single session creation attempt |
| `borrow_timeout_s` | `connect_timeout_s` | Timeout for waiting on pool capacity |
| `retry_count` | `2` | Retries for session creation after the first failure |
| `retry_base_delay_s` | `0.1` | Base delay for exponential retry backoff |
| `retry_max_delay_s` | `2.0` | Maximum retry delay |
| `failure_threshold` | `5` | Consecutive failures before the circuit opens |
| `recovery_timeout_s` | `30.0` | Time before the circuit allows a half-open probe |
| `enable_opentelemetry` | `False` | Enable OTel spans/metrics if `opentelemetry-api` is installed |

### Event Hooks

`PoolConfig.event_hooks` accepts async or sync callbacks for:

- `on_session_created`
- `on_session_destroyed`
- `on_borrow`
- `on_return`
- `on_health_check_failed`
- `on_circuit_open`
- `on_circuit_close`

## Metrics

`pool.metrics.snapshot()` now includes the new resilience and cache fields:

```python
{
    "active": 1,
    "idle": 4,
    "total": 5,
    "borrow_count": 42,
    "avg_borrow_wait_s": 0.003,
    "return_count": 42,
    "cache_hits": 38,
    "cache_misses": 4,
    "cache_refresh_count": 4,
    "cache_waiters": 7,
    "cache_hit_rate": 0.905,
    "reconnect_count": 1,
    "retry_attempts": 2,
    "health_check_count": 120,
    "health_check_failures": 1,
    "recycled_count": 3,
    "sessions_created": 8,
    "sessions_destroyed": 3,
    "errors": 0,
    "circuit_state": "closed",
    "uptime_s": 3600.5,
}
```

## Observability

When OTel is enabled, `mcpool` emits spans for:

- `pool.borrow`
- `pool.return`
- `session.create`
- `session.close`
- `list_tools`

And OTel metrics for:

- `pool.active_sessions`
- `pool.idle_sessions`
- `pool.borrow_wait_seconds`
- `pool.errors_total`

## Documentation

The repository now includes a mkdocs site in [`docs/`](docs/) covering:

- Quickstart
- Configuration reference
- Migration guide for `0.1.0 -> 0.2.0`
- Architecture
- Deployment patterns
- Performance tuning

Build it locally with:

```bash
mkdocs serve
```

## Development

```bash
git clone https://github.com/adwantg/mcp-pool.git
cd mcp-pool
pip install -e ".[dev]"
pytest -v
pytest tests/benchmarks tests/fuzz -v --no-cov
ruff check src/ tests/
mypy src/
mkdocs build --strict
```

## License

MIT — see [LICENSE](LICENSE).

## Citation

If you use `mcpool` in research, please cite:

```bibtex
@software{adwant_mcpool_2025,
  author = {Goutam Adwant},
  title = {mcpool: Async Connection Pool for MCP Sessions},
  year = {2025},
  url = {https://github.com/adwantg/mcp-pool}
}
```
