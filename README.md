# mcpool

[![PyPI version](https://img.shields.io/pypi/v/mcp-pool.svg)](https://pypi.org/project/mcp-pool/)
[![PyPI Downloads](https://static.pepy.tech/personalized-badge/mcp-pool?period=total&units=INTERNATIONAL_SYSTEM&left_color=BLACK&right_color=GREEN&left_text=downloads)](https://pepy.tech/projects/mcp-pool)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)
[![Tests](https://github.com/adwantg/mcp-pool/actions/workflows/ci.yml/badge.svg)](https://github.com/adwantg/mcp-pool/actions)

Async connection pool for Model Context Protocol (MCP) client sessions. `mcpool` keeps sessions warm, reuses them across requests, collapses concurrent `tools/list` refreshes, and hardens pool behavior with retries, a circuit breaker, proactive recycling, custom transports, dynamic auth, and optional OpenTelemetry hooks.

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
pip install "mcp-pool[otel]"       # OpenTelemetry spans/metrics
pip install "mcp-pool[aws]"        # CloudWatch metrics publishing
pip install "mcp-pool[langchain]"  # LangChain Tool integration
pip install "mcp-pool[oauth]"      # OAuth 2.1 with PKCE support
pip install "mcp-pool[docs]"       # mkdocs documentation
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
        # Wait for pool readiness
        await pool.wait_ready(timeout_s=10)

        # Borrow a session
        async with pool.session(headers={"X-Request-ID": "req-123"}) as session:
            result = await session.call_tool("my_tool", arguments={"key": "value"})
            print(result)

        # One-liner convenience
        result = await pool.call_tool("my_tool", arguments={"key": "value"})

        # Non-blocking borrow
        async with pool.try_session() as session:
            if session is not None:
                await session.call_tool("best_effort_tool")

        # Cached tool list
        tools = await pool.list_tools()
        print(f"Tools: {[tool.name for tool in tools.tools]}")
        print(pool.metrics.snapshot())


asyncio.run(main())
```

## What v1.0.0 Adds

| Area | Change |
|------|--------|
| Rate Limiting | Token-bucket rate limiter with burst support and backoff awareness |
| Adaptive Sizing | Background auto-scaler that dynamically adjusts pool capacity based on EWMA wait time and utilization |
| Tenant Caps | Provide QoS and prevent noisy neighbors with per-tenant concurrency limits |
| Multi-Endpoint | `MCPPoolManager` to manage multiple named pools with failover and load balancing |

## What v0.4.0 Adds

| Area | Change |
|------|--------|
| OAuth 2.1 | `OAuthConfig` + `OAuthProvider` with PKCE, OIDC discovery, background refresh |
| Health Probes | `health_probe` callback replaces default `list_tools()` ping |
| Warmup Hooks | `warmup_hook` runs custom setup after each session `initialize()` |
| Schema Detection | Hash-based tool schema change detection with `on_schema_changed` hook |

## What v0.3.0 Adds

| Area | Change |
|------|--------|
| AWS Auth | `auth_provider` for dynamic SigV4/IAM credentials without library forks |
| Custom Transports | `transport_factory` to plug in any transport (e.g. `aws_iam_streamablehttp_client`) |
| Per-Request Headers | Headers passed to `pool.session(headers=...)` propagate to HTTP transport |
| LangChain | `pool.langchain_tools()` returns LangChain `Tool` objects from cached definitions |
| Readiness | `pool.wait_ready()` / `pool.is_ready` for health-check gating |
| Convenience API | `pool.call_tool("name", args)` one-liner for borrow→call→return |
| CloudWatch | `pool.metrics.publish(namespace="ECC/MCPPool")` pushes to CloudWatch |
| Runtime Resize | `pool.resize(min=5, max=20)` adjusts capacity without restart |
| Session Affinity | `pool.session(affinity_key="site-1234")` for sticky routing |
| Graceful Degradation | Ephemeral fallback + background recovery on Gateway failure |
| Prometheus | `pool.metrics.to_prometheus()` for Prometheus-compatible export |
| Introspection | `pool.debug_snapshot()` for per-session diagnostics |

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
| `async with pool.session(headers=..., affinity_key=...) as session:` | Borrow a session, waiting up to `borrow_timeout_s` |
| `async with pool.try_session(headers=...) as session:` | Borrow immediately or yield `None` if no capacity is free |
| `await pool.call_tool("name", args, headers=...)` | Borrow → call → return in one line |
| `await pool.list_tools()` | Return cached tools, refreshing with single-flight behavior when stale |
| `pool.invalidate_tools_cache()` | Force the next `list_tools()` call to refresh |
| `pool.langchain_tools()` | Convert cached tools to LangChain `Tool` objects |
| `await pool.wait_ready(timeout_s=10)` | Block until `min_sessions` are warmed — returns `True`/`False` |
| `pool.is_ready` | `True` when the pool is fully warmed and usable |
| `pool.is_degraded` | `True` if in degraded (ephemeral fallback) mode |
| `await pool.resize(min_sessions=5, max_sessions=20)` | Adjust pool capacity at runtime |
| `pool.debug_snapshot()` | Per-session age, idle time, borrow count, affinity key |
| `pool.metrics.snapshot()` | Return a metrics dictionary |
| `pool.metrics.to_prometheus()` | Return Prometheus-compatible metrics dict |
| `pool.metrics.publish(namespace="ECC/MCPPool")` | Push metrics to CloudWatch |

### `MCPPoolManager`

```python
from mcpool import MCPPoolManager
manager = MCPPoolManager()
```

| Method | Description |
|--------|-------------|
| `manager.add("name", PoolConfig(...))` | Add a pool to the manager |
| `await manager.remove("name")` | Remove and shutdown a pool |
| `async with manager.session(strategy=...) as session:` | Borrow using `round_robin`, `failover`, or `least_connections` |
| `await manager.call_tool("tool", args, strategy=...)` | Borrow, call, return |
| `manager.metrics_snapshot()` | Aggregate metrics for all managed pools |
| `await manager.start() / shutdown()` | Control lifecycle for all pools |

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
| `auth` | `None` | Static auth token (Bearer) |
| `auth_provider` | `None` | Async callable returning token or header dict |
| `transport_factory` | `None` | Custom transport creation callback |
| `graceful_degradation` | `False` | Ephemeral fallback on warmup failure |
| `oauth` | `None` | `OAuthConfig` for OAuth 2.1 (mutually exclusive with `auth_provider`) |
| `warmup_hook` | `None` | Async callback run on each session after `initialize()` |
| `health_probe` | `None` | Custom health check — replaces default `list_tools()` ping |
| `rate_limit` | `None` | `RateLimiterConfig` for token-bucket rate limits |
| `autoscaler` | `None` | `AutoScalerConfig` for dynamic pool sizing |
| `tenant_limiter` | `None` | `TenantLimiterConfig` for per-tenant concurrency caps |

## Feature Deep-Dives

### Multi-Endpoint Pool Manager

`MCPPoolManager` orchestrates multiple pools across backends, supporting failover, round-robin, and least-connections routing:

```python
from mcpool import MCPPoolManager, PoolConfig

manager = MCPPoolManager()
manager.add("us-east-1", PoolConfig(endpoint="https://us-east-1.example.mcp"))
manager.add("eu-west-1", PoolConfig(endpoint="https://eu-west-1.example.mcp"))

await manager.start()

# Automatic proxying to the optimal endpoint:
# fallback, round_robin, or least_connections
result = await manager.call_tool(
    "query", 
    {"data": "xyz"},
    strategy="least_connections" 
)
```

### Rate Limiting

Apply strict or burstable global rate limits to your pool via a Token Bucket algorithm. It's safe against concurrency and can optionally react to server Throttling indicators.

```python
from mcpool import MCPPool, PoolConfig, RateLimiterConfig

pool = MCPPool(config=PoolConfig(
    endpoint="https://mcp.example.com",
    # Limit to 100 requests per second with a burst of up to 50
    rate_limit=RateLimiterConfig(
        requests_per_second=100.0,
        burst_size=50,
    )
))
```

### Adaptive Pool Sizing (Autoscaler)

Save resources by having the pool automatically `resize()` when load fluctuates.

```python
from mcpool import MCPPool, PoolConfig, AutoScalerConfig

pool = MCPPool(config=PoolConfig(
    endpoint="https://mcp.example.com",
    min_sessions=2,
    max_sessions=50,
    autoscaler=AutoScalerConfig(
        enabled=True,
        # Scale UP if average wait time drops below this threshold
        scale_up_threshold_ms=30.0,
        # Scale DOWN if sessions remain idle this long
        scale_down_idle_s=600.0,
        # Lockout period to prevent oscillation
        cooldown_s=30.0,
    )
))
```

### Per-Tenant Concurrency Caps

In multi-tenant setups, prevent one noisy tenant from starving the entire pool while providing fair quality-of-service limits.

```python
from mcpool import MCPPool, PoolConfig, TenantLimiterConfig

pool = MCPPool(config=PoolConfig(
    endpoint="https://mcp.example.com",
    tenant_limiter=TenantLimiterConfig(
        # Never let one tenant consume more than 5 parallel sessions
        max_concurrent_per_tenant=5,
        # Derive tenant key from an HTTP Header...
        tenant_key_header="X-Tenant-ID",
        # ... or it falls back to the `affinity_key`
    )
))

# Fast rejects if "TenantA" goes over their quota
async with pool.session(headers={"X-Tenant-ID": "TenantA"}) as session:
    await session.call_tool("heavy_query")
```

### Custom Transport Factory

Plug in any MCP transport without forking the library:

```python
from mcpool import MCPPool, PoolConfig

async def aws_iam_transport(endpoint: str, headers: dict[str, str]):
    """Use AWS IAM-signed Streamable HTTP client."""
    from aws_agents_mcp import aws_iam_streamablehttp_client

    transport_ctx = aws_iam_streamablehttp_client(endpoint)
    read, write, _ = await transport_ctx.__aenter__()

    from mcp import ClientSession
    session_ctx = ClientSession(read, write)
    session = await session_ctx.__aenter__()
    await session.initialize()

    return read, write, transport_ctx, session_ctx, session

pool = MCPPool(config=PoolConfig(
    endpoint="https://agentcore.us-east-1.amazonaws.com/mcp",
    transport_factory=aws_iam_transport,
))
```

### Dynamic Auth Provider (SigV4 / IAM)

Replace static tokens with dynamic credential resolution:

```python
async def sigv4_provider() -> dict[str, str]:
    """Sign requests with AWS SigV4."""
    import boto3
    from botocore.auth import SigV4Auth
    # ... signing logic ...
    return {
        "Authorization": "AWS4-HMAC-SHA256 ...",
        "X-Amz-Date": "20260323T000000Z",
        "X-Amz-Security-Token": "...",
    }

pool = MCPPool(config=PoolConfig(
    endpoint="https://gateway.example.com/mcp",
    auth_provider=sigv4_provider,
))
```

### Per-Request Headers at Transport Level

Headers are propagated to the actual HTTP request, not just stored:

```python
async with pool.session(headers={"X-Access-Token": "eyJ..."}) as session:
    # X-Access-Token is sent on the HTTP tools/call request
    result = await session.call_tool("invoke_backend_api")
```

### LangChain Integration

```python
from mcpool import MCPPool, PoolConfig
from langchain.agents import create_react_agent

async with MCPPool(config=PoolConfig(endpoint="http://...")) as pool:
    await pool.list_tools()  # Warm the cache
    tools = pool.langchain_tools()
    agent = create_react_agent(llm, tools)
```

### Pool Readiness

```python
async with MCPPool(config=config) as pool:
    # Use as a health check endpoint
    if not pool.is_ready:
        return {"status": "unhealthy"}

    # Or block until ready
    ready = await pool.wait_ready(timeout_s=30)
    if not ready:
        raise RuntimeError("Pool warmup timed out")
```

### Call Tool Convenience

```python
# Instead of:
async with pool.session() as session:
    result = await session.call_tool("my_tool", arguments={"key": "val"})

# Just:
result = await pool.call_tool("my_tool", {"key": "val"})

# With per-call headers:
result = await pool.call_tool("my_tool", {"key": "val"}, headers={"X-Trace": "abc"})
```

### Runtime Resize

```python
# Scale up during peak hours
await pool.resize(min_sessions=10, max_sessions=50)

# Scale down after peak
await pool.resize(min_sessions=2, max_sessions=10)
```

### Session Affinity

```python
# Route same tenant to same session for server-side state benefit
async with pool.session(affinity_key="tenant-42") as session:
    await session.call_tool("get_context")

# Next request with same key reuses the same session
async with pool.session(affinity_key="tenant-42") as session:
    await session.call_tool("invoke_tool")
```

### Graceful Degradation

```python
pool = MCPPool(config=PoolConfig(
    endpoint="https://gateway.example.com/mcp",
    graceful_degradation=True,
    min_sessions=5,
))
async with pool:
    # If Gateway is unreachable:
    # 1. Pool enters degraded mode
    # 2. Ephemeral per-request sessions are created
    # 3. Background recovery retries warmup
    # 4. When recovery succeeds, pool.is_degraded -> False

    async with pool.session() as session:
        await session.call_tool("my_tool")  # Works even in degraded mode
```

### CloudWatch Metrics

```python
# Push to CloudWatch
pool.metrics.publish(
    namespace="ECC/MCPPool",
    dimensions={"Environment": "production"},
    region_name="us-east-1",
)
```

### Prometheus Export

```python
prom = pool.metrics.to_prometheus()
# {"mcpool_active_sessions": 3, "mcpool_borrow_total": 42, ...}
```

### Debug Snapshot

```python
for info in pool.debug_snapshot():
    print(f"{info['session_id']}: {info['state']}, age={info['age_s']}s, "
          f"borrows={info['borrow_count']}, affinity={info['affinity_key']}")
```

### Event Hooks

`PoolConfig.event_hooks` accepts async or sync callbacks for:

- `on_session_created`
- `on_session_destroyed`
- `on_borrow`
- `on_return`
- `on_health_check_failed`
- `on_circuit_open`
- `on_circuit_close`
- `on_schema_changed`
- `on_rate_limited`
- `on_autoscale`

### OAuth 2.1 Authentication

```python
from mcpool import MCPPool, PoolConfig, OAuthConfig

pool = MCPPool(config=PoolConfig(
    endpoint="https://mcp.example.com",
    oauth=OAuthConfig(
        client_id="my-client",
        client_secret="my-secret",
        token_endpoint="https://auth.example.com/token",
        scopes=["mcp:read", "mcp:write"],
    ),
))
```

Or with OIDC discovery:

```python
pool = MCPPool(config=PoolConfig(
    endpoint="https://mcp.example.com",
    oauth=OAuthConfig(
        client_id="my-client",
        discovery_url="https://auth.example.com/.well-known/oauth-authorization-server",
    ),
))
```

### Custom Health Probes

```python
async def my_health_check(session) -> bool:
    """Custom readiness check."""
    try:
        result = await session.call_tool("health_ping")
        return result is not None
    except Exception:
        return False

pool = MCPPool(config=PoolConfig(
    endpoint="https://mcp.example.com",
    health_probe=my_health_check,
))
```

### Warmup Hooks

```python
async def warmup(session):
    """Pre-load context after session init."""
    await session.call_tool("load_context", {"scope": "global"})

pool = MCPPool(config=PoolConfig(
    endpoint="https://mcp.example.com",
    warmup_hook=warmup,
))
```

### Schema Change Detection

```python
from mcpool import MCPPool, PoolConfig, EventHooks

async def on_schema_changed(payload):
    print(f"Tool schema changed! Hash: {payload['schema_hash']}")
    # Invalidate downstream caches, re-sync agents, etc.

pool = MCPPool(config=PoolConfig(
    endpoint="https://mcp.example.com",
    event_hooks=EventHooks(on_schema_changed=on_schema_changed),
))

## Metrics

`pool.metrics.snapshot()` includes resilience, cache, and degradation fields:

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
    "degraded": False,
    "rate_limit_waits": 2,
    "rate_limit_rejects": 0,
    "tenant_rejects": 1,
    "autoscale_ups": 3,
    "autoscale_downs": 1,
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

The repository includes a mkdocs site in [`docs/`](docs/) covering:

- Quickstart
- Configuration reference
- Migration guide for `0.1.0 -> 0.2.0 -> 0.3.0 -> 0.4.0`
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
pytest tests/performance -v --no-cov
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
